from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.market_data.bars import CachedDailyBars, CanonicalBar
from market_intelligence.market_data.providers import ProviderBar, ProviderFrame, TimestampKind
from market_intelligence.core.timeframes import Timeframe
from scripts.atc_telegram_briefings import make_daily_preview_frame

IST = ZoneInfo("Europe/Istanbul")


class PreviewOnlyStore:
    def __init__(self, cache):
        self.cache = cache
        self.writes = 0

    def load_recent_bars(self, **kwargs):
        return self.cache

    def save(self, *args, **kwargs):
        self.writes += 1
        raise AssertionError("Provisional market data must never be persisted")


class PreviewProvider:
    def __init__(self):
        self.source = None

    def fetch_from_source(self, source, request):
        self.source = source
        return ProviderFrame(
            provider=source,
            provider_symbol=request.provider_symbol,
            timeframe=Timeframe.D1,
            timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone="Europe/Istanbul",
            price_basis=PriceBasis.SPLIT_ADJUSTED,
            bars=(ProviderBar(
                timestamp=datetime(2026, 10, 15, 10, tzinfo=IST),
                open=100, high=103, low=99, close=101, volume=2000,
            ),),
        )


class PreviewIsolationTests(unittest.TestCase):
    def test_preview_calculates_from_actual_mutable_bar_without_db_save(self):
        last_day = datetime(2026, 10, 14, 10, tzinfo=IST)
        bars = []
        day = last_day - timedelta(days=45)
        while day.date() <= last_day.date():
            if day.weekday() < 5:
                bars.append(CanonicalBar(
                    open_time=day, close_time=day.replace(hour=18),
                    open=100, high=104, low=98, close=102, volume=1200,
                ))
            day += timedelta(days=1)
        cache = CachedDailyBars(
            source="borsapy",
            price_basis=PriceBasis.SPLIT_ADJUSTED,
            series_revision=1, bars=tuple(bars),
        )
        store = PreviewOnlyStore(cache)
        provider = PreviewProvider()
        settings = SimpleNamespace(runtime=SimpleNamespace(database_url="postgresql://unused"))
        member = SimpleNamespace(
            instrument_id="i", symbol="ATC_TEST", market="BIST",
            provider_symbol="ATC_TEST",
        )
        with patch("scripts.atc_telegram_briefings.PostgresSnapshotStore", return_value=store):
            with patch("scripts.atc_telegram_briefings._market_data_provider", return_value=provider):
                preview = make_daily_preview_frame(
                    object(), member, settings,
                    now=datetime(2026, 10, 15, 12, 45, tzinfo=IST),
                )
        self.assertEqual(preview.bars[-1].close, 101)
        self.assertEqual(preview.through_bar_time.hour, 18)
        self.assertEqual(preview.quality, "PROVISIONAL_WHAT_IF_NOT_PERSISTED")
        self.assertFalse(preview.is_partial)  # intentional formula-only projection
        self.assertEqual(store.writes, 0)
        self.assertEqual(provider.source, "borsapy")


if __name__ == "__main__":
    unittest.main()
