from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from market_intelligence.core.identity import stable_hash


@dataclass(frozen=True)
class WarmupSpec:
    bars: int
    seed: str = "implementation_default"

    def __post_init__(self) -> None:
        if self.bars < 0:
            raise ValueError("Warmup bar sayısı negatif olamaz")


@dataclass(frozen=True)
class FeatureSpec:
    feature_id: str
    implementation: str
    version: str
    parameters: dict[str, Any] = field(default_factory=dict)
    warmup: WarmupSpec = field(default_factory=lambda: WarmupSpec(0))

    @property
    def identity_hash(self) -> str:
        return stable_hash(self)


@dataclass(frozen=True)
class FeatureSliceKey:
    instrument_id: str
    timeframe: str
    through_bar_time: str
    series_revision: int
    feature: FeatureSpec

    @property
    def cache_key(self) -> str:
        return stable_hash(self)
