"""Produce the production PDF/JSON views from real data without sending messages."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from market_intelligence.application.equity_reports import EquityReportService
from market_intelligence.application.symbol_commands import StoredNews, SymbolSnapshot
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.decision import DecisionPanelV645Provider
from market_intelligence.features.momentum import MacdProvider, RsiProvider, SmiProvider
from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.features.research import ResearchTechnicalSnapshotProvider
from market_intelligence.features.technical import TechnicalMarketContextProvider
from market_intelligence.features.volatility import WilderAtr14Provider
from market_intelligence.fundamentals.kap_archive import KapArchivedFinancialProvider
from market_intelligence.fundamentals.providers import (
    BorsapyKapFinancialProvider,
    FinancialProviderChain,
    YFinanceFinancialProvider,
)
from market_intelligence.fundamentals.quotes import MarketQuoteProvider
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.adapters.fallback import FallbackMarketDataProvider
from market_intelligence.market_data.adapters.yfinance import YFinanceBistProvider
from market_intelligence.market_data.canonicalizer import Canonicalizer
from market_intelligence.market_data.providers import FetchRequest
from market_intelligence.research.pdf_report import render_equity_research_pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("--archive-root", type=Path, default=Path("data/financial_archive"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(UTC)
    symbol = args.symbol.upper()
    instrument_id = str(uuid5(NAMESPACE_URL, "borsapp-preview:BIST:" + symbol))
    raw = FallbackMarketDataProvider((BorsapyProvider(), YFinanceBistProvider())).fetch(
        FetchRequest(symbol, Timeframe.D1, 500, now)
    )
    frame = Canonicalizer().build(
        instrument_id=instrument_id,
        symbol_at_snapshot=symbol,
        market="BIST",
        provider_frame=raw,
        target_timeframe=Timeframe.D1,
        series_revision=1,
    )
    registry = FeatureRegistry()
    for provider in (
        WilderAtr14Provider(),
        RsiProvider(),
        MacdProvider(),
        SmiProvider(),
        TechnicalMarketContextProvider(),
        DecisionPanelV645Provider(),
        ResearchTechnicalSnapshotProvider(),
    ):
        registry.register(provider)
    kap = KapArchivedFinancialProvider(args.archive_root)
    reports = kap.store.reports(symbol, known_at=now)
    news = tuple(
        StoredNews(
            "Finansal rapor · " + report["report_end"],
            datetime.fromisoformat(report["published_at"]),
            url=report["source_url"],
            source="kap",
            provider=report["company_name"] or "KAP",
        )
        for report in reports[:5]
    )
    service = EquityReportService(
        feature_engine=FeatureEngine(registry),
        financials=FinancialProviderChain(
            (kap, BorsapyKapFinancialProvider(args.archive_root), YFinanceFinancialProvider()),
            quote_provider=MarketQuoteProvider(),
        ),
        valuation_assumptions_root=args.archive_root / "assumptions",
    )
    report = service.assemble(
        frame=frame, stored=SymbolSnapshot(instrument_id, symbol, news=news), generated_at=now
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(report.machine_readable_json(), encoding="utf-8")
    rendered = render_equity_research_pdf(report, args.output)
    print(
        f"{rendered.path} | {rendered.size_bytes} bytes | source={frame.source} | bar={frame.through_bar_time.isoformat()}"
    )


if __name__ == "__main__":
    main()
