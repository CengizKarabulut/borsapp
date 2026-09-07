import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.stock_dashboard import render_report
from src.technical_commentary import build_technical_commentary


class TestRenderRegression(unittest.TestCase):
    def test_render_v2_commentary_produces_valid_png(self):
        dates = pd.date_range("2026-01-01", periods=300)
        data = pd.DataFrame({
            "Open": np.random.uniform(100, 110, 300),
            "High": np.random.uniform(110, 120, 300),
            "Low": np.random.uniform(90, 100, 300),
            "Close": np.random.uniform(100, 110, 300),
            "Volume": np.random.uniform(100000, 1000000, 300),
            "RSI": np.random.uniform(30, 70, 300),
            "RSI_MA": np.random.uniform(45, 55, 300),
            "MACD": np.random.uniform(-1, 1, 300),
            "MACD_SIGNAL": np.random.uniform(-1, 1, 300),
            "MACD_HIST": np.random.uniform(-1, 1, 300),
            "SMI": np.random.uniform(-100, 100, 300),
            "SMI_EMA": np.random.uniform(-100, 100, 300),
            "STOCH_K": np.random.uniform(0, 100, 300),
            "STOCH_D": np.random.uniform(0, 100, 300),
            "ATR": np.random.uniform(1, 5, 300),
            "OBV": np.cumsum(np.random.uniform(-100, 100, 300)),
            "BB_UPPER": np.random.uniform(120, 130, 300),
            "BB_MID": np.random.uniform(110, 120, 300),
            "BB_LOWER": np.random.uniform(90, 100, 300),
            "SUPERTREND": np.random.uniform(90, 100, 300),
        }, index=dates)
        for p in [21, 50, 55, 200, 233]:
            data[f"EMA_{p}"] = data["Close"].ewm(span=p).mean()

        ctx = {
            "regime": {"state": "Denge", "adx": 22.0, "adx_delta": 0.5, "tone": "warning", "candidate": "Denge"},
            "structure": {"state": "HH / HL", "high": 120.0, "low": 90.0, "tone": "positive"},
            "profile": {"position": "Value Area i?inde", "developing_acceptance": "Kabul yok", "poc": 102.0, "vah": 108.0, "val": 98.0, "poc_migration": "Yatay", "tone": "neutral"},
            "semantic": {
                "trend_quality": {"state": "Bullish", "tone": "positive", "spread_state": "geni?liyor", "summary": "Trend pozitif"},
                "momentum_character": {"state": "Pozitif", "tone": "positive", "summary": "Momentum g??l?", "macd": {"histogram_character": "geni?liyor"}, "active_divergences": []},
                "participation": {"state": "Normal", "tone": "neutral", "rvol_1": 1.1, "summary": "Kat?l?m normal"},
                "price_action": {"state": "G??l?", "tone": "positive", "patterns": [], "summary": "Fiyat g??l?"},
                "level_confluence": {"summary": "Seviye uyumu var", "nearest_support": None, "nearest_resistance": None, "clusters": []}
            },
            "events": []
        }
        decision = {
            "relative_strength": {"available": True, "state": "Strong", "benchmark": "XU100", "tone": "positive", "ratio_slope_5_pct": 1.2, "periods": {"20": {"stock_return_pct": 1.0, "benchmark_return_pct": 0.5, "excess_return_pct": 0.5}}},
            "multi_timeframe": {"state": "Aligned", "tone": "positive", "frames": [{"label": "D", "state": "Up"}]},
            "liquidity": {"state": "High", "average_turnover_20": 1000000, "free_float_pct": 50.0, "warnings": []},
        }
        comm = build_technical_commentary(data, ctx, decision, {"is_live": False})
        status = {
            "symbol": "TEST", "price": 105.0, "change_pct": 1.2, "timestamp": "2026-08-16",
            "interval": "1D", "bar_state": {"label": "CLOSED", "is_live": False},
            "data_provider": "Mock", "download_period": "2y",
            "technical_commentary": comm,
            "decision_rows": [["Relative Strength", "Strong", "Positive", "positive"]],
            "ma": [{"period": 21, "sma": 104.0, "ema": 104.5, "sma_color": "green", "ema_color": "green"}],
            "momentum": [["RSI", "65", "Bullish", "positive"]],
            "trend_volatility_volume": [["Trend", "Up", "Strong", "positive"]],
            "location": [["Price", "Above POC", "Bullish", "positive"]],
            "participation": [["RVOL", "1.2x", "Normal", "neutral"]],
            "events": [["Breakout", "2026-08-15", "Bullish", "positive"]],
            "equality_tolerance_pct": 0.02,
            "executive": [
                ["Rejim", "Denge", "ADX 20", "warning"],
                ["Yap?", "Up", "Summary", "positive"],
                ["Momentum", "Bullish", "Summary", "positive"],
                ["Kat?l?m", "Normal", "Summary", "neutral"],
                ["Konum", "Inside VA", "Summary", "neutral"],
                ["Relative Strength", "Strong", "Summary", "positive"],
                ["Price Action", "Strong", "Summary", "positive"],
            ]
        }
        temp_file = Path(tempfile.gettempdir()) / "test_render_regression.png"
        try:
            render_report(data, status, temp_file)
            self.assertTrue(temp_file.exists(), "PNG file should be created")
            self.assertTrue(temp_file.stat().st_size > 0, "PNG file size should be greater than 0")
        finally:
            if temp_file.exists():
                temp_file.unlink()

if __name__ == "__main__":
    unittest.main()


class TestTableWrapping(unittest.TestCase):
    def test_wrap_cell_respects_width_and_keeps_content(self) -> None:
        from src.stock_dashboard import wrap_cell

        text = "RSI 38.89 negatif bölge eğim5 -1.58 MACD negatif histogram genişliyor uyumsuzluk yok"
        wrapped = wrap_cell(text, 30)
        self.assertGreater(wrapped.count("\n"), 1)
        self.assertTrue(all(len(line) <= 30 for line in wrapped.split("\n")))
        self.assertEqual(wrapped.replace("\n", " ").split(), text.split())

    def test_wrap_cell_handles_short_text_without_breaking(self) -> None:
        from src.stock_dashboard import wrap_cell

        self.assertEqual(wrap_cell("Value Area içinde", 40), "Value Area içinde")

    def test_column_capacity_scales_with_column_width(self) -> None:
        import matplotlib.pyplot as plt

        from src.stock_dashboard import column_char_capacity

        figure = plt.figure(figsize=(18, 4))
        axes = figure.add_subplot(111)
        capacities = column_char_capacity(axes, [0.16, 0.38, 0.46], 3, 11)
        plt.close(figure)
        self.assertLess(capacities[0], capacities[1])
        self.assertLess(capacities[1], capacities[2])
        self.assertTrue(all(capacity >= 8 for capacity in capacities))


class PageConsistencyTests(unittest.TestCase):
    def test_all_images_share_width_and_respect_aspect_limit(self) -> None:
        import numpy as np
        import pandas as pd
        from PIL import Image

        from src.analyst_card import render_analyst_cards
        from src.stock_dashboard import (
            ScanConfig,
            build_status,
            calculate_indicators,
            render_report_pages,
        )

        rng = np.random.default_rng(3)
        bars = 300
        index = pd.bdate_range("2024-01-01", periods=bars)
        close = 300 * np.exp(np.cumsum(rng.normal(0, 0.015, bars)))
        frame = pd.DataFrame(
            {
                "Open": close,
                "High": close * 1.01,
                "Low": close * 0.99,
                "Close": close,
                "Volume": rng.lognormal(16, 0.3, bars),
            },
            index=index,
        )
        data = calculate_indicators(frame)
        status = build_status(data, ScanConfig(ticker="TEST"), "TEST")
        with tempfile.TemporaryDirectory() as directory:
            paths = render_report_pages(data, status, Path(directory)) + render_analyst_cards(status, Path(directory))
            sizes = [Image.open(path).size for path in paths]
            widths = {size[0] for size in sizes}
            self.assertGreaterEqual(len(paths), 4)
            self.assertEqual(len(widths), 1, f"Görsel genişlikleri aynı olmalı, bulunan: {widths}")
            for width, height in sizes:
                self.assertLessEqual(height / width, 2.75, "Hiçbir sayfa oran sınırını aşmamalı")

    def test_estimated_table_height_grows_with_wrapped_text(self) -> None:
        from src.stock_dashboard import estimate_table_height

        short_rows = [["A", "kısa", "kısa"]]
        long_rows = [["A", "kısa", "çok uzun bir metin " * 15]]
        self.assertGreater(
            estimate_table_height(long_rows, [0.2, 0.3, 0.5], 11, 11.0),
            estimate_table_height(short_rows, [0.2, 0.3, 0.5], 11, 11.0),
        )

    def test_multiline_cells_are_summed_not_maxed(self) -> None:
        from src.stock_dashboard import estimate_table_height

        single = estimate_table_height([["A", "satır", "satır"]], [0.2, 0.3, 0.5], 11, 11.0)
        multi = estimate_table_height([["A", "satır", "satır\nsatır\nsatır"]], [0.2, 0.3, 0.5], 11, 11.0)
        self.assertGreater(multi, single)


class DetailLevelTests(unittest.TestCase):
    def _render(self, detail: str):
        import numpy as np
        import pandas as pd

        from src.analyst_card import render_analyst_cards
        from src.stock_dashboard import (
            ScanConfig,
            build_status,
            calculate_indicators,
            render_report_pages,
        )

        rng = np.random.default_rng(21)
        bars = 400
        index = pd.bdate_range("2024-06-01", periods=bars)
        close = 300 * np.exp(np.cumsum(rng.normal(-0.0006, 0.016, bars)))
        frame = pd.DataFrame(
            {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": rng.lognormal(16.5, 0.3, bars)},
            index=index,
        )
        data = calculate_indicators(frame, "1d")
        status = build_status(data, ScanConfig(ticker="T", report_detail=detail), "T")
        directory = Path(tempfile.mkdtemp())
        return render_report_pages(data, status, directory) + render_analyst_cards(status, directory)

    def test_compact_level_includes_the_educational_analyst_page(self) -> None:
        self.assertEqual(len(self._render("kompakt")), 5)

    def test_full_level_produces_more_images_than_compact(self) -> None:
        self.assertGreater(len(self._render("tam")), len(self._render("kompakt")))

    def test_layered_commentary_panel_only_appears_in_full_level(self) -> None:
        import numpy as np
        import pandas as pd

        from src.stock_dashboard import (
            PAGE_WIDTH_INCHES,
            ScanConfig,
            _report_panels,
            build_status,
            calculate_indicators,
        )

        rng = np.random.default_rng(3)
        bars = 300
        index = pd.bdate_range("2024-01-01", periods=bars)
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, bars)))
        frame = pd.DataFrame(
            {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": rng.lognormal(16, 0.3, bars)},
            index=index,
        )
        data = calculate_indicators(frame, "1d")
        status = build_status(data, ScanConfig(ticker="T"), "T")
        names = lambda detail: {panel["name"] for panel in _report_panels(data, status, PAGE_WIDTH_INCHES - 1.0, detail)}
        self.assertIn("Katmanlı Teknik Yorum • Kanıt • Karşı Kanıt • Teyit", names("tam"))
        self.assertNotIn("Katmanlı Teknik Yorum • Kanıt • Karşı Kanıt • Teyit", names("kompakt"))
        self.assertIn("Son 12 Teyitli Olay", names("dengeli"))
