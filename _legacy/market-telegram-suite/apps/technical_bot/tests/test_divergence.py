import unittest

import numpy as np
import pandas as pd

from src.divergence import detect_divergences


def divergence_frame(kind: str, rows: int = 35) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=rows, freq="B")
    low = np.full(rows, 100.0)
    high = np.full(rows, 110.0)
    rsi = np.full(rows, 50.0)
    macd = np.zeros(rows)
    smi = np.zeros(rows)
    if kind == "regular_bullish":
        low[[10, 25]] = [90.0, 85.0]
        rsi[[10, 25]], macd[[10, 25]], smi[[10, 25]] = [30.0, 40.0], [-2.0, -1.0], [-40.0, -30.0]
    elif kind == "regular_bearish":
        high[[10, 25]] = [120.0, 125.0]
        rsi[[10, 25]], macd[[10, 25]], smi[[10, 25]] = [70.0, 60.0], [2.0, 1.0], [40.0, 30.0]
    elif kind == "hidden_bullish":
        low[[10, 25]] = [90.0, 95.0]
        rsi[[10, 25]], macd[[10, 25]], smi[[10, 25]] = [40.0, 30.0], [-1.0, -2.0], [-30.0, -40.0]
    elif kind == "hidden_bearish":
        high[[10, 25]] = [120.0, 115.0]
        rsi[[10, 25]], macd[[10, 25]], smi[[10, 25]] = [60.0, 70.0], [1.0, 2.0], [30.0, 40.0]
    else:
        raise ValueError(kind)
    return pd.DataFrame({"Low": low, "High": high, "RSI": rsi, "MACD": macd, "SMI": smi}, index=index)


class DivergenceTests(unittest.TestCase):
    def test_stoch_rsi_is_excluded_from_divergence_scan(self) -> None:
        result = detect_divergences(divergence_frame("regular_bullish"))
        self.assertNotIn("Stoch RSI", result["indicators"])
        self.assertIn("Stoch RSI", result["method"])

    def _assert_all(self, kind: str, state: str, relation: str, hidden: bool) -> None:
        result = detect_divergences(divergence_frame(kind))
        for name in ("RSI", "MACD", "SMI"):
            item = result["indicators"][name]
            self.assertTrue(item["detected"])
            self.assertEqual(item["state"], state)
            self.assertEqual(item["pivot_relation"], relation)
            self.assertEqual(item["hidden"], hidden)
            self.assertEqual(item["event_age"], 4)

    def test_regular_bullish(self) -> None:
        self._assert_all("regular_bullish", "Pozitif normal uyumsuzluk", "LL / HL", False)

    def test_regular_bearish(self) -> None:
        self._assert_all("regular_bearish", "Negatif normal uyumsuzluk", "HH / LH", False)

    def test_hidden_bullish(self) -> None:
        self._assert_all("hidden_bullish", "Pozitif gizli uyumsuzluk", "HL / LL", True)

    def test_hidden_bearish(self) -> None:
        self._assert_all("hidden_bearish", "Negatif gizli uyumsuzluk", "LH / HH", True)

    def test_right_lookback_delays_confirmation(self) -> None:
        full = divergence_frame("regular_bullish")
        self.assertFalse(detect_divergences(full.iloc[:30])["indicators"]["RSI"]["detected"])
        at_confirmation = detect_divergences(full.iloc[:31])["indicators"]["RSI"]
        self.assertTrue(at_confirmation["detected"])
        self.assertEqual(at_confirmation["event_age"], 0)

    def test_old_divergence_is_not_active(self) -> None:
        old = detect_divergences(divergence_frame("regular_bullish", rows=45))
        self.assertFalse(old["indicators"]["RSI"]["detected"])
        self.assertEqual(old["indicators"]["RSI"]["state"], "Son 5 barda aktif uyumsuzluk yok")
        historical = detect_divergences(divergence_frame("regular_bullish", rows=45), max_event_age=20)
        self.assertTrue(historical["indicators"]["RSI"]["detected"])
        self.assertEqual(historical["indicators"]["RSI"]["event_age"], 14)

    def test_pivots_outside_range_are_not_compared(self) -> None:
        data = divergence_frame("regular_bullish", rows=50)
        data.loc[:, ["RSI", "MACD", "SMI"]] = [50.0, 0.0, 0.0]
        data.loc[data.index[[5, 40]], "RSI"] = [30.0, 40.0]
        data.loc[data.index[[5, 40]], "Low"] = [90.0, 85.0]
        result = detect_divergences(data, left=2, right=2, range_lower=5, range_upper=30, max_event_age=20)
        self.assertFalse(result["indicators"]["RSI"]["detected"])


if __name__ == "__main__":
    unittest.main()
