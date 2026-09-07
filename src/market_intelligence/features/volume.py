from __future__ import annotations

import math
from dataclasses import dataclass

from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.market_data.bars import CanonicalFrame

RELATIVE_VOLUME_20 = FeatureSpec(
    feature_id="volume.relative.previous_mean",
    implementation="previous_complete_bars_mean",
    version="1.0.0",
    parameters={"window": 20, "min_history": 5, "exclude_current": True},
    warmup=WarmupSpec(bars=6, seed="not_applicable"),
)


@dataclass(frozen=True)
class VolumeActivity:
    observed_volume: float
    baseline_volume: float
    relative_volume: float
    average_turnover: float
    close: float
    baseline_bar_count: int


def calculate_volume_activity(
    frame: CanonicalFrame,
    *,
    window: int = 20,
    min_history: int = 5,
) -> VolumeActivity | None:
    """Compare the current bar with previous complete bars only."""
    if window < 1 or min_history < 1 or min_history > window:
        raise ValueError("Geçersiz hacim baseline ayarı")
    if frame.is_partial:
        return None
    history = frame.bars[:-1][-window:]
    if len(history) < min_history:
        return None
    baseline = sum(bar.volume for bar in history) / len(history)
    current = frame.bars[-1]
    turnover_bars = frame.bars[-window:]
    average_turnover = sum(bar.close * bar.volume for bar in turnover_bars) / len(turnover_bars)
    if baseline <= 0 or not math.isfinite(baseline):
        return None
    return VolumeActivity(
        observed_volume=current.volume,
        baseline_volume=baseline,
        relative_volume=current.volume / baseline,
        average_turnover=average_turnover,
        close=current.close,
        baseline_bar_count=len(history),
    )
