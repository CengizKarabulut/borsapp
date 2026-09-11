import unittest

from market_intelligence.research.valuation import (
    CapitalCost,
    ForecastYear,
    ValuationInputError,
    discounted_cash_flow,
    fcff,
)


class ValuationTests(unittest.TestCase):
    def test_pdf_capital_cost_example(self):
        result = CapitalCost(0.14, 1, 0.06, 0.05, 0.20, 0.25, 0.70, 0.30).calculate()
        self.assertAlmostEqual(result["wacc"], 0.22)
        self.assertAlmostEqual(result["cost_of_equity"], 0.25)

    def test_fcff_bridge(self):
        result = fcff(
            ebit=100, tax_rate=0.25, depreciation_amortization=20, capex=30, delta_operating_nwc=10
        )
        self.assertEqual(result["fcff"], 55)

    def test_dcf_matches_independent_discount_sum(self):
        rows = [
            ForecastYear(i, cash, 0, 0, 0, 0)
            for i, cash in enumerate([1.23, 1.64, 2.03, 2.44, 2.848], 1)
        ]
        result = discounted_cash_flow(
            rows,
            wacc=0.22,
            terminal_growth=0.08,
            net_debt=3.2,
            total_diluted_shares=0.15,
            equity_bridge_adjustment=0,
        )
        ev = (
            sum(c / 1.22**i for i, c in enumerate([1.23, 1.64, 2.03, 2.44, 2.848], 1))
            + 2.848 * 1.08 / (0.22 - 0.08) / 1.22**5
        )
        self.assertAlmostEqual(result["value_per_share"], (ev - 3.2) / 0.15)

    def test_invalid_terminal_spread_rejected(self):
        with self.assertRaises(ValuationInputError):
            discounted_cash_flow(
                [ForecastYear(1, 100, 0, 0, 0, 0)],
                wacc=0.1,
                terminal_growth=0.1,
                net_debt=0,
                total_diluted_shares=10,
                equity_bridge_adjustment=0,
            )

    def test_missing_investment_is_not_zero(self):
        with self.assertRaises(ValuationInputError):
            fcff(
                ebit=100,
                tax_rate=0.25,
                depreciation_amortization=20,
                capex=None,
                delta_operating_nwc=0,
            )
