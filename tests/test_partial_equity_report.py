import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

from market_intelligence.application.equity_reports import EquityReportService
from market_intelligence.application.symbol_commands import SymbolSnapshot
from market_intelligence.research.equity_report_v2 import analysis_message
from tests.test_equity_report import financial, frame


class PartialReportTests(unittest.TestCase):
    def make(self, fin=True):
        source = frame()
        source = replace(source, bars=source.bars[-50:])
        engine = SimpleNamespace(
            resolve=lambda *args: SimpleNamespace(
                values={}, unavailable=("decision.panel_v645", "research.technical_snapshot")
            )
        )
        providers = SimpleNamespace(fetch=lambda *args, **kwargs: financial() if fin else None)
        report = EquityReportService(feature_engine=engine, financials=providers).assemble(
            frame=source,
            stored=SymbolSnapshot(source.instrument_id, source.symbol_at_snapshot),
            generated_at=datetime(2026, 9, 19, tzinfo=UTC),
        )
        return report

    def test_missing_technical_keeps_financials_and_never_invents_scores(self):
        report = self.make()
        self.assertEqual(len(report.sections), 25)
        self.assertIsNone(report.technical_score)
        self.assertIsNone(report.confidence_score)
        self.assertEqual(report.sections[9].status, "UNKNOWN")
        self.assertEqual(report.sections[4].status, "PARTIAL")
        machine = json.loads(report.machine_readable_json())
        self.assertEqual(machine["financial"]["metrics"]["revenue_ttm"], 100000000)
        self.assertEqual(machine["financial"]["metric_sources"]["revenue_ttm"], "fixture:kap")
        self.assertIn("Kısmi rapor", analysis_message(report))
        self.assertIn("Hesaplanamadı", report.summary)

    def test_missing_financial_and_technical_stays_unknown(self):
        report = self.make(False)
        self.assertIsNone(report.financial_health_score)
        self.assertEqual(report.sections[4].status, "UNKNOWN")
        self.assertIsNone(json.loads(report.machine_readable_json())["financial"])
