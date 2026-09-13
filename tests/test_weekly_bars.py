import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar
from market_intelligence.market_data.canonicalizer import Canonicalizer
from market_intelligence.scheduling.xist import ScheduledBarPlanner

TZ = ZoneInfo("Europe/Istanbul")


class Calendar:
    version = "fixture"

    def sessions(self, start, end):
        return tuple(
            start + timedelta(days=i)
            for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5
            and start + timedelta(days=i) != date(2026, 9, 8)
        )


class WeeklyTests(unittest.TestCase):
    def bars(self):
        return tuple(
            CanonicalBar(
                datetime.combine(d, datetime.min.time(), TZ).replace(hour=10),
                datetime.combine(d, datetime.min.time(), TZ).replace(hour=18),
                10,
                12,
                9,
                11,
                100,
            )
            for d in Calendar().sessions(date(2026, 9, 7), date(2026, 9, 11))
        )

    @patch("market_intelligence.scheduling.xist.ExchangeCalendarsXist", Calendar)
    def test_holiday_week_aggregates_all_sessions(self):
        result = Canonicalizer()._resample(self.bars(), Timeframe.D1, Timeframe.W1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].volume, 400)
        self.assertEqual(result[0].close_time.day, 11)

    @patch("market_intelligence.scheduling.xist.ExchangeCalendarsXist", Calendar)
    def test_missing_or_partial_week_is_excluded(self):
        for bars in (self.bars()[:-1], self.bars()[1:], self.bars()[::2]):
            self.assertEqual(Canonicalizer()._resample(bars, Timeframe.D1, Timeframe.W1), ())

    def test_in_progress_week_not_scheduled(self):
        result = ScheduledBarPlanner(Calendar()).due(
            timeframe=Timeframe.W1,
            evaluation_time=datetime(2026, 9, 10, 18, 30, tzinfo=TZ),
            watermark=None,
        )
        self.assertEqual(result[-1], datetime(2026, 9, 4, 18, tzinfo=TZ))

    def test_friday_after_close_is_scheduled(self):
        result = ScheduledBarPlanner(Calendar()).due(
            timeframe=Timeframe.W1,
            evaluation_time=datetime(2026, 9, 11, 18, 30, tzinfo=TZ),
            watermark=None,
        )
        self.assertEqual(result[-1], datetime(2026, 9, 11, 18, tzinfo=TZ))
