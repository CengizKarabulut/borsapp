from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CachedDailyBars, CanonicalFrame
from market_intelligence.market_data.canonicalizer import Canonicalizer
from market_intelligence.market_data.errors import SeriesRevisionConflict
from market_intelligence.market_data.providers import (
    FetchRequest,
    MarketDataProvider,
    ProviderBar,
    ProviderFrame,
    TimestampKind,
)

BASE_TIMEFRAME = {
    Timeframe.M5: Timeframe.M5,
    Timeframe.M15: Timeframe.M15,
    Timeframe.M30: Timeframe.M30,
    Timeframe.M45: Timeframe.M15,
    Timeframe.H1: Timeframe.H1,
    Timeframe.H2: Timeframe.H1,
    Timeframe.H4: Timeframe.H1,
    Timeframe.D1: Timeframe.D1,
    Timeframe.W1: Timeframe.D1,
}


class SnapshotStore(Protocol):
    def latest_series_revision(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        source: str,
        price_basis: str,
    ) -> int: ...

    def save(self, frame: CanonicalFrame) -> None: ...


@dataclass(frozen=True)
class IngestionRequest:
    instrument_id: str
    symbol: str
    provider_symbol: str
    market: str
    timeframe: Timeframe
    bars: int
    as_of: datetime
    series_revision: int


class IngestionService:
    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        store: SnapshotStore,
        canonicalizer: Canonicalizer | None = None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.canonicalizer = canonicalizer or Canonicalizer()

    def _cached_daily_fetch(self, request: IngestionRequest) -> ProviderFrame | None:
        """Fetch a small overlap when the durable daily cache already exists.

        Backfill the complete requested window if source/basis changes, if
        overlapping OHLCV was revised, or if the provider has an unexpected
        gap. It is unsafe to stitch different vendors or price bases together.
        """
        load = getattr(self.store, "load_recent_bars", None)
        if not callable(load) or request.timeframe is not Timeframe.D1:
            return None
        if request.bars < 40:
            return None
        cache: CachedDailyBars | None = load(
            instrument_id=request.instrument_id,
            as_of=request.as_of,
            limit=request.bars,
        )
        if cache is None or len(cache.bars) < 30:
            return None
        revision = self.store.latest_series_revision(
            instrument_id=request.instrument_id,
            timeframe="1d",
            source=cache.source,
            price_basis=cache.price_basis.value,
        )
        if revision != cache.series_revision:
            # The most recent timestamp must also belong to the latest
            # immutable corporate-action/price-adjustment revision.
            return None
        days = (request.as_of.date() - cache.bars[-1].close_time.date()).days
        if days < 0:
            return None
        overlap_bars = min(request.bars, max(12, days + 10))
        try:
            raw = self.provider.fetch(
                FetchRequest(
                    provider_symbol=request.provider_symbol,
                    timeframe=Timeframe.D1,
                    bars=overlap_bars,
                    as_of=request.as_of,
                )
            )
            if raw.provider != cache.source or raw.price_basis != cache.price_basis:
                return None
            recent = self.canonicalizer.build(
                instrument_id=request.instrument_id,
                symbol_at_snapshot=request.symbol,
                market=request.market,
                provider_frame=raw,
                target_timeframe=Timeframe.D1,
                series_revision=cache.series_revision,
            )
            if recent.through_bar_time > request.as_of:
                raise ValueError("Incremental provider returned a future closed candle")
            prior = {b.close_time: b for b in cache.bars}
            shared = [b for b in recent.bars if b.close_time in prior]
            # Without an overlap we cannot verify continuity or revisions.
            if len(shared) < 2 or any(prior[b.close_time] != b for b in shared):
                return None
            combined = {b.close_time: b for b in cache.bars}
            combined.update({b.close_time: b for b in recent.bars})
            merged = tuple(sorted(combined.values(), key=lambda b: b.close_time))[
                -request.bars:
            ]
            return ProviderFrame(
                provider=raw.provider,
                provider_symbol=raw.provider_symbol,
                timeframe=Timeframe.D1,
                timestamp_kind=TimestampKind.OPEN,
                timestamp_timezone=raw.timestamp_timezone,
                price_basis=raw.price_basis,
                bars=tuple(
                    ProviderBar(
                        timestamp=b.open_time, open=b.open, high=b.high,
                        low=b.low, close=b.close, volume=b.volume,
                    )
                    for b in merged
                ),
                last_bar_is_partial=False,
            )
        except (ValueError, RuntimeError):
            # A broken recent fetch should not silently promote cached data
            # as a fresh scan; the full fetch below must succeed on its own.
            return None

    def ingest(self, request: IngestionRequest) -> CanonicalFrame:
        try:
            base = BASE_TIMEFRAME[request.timeframe]
        except KeyError as exc:
            raise ValueError(
                "Haftalık/aylık ingestion point-in-time takvim adapter'ı gerektirir"
            ) from exc
        multiplier = 1
        if request.timeframe.minutes and base.minutes:
            multiplier = max(request.timeframe.minutes // base.minutes, 1)
        if request.timeframe is Timeframe.W1:
            multiplier = 5
        raw = self._cached_daily_fetch(request)
        if raw is None:
            raw = self.provider.fetch(
                FetchRequest(
                    provider_symbol=request.provider_symbol,
                    timeframe=base,
                    bars=request.bars * multiplier + (10 if request.timeframe is Timeframe.W1 else 0),
                    as_of=request.as_of,
                )
            )
        series_revision = max(
            request.series_revision,
            self.store.latest_series_revision(
                instrument_id=request.instrument_id,
                timeframe=request.timeframe.value,
                source=raw.provider,
                price_basis=raw.price_basis.value,
            ),
        )
        for _attempt in range(3):
            canonical = self.canonicalizer.build(
                instrument_id=request.instrument_id,
                symbol_at_snapshot=request.symbol,
                market=request.market,
                provider_frame=raw,
                target_timeframe=request.timeframe,
                series_revision=series_revision,
            )
            if canonical.through_bar_time > request.as_of:
                raise ValueError("Canonical snapshot gelecekte kapanan bar içeremez")
            try:
                self.store.save(canonical)
            except SeriesRevisionConflict:
                latest = self.store.latest_series_revision(
                    instrument_id=request.instrument_id,
                    timeframe=request.timeframe.value,
                    source=raw.provider,
                    price_basis=raw.price_basis.value,
                )
                series_revision = max(series_revision, latest) + 1
                continue
            return canonical
        raise SeriesRevisionConflict("Canonical seri revizyonu üç denemede çözülemedi")
