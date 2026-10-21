from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy_native_multihour import (
    BorsapyNativeMultihourProvider,
)
from market_intelligence.market_data.adapters.tvdatafeed import TvDatafeedBistProvider
from market_intelligence.market_data.providers import FetchRequest

IST = ZoneInfo("Europe/Istanbul")


def data(target=Timeframe.H2):
    target = Timeframe(target)
    first = "09:45" if target is Timeframe.M15 else "09:30" if target is Timeframe.M30 else "09:00"
    final = "18:00" if target.minutes <= 60 else "17:00"
    return pd.DataFrame({"open": [10., 11.], "high": [13., 14.], "low": [9., 10.],
        "close": [12., 13.], "volume": [100., 200.]},
        index=pd.DatetimeIndex([f"2026-10-20 {first}", f"2026-10-20 {final}"], tz=IST))


class SdkStub:
    TIMEFRAMES = {"1h": "60", "4h": "240"}  # Real0.11 SDK has no2h mapping.
    instances = []
    override_resolution = None
    override_adjustment = None
    include_volume = True

    def __init__(self):
        self.instances.append(self)
        self.closed = False
        self.messages = []

    def _get_auth_token(self):
        raise AssertionError("No account storage")

    def _calculate_bars(self, period, interval, start, end):
        raise AssertionError("Unknown-interval daily fallback must not be used")

    def _create_message(self, method, params):
        self.messages.append((method, params))
        return json.dumps({"m": method, "p": params})

    def get_history(self, symbol, interval, period, exchange):
        self._create_message("set_auth_token", [self._get_auth_token()])
        self._create_message("resolve_symbol", ["chart", "ser", "=" + json.dumps({
            "symbol": f"{exchange}:{symbol}", "adjustment": self.override_adjustment or "splits", "session": "regular"})])
        self._create_message("create_series", ["chart", "prices", "s1", "ser",
            self.override_resolution or self.TIMEFRAMES.get(interval, "1D"),
            self._calculate_bars(period, interval, None, None), ""])
        return data(interval) if self.include_volume else data(interval).drop(columns=["volume"])

    def close(self):
        self.closed = True


class NativeMultihourProviderTests(unittest.TestCase):
    def setUp(self):
        SdkStub.instances = []
        SdkStub.override_resolution = None
        SdkStub.override_adjustment = None
        SdkStub.include_volume = True

    def request(self, target):
        return FetchRequest("BIST:ATSYH", target, 600, datetime(2026, 10, 21, 8, tzinfo=IST))

    def provider(self, version="0.11.0"):
        return BorsapyNativeMultihourProvider(sdk_client_class=SdkStub, sdk_version=version)

    def test_actual120_and240_resolution_messages_ohlcv_and_sdk_global_mapping_preserved(self):
        original = dict(SdkStub.TIMEFRAMES)
        for target, resolution in ((Timeframe.M15, "15"), (Timeframe.M30, "30"), (Timeframe.H1, "60"),
                                   (Timeframe.H2, "120"), (Timeframe.H4, "240")):
            frame = self.provider().fetch_native_multihour(self.request(target))
            self.assertEqual(frame.timeframe, target)
            self.assertEqual(frame.price_basis, PriceBasis.SPLIT_ADJUSTED)
            self.assertEqual(frame.bars[-1].timestamp, datetime(2026, 10, 20, 15 if target.minutes <= 60 else 14, tzinfo=UTC))
            self.assertEqual((frame.bars[-1].open, frame.bars[-1].high, frame.bars[-1].low,
                frame.bars[-1].close, frame.bars[-1].volume), (11, 14, 10, 13, 200))
            self.assertEqual([p[4:6] for m, p in SdkStub.instances[-1].messages if m == "create_series"], [[resolution, 600]])
            self.assertTrue(SdkStub.instances[-1].closed)
        self.assertEqual(SdkStub.TIMEFRAMES, original)
        self.assertNotIn("2h", SdkStub.TIMEFRAMES)

    def test_wrong_resolution_price_basis_missing_volume_and_sdk_version_are_rejected(self):
        SdkStub.override_resolution = "1D"
        with self.assertRaisesRegex(ValueError, "exact native resolution"):
            self.provider().fetch_native_multihour(self.request(Timeframe.H2))
        SdkStub.override_resolution = None
        SdkStub.override_adjustment = "none"
        with self.assertRaisesRegex(ValueError, "price basis"):
            self.provider().fetch_native_multihour(self.request(Timeframe.H4))
        SdkStub.override_adjustment = None
        SdkStub.include_volume = False
        with self.assertRaisesRegex(ValueError, "actual volume"):
            self.provider().fetch_native_multihour(self.request(Timeframe.H2))
        with self.assertRaisesRegex(ValueError, "SDK version"):
            self.provider("0.12.0").fetch_native_multihour(self.request(Timeframe.H2))

    def test_other_timeframes_and_boolean_bar_counts_are_rejected_before_sdk(self):
        with self.assertRaisesRegex(ValueError, "only explicit"):
            self.provider().fetch_native_multihour(self.request(Timeframe.D1))
        request = FetchRequest("ATSYH", Timeframe.H2, True, self.request(Timeframe.H2).as_of)
        with self.assertRaisesRegex(ValueError, "bars"):
            self.provider().fetch_native_multihour(request)
        self.assertFalse(SdkStub.instances)

    def test_tv_native2h4h_preserve_actual_times_on_both_host_clocks_without_closed_filter(self):
        for target, attr, resolution in ((Timeframe.M15, "in_15_minute", "15"),
                (Timeframe.M30, "in_30_minute", "30"), (Timeframe.H1, "in_1_hour", "60"),
                (Timeframe.H2, "in_2_hour", "120"), (Timeframe.H4, "in_4_hour", "240")):
            outputs = []
            for zone in ("UTC", "Europe/Istanbul"):
                source = data(target)
                source.index = source.index.tz_convert(zone).tz_localize(None)
                calls = []
                stub = SimpleNamespace(get_hist=lambda calls=calls, source=source, **kw: (calls.append(kw), source)[1])
                module = SimpleNamespace(Interval=SimpleNamespace(**{attr: resolution}), TvDatafeed=lambda stub=stub: stub)
                provider = TvDatafeedBistProvider(client=stub, naive_timestamp_timezone=zone)
                with patch.dict(sys.modules, {"tvDatafeed": module}):
                    frame = provider.fetch_native_multihour(self.request(target))
                self.assertEqual(calls[0]["interval"], resolution)
                self.assertEqual(frame.bars[-1].timestamp, datetime(2026, 10, 20, 15 if target.minutes <= 60 else 14, tzinfo=UTC))
                self.assertEqual(frame.price_basis, PriceBasis.SPLIT_ADJUSTED)
                if target in (Timeframe.H2, Timeframe.H4):
                    with self.assertRaisesRegex(ValueError, "explicit native-multihour"):
                        provider.fetch(self.request(target))
                outputs.append(frame.bars)
            self.assertEqual(outputs[0], outputs[1])

    def test_confirmed_hourly_fetch_remains_regular_only_while_explicit_ram_keeps_auctions(self):
        source = pd.concat((data(Timeframe.H1).iloc[:1], data(Timeframe.H2).iloc[-1:], data(Timeframe.H1).iloc[-1:]))
        stub = SimpleNamespace(get_hist=lambda **kw: source)
        module = SimpleNamespace(Interval=SimpleNamespace(in_1_hour="60"), TvDatafeed=lambda: stub)
        provider = TvDatafeedBistProvider(client=stub)
        with patch.dict(sys.modules, {"tvDatafeed": module}):
            confirmed = provider.fetch(self.request(Timeframe.H1))
            ram = provider.fetch_native_multihour(self.request(Timeframe.H1))
        self.assertEqual([bar.timestamp.astimezone(IST).hour for bar in confirmed.bars], [17])
        self.assertEqual([bar.timestamp.astimezone(IST).hour for bar in ram.bars], [9, 17, 18])

    def test_tv_native_multihour_cannot_invent_volume_or_accept_duplicate_timestamps(self):
        for source, reason in ((data().drop(columns=["volume"]), "actual volume"),
                              (pd.concat((data().iloc[:1], data().iloc[:1])), "unique actual")):
            stub = SimpleNamespace(get_hist=lambda source=source, **kw: source)
            module = SimpleNamespace(Interval=SimpleNamespace(in_2_hour="120"), TvDatafeed=lambda stub=stub: stub)
            with patch.dict(sys.modules, {"tvDatafeed": module}), self.assertRaisesRegex(ValueError, reason):
                TvDatafeedBistProvider(client=stub).fetch_native_multihour(self.request(Timeframe.H2))


if __name__ == "__main__":
    unittest.main()
