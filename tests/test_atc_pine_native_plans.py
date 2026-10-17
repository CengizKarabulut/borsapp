from __future__ import annotations

import unittest
from dataclasses import replace

from market_intelligence.core.enums import PriceBasis
from market_intelligence.scanning.trade_plan import PINE_A_I, build_pine_a_i_plan
from tests.test_trade_plan import frame


class PineSpecializedPlanTests(unittest.TestCase):
    def test_all_nine_pine_codes_have_exact_native_spec(self):
        self.assertEqual(len(PINE_A_I), 9)
        for name, spec in PINE_A_I.items():
            with self.subTest(name=name):
                plan = build_pine_a_i_plan(frame(), name, "bullish")
                self.assertEqual(plan["status"], "reference")
                entry = plan["scenarios"][0]["entry"]
                stop = plan["scenarios"][0]["stop"]
                self.assertLess(stop, entry)
                risk = entry - stop
                for key, ratio in zip(("tp1", "tp2", "tp3"), spec[6:], strict=True):
                    self.assertAlmostEqual(plan["scenarios"][0][key], entry + risk * ratio)

    def test_flat_history_gives_pine_a_and_b_exact_levels(self):
        a = build_pine_a_i_plan(frame(), "signal.macd_positive_cross", "bullish")
        pa = a["scenarios"][0]
        self.assertAlmostEqual(pa["atr14"], 4.0)
        self.assertAlmostEqual(pa["entry"], 100)
        self.assertAlmostEqual(pa["stop"], 97)
        self.assertAlmostEqual(pa["tp1"], 103)
        self.assertAlmostEqual(pa["tp2"], 105.4)
        self.assertAlmostEqual(pa["tp3"], 108.4)
        b = build_pine_a_i_plan(frame(), "signal.smi_macd_positive", "bullish")
        pb = b["scenarios"][0]
        self.assertAlmostEqual(pb["stop"], 97.2)
        self.assertAlmostEqual(pb["tp1"], 102.24)
        self.assertAlmostEqual(pb["tp2"], 104.2)
        self.assertAlmostEqual(pb["tp3"], 106.72)

    def test_original_pine_atr_minimum_is_not_silently_changed(self):
        # Pine f_plan itself can make Stop nonpositive when ATR minimum
        # exceeds entry. Keep the ORIGINAL model and show unavailable;
        # the presentation layer renders that stop as '-' without a floor.
        source = frame()
        bars = tuple(
            replace(bar, open=8.0, high=24.0, low=7.8, close=8.0)
            for bar in source.bars
        )
        plan = build_pine_a_i_plan(
            replace(source, bars=bars), "signal.smi_macd_early", "bullish",
        )
        self.assertEqual(plan["version"], "pine-a-i-plan-v1")
        self.assertEqual(plan["status"], "unavailable")
        self.assertEqual(plan["reason"], "invalid_stop_or_target")
        self.assertAlmostEqual(plan["display_levels"]["stop"], 8.0 - 0.75 * 16.2)
        self.assertEqual(plan["scenarios"], [])

    def test_short_partial_and_adjustment_do_not_invent_pine_long(self):
        name = "signal.ema_trend_volume"
        self.assertEqual(
            build_pine_a_i_plan(frame(), name, "bearish")["reason"],
            "native_a_i_no_short_side",
        )
        self.assertEqual(
            build_pine_a_i_plan(replace(frame(), is_partial=True), name, "bullish")["reason"],
            "partial_bar",
        )
        self.assertEqual(
            build_pine_a_i_plan(
                replace(frame(), price_basis=PriceBasis.TOTAL_RETURN_ADJUSTED),
                name, "bullish",
            )["reason"],
            "unsupported_price_basis",
        )

    def test_invalid_source_rule_cannot_receive_made_up_stop(self):
        with self.assertRaises(ValueError):
            build_pine_a_i_plan(frame(), "decision.panel_v645", "bullish")


if __name__ == "__main__":
    unittest.main()
