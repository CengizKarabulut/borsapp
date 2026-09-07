from __future__ import annotations

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.features.volume import calculate_volume_activity
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.shadow.compare import ShadowEvaluation


class LegacyVolumeSpikeContractAdapter:
    """Extracted legacy hacim_patlamasi rule for same-snapshot shadowing."""

    scanner_id = "technical.volume_spike"

    def __init__(
        self,
        *,
        relative_volume_threshold: float = 3.0,
        minimum_average_turnover: float = 20_000_000.0,
        minimum_price: float = 1.0,
    ) -> None:
        self.relative_volume_threshold = relative_volume_threshold
        self.minimum_average_turnover = minimum_average_turnover
        self.minimum_price = minimum_price

    def evaluate(self, frame: CanonicalFrame) -> ShadowEvaluation:
        activity = calculate_volume_activity(frame)
        if activity is None:
            return ShadowEvaluation(
                snapshot_id=frame.snapshot_id,
                scanner_id=self.scanner_id,
                status=EvaluationStatus.UNKNOWN,
                diagnostics=("legacy_contract:volume_feature_unavailable",),
            )
        matched = (
            activity.relative_volume >= self.relative_volume_threshold
            and activity.average_turnover >= self.minimum_average_turnover
            and activity.close >= self.minimum_price
        )
        return ShadowEvaluation(
            snapshot_id=frame.snapshot_id,
            scanner_id=self.scanner_id,
            status=(
                EvaluationStatus.MATCH if matched else EvaluationStatus.NO_MATCH
            ),
            finding_keys=("hacim_patlamasi",) if matched else (),
            diagnostics=(
                "_legacy/market-telegram-suite/apps/technical_bot/src/screener.py:266",
            ),
        )
