from __future__ import annotations

import importlib.util
import sys
from typing import Any

from market_intelligence.compat.paths import repository_root
from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.features.ma import (
    QUALIFIED_MA_PROXIMITY,
    MaProximitySnapshot,
    QualifiedMaLevel,
)
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.shadow.compare import ShadowEvaluation

_LEVEL_CLASS = {
    "strong_level": "Güçlü seviye",
    "level": "Seviye",
    "weak_level": "Zayıf seviye",
    "not_level": "Seviye değil",
    "insufficient_touches": "Yetersiz temas",
}


class LegacyMaLiveAdapter:
    """Compare live proximity while holding the research qualification fixed."""

    scanner_id = "ma.near_zone"
    legacy_source = "ma-reaction-scanner"
    legacy_reference = "scanner/ma_engine.py:build_market_summary"

    def __init__(self) -> None:
        self._build_market_summary = None

    def _load(self) -> None:
        if self._build_market_summary is not None:
            return
        path = (
            repository_root()
            / "_legacy"
            / "ma-reaction-scanner"
            / "scanner"
            / "ma_engine.py"
        )
        spec = importlib.util.spec_from_file_location("borsapp_legacy_ma_engine", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Legacy MA motoru yüklenemedi: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self._build_market_summary = module.build_market_summary

    @staticmethod
    def _row(frame: CanonicalFrame, level: QualifiedMaLevel) -> dict[str, object]:
        side = "Destek" if level.side.casefold() == "support" else "Direnç"
        level_class = _LEVEL_CLASS.get(level.level_class.casefold(), "Yetersiz temas")
        compatible = level_class in {"Güçlü seviye", "Seviye"}
        return {
            "symbol": frame.symbol_at_snapshot,
            "timeframe": frame.timeframe.value,
            "ma": f"{level.ma_type.upper()}{level.period}",
            "ma_type": level.ma_type.upper(),
            "period": level.period,
            "current_ma": level.value,
            "current_price": frame.bars[-1].close,
            "distance_value": level.value - frame.bars[-1].close,
            "distance_pct": (level.value / frame.bars[-1].close - 1.0) * 100.0,
            "distance_atr": level.distance_atr,
            "side": side,
            "active_side": level.active_side,
            "trend_state": "Yetersiz veri",
            "filter_pass": True,
            "compatibility": "Uyumlu" if compatible else "İzleme",
            "compatibility_score": level.quality_score,
            "level_score": level.quality_score,
            "level_class": level_class,
            "touches": level.touches,
            "level_touches": level.touches,
            "positive_periods": 0,
            "win_rate_pct": 0.0,
            "median_net_r": 0.0,
            "edge_r": 0.0,
        }

    def evaluate(
        self,
        frame: CanonicalFrame,
        *,
        feature_values: dict[str, Any] | None = None,
    ) -> ShadowEvaluation:
        snapshot = (feature_values or {}).get(QUALIFIED_MA_PROXIMITY.feature_id)
        if not isinstance(snapshot, MaProximitySnapshot):
            return ShadowEvaluation(
                snapshot_id=frame.snapshot_id,
                scanner_id=self.scanner_id,
                status=EvaluationStatus.UNKNOWN,
                diagnostics=("legacy_ma_live:qualification_snapshot_unavailable",),
            )
        try:
            self._load()
            candidates: list[tuple[QualifiedMaLevel, str]] = []
            for level in snapshot.levels:
                if not level.active_side:
                    continue
                import pandas as pd

                summary = self._build_market_summary(
                    pd.DataFrame([self._row(frame, level)]),
                    near_distance_atr=1.0,
                    rank_by="level",
                )
                if not summary.empty and str(summary.iloc[0]["setup"]) in {
                    "Desteğe yakın",
                    "Dirence yakın",
                }:
                    candidates.append((level, f"near-zone:{level.level_id}"))
        except Exception as exc:
            return ShadowEvaluation(
                snapshot_id=frame.snapshot_id,
                scanner_id=self.scanner_id,
                status=EvaluationStatus.UNKNOWN,
                diagnostics=(f"legacy_error:{type(exc).__name__}:{exc}",),
            )
        matches: list[str] = []
        for side in ("support", "resistance"):
            ordered = sorted(
                (candidate for candidate in candidates if candidate[0].side.casefold() == side),
                key=lambda candidate: (
                    -candidate[0].quality_score,
                    abs(candidate[0].distance_atr),
                ),
            )
            matches.extend(key for _level, key in ordered[:2])
        keys = tuple(sorted(matches))
        return ShadowEvaluation(
            snapshot_id=frame.snapshot_id,
            scanner_id=self.scanner_id,
            status=EvaluationStatus.MATCH if keys else EvaluationStatus.NO_MATCH,
            finding_keys=keys,
            diagnostics=("ma_research_qualification:held_fixed",),
        )
