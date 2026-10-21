from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy_native_grid import BorsapyNative45Provider
from market_intelligence.market_data.providers import FetchRequest

IST = ZoneInfo("Europe/Istanbul")


class SdkStub:
    TIMEFRAMES = {"15m": "15", "1d": "1D"}
    instances = []
    override_resolution = None
    override_adjustment = None

    def __init__(self):
        self.closed = False
        self.messages = []
        self.instances.append(self)

    def _get_auth_token(self):
        raise AssertionError("SDK account storage must not be read")

    def _calculate_bars(self, period, interval, start, end):
        raise AssertionError("SDK daily fallback bar calculator must not be used")

    def _create_message(self, method, params):
        self.messages.append((method, params))
        return json.dumps({"m": method, "p": params})

    def get_history(self, symbol, interval, period, exchange):
        self._create_message("set_auth_token", [self._get_auth_token()])
        config = {"symbol": f"{exchange}:{symbol}", "adjustment": self.override_adjustment or "splits",
                  "session": "regular"}
        self._create_message("resolve_symbol", ["chart", "ser_1", "=" + json.dumps(config)])
        self._create_message("create_series", ["chart", "$prices", "s1", "ser_1",
            self.override_resolution or self.TIMEFRAMES.get(interval, "1D"),
            self._calculate_bars(period, interval, None, None), ""])
        return pd.DataFrame({"Open": [1.0, 2.0], "High": [1.0, 2.0],
            "Low": [1.0, 2.0], "Close": [1.0, 2.0], "Volume": [100.0, 200.0]},
            index=pd.DatetimeIndex(["2026-10-20 09:45", "2026-10-20 18:00"], tz=IST))

    def close(self):
        self.closed = True


class BorsapyNativeGridTests(unittest.TestCase):
    def setUp(self):
        SdkStub.instances = []
        SdkStub.override_resolution = None
        SdkStub.override_adjustment = None
        self.request = FetchRequest("BIST:ALVES", Timeframe.M45, 600,
            datetime(2026, 10, 20, 21, tzinfo=IST))

    def provider(self, sdk_version="0.11.0"):
        return BorsapyNative45Provider(sdk_client_class=SdkStub, sdk_version=sdk_version)

    def test_explicit_native_resolution_keeps_auction_prices_without_mutating_sdk_mapping(self):
        original = dict(SdkStub.TIMEFRAMES)
        frame = self.provider().fetch_native_grid(self.request)
        self.assertEqual(SdkStub.TIMEFRAMES, original)
        self.assertNotIn("45m", SdkStub.TIMEFRAMES)
        self.assertEqual(frame.timeframe, Timeframe.M45)
        self.assertEqual(frame.price_basis, PriceBasis.SPLIT_ADJUSTED)
        self.assertEqual([bar.timestamp for bar in frame.bars], [
            datetime(2026, 10, 20, 6, 45, tzinfo=UTC), datetime(2026, 10, 20, 15, tzinfo=UTC)])
        self.assertEqual([(bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in frame.bars],
            [(1.0, 1.0, 1.0, 1.0, 100.0), (2.0, 2.0, 2.0, 2.0, 200.0)])
        client = SdkStub.instances[-1]
        series = [params for method, params in client.messages if method == "create_series"]
        self.assertEqual(series[0][4:6], ["45", 600])
        self.assertTrue(client.closed)

    def test_silent_daily_resolution_fallback_is_rejected_before_accepting_prices(self):
        SdkStub.override_resolution = "1D"
        with self.assertRaisesRegex(ValueError, "actual 45m resolution"):
            self.provider().fetch_native_grid(self.request)
        self.assertTrue(SdkStub.instances[-1].closed)

    def test_changed_sdk_price_basis_is_rejected(self):
        SdkStub.override_adjustment = "none"
        with self.assertRaisesRegex(ValueError, "price basis"):
            self.provider().fetch_native_grid(self.request)

    def test_unknown_sdk_version_and_non_45m_request_fail_before_client_creation(self):
        with self.assertRaisesRegex(ValueError, "SDK version"):
            self.provider("0.12.0").fetch_native_grid(self.request)
        with self.assertRaisesRegex(ValueError, "only explicit 45m"):
            self.provider().fetch_native_grid(FetchRequest("ALVES", Timeframe.D1, 600, self.request.as_of))
        self.assertEqual(SdkStub.instances, [])


if __name__ == "__main__":
    unittest.main()
