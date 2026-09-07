from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.features.specs import FeatureSpec, WarmupSpec

QUALIFIED_MA_PROXIMITY = FeatureSpec(
    feature_id="ma.qualified_proximity",
    implementation="ma_research_level_registry_v1",
    version="1.0.0",
    parameters={
        "distance_unit": "atr",
        "qualification_source": "historical_level_research",
    },
    warmup=WarmupSpec(bars=0, seed="precomputed_research_state"),
)


@dataclass(frozen=True)
class QualifiedMaLevel:
    ma_type: str
    period: int
    value: float
    side: str
    distance_atr: float
    level_class: str
    touches: int
    quality_score: float
    active_side: bool = True

    @property
    def level_id(self) -> str:
        return f"{self.ma_type.upper()}:{self.period}:{self.side.casefold()}"


@dataclass(frozen=True)
class MaProximitySnapshot:
    current_price: float
    atr: float
    levels: tuple[QualifiedMaLevel, ...]
    research_version: str
