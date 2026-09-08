from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.decision import (
    DECISION_PANEL_V645,
    DecisionPanelSnapshot,
)
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext


@dataclass(frozen=True)
class DecisionPanelV645Config:
    minimum_score: int = 75

    def __post_init__(self) -> None:
        if self.minimum_score != 75:
            raise ValueError("v6.4.5 parity sözleşmesinde minimum_score 75 olmalıdır")


class DecisionPanelV645Scanner:
    id = "decision.panel_v645"
    family = "decision"
    version = "6.4.5"
    result_kind = ResultKind.EVENT
    supported_timeframes = {Timeframe.D1}
    required_features = (DECISION_PANEL_V645,)
    accepts_partial_bars = False

    def __init__(self, config: DecisionPanelV645Config | None = None) -> None:
        self.config = config or DecisionPanelV645Config()

    @staticmethod
    def _snapshot(context: ScanContext) -> DecisionPanelSnapshot | None:
        value = context.feature_values.get(DECISION_PANEL_V645.feature_id)
        return value if isinstance(value, DecisionPanelSnapshot) else None

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        snapshot = self._snapshot(context)
        return bool(snapshot and snapshot.entry and snapshot.score >= self.config.minimum_score)

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        snapshot = self._snapshot(context)
        if snapshot is None or not self.prefilter(frame, context):
            return ()
        return (
            Finding(
                finding_key=f"entry:{snapshot.new_setup.casefold().replace(' ', '-')}",
                instrument_id=frame.instrument_id,
                symbol_at_event=frame.symbol_at_snapshot,
                timeframe=frame.timeframe,
                scanner_id=self.id,
                scanner_version=self.version,
                ruleset_hash=context.ruleset_hash,
                kind=self.result_kind,
                bar_time=context.bar_close_time,
                direction=Direction.BULLISH,
                metrics={
                    "setup": snapshot.new_setup,
                    "active_setup": snapshot.active_setup,
                    "score": snapshot.score,
                    "relative_volume": snapshot.relative_volume,
                    "pct20": snapshot.pct20,
                    "adx": snapshot.adx,
                    "pullback_guard": snapshot.pullback_guard,
                    "pullback_base": snapshot.pullback_base,
                },
                evidence=(
                    "Taramabot Karar Paneli v6.4.5 causal giriş koşulları sağlandı.",
                    "Pullback için RVOL ≤ 2.0 ve 20 bar zirvesine yakınlık filtresi uygulandı.",
                ),
            ),
        )
