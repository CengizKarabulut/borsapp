"""When strict ATC scans fail on stale/invalid bars, try other real sources."""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.application.ingestion import IngestionRequest, IngestionService
from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.fallback import FallbackMarketDataProvider
from market_intelligence.market_data.providers import ProviderBar, ProviderFrame, TimestampKind

IST = ZoneInfo("Europe/Istanbul")
END = datetime(2026, 9, 7, 10, 15, tzinfo=IST)


class Vendor:
    def __init__(self, name: str, bar: ProviderBar) -> None:
        self.name = name
        self.bar = bar
        self.calls = 0

    def fetch(self, request):
        self.calls += 1
        return ProviderFrame(
            provider=self.name, provider_symbol=request.provider_symbol,
            timeframe=Timeframe.M15, timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone="Europe/Istanbul", price_basis=PriceBasis.RAW,
            bars=(self.bar,),
        )


class Store:
    def __init__(self):
        self.saved = []

    def latest_series_revision(self, **kwargs):
        return 0

    def save(self, frame):
        self.saved.append(frame)


def bar(date=7, *, valid=True):
    return ProviderBar(
        timestamp=datetime(2026, 9, date, 10, 0),
        open=10.0, high=11.0 if valid else 9.0,
        low=9.0, close=10.5, volume=100,
    )


def request():
    return IngestionRequest(
        instrument_id="id-1", symbol="TEST", provider_symbol="TEST",
        market="BIST", timeframe=Timeframe.M15, bars=60,
        as_of=END, series_revision=1, require_target_bar=True,
    )


class VerifiedFallbackTests(unittest.TestCase):
    def test_stale_vendor_is_replaced_with_same_close_from_real_backup(self):
        old, current = Vendor("stale", bar(date=4)), Vendor("fresh", bar())
        store = Store()
        result = IngestionService(
            provider=FallbackMarketDataProvider((old, current), prefer_complete_history=True),
            store=store,
        ).ingest(request())
        self.assertEqual(result.source, "fresh")
        self.assertEqual(result.through_bar_time, END)
        self.assertEqual((old.calls, current.calls), (1, 1))
        self.assertEqual(store.saved, [result])

    def test_inconsistent_ohlc_is_not_saved_if_backup_has_valid_candle(self):
        broken, backup = Vendor("broken", bar(valid=False)), Vendor("backup", bar())
        store = Store()
        result = IngestionService(
            provider=FallbackMarketDataProvider((broken, backup)), store=store,
        ).ingest(request())
        self.assertEqual(result.source, "backup")
        self.assertEqual(store.saved, [result])

    def test_no_valid_vendor_fails_closed_without_persisting_or_fabricating(self):
        store = Store()
        service = IngestionService(
            provider=FallbackMarketDataProvider(
                (Vendor("stale", bar(date=4)), Vendor("bad-ohlc", bar(valid=False)),
            ), store=store,
        )
        with self.assertRaisesRegex(RuntimeError, "No provider has a valid completed"):
            service.ingest(request())
        self.assertEqual(store.saved, [])


if __name__ == "__main__":
    unittest.main()
