from __future__ import annotations

from dataclasses import dataclass, replace

from market_intelligence.features.registry import FeatureEngine, FeatureResolution
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import ScanContext, Scanner
from market_intelligence.scanning.engine import ScannerEngine, ScanRun


@dataclass(frozen=True)
class PipelineRun:
    scan: ScanRun
    features: FeatureResolution


class ScanPipeline:
    """Resolve shared features once, then execute a pure scanner."""

    def __init__(self, feature_engine: FeatureEngine, scanner_engine: ScannerEngine | None = None) -> None:
        self.feature_engine = feature_engine
        self.scanner_engine = scanner_engine or ScannerEngine()

    def run(
        self,
        *,
        cycle_id: str,
        frame: CanonicalFrame,
        scanner: Scanner,
        context: ScanContext,
    ) -> PipelineRun:
        resolution = self.feature_engine.resolve(frame, scanner.required_features)
        prepared_context = replace(context, feature_values=resolution.values)
        scan = self.scanner_engine.run(
            cycle_id=cycle_id,
            frame=frame,
            scanner=scanner,
            context=prepared_context,
        )
        return PipelineRun(scan=scan, features=resolution)
