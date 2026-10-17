"""Real vendor selection must prefer valid completed candles over stale length."""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.application.ingestion import IngestionRequest, IngestionService
from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.fallback import FallbackMarketDataProvider
from market_intelligence.market_data.providers import ProviderBar, ProviderFrame, TimestampKind

TZ = ZoneInfo("Europe/Istanbul")
TARGET = datetime(2026, 10, 16, 18, tzinfo=TZ)


def frame(source, days, *, malformed=False):
    return ProviderFrame(
        provider=source, provider_symbol="SAMPLE",
        timeframe=Timeframe.D1, timestamp_kind=TimestampKind.OPEN,
        timestamp_timezone="Europe/Istanbul", price_basis=PriceBasis.RAW,
        bars=tuple(
            ProviderBar(
                timestamp=datetime(2026, 10, day, 10, tzinfo=TZ),
                open=10.0, high=9.0 if malformed else 12.0,
                low=8.0, close=11.0, volume=100.0,
            )
            for day in days
        ),
    )


class StubProvider:
    def __init__(self, name, raw):
        self.name = name
        self.raw = raw
        self.calls = 0

    def fetch(self, request):
        self.calls += 1
        return self.raw


class StubStore:
    def __init__(self):
        self.frames = []

    def save(self, value):
        self.frames.append(value)

    def latest_series_revision(self, **kwargs):
        return 0


def scan_request():
    return IngestionRequest(
        instrument_id="sample-id", symbol="SAMPLE",
        provider_symbol="SAMPLE", market="BIST",
        timeframe=Timeframe.D1, bars=3,
        as_of=TARGET, series_revision=1,
    )


class FreshVendorTests(unittest.TestCase):
    def test_stale_long_history_does_not_hide_fresh_short_vendor(self):
        stale = StubProvider("stale", frame("stale", (12, 13, 14, 15)))
        fresh = StubProvider("fresh", frame("fresh", (15, 16)))
        chain = FallbackMarketDataProvider(
            (stale, fresh), prefer_complete_history=True,
        )
        store = StubStore()
        result = IngestionService(provider=chain, store=store).ingest(scan_request())
        self.assertEqual(result.source, "fresh")
        self.assertEqual(result.through_bar_time, TARGET)
        self.assertEqual((stale.calls, fresh.calls), (1, 1))
        self.assertEqual(store.frames, [result])

    def test_invalid_ohlc_vendor_falls_back_without_price_fabrication(self):
        invalid = StubProvider("invalid", frame("invalid", (15, 16), malformed=True))
        fresh = StubProvider("fresh", frame("fresh", (15, 16)))
        chain = FallbackMarketDataProvider((invalid, fresh), prefer_complete_history=True)
        result = IngestionService(provider=chain, store=StubStore()).ingest(scan_request())
        self.assertEqual(result.source, "fresh")
        self.assertEqual(invalid.calls, 1)

    def test_all_stale_sources_fail_closed_without_saving(self):
        first = StubProvider("first", frame("first", (12, 13, 14)))
        second = StubProvider("second", frame("second", (14, 15)))
        store = StubStore()
        chain = FallbackMarketDataProvider((first, second), prefer_complete_history=True)
        with self.assertRaisesRegex(RuntimeError, "No provider supplied an authentic"):
            IngestionService(provider=chain, store=store).ingest(scan_request())
        self.assertEqual(store.frames, [])


if __name__ == "__main__":
    unittest.main()
