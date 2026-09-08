from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from market_intelligence.core.identity import stable_hash
from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.features.volatility import WILDER_ATR_14, AtrSeries, wilder_atr_series
from market_intelligence.market_data.bars import CanonicalFrame

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


@dataclass(frozen=True)
class MaQualification:
    ma_type: str
    period: int
    level_class: str
    touches: int
    quality_score: float
    research_version: str
    qualification_side: str = "both"


class MaQualificationSource(Protocol):
    def load(self, frame: CanonicalFrame) -> tuple[MaQualification, ...]: ...


def _ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    alpha = 2.0 / (period + 1.0)
    current = values[0]
    result: list[float | None] = []
    for index, value in enumerate(values):
        if index:
            current = alpha * value + (1.0 - alpha) * current
        result.append(current if index >= period - 1 else None)
    return result


def _rolling_wma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    denominator = period * (period + 1) / 2.0
    window_sum = sum(values[:period])
    weighted_sum = sum((index + 1) * value for index, value in enumerate(values[:period]))
    result[period - 1] = weighted_sum / denominator
    for index in range(period, len(values)):
        previous_sum = window_sum
        window_sum += values[index] - values[index - period]
        weighted_sum += period * values[index] - previous_sum
        result[index] = weighted_sum / denominator
    return result


def ma_series(
    ma_type: str,
    close: list[float],
    volume: list[float],
    period: int,
) -> list[float | None]:
    kind = ma_type.upper()
    if period < 2:
        raise ValueError("MA periyodu en az 2 olmalıdır")
    if kind == "SMA":
        result: list[float | None] = [None] * len(close)
        if len(close) < period:
            return result
        rolling = sum(close[:period])
        result[period - 1] = rolling / period
        for index in range(period, len(close)):
            rolling += close[index] - close[index - period]
            result[index] = rolling / period
        return result
    if kind == "EMA":
        return _ema(close, period)
    if kind == "WMA":
        return _rolling_wma(close, period)
    if kind == "VWMA":
        result = [None] * len(close)
        if len(close) < period:
            return result
        denominator = sum(volume[:period])
        numerator = sum(
            price * observed_volume
            for price, observed_volume in zip(close[:period], volume[:period], strict=True)
        )
        if denominator > 0:
            result[period - 1] = numerator / denominator
        for index in range(period, len(close)):
            denominator += volume[index] - volume[index - period]
            numerator += close[index] * volume[index]
            numerator -= close[index - period] * volume[index - period]
            if denominator > 0:
                result[index] = numerator / denominator
        return result
    if kind == "KAMA":
        result = [None] * len(close)
        if len(close) < period:
            return result
        current = sum(close[:period]) / period
        result[period - 1] = current
        fast, slow = 2.0 / 3.0, 2.0 / 31.0
        volatility = sum(
            abs(close[offset] - close[offset - 1]) for offset in range(1, period + 1)
        ) if len(close) > period else 0.0
        for index in range(period, len(close)):
            change = abs(close[index] - close[index - period])
            if index > period:
                volatility += abs(close[index] - close[index - 1])
                volatility -= abs(close[index - period] - close[index - period - 1])
            efficiency = change / volatility if volatility > 0 else 0.0
            smoothing = (efficiency * (fast - slow) + slow) ** 2
            current += smoothing * (close[index] - current)
            result[index] = current
        return result
    if kind == "ALMA":
        center = 0.85 * (period - 1)
        width = period / 6.0
        weights = [
            math.exp(-((index - center) ** 2) / (2.0 * width * width))
            for index in range(period)
        ]
        denominator = sum(weights)
        result = [None] * len(close)
        for index in range(period - 1, len(close)):
            window = close[index - period + 1 : index + 1]
            result[index] = sum(
                value * weight for value, weight in zip(window, weights, strict=True)
            ) / denominator
        return result
    if kind == "HMA":
        half = max(2, period // 2)
        root = max(2, int(math.sqrt(period)))
        half_values = _rolling_wma(close, half)
        full_values = _rolling_wma(close, period)
        combined: list[float] = []
        positions: list[int] = []
        for index, (half_value, full_value) in enumerate(
            zip(half_values, full_values, strict=True)
        ):
            if half_value is not None and full_value is not None:
                combined.append(2.0 * half_value - full_value)
                positions.append(index)
        smoothed = _rolling_wma(combined, root)
        result = [None] * len(close)
        for position, value in zip(positions, smoothed, strict=True):
            result[position] = value
        return result
    raise ValueError(f"Bilinmeyen MA türü: {ma_type}")


class QualifiedMaResearchProvider:
    spec = QUALIFIED_MA_PROXIMITY
    dependencies = (WILDER_ATR_14,)

    def __init__(self, source: MaQualificationSource, *, atr_period: int = 14) -> None:
        self.source = source
        self.atr_period = atr_period

    def compute(self, frame: CanonicalFrame) -> MaProximitySnapshot | None:
        atr_series = wilder_atr_series(frame, self.atr_period)
        return self._compute(frame, atr_series.latest if atr_series is not None else None)

    def compute_with_dependencies(
        self,
        frame: CanonicalFrame,
        values: dict[str, object],
    ) -> MaProximitySnapshot | None:
        atr_series = values.get(WILDER_ATR_14.feature_id)
        atr = atr_series.latest if isinstance(atr_series, AtrSeries) else None
        return self._compute(frame, atr)

    def _compute(self, frame: CanonicalFrame, atr: float | None) -> MaProximitySnapshot | None:
        qualifications = self.source.load(frame)
        if not qualifications or atr is None or frame.is_partial:
            return None
        close = [bar.close for bar in frame.bars]
        volume = [bar.volume for bar in frame.bars]
        current_price = close[-1]
        levels: list[QualifiedMaLevel] = []
        versions: set[str] = set()
        for qualification in qualifications:
            values = ma_series(
                qualification.ma_type,
                close,
                volume,
                qualification.period,
            )
            value = values[-1] if values else None
            if value is None or not math.isfinite(value):
                continue
            side = "support" if value <= current_price else "resistance"
            if qualification.qualification_side not in {"both", side}:
                continue
            levels.append(
                QualifiedMaLevel(
                    ma_type=qualification.ma_type,
                    period=qualification.period,
                    value=value,
                    side=side,
                    distance_atr=(value - current_price) / atr,
                    level_class=qualification.level_class,
                    touches=qualification.touches,
                    quality_score=qualification.quality_score,
                )
            )
            versions.add(qualification.research_version)
        if not levels:
            return None
        return MaProximitySnapshot(
            current_price=current_price,
            atr=atr,
            levels=tuple(levels),
            research_version=stable_hash(sorted(versions)),
        )


class UnavailableMaResearchProvider:
    """Explicit UNKNOWN until qualified MA Research data is wired for the frame."""

    spec = QUALIFIED_MA_PROXIMITY

    def compute(self, frame) -> None:
        return None
