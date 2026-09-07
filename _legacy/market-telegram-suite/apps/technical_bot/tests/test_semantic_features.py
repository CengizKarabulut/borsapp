import unittest

import numpy as np
import pandas as pd

from src.market_context import build_market_context
from src.semantic_features import (
    build_semantic_features,
    momentum_character_context,
    price_action_context,
    trend_quality_context,
)
from src.stock_dashboard import MA_PERIODS, calculate_indicators


def prices(rows: int = 430) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = pd.Series(np.linspace(80, 150, rows) + np.sin(np.arange(rows) / 8), index=index)
    return pd.DataFrame(
        {
            "Open": close - 0.4,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_500_000, rows),
        },
        index=index,
    )


class SemanticFeaturesTests(unittest.TestCase):
    def test_price_action_reports_close_location_and_patterns(self) -> None:
        data = prices(20)
        data.loc[data.index[-1], ["Open", "High", "Low", "Close"]] = [100.0, 110.0, 99.0, 109.5]
        data["ATR"] = 4.0
        result = price_action_context(data)
        self.assertEqual(result["state"], "Güçlü alıcı kapanışı")
        self.assertGreater(result["close_location_pct"], 90)

    def test_trend_quality_detects_bullish_stack_and_normalized_slopes(self) -> None:
        data = calculate_indicators(prices())
        result = trend_quality_context(data, MA_PERIODS)
        self.assertIn("bullish", result["state"].casefold())
        self.assertGreater(result["slopes_atr_5"]["21"], 0)

    def test_volume_ratio_uses_previous_completed_bars(self) -> None:
        data = prices(40)
        data["Volume"] = 100.0
        data.loc[data.index[-1], "Volume"] = 200.0
        result = calculate_indicators(data)
        self.assertAlmostEqual(result["VOLUME_MA"].iloc[-1], 100.0)
        self.assertAlmostEqual(result["VOLUME_RATIO"].iloc[-1], 2.0)

    def test_momentum_is_character_not_vote_count(self) -> None:
        data = calculate_indicators(prices())
        result = momentum_character_context(data, {"indicators": {}})
        self.assertNotIn("/4", result["summary"])
        self.assertIn("momentum", result["state"].casefold())

    def test_market_context_exposes_all_semantic_families(self) -> None:
        data = calculate_indicators(prices())
        result = build_market_context(data, MA_PERIODS)
        self.assertEqual(
            set(result["semantic"]),
            {"price_action", "trend_quality", "momentum_character", "participation", "level_confluence"},
        )
        momentum_row = next(item for item in result["families"] if item[0] == "MOMENTUM")
        self.assertNotIn("/4", momentum_row[2])

    def test_level_confluence_returns_multiple_family_clusters(self) -> None:
        data = calculate_indicators(prices())
        row = data.iloc[-1]
        level = float(row["EMA_50"])
        semantic = build_semantic_features(
            data,
            MA_PERIODS,
            {"pdh": level + 0.01, "pdl": level - 10},
            {"poc": level + 0.02, "vah": level + 5, "val": level - 5},
            {"manual": level + 0.03, "month": level + 8, "quarter": level + 9, "year": level + 10},
            {"high": level + 12, "low": level - 12},
            {"indicators": {}},
        )
        clusters = semantic["level_confluence"]["clusters"]
        self.assertTrue(any(len(item["families"]) >= 2 for item in clusters))


if __name__ == "__main__":
    unittest.main()


class ParticipationDirectionTests(unittest.TestCase):
    """Katılım etiketi son barın yönüyle çelişmemeli."""

    def _participation(self, last_change: float):
        import numpy as np

        from src.divergence import detect_divergences
        from src.market_context import market_structure, profile_context
        from src.semantic_features import build_semantic_features
        from src.stock_dashboard import MA_PERIODS, calculate_indicators

        rng = np.random.default_rng(3)
        bars = 300
        index = pd.bdate_range("2025-01-01", periods=bars)
        close = 30 * np.exp(np.cumsum(rng.normal(0, 0.012, bars)))
        close[-6:-1] = close[-7] * np.array([1.02, 1.04, 1.07, 1.09, 1.12])
        close[-1] = close[-2] * (1 + last_change)
        volume = rng.lognormal(14, 0.3, bars)
        volume[-1] *= 2.2
        frame = pd.DataFrame(
            {"Open": close, "High": close * 1.02, "Low": close * 0.98, "Close": close, "Volume": volume},
            index=index,
        )
        data = calculate_indicators(frame, "1d")
        semantic = build_semantic_features(
            data, MA_PERIODS, {}, profile_context(data), {}, market_structure(data), detect_divergences(data)
        )
        return semantic["participation"]

    def test_sharp_down_bar_is_not_called_upward_participation(self) -> None:
        state = self._participation(-0.048)["state"]
        self.assertNotIn("Yükseliş yönünde", state)
        self.assertIn("çelişkili", state)

    def test_agreeing_up_bar_keeps_upward_label(self) -> None:
        self.assertEqual(self._participation(0.03)["state"], "Yükseliş yönünde güçlü katılım")

    def test_current_bar_change_is_exposed(self) -> None:
        participation = self._participation(-0.048)
        self.assertIn("price_change_1", participation)
        self.assertLess(participation["price_change_1"], 0)
