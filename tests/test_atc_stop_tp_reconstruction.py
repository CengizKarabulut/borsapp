from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from scripts.atc_saved_scan_plans import (
    _exact_frame_from_saved_bars,
    reconstruct_pine_plan,
)

IST = ZoneInfo("Europe/Istanbul")
END = datetime(2026, 10, 16, 18, 0, tzinfo=IST)


def sample_frame():
    bars = tuple(
        CanonicalBar(
            open_time=END - timedelta(minutes=30 * (30 - i)),
            close_time=END - timedelta(minutes=30 * (29 - i)),
            open=100.0, high=102.0, low=98.0, close=100.0, volume=1000,
        ) for i in range(30)
    )
    return CanonicalFrame(
        instrument_id="id-A", symbol_at_snapshot="ASELS", market="BIST",
        timeframe=Timeframe.M30, snapshot_id="exact-snapshot",
        series_revision=3, price_basis=PriceBasis.RAW, source="actual-vendor",
        bars=bars,
    )


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, statement, params):
        self.queries.append((statement, params))

    def fetchall(self):
        return self.rows


class StopTpSameSnapshotTests(unittest.TestCase):
    def test_b_long_snapshot_uses_actual_native_alarm_risk_not_chart_overlay(self):
        frame = sample_frame()
        plan = reconstruct_pine_plan(
            frame, "signal.smi_macd_positive", "bullish",
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.entry, 100.0)
        self.assertAlmostEqual(plan.stop, 97.0)
        self.assertAlmostEqual(plan.tp1, 103.0)
        self.assertAlmostEqual(plan.tp2, 106.0)
        self.assertAlmostEqual(plan.tp3, 109.0)

    def test_generic_thirteen_short_targets_decrease(self):
        frame = sample_frame()
        plan = reconstruct_pine_plan(
            frame, "technical.failed_breakout", "bearish",
        )
        self.assertIsNotNone(plan)
        self.assertTrue(plan.tp3 < plan.tp2 < plan.tp1 < plan.entry < plan.stop)

    def test_17_18_no_plan_but_a_i_short_uses_native_source(self):
        frame = sample_frame()
        for rule in ("decision.panel_v645", "ma.near_zone"):
            self.assertIsNone(reconstruct_pine_plan(frame, rule, "bullish"))
        short = reconstruct_pine_plan(
            frame, "signal.smi_macd_positive", "bearish",
        )
        self.assertIsNotNone(short)
        self.assertAlmostEqual(short.stop, 103.0)
        self.assertTrue(short.tp3 < short.tp2 < short.tp1 < short.entry)
        self.assertIsNone(reconstruct_pine_plan(
            frame, "signal.smi_macd_positive", "neutral",
        ))

    def test_exact_stored_ohlcv_source_revision_window(self):
        frame = sample_frame()
        rows = [
            (b.open_time, b.close_time, b.open, b.high, b.low, b.close, b.volume)
            for b in frame.bars
        ]
        identity = (
            "eval-A", "id-A", "signal.smi_macd_positive",
            "exact-snapshot", "actual-vendor", "raw", 3,
            frame.bars[0].open_time, END, 30, "30m", END,
        )
        cursor = FakeCursor(rows)
        restored = _exact_frame_from_saved_bars(cursor, identity)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.bars, frame.bars)
        sql, params = cursor.queries[0]
        self.assertIn("source = %s", sql)
        self.assertIn("price_basis = %s", sql)
        self.assertIn("series_revision = %s", sql)
        self.assertEqual(params[2:5], ("actual-vendor", "raw", 3))
        # Historical bar omission invalidates the reconstruction.
        broken = FakeCursor(rows[:-1])
        self.assertIsNone(_exact_frame_from_saved_bars(broken, identity))
        self.assertIsNone(_exact_frame_from_saved_bars(
            FakeCursor(rows), (*identity[:9], 31, *identity[10:]),
        ))

    def test_total_return_adjusted_snapshot_fails_closed(self):
        frame = sample_frame()
        frame = replace(frame, price_basis=PriceBasis.TOTAL_RETURN_ADJUSTED)
        self.assertIsNone(reconstruct_pine_plan(
            frame, "signal.smi_macd_positive", "bullish",
        ))


if __name__ == "__main__":
    unittest.main()
