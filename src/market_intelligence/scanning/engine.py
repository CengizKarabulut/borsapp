from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from market_intelligence.core.enums import EvaluationStatus, ResultKind
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext, ScanEvaluation, Scanner


@dataclass(frozen=True)
class ScanRun:
    evaluation: ScanEvaluation
    findings: tuple[Finding, ...] = ()


class ScannerEngine:
    """Pure orchestration: validate a prepared snapshot and execute one scanner."""

    @staticmethod
    def _evaluation(
        *,
        cycle_id: str,
        frame: CanonicalFrame,
        scanner: Scanner,
        context: ScanContext,
        status: EvaluationStatus,
        finding_count: int = 0,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> ScanEvaluation:
        return ScanEvaluation(
            cycle_id=cycle_id,
            instrument_id=frame.instrument_id,
            symbol_at_evaluation=frame.symbol_at_snapshot,
            timeframe=frame.timeframe,
            scanner_id=scanner.id,
            scanner_version=scanner.version,
            ruleset_hash=context.ruleset_hash,
            bar_time=context.bar_close_time,
            status=status,
            finding_count=finding_count,
            snapshot_id=frame.snapshot_id,
            error_code=error_code,
            error_detail=error_detail,
        )

    def run(
        self,
        *,
        cycle_id: str,
        frame: CanonicalFrame,
        scanner: Scanner,
        context: ScanContext,
    ) -> ScanRun:
        if frame.timeframe not in scanner.supported_timeframes:
            return ScanRun(
                self._evaluation(
                    cycle_id=cycle_id,
                    frame=frame,
                    scanner=scanner,
                    context=context,
                    status=EvaluationStatus.UNKNOWN,
                    error_code="unsupported_timeframe",
                )
            )
        if frame.through_bar_time != context.bar_close_time:
            return ScanRun(
                self._evaluation(
                    cycle_id=cycle_id,
                    frame=frame,
                    scanner=scanner,
                    context=context,
                    status=EvaluationStatus.UNKNOWN,
                    error_code="snapshot_context_mismatch",
                )
            )
        if frame.is_partial and not scanner.accepts_partial_bars:
            return ScanRun(
                self._evaluation(
                    cycle_id=cycle_id,
                    frame=frame,
                    scanner=scanner,
                    context=context,
                    status=EvaluationStatus.UNKNOWN,
                    error_code="partial_bar_rejected",
                )
            )
        missing = [
            feature.feature_id
            for feature in scanner.required_features
            if feature.feature_id not in context.feature_values
        ]
        if missing:
            return ScanRun(
                self._evaluation(
                    cycle_id=cycle_id,
                    frame=frame,
                    scanner=scanner,
                    context=context,
                    status=EvaluationStatus.UNKNOWN,
                    error_code="missing_features",
                    error_detail=",".join(missing),
                )
            )
        try:
            if not scanner.prefilter(frame, context):
                return ScanRun(
                    self._evaluation(
                        cycle_id=cycle_id,
                        frame=frame,
                        scanner=scanner,
                        context=context,
                        status=EvaluationStatus.NO_MATCH,
                    )
                )
            findings = tuple(scanner.evaluate(frame, context))
            self._validate_findings(frame, scanner, context, findings)
        except Exception as exc:
            return ScanRun(
                self._evaluation(
                    cycle_id=cycle_id,
                    frame=frame,
                    scanner=scanner,
                    context=context,
                    status=EvaluationStatus.UNKNOWN,
                    error_code="scanner_error",
                    error_detail=f"{type(exc).__name__}: {exc}",
                )
            )
        status = EvaluationStatus.MATCH if findings else EvaluationStatus.NO_MATCH
        return ScanRun(
            self._evaluation(
                cycle_id=cycle_id,
                frame=frame,
                scanner=scanner,
                context=context,
                status=status,
                finding_count=len(findings),
            ),
            findings,
        )

    @staticmethod
    def _validate_findings(
        frame: CanonicalFrame,
        scanner: Scanner,
        context: ScanContext,
        findings: tuple[Finding, ...],
    ) -> None:
        seen: set[str] = set()
        for finding in findings:
            expected: dict[str, Any] = {
                "instrument_id": frame.instrument_id,
                "timeframe": frame.timeframe,
                "scanner_id": scanner.id,
                "scanner_version": scanner.version,
                "ruleset_hash": context.ruleset_hash,
                "bar_time": context.bar_close_time,
                "kind": scanner.result_kind,
            }
            for field_name, expected_value in expected.items():
                if getattr(finding, field_name) != expected_value:
                    raise ValueError(f"Finding sözleşme ihlali: {field_name}")
            if finding.finding_key in seen:
                raise ValueError("Aynı değerlendirmede finding_key benzersiz olmalıdır")
            if finding.kind is ResultKind.STATE:
                if not finding.state_key or finding.valid_from is None:
                    raise ValueError("State finding state_key ve valid_from içermelidir")
                if (
                    finding.valid_until is not None
                    and finding.valid_until <= finding.valid_from
                ):
                    raise ValueError("State valid_until valid_from sonrasında olmalıdır")
            seen.add(finding.finding_key)
