from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.atc_ephemeral_intersections import from_verified_digests
from scripts.atc_ephemeral_schedule import select_timeframes

IST = ZoneInfo("Europe/Istanbul")


class WeekdayCalendar:
    def sessions(self, start: date, end: date):
        return tuple(
            start + timedelta(days=i)
            for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5
        )


class EphemeralScheduleTests(unittest.TestCase):
    def test_friday_eod_has_all_eight_timeframes(self):
        actual = select_timeframes(
            datetime(2026, 10, 16, 18, 30, tzinfo=IST),
            calendar=WeekdayCalendar(),
        )
        self.assertEqual(
            actual, ("15m", "30m", "45m", "1h", "2h", "4h", "1d", "1wk"),
        )

    def test_thursday_eod_excludes_unclosed_week(self):
        actual = select_timeframes(
            datetime(2026, 10, 15, 18, 30, tzinfo=IST),
            calendar=WeekdayCalendar(),
        )
        self.assertEqual(
            actual, ("15m", "30m", "45m", "1h", "2h", "4h", "1d"),
        )

    def test_intraday_schedules_only_closed_interval(self):
        frames = select_timeframes(
            datetime(2026, 10, 16, 10, 22, tzinfo=IST),
            calendar=WeekdayCalendar(),
        )
        self.assertEqual(frames, ("15m",))
        self.assertEqual(
            select_timeframes(
                datetime(2026, 10, 17, 11, 22, tzinfo=IST),
                calendar=WeekdayCalendar(),
            ), (),
        )

    def test_manual_all_and_timezone_validation(self):
        self.assertEqual(
            len(select_timeframes(
                datetime(2026, 10, 16, 14, tzinfo=IST), all_scans=True,
            )), 8,
        )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            select_timeframes(datetime(2026, 10, 16, 14))


class StrictIntersectionDigestTests(unittest.TestCase):
    def write(self, folder, tf, close, entries, covered=600):
        path = Path(folder) / f"{tf}.json"
        path.write_text(json.dumps({
            "schema": "atc-verified-timeframe-digest-v1",
            "timeframe": tf,
            "bar_close": close.isoformat(),
            "covered": covered,
            "universe": 630,
            "entries": entries,
        }), encoding="utf-8")
        return path

    def test_only_two_same_direction_rules_per_timeframe_are_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            close = datetime(2026, 10, 16, 15, tzinfo=IST)
            rows = [
                {"symbol": "ASELS", "scanner": "signal.macd_positive_cross", "direction": "bullish"},
                {"symbol": "ASELS", "scanner": "technical.volume_spike", "direction": "bullish"},
            ]
            first = self.write(folder, "15m", close, rows)
            second = self.write(folder, "1h", close, rows)
            ranked, closings, coverage = from_verified_digests(
                [first, second], now=close + timedelta(hours=1),
                expected_timeframes=("15m", "1h"),
            )
            self.assertEqual(len(ranked), 1)
            self.assertEqual(ranked[0]["symbol"], "ASELS")
            self.assertEqual(ranked[0]["timeframe_count"], 2)
            self.assertEqual(set(closings), {"15m", "1h"})
            self.assertEqual(coverage, {"15m": 600, "1h": 600})

    def test_stale_low_coverage_and_missing_timeframes_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            now = datetime(2026, 10, 16, 18, tzinfo=IST)
            first = self.write(folder, "15m", now, [], covered=566)
            with self.assertRaisesRegex(ValueError, "Insufficient"):
                from_verified_digests([first], now=now)
            first = self.write(folder, "15m", now, [], covered=590)
            with self.assertRaisesRegex(ValueError, "Missing"):
                from_verified_digests(
                    [first], now=now, expected_timeframes=("15m", "1d"),
                )
            second = self.write(
                folder, "1d", now - timedelta(days=3), [], covered=600,
            )
            with self.assertRaisesRegex(ValueError, "Stale"):
                from_verified_digests([first, second], now=now)
            second = self.write(folder, "1d", now, [], covered=600)
            ranked, *_ = from_verified_digests([first, second], now=now)
            self.assertEqual(ranked, [])
            # An incomplete provider must not report yesterday's EOD bar as
            # today's verified intersection, even if its age is <48 hours.
            second = self.write(
                folder, "1d", now - timedelta(days=1), [], covered=600,
            )
            with self.assertRaisesRegex(ValueError, "earlier trading session"):
                from_verified_digests(
                    [first, second], now=now,
                    expected_timeframes=("15m", "1d"),
                )


if __name__ == "__main__":
    unittest.main()
