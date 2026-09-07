import unittest

import numpy as np
import pandas as pd

from src.setup_recognition import (
    duration_context,
    evidence_weight,
    participation_reading,
    recognize_setup,
    reconcile,
    regime_family,
)


def frame(bars: int = 120) -> pd.DataFrame:
    index = pd.bdate_range("2025-01-01", periods=bars)
    close = np.linspace(100, 110, bars)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(bars, 1_000_000.0),
            "ATR": np.full(bars, 2.0),
            "BB_WIDTH_RANK": np.full(bars, 50.0),
            "ADX": np.full(bars, 25.0),
            "EMA_21": close * 0.99,
        },
        index=index,
    )


def semantic(**overrides):
    base = {
        "trend_quality": {"tone": "neutral"},
        "momentum_character": {"tone": "neutral", "active_divergences": [], "rsi": {"value": 50.0}},
        "participation": {"tone": "neutral", "rvol_1": 1.0, "state": "Normal", "summary": "—", "low_progress_high_volume": False},
        "price_action": {"state": "Dengeli bar"},
        "level_confluence": {"clusters": []},
    }
    base.update(overrides)
    return base


class DurationTests(unittest.TestCase):
    def test_squeeze_streak_counts_only_consecutive_bars(self) -> None:
        data = frame()
        data.loc[data.index[-6:], "BB_WIDTH_RANK"] = 10.0
        data.loc[data.index[-7], "BB_WIDTH_RANK"] = 60.0
        result = duration_context(data, {"val": 95.0, "vah": 115.0}, {})
        self.assertEqual(result["squeeze_bars"], 6)

    def test_ema21_streak_reported_on_correct_side(self) -> None:
        data = frame()
        result = duration_context(data, {"val": 95.0, "vah": 115.0}, {})
        self.assertGreater(result["above_ema21_bars"], 5)
        self.assertEqual(result["below_ema21_bars"], 0)


class SetupTests(unittest.TestCase):
    def test_failed_breakdown_overrides_bearish_structure(self) -> None:
        data = frame()
        data.loc[data.index[-2], "Low"] = 90.0
        data.loc[data.index[-1], "Close"] = 109.0
        context = {
            "regime": {"state": "Geçiş / karma piyasa", "adx": 25.0},
            "structure": {"state": "LH / LL", "tone": "negative", "low": 95.0, "high": 120.0},
            "profile": {"val": 100.0, "vah": 115.0},
        }
        duration = duration_context(data, context["profile"], context["structure"])
        setup = recognize_setup(data, context, semantic(), duration)
        self.assertIn("reddedilme", setup["name"])
        self.assertEqual(setup["bias"], "iki yönlü")
        self.assertTrue(setup["reasons"])

    def test_squeeze_setup_reports_two_sided_bias(self) -> None:
        data = frame()
        data.loc[data.index[-10:], "BB_WIDTH_RANK"] = 8.0
        data.loc[data.index[-10:], "ADX"] = 14.0
        context = {
            "regime": {"state": "Dengeli / sıkışan piyasa", "adx": 14.0},
            "structure": {"state": "LH / LL", "tone": "negative", "low": 95.0, "high": 120.0},
            "profile": {"val": 95.0, "vah": 120.0},
        }
        duration = duration_context(data, context["profile"], context["structure"])
        setup = recognize_setup(data, context, semantic(), duration)
        self.assertEqual(setup["name"], "Sıkışma / karar bölgesi")
        self.assertEqual(setup["bias"], "iki yönlü")

    def test_trend_continuation_requires_alignment_and_directionality(self) -> None:
        data = frame()
        context = {
            "regime": {"state": "Trend / yönlü piyasa", "adx": 28.0},
            "structure": {"state": "HH / HL", "tone": "positive", "low": 95.0, "high": 120.0},
            "profile": {"val": 95.0, "vah": 120.0},
        }
        duration = duration_context(data, context["profile"], context["structure"])
        setup = recognize_setup(data, context, semantic(trend_quality={"tone": "positive"}), duration)
        self.assertEqual(setup["name"], "Trend devamı")
        self.assertEqual(setup["bias"], "yukarı")


class WeightingTests(unittest.TestCase):
    def test_regime_family_classification(self) -> None:
        self.assertEqual(regime_family("Dengeli / sıkışan piyasa"), "squeeze")
        self.assertEqual(regime_family("Trend / yönlü piyasa"), "trend")
        self.assertEqual(regime_family("Geçiş / karma piyasa"), "transition")

    def test_momentum_weighted_lower_in_squeeze_than_trend(self) -> None:
        squeeze = evidence_weight("Dengeli / sıkışan piyasa", "Momentum")
        trend = evidence_weight("Trend / yönlü piyasa", "Momentum")
        self.assertLess(squeeze, trend)
        self.assertGreater(evidence_weight("Dengeli / sıkışan piyasa", "Konum"), evidence_weight("Trend / yönlü piyasa", "Konum"))

    def test_low_rvol_is_expected_behaviour_inside_squeeze(self) -> None:
        participation = {"rvol_1": 0.56, "state": "Düşük katılım", "tone": "warning", "summary": "—"}
        squeeze = participation_reading(participation, "Dengeli / sıkışan piyasa", {"squeeze_bars": 12})
        trending = participation_reading(participation, "Trend / yönlü piyasa", {"squeeze_bars": 0})
        self.assertEqual(squeeze["tone"], "neutral")
        self.assertIn("beklenen davranış", squeeze["meaning"])
        self.assertEqual(trending["tone"], "warning")

    def test_setup_name_alone_can_trigger_squeeze_reading(self) -> None:
        participation = {"rvol_1": 0.6, "state": "Düşük katılım", "tone": "warning", "summary": "—"}
        result = participation_reading(participation, "Geçiş / karma piyasa", {"squeeze_bars": 0}, {"name": "Sıkışma / karar bölgesi"})
        self.assertEqual(result["tone"], "neutral")


class ReconcileTests(unittest.TestCase):
    def test_two_sided_setup_reports_both_directions(self) -> None:
        text = reconcile(
            {"name": "Sıkışma / karar bölgesi", "bias": "iki yönlü"},
            [{"family": "Yapı", "state": "HH / HL", "tone": "positive"}],
            [{"family": "Momentum", "state": "Negatif", "tone": "negative"}],
        )
        self.assertIn("yukarı tarafta yapı", text)
        self.assertIn("aşağı tarafta momentum", text)

    def test_directional_setup_names_strongest_counter_evidence(self) -> None:
        text = reconcile(
            {"name": "Trend devamı", "bias": "yukarı"},
            [{"family": "Trend", "state": "Bullish", "tone": "positive"}],
            [{"family": "Katılım", "state": "Düşük katılım", "tone": "negative"}],
        )
        self.assertIn("katılım", text.casefold())
        self.assertIn("çelişki", text.casefold())


if __name__ == "__main__":
    unittest.main()
