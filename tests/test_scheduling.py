from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scheduling.bist import BistSessionSchedule, PartialBarPolicy
from market_intelligence.scheduling.watermarks import WatermarkPlanner

ISTANBUL = ZoneInfo("Europe/Istanbul")


class BistScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schedule = BistSessionSchedule()
        self.day = date(2026, 9, 7)

    def test_45m_is_anchored_to_session_open(self) -> None:
        closes = self.schedule.bar_closes(self.day, Timeframe.M45)
        self.assertIn(datetime(2026, 9, 7, 12, 15, tzinfo=ISTANBUL), closes)
        self.assertEqual(closes[-1], datetime(2026, 9, 7, 17, 30, tzinfo=ISTANBUL))
        self.assertNotIn(datetime(2026, 9, 7, 18, 0, tzinfo=ISTANBUL), closes)

    def test_45m_partial_tail_can_only_be_explicitly_provisional(self) -> None:
        closes = self.schedule.bar_closes(
            self.day,
            Timeframe.M45,
            partial_policy=PartialBarPolicy.INCLUDE_PROVISIONAL,
        )
        self.assertEqual(closes[-1], datetime(2026, 9, 7, 18, 0, tzinfo=ISTANBUL))

    def test_daily_closes_at_session_close(self) -> None:
        self.assertEqual(
            self.schedule.bar_closes(self.day, Timeframe.D1),
            (datetime(2026, 9, 7, 18, 0, tzinfo=ISTANBUL),),
        )


class WatermarkPlannerTests(unittest.TestCase):
    def test_missed_bars_are_replayed_after_watermark(self) -> None:
        schedule = BistSessionSchedule()
        closes = schedule.bar_closes(date(2026, 9, 7), Timeframe.H1)
        due = WatermarkPlanner().due(
            closed_bar_times=closes,
            watermark=datetime(2026, 9, 7, 12, 0, tzinfo=ISTANBUL),
            evaluation_time=datetime(2026, 9, 7, 15, 10, tzinfo=ISTANBUL),
        )
        self.assertEqual(
            due,
            (
                datetime(2026, 9, 7, 13, 0, tzinfo=ISTANBUL),
                datetime(2026, 9, 7, 14, 0, tzinfo=ISTANBUL),
                datetime(2026, 9, 7, 15, 0, tzinfo=ISTANBUL),
            ),
        )


if __name__ == "__main__":
    unittest.main()
