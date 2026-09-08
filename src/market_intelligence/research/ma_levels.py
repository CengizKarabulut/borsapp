from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import median

from market_intelligence.core.identity import stable_hash
from market_intelligence.features.ma import ma_series
from market_intelligence.features.volatility import wilder_atr_series
from market_intelligence.market_data.bars import CanonicalFrame

MA_TYPES = ("SMA", "EMA", "WMA", "VWMA", "KAMA", "ALMA", "HMA")
DEFAULT_PERIODS = (5, 8, 10, 13, 20, 21, 22, 34, 50, 55, 89, 100, 144, 200, 233, 377)


@dataclass(frozen=True)
class MaResearchConfig:
    ma_types: tuple[str, ...] = MA_TYPES
    periods: tuple[int, ...] = DEFAULT_PERIODS
    atr_period: int = 14
    touch_zone_atr: float = 0.20
    separation_atr: float = 2.0
    independence_bars: int = 20
    reaction_bars: int = 10
    hold_bars: int = 5
    break_atr: float = 0.50
    bounce_cap_atr: float = 4.0
    cross_cap_per_100: float = 8.0
    cross_damping: float = 0.60
    evidence_target_touches: int = 20
    strong_threshold: float = 50.0
    level_threshold: float = 38.0
    weak_threshold: float = 27.0

    def __post_init__(self) -> None:
        if not self.ma_types or not self.periods:
            raise ValueError("En az bir MA türü ve periyot gerekir")
        unknown = set(self.ma_types) - set(MA_TYPES)
        if unknown:
            raise ValueError("Bilinmeyen MA türleri: " + ", ".join(sorted(unknown)))
        if any(period < 2 for period in self.periods):
            raise ValueError("MA periyotları en az 2 olmalıdır")
        integers = (
            self.atr_period,
            self.independence_bars,
            self.reaction_bars,
            self.hold_bars,
            self.evidence_target_touches,
        )
        if any(value < 1 for value in integers):
            raise ValueError("MA Research bar eşikleri pozitif olmalıdır")
        if not self.strong_threshold >= self.level_threshold >= self.weak_threshold:
            raise ValueError("Seviye eşikleri azalan sırada olmalıdır")
        if not 0 <= self.cross_damping <= 1:
            raise ValueError("cross_damping 0 ile 1 arasında olmalıdır")
        if self.bounce_cap_atr <= 0 or self.cross_cap_per_100 <= 0:
            raise ValueError("Sıçrama ve kesişim tavanları sıfırdan büyük olmalıdır")
        if min(self.touch_zone_atr, self.separation_atr, self.break_atr) < 0:
            raise ValueError("MA Research ATR eşikleri negatif olamaz")

    @property
    def version(self) -> str:
        return stable_hash(
            {
                "implementation": "ma_level_observation_v1",
                "config": asdict(self),
            }
        )


@dataclass(frozen=True)
class ResearchedMaLevel:
    ma_type: str
    period: int
    qualification_side: str
    level_class: str
    touches: int
    quality_score: float
    research_version: str
    metrics: dict[str, float | int | None]


@dataclass(frozen=True)
class _Touch:
    position: int
    ma_value: float
    atr: float


def _cross_count(close: list[float], moving: list[float | None]) -> int:
    previous_sign: int | None = None
    crossings = 0
    for price, value in zip(close, moving, strict=True):
        if value is None:
            continue
        difference = price - value
        if difference == 0:
            continue
        sign = 1 if difference > 0 else -1
        if previous_sign is not None and sign != previous_sign:
            crossings += 1
        previous_sign = sign
    return crossings


def _touches(
    frame: CanonicalFrame,
    moving: list[float | None],
    atr: list[float | None],
    side: int,
    config: MaResearchConfig,
) -> list[_Touch]:
    result: list[_Touch] = []
    was_far = False
    previous_in_zone = False
    last_touch = -10**9
    # Preserve the legacy evidence boundary: a touch needs a full independent
    # observation window after it, even though the direct reaction metric uses
    # a shorter horizon.
    final_position = len(frame.bars) - config.independence_bars - 2
    for index in range(1, max(1, final_position)):
        bar = frame.bars[index]
        value = moving[index]
        atr_value = atr[index]
        if value is None or atr_value is None or atr_value <= 0:
            was_far = False
            previous_in_zone = False
            continue
        signed_distance = (bar.close - value) / atr_value
        zone = config.touch_zone_atr * atr_value
        in_zone = bar.low <= value + zone and bar.high >= value - zone
        if not in_zone:
            if side == 1 and signed_distance >= config.separation_atr:
                was_far = True
            elif side == 1 and bar.high < value - zone:
                was_far = False
            elif side == -1 and signed_distance <= -config.separation_atr:
                was_far = True
            elif side == -1 and bar.low > value + zone:
                was_far = False
        independent = index - last_touch > config.independence_bars
        if in_zone and not previous_in_zone and was_far and independent:
            result.append(_Touch(index, value, atr_value))
            last_touch = index
            was_far = False
        previous_in_zone = in_zone
    return result


def _metrics(
    frame: CanonicalFrame,
    touches: list[_Touch],
    *,
    side: int,
    valid_bars: int,
    cross_count: int,
    config: MaResearchConfig,
) -> dict[str, float | int | None]:
    bounces: list[float] = []
    penetrations: list[float] = []
    holds: list[bool] = []
    for touch in touches:
        start = touch.position + 1
        reaction = frame.bars[start : start + config.reaction_bars]
        holding = frame.bars[start : start + config.hold_bars]
        if not reaction:
            continue
        extreme = max(bar.high for bar in reaction) if side == 1 else min(
            bar.low for bar in reaction
        )
        bounces.append(side * (extreme - touch.ma_value) / touch.atr)
        if holding:
            adverse = min(bar.low for bar in holding) if side == 1 else max(
                bar.high for bar in holding
            )
            penetrations.append(max(0.0, side * (touch.ma_value - adverse) / touch.atr))
            breaches = [side * (touch.ma_value - bar.close) / touch.atr for bar in holding]
            holds.append(max(breaches) <= config.break_atr)
    count = len(bounces)
    bars = max(valid_bars, 1)
    if not count:
        return {
            "level_touches": 0,
            "touch_density_per_100": 0.0,
            "cross_per_100": 100.0 * cross_count / bars,
            "median_bounce_atr": None,
            "median_penetration_atr": None,
            "hold_rate_pct": None,
        }
    return {
        "level_touches": count,
        "touch_density_per_100": 100.0 * count / bars,
        "cross_per_100": 100.0 * cross_count / bars,
        "median_bounce_atr": float(median(bounces)),
        "median_penetration_atr": float(median(penetrations)) if penetrations else None,
        "hold_rate_pct": 100.0 * sum(holds) / len(holds) if holds else None,
    }


def _score(metrics: dict[str, float | int | None], config: MaResearchConfig) -> float:
    touches = int(metrics["level_touches"] or 0)
    if not touches:
        return 0.0
    evidence = min(touches / config.evidence_target_touches, 1.0) * 25.0
    hold = max(0.0, min(float(metrics["hold_rate_pct"] or 0), 100.0)) / 100.0 * 30.0
    bounce = max(
        0.0,
        min(float(metrics["median_bounce_atr"] or 0), config.bounce_cap_atr),
    ) / config.bounce_cap_atr * 25.0
    quality = (evidence + hold + bounce) / 80.0 * 100.0
    crossing = max(
        0.0,
        min(float(metrics["cross_per_100"] or 0), config.cross_cap_per_100),
    )
    cleanliness = 1.0 - config.cross_damping * crossing / config.cross_cap_per_100
    return round(quality * cleanliness, 2)


def _level_class(touches: int, score: float, config: MaResearchConfig) -> str:
    if touches < max(3, config.evidence_target_touches // 4):
        return "insufficient_touches"
    if score >= config.strong_threshold:
        return "strong_level"
    if score >= config.level_threshold:
        return "level"
    if score >= config.weak_threshold:
        return "weak_level"
    return "not_level"


def research_ma_levels(
    frame: CanonicalFrame,
    config: MaResearchConfig | None = None,
) -> tuple[ResearchedMaLevel, ...]:
    """Classify each MA from closed historical observations only."""

    resolved = config or MaResearchConfig()
    if frame.is_partial:
        raise ValueError("MA Research kısmi canonical frame üzerinde çalışamaz")
    close = [bar.close for bar in frame.bars]
    volume = [bar.volume for bar in frame.bars]
    atr_snapshot = wilder_atr_series(frame, resolved.atr_period)
    atr = list(atr_snapshot.values) if atr_snapshot is not None else [None] * len(frame.bars)
    levels: list[ResearchedMaLevel] = []
    for ma_type in resolved.ma_types:
        for period in resolved.periods:
            moving = ma_series(ma_type, close, volume, period)
            valid_bars = sum(value is not None and math.isfinite(value) for value in moving)
            if not valid_bars:
                continue
            crossings = _cross_count(close, moving)
            candidates: list[ResearchedMaLevel] = []
            for side, label in ((1, "support"), (-1, "resistance")):
                touches = _touches(frame, moving, atr, side, resolved)
                metrics = _metrics(
                    frame,
                    touches,
                    side=side,
                    valid_bars=valid_bars,
                    cross_count=crossings,
                    config=resolved,
                )
                score = _score(metrics, resolved)
                count = int(metrics["level_touches"] or 0)
                candidates.append(
                    ResearchedMaLevel(
                        ma_type=ma_type,
                        period=period,
                        qualification_side=label,
                        level_class=_level_class(count, score, resolved),
                        touches=count,
                        quality_score=score,
                        research_version=resolved.version,
                        metrics=metrics,
                    )
                )
            levels.append(max(candidates, key=lambda item: (item.quality_score, item.touches)))
    return tuple(levels)
