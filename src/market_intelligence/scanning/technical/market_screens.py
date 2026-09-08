from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.technical import (
    TECHNICAL_MARKET_CONTEXT,
    TechnicalMarketContext,
)
from market_intelligence.features.volume import RELATIVE_VOLUME_20, VolumeActivity
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext


@dataclass(frozen=True)
class TechnicalScreenConfig:
    minimum_average_turnover: float = 20_000_000.0
    minimum_price: float = 1.0
    bb_rank_max: float = 20.0
    squeeze_rvol_min: float = 1.5
    extreme_rvol_min: float = 1.0
    trend_adx_min: float = 25.0
    trend_rvol_min: float = 1.0

    def __post_init__(self) -> None:
        if self.minimum_average_turnover < 0 or self.minimum_price < 0:
            raise ValueError("Teknik tarama likidite eşikleri negatif olamaz")
        if not 0 <= self.bb_rank_max <= 100:
            raise ValueError("Bollinger yüzdelik eşiği 0 ile 100 arasında olmalıdır")
        if min(self.squeeze_rvol_min, self.extreme_rvol_min, self.trend_rvol_min) < 0:
            raise ValueError("RVOL eşikleri negatif olamaz")
        if self.trend_adx_min < 0:
            raise ValueError("ADX eşiği negatif olamaz")


class _TechnicalScreen:
    family = "technical"
    version = "1.0.0"
    supported_timeframes = set(Timeframe)
    required_features = (TECHNICAL_MARKET_CONTEXT, RELATIVE_VOLUME_20)
    accepts_partial_bars = False
    result_kind = ResultKind.STATE
    label = ""

    def __init__(self, config: TechnicalScreenConfig | None = None) -> None:
        self.config = config or TechnicalScreenConfig()

    @staticmethod
    def _values(
        context: ScanContext,
    ) -> tuple[TechnicalMarketContext, VolumeActivity] | None:
        technical = context.feature_values.get(TECHNICAL_MARKET_CONTEXT.feature_id)
        volume = context.feature_values.get(RELATIVE_VOLUME_20.feature_id)
        if not isinstance(technical, TechnicalMarketContext) or not isinstance(
            volume, VolumeActivity
        ):
            return None
        return technical, volume

    def _liquid(self, volume: VolumeActivity) -> bool:
        return (
            volume.close >= self.config.minimum_price
            and volume.average_turnover >= self.config.minimum_average_turnover
        )

    def _finding(
        self,
        frame: CanonicalFrame,
        context: ScanContext,
        technical: TechnicalMarketContext,
        volume: VolumeActivity,
        direction: Direction,
    ) -> Finding:
        state = self.result_kind is ResultKind.STATE
        return Finding(
            finding_key=self.id,
            state_key=self.id if state else None,
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
                "close": technical.close,
                "relative_volume": volume.relative_volume,
                "average_turnover": volume.average_turnover,
                "bb_width_percentile": technical.bb_width_percentile,
                "rsi": technical.rsi,
                "adx": technical.adx,
                "atr": technical.atr,
                "ema21": technical.ema21,
                "ema55": technical.ema55,
                "pierced_down": technical.pierced_down,
                "pierced_up": technical.pierced_up,
                "squeeze_bars": technical.squeeze_bars,
                "structure_tone": technical.structure_tone,
                "trend_tone": technical.trend_tone,
                "setup_name": technical.setup_name,
                "strong_divergences": technical.strong_divergences,
                "near_confluence": technical.near_confluence,
            },
            evidence=(
                self.label,
                "Legacy market-telegram-suite eşikleri canonical kapalı mum üzerinde uygulandı.",
            ),
            valid_from=context.bar_close_time if state else None,
        )


class SqueezeVolumeScanner(_TechnicalScreen):
    id = "technical.squeeze_volume"
    label = "Dar Bollinger bandına ortalama üstü hacim katılımı geldi."

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = self._values(context)
        if values is None:
            return False
        technical, volume = values
        return (
            self._liquid(volume)
            and technical.bb_width_percentile <= self.config.bb_rank_max
            and volume.relative_volume >= self.config.squeeze_rvol_min
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = self._values(context)
        if values is None or not self.prefilter(frame, context):
            return ()
        technical, volume = values
        return (self._finding(frame, context, technical, volume, Direction.NEUTRAL),)


class ExtremeRsiScanner(_TechnicalScreen):
    id = "technical.extreme_rsi"
    label = "RSI uç bölgede ve hacim katılımı en az normal düzeyde."

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = self._values(context)
        if values is None:
            return False
        technical, volume = values
        return (
            self._liquid(volume)
            and (technical.rsi <= 25 or technical.rsi >= 75)
            and volume.relative_volume >= self.config.extreme_rvol_min
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = self._values(context)
        if values is None or not self.prefilter(frame, context):
            return ()
        technical, volume = values
        direction = Direction.BULLISH if technical.rsi <= 25 else Direction.BEARISH
        return (self._finding(frame, context, technical, volume, direction),)


class FailedBreakoutScanner(_TechnicalScreen):
    id = "technical.failed_breakout"
    label = "Seviye denemesi kapanışla kabul görmedi ve fiyat bölgeye geri döndü."
    result_kind = ResultKind.EVENT

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = self._values(context)
        if values is None:
            return False
        technical, volume = values
        return self._liquid(volume) and (technical.pierced_down or technical.pierced_up)

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = self._values(context)
        if values is None or not self.prefilter(frame, context):
            return ()
        technical, volume = values
        if "reddedilme" not in technical.setup_name.casefold():
            return ()
        direction = (
            Direction.BULLISH
            if technical.setup_direction == "bullish"
            else Direction.BEARISH
        )
        return (self._finding(frame, context, technical, volume, direction),)


class DecisionZoneScanner(_TechnicalScreen):
    id = "technical.decision_zone"
    label = "Fiyat düşük yönlülükte sıkışma ve karar bölgesinde."

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = self._values(context)
        if values is None:
            return False
        technical, volume = values
        return (
            self._liquid(volume)
            and technical.bb_width_percentile <= self.config.bb_rank_max
            and technical.adx < 20
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = self._values(context)
        if values is None or not self.prefilter(frame, context):
            return ()
        technical, volume = values
        if technical.setup_name != "Sıkışma / karar bölgesi":
            return ()
        return (self._finding(frame, context, technical, volume, Direction.NEUTRAL),)


class TrendContinuationScanner(_TechnicalScreen):
    id = "technical.trend_continuation"
    label = "Yapı, EMA dizilimi, yönlülük ve katılım aynı trendi destekliyor."

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = self._values(context)
        if values is None:
            return False
        technical, volume = values
        return (
            self._liquid(volume)
            and technical.adx >= self.config.trend_adx_min
            and technical.stacked_direction is not None
            and volume.relative_volume >= self.config.trend_rvol_min
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = self._values(context)
        if values is None or not self.prefilter(frame, context):
            return ()
        technical, volume = values
        if technical.setup_name != "Trend devamı":
            return ()
        direction = (
            Direction.BULLISH
            if technical.setup_direction == "bullish"
            else Direction.BEARISH
        )
        return (self._finding(frame, context, technical, volume, direction),)


class ExhaustionScanner(_TechnicalScreen):
    id = "technical.exhaustion"
    label = "Momentum aşırılığı, seviye yoğunlaşması ve teyitli uyumsuzluk birlikte."

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = self._values(context)
        if values is None:
            return False
        technical, volume = values
        return (
            self._liquid(volume)
            and (technical.rsi <= 30 or technical.rsi >= 70)
            and (technical.pierced_down or technical.pierced_up)
        )

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        values = self._values(context)
        if values is None or not self.prefilter(frame, context):
            return ()
        technical, volume = values
        if technical.setup_name != "Tükenme denemesi":
            return ()
        direction = (
            Direction.BULLISH if technical.setup_direction == "bullish" else Direction.BEARISH
        )
        return (self._finding(frame, context, technical, volume, direction),)
