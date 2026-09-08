from __future__ import annotations

import math
from dataclasses import dataclass

from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.market_data.bars import CanonicalFrame

WILDER_ATR_14 = FeatureSpec(
    feature_id="volatility.atr.14",
    implementation="wilder_rma_true_range",
    version="1.0.0",
    parameters={"period": 14},
    warmup=WarmupSpec(bars=14, seed="first_true_range"),
)


@dataclass(frozen=True)
class AtrSeries:
    period: int
    values: tuple[float | None, ...]

    @property
    def latest(self) -> float | None:
        return self.values[-1] if self.values else None


def wilder_atr_series(frame: CanonicalFrame, period: int = 14) -> AtrSeries | None:
    if period < 1 or len(frame.bars) < period:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for bar in frame.bars:
        candidates = [bar.high - bar.low]
        if previous_close is not None:
            candidates.extend((abs(bar.high - previous_close), abs(bar.low - previous_close)))
        ranges.append(max(candidates))
        previous_close = bar.close

    current = ranges[0]
    alpha = 1.0 / period
    values: list[float | None] = []
    for index, observed in enumerate(ranges):
        if index:
            current = alpha * observed + (1.0 - alpha) * current
        values.append(current if index >= period - 1 else None)
    latest = values[-1]
    if latest is None or not math.isfinite(latest) or latest <= 0:
        return None
    return AtrSeries(period=period, values=tuple(values))


class WilderAtr14Provider:
    spec = WILDER_ATR_14

    def compute(self, frame: CanonicalFrame) -> AtrSeries | None:
        if frame.is_partial:
            return None
        return wilder_atr_series(frame, period=14)
