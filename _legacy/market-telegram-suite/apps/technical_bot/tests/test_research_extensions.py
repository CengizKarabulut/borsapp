"""Regression tests for PR #13 ratio/card port on current raw-first policy."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from src.fundamental_analysis import FundamentalReport
from src.research_extensions import enrich_financial_analysis, enrich_valuation


def _peer_frame() -> pd.DataFrame:
    rows = []
    for index in range(10):
        rows.append(
            {
                "symbol": "TST" if index == 0 else f"P{index}",
                "name": "Target" if index == 0 else f"Peer {index}",
                "sector": "Technology",
                "industry": "Software",
                "market_cap": 1_000.0 + index * 100.0,
                "pe": 8.0 + index,
                "pb": 1.0 + index * 0.2,
                "ev_ebitda": 5.0 + index * 0.5,
                "ev_sales": 1.0 + index * 0.15,
                "roe": 10.0 + index,
            }
        )
    return pd.DataFrame(rows)


def _base_valuation() -> dict:
    return {
        "score": 99.0,
        "coverage": 1.0,
        "scope": "provider scope",
        "metrics": {
            "pe": {"value": 14.0, "percentile": 50.0},
            "pb": {"value": 1.4, "percentile": 50.0},
            "ev_ebitda": {"value": 7.0, "percentile": 50.0},
            "ev_sales": {"value": 1.8, "percentile": 50.0},
            "ps": {"value": 2.5, "percentile": None},
            "p_fcf": {"value": 20.0, "percentile": None},
            "peg": {"value": 0.8, "percentile": None},
            "earnings_yield": {"value": 7.1, "percentile": None},
            "fcf_yield": {"value": 5.0, "percentile": None},
        },
    }


class RawFirstValuationTests(unittest.TestCase):
    def test_non_positive_raw_denominators_are_nm_and_provider_cannot_mask_them(self) -> None:
        financial = {
            "metrics": {
                "market_cap": 1_000.0,
                "total_financial_debt": 100.0,
                "cash": 50.0,
                "equity": 500.0,
                "revenue_ttm": 500.0,
                "ebitda_ttm": 100.0,
                "net_income_ttm": -100.0,
                "fcf_ttm": -20.0,
                "net_income_growth": 25.0,
            }
        }
        with patch("src.research_extensions.core._fetch_peer_snapshot", return_value=_peer_frame()):
            result = enrich_valuation(_base_valuation(), financial, symbol="TST", profile="GENERIC")

        metrics = result["metrics"]
        self.assertIsNone(metrics["pe"]["value"])
        self.assertIsNone(metrics["p_fcf"]["value"])
        self.assertIsNone(metrics["peg"]["value"])
        self.assertAlmostEqual(metrics["pb"]["value"], 2.0)
        self.assertAlmostEqual(metrics["ev_ebitda"]["value"], 10.5)
        self.assertAlmostEqual(metrics["ev_sales"]["value"], 2.1)
        self.assertAlmostEqual(metrics["ps"]["value"], 2.0)
        self.assertAlmostEqual(metrics["earnings_yield"]["value"], -10.0)
        self.assertAlmostEqual(metrics["fcf_yield"]["value"], -2.0)
        self.assertAlmostEqual(result["coverage"], 0.75)
        self.assertIsNone(result["peer_analysis"]["benchmarks"]["pe"]["target"])

    def test_provider_multiple_survives_only_when_raw_input_is_missing(self) -> None:
        financial = {
            "metrics": {
                "market_cap": None,
                "total_financial_debt": 100.0,
                "cash": 50.0,
                "equity": 500.0,
                "revenue_ttm": 500.0,
                "ebitda_ttm": 100.0,
                "net_income_ttm": -100.0,
                "fcf_ttm": -20.0,
                "net_income_growth": 25.0,
            }
        }
        with patch("src.research_extensions.core._fetch_peer_snapshot", return_value=_peer_frame()):
            result = enrich_valuation(_base_valuation(), financial, symbol="TST", profile="GENERIC")

        metrics = result["metrics"]
        self.assertEqual(metrics["pe"]["value"], 14.0)
        self.assertEqual(metrics["pb"]["value"], 1.4)
        self.assertEqual(metrics["ev_ebitda"]["value"], 7.0)
        self.assertEqual(metrics["ev_sales"]["value"], 1.8)
        self.assertEqual(metrics["ps"]["value"], 2.5)
        self.assertEqual(metrics["p_fcf"]["value"], 20.0)


class FinancialEnrichmentTests(unittest.TestCase):
    def test_statement_ratios_and_forensic_payload_are_populated(self) -> None:
        periods = [f"2024Q{q}" for q in range(1, 5)] + [f"2025Q{q}" for q in range(1, 5)]

        def row(start: float, step: float) -> list[float]:
            return [start + step * index for index in range(8)]

        balance = pd.DataFrame(
            {
                period: values
                for period, values in zip(
                    periods,
                    zip(
                        row(1_000, 40),
                        row(500, 20),
                        row(250, 8),
                        row(450, 18),
                        row(100, 4),
                        row(90, 2),
                        row(120, 3),
                        row(80, 2),
                        row(60, 1),
                        row(140, 2),
                        row(550, 22),
                        row(300, 8),
                        row(100, 4),
                        row(50, 0),
                    ),
                    strict=True,
                )
            },
            index=[
                "Total Assets",
                "Current Assets",
                "Current Liabilities",
                "Total Equity",
                "Cash and Cash Equivalents",
                "Inventories",
                "Trade Receivables",
                "Trade Payables",
                "Short Term Borrowings",
                "Long Term Borrowings",
                "Total Liabilities",
                "Property Plant and Equipment",
                "Retained Earnings",
                "Issued Capital",
            ],
        )
        income = pd.DataFrame(
            {
                period: values
                for period, values in zip(
                    periods,
                    zip(
                        row(220, 8),
                        row(80, 3),
                        row(45, 2),
                        row(55, 2),
                        row(30, 1.5),
                        row(-8, -0.2),
                        row(9, 0.2),
                        row(18, 0.3),
                        row(6, 0.1),
                    ),
                    strict=True,
                )
            },
            index=[
                "Sales Revenue",
                "Gross Profit",
                "Operating Profit",
                "EBITDA",
                "Net Income",
                "Finance Expenses",
                "Depreciation and Amortization",
                "Selling General and Administrative Expenses",
                "Tax Expense Income",
            ],
        )
        cashflow = pd.DataFrame(
            {
                period: values
                for period, values in zip(
                    periods,
                    zip(row(42, 1.8), row(-10, -0.2)),
                    strict=True,
                )
            },
            index=["Cash Flows from Operating Activities", "Capital Expenditures"],
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
            metrics={"net_income_growth": 12.0},
            note="",
        )
        with (
            patch(
                "src.research_extensions._market_snapshot",
                return_value={"market_cap": 2_000.0, "enterprise_value": 2_100.0, "shares_outstanding": 100.0},
            ),
            patch("src.research_extensions._beta", return_value=0.9),
        ):
            result = enrich_financial_analysis({}, fundamental, balance, income, cashflow)

        metrics = result["metrics"]
        self.assertEqual(len(result["ratio_groups"]), 4)
        self.assertIn("forensic_scores", result)
        self.assertGreater(metrics["current_ratio"], 1.0)
        self.assertGreater(metrics["revenue_ttm"], 0.0)
        self.assertGreater(metrics["ebitda_ttm"], 0.0)
        self.assertGreater(metrics["net_income_ttm"], 0.0)
        self.assertEqual(metrics["market_cap"], 2_000.0)
        self.assertEqual(metrics["beta"], 0.9)
        self.assertIn("piotroski_f", result["forensic_scores"])


if __name__ == "__main__":
    unittest.main()
