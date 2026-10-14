from __future__ import annotations

import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.fallback import FallbackMarketDataProvider
from market_intelligence.market_data.adapters.tvdatafeed import TvDatafeedBistProvider
from market_intelligence.market_data.providers import FetchRequest

ISTANBUL = ZoneInfo("Europe/Istanbul")


class TvStub:
    def __init__(self, data):
        self.data = data
        self.requests = []

    def get_hist(self, **kwargs):
        self.requests.append(kwargs)
        return self.data


def candles():
    # Simulate TradingView UTC-naive index on an Ubuntu GitHub UTC runner.
    idx = pd.DatetimeIndex(["2026-10-13 07:00:00", "2026-10-14 07:00:00"])
    return pd.DataFrame(
        {
            "open": [10.0, 11.0],
            "high": [12.0, 13.0],
            "low": [9.0, 10.0],
            "close": [11.0, 12.0],
            "volume": [1000.0, 2000.0],
        },
        index=idx,
    )


class ThirdProviderTests(unittest.TestCase):
    def test_tvdatafeed_fetches_bist_daily_and_drops_unclosed_candle(self):
        stub = TvStub(candles())
        fake_module = SimpleNamespace(
            Interval=SimpleNamespace(in_daily="D"),
            TvDatafeed=lambda: stub,
        )
        provider = TvDatafeedBistProvider(client=stub)
        request = FetchRequest(
            "ASELS.IS", Timeframe.D1, 600,
            datetime(2026, 10, 14, 17, 30, tzinfo=ISTANBUL),
        )
        with patch.dict(sys.modules, {"tvDatafeed": fake_module}):
            result = provider.fetch(request)

        self.assertEqual(result.provider, "tvdatafeed")
        self.assertEqual(result.provider_symbol, "BIST:ASELS")
        self.assertEqual(result.price_basis, PriceBasis.RAW)
        self.assertEqual(len(result.bars), 1)
        self.assertEqual(result.bars[0].timestamp.astimezone(ISTANBUL).hour, 10)
        self.assertEqual(stub.requests[0]["symbol"], "ASELS")
        self.assertEqual(stub.requests[0]["exchange"], "BIST")

    def test_last_confirmed_candle_is_available_after_auction(self):
        stub = TvStub(candles())
        fake_module = SimpleNamespace(
            Interval=SimpleNamespace(in_daily="D"),
            TvDatafeed=lambda: stub,
        )
        request = FetchRequest(
            "ASELS", Timeframe.D1, 600,
            datetime(2026, 10, 14, 18, 45, tzinfo=ISTANBUL),
        )
        with patch.dict(sys.modules, {"tvDatafeed": fake_module}):
            result = TvDatafeedBistProvider(client=stub).fetch(request)
        self.assertEqual(len(result.bars), 2)

    def test_fallback_order_and_same_source_incremental_refresh(self):
        calls = []

        class Stub:
            def __init__(self, name, *, fails=False):
                self.name = name
                self.fails = fails

            def fetch(self, request):
                calls.append(self.name)
                if self.fails:
                    raise RuntimeError("unavailable")
                return SimpleNamespace(provider=self.name, bars=tuple(range(60)))

        chain = FallbackMarketDataProvider(
            (
                Stub("borsapy", fails=True),
                Stub("tvdatafeed"),
                Stub("yfinance"),
            ),
            prefer_complete_history=True,
        )
        request = FetchRequest(
            "ASELS", Timeframe.D1, 50,
            datetime(2026, 10, 14, 18, 45, tzinfo=ISTANBUL),
        )
        result = chain.fetch(request)
        self.assertEqual(result.provider, "tvdatafeed")
        self.assertEqual(calls, ["borsapy", "tvdatafeed"])
        calls.clear()
        result = chain.fetch_from_source("tvdatafeed", request)
        self.assertEqual(result.provider, "tvdatafeed")
        self.assertEqual(calls, ["tvdatafeed"])
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            chain.fetch_from_source("fake", request)


if __name__ == "__main__":
    unittest.main()
