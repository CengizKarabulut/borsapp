from __future__ import annotations

import unittest

from src.valuation_models import (
    DCFInputs,
    NAVInputs,
    blend_valuations,
    fisher_real_rate,
    margin_of_safety,
    monte_carlo_dcf,
    nav_per_share,
    nav_premium,
    residual_income_value,
    run_dcf,
    tms29_index,
)


class ValuationModelsTests(unittest.TestCase):
    def test_nav_and_market_relation(self) -> None:
        nav = nav_per_share(
            NAVInputs(
                portfolio_fair_value=1_000.0,
                cash_and_equivalents=100.0,
                financial_debt=200.0,
                other_liabilities=50.0,
                shares_outstanding=10.0,
            )
        )
        self.assertAlmostEqual(nav["nav"], 850.0)
        self.assertAlmostEqual(nav["nav_per_share"], 85.0)
        relation = nav_premium(68.0, nav["nav_per_share"])
        self.assertAlmostEqual(relation["pd_nav"], 0.8)
        self.assertAlmostEqual(relation["premium"], -0.2)

    def test_residual_income_equals_book_when_roe_equals_cost(self) -> None:
        result = residual_income_value(
            book_value_0=100.0,
            roe_forecast=[0.20, 0.20, 0.20],
            cost_of_equity=0.20,
            persistence=0.0,
            payout_ratio=1.0,
        )
        self.assertAlmostEqual(result["value"], 100.0)
        self.assertAlmostEqual(result["implied_pb"], 1.0)

    def test_dcf_requires_r_above_g(self) -> None:
        with self.assertRaises(ValueError):
            run_dcf(DCFInputs(fcff=(10.0, 11.0), wacc=0.10, terminal_growth=0.10))

    def test_monte_carlo_is_deterministic_and_ordered(self) -> None:
        base = DCFInputs(
            fcff=(10.0, 11.0, 12.0, 13.0, 14.0),
            wacc=0.20,
            terminal_growth=0.05,
            net_debt=5.0,
            shares_outstanding=10.0,
        )
        first = monte_carlo_dcf(
            base,
            wacc_mu=0.20,
            wacc_sigma=0.01,
            growth_mu=0.05,
            growth_sigma=0.005,
            n_sims=500,
            seed=7,
        )
        second = monte_carlo_dcf(
            base,
            wacc_mu=0.20,
            wacc_sigma=0.01,
            growth_mu=0.05,
            growth_sigma=0.005,
            n_sims=500,
            seed=7,
        )
        self.assertEqual(first, second)
        self.assertLess(first["p05"], first["p25"])
        self.assertLess(first["p25"], first["p75"])
        self.assertLess(first["p75"], first["p95"])

    def test_real_rate_and_tms29_are_consistent(self) -> None:
        self.assertAlmostEqual(fisher_real_rate(0.50, 0.40), 1.5 / 1.4 - 1.0)
        self.assertAlmostEqual(tms29_index(100.0, 150.0, 100.0), 150.0)

    def test_blend_and_margin_of_safety(self) -> None:
        blend = blend_valuations({"DCF": 100.0, "EPV": 80.0}, {"DCF": 2.0, "EPV": 1.0})
        self.assertAlmostEqual(blend["blended_value"], 280.0 / 3.0)
        mos = margin_of_safety(100.0, 75.0)
        self.assertAlmostEqual(mos["upside"], 1.0 / 3.0)
        self.assertAlmostEqual(mos["margin_of_safety"], 0.25)


if __name__ == "__main__":
    unittest.main()
