from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.scanning.engine import ScanRun


class ShadowCategory(StrEnum):
    AGREE_MATCH = "agree_match"
    AGREE_NO_MATCH = "agree_no_match"
    LEGACY_ONLY = "legacy_only"
    NEW_ONLY = "new_only"
    UNKNOWN = "unknown"
    FINDING_DIFF = "finding_diff"


@dataclass(frozen=True)
class ShadowEvaluation:
    snapshot_id: str
    scanner_id: str
    status: EvaluationStatus
    finding_keys: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowComparison:
    snapshot_id: str
    scanner_id: str
    legacy_status: EvaluationStatus
    new_status: EvaluationStatus
    legacy_finding_keys: tuple[str, ...]
    new_finding_keys: tuple[str, ...]
    category: ShadowCategory
    diagnostics: tuple[str, ...]


class ShadowComparator:
    def __init__(self, aliases: dict[str, str] | None = None) -> None:
        self.aliases = aliases or {}

    def compare(
        self,
        legacy: ShadowEvaluation,
        new: ScanRun,
    ) -> ShadowComparison:
        if legacy.snapshot_id != new.evaluation.snapshot_id:
            raise ValueError("Shadow motorları aynı snapshot üzerinde çalışmalıdır")
        if legacy.scanner_id != new.evaluation.scanner_id:
            raise ValueError("Shadow scanner kimlikleri uyuşmuyor")
        new_keys = tuple(sorted(finding.finding_key for finding in new.findings))
        legacy_keys = tuple(
            sorted(self.aliases.get(key, key) for key in legacy.finding_keys)
        )
        legacy_status = legacy.status
        new_status = new.evaluation.status
        diagnostics = list(legacy.diagnostics)
        if new.evaluation.error_code:
            diagnostics.append(
                f"new:{new.evaluation.error_code}:{new.evaluation.error_detail or ''}"
            )
        if EvaluationStatus.UNKNOWN in (legacy_status, new_status):
            category = ShadowCategory.UNKNOWN
        elif legacy_status is EvaluationStatus.MATCH and new_status is EvaluationStatus.NO_MATCH:
            category = ShadowCategory.LEGACY_ONLY
        elif legacy_status is EvaluationStatus.NO_MATCH and new_status is EvaluationStatus.MATCH:
            category = ShadowCategory.NEW_ONLY
        elif legacy_status is EvaluationStatus.NO_MATCH:
            category = ShadowCategory.AGREE_NO_MATCH
        elif legacy_keys != new_keys:
            category = ShadowCategory.FINDING_DIFF
        else:
            category = ShadowCategory.AGREE_MATCH
        return ShadowComparison(
            snapshot_id=legacy.snapshot_id,
            scanner_id=legacy.scanner_id,
            legacy_status=legacy_status,
            new_status=new_status,
            legacy_finding_keys=legacy_keys,
            new_finding_keys=new_keys,
            category=category,
            diagnostics=tuple(diagnostics),
        )
