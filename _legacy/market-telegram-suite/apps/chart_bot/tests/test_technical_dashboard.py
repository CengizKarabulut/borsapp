"""Teknik dashboard duman testleri (ag baglantisi gerektirmez)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from src import bot
from src.technical_dashboard import _alpha_trend, _market_structure, render_dashboard


def _frame(rows: int = 260) -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=rows)
    x = np.arange(rows, dtype=float)
    close = 45.0 + x * 0.055 + np.sin(x / 6.0) * 2.8 + np.sin(x / 19.0) * 1.6
    open_ = close + np.sin(x / 3.7) * 0.45
    high = np.maximum(open_, close) + 0.7 + (np.sin(x / 4.0) + 1.0) * 0.18
    low = np.minimum(open_, close) - 0.7 - (np.cos(x / 5.0) + 1.0) * 0.16
    volume = 1_500_000 + (np.sin(x / 8.0) + 1.2) * 550_000 + (x % 17) * 20_000
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )


class AlphaTrendAndStructureTests(unittest.TestCase):
    def test_alpha_trend_and_structure_have_real_output(self) -> None:
        frame = _frame()
        alpha = _alpha_trend(frame)
        self.assertLessEqual(
            {"AlphaTrend", "AlphaTrendLag2", "AlphaTrendDir"}, set(alpha.columns)
        )
        self.assertGreater(alpha["AlphaTrend"].dropna().size, 150)
        self.assertLessEqual(set(alpha["AlphaTrendDir"].dropna().unique()), {-1.0, 1.0})

        structure = _market_structure(frame)
        self.assertTrue(structure["highs"])
        self.assertTrue(structure["lows"])
        labels = {item[2] for item in structure["highs"] + structure["lows"]}
        self.assertTrue(labels & {"HH", "LH"})
        self.assertTrue(labels & {"HL", "LL"})


class DashboardRenderTests(unittest.TestCase):
    def test_dashboard_renders_single_white_indicator_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ASELS_1d_teknik_dashboard.png"
            snapshot = render_dashboard(
                _frame(),
                output,
                symbol="ASELS",
                interval="1d",
                subtitle="test veri",
            )
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 80_000)

            with Image.open(output) as handle:
                image = handle.convert("RGB")
                self.assertGreater(image.width, 2000)
                self.assertGreater(image.height, 1400)
                # Beyaz/açık tema: köşe koyu eski TradingView zemini olmamalı.
                r, g, b = image.getpixel((5, 5))
            self.assertGreater(min(r, g, b), 230)

            labels = {label for label, _, _ in snapshot}
            self.assertLessEqual(
                {"Son", "Trend", "Momentum", "RSI", "RVOL", "ATR", "ADX"}, labels
            )


class CommandSurfaceTests(unittest.TestCase):
    def test_old_equal_grid_command_is_not_exposed(self) -> None:
        self.assertNotIn("kareler", bot.OWN_COMMANDS)
        self.assertEqual(bot._parse("/kareler", "chartbot"), ("kareler", []))
        self.assertEqual(
            bot._parse("/grafik ASELS 1d", "chartbot"), ("grafik", ["ASELS", "1d"])
        )


if __name__ == "__main__":
    unittest.main()
