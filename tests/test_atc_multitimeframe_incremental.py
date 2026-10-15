from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.application.ingestion import IngestionRequest, IngestionService
from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CachedDailyBars
from market_intelligence.market_data.providers import ProviderBar, ProviderFrame, TimestampKind

ISTANBUL = ZoneInfo("Europe/Istanbul")


class Provider:
    name = "fixture"

    def __init__(self, base: Timeframe):
        self.base = base
        self.calls = []
        self.bars = []
        day = datetime(2026, 9, 1, 10, tzinfo=ISTANBUL)
        count = 0
        for _ in range(35):
            if day.weekday() < 5:
                start = day
                step = timedelta(minutes=base.minutes)
                for _part in range(480 // base.minutes):
                    n = count
                    self.bars.append(ProviderBar(
                        timestamp=start, open=100 + n * .001,
                        high=102 + n * .001, low=99 + n * .001,
                        close=101 + n * .001, volume=10000 + n,
                    ))
                    start += step
                    count += 1
            day += timedelta(days=1)

    def fetch(self, request):
        self.calls.append(request.bars)
        step = timedelta(minutes=self.base.minutes)
        bars = [bar for bar in self.bars if bar.timestamp + step <= request.as_of]
        return ProviderFrame(
            provider=self.name,
            provider_symbol=request.provider_symbol,
            timeframe=self.base,
            timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone="Europe/Istanbul",
            price_basis=PriceBasis.RAW,
            bars=tuple(bars[-request.bars:]),
        )

    def fetch_from_source(self, source, request):
        if source != self.name:
            raise RuntimeError("wrong source")
        return self.fetch(request)


class Store:
    def __init__(self):
        self.frames = []
        self.cache = None

    def latest_series_revision(self, **kwargs):
        return self.cache.series_revision if self.cache else 0

    def save(self, frame):
        self.frames.append(frame)
        self.cache = CachedDailyBars(
            source=frame.source, price_basis=frame.price_basis,
            series_revision=frame.series_revision, bars=frame.bars,
        )

    def load_recent_bars(self, *, instrument_id, as_of, limit, timeframe="1d"):
        if not self.cache:
            return None
        kept = tuple(b for b in self.cache.bars if b.close_time <= as_of)
        return CachedDailyBars(self.cache.source, self.cache.price_basis,
                               self.cache.series_revision, kept[-limit:])


class TimeframeCacheTests(unittest.TestCase):
    def _verify(self, base, target, count):
        provider = Provider(base)
        store = Store()
        service = IngestionService(provider=provider, store=store)
        closes = [bar.timestamp + timedelta(minutes=base.minutes) for bar in provider.bars]
        # End of an entire target bucket/session; ensure 2 closed target bars
        # exist in the new overlap after first historical snapshot.
        first_at = closes[-18]
        second_at = closes[-1]
        request = lambda when: IngestionRequest(
            instrument_id="i-1", symbol="TEST", provider_symbol="TEST", market="BIST",
            timeframe=target, bars=count, as_of=when, series_revision=1,
        )
        first = service.ingest(request(first_at))
        second = service.ingest(request(second_at))
        self.assertLess(provider.calls[1], provider.calls[0])
        self.assertGreaterEqual(len(second.bars), len(first.bars))
        self.assertEqual(second.source, first.source)
        self.assertEqual(second.bars[-1].close_time, second_at)
        self.assertEqual(second.bars[-2], store.cache.bars[-2])
        self.assertEqual(second.series_revision, first.series_revision)

    def test_direct_15m_uses_incremental_bars(self):
        self._verify(Timeframe.M15, Timeframe.M15, 100)

    def test_resampled_4h_uses_completed_hourly_buckets(self):
        self._verify(Timeframe.H1, Timeframe.H4, 30)


if __name__ == "__main__":
    unittest.main()
