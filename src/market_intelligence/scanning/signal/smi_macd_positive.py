from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.momentum import (
    MACD_12_26_9,
    SMI_10_3_3,
    MacdSnapshot,
    SmiSnapshot,
)
from market_intelligence.features.trend import (
    INCLUSIVE_VOLUME_SMA_20,
    SMA_200,
    InclusiveVolumeSnapshot,
    MovingAverageSnapshot,
)
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext


@dataclass(frozen=True)
class SmiMacdPositiveConfig:
    minimum_history: int = 200

    def __post_init__(self) -> None:
        if self.minimum_history < 2:
            raise ValueError("SMI/MACD minimum_history en az 2 olmalıdır")


@dataclass(frozen=True)
class SmiMacdPositiveVolumeConfig:
    minimum_history: int = 200
    volume_multiplier: float = 1.5

    def __post_init__(self) -> None:
        if self.minimum_history < 200:
            raise ValueError("MA200 onaylı scanner minimum_history en az 200 olmalıdır")
        if self.volume_multiplier <= 0:
            raise ValueError("Hacim çarpanı pozitif olmalıdır")


def _momentum(context: ScanContext) -> tuple[SmiSnapshot, MacdSnapshot] | None:
    smi = context.feature_values.get(SMI_10_3_3.feature_id)
    macd = context.feature_values.get(MACD_12_26_9.feature_id)
    if not isinstance(smi, SmiSnapshot) or not isinstance(macd, MacdSnapshot):
        return None
    return smi, macd


def _conditions(smi: SmiSnapshot, macd: MacdSnapshot) -> dict[str, bool]:
    true_cross = smi.previous_value <= smi.previous_signal and smi.value > smi.signal
    rising_above = smi.value > smi.signal and smi.value > smi.previous_value
    return {
        "true_cross": true_cross,
        "legacy_rising_above": rising_above,
        "smi_positive": smi.value > 0,
        "histogram_positive": macd.histogram > 0,
        "histogram_rising": macd.histogram > macd.previous_histogram,
    }


def _base_match(frame: CanonicalFrame, context: ScanContext, minimum_history: int) -> bool:
    values = _momentum(context)
    if values is None or len(frame.bars) < minimum_history:
        return False
    conditions = _conditions(*values)
    return (
        (conditions["true_cross"] or conditions["legacy_rising_above"])
        and conditions["smi_positive"]
        and conditions["histogram_positive"]
        and conditions["histogram_rising"]
    )


class SmiMacdPositiveScanner:
    id = "signal.smi_macd_positive"
    family = "signal"
    version = "1.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    required_features = (SMI_10_3_3, MACD_12_26_9)
    accepts_partial_bars = False

    def __init__(self, config: SmiMacdPositiveConfig | None = None) -> None:
        self.config = config or SmiMacdPositiveConfig()

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        return _base_match(frame, context, self.config.minimum_history)

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = _momentum(context)
        if values is None or not self.prefilter(frame, context):
            return ()
        smi, macd = values
        conditions = _conditions(smi, macd)
        return (
            Finding(
                finding_key="smi-macd-positive",
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
                    "smi": smi.value,
                    "smi_signal": smi.signal,
                    "macd_histogram": macd.histogram,
                    **conditions,
                },
                evidence=(
                    "Legacy S-M-1 SMI(10,3,3) ve MACD histogram koşulları korundu.",
                    "Legacy kesişim-veya-yükseliş davranışı açık metriklerle kaydedildi.",
                ),
            ),
        )


class SmiMacdPositiveVolumeConfirmedScanner:
    id = "signal.smi_macd_positive_volume_confirmed"
    family = "signal"
    version = "1.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    required_features = (
        SMI_10_3_3,
        MACD_12_26_9,
        SMA_200,
        INCLUSIVE_VOLUME_SMA_20,
    )
    accepts_partial_bars = False

    def __init__(self, config: SmiMacdPositiveVolumeConfig | None = None) -> None:
        self.config = config or SmiMacdPositiveVolumeConfig()

    @staticmethod
    def _confirmations(
        context: ScanContext,
    ) -> tuple[MovingAverageSnapshot, InclusiveVolumeSnapshot] | None:
        average = context.feature_values.get(SMA_200.feature_id)
        volume = context.feature_values.get(INCLUSIVE_VOLUME_SMA_20.feature_id)
        if not isinstance(average, MovingAverageSnapshot) or not isinstance(
            volume, InclusiveVolumeSnapshot
        ):
            return None
        return average, volume

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        confirmations = self._confirmations(context)
        if confirmations is None or not _base_match(
            frame, context, self.config.minimum_history
        ):
            return False
        average, volume = confirmations
        return (
            average.close > average.value
            and volume.observed_volume > volume.mean_volume * self.config.volume_multiplier
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        momentum = _momentum(context)
        confirmations = self._confirmations(context)
        if momentum is None or confirmations is None or not self.prefilter(frame, context):
            return ()
        smi, macd = momentum
        average, volume = confirmations
        return (
            Finding(
                finding_key="smi-macd-positive-volume-confirmed",
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
                    "smi": smi.value,
                    "smi_signal": smi.signal,
                    "macd_histogram": macd.histogram,
                    "close": average.close,
                    "sma200": average.value,
                    "volume": volume.observed_volume,
                    "volume_sma20_inclusive": volume.mean_volume,
                    "volume_ratio": volume.ratio,
                    "volume_multiplier": self.config.volume_multiplier,
                    **_conditions(smi, macd),
                },
                evidence=(
                    "Legacy S-M-V-1, S-M-1 üzerine SMA200 ve hacim onayı uygular.",
                    "Hacim SMA20 legacy davranışıyla mevcut barı ortalamaya dahil eder.",
                ),
            ),
        )
