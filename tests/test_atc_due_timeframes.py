from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.atc_due_timeframes import due_timeframes

IST = ZoneInfo("Europe/Istanbul")


class WeekdayCalendar:
    def sessions(self, start: date, end: date):
        current = start
        result = []
        while current <= end:
            if current.weekday() < 5:
                result.append(current)
            current += timedelta(days=1)
        return tuple(result)


class DueTimeframeTests(unittest.TestCase):
    def test_only_current_completed_intraday_bars(self):
        cal = WeekdayCalendar()
        self.assertEqual(due_timeframes(datetime(2026, 10, 15, 10, 15, tzinfo=IST), cal),
                         ("15m",))
        self.assertEqual(due_timeframes(datetime(2026, 10, 15, 10, 45, tzinfo=IST), cal),
                         ("15m", "45m"))
        self.assertEqual(due_timeframes(datetime(2026, 10, 15, 12, 0, tzinfo=IST), cal),
                         ("15m", "30m", "1h", "2h"))

    def test_post_auction_final_pass_and_weekly_only_last_session(self):
        cal = WeekdayCalendar()
        thursday = due_timeframes(datetime(2026, 10, 15, 18, 30, tzinfo=IST), cal)
        friday = due_timeframes(datetime(2026, 10, 16, 18, 30, tzinfo=IST), cal)
        self.assertEqual(thursday, ("15m", "30m", "1h", "2h", "4h", "1d"))
        self.assertEqual(friday, (*thursday, "1wk"))
        self.assertEqual(due_timeframes(datetime(2026, 10, 17, 18, 30, tzinfo=IST), cal), ())
        self.assertEqual(due_timeframes(datetime(2026, 10, 15, 9, 45, tzinfo=IST), cal), ())


if __name__ == "__main__":
    unittest.main()
