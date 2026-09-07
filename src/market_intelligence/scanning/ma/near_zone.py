from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.ma import (
    QUALIFIED_MA_PROXIMITY,
    MaProximitySnapshot,
    QualifiedMaLevel,
)
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext


@dataclass(frozen=True)
class MaNearZoneConfig:
    maximum_distance_atr: float = 1.0
    accepted_level_classes: tuple[str, ...] = ("strong_level", "level")
    maximum_levels_per_side: int = 2

    def __post_init__(self) -> None:
        if self.maximum_distance_atr < 0 or self.maximum_levels_per_side < 1:
            raise ValueError("MA yakınlık ayarları geçersiz")


class MaNearZoneScanner:
    id = "ma.near_zone"
    family = "ma"
    version = "1.0.0"
    result_kind = ResultKind.STATE
    supported_timeframes = set(Timeframe)
    required_features = (QUALIFIED_MA_PROXIMITY,)
    accepts_partial_bars = False

    def __init__(self, config: MaNearZoneConfig | None = None) -> None:
        self.config = config or MaNearZoneConfig()

    def _candidates(self, context: ScanContext) -> tuple[QualifiedMaLevel, ...]:
        snapshot = context.feature_values.get(QUALIFIED_MA_PROXIMITY.feature_id)
        if not isinstance(snapshot, MaProximitySnapshot):
            return ()
        accepted = {
            value.strip().casefold() for value in self.config.accepted_level_classes
        }
        candidates = [
            level
            for level in snapshot.levels
            if level.active_side
            and level.level_class.strip().casefold() in accepted
            and abs(level.distance_atr) <= self.config.maximum_distance_atr
        ]
        selected: list[QualifiedMaLevel] = []
        for side in ("support", "resistance"):
            matching = sorted(
                (level for level in candidates if level.side.casefold() == side),
                key=lambda level: (-level.quality_score, abs(level.distance_atr)),
            )
            selected.extend(matching[: self.config.maximum_levels_per_side])
        return tuple(selected)

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        return bool(self._candidates(context))

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        snapshot = context.feature_values.get(QUALIFIED_MA_PROXIMITY.feature_id)
        if not isinstance(snapshot, MaProximitySnapshot):
            return ()
        next_bar = context.declared_dependencies.get("next_bar_close_time")
        valid_until = next_bar if isinstance(next_bar, datetime) else None
        findings: list[Finding] = []
        for level in self._candidates(context):
            side = level.side.casefold()
            direction = Direction.BULLISH if side == "support" else Direction.BEARISH
            findings.append(
                Finding(
                    finding_key=f"near-zone:{level.level_id}",
                    state_key=level.level_id,
                    instrument_id=frame.instrument_id,
                    symbol_at_event=frame.symbol_at_snapshot,
                    timeframe=frame.timeframe,
                    scanner_id=self.id,
                    scanner_version=self.version,
                    ruleset_hash=context.ruleset_hash,
                    kind=self.result_kind,
                    bar_time=context.bar_close_time,
                    direction=direction,
                    metrics={
                        "ma_type": level.ma_type,
                        "period": level.period,
                        "side": side,
                        "ma_value": level.value,
                        "current_price": snapshot.current_price,
                        "atr": snapshot.atr,
                        "distance_atr": level.distance_atr,
                        "level_class": level.level_class,
                        "touches": level.touches,
                        "quality_score": level.quality_score,
                        "research_version": snapshot.research_version,
                    },
                    evidence=(
                        "Yakınlık ATR cinsinden ölçüldü.",
                        "Seviye MA Research tarihsel kalite filtresini önceden geçti.",
                    ),
                    valid_from=context.bar_close_time,
                    valid_until=valid_until,
                )
            )
        return tuple(findings)
