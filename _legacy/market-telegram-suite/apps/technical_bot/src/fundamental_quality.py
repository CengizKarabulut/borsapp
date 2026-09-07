"""Quality policy for fundamental scorecards.

A missing accounting metric is not a negative observation. Likewise, a factor
must not look excellent merely because only one easy-to-score component exists.
This module applies a fail-closed coverage policy before a report reaches users.
"""

from __future__ import annotations

from dataclasses import replace

from src.fundamental_analysis import FundamentalReport

MIN_FACTOR_COVERAGE = 0.50
WARN_FACTOR_COVERAGE = 0.75


def apply_coverage_policy(report: FundamentalReport) -> FundamentalReport:
    """Remove scores that do not have enough underlying metric coverage."""
    adjusted = []
    suppressed_names: set[str] = set()
    for factor in report.factors:
        detail = factor.detail
        if factor.coverage < WARN_FACTOR_COVERAGE:
            coverage_note = f"Veri kapsamı %{round(factor.coverage * 100)}"
            detail = f"{detail} · {coverage_note}" if detail else coverage_note
        if factor.coverage < MIN_FACTOR_COVERAGE:
            suppressed_names.add(factor.name)
            adjusted.append(replace(factor, score=None, detail=detail))
        else:
            adjusted.append(replace(factor, detail=detail))

    available = [factor.score for factor in adjusted if factor.score is not None]
    overall = round(sum(available) / len(available), 2) if available else None

    def keep_insight(text: str) -> bool:
        return not any(text.startswith(f"{name}:") for name in suppressed_names)

    positives = tuple(item for item in report.positives if keep_insight(item))
    risks = tuple(item for item in report.risks if keep_insight(item))
    return replace(
        report,
        overall_score=overall,
        factors=tuple(adjusted),
        positives=positives,
        risks=risks,
    )
