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
from scripts import atc_live_multihour_frames as native

IST = ZoneInfo("Europe/Istanbul")
DAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 21, 8, tzinfo=IST)
MEMBER = SimpleNamespace(instrument_id="BIST:ATSYH", symbol="ATSYH", provider_symbol="ATSYH", market="BIST")
SESSIONS = frozenset((date(2026, 10, 19), DAY, NOW.date(), date(2026, 5, 26), date(2025, 6, 5)))


def raw(target=Timeframe.H2, starts=None):
    hours = (9, 11, 13, 15, 17) if target is Timeframe.H2 else (9, 13, 17)
    starts = starts or [datetime.combine(DAY, datetime.min.time(), IST).replace(hour=hour) for hour in hours]
    return ProviderFrame(provider="native_fixture", provider_symbol="BIST:ATSYH", timeframe=target,
        timestamp_kind=TimestampKind.OPEN, timestamp_timezone="Europe/Istanbul", price_basis=PriceBasis.SPLIT_ADJUSTED,
        bars=tuple(ProviderBar(stamp, 100 + i, 113 + i, 91 + i, 107 + i, 1000 + i)
            for i, stamp in enumerate(starts)), last_bar_is_partial=False)


class Vendor:
    def __init__(self, frame):
        self.frame = frame
        self.requests = []

    def fetch(self, request):
        raise AssertionError("Native multihour cannot derive from H1")

    def fetch_native_multihour(self, request):
        self.requests.append(request)
        return self.frame


class NativeMultihourFrameTests(unittest.TestCase):
    def setUp(self):
        for name, result in (("_session_days", SESSIONS), ("_nonregular_session_days", frozenset()),
                             ("_historical_halfdays", {})):
            mocked = patch.object(native, name, return_value=result)
            mocked.start()
            self.addCleanup(mocked.stop)

    def prepare(self, frame, *, now=NOW, target=None, bars=600):
        return native.prepare_native_multihour(Vendor(frame), MEMBER, timeframe=target or frame.timeframe,
            observed_at=now, clock=lambda: now, bars=bars)

    def test_exact_native_prices_and_17_hour_nominal_ends_are_preserved_in_ram(self):
        for target, end in ((Timeframe.H2, 19), (Timeframe.H4, 21)):
            source = raw(target)
            vendor = Vendor(source)
            frame, meta = native.prepare_native_multihour(vendor, MEMBER, timeframe=target,
                observed_at=NOW, clock=lambda: NOW, bars=600)
            self.assertEqual(frame.timeframe, target)
            self.assertEqual(frame.quality, native.QUALITY)
            self.assertFalse(frame.is_partial)
            self.assertEqual(frame.bars[-1].open_time.hour, 17)
            self.assertEqual(frame.bars[-1].close_time.hour, end)
            self.assertEqual(frame.bars[-1].close_time.date(), DAY)
            for actual, original in zip(frame.bars, source.bars, strict=True):
                self.assertEqual(actual.open_time, original.timestamp)
                self.assertEqual((actual.open, actual.high, actual.low, actual.close, actual.volume),
                    (original.open, original.high, original.low, original.close, original.volume))
            self.assertTrue(meta["usable_latest"])
            self.assertEqual(meta["expected_market_session"], DAY.isoformat())
            self.assertEqual(meta["source_grid"], native.NATIVE_MULTIHOUR_GRIDS[target])
            for field in ("last_trade_at", "price_delay_seconds", "actual_bar_is_open", "latest_target_complete"):
                self.assertIsNone(meta[field])
            self.assertFalse(meta["persisted"])
            self.assertFalse(meta["nominal_end_is_exchange_confirmation"])
            self.assertEqual(vendor.requests[0].timeframe, target)

    def test_sparse_auction_history_is_not_replaced_by_fake_missing_native_bars(self):
        source = raw(starts=[datetime(2026, 10, 20, hour, tzinfo=IST) for hour in (9, 11, 13, 17)])
        frame, meta = self.prepare(source)
        self.assertEqual([bar.open_time.hour for bar in frame.bars], [9, 11, 13, 17])
        self.assertEqual(len(frame.bars), 4)
        self.assertTrue(meta["usable_latest"])

    def test_actual_current_interval_is_not_exchange_confirmation(self):
        now = datetime(2026, 10, 20, 13, 5, tzinfo=IST)
        source = raw(Timeframe.H4, starts=[now.replace(hour=9, minute=0), now.replace(minute=0)])
        _, meta = self.prepare(source, now=now)
        self.assertTrue(meta["usable_latest"])
        self.assertTrue(meta["nominally_open"])
        self.assertIsNone(meta["actual_bar_is_open"])
        self.assertEqual(meta["actual_bar_confirmation"], "unknown")

    def test_delayed_previous_native_interval_keeps_30_minute_guard_and_truthful_status(self):
        source = raw(starts=[datetime(2026, 10, 20, 11, tzinfo=IST)])
        _, within = self.prepare(source, now=datetime(2026, 10, 20, 13, 30, tzinfo=IST))
        _, outside = self.prepare(source, now=datetime(2026, 10, 20, 13, 30, 1, tzinfo=IST))
        self.assertTrue(within["usable_latest"])
        self.assertFalse(within["current_bucket"])
        self.assertEqual(within["status"], "stale_previous_bucket")
        self.assertFalse(outside["usable_latest"])

    def test_actual_stale_source_still_calculates_without_becoming_current_or_missing(self):
        source = raw(starts=[datetime(2026, 10, 19, 17, tzinfo=IST)])
        frame, meta = self.prepare(source)
        self.assertEqual(frame.bars[-1].close, source.bars[-1].close)
        self.assertEqual(meta["status"], "stale_previous_session")
        self.assertFalse(meta["usable_latest"])

    def test_dated_historical_halfday_times_and_nominal_ends_remain_unchanged(self):
        for target, hours, nominal_end in ((Timeframe.H2, (9, 11), 13), (Timeframe.H4, (9,), 13)):
            day = date(2026, 5, 26)
            starts = [datetime.combine(day, datetime.min.time(), IST).replace(hour=h, minute=30) for h in hours]
            starts.append(datetime(2026, 10, 20, 17, tzinfo=IST))
            with patch.object(native, "_nonregular_session_days", return_value=frozenset((day,))), patch.object(
                    native, "_historical_halfdays", return_value={day: {"calendar_open": "2026-05-26T10:00:00+03:00", "calendar_close": "2026-05-26T12:30:00+03:00"}}):
                frame, meta = self.prepare(raw(target, starts=starts))
            self.assertEqual(frame.bars[0].open_time, starts[0])
            self.assertEqual(frame.bars[-2].close_time.hour, nominal_end)
            self.assertEqual(frame.bars[-2].close_time.minute, 30)
            policy = meta["historical_nonregular_native_grid_policies"][0]
            self.assertEqual(policy["calendar_close"], "2026-05-26T12:30:00+03:00")
            self.assertEqual(policy["anchor"], "09:30")
            self.assertTrue(meta["historical_nonregular_close_times_nominal"])

    def test_other_calendar_certified_halfday_does_not_require_a_hardcoded_date(self):
        day = date(2025, 6, 5)  # Not one of the3 source-probe evidence dates.
        starts = [datetime(2025, 6, 5, 9, 30, tzinfo=IST), datetime(2026, 10, 20, 17, tzinfo=IST)]
        with patch.object(native, "_nonregular_session_days", return_value=frozenset((day,))), patch.object(
                native, "_historical_halfdays", return_value={day: {"calendar_open": "2025-06-05T10:00:00+03:00", "calendar_close": "2025-06-05T12:30:00+03:00"}}):
            frame, meta = self.prepare(raw(Timeframe.H4, starts=starts))
        self.assertEqual(frame.bars[0].open_time, starts[0])
        self.assertEqual(meta["nonregular_history_dates"], [day.isoformat()])

    def test_unrecognized_nonregular_calendar_day_and_current_halfday_remain_rejected(self):
        for day in (date(2026, 5, 26), DAY):
            with patch.object(native, "_nonregular_session_days", return_value=frozenset((day,))), self.assertRaisesRegex(
                    ValueError, "Unsupported historical|half-day/nonregular"):
                self.prepare(raw(starts=[datetime.combine(day, datetime.min.time(), IST).replace(hour=9, minute=30)]))

    def test_wrong_resolution_instrument_close_label_and_shifted_grid_rejected(self):
        for source, target, reason in (
            (raw(Timeframe.H4), Timeframe.H2, "exact requested"),
            (replace(raw(), provider_symbol="ASELS"), Timeframe.H2, "different instrument"),
            (replace(raw(), timestamp_kind=TimestampKind.CLOSE), Timeframe.H2, "open-time"),
            (raw(starts=[datetime(2026, 10, 20, 10, tzinfo=IST)]), Timeframe.H2, "shifted native"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.prepare(source, target=target)

    def test_native_timestamps_must_be_aware_ordered_unique_nonfuture_and_session_dates(self):
        fixtures = (
            ([datetime(2026, 10, 20, 9)], "timezone-aware"),
            ([datetime(2026, 10, 22, 9, tzinfo=IST)], "after actual receipt"),
            ([datetime(2026, 10, 18, 9, tzinfo=IST)], "non-session"),
            ([datetime(2026, 10, 20, 9, tzinfo=IST)] * 2, "unique and ordered"),
            ([datetime(2026, 10, 20, h, tzinfo=IST) for h in (11, 9)], "unique and ordered"),
        )
        for starts, reason in fixtures:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.prepare(raw(starts=starts))

    def test_nonfinite_bool_nonpositive_inconsistent_prices_or_negative_volume_not_repaired(self):
        for changes in ({"close": 0}, {"low": -1}, {"open": True}, {"high": float("inf")},
                        {"volume": -1}, {"close": float("nan")}, {"high": 1}, {"close": "100"}):
            source = raw()
            source = replace(source, bars=(*source.bars[:-1], replace(source.bars[-1], **changes)))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.prepare(source)

    def test_receipt_clock_rechecks_expected_source_session_and_rejects_backwards(self):
        source = raw()
        observed = datetime(2026, 10, 21, 9, 44, tzinfo=IST)
        _, meta = native.prepare_native_multihour(Vendor(source), MEMBER, timeframe="2h", observed_at=observed,
            clock=lambda: observed + timedelta(minutes=2), bars=600)
        self.assertEqual(meta["expected_market_session"], "2026-10-21")
        self.assertFalse(meta["usable_latest"])
        with self.assertRaisesRegex(ValueError, "backwards"):
            native.prepare_native_multihour(Vendor(source), MEMBER, timeframe="2h", observed_at=observed,
                clock=lambda: observed - timedelta(seconds=1), bars=600)


if __name__ == "__main__":
    unittest.main()
