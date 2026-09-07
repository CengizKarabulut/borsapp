from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.market_data.canonicalizer import Canonicalizer
from market_intelligence.market_data.providers import FetchRequest, MarketDataProvider

BASE_TIMEFRAME = {
    Timeframe.M5: Timeframe.M5,
    Timeframe.M15: Timeframe.M15,
    Timeframe.M30: Timeframe.M30,
    Timeframe.M45: Timeframe.M15,
    Timeframe.H1: Timeframe.H1,
    Timeframe.H2: Timeframe.H1,
    Timeframe.H4: Timeframe.H1,
    Timeframe.D1: Timeframe.D1,
}


class SnapshotStore(Protocol):
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
        raw = self.provider.fetch(
            FetchRequest(
                provider_symbol=request.provider_symbol,
                timeframe=base,
                bars=request.bars * multiplier,
                as_of=request.as_of,
            )
        )
        canonical = self.canonicalizer.build(
            instrument_id=request.instrument_id,
            symbol_at_snapshot=request.symbol,
            market=request.market,
            provider_frame=raw,
            target_timeframe=request.timeframe,
            series_revision=request.series_revision,
        )
        if canonical.through_bar_time > request.as_of:
            raise ValueError("Canonical snapshot gelecekte kapanan bar içeremez")
        self.store.save(canonical)
        return canonical
