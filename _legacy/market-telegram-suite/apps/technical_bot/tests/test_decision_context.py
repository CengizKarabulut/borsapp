import unittest

import numpy as np
import pandas as pd

from src.decision_context import (
    liquidity_context,
    multi_timeframe_context,
    relative_strength_context,
    risk_reference_context,
)
from src.stock_dashboard import calculate_indicators


def prices(rows: int = 520, growth: float = 1.0, volume: float = 2_000_000) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="B", tz="Europe/Istanbul")
    close = np.linspace(50.0, 50.0 + rows * growth, rows) + np.sin(np.arange(rows) / 9)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(rows, volume),
        },
        index=index,
    )


class DecisionContextTests(unittest.TestCase):
    def test_relative_strength_uses_aligned_benchmark_returns(self) -> None:
        stock = prices(growth=1.0)
        benchmark = prices(growth=0.25)
        result = relative_strength_context(stock, benchmark, "XU100")
        self.assertTrue(result["available"])
        self.assertEqual(result["state"], "Göreceli güçleniyor")
        self.assertGreater(result["periods"]["60"]["excess_return_pct"], 0)

    def test_mtf_contains_daily_weekly_monthly_without_future_data(self) -> None:
        result = multi_timeframe_context(prices())
        self.assertEqual([item["label"] for item in result["frames"]], ["Günlük", "Haftalık", "Aylık"])
        self.assertTrue(all(item["available"] for item in result["frames"]))

    def test_flat_mtf_rsi_is_neutral(self) -> None:
        flat = prices(growth=0.0)
        flat.loc[:, "Close"] = 50.0
        result = multi_timeframe_context(flat)
        self.assertEqual(result["frames"][0]["rsi14"], 50.0)

    def test_liquidity_warns_for_low_free_float(self) -> None:
        result = liquidity_context(prices(volume=1_000_000), "BIST", free_float_pct=7.5)
        self.assertIn("Halka açıklık %10 altında", result["warnings"])
        self.assertEqual(result["tone"], "negative")

    def test_risk_reference_calculates_position_from_risk_budget(self) -> None:
        data = calculate_indicators(prices())
        result = risk_reference_context(data, account_size=100_000, risk_pct=1, atr_multiple=2)
        self.assertTrue(result["available"])
        self.assertGreater(result["reference_quantity"], 0)
        self.assertAlmostEqual(result["risk_amount"], 1_000)
        self.assertGreater(result["long_reference_2r"], result["entry_reference"])


if __name__ == "__main__":
    unittest.main()
