from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.volume import RELATIVE_VOLUME_20, VolumeActivity
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext


@dataclass(frozen=True)
class VolumeSpikeConfig:
    relative_volume_threshold: float = 3.0
    minimum_average_turnover: float = 20_000_000.0
    minimum_price: float = 1.0

    def __post_init__(self) -> None:
        if self.relative_volume_threshold <= 0:
            raise ValueError("Hacim oranı eşiği pozitif olmalıdır")
        if self.minimum_average_turnover < 0 or self.minimum_price < 0:
            raise ValueError("Likidite eşikleri negatif olamaz")


class TechnicalVolumeSpikeScanner:
    id = "technical.volume_spike"
    family = "technical"
    version = "1.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    required_features = (RELATIVE_VOLUME_20,)
    accepts_partial_bars = False

    def __init__(self, config: VolumeSpikeConfig | None = None) -> None:
        self.config = config or VolumeSpikeConfig()

    @staticmethod
    def _activity(context: ScanContext) -> VolumeActivity | None:
        value = context.feature_values.get(RELATIVE_VOLUME_20.feature_id)
        return value if isinstance(value, VolumeActivity) else None

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        activity = self._activity(context)
        if activity is None:
            return False
        return (
            activity.close >= self.config.minimum_price
            and activity.average_turnover >= self.config.minimum_average_turnover
            and activity.relative_volume >= self.config.relative_volume_threshold
        )

    def evaluate(
        self,
        frame: CanonicalFrame,
        context: ScanContext,
    ) -> tuple[Finding, ...]:
        activity = self._activity(context)
        if activity is None or not self.prefilter(frame, context):
            return ()
        return (
            Finding(
                finding_key="volume-spike",
                instrument_id=frame.instrument_id,
                symbol_at_event=frame.symbol_at_snapshot,
                timeframe=frame.timeframe,
                scanner_id=self.id,
                scanner_version=self.version,
                ruleset_hash=context.ruleset_hash,
                kind=self.result_kind,
                bar_time=context.bar_close_time,
                direction=Direction.NEUTRAL,
                metrics={
                    "relative_volume": activity.relative_volume,
                    "observed_volume": activity.observed_volume,
                    "baseline_volume": activity.baseline_volume,
                    "baseline_bar_count": activity.baseline_bar_count,
                    "average_turnover": activity.average_turnover,
                    "close": activity.close,
                    "threshold": self.config.relative_volume_threshold,
                },
                evidence=(
                    "Mevcut kapalı bar hacmi önceki kapalı barların ortalamasıyla karşılaştırıldı.",
                    "Likidite ve minimum fiyat eşikleri sağlandı.",
                ),
            ),
        )
