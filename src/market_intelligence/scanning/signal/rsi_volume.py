from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.momentum import (
    LEGACY_RSI_7,
    LEGACY_RSI_14,
    MACD_12_26_9,
    MacdSnapshot,
    RsiSnapshot,
)
from market_intelligence.features.trend import (
    INCLUSIVE_VOLUME_SMA_10,
    INCLUSIVE_VOLUME_SMA_20,
    InclusiveVolumeSnapshot,
)
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext


@dataclass(frozen=True)
class RsiMomentumVolumeConfig:
    minimum_history: int = 30
    strength_threshold: float = 60.0
    crossover_level: float = 50.0
    volume_multiplier: float = 1.5

    def __post_init__(self) -> None:
        if self.minimum_history < 3:
            raise ValueError("R-V-1 minimum_history en az 3 olmalıdır")
        if not 0 <= self.crossover_level <= self.strength_threshold <= 100:
            raise ValueError("R-V-1 RSI eşikleri geçersiz")
        if self.volume_multiplier <= 0:
            raise ValueError("R-V-1 hacim çarpanı pozitif olmalıdır")


@dataclass(frozen=True)
class RsiMacdVolumeConfig:
    minimum_history: int = 35
    crossover_level: float = 50.0
    maximum_rsi: float = 70.0
    volume_multiplier: float = 1.5

    def __post_init__(self) -> None:
        if self.minimum_history < 3:
            raise ValueError("R-M-V-1 minimum_history en az 3 olmalıdır")
        if not 0 <= self.crossover_level < self.maximum_rsi <= 100:
            raise ValueError("R-M-V-1 RSI eşikleri geçersiz")
        if self.volume_multiplier <= 0:
            raise ValueError("R-M-V-1 hacim çarpanı pozitif olmalıdır")


def _rising_above(rsi: RsiSnapshot, level: float) -> tuple[bool, bool]:
    true_cross = rsi.previous_value <= level and rsi.value > level
    rising_above = rsi.value > level and rsi.value > rsi.previous_value
    return true_cross, rising_above


def _macd_trigger(macd: MacdSnapshot) -> tuple[bool, bool]:
    true_cross = macd.previous_line <= macd.previous_signal and macd.line > macd.signal
    rising_above = macd.line > macd.signal and macd.line > macd.previous_line
    return true_cross, rising_above


class RsiMomentumVolumeScanner:
    id = "signal.rsi_momentum_volume"
    family = "signal"
    version = "1.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    required_features = (LEGACY_RSI_7, INCLUSIVE_VOLUME_SMA_10)
    accepts_partial_bars = False

    def __init__(self, config: RsiMomentumVolumeConfig | None = None) -> None:
        self.config = config or RsiMomentumVolumeConfig()

    @staticmethod
    def _features(
        context: ScanContext,
    ) -> tuple[RsiSnapshot, InclusiveVolumeSnapshot] | None:
        rsi = context.feature_values.get(LEGACY_RSI_7.feature_id)
        volume = context.feature_values.get(INCLUSIVE_VOLUME_SMA_10.feature_id)
        if not isinstance(rsi, RsiSnapshot) or not isinstance(
            volume, InclusiveVolumeSnapshot
        ):
            return None
        return rsi, volume

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        features = self._features(context)
        if features is None or len(frame.bars) < self.config.minimum_history:
            return False
        rsi, volume = features
        true_cross, rising_above = _rising_above(rsi, self.config.crossover_level)
        return (
            rsi.value > self.config.strength_threshold
            and (true_cross or rising_above)
            and volume.observed_volume > volume.mean_volume * self.config.volume_multiplier
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        features = self._features(context)
        if features is None or not self.prefilter(frame, context):
            return ()
        rsi, volume = features
        true_cross, rising_above = _rising_above(rsi, self.config.crossover_level)
        return (
            Finding(
                finding_key="rsi-momentum-volume",
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
                    "rsi7": rsi.value,
                    "previous_rsi7": rsi.previous_value,
                    "true_cross_50": true_cross,
                    "legacy_rising_above_50": rising_above,
                    "volume_ratio10_inclusive": volume.ratio,
                    "volume_multiplier": self.config.volume_multiplier,
                },
                evidence=(
                    "Legacy R-V-1 RSI(7) güç ve 50 kesişim/yükseliş koşulları korundu.",
                    "Hacim ortalaması mevcut bar dahil son 10 bar üzerinden hesaplandı.",
                ),
            ),
        )


class RsiMacdVolumeScanner:
    id = "signal.rsi_macd_volume"
    family = "signal"
    version = "1.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    required_features = (LEGACY_RSI_14, MACD_12_26_9, INCLUSIVE_VOLUME_SMA_20)
    accepts_partial_bars = False

    def __init__(self, config: RsiMacdVolumeConfig | None = None) -> None:
        self.config = config or RsiMacdVolumeConfig()

    @staticmethod
    def _features(
        context: ScanContext,
    ) -> tuple[RsiSnapshot, MacdSnapshot, InclusiveVolumeSnapshot] | None:
        rsi = context.feature_values.get(LEGACY_RSI_14.feature_id)
        macd = context.feature_values.get(MACD_12_26_9.feature_id)
        volume = context.feature_values.get(INCLUSIVE_VOLUME_SMA_20.feature_id)
        if (
            not isinstance(rsi, RsiSnapshot)
            or not isinstance(macd, MacdSnapshot)
            or not isinstance(volume, InclusiveVolumeSnapshot)
        ):
            return None
        return rsi, macd, volume

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        features = self._features(context)
        if features is None or len(frame.bars) < self.config.minimum_history:
            return False
        rsi, macd, volume = features
        rsi_cross, rsi_rising = _rising_above(rsi, self.config.crossover_level)
        macd_cross, macd_rising = _macd_trigger(macd)
        return (
            (rsi_cross or rsi_rising)
            and rsi.value < self.config.maximum_rsi
            and (macd_cross or macd_rising)
            and volume.ratio > self.config.volume_multiplier
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        features = self._features(context)
        if features is None or not self.prefilter(frame, context):
            return ()
        rsi, macd, volume = features
        rsi_cross, rsi_rising = _rising_above(rsi, self.config.crossover_level)
        macd_cross, macd_rising = _macd_trigger(macd)
        return (
            Finding(
                finding_key="rsi-macd-volume",
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
                    "rsi14": rsi.value,
                    "previous_rsi14": rsi.previous_value,
                    "rsi_true_cross_50": rsi_cross,
                    "rsi_legacy_rising_above_50": rsi_rising,
                    "macd": macd.line,
                    "macd_signal": macd.signal,
                    "macd_true_cross": macd_cross,
                    "macd_legacy_rising_above": macd_rising,
                    "volume_ratio20_inclusive": volume.ratio,
                    "volume_multiplier": self.config.volume_multiplier,
                },
                evidence=(
                    "Legacy R-M-V-1 RSI(14), MACD ve hacim koşulları korundu.",
                    "RSI ve MACD için legacy kesişim-veya-yükseliş ayrımı kaydedildi.",
                ),
            ),
        )
