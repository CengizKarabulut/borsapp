from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} timezone bilgisi içermelidir")


@dataclass(frozen=True)
class CanonicalBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        _require_aware(self.open_time, "open_time")
        _require_aware(self.close_time, "close_time")
        if self.close_time <= self.open_time:
            raise ValueError("Bar kapanış zamanı açılıştan sonra olmalıdır")
        if self.volume < 0:
            raise ValueError("Hacim negatif olamaz")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC fiyatları tutarsız")
        if self.high < self.low:
            raise ValueError("Bar yüksek fiyatı düşük fiyattan küçük olamaz")


@dataclass(frozen=True)
class CanonicalFrame:
    instrument_id: str
    symbol_at_snapshot: str
    market: str
    timeframe: Timeframe
    snapshot_id: str
    series_revision: int
    price_basis: PriceBasis
    source: str
    bars: tuple[CanonicalBar, ...]
    is_partial: bool = False
    quality: str = "complete"

    def __post_init__(self) -> None:
        if not self.bars:
            raise ValueError("Canonical frame en az bir bar içermelidir")
        closes = [bar.close_time for bar in self.bars]
        if closes != sorted(closes) or len(closes) != len(set(closes)):
            raise ValueError("Barlar benzersiz kapanış zamanına göre sıralı olmalıdır")
        if self.series_revision < 0:
            raise ValueError("series_revision negatif olamaz")

    @property
    def through_bar_time(self) -> datetime:
        return self.bars[-1].close_time
