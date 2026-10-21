from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
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
        provider = TvDatafeedBistProvider(client=stub, naive_timestamp_timezone="UTC")
        request = FetchRequest(
            "ASELS.IS", Timeframe.D1, 600,
            datetime(2026, 10, 14, 17, 30, tzinfo=ISTANBUL),
        )
        with patch.dict(sys.modules, {"tvDatafeed": fake_module}):
            result = provider.fetch(request)

        self.assertEqual(result.provider, "tvdatafeed")
        self.assertEqual(result.provider_symbol, "BIST:ASELS")
        self.assertEqual(result.price_basis, PriceBasis.SPLIT_ADJUSTED)
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
            result = TvDatafeedBistProvider(client=stub, naive_timestamp_timezone="UTC").fetch(request)
        self.assertEqual(len(result.bars), 2)

    def test_native_45m_preserves_actual_auction_grid_and_ohlcv_without_reanchoring(self):
        source = candles()
        source.index = pd.DatetimeIndex(["2026-10-20 09:45:00", "2026-10-20 18:00:00"])
        original = source.copy(deep=True)
        stub = TvStub(source)
        fake_module = SimpleNamespace(Interval=SimpleNamespace(in_45_minute="45"), TvDatafeed=lambda: stub)
        provider = TvDatafeedBistProvider(client=stub, naive_timestamp_timezone="Europe/Istanbul")
        request = FetchRequest("BIST:ALVES", Timeframe.M45, 600,
            datetime(2026, 10, 20, 21, tzinfo=ISTANBUL))
        with patch.dict(sys.modules, {"tvDatafeed": fake_module}):
            frame = provider.fetch_native_grid(request)
        self.assertEqual(stub.requests[0]["interval"], "45")
        self.assertEqual(frame.timeframe, Timeframe.M45)
        self.assertEqual(frame.price_basis, PriceBasis.SPLIT_ADJUSTED)
        self.assertEqual([bar.timestamp.astimezone(ISTANBUL).strftime("%H:%M") for bar in frame.bars],
            ["09:45", "18:00"])
        for bar, (_, row) in zip(frame.bars, source.iterrows(), strict=True):
            self.assertEqual((bar.open, bar.high, bar.low, bar.close, bar.volume),
                tuple(float(row[column]) for column in ("open", "high", "low", "close", "volume")))
            self.assertEqual(bar.timestamp.tzinfo, UTC)
        pd.testing.assert_frame_equal(source, original)
        with self.assertRaisesRegex(ValueError, "explicit native-grid"):
            provider.fetch(request)

    def test_native_45m_utc_and_istanbul_naive_clocks_produce_same_actual_instants(self):
        outputs = []
        for zone, opened in (("UTC", "2026-10-20 06:45:00"),
                             ("Europe/Istanbul", "2026-10-20 09:45:00")):
            data = candles().iloc[:1].copy()
            data.index = pd.DatetimeIndex([opened])
            stub = TvStub(data)
            module = SimpleNamespace(Interval=SimpleNamespace(in_45_minute="45"), TvDatafeed=lambda stub=stub: stub)
            request = FetchRequest("ALVES", Timeframe.M45, 1,
                datetime(2026, 10, 20, 21, tzinfo=ISTANBUL))
            with patch.dict(sys.modules, {"tvDatafeed": module}):
                outputs.append(TvDatafeedBistProvider(client=stub,
                    naive_timestamp_timezone=zone).fetch_native_grid(request).bars)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0][0].timestamp, datetime(2026, 10, 20, 6, 45, tzinfo=UTC))

    def test_real_sdk_fromtimestamp_host_clock_roundtrips_without_fixed_utc_assumption(self):
        instant = datetime(2026, 10, 20, 7, tzinfo=UTC)
        data = candles().iloc[:1].copy()
        # Exactly the installed SDK's conversion: host-local naive, on both
        # Windows/Istanbul and GitHub/Linux/UTC, for the same epoch instant.
        data.index = pd.DatetimeIndex([datetime.fromtimestamp(instant.timestamp())])
        stub = TvStub(data)
        module = SimpleNamespace(Interval=SimpleNamespace(in_15_minute="15"), TvDatafeed=lambda: stub)
        request = FetchRequest("ASELS", Timeframe.M15, 1,
            datetime(2026, 10, 20, 11, tzinfo=ISTANBUL))
        with patch.dict(sys.modules, {"tvDatafeed": module}):
            frame = TvDatafeedBistProvider(client=stub).fetch(request)
        self.assertEqual(frame.bars[0].timestamp, instant)

    def test_native_grid_rejects_wrong_interval_or_duplicate_actual_timestamps(self):
        request = FetchRequest("ALVES", Timeframe.M15, 10,
            datetime(2026, 10, 20, 21, tzinfo=ISTANBUL))
        with self.assertRaisesRegex(ValueError, "only explicit 45m"):
            TvDatafeedBistProvider().fetch_native_grid(request)
        data = candles()
        data.index = pd.DatetimeIndex(["2026-10-20 09:45:00"] * 2)
        stub = TvStub(data)
        module = SimpleNamespace(Interval=SimpleNamespace(in_45_minute="45"), TvDatafeed=lambda: stub)
        with patch.dict(sys.modules, {"tvDatafeed": module}), self.assertRaisesRegex(ValueError, "unique actual"):
            TvDatafeedBistProvider(client=stub, naive_timestamp_timezone="Europe/Istanbul").fetch_native_grid(
                FetchRequest("ALVES", Timeframe.M45, 10, request.as_of))

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
