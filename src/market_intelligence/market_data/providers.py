from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe


class TimestampKind(StrEnum):
    OPEN = "open"
    CLOSE = "close"


@dataclass(frozen=True)
class ProviderBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class ProviderFrame:
    provider: str
    provider_symbol: str
    timeframe: Timeframe
    timestamp_kind: TimestampKind
    timestamp_timezone: str
    price_basis: PriceBasis
    bars: tuple[ProviderBar, ...]
    last_bar_is_partial: bool = False

    def __post_init__(self) -> None:
        if not self.provider or not self.provider_symbol:
            raise ValueError("Provider ve provider sembolü zorunludur")
        if not self.timestamp_timezone:
            raise ValueError("Provider timestamp timezone açıkça belirtilmelidir")
        if not self.bars:
            raise ValueError("Provider frame boş olamaz")


@dataclass(frozen=True)
class FetchRequest:
    provider_symbol: str
    timeframe: Timeframe
    bars: int
    as_of: datetime


class MarketDataProvider(Protocol):
    name: str

    def fetch(self, request: FetchRequest) -> ProviderFrame: ...
