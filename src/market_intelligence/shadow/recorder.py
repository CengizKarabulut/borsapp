from __future__ import annotations

from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.engine import ScanRun
from market_intelligence.shadow.compare import ShadowComparator, ShadowComparison
from market_intelligence.shadow.ports import ShadowComparisonStore
from market_intelligence.shadow.registry import ShadowAdapterRegistry


class ShadowRecorder:
    def __init__(self, store: ShadowComparisonStore) -> None:
        self.store = store
        self.comparator = ShadowComparator()
        self.registry = ShadowAdapterRegistry()

    def record(
        self,
        *,
        cycle_id: str,
        frame: CanonicalFrame,
        run: ScanRun,
    ) -> ShadowComparison | None:
        del cycle_id
        adapter = self.registry.adapter_for(run.evaluation.scanner_id)
        if adapter is None:
            return None
        comparison = self.comparator.compare(adapter.evaluate(frame), run)
        self.store.persist(frame, comparison)
        return comparison
