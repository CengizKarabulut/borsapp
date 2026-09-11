from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from market_intelligence.application.symbol_commands import StoredNews, SymbolSnapshot
from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.decision import DecisionPanelV645Provider
from market_intelligence.features.momentum import MacdProvider, RsiProvider, SmiProvider
from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.features.research import (
    RESEARCH_TECHNICAL_SNAPSHOT,
    ResearchTechnicalSnapshot,
    ResearchTechnicalSnapshotProvider,
)
from market_intelligence.features.technical import TechnicalMarketContextProvider
from market_intelligence.features.volatility import WilderAtr14Provider
from market_intelligence.fundamentals.providers import FinancialSnapshot
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.research.equity_report_v2 import build_equity_research_report
from market_intelligence.research.pdf_report import render_equity_research_pdf


def frame() -> CanonicalFrame:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = []
    for index in range(340):
        close = 50.0 + index * 0.08 + math.sin(index / 8.0) * 1.8
        opened = close - math.sin(index / 3.0) * 0.3
        bars.append(
            CanonicalBar(
                open_time=start + timedelta(days=index),
                close_time=start + timedelta(days=index + 1),
                open=opened,
                high=max(opened, close) + 0.9,
                low=min(opened, close) - 0.8,
                close=close,
                volume=1_000_000.0 + index * 1_000.0,
            )
        )
    return CanonicalFrame(
        instrument_id="00000000-0000-0000-0000-000000000001",
        symbol_at_snapshot="ASELS",
        market="BIST",
        timeframe=Timeframe.D1,
        snapshot_id="snapshot-report",
        series_revision=3,
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        source="fixture",
        bars=tuple(bars),
    )


def technical_snapshot(source: CanonicalFrame) -> ResearchTechnicalSnapshot:
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
    result = FeatureEngine(registry).resolve(source, (RESEARCH_TECHNICAL_SNAPSHOT,))
    value = result.values.get(RESEARCH_TECHNICAL_SNAPSHOT.feature_id)
    assert isinstance(value, ResearchTechnicalSnapshot)
    return value


def financial() -> FinancialSnapshot:
    metrics = {
        "revenue_ttm": 100_000_000.0,
        "revenue_growth": 18.0,
        "net_income_ttm": 12_000_000.0,
        "net_margin": 12.0,
        "assets": 220_000_000.0,
        "equity": 100_000_000.0,
        "cash": 20_000_000.0,
        "total_debt": 35_000_000.0,
        "net_debt": 15_000_000.0,
        "current_ratio": 1.8,
        "debt_equity": 0.35,
        "roe": 12.0,
        "roa": 5.5,
        "market_cap": 300_000_000.0,
        "pe": 25.0,
        "pb": 3.0,
        "ev_ebitda": 14.0,
        "cfo_ttm": 16_000_000.0,
    }
    return FinancialSnapshot(
        symbol="ASELS",
        as_of=datetime(2026, 9, 7, tzinfo=UTC),
        company_name="ASELSAN DEMO",
        sector="Savunma",
        currency="TRY",
        metrics=metrics,
        metric_sources={key: "fixture:kap" for key in metrics},
        statement_periods=("2026-06-30",),
        providers_used=("fixture:kap",),
    )


class EquityReportTests(unittest.TestCase):
    def test_contract_has_25_sections_and_deterministic_report_id(self) -> None:
        source = frame()
        kwargs = {
            "frame": source,
            "technical": technical_snapshot(source),
            "stored": SymbolSnapshot(source.instrument_id, "ASELS"),
            "financial": financial(),
            "generated_at": datetime(2026, 9, 8, tzinfo=UTC),
        }

        first = build_equity_research_report(**kwargs)
        second = build_equity_research_report(
            **{**kwargs, "generated_at": datetime(2026, 9, 9, tzinfo=UTC)}
        )

        self.assertEqual(len(first.sections), 25)
        self.assertEqual(first.report_id, second.report_id)
        self.assertEqual(first.sections[4].status, "AVAILABLE")
        self.assertNotIn("AL/SAT", first.conclusion)
        machine = json.loads(first.machine_readable_json())
        self.assertEqual(machine["ticker"], "ASELS")
        self.assertEqual(machine["timeframes"]["1d"]["status"], "AVAILABLE")
        self.assertEqual(machine["timeframes"]["1h"], {})
        self.assertIsNone(machine["technical"]["bos_level"])
        self.assertTrue(
            any(item.startswith("timeframes:") for item in machine["confidence"]["missing_data"])
        )

    def test_hourly_and_daily_snapshots_create_partial_mtf_dashboard(self) -> None:
        daily = frame()
        hourly = replace(daily, timeframe=Timeframe.H1, snapshot_id="snapshot-report-h1")
        hourly_technical = technical_snapshot(hourly)
        report = build_equity_research_report(
            frame=daily,
            technical=technical_snapshot(daily),
            stored=SymbolSnapshot(daily.instrument_id, "ASELS"),
            financial=financial(),
            generated_at=datetime(2026, 9, 8, tzinfo=UTC),
            timeframe_technicals={
                "1h": hourly_technical,
                "1d": technical_snapshot(daily),
            },
        )
        machine = json.loads(report.machine_readable_json())
        self.assertEqual(report.sections[15].status, "PARTIAL")
        self.assertEqual(machine["timeframes"]["1h"]["status"], "AVAILABLE")
        self.assertEqual(machine["timeframes"]["1d"]["status"], "AVAILABLE")
        self.assertGreater(report.technical_coverage, 80.0)

    def test_kap_title_and_inflation_are_report_inputs(self) -> None:
        source = frame()
        stored = SymbolSnapshot(
            source.instrument_id,
            "ASELS",
            news=(
                StoredNews(
                    "Finansal rapor",
                    datetime(2026, 9, 8, tzinfo=UTC),
                    source="kap",
                    provider="ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.",
                ),
            ),
        )
        kwargs = {
            "frame": source,
            "technical": technical_snapshot(source),
            "stored": stored,
            "financial": financial(),
            "generated_at": datetime(2026, 9, 8, tzinfo=UTC),
        }

        report = build_equity_research_report(**kwargs, inflation_yoy_pct=32.11)
        other_inflation = build_equity_research_report(
            **kwargs,
            inflation_yoy_pct=30.0,
        )

        company_row = report.sections[1].tables[0].rows[0]
        self.assertEqual(company_row[1], "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.")
        revenue_row = report.sections[4].tables[0].rows[0]
        self.assertIn("TMS-29 bazı doğrulanmadı", revenue_row[3])
        self.assertNotEqual(report.report_id, other_inflation.report_id)
        self.assertEqual(
            report.machine_readable["fundamental"]["inflation"]["yoy_pct"],
            32.11,
        )

    def test_pdf_is_created_with_all_section_titles(self) -> None:
        source = frame()
        report = build_equity_research_report(
            frame=source,
            technical=technical_snapshot(source),
            stored=SymbolSnapshot(source.instrument_id, "ASELS"),
            financial=financial(),
            generated_at=datetime(2026, 9, 8, tzinfo=UTC),
        )
        with tempfile.TemporaryDirectory() as directory:
            rendered = render_equity_research_pdf(report, Path(directory) / "ASELS.pdf")
            self.assertGreater(rendered.size_bytes, 10_000)
            self.assertTrue(rendered.path.is_file())


if __name__ == "__main__":
    unittest.main()
