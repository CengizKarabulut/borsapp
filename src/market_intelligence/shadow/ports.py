from __future__ import annotations

from typing import Protocol

from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.engine import ScanRun
from market_intelligence.shadow.compare import ShadowComparison, ShadowEvaluation


class LegacyScannerAdapter(Protocol):
    scanner_id: str
    legacy_source: str
    legacy_reference: str

    def evaluate(self, frame: CanonicalFrame) -> ShadowEvaluation: ...


class ShadowComparisonStore(Protocol):
    def persist(self, frame: CanonicalFrame, comparison: ShadowComparison) -> str: ...


class ShadowRecorderPort(Protocol):
    def record(
        self,
        *,
        cycle_id: str,
        frame: CanonicalFrame,
        run: ScanRun,
    ) -> ShadowComparison | None: ...
