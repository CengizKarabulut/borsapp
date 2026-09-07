import unittest

import numpy as np
import pandas as pd

from src.market_context import (
    anchored_vwaps,
    approximate_volume_profile,
    build_market_context,
    market_structure,
    normalized_gap_state,
    profile_context,
    recent_events,
    rolling_volume_profile_levels,
)
from src.stock_dashboard import MA_PERIODS, calculate_indicators


def contextual_prices(rows: int = 520) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="B", tz="Europe/Istanbul")
    trend = np.linspace(80.0, 150.0, rows)
    wave = np.sin(np.arange(rows) / 7.0) * 4.0
    close = trend + wave
    return pd.DataFrame(
        {
            "Open": close - np.cos(np.arange(rows) / 5.0),
            "High": close + 2.2,
            "Low": close - 2.0,
            "Close": close,
            "Volume": 1_000_000 + (np.arange(rows) % 20) * 75_000,
        },
        index=index,
    )


class MarketContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = calculate_indicators(contextual_prices())

    def test_volume_profile_levels_are_ordered(self) -> None:
        profile = approximate_volume_profile(self.data, lookback=100)
        self.assertLessEqual(profile["val"], profile["poc"])
        self.assertLessEqual(profile["poc"], profile["vah"])
        self.assertGreater(profile["width_pct"], 0)

    def test_manual_anchor_rejects_dates_outside_downloaded_history(self) -> None:
        with self.assertRaisesRegex(ValueError, "verinin başlangıcından"):
            anchored_vwaps(self.data, "2020-01-01")
        with self.assertRaisesRegex(ValueError, "son mum tarihinden"):
            anchored_vwaps(self.data, "2030-01-01")
        with self.assertRaisesRegex(ValueError, "Geçersiz AVWAP anchor"):
            anchored_vwaps(self.data, "NaT")

    def test_manual_anchor_accepts_first_candle_calendar_date(self) -> None:
        result = anchored_vwaps(self.data, str(self.data.index[0].date()))
        self.assertTrue(np.isfinite(result["manual"]))

    def test_rolling_profile_has_no_future_data_dependency(self) -> None:
        lookback = 100
        historical_position = 250
        profiles = rolling_volume_profile_levels(self.data, lookback=lookback)
        timestamp = self.data.index[historical_position]
        expected = approximate_volume_profile(self.data.iloc[: historical_position + 1], lookback=lookback)
        self.assertAlmostEqual(profiles.loc[timestamp, "poc"], expected["poc"])
        self.assertAlmostEqual(profiles.loc[timestamp, "vah"], expected["vah"])
        self.assertAlmostEqual(profiles.loc[timestamp, "val"], expected["val"])

    def test_profile_reports_current_and_developing_acceptance(self) -> None:
        profile = profile_context(self.data)
        self.assertIn("current_profile_acceptance", profile)
        self.assertIn("developing_acceptance", profile)
        self.assertTrue(np.isfinite(profile["poc_migration_threshold"]))
        self.assertTrue(np.isfinite(profile["poc_migration_bins"]))

    def test_current_bar_cross_is_live_only_when_session_bar_is_live(self) -> None:
        data = self.data.copy()
        data.loc[data.index[-2], ["RSI", "RSI_MA"]] = [40.0, 50.0]
        data.loc[data.index[-1], ["RSI", "RSI_MA"]] = [60.0, 50.0]
        structure = market_structure(data)
        profile = profile_context(data)
        live_events = recent_events(data, structure, profile, limit=100, bar_state={"is_live": True})
        confirmed_events = recent_events(data, structure, profile, limit=100, bar_state={"is_live": False})
        live_rsi = next(item for item in live_events if item["event"] == "RSI ↑ MA" and item["age"] == 0)
        confirmed_rsi = next(item for item in confirmed_events if item["event"] == "RSI ↑ MA" and item["age"] == 0)
        self.assertEqual(live_rsi["state"], "CANLI")
        self.assertEqual(confirmed_rsi["state"], "TEYİTLİ")

    def test_market_structure_uses_confirmed_pivots(self) -> None:
        structure = market_structure(self.data)
        self.assertTrue(structure["confirmed"])
        self.assertIn(structure["state"], {"HH / HL", "HH / LL", "LH / HL", "LH / LL"})
        self.assertLess(pd.Timestamp(structure["high_time"]), self.data.index[-1])
        self.assertLess(pd.Timestamp(structure["low_time"]), self.data.index[-1])

    def test_normalized_gap_distinguishes_near_cross(self) -> None:
        main = pd.Series([5.0] * 50 + [1.0, 0.2, -0.05])
        signal = pd.Series([0.0] * len(main))
        self.assertEqual(normalized_gap_state(main, signal), "↑ Kesişime yakın")

    def test_context_contains_all_families(self) -> None:
        context = build_market_context(self.data, MA_PERIODS, "2025-01-02")
        family_names = [row[0] for row in context["families"]]
        self.assertEqual(
            family_names,
            ["KURULUM", "REJİM", "YAPI", "KONUM", "TREND", "MOMENTUM", "KATILIM", "VOLATİLİTE"],
        )
        self.assertGreaterEqual(len(context["events"]), 1)
        self.assertIn("gerçek footprint delta değildir", context["order_flow_proxy"]["method"])
        self.assertEqual(set(context["ma_structure"]["groups"]), {"Çok kısa", "Kısa", "Orta", "Uzun"})
        self.assertIn(context["regime"]["persistence_bars"], {2})
        self.assertEqual(
            set(context["divergences"]["indicators"]),
            {"RSI", "MACD", "SMI", "CCI", "Fisher", "OBV", "CMF", "Momentum"},
        )
        self.assertEqual(context["divergences"]["settings"]["lookback_right"], 5)
        self.assertEqual(context["divergences"]["settings"]["active_max_age"], 5)


if __name__ == "__main__":
    unittest.main()
