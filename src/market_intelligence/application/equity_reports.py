from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from market_intelligence.application.symbol_commands import SymbolSnapshot
from market_intelligence.features.registry import FeatureEngine
from market_intelligence.features.research import (
    RESEARCH_TECHNICAL_SNAPSHOT,
    ResearchTechnicalSnapshot,
)
from market_intelligence.fundamentals.providers import FinancialProviderChain
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.research.equity_report_v2 import (
    EquityResearchReport,
    build_equity_research_report,
)
from market_intelligence.research.pdf_report import RenderedPdf, render_equity_research_pdf


@dataclass(frozen=True)
class GeneratedEquityReport:
    report_id: str
    summary: str
    rendered: RenderedPdf
    instrument_id: str
    timeframe: str
    bar_time: datetime


class EquityReportService:
    """Application service: orchestration only; calculations live in feature/providers."""

    def __init__(
        self,
        *,
        feature_engine: FeatureEngine,
        financials: FinancialProviderChain,
    ) -> None:
        self.feature_engine = feature_engine
        self.financials = financials

    def assemble(
        self,
        *,
        frame: CanonicalFrame,
        stored: SymbolSnapshot,
        generated_at: datetime,
    ) -> EquityResearchReport:
        resolution = self.feature_engine.resolve(frame, (RESEARCH_TECHNICAL_SNAPSHOT,))
        technical = resolution.values.get(RESEARCH_TECHNICAL_SNAPSHOT.feature_id)
        if not isinstance(technical, ResearchTechnicalSnapshot):
            missing = ",".join(resolution.unavailable) or "research.technical_snapshot"
            raise ValueError(f"Rapor feature verisi üretilemedi: {missing}")
        financial = self.financials.fetch(frame.symbol_at_snapshot, as_of=frame.through_bar_time)
        return build_equity_research_report(
            frame=frame,
            technical=technical,
            stored=stored,
            financial=financial,
            generated_at=generated_at,
        )

    def generate(
        self,
        *,
        frame: CanonicalFrame,
        stored: SymbolSnapshot,
        generated_at: datetime,
        target: Path,
    ) -> GeneratedEquityReport:
        report = self.assemble(
            frame=frame,
            stored=stored,
            generated_at=generated_at,
        )
        rendered = render_equity_research_pdf(report, target)
        return GeneratedEquityReport(
            report_id=report.report_id,
            summary=report.summary,
            rendered=rendered,
            instrument_id=report.instrument_id,
            timeframe=frame.timeframe.value,
            bar_time=report.as_of_bar,
        )
