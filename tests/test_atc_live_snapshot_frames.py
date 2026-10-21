from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.fallback import FallbackMarketDataProvider
from market_intelligence.market_data.providers import ProviderBar, ProviderFrame, TimestampKind
from scripts import atc_live_snapshot_frames as live

IST = ZoneInfo("Europe/Istanbul")
DAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 11, 20, tzinfo=IST)
MEMBER = SimpleNamespace(instrument_id="BIST:ASELS", symbol="ASELS", provider_symbol="ASELS", market="BIST")
SESSIONS = frozenset((date(2026, 10, 16), date(2026, 10, 19), DAY))


def raw_frame(timeframe=Timeframe.M15, *, starts=None, partial=True, source="fixture"):
    starts = starts if starts is not None else [
        datetime(2026, 10, 20, 10, 0, tzinfo=IST) + timedelta(minutes=15 * index)
        for index in range(6)
    ]
    return ProviderFrame(
        provider=source, provider_symbol="ASELS", timeframe=timeframe,
        timestamp_kind=TimestampKind.OPEN, timestamp_timezone="Europe/Istanbul",
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        bars=tuple(ProviderBar(timestamp=stamp, open=100 + index, high=102 + index,
            low=99 + index, close=101 + index, volume=10 + index)
            for index, stamp in enumerate(starts)), last_bar_is_partial=partial,
    )


class Vendor:
    def __init__(self, frame):
        self.frame = frame
        self.name = frame.provider
        self.requests = []

    def fetch(self, request):
        self.requests.append(request)
        return self.frame


class NativeVendor(Vendor):
    def fetch(self, request):
        raise AssertionError("Native45 must not fetch or derive from15m")

    def fetch_native_grid(self, request):
        self.requests.append(request)
        return self.frame


class LatestActualFrameTests(unittest.TestCase):
    def setUp(self):
        self.calendar = patch.object(live, "_session_days", return_value=SESSIONS)
        self.calendar.start()
        self.addCleanup(self.calendar.stop)
        self.nonregular = patch.object(live, "_nonregular_session_days", return_value=frozenset())
        self.nonregular.start()
        self.addCleanup(self.nonregular.stop)

    def test_native_open_row_is_kept_only_as_ram_hypothetical_close(self):
        raw = raw_frame()
        vendor = Vendor(raw)
        frame, meta = live.prepare_frame(vendor, MEMBER, "15m", now=NOW)
        self.assertEqual(len(frame.bars), 6)
        self.assertFalse(frame.is_partial)
        self.assertEqual(frame.quality, live.QUALITY)
        self.assertTrue(meta["actual_bar_is_open"])
        self.assertTrue(meta["current_bucket"])
        self.assertTrue(meta["usable_latest"])
        self.assertEqual(meta["status"], "live_open")
        self.assertFalse(meta["persisted"])
        self.assertEqual(frame.bars[-1].open_time.hour, 11)
        self.assertEqual(frame.bars[-1].open_time.minute, 15)
        self.assertEqual(frame.bars[-1].close, raw.bars[-1].close)
        self.assertTrue(raw.last_bar_is_partial)  # Immutable input untouched.
        self.assertEqual(vendor.requests[0].as_of.minute, 30)
        self.assertIsNone(meta["last_trade_at"])
        self.assertIsNone(meta["price_delay_seconds"])

    def test_temporally_mutable_row_is_recognized_when_vendor_flag_false(self):
        frame, meta = live.prepare_frame(Vendor(raw_frame(partial=False)), MEMBER, "15m", now=NOW)
        self.assertEqual(len(frame.bars), 6)
        self.assertTrue(meta["actual_bar_is_open"])
        self.assertFalse(meta["provider_partial_flag"])

    def test_45m_aggregate_keeps_only_real_current_prefix(self):
        frame, meta = live.prepare_frame(Vendor(raw_frame()), MEMBER, "45m", now=NOW)
        self.assertEqual(len(frame.bars), 2)
        current = frame.bars[-1]
        self.assertEqual(current.open_time.minute, 45)
        self.assertEqual(current.close_time, NOW.replace(minute=30))
        self.assertEqual(current.volume, 13 + 14 + 15)
        self.assertEqual(current.close, 106)
        self.assertTrue(meta["current_bucket"])
        self.assertFalse(meta["latest_target_complete"])

    def test_delayed_contiguous_45m_prefix_survives_nominal_boundary_without_fake_tail(self):
        # Real bootstrap pattern: request started just before 16:45, receipt
        # crossed the boundary while the vendor still lacked its 16:30 row.
        starts = [NOW.replace(hour=16, minute=0), NOW.replace(hour=16, minute=15)]
        raw = raw_frame(starts=starts, partial=False)
        moments = iter((NOW.replace(hour=16, minute=44), NOW.replace(hour=16, minute=45, second=6)))
        frame, meta = live.prepare_frame(Vendor(raw), MEMBER, "45m", now=lambda: next(moments))
        self.assertEqual(frame.bars[-1].open_time, starts[0])
        self.assertEqual(frame.bars[-1].close_time, NOW.replace(hour=16, minute=45))
        self.assertEqual(frame.bars[-1].volume, 21)
        self.assertEqual(frame.bars[-1].close, raw.bars[-1].close)
        self.assertEqual(len(frame.bars), 1)
        self.assertEqual(meta["status"], "incomplete_latest_native_prefix")
        self.assertEqual(meta["observed_prefix_end"], NOW.replace(hour=16, minute=30).isoformat())
        self.assertFalse(meta["latest_target_complete"])
        self.assertFalse(meta["current_bucket"])
        self.assertFalse(meta["actual_bar_is_open"])
        self.assertFalse(meta["temporally_open"])
        self.assertTrue(meta["usable_latest"])
        self.assertFalse(meta["persisted"])
        self.assertFalse(frame.is_partial)  # Formula-only RAM frame, never confirmation.
        self.assertEqual(frame.quality, live.QUALITY)
        self.assertIsNone(meta["last_trade_at"])
        self.assertIsNone(meta["price_delay_seconds"])

    def test_after_boundary_prefix_limit_is_30_minutes_and_never_claims_fresh_quote(self):
        starts = [NOW.replace(hour=16, minute=0), NOW.replace(hour=16, minute=15)]
        raw = raw_frame(starts=starts, partial=False)
        _, boundary = live.prepare_frame(Vendor(raw), MEMBER, "45m", now=NOW.replace(hour=17, minute=0))
        self.assertTrue(boundary["usable_latest"])
        self.assertEqual(boundary["latest_native_close_age_seconds"], 1800)
        self.assertFalse(boundary["latest_target_complete"])
        with self.assertRaisesRegex(ValueError, "missing native"):
            live.prepare_frame(Vendor(raw), MEMBER, "45m", now=NOW.replace(hour=17, minute=0, second=1))

    def test_after_boundary_prefix_never_accepts_start_or_interior_gap(self):
        now = NOW.replace(hour=16, minute=46)
        for starts in (
            [NOW.replace(hour=16, minute=15)],
            [NOW.replace(hour=16, minute=0), NOW.replace(hour=16, minute=30)],
        ):
            with self.subTest(starts=starts), self.assertRaisesRegex(ValueError, "missing native"):
                live.prepare_frame(Vendor(raw_frame(starts=starts, partial=False)), MEMBER, "45m", now=now)

    def test_old_session_or_after_hours_incomplete_prefix_is_not_rescued(self):
        cases = (
            ([datetime(2026, 10, 19, 16, 0, tzinfo=IST), datetime(2026, 10, 19, 16, 15, tzinfo=IST)],
             NOW.replace(hour=10, minute=1)),
            ([NOW.replace(hour=17, minute=30)], NOW.replace(hour=18, minute=1)),
            ([NOW.replace(hour=13, minute=45)], NOW.replace(hour=16, minute=56)),
        )
        for starts, observed in cases:
            with self.subTest(starts=starts), self.assertRaisesRegex(ValueError, "missing native"):
                live.prepare_frame(Vendor(raw_frame(starts=starts, partial=False)), MEMBER, "45m", now=observed)

    def test_historical_incomplete_bucket_is_not_promoted_by_new_prefix_exception(self):
        starts = [NOW.replace(hour=15, minute=15), NOW.replace(hour=15, minute=30),
                  NOW.replace(hour=16, minute=0), NOW.replace(hour=16, minute=15)]
        frame, meta = live.prepare_frame(Vendor(raw_frame(starts=starts, partial=False)),
            MEMBER, "45m", now=NOW.replace(hour=16, minute=46))
        self.assertEqual(len(frame.bars), 1)
        self.assertEqual(meta["dropped_incomplete_history_buckets"], 1)
        self.assertEqual(meta["status"], "incomplete_latest_native_prefix")
        self.assertEqual(frame.bars[0].open_time, NOW.replace(hour=16, minute=0))

    def test_complete_closed_target_exposes_complete_metadata(self):
        starts = [NOW.replace(hour=16, minute=0), NOW.replace(hour=16, minute=15),
                  NOW.replace(hour=16, minute=30)]
        _, meta = live.prepare_frame(Vendor(raw_frame(starts=starts, partial=False)),
            MEMBER, "45m", now=NOW.replace(hour=16, minute=46))
        self.assertTrue(meta["latest_target_complete"])
        self.assertEqual(meta["observed_prefix_end"], NOW.replace(hour=16, minute=45).isoformat())
        self.assertEqual(meta["status"], "stale_previous_bucket")

    def test_two_and_four_hour_native_resolution_mapping(self):
        starts = [datetime(2026, 10, 20, 10 + i, tzinfo=IST) for i in range(2)]
        for target in ("2h", "4h"):
            with self.subTest(target=target):
                vendor = Vendor(raw_frame(Timeframe.H1, starts=starts))
                frame, meta = live.prepare_frame(vendor, MEMBER, target, now=NOW)
                self.assertEqual(vendor.requests[0].timeframe, Timeframe.H1)
                self.assertEqual(len(frame.bars), 1)
                self.assertEqual(frame.bars[-1].volume, 21)
                self.assertTrue(meta["actual_bar_is_open"])

    def test_thirty_minute_native_candle_and_close_timestamp_are_respected(self):
        raw = raw_frame(Timeframe.M30, starts=[NOW.replace(hour=10, minute=30), NOW.replace(hour=11, minute=0)])
        raw = replace(raw, timestamp_kind=TimestampKind.CLOSE,
            bars=tuple(replace(bar, timestamp=bar.timestamp + timedelta(minutes=30)) for bar in raw.bars))
        frame, meta = live.prepare_frame(Vendor(raw), MEMBER, "30m", now=NOW)
        self.assertEqual(frame.bars[-1].open_time, NOW.replace(minute=0))
        self.assertTrue(meta["current_bucket"])

    def test_latest_45m_session_tail_is_observed_without_inventing_1815(self):
        starts = [datetime(2026, 10, 20, 17, 30, tzinfo=IST), datetime(2026, 10, 20, 17, 45, tzinfo=IST)]
        frame, meta = live.prepare_frame(Vendor(raw_frame(starts=starts, partial=False)),
            MEMBER, "45m", now=NOW.replace(hour=19))
        self.assertEqual(frame.bars[-1].close_time, NOW.replace(hour=18, minute=0))
        self.assertTrue(meta["session_truncated_bucket"])
        self.assertEqual(meta["status"], "latest_closed")

    def test_older_45m_session_tails_do_not_change_confirmed_history_contract(self):
        starts = [datetime(2026, 10, 19, 17, 30, tzinfo=IST), datetime(2026, 10, 19, 17, 45, tzinfo=IST)]
        raw = raw_frame(starts=starts + [bar.timestamp for bar in raw_frame().bars])
        frame, meta = live.prepare_frame(Vendor(raw), MEMBER, "45m", now=NOW)
        self.assertEqual(len(frame.bars), 2)
        self.assertTrue(all(bar.open_time.date() == DAY for bar in frame.bars))
        self.assertEqual(meta["dropped_incomplete_history_buckets"], 1)

    def test_missing_current_aggregate_prefix_is_not_filled(self):
        raw = raw_frame()
        raw = replace(raw, bars=raw.bars[:3] + raw.bars[4:])
        with self.assertRaisesRegex(ValueError, "missing native"):
            live.prepare_frame(Vendor(raw), MEMBER, "45m", now=NOW)

    def test_internal_historical_aggregate_gap_drops_bucket_without_filling(self):
        raw = raw_frame()
        raw = replace(raw, bars=(raw.bars[0],) + raw.bars[2:])
        frame, meta = live.prepare_frame(Vendor(raw), MEMBER, "45m", now=NOW)
        self.assertEqual(len(frame.bars), 1)
        self.assertEqual(meta["dropped_incomplete_history_buckets"], 1)
        self.assertEqual(frame.bars[0].open_time.minute, 45)

    def test_missing_native_current_row_is_stale_even_inside_same_target_bucket(self):
        raw = replace(raw_frame(), bars=raw_frame().bars[:4], last_bar_is_partial=False)
        _, meta = live.prepare_frame(Vendor(raw), MEMBER, "45m", now=NOW)
        self.assertTrue(meta["target_bucket_present"])
        self.assertFalse(meta["current_bucket"])
        self.assertEqual(meta["status"], "stale_native_prefix")

    def test_native_gaps_are_not_forward_filled(self):
        raw = raw_frame()
        raw = replace(raw, bars=raw.bars[:2] + raw.bars[3:])
        frame, _ = live.prepare_frame(Vendor(raw), MEMBER, "15m", now=NOW)
        self.assertEqual(len(frame.bars), 5)
        self.assertNotIn(NOW.replace(hour=10, minute=30), [b.open_time for b in frame.bars])

    def test_latest_previous_bucket_is_retained_but_not_counted_fresh(self):
        raw = replace(raw_frame(), bars=raw_frame().bars[:-1], last_bar_is_partial=False)
        frame, meta = live.prepare_frame(Vendor(raw), MEMBER, "15m", now=NOW)
        self.assertEqual(frame.bars[-1].open_time.minute, 0)
        self.assertFalse(meta["current_bucket"])
        self.assertTrue(meta["usable_latest"])
        self.assertEqual(meta["status"], "stale_previous_bucket")

    def test_usable_latest_native_age_boundary_is_30_minutes_not_fresh_quote_claim(self):
        raw = raw_frame(starts=[NOW.replace(hour=10, minute=45)], partial=False)
        _, at_boundary = live.prepare_frame(Vendor(raw), MEMBER, "15m", now=NOW.replace(minute=30))
        _, beyond = live.prepare_frame(Vendor(raw), MEMBER, "15m", now=NOW.replace(minute=31))
        self.assertTrue(at_boundary["usable_latest"])
        self.assertFalse(at_boundary["current_bucket"])
        self.assertEqual(at_boundary["latest_native_close_age_seconds"], 1800)
        self.assertFalse(beyond["usable_latest"])
        self.assertIsNone(at_boundary["price_delay_seconds"])

    def test_latest_halfday_is_explicitly_unsupported_and_not_assumed_to_close_at_18(self):
        with patch.object(live, "_nonregular_session_days", return_value=frozenset((DAY,))):
            with self.assertRaisesRegex(ValueError, "half-day/nonregular"):
                live.prepare_frame(Vendor(raw_frame()), MEMBER, "15m", now=NOW)

    def test_past_halfday_ohlcv_preserved_with_nominal_timestamp_warning(self):
        stamps = [datetime(2026, 10, 19, tzinfo=IST), datetime(2026, 10, 20, tzinfo=IST)]
        with patch.object(live, "_nonregular_session_days", return_value=frozenset((date(2026, 10, 19),))):
            frame, meta = live.prepare_frame(Vendor(raw_frame(Timeframe.D1, starts=stamps)), MEMBER, "1d", now=NOW)
        self.assertEqual(len(frame.bars), 2)
        self.assertTrue(meta["historical_nonregular_close_times_nominal"])
        self.assertEqual(meta["nonregular_history_dates"], ["2026-10-19"])

    def test_previous_session_is_retained_and_explicitly_stale(self):
        raw = raw_frame(starts=[datetime(2026, 10, 19, 17, 45, tzinfo=IST)], partial=False)
        _, meta = live.prepare_frame(Vendor(raw), MEMBER, "15m", now=NOW)
        self.assertEqual(meta["status"], "stale_previous_session")
        self.assertFalse(meta["current_bucket"])
        self.assertFalse(meta["usable_latest"])

    def test_future_open_is_rejected_despite_future_technical_cutoff(self):
        raw = raw_frame(starts=[NOW.replace(minute=30)])
        with self.assertRaisesRegex(ValueError, "starts after receipt"):
            live.prepare_frame(Vendor(raw), MEMBER, "45m", now=NOW)

    def test_advancing_receipt_clock_validates_against_receipt_not_batch_start(self):
        raw = raw_frame(starts=[NOW.replace(minute=30)])
        times = iter((NOW, NOW.replace(minute=31)))
        _, meta = live.prepare_frame(Vendor(raw), MEMBER, "15m", now=lambda: next(times))
        self.assertEqual(meta["received_at"], NOW.replace(minute=31).isoformat())

    def test_daily_native_mutable_row_has_actual_ohlcv_without_zero_fill(self):
        stamps = [datetime(2026, 10, 19, tzinfo=IST), datetime(2026, 10, 20, tzinfo=IST)]
        vendor = Vendor(raw_frame(Timeframe.D1, starts=stamps))
        frame, meta = live.prepare_frame(vendor, MEMBER, "1d", now=NOW)
        self.assertEqual(frame.bars[-1].open_time.hour, 10)
        self.assertEqual(frame.bars[-1].close_time.hour, 18)
        self.assertEqual(frame.bars[-1].volume, 11)
        self.assertTrue(meta["current_bucket"])
        self.assertTrue(meta["usable_latest"])

    def test_daily_before_session_does_not_accept_untraded_today(self):
        stamp = datetime(2026, 10, 20, tzinfo=IST)
        raw = raw_frame(Timeframe.D1, starts=[stamp])
        with self.assertRaisesRegex(ValueError, "starts after receipt"):
            live.prepare_frame(Vendor(raw), MEMBER, "1d", now=NOW.replace(hour=9))

    def test_after_hours_and_weekend_accept_last_actual_close_without_fake_today(self):
        raw = raw_frame(starts=[datetime(2026, 10, 16, 17, 45, tzinfo=IST)], partial=False)
        saturday = datetime(2026, 10, 17, 12, tzinfo=IST)
        frame, meta = live.prepare_frame(Vendor(raw), MEMBER, "15m", now=saturday)
        self.assertEqual(len(frame.bars), 1)
        self.assertTrue(meta["current_bucket"])
        self.assertEqual(meta["status"], "latest_closed")
        self.assertFalse(meta["actual_bar_is_open"])

    def test_exchange_holiday_and_shifted_and_duplicate_rows_rejected(self):
        cases = (
            raw_frame(starts=[datetime(2026, 10, 18, 10, tzinfo=IST)]),
            raw_frame(starts=[datetime(2026, 10, 20, 10, 1, tzinfo=IST)]),
            raw_frame(starts=[NOW.replace(minute=0), NOW.replace(minute=0)]),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                live.prepare_frame(Vendor(raw), MEMBER, "15m", now=NOW)

    def test_fallback_validates_whole_source_and_preserves_selected_basis(self):
        invalid = replace(raw_frame(source="bad"), provider_symbol="OTHER")
        good = replace(raw_frame(source="good"), price_basis=PriceBasis.RAW)
        provider = FallbackMarketDataProvider((Vendor(invalid), Vendor(good)))
        frame, meta = live.prepare_frame(provider, MEMBER, "15m", now=NOW)
        self.assertEqual(frame.source, "good")
        self.assertEqual(frame.price_basis, PriceBasis.RAW)
        self.assertEqual(meta["price_basis"], PriceBasis.RAW.value)

    def test_invalid_geometry_and_nonpositive_prices_rejected(self):
        raw = raw_frame()
        for changed in (replace(raw.bars[-1], high=1), replace(raw.bars[-1], low=-1)):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                live.prepare_frame(Vendor(replace(raw, bars=raw.bars[:-1] + (changed,))),
                    MEMBER, "15m", now=NOW)

    def test_weekly_and_naive_clock_and_other_instrument_explicitly_rejected(self):
        with self.assertRaisesRegex(ValueError, "weekly unsupported"):
            live.prepare_frame(Vendor(raw_frame()), MEMBER, "1wk", now=NOW)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            live.prepare_frame(Vendor(raw_frame()), MEMBER, "15m", now=NOW.replace(tzinfo=None))
        with self.assertRaisesRegex(ValueError, "different instrument"):
            live.prepare_frame(Vendor(replace(raw_frame(), provider_symbol="OTHER")), MEMBER, "15m", now=NOW)


class Native45ActualFrameTests(unittest.TestCase):
    def setUp(self):
        self.calendar = patch.object(live, "_session_days", return_value=SESSIONS)
        self.calendar.start()
        self.addCleanup(self.calendar.stop)
        self.nonregular = patch.object(live, "_nonregular_session_days", return_value=frozenset())
        self.nonregular.start()
        self.addCleanup(self.nonregular.stop)

    def raw(self, *, starts=None, partial=False):
        starts = starts if starts is not None else [
            NOW.replace(hour=9, minute=45) + timedelta(minutes=45 * index)
            for index in range(12)]
        return raw_frame(Timeframe.M45, starts=starts, partial=partial, source="actual-native-fixture")

    def test_dense_native_grid_preserves_auctions_and_nominal_1845_end(self):
        vendor = NativeVendor(self.raw())
        frame, meta = live.prepare_frame(vendor, MEMBER, "45m", now=NOW.replace(hour=21))
        self.assertEqual(vendor.requests[0].timeframe, Timeframe.M45)
        self.assertEqual(len(frame.bars), 12)
        self.assertEqual(frame.bars[0].open_time, NOW.replace(hour=9, minute=45))
        self.assertEqual(frame.bars[-1].open_time, NOW.replace(hour=18, minute=0))
        self.assertEqual(frame.bars[-1].close_time, NOW.replace(hour=18, minute=45))
        self.assertEqual(frame.bars[-1].volume, vendor.frame.bars[-1].volume)
        self.assertEqual(frame.bars[-1].close, vendor.frame.bars[-1].close)
        self.assertEqual(meta["source_grid"], live.NATIVE_45M_GRID)
        self.assertEqual(meta["native_timeframe"], "45m")
        self.assertEqual(meta["native_bar_time_basis"], "provider_nominal_interval_not_last_trade")
        self.assertTrue(meta["usable_latest"])
        self.assertTrue(meta["current_bucket"])
        self.assertTrue(meta["latest_target_complete"])
        self.assertFalse(meta["session_truncated_bucket"])
        self.assertFalse(meta["persisted"])
        self.assertFalse(frame.is_partial)
        self.assertEqual(frame.quality, live.QUALITY)
        self.assertIsNone(meta["actual_bar_is_open"])
        self.assertIsNone(meta["last_trade_at"])
        self.assertIsNone(meta["price_delay_seconds"])

    def test_sparse_actual_native_bars_are_kept_without_filling_empty_periods(self):
        starts = [NOW.replace(hour=9, minute=45), NOW.replace(hour=12, minute=45),
                  NOW.replace(hour=13, minute=30), NOW.replace(hour=17, minute=15),
                  NOW.replace(hour=18, minute=0)]
        raw = self.raw(starts=starts)
        frame, meta = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=21))
        self.assertEqual([bar.open_time for bar in frame.bars], starts)
        self.assertEqual([bar.volume for bar in frame.bars], [bar.volume for bar in raw.bars])
        self.assertEqual([bar.close for bar in frame.bars], [bar.close for bar in raw.bars])
        self.assertEqual(meta["dropped_incomplete_history_buckets"], 0)
        self.assertTrue(meta["usable_latest"])

    def test_stale_sparse_snapshot_is_returned_for_calculation_not_called_fresh(self):
        raw = self.raw(starts=[NOW.replace(hour=12, minute=45), NOW.replace(hour=13, minute=30)])
        frame, meta = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=17, minute=10))
        self.assertEqual(len(frame.bars), 2)
        self.assertEqual(meta["status"], "stale_previous_bucket")
        self.assertFalse(meta["usable_latest"])
        self.assertFalse(meta["current_bucket"])
        self.assertEqual(frame.bars[-1].close, raw.bars[-1].close)

    def test_prior_day_halted_or_untraded_snapshot_does_not_create_today_bar(self):
        raw = self.raw(starts=[datetime(2026, 10, 19, 18, 0, tzinfo=IST)])
        frame, meta = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=21))
        self.assertEqual(len(frame.bars), 1)
        self.assertEqual(frame.bars[-1].open_time.date(), date(2026, 10, 19))
        self.assertEqual(meta["status"], "stale_previous_session")
        self.assertFalse(meta["usable_latest"])

    def test_native_freshness_boundary_remains_30_minutes(self):
        raw = self.raw(starts=[NOW.replace(hour=13, minute=30)])
        _, boundary = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=14, minute=45))
        _, beyond = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=14, minute=45, second=1))
        self.assertTrue(boundary["usable_latest"])
        self.assertEqual(boundary["latest_native_close_age_seconds"], 1800)
        self.assertFalse(beyond["usable_latest"])

    def test_nominal_auction_interval_does_not_claim_actual_trading_is_open(self):
        raw = self.raw(starts=[NOW.replace(hour=18, minute=0)])
        _, meta = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=18, minute=20))
        self.assertTrue(meta["nominally_open"])
        self.assertTrue(meta["temporally_open"])
        self.assertFalse(meta["latest_target_complete"])
        self.assertIsNone(meta["actual_bar_is_open"])
        self.assertEqual(meta["actual_bar_confirmation"], "unknown")

    def test_before_open_and_weekend_use_previous_session_native_auction(self):
        raw = self.raw(starts=[datetime(2026, 10, 19, 18, 0, tzinfo=IST)])
        _, meta = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=9, minute=30))
        self.assertTrue(meta["current_bucket"])
        self.assertTrue(meta["usable_latest"])
        friday = self.raw(starts=[datetime(2026, 10, 16, 18, 0, tzinfo=IST)])
        _, weekend = live.prepare_frame(NativeVendor(friday), MEMBER, "45m",
                                       now=datetime(2026, 10, 17, 12, 0, tzinfo=IST))
        self.assertTrue(weekend["current_bucket"])
        self.assertTrue(weekend["usable_latest"])

    def test_native_grid_rejects_shifted_10am_derived_grid_and_outside_opens(self):
        for stamp in (NOW.replace(hour=10, minute=0), NOW.replace(hour=9, minute=0),
                      NOW.replace(hour=18, minute=45), NOW.replace(hour=12, minute=46)):
            with self.subTest(stamp=stamp), self.assertRaisesRegex(ValueError, "shifted native"):
                live.prepare_frame(NativeVendor(self.raw(starts=[stamp])), MEMBER, "45m", now=NOW.replace(hour=21))

    def test_aware_utc_input_and_close_stamps_preserve_native_opens(self):
        starts = [NOW.replace(hour=13, minute=30).astimezone(ZoneInfo("UTC"))]
        raw = self.raw(starts=starts)
        raw = replace(raw, timestamp_kind=TimestampKind.CLOSE,
                      bars=tuple(replace(bar, timestamp=bar.timestamp + timedelta(minutes=45)) for bar in raw.bars))
        frame, _ = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=14))
        self.assertEqual(frame.bars[-1].open_time, NOW.replace(hour=13, minute=30))

    def test_native_frame_identity_and_nonempty_history_are_required(self):
        raw = self.raw(starts=[NOW.replace(hour=9, minute=45)])
        for changed, message in ((replace(raw, timeframe=Timeframe.M15), "different timeframe"),
                                 (replace(raw, provider_symbol="OTHER"), "different instrument"),
                                 (SimpleNamespace(**{**vars(raw), "bars": ()}), "No authentic")):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                live.prepare_frame(NativeVendor(changed), MEMBER, "45m", now=NOW)

    def test_naive_future_non_session_duplicate_and_unordered_native_bars_fail_closed(self):
        raw = self.raw(starts=[NOW.replace(hour=9, minute=45), NOW.replace(hour=10, minute=30)])
        cases = (
            replace(raw, bars=(replace(raw.bars[0], timestamp=raw.bars[0].timestamp.replace(tzinfo=None)),)),
            self.raw(starts=[NOW.replace(hour=12, minute=0)]),
            self.raw(starts=[datetime(2026, 10, 18, 9, 45, tzinfo=IST)]),
            replace(raw, bars=(raw.bars[0], raw.bars[0])),
            replace(raw, bars=tuple(reversed(raw.bars))),
        )
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                live.prepare_frame(NativeVendor(changed), MEMBER, "45m", now=NOW)

    def test_native_ohlcv_positive_finite_and_consistent_geometry_required(self):
        raw = self.raw(starts=[NOW.replace(hour=9, minute=45)])
        for values in ({"close": float("nan")}, {"high": float("inf")}, {"low": -1},
                       {"open": True}, {"volume": -1}, {"high": 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                changed = replace(raw, bars=(replace(raw.bars[0], **values),))
                live.prepare_frame(NativeVendor(changed), MEMBER, "45m", now=NOW)

    def test_native_latest_halfday_remains_explicitly_unsupported(self):
        with patch.object(live, "_nonregular_session_days", return_value=frozenset((DAY,))):
            with self.assertRaisesRegex(ValueError, "half-day/nonregular"):
                live.prepare_frame(NativeVendor(self.raw(starts=[NOW.replace(hour=9, minute=45)])),
                                   MEMBER, "45m", now=NOW)

    def test_certified_historical_short_session_preserves_actual_0930_native_grid(self):
        day = date(2026, 5, 26)
        starts = [datetime(2026, 5, 26, 9, 30, tzinfo=IST),
                  datetime(2026, 5, 26, 11, 45, tzinfo=IST),
                  datetime(2026, 5, 26, 12, 30, tzinfo=IST), NOW.replace(hour=18, minute=0)]
        raw = self.raw(starts=starts)
        with patch.object(live, "_session_days", return_value=SESSIONS | {day}), \
                patch.object(live, "_nonregular_session_days", return_value=frozenset((day,))):
            frame, meta = live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=21))
        self.assertEqual([bar.open_time for bar in frame.bars], starts)
        self.assertEqual(frame.bars[2].close_time, datetime(2026, 5, 26, 13, 15, tzinfo=IST))
        self.assertEqual([bar.volume for bar in frame.bars], [bar.volume for bar in raw.bars])
        self.assertTrue(meta["historical_nonregular_close_times_nominal"])
        self.assertEqual(meta["historical_nonregular_native_grid_policies"][0]["session"], "2026-05-26")
        self.assertTrue(meta["usable_latest"])

    def test_short_grid_requires_calendar_certification_and_dated_policy(self):
        stamp = datetime(2026, 5, 26, 9, 30, tzinfo=IST)
        raw = self.raw(starts=[stamp, NOW.replace(hour=18, minute=0)])
        with patch.object(live, "_session_days", return_value=SESSIONS | {stamp.date()}):
            with self.assertRaisesRegex(ValueError, "shifted native"):
                live.prepare_frame(NativeVendor(raw), MEMBER, "45m", now=NOW.replace(hour=21))
        other = datetime(2026, 5, 25, 9, 30, tzinfo=IST)
        with patch.object(live, "_session_days", return_value=SESSIONS | {other.date()}), \
                patch.object(live, "_nonregular_session_days", return_value=frozenset((other.date(),))):
            with self.assertRaisesRegex(ValueError, "Unsupported historical"):
                live.prepare_frame(NativeVendor(self.raw(starts=[other, NOW.replace(hour=18, minute=0)])),
                                   MEMBER, "45m", now=NOW.replace(hour=21))


if __name__ == "__main__":
    unittest.main()
