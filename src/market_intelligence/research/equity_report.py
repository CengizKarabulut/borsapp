"""Backward-compatible exports for the canonical equity research report v2."""

from market_intelligence.research.equity_report_v2 import (
    REPORT_TEMPLATE_VERSION,
    EquityResearchReport,
    ReportSection,
    ReportTable,
    analysis_message,
    build_equity_research_report,
)

__all__ = [
    "REPORT_TEMPLATE_VERSION",
    "EquityResearchReport",
    "ReportSection",
    "ReportTable",
    "analysis_message",
    "build_equity_research_report",
]
