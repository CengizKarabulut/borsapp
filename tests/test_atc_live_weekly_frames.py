from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.providers import ProviderBar, ProviderFrame, TimestampKind
from scripts import atc_live_weekly_frames as weekly
from scripts.atc_live_snapshot_frames import prepare_frame

IST = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 21, 11, tzinfo=IST)
MEMBER = SimpleNamespace(instrument_id="BIST:ASELS", symbol="ASELS", provider_symbol="ASELS", market="BIST")
SESSIONS = frozenset((date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 16),
    date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 23)))


def source(*, starts=None, partial=False):
    starts = starts or [datetime(2026, 10, 12, 9, tzinfo=IST), datetime(2026, 10, 19, 9, tzinfo=IST)]
    return ProviderFrame(provider="native_weekly_fixture", provider_symbol="BIST:ASELS", timeframe=Timeframe.W1,
        timestamp_kind=TimestampKind.OPEN, timestamp_timezone="Europe/Istanbul",
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        bars=tuple(ProviderBar(stamp, 100 + index, 112 + index, 91 + index,
            105 + index, 1000 + index) for index, stamp in enumerate(starts)), last_bar_is_partial=partial)


class Vendor:
    def __init__(self, raw):
        self.raw = raw
        self.requests = []

    def fetch(self, request):
        raise AssertionError("A native week must never be assembled from daily bars")

    def fetch_native_weekly(self, request):
        self.requests.append(request)
        return self.raw


class NativeWeeklyFrameTests(unittest.TestCase):
    def setUp(self):
        calendar = patch.object(weekly, "_session_days", return_value=SESSIONS)
        calendar.start()
        self.addCleanup(calendar.stop)

    def test_actual_mutable_week_is_kept_without_claiming_fresh_last_trade_or_confirmation(self):
        raw = source(partial=True)
        vendor = Vendor(raw)
        frame, meta = prepare_frame(vendor, MEMBER, "1wk", now=NOW)
        self.assertEqual(frame.timeframe, Timeframe.W1)
        self.assertFalse(frame.is_partial)  # Only formula evaluation sees this hypothetical close.
        self.assertEqual(frame.quality, weekly.QUALITY)
        self.assertEqual(frame.bars[-1].open_time, raw.bars[-1].timestamp)
        self.assertEqual(frame.bars[-1].close_time, raw.bars[-1].timestamp + timedelta(days=7))
        self.assertEqual((frame.bars[-1].open, frame.bars[-1].high, frame.bars[-1].low,
            frame.bars[-1].close, frame.bars[-1].volume), (101, 113, 92, 106, 1001))
        self.assertEqual(meta["expected_market_session"], "2026-10-21")
        self.assertEqual(meta["source_week"], "2026-10-19")
        self.assertEqual(meta["source_grid"], weekly.NATIVE_WEEKLY_GRID)
        self.assertTrue(meta["usable_latest"])
        self.assertTrue(meta["weekly_cohort_matches"])
        self.assertTrue(meta["nominally_open"])
        self.assertTrue(meta["provider_partial_flag"])
        self.assertIsNone(meta["actual_bar_is_open"])
        self.assertIsNone(meta["latest_target_complete"])
        self.assertIsNone(meta["last_trade_at"])
        self.assertIsNone(meta["price_delay_seconds"])
        self.assertIsNone(meta["latest_native_close_age_seconds"])
        self.assertFalse(meta["persisted"])
        self.assertEqual(meta["freshness_basis"], "calendar_week_membership_not_last_trade_time")
        self.assertEqual(vendor.requests[0].timeframe, Timeframe.W1)
        self.assertTrue(raw.last_bar_is_partial)

    def test_holiday_tuesday_actual_anchor_is_preserved_with_nominal_seven_day_end(self):
        sessions = frozenset((date(2026, 10, 12), date(2026, 10, 16), date(2026, 10, 20), date(2026, 10, 21)))
        raw = source(starts=[datetime(2026, 10, 20, 9, tzinfo=IST)])
        with patch.object(weekly, "_session_days", return_value=sessions):
            frame, meta = prepare_frame(Vendor(raw), MEMBER, "1wk", now=NOW)
        self.assertEqual(frame.bars[-1].open_time, datetime(2026, 10, 20, 9, tzinfo=IST))
        self.assertEqual(frame.bars[-1].close_time, datetime(2026, 10, 27, 9, tzinfo=IST))
        self.assertEqual(meta["expected_week"], "2026-10-19")
        self.assertEqual(meta["expected_bucket_open"], "2026-10-20T09:00:00+03:00")
        self.assertTrue(meta["usable_latest"])

    def test_instrument_first_trade_later_in_week_is_not_relabelled_or_gap_filled(self):
        raw = source(starts=[datetime(2026, 10, 20, 9, tzinfo=IST)])
        frame, meta = prepare_frame(Vendor(raw), MEMBER, "1wk", now=NOW)
        self.assertEqual(len(frame.bars), 1)
        self.assertEqual(frame.bars[0].open_time, raw.bars[0].timestamp)
        self.assertEqual(meta["expected_bucket_open"], "2026-10-19T09:00:00+03:00")
        self.assertTrue(meta["usable_latest"])  # Week membership; never quote-age confirmation.

    def test_real_holiday_week_label_is_preserved_when_week_contains_real_sessions(self):
        # Actual 600-bar ASELS W1 source: label 2019-07-15, while the exchange
        # holiday calendar has real sessions 16-19 July. It is a period label.
        sessions = SESSIONS | frozenset((date(2019, 7, 16), date(2019, 7, 17), date(2019, 7, 18), date(2019, 7, 19)))
        starts = [datetime(2019, 7, 15, 9, tzinfo=IST), datetime(2026, 10, 19, 9, tzinfo=IST)]
        with patch.object(weekly, "_session_days", return_value=sessions):
            frame, meta = prepare_frame(Vendor(source(starts=starts)), MEMBER, "1wk", now=NOW)
        self.assertEqual(frame.bars[0].open_time, starts[0])
        self.assertEqual(frame.bars[0].close_time, starts[0] + timedelta(days=7))
        self.assertEqual(meta["calendar_non_session_week_labels"], ["2019-07-15"])
        self.assertTrue(meta["usable_latest"])

    def test_week_without_any_real_exchange_session_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-session week label"):
            prepare_frame(Vendor(source(starts=[datetime(2026, 9, 28, 9, tzinfo=IST)])), MEMBER, "1wk", now=NOW)

    def test_stale_previous_week_still_calculates_actual_history_without_becoming_current(self):
        raw = source(starts=[datetime(2026, 10, 12, 9, tzinfo=IST)])
        frame, meta = prepare_frame(Vendor(raw), MEMBER, "1wk", now=NOW)
        self.assertEqual(frame.bars[-1].close, 105)
        self.assertFalse(meta["usable_latest"])
        self.assertEqual(meta["status"], "stale_previous_week")

    def test_weekend_and_preopen_cohort_use_latest_real_started_market_session(self):
        for now, session, week in (
            (NOW.replace(day=24, hour=15), "2026-10-23", "2026-10-19"),
            (NOW.replace(day=19, hour=8), "2026-10-16", "2026-10-12"),
        ):
            raw = source(starts=[datetime.fromisoformat(week).replace(hour=9, tzinfo=IST)])
            _, meta = prepare_frame(Vendor(raw), MEMBER, "1wk", now=now)
            self.assertEqual(meta["expected_market_session"], session)
            self.assertEqual(meta["expected_week"], week)
            self.assertTrue(meta["usable_latest"])

    def test_new_native_week_before_report_session_is_not_current_previous_week(self):
        _, meta = prepare_frame(Vendor(source()), MEMBER, "1wk", now=NOW.replace(day=19, hour=9, minute=30))
        self.assertFalse(meta["usable_latest"])
        self.assertEqual(meta["status"], "native_week_before_report_session")

    def test_receipt_clock_crossing_week_boundary_rechecks_real_expected_week(self):
        observations = iter((NOW.replace(day=19, hour=9, minute=44), NOW.replace(day=19, hour=9, minute=46)))
        raw = source(starts=[datetime(2026, 10, 12, 9, tzinfo=IST)])
        _, meta = prepare_frame(Vendor(raw), MEMBER, "1wk", now=lambda: next(observations))
        self.assertEqual(meta["expected_market_session"], "2026-10-19")
        self.assertFalse(meta["usable_latest"])

    def test_calendar_week_identity_uses_istanbul_date_and_rejects_naive_time(self):
        self.assertEqual(weekly.calendar_week_identity(date(2026, 10, 21)), "2026-10-19")
        self.assertEqual(weekly.calendar_week_identity(datetime.fromisoformat("2026-10-18T23:00:00+00:00")), "2026-10-19")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            weekly.calendar_week_identity(datetime(2026, 10, 19))

    def test_no_daily_fallback_and_no_monthly_broadening(self):
        with self.assertRaisesRegex(ValueError, "explicit native-weekly"):
            prepare_frame(SimpleNamespace(fetch=lambda request: source()), MEMBER, "1wk", now=NOW)
        with self.assertRaises(ValueError):
            prepare_frame(Vendor(source()), MEMBER, "1mo", now=NOW)

    def test_wrong_instrument_timeframe_and_timestamp_kind_are_rejected(self):
        for raw, reason in (
            (replace(source(), provider_symbol="ALVES"), "different instrument"),
            (replace(source(), timeframe=Timeframe.D1), "explicit W1"),
            (replace(source(), timestamp_kind=TimestampKind.CLOSE), "explicit W1"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                prepare_frame(Vendor(raw), MEMBER, "1wk", now=NOW)

    def test_future_non_session_naive_duplicate_and_same_week_rows_are_rejected(self):
        fixtures = (
            ([NOW + timedelta(days=5)], "after actual receipt"),
            ([NOW.replace(day=18, hour=9)], "non-session"),
            ([datetime(2026, 10, 19, 9)], "timezone-aware"),
            ([NOW.replace(day=19, hour=10)], "shifted native weekly"),
            ([NOW.replace(day=19, hour=9)] * 2, "unique and ordered"),
            ([NOW.replace(day=19, hour=9), NOW.replace(day=20, hour=9)], "one calendar week"),
            ([NOW.replace(day=19, hour=9), NOW.replace(day=12, hour=9)], "unique and ordered"),
        )
        for starts, reason in fixtures:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                prepare_frame(Vendor(source(starts=starts)), MEMBER, "1wk", now=NOW)

    def test_bad_ohlcv_is_never_repaired_or_published_as_real_prices(self):
        for changes in ({"close": 0}, {"low": -1}, {"high": float("inf")},
                        {"volume": -1}, {"close": float("nan")}, {"high": 50},
                        {"open": True}, {"close": "105"}):
            raw = source()
            raw = replace(raw, bars=(*raw.bars[:-1], replace(raw.bars[-1], **changes)))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepare_frame(Vendor(raw), MEMBER, "1wk", now=NOW)

    def test_backward_clock_and_naive_clock_are_rejected(self):
        moments = iter((NOW, NOW - timedelta(seconds=1)))
        with self.assertRaisesRegex(ValueError, "backwards"):
            prepare_frame(Vendor(source()), MEMBER, "1wk", now=lambda: next(moments))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            prepare_frame(Vendor(source()), MEMBER, "1wk", now=NOW.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
