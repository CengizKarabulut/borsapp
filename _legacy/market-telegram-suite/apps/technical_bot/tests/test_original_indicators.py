from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.original_indicators import (
    build_indicator_frame,
    moving_averages,
    rsi,
    rsi_divergences,
)


class OriginalIndicatorTests(unittest.TestCase):
    def frame(self, periods: int = 320) -> pd.DataFrame:
        index = pd.date_range("2025-01-02", periods=periods, freq="B")
        base = 100.0 + np.linspace(0.0, 35.0, periods) + np.sin(np.arange(periods) / 5.0) * 4.0
        close = pd.Series(base, index=index)
        return pd.DataFrame(
            {
                "Open": close - 0.35,
                "High": close + 1.2,
                "Low": close - 1.1,
                "Close": close,
                "Volume": 1_000_000 + (np.sin(np.arange(periods) / 7.0) + 1.5) * 350_000,
            },
            index=index,
        )

    def test_indicator_stack_produces_original_default_columns(self) -> None:
        data, divergences = build_indicator_frame(self.frame())
        expected = {
            "RSI14",
            "RSI_MA14",
            "SMI",
            "SMI_SIGNAL",
            "MACD",
            "MACD_SIGNAL",
            "MACD_HIST",
            "OBV",
            "ATR14",
            "BB_MID",
            "BB_UPPER",
            "BB_LOWER",
            "AlphaTrend",
            "AlphaTrendLag2",
            "AlphaTrendBuy",
            "AlphaTrendSell",
        }
        self.assertTrue(expected.issubset(data.columns))
        self.assertTrue(data["RSI14"].dropna().between(0, 100).all())
        self.assertTrue(np.isfinite(data["RSI_MA14"].dropna().iloc[-1]))
        self.assertTrue((data["BB_UPPER"].dropna() >= data.loc[data["BB_UPPER"].dropna().index, "BB_MID"]).all())
        self.assertTrue((data["BB_LOWER"].dropna() <= data.loc[data["BB_LOWER"].dropna().index, "BB_MID"]).all())
        self.assertGreater(data["ATR14"].dropna().iloc[-1], 0)
        self.assertIsInstance(divergences, tuple)

    def test_wilder_rsi_reaches_expected_extremes(self) -> None:
        frame = self.frame(80)
        frame["Close"] = np.arange(1.0, 81.0)
        frame["High"] = frame["Close"] + 1.0
        frame["Low"] = frame["Close"] - 1.0
        result = rsi(frame, 14)
        self.assertAlmostEqual(float(result.dropna().iloc[-1]), 100.0, places=6)

    def test_divergence_retains_previous_pivot_for_original_line(self) -> None:
        frame = self.frame(40)
        osc = pd.Series(50.0, index=frame.index)
        osc.iloc[10] = 20.0
        osc.iloc[20] = 30.0
        frame.loc[frame.index[10], "Low"] = 90.0
        frame.loc[frame.index[20], "Low"] = 85.0
        points = rsi_divergences(frame, osc, left=2, right=2, range_lower=5, range_upper=60)
        bullish = [point for point in points if point.kind == "Regular Bullish"]
        self.assertTrue(bullish)
        latest = bullish[-1]
        self.assertEqual(latest.previous_index, frame.index[10])
        self.assertAlmostEqual(float(latest.previous_rsi), 20.0)
        self.assertEqual(latest.index, frame.index[20])

    def test_daily_ma_set_contains_all_requested_periods(self) -> None:
        averages = moving_averages(self.frame())
        self.assertEqual(
            list(averages.columns),
            ["MA5", "MA8", "MA13", "MA21", "MA34", "MA55", "MA89", "MA144", "MA233"],
        )
        self.assertTrue(np.isfinite(averages["MA233"].iloc[-1]))


if __name__ == "__main__":
    unittest.main()
