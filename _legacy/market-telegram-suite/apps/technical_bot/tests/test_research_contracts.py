"""Contract tests for Beneish completeness and presentation-only sanitization."""

from __future__ import annotations

import unittest

import pandas as pd

from src.fundamental_analysis import FundamentalReport
from src.research_contracts import (
    _beneish,
    enrich_beneish,
    sanitize_profile_financials,
    sanitize_valuation,
)


class BeneishContractTests(unittest.TestCase):
    def _kwargs(self) -> dict:
        return {
            "revenue": 1_200.0,
            "revenue_prev": 1_000.0,
            "receivables": 180.0,
            "receivables_prev": 140.0,
            "gross_profit": 420.0,
            "gross_profit_prev": 360.0,
            "current_assets": 550.0,
            "current_assets_prev": 500.0,
            "ppe": 380.0,
            "ppe_prev": 360.0,
            "assets": 1_300.0,
            "assets_prev": 1_180.0,
            "depreciation": 45.0,
            "depreciation_prev": 42.0,
            "sga": 130.0,
            "sga_prev": 118.0,
            "liabilities": 520.0,
            "liabilities_prev": 500.0,
            "net_income": 120.0,
            "cfo": 135.0,
        }

    def test_beneish_requires_all_eight_components(self) -> None:
        full = _beneish(**self._kwargs())
        self.assertIsNotNone(full["value"])
        self.assertEqual(full["coverage"], 1.0)
        self.assertEqual(len(full["components"]), 8)

        missing_kwargs = self._kwargs()
        missing_kwargs["depreciation"] = None
        partial = _beneish(**missing_kwargs)
        self.assertIsNone(partial["value"])
        self.assertLess(partial["coverage"], 1.0)
        self.assertIsNone(partial["components"]["DEPI"])

    def test_statement_binding_uses_current_and_prior_four_quarters(self) -> None:
        periods = [f"2024Q{q}" for q in range(1, 5)] + [f"2025Q{q}" for q in range(1, 5)]

        def row(start: float, step: float) -> list[float]:
            return [start + step * index for index in range(8)]

        balance_rows = {
            "Total Assets": row(1_000, 30),
            "Current Assets": row(500, 15),
            "Total Equity": row(450, 12),
            "Trade Receivables": row(120, 3),
            "Total Liabilities": row(550, 18),
            "Property Plant and Equipment": row(300, 8),
        }
        income_rows = {
            "Sales Revenue": row(220, 8),
            "Gross Profit": row(80, 3),
            "Net Income": row(30, 1.5),
            "Depreciation and Amortization": row(9, 0.2),
            "Selling General and Administrative Expenses": row(18, 0.3),
        }
        cash_rows = {"Cash Flows from Operating Activities": row(42, 1.8)}

        balance = pd.DataFrame(
            {period: [values[index] for values in balance_rows.values()] for index, period in enumerate(periods)},
            index=list(balance_rows),
        )
        income = pd.DataFrame(
            {period: [values[index] for values in income_rows.values()] for index, period in enumerate(periods)},
            index=list(income_rows),
        )
        cashflow = pd.DataFrame(
            {period: [values[index] for values in cash_rows.values()] for index, period in enumerate(periods)},
            index=list(cash_rows),
        )
        fundamental = FundamentalReport(
            symbol="TST",
            company_name="Test AŞ",
            price=10.0,
            sector="Technology",
            profile="GENERIC",
            overall_score=None,
            coverage=0.0,
            factors=(),
            positives=(),
            risks=(),
            metrics={},
            note="",
        )

        result = enrich_beneish(
            {"forensic_scores": {"beneish_m": {"value": None, "coverage": 0.0}}},
            fundamental,
            balance,
            income,
            cashflow,
        )
        beneish = result["forensic_scores"]["beneish_m"]
        self.assertIsNotNone(beneish["value"])
        self.assertEqual(beneish["coverage"], 1.0)


class SanitizationContractTests(unittest.TestCase):
    def test_multiple_sentinels_are_removed_without_overwriting_raw_yields(self) -> None:
        valuation = {
            "metrics": {
                "pe": {"value": -15.0, "percentile": 20.0},
                "pb": {"value": 1.5, "percentile": 30.0},
                "ev_ebitda": {"value": 12_000.0, "percentile": 80.0},
                "ev_sales": {"value": 2.0, "percentile": 40.0},
                "ps": {"value": 2.5, "percentile": None},
                "p_fcf": {"value": 10.0, "percentile": None},
                "peg": {"value": 0.9, "percentile": None},
                "earnings_yield": {"value": -7.5, "percentile": None},
                "fcf_yield": {"value": -2.0, "percentile": None},
            },
            "peer_analysis": {
                "peers": [
                    {"symbol": "AAA", "pe": -9.0, "pb": 2.0, "ev_ebitda": 11_000.0, "ev_sales": 3.0},
                    {"symbol": "BBB", "pe": 12.0, "pb": 1.5, "ev_ebitda": 8.0, "ev_sales": 2.0},
                ]
            },
        }

        result = sanitize_valuation(valuation)
        metrics = result["metrics"]
        self.assertIsNone(metrics["pe"]["value"])
        self.assertIsNone(metrics["ev_ebitda"]["value"])
        self.assertEqual(metrics["pb"]["value"], 1.5)
        self.assertEqual(metrics["earnings_yield"]["value"], -7.5)
        self.assertEqual(metrics["fcf_yield"]["value"], -2.0)
        self.assertIsNone(result["peer_analysis"]["peers"][0]["pe"])
        self.assertIsNone(result["peer_analysis"]["peers"][0]["ev_ebitda"])
        self.assertEqual(result["peer_analysis"]["peers"][1]["pe"], 12.0)
        self.assertIn("zorla eşitlenmez", result["multiple_quality_note"])

    def test_gyo_extreme_margins_move_to_non_comparable_raw_bucket(self) -> None:
        financial = {
            "metrics": {
                "gross_margin": 95.0,
                "operating_margin": 1_700.0,
                "operating_margin_quarterly": 26_000.0,
                "net_margin": 4_800.0,
                "net_margin_quarterly": 18_000.0,
            },
            "ratio_groups": (
                {
                    "name": "Kârlılık Oranları",
                    "rows": (
                        {"key": "gross_margin", "label": "Brüt Kâr Marjı", "unit": "%", "value": 95.0},
                        {"key": "operating_margin", "label": "Esas Faaliyet Kâr Marjı", "unit": "%", "value": 1_700.0},
                        {"key": "net_margin", "label": "Net Kâr Marjı", "unit": "%", "value": 4_800.0},
                    ),
                },
            ),
            "ratio_note": "Temel not.",
        }

        result = sanitize_profile_financials(financial, "GYO")
        self.assertEqual(result["metrics"]["gross_margin"], 95.0)
        self.assertIsNone(result["metrics"]["operating_margin"])
        self.assertIsNone(result["metrics"]["net_margin"])
        self.assertEqual(result["non_comparable_metrics"]["operating_margin"], 1_700.0)
        rows = result["ratio_groups"][0]["rows"]
        self.assertEqual(rows[0]["value"], 95.0)
        self.assertIsNone(rows[1]["value"])
        self.assertIsNone(rows[2]["value"])
        self.assertIn("ham değer JSON'da korunur", result["ratio_note"])


if __name__ == "__main__":
    unittest.main()
