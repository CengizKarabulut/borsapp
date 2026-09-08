from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field

from market_intelligence.compat.paths import repository_root
from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.shadow.bridge import to_legacy_frame
from market_intelligence.shadow.compare import ShadowEvaluation

SIGNAL_ALIASES = {
    "signal.macd_positive_cross": ("macd_cross", "macd-positive-cross"),
    "signal.smi_macd_positive": ("h8", "smi-macd-positive"),
    "signal.smi_macd_positive_volume_confirmed": (
        "i9",
        "smi-macd-positive-volume-confirmed",
    ),
    "signal.rsi_momentum_volume": ("rsi", "rsi-momentum-volume"),
    "signal.rsi_macd_volume": ("rsi_macd", "rsi-macd-volume"),
    "signal.smi_macd_early": ("smi_macd", "smi-macd-early"),
    "signal.smi_macd_full": ("smi_macd_full", "smi-macd-full"),
    "signal.sma_macd_volume": ("new_scan", "sma-macd-volume"),
    "signal.ema_trend_volume": ("ema", "ema-trend-volume"),
}


class LegacySignalSession:
    """Load the frozen vectorized A-I parity engine once per process."""

    def __init__(self) -> None:
        self._build_signal_frame = None
        self._snapshot_id: str | None = None
        self._result = None
        self._error: str | None = None

    def _load(self) -> None:
        if self._build_signal_frame is not None:
            return
        path = repository_root() / "_legacy" / "taramabot" / "signal_parity.py"
        spec = importlib.util.spec_from_file_location("borsapp_legacy_signal_parity", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Legacy signal parity modülü yüklenemedi: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._build_signal_frame = module.build_signal_frame

    def evaluate(self, frame: CanonicalFrame):
        if self._snapshot_id == frame.snapshot_id:
            return self._result, self._error
        try:
            self._load()
            result = self._build_signal_frame(
                to_legacy_frame(frame),
                period=frame.timeframe.value,
            )
            error = None
        except Exception as exc:
            result = None
            error = f"legacy_error:{type(exc).__name__}:{exc}"
        self._snapshot_id = frame.snapshot_id
        self._result = result
        self._error = error
        return result, error


@dataclass(frozen=True)
class LegacyTaramabotSignalAdapter:
    scanner_id: str
    session: LegacySignalSession = field(default_factory=lambda: LegacySignalSession())
    legacy_source: str = "taramabot"
    legacy_reference: str = "signal_parity.py:build_signal_frame"

    def __post_init__(self) -> None:
        if self.scanner_id not in SIGNAL_ALIASES:
            raise ValueError(f"SIGNAL legacy alias bulunamadı: {self.scanner_id}")

    def evaluate(self, frame: CanonicalFrame) -> ShadowEvaluation:
        strategy, finding_key = SIGNAL_ALIASES[self.scanner_id]
        result, error = self.session.evaluate(frame)
        if error is not None or result is None or result.empty:
            return ShadowEvaluation(
                snapshot_id=frame.snapshot_id,
                scanner_id=self.scanner_id,
                status=EvaluationStatus.UNKNOWN,
                diagnostics=(error or "legacy_error:empty_result",),
            )
        matched = bool(result.iloc[-1][strategy])
        return ShadowEvaluation(
            snapshot_id=frame.snapshot_id,
            scanner_id=self.scanner_id,
            status=EvaluationStatus.MATCH if matched else EvaluationStatus.NO_MATCH,
            finding_keys=(finding_key,) if matched else (),
            diagnostics=(f"legacy_strategy:{strategy}",),
        )
