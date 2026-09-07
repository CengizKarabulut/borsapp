import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.stock_dashboard import calculate_indicators
from src.watchlist_scan import evaluate_conditions, read_watchlist


class WatchlistScanTests(unittest.TestCase):
    def test_watchlist_ignores_comments_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.txt"
            path.write_text("THYAO\n# not\nASELS # savunma\nTHYAO\n", encoding="utf-8")
            self.assertEqual(read_watchlist(path), ["THYAO", "ASELS"])

    def test_condition_requires_both_squeeze_and_rvol(self) -> None:
        rows = 500
        close = np.linspace(100, 120, rows)
        frame = pd.DataFrame(
            {
                "Open": close,
                "High": close + 1,
                "Low": close - 1,
                "Close": close,
                "Volume": np.r_[np.full(rows - 1, 1_000_000), 2_000_000],
            },
            index=pd.date_range("2024-01-01", periods=rows, freq="B"),
        )
        data = calculate_indicators(frame)
        data.loc[data.index[-1], "BB_WIDTH_RANK"] = 10
        result = evaluate_conditions(data, {"state": "Göreceli güçleniyor"}, 20, 1.5)
        self.assertTrue(result["matched"])


if __name__ == "__main__":
    unittest.main()
