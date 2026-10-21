from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy_native_weekly import (
    BorsapyNativeWeeklyProvider,
)
from market_intelligence.market_data.providers import FetchRequest

IST = ZoneInfo("Europe/Istanbul")


class WeeklySdkStub:
    TIMEFRAMES = {"1d": "1D", "1wk": "1W"}
    instances = []
    override_resolution = None
    override_adjustment = None
    include_volume = True
    naive_clock = False

    def __init__(self):
        self.closed = False
        self.messages = []
        self.instances.append(self)

    def _get_auth_token(self):
        raise AssertionError("Account storage must not be read")

    def _calculate_bars(self, period, interval, start, end):
        raise AssertionError("Daily history calculator must not be used")

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
        data = pd.DataFrame({"Open": [1.0, 2.0], "High": [1.5, 2.5],
            "Low": [0.5, 1.5], "Close": [1.25, 2.25], "Volume": [100, 200]},
            index=pd.DatetimeIndex(["2026-10-12 09:00", "2026-10-19 09:00"], tz=IST))
        if not self.include_volume:
            data = data.drop(columns=["Volume"])
        if self.naive_clock:
            data.index = data.index.tz_localize(None)
        return data

    def close(self):
        self.closed = True


class BorsapyNativeWeeklyTests(unittest.TestCase):
    def setUp(self):
        WeeklySdkStub.instances = []
        WeeklySdkStub.override_resolution = None
        WeeklySdkStub.override_adjustment = None
        WeeklySdkStub.include_volume = True
        WeeklySdkStub.naive_clock = False
        self.request = FetchRequest("BIST:ASELS", Timeframe.W1, 600, datetime(2026, 10, 21, 12, tzinfo=IST))

    def provider(self, sdk_version="0.11.0"):
        return BorsapyNativeWeeklyProvider(sdk_client_class=WeeklySdkStub, sdk_version=sdk_version)

    def test_native_1W_message_and_actual_mutable_ohlcv_are_independently_verified(self):
        original = dict(WeeklySdkStub.TIMEFRAMES)
        frame = self.provider().fetch_native_weekly(self.request)
        self.assertEqual(WeeklySdkStub.TIMEFRAMES, original)
        self.assertEqual(frame.timeframe, Timeframe.W1)
        self.assertEqual(frame.price_basis, PriceBasis.SPLIT_ADJUSTED)
        self.assertEqual(frame.bars[-1].timestamp, datetime(2026, 10, 19, 6, tzinfo=UTC))
        self.assertEqual((frame.bars[-1].open, frame.bars[-1].high, frame.bars[-1].low,
            frame.bars[-1].close, frame.bars[-1].volume), (2, 2.5, 1.5, 2.25, 200))
        client = WeeklySdkStub.instances[-1]
        self.assertEqual([params[4:6] for method, params in client.messages if method == "create_series"], [["1W", 600]])
        self.assertTrue(client.closed)

    def test_silent_daily_resolution_or_other_price_basis_are_rejected(self):
        WeeklySdkStub.override_resolution = "1D"
        with self.assertRaisesRegex(ValueError, "actual 1W resolution"):
            self.provider().fetch_native_weekly(self.request)
        self.assertTrue(WeeklySdkStub.instances[-1].closed)
        WeeklySdkStub.override_resolution = None
        WeeklySdkStub.override_adjustment = "none"
        with self.assertRaisesRegex(ValueError, "price basis"):
            self.provider().fetch_native_weekly(self.request)

    def test_wrong_timeframe_version_and_bar_count_fail_before_network_client(self):
        for request in (FetchRequest("ASELS", Timeframe.D1, 600, self.request.as_of),
                        FetchRequest("ASELS", Timeframe.W1, True, self.request.as_of)):
            with self.assertRaises(ValueError):
                self.provider().fetch_native_weekly(request)
        with self.assertRaisesRegex(ValueError, "SDK version"):
            self.provider("0.12.0").fetch_native_weekly(self.request)
        self.assertEqual(WeeklySdkStub.instances, [])

    def test_missing_volume_and_ambiguous_source_timezone_are_never_invented(self):
        WeeklySdkStub.include_volume = False
        with self.assertRaisesRegex(ValueError, "actual volume"):
            self.provider().fetch_native_weekly(self.request)
        WeeklySdkStub.include_volume = True
        WeeklySdkStub.naive_clock = True
        with self.assertRaisesRegex(ValueError, "timezone-aware timestamps"):
            self.provider().fetch_native_weekly(self.request)

    def test_changed_sdk_weekly_mapping_is_rejected_before_client_or_daily_fallback(self):
        with patch.dict(WeeklySdkStub.TIMEFRAMES, {"1wk": "1D"}), self.assertRaisesRegex(ValueError, "SDK interface"):
            self.provider().fetch_native_weekly(self.request)
        self.assertEqual(WeeklySdkStub.instances, [])


if __name__ == "__main__":
    unittest.main()
