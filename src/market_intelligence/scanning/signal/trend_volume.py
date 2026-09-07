from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.momentum import MACD_12_26_9, MacdSnapshot
from market_intelligence.features.trend import (
    INCLUSIVE_VOLUME_SMA_20,
    LEGACY_TREND_MA_SET,
    InclusiveVolumeSnapshot,
    LegacyTrendMaSnapshot,
)
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext


@dataclass(frozen=True)
class TrendVolumeConfig:
    minimum_history: int = 200
    volume_multiplier: float = 1.5

    def __post_init__(self) -> None:
        if self.minimum_history < 200:
            raise ValueError("Trend scanner minimum_history en az 200 olmalıdır")
        if self.volume_multiplier <= 0:
            raise ValueError("Hacim çarpanı pozitif olmalıdır")


def _trend_and_volume(
    context: ScanContext,
) -> tuple[LegacyTrendMaSnapshot, InclusiveVolumeSnapshot] | None:
    trend = context.feature_values.get(LEGACY_TREND_MA_SET.feature_id)
    volume = context.feature_values.get(INCLUSIVE_VOLUME_SMA_20.feature_id)
    if not isinstance(trend, LegacyTrendMaSnapshot) or not isinstance(
        volume, InclusiveVolumeSnapshot
    ):
        return None
    return trend, volume


def _macd(context: ScanContext) -> MacdSnapshot | None:
    value = context.feature_values.get(MACD_12_26_9.feature_id)
    return value if isinstance(value, MacdSnapshot) else None


def _macd_trigger(macd: MacdSnapshot) -> tuple[bool, bool]:
    true_cross = macd.previous_line <= macd.previous_signal and macd.line > macd.signal
    rising_above = macd.line > macd.signal and macd.line > macd.previous_line
    return true_cross, rising_above


class SmaMacdVolumeScanner:
    id = "signal.sma_macd_volume"
    family = "signal"
    version = "1.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    required_features = (LEGACY_TREND_MA_SET, MACD_12_26_9, INCLUSIVE_VOLUME_SMA_20)
    accepts_partial_bars = False

    def __init__(self, config: TrendVolumeConfig | None = None) -> None:
        self.config = config or TrendVolumeConfig()

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = _trend_and_volume(context)
        macd = _macd(context)
        if values is None or macd is None or len(frame.bars) < self.config.minimum_history:
            return False
        trend, volume = values
        true_cross, rising_above = _macd_trigger(macd)
        return (
            all(trend.close > trend.sma[period] for period in (5, 8, 21, 50, 55, 200))
            and macd.line > 0
            and (true_cross or rising_above)
            and volume.observed_volume > volume.mean_volume * self.config.volume_multiplier
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = _trend_and_volume(context)
        macd = _macd(context)
        if values is None or macd is None or not self.prefilter(frame, context):
            return ()
        trend, volume = values
        true_cross, rising_above = _macd_trigger(macd)
        return (
            Finding(
                finding_key="sma-macd-volume",
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
                    "close": trend.close,
                    **{f"sma{period}": trend.sma[period] for period in (5, 8, 21, 50, 55, 200)},
                    "macd": macd.line,
                    "macd_signal": macd.signal,
                    "macd_true_cross": true_cross,
                    "macd_legacy_rising_above": rising_above,
                    "volume_ratio20_inclusive": volume.ratio,
                    "volume_multiplier": self.config.volume_multiplier,
                },
                evidence=(
                    "Legacy A-M-V-1 SMA 5/8/21/50/55/200, MACD ve hacim koşulları korundu.",
                    "Tüm hareketli ortalamalar ortak canonical feature setinden okundu.",
                ),
            ),
        )


class EmaTrendVolumeScanner:
    id = "signal.ema_trend_volume"
    family = "signal"
    version = "1.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    required_features = (LEGACY_TREND_MA_SET, INCLUSIVE_VOLUME_SMA_20)
    accepts_partial_bars = False

    def __init__(self, config: TrendVolumeConfig | None = None) -> None:
        self.config = config or TrendVolumeConfig()

    @staticmethod
    def _triggers(trend: LegacyTrendMaSnapshot) -> dict[str, bool]:
        ema = trend.ema
        previous = trend.previous_ema
        return {
            "ema8_over_ema13": (
                previous[8] <= previous[13] and ema[8] > ema[13]
            ) or (ema[8] > ema[13] and ema[8] > previous[8]),
            "ema5_over_ema8": (
                previous[5] <= previous[8] and ema[5] > ema[8]
            ) or (ema[5] > ema[8] and ema[5] > previous[5]),
            "ema5_over_ema13": (
                previous[5] <= previous[13] and ema[5] > ema[13]
            ) or (ema[5] > ema[13] and ema[5] > previous[5]),
        }

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = _trend_and_volume(context)
        if values is None or len(frame.bars) < self.config.minimum_history:
            return False
        trend, volume = values
        triggers = self._triggers(trend)
        return (
            all(trend.close > trend.ema[period] for period in (21, 55, 200))
            and all(triggers.values())
            and volume.ratio > self.config.volume_multiplier
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = _trend_and_volume(context)
        if values is None or not self.prefilter(frame, context):
            return ()
        trend, volume = values
        triggers = self._triggers(trend)
        return (
            Finding(
                finding_key="ema-trend-volume",
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
                    "close": trend.close,
                    **{f"ema{period}": trend.ema[period] for period in (5, 8, 13, 21, 55, 200)},
                    **triggers,
                    "volume_ratio20_inclusive": volume.ratio,
                    "volume_multiplier": self.config.volume_multiplier,
                },
                evidence=(
                    "Legacy E-V-1 EMA 5/8/13/21/55/200 ve hacim koşulları korundu.",
                    "Legacy kesişim-veya-üzerinde-yükseliş davranışı metriklere ayrıldı.",
                ),
            ),
        )
