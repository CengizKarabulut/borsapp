from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scheduling.xist import ScheduledBarPlanner

ISTANBUL = ZoneInfo("Europe/Istanbul")


class FakeCalendar:
    version = "fixture-calendar-v1"

    def sessions(self, start: date, end: date) -> tuple[date, ...]:
        holiday = date(2026, 9, 8)
        result = []
        cursor = start
        while cursor <= end:
            if cursor.weekday() < 5 and cursor != holiday:
                result.append(cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)
        return tuple(result)


class ScheduledBarPlannerTests(unittest.TestCase):
    def test_holiday_is_never_scheduled_and_missed_session_is_replayed(self) -> None:
        due = ScheduledBarPlanner(FakeCalendar()).due(
            timeframe=Timeframe.D1,
            watermark=datetime(2026, 9, 7, 18, 0, tzinfo=ISTANBUL),
            evaluation_time=datetime(2026, 9, 9, 18, 5, tzinfo=ISTANBUL),
        )
        self.assertEqual(
            due,
            (datetime(2026, 9, 9, 18, 0, tzinfo=ISTANBUL),),
        )

    def test_intraday_due_closes_are_anchored_to_session_open(self) -> None:
        due = ScheduledBarPlanner(FakeCalendar(), maximum_lookback_days=1).due(
            timeframe=Timeframe.M45,
            watermark=datetime(2026, 9, 9, 11, 30, tzinfo=ISTANBUL),
            evaluation_time=datetime(2026, 9, 9, 12, 16, tzinfo=ISTANBUL),
        )
        self.assertEqual(
            due,
            (datetime(2026, 9, 9, 12, 15, tzinfo=ISTANBUL),),
        )


if __name__ == "__main__":
    unittest.main()
