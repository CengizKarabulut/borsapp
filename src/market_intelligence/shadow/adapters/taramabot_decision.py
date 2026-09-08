from __future__ import annotations

import importlib.util
import sys

from market_intelligence.compat.paths import repository_root
from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.shadow.bridge import to_legacy_frame
from market_intelligence.shadow.compare import ShadowEvaluation


class LegacyTaramabotDecisionAdapter:
    scanner_id = "decision.panel_v645"
    legacy_source = "taramabot"
    legacy_reference = "decision_panel_v645_signal.py:latest_decision"

    def __init__(self) -> None:
        self._latest_decision = None

    def _load(self) -> None:
        if self._latest_decision is not None:
            return
        root = repository_root() / "_legacy" / "taramabot"
        path = root / "decision_panel_v645_signal.py"
        spec = importlib.util.spec_from_file_location("borsapp_legacy_decision_v645", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Legacy KARAR modülü yüklenemedi: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(root))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(root))
        self._latest_decision = module.latest_decision

    def evaluate(self, frame: CanonicalFrame, *, feature_values=None) -> ShadowEvaluation:
        del feature_values
        try:
            self._load()
            result = self._latest_decision(to_legacy_frame(frame), min_score=75)
        except Exception as exc:
            return ShadowEvaluation(
                snapshot_id=frame.snapshot_id,
                scanner_id=self.scanner_id,
                status=EvaluationStatus.UNKNOWN,
                diagnostics=(f"legacy_error:{type(exc).__name__}:{exc}",),
            )
        matched = bool(result["entry"])
        setup = str(result.get("new_setup", "")).casefold().replace(" ", "-")
        return ShadowEvaluation(
            snapshot_id=frame.snapshot_id,
            scanner_id=self.scanner_id,
            status=EvaluationStatus.MATCH if matched else EvaluationStatus.NO_MATCH,
            finding_keys=(f"entry:{setup}",) if matched else (),
            diagnostics=(f"legacy_version:{result.get('version', 'unknown')}",),
        )
