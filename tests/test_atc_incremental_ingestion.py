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


def days(count: int = 625):
    date = datetime(2023, 1, 2, 10, tzinfo=ISTANBUL)
    dates = []
    while len(dates) < count:
        if date.weekday() < 5:
            dates.append(date)
        date += timedelta(days=1)
    return dates


DATES = days()


def sample_bars():
    return tuple(
        ProviderBar(
            timestamp=d, open=90 + i * 0.01,
            high=92 + i * 0.01, low=89 + i * 0.01,
            close=91 + i * 0.01, volume=100_000.0 + i,
        )
        for i, d in enumerate(DATES)
    )


class DailyProvider:
    name = "mock"
    def __init__(self):
        self.bars = sample_bars()
        self.calls = []
        self.provider_name = "mock"
        self.basis = PriceBasis.SPLIT_ADJUSTED

    def fetch(self, request):
        self.calls.append(request.bars)
        dated = [b for b in self.bars if b.timestamp.date() <= request.as_of.date()]
        return ProviderFrame(
            provider=self.provider_name, provider_symbol=request.provider_symbol,
            timeframe=request.timeframe, timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone="Europe/Istanbul", price_basis=self.basis,
            bars=tuple(dated[-request.bars:]),
        )


class PersistentStore:
    def __init__(self):
        self.frames = []
        self.cached = None

    def latest_series_revision(self, **_kwargs):
        return self.cached.series_revision if self.cached else 0

    def save(self, frame):
        self.frames.append(frame)
        self.cached = CachedDailyBars(
            source=frame.source, price_basis=frame.price_basis,
            series_revision=frame.series_revision, bars=frame.bars,
        )

    def load_recent_bars(self, *, instrument_id, as_of, limit):
        if not self.cached:
            return None
        subset = tuple(b for b in self.cached.bars if b.close_time <= as_of)
        if not subset:
            return None
        return CachedDailyBars(
            self.cached.source, self.cached.price_basis,
            self.cached.series_revision, subset[-limit:],
        )


def request(index):
    return IngestionRequest(
        instrument_id="instrument-1", symbol="TEST", provider_symbol="TEST",
        market="BIST", timeframe=Timeframe.D1, bars=600,
        as_of=DATES[index].replace(hour=19), series_revision=1,
    )


class IncrementalDailyIngestionTests(unittest.TestCase):
    def test_first_run_seeds_600_then_fetches_only_recent_overlap(self):
        provider, store = DailyProvider(), PersistentStore()
        service = IngestionService(provider=provider, store=store)
        first = service.ingest(request(623))
        second = service.ingest(request(624))
        self.assertEqual(provider.calls[0], 600)
        self.assertLess(provider.calls[1], 40)
        self.assertEqual(len(first.bars), 600)
        self.assertEqual(len(second.bars), 600)
        self.assertEqual(second.bars[-1].open_time.date(), DATES[624].date())
        self.assertEqual(second.bars[-2], first.bars[-1])
        self.assertEqual(store.cached.source, "mock")

    def test_changed_overlap_fails_closed_to_full_refresh(self):
        provider, store = DailyProvider(), PersistentStore()
        service = IngestionService(provider=provider, store=store)
        service.ingest(request(623))
        changed = list(provider.bars)
        original = changed[-3]
        changed[-3] = ProviderBar(
            timestamp=original.timestamp, open=original.open,
            high=original.high, low=original.low,
            close=original.close, volume=original.volume + 100,
        )
        provider.bars = tuple(changed)
        service.ingest(request(624))
        self.assertEqual(provider.calls, [600, 12, 600])

    def test_different_price_basis_never_stitches_cached_bars(self):
        provider, store = DailyProvider(), PersistentStore()
        service = IngestionService(provider=provider, store=store)
        service.ingest(request(623))
        provider.basis = PriceBasis.RAW
        frame = service.ingest(request(624))
        self.assertEqual(provider.calls, [600, 12, 600])
        self.assertEqual(frame.price_basis, PriceBasis.RAW)

    def test_provider_history_period_reduces_after_initial_seed(self):
        from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
        from market_intelligence.market_data.adapters.yfinance import YFinanceBistProvider

        provider = BorsapyProvider()
        self.assertEqual(provider._history_period(request(624).__class__(
            **{
                "provider_symbol": "ASELS",
                "timeframe": Timeframe.D1,
                "bars": 12,
                "as_of": request(624).as_of,
            }
        )), "1mo")
        self.assertEqual(YFinanceBistProvider.name, "yfinance")


if __name__ == "__main__":
    unittest.main()
