from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.momentum import (
    MACD_12_26_9,
    RSI_14,
    MacdSnapshot,
    RsiSnapshot,
)
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext


class MacdTriggerMode(StrEnum):
    LEGACY_RISING_OR_CROSS = "legacy_rising_or_cross"
    STRICT_CROSS = "strict_cross"


@dataclass(frozen=True)
class MacdPositiveCrossConfig:
    minimum_rsi: float = 30.0
    require_positive_macd: bool = True
    trigger_mode: MacdTriggerMode = MacdTriggerMode.LEGACY_RISING_OR_CROSS


class MacdPositiveCrossScanner:
    id = "signal.macd_positive_cross"
    family = "signal"
    version = "1.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    required_features = (MACD_12_26_9, RSI_14)
    accepts_partial_bars = False

    def __init__(self, config: MacdPositiveCrossConfig | None = None) -> None:
        self.config = config or MacdPositiveCrossConfig()

    @staticmethod
    def _features(context: ScanContext) -> tuple[MacdSnapshot, RsiSnapshot] | None:
        macd = context.feature_values.get(MACD_12_26_9.feature_id)
        rsi = context.feature_values.get(RSI_14.feature_id)
        if not isinstance(macd, MacdSnapshot) or not isinstance(rsi, RsiSnapshot):
            return None
        return macd, rsi

    def _trigger(self, macd: MacdSnapshot) -> tuple[bool, bool, bool]:
        true_cross = macd.previous_line <= macd.previous_signal and macd.line > macd.signal
        rising_above = macd.line > macd.signal and macd.line > macd.previous_line
        triggered = (
            true_cross
            if self.config.trigger_mode is MacdTriggerMode.STRICT_CROSS
            else true_cross or rising_above
        )
        return triggered, true_cross, rising_above

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        features = self._features(context)
        if features is None:
            return False
        macd, rsi = features
        triggered, _true_cross, _rising_above = self._trigger(macd)
        positive_ok = not self.config.require_positive_macd or macd.line > 0
        return rsi.value > self.config.minimum_rsi and positive_ok and triggered

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        features = self._features(context)
        if features is None or not self.prefilter(frame, context):
            return ()
        macd, rsi = features
        _triggered, true_cross, rising_above = self._trigger(macd)
        return (
            Finding(
                finding_key="macd-positive-cross",
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
                    "macd": macd.line,
                    "macd_signal": macd.signal,
                    "macd_histogram": macd.histogram,
                    "rsi": rsi.value,
                    "true_cross": true_cross,
                    "legacy_rising_above": rising_above,
                    "trigger_mode": self.config.trigger_mode.value,
                },
                evidence=(
                    "MACD 12/26/9 recursive EMA referans implementasyonuyla hesaplandı.",
                    "Legacy M-1 tetik modu ADR-0001 uyarınca açıkça kaydedildi.",
                ),
            ),
        )
