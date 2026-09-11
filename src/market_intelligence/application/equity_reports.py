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
from market_intelligence.fundamentals.inflation import InflationDataProvider
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
        inflation: InflationDataProvider | None = None,
        valuation_assumptions_root: Path | None = None,
    ) -> None:
        self.feature_engine = feature_engine
        self.financials = financials
        self.inflation = inflation
        self.valuation_assumptions_root = valuation_assumptions_root

    def assemble(
        self,
        *,
        frame: CanonicalFrame,
        stored: SymbolSnapshot,
        generated_at: datetime,
        related_frames: tuple[CanonicalFrame, ...] = (),
    ) -> EquityResearchReport:
        resolution = self.feature_engine.resolve(frame, (RESEARCH_TECHNICAL_SNAPSHOT,))
        technical = resolution.values.get(RESEARCH_TECHNICAL_SNAPSHOT.feature_id)
        if not isinstance(technical, ResearchTechnicalSnapshot):
            missing = ",".join(resolution.unavailable) or "research.technical_snapshot"
            raise ValueError(f"Rapor feature verisi üretilemedi: {missing}")
        timeframe_technicals = {frame.timeframe.value: technical}
        for related in related_frames:
            if related.instrument_id != frame.instrument_id or related.is_partial:
                continue
            related_resolution = self.feature_engine.resolve(
                related,
                (RESEARCH_TECHNICAL_SNAPSHOT,),
            )
            related_technical = related_resolution.values.get(
                RESEARCH_TECHNICAL_SNAPSHOT.feature_id
            )
            if isinstance(related_technical, ResearchTechnicalSnapshot):
                timeframe_technicals[related.timeframe.value] = related_technical
        financial = self.financials.fetch(frame.symbol_at_snapshot, as_of=generated_at)
        inflation_yoy_pct = None
        if self.inflation is not None and financial and financial.flow_period:
            try:
                inflation_yoy_pct = self.inflation.fetch_yoy(
                    period_end=financial.flow_period
                )
            except Exception:
                # Inflation enrichment must not make the complete report unavailable.
                inflation_yoy_pct = None
        assumptions = None
        if self.valuation_assumptions_root:
            import json
            import re
            symbol = frame.symbol_at_snapshot
            if not re.fullmatch(r"[A-Z0-9]{2,12}", symbol):
                raise ValueError("Invalid report symbol")
            assumption_file = self.valuation_assumptions_root / (symbol + ".json")
            if assumption_file.is_file():
                assumptions = json.loads(assumption_file.read_text(encoding="utf-8"))
        return build_equity_research_report(
            valuation_assumptions=assumptions,
            frame=frame,
            technical=technical,
            stored=stored,
            financial=financial,
            generated_at=generated_at,
            timeframe_technicals=timeframe_technicals,
            inflation_yoy_pct=inflation_yoy_pct,
            inflation_provider_id=self.inflation.provider_id if self.inflation else None,
            inflation_period=financial.flow_period if financial else None,
        )

    def generate(
        self,
        *,
        frame: CanonicalFrame,
        stored: SymbolSnapshot,
        generated_at: datetime,
        target: Path,
        related_frames: tuple[CanonicalFrame, ...] = (),
    ) -> GeneratedEquityReport:
        report = self.assemble(
            frame=frame,
            stored=stored,
            generated_at=generated_at,
            related_frames=related_frames,
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
