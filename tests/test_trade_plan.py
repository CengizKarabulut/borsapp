import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.trade_plan import build_trade_plan


def frame():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    bars = tuple(
        CanonicalBar(
            start + timedelta(hours=i), start + timedelta(hours=i + 1), 100, 102, 98, 100, 1000
        )
        for i in range(30)
    )
    return CanonicalFrame(
        "id", "TEST", "BIST", Timeframe.H1, "snapshot", 1, PriceBasis.RAW, "fixture", bars
    )


class TradePlanTests(unittest.TestCase):
    def test_long_risk_and_targets(self):
        p = build_trade_plan(frame(), "bullish")["scenarios"][0]
        self.assertEqual(p["atr14"], 4)
        self.assertAlmostEqual(p["stop"], 97)
        self.assertEqual([p[k] for k in ("entry", "tp1", "tp2", "tp3")], [100, 103, 106, 109])

    def test_short_mirrors_direction(self):
        p = build_trade_plan(frame(), "bearish")["scenarios"][0]
        self.assertEqual(
            [p[k] for k in ("stop", "entry", "tp1", "tp2", "tp3")], [103, 100, 97, 94, 91]
        )

    def test_neutral_is_conditional_not_buy(self):
        p = build_trade_plan(frame(), "neutral")
        self.assertEqual(p["status"], "conditional")
        self.assertEqual(len(p["scenarios"]), 2)

    def test_insufficient_and_partial_do_not_invent_volatility(self):
        self.assertEqual(
            build_trade_plan(replace(frame(), bars=frame().bars[:5]), "bullish")["reason"],
            "insufficient_history",
        )
        self.assertEqual(
            build_trade_plan(replace(frame(), is_partial=True), "bullish")["reason"], "partial_bar"
        )

    def test_adjusted_prices_are_labeled_reference_not_orders(self):
        p = build_trade_plan(replace(frame(), price_basis=PriceBasis.SPLIT_ADJUSTED), "bullish")
        self.assertEqual(p["price_basis"], "split_adjusted")
        self.assertFalse(p["executable_order"])
        self.assertEqual(p["status"], "reference")
        p = build_trade_plan(
            replace(frame(), price_basis=PriceBasis.TOTAL_RETURN_ADJUSTED), "bullish"
        )
        self.assertEqual(p["reason"], "unsupported_price_basis")

    def test_wide_structural_stop_is_not_clamped_inward(self):
        f = frame()
        bars = list(f.bars)
        bars[-2] = replace(bars[-2], low=60)
        p = build_trade_plan(replace(f, bars=tuple(bars)), "bullish")["scenarios"][0]
        self.assertLess(p["stop"], 60)
        self.assertTrue(p["wide_stop"])

    def test_snapshot_provenance(self):
        p = build_trade_plan(frame(), "bullish")
        self.assertEqual(p["snapshot_id"], "snapshot")
        self.assertFalse(p["costs_included"])
        self.assertEqual(p["validation"], "not_backtested")
