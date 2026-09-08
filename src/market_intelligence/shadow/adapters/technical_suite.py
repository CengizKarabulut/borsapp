from __future__ import annotations

from dataclasses import dataclass, field

from market_intelligence.compat.legacy_suite import _legacy_imports, _technical_app
from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.shadow.bridge import to_legacy_frame
from market_intelligence.shadow.compare import ShadowEvaluation

TECHNICAL_ALIASES = {
    "technical.squeeze_volume": "sikisma_hacim",
    "technical.volume_spike": "hacim_patlamasi",
    "technical.extreme_rsi": "asiri_bolge",
    "technical.failed_breakout": "basarisiz_kirilim",
    "technical.decision_zone": "karar_bolgesi",
    "technical.trend_continuation": "trend_devami",
    "technical.exhaustion": "tukenme",
}


@dataclass(frozen=True)
class LegacyTechnicalSuiteAdapter:
    scanner_id: str
    session: LegacyTechnicalSuiteSession = field(
        default_factory=lambda: LegacyTechnicalSuiteSession()
    )
    legacy_source: str = "market-telegram-suite"
    legacy_reference: str = "apps/technical_bot/src/screener.py:screen_symbol_detailed"

    def __post_init__(self) -> None:
        if self.scanner_id not in TECHNICAL_ALIASES:
            raise ValueError(f"TECHNICAL legacy alias bulunamadı: {self.scanner_id}")

    def evaluate(self, frame: CanonicalFrame) -> ShadowEvaluation:
        legacy_id = TECHNICAL_ALIASES[self.scanner_id]
        result, reason, error = self.session.evaluate(frame)
        if error is not None:
            return ShadowEvaluation(
                snapshot_id=frame.snapshot_id,
                scanner_id=self.scanner_id,
                status=EvaluationStatus.UNKNOWN,
                diagnostics=(error,),
            )
        if reason == "corporate_action":
            status = EvaluationStatus.UNKNOWN
        else:
            matched = result is not None and legacy_id in result.screens
            status = EvaluationStatus.MATCH if matched else EvaluationStatus.NO_MATCH
        return ShadowEvaluation(
            snapshot_id=frame.snapshot_id,
            scanner_id=self.scanner_id,
            status=status,
            finding_keys=(self.scanner_id,) if status is EvaluationStatus.MATCH else (),
            diagnostics=(f"legacy_reason:{reason}",),
        )


class LegacyTechnicalSuiteSession:
    """Compute the expensive legacy dashboard context once per snapshot."""

    def __init__(self) -> None:
        self._snapshot_id: str | None = None
        self._result = None
        self._reason = "unknown"
        self._error: str | None = None
        self._screen = None
        self._options: dict[str, float] | None = None

    def _load(self) -> None:
        if self._screen is not None:
            return
        with _legacy_imports(_technical_app(), {"MPLBACKEND": "Agg"}):
            from src.screener import default_options, screen_symbol_detailed

            self._screen = screen_symbol_detailed
            self._options = default_options()

    def evaluate(self, frame: CanonicalFrame):
        if self._snapshot_id == frame.snapshot_id:
            return self._result, self._reason, self._error
        try:
            self._load()
            result, reason = self._screen(
                frame.symbol_at_snapshot,
                to_legacy_frame(frame),
                dict(self._options or {}),
                list(TECHNICAL_ALIASES.values()),
                interval=frame.timeframe.value,
            )
        except Exception as exc:
            result = None
            reason = "legacy_error"
            error = f"legacy_error:{type(exc).__name__}:{exc}"
        else:
            error = None
        self._snapshot_id = frame.snapshot_id
        self._result = result
        self._reason = reason
        self._error = error
        return result, reason, error
