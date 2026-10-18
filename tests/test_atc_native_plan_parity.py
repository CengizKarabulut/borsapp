"""A-I Telegram reconstruction must use the latest Pine native packet plan."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from market_intelligence.features.atc_native import NativePacketSnapshot
from scripts.atc_saved_scan_plans import reconstruct_pine_plan
from tests.test_atc_native_packet import price_frame


class LatestPineNativePlanParityTests(unittest.TestCase):
    def test_bearish_ai_uses_native_short_not_chart_only_f_plan(self):
        frame = price_frame([100.0] * 260)
        packet = NativePacketSnapshot(
            known=(True,) * 9,
            flags=(True,) + (False,) * 8,
            long_plan=(95.0, 105.0, 110.0, 115.0),
            short_plan=(105.0, 95.0, 90.0, 85.0),
            bars=260,
            directions=(-1,) + (0,) * 8,
        )
        with patch("scripts.atc_saved_scan_plans.calculate_native_packet", return_value=packet):
            plan = reconstruct_pine_plan(frame, "signal.macd_positive_cross", "bearish")
            self.assertIsNotNone(plan)
            self.assertEqual(plan.stop, 105.0)
            self.assertEqual(plan.tp3, 85.0)
            self.assertIsNone(reconstruct_pine_plan(frame, "signal.macd_positive_cross", "bullish"))

    def test_invalid_native_short_does_not_become_invented_level(self):
        frame = price_frame([100.0] * 260)
        packet = NativePacketSnapshot(
            known=(True,) * 9,
            flags=(True,) + (False,) * 8,
            long_plan=(),
            short_plan=(),
            bars=260,
            directions=(-1,) + (0,) * 8,
        )
        with patch("scripts.atc_saved_scan_plans.calculate_native_packet", return_value=packet):
            self.assertIsNone(reconstruct_pine_plan(frame, "signal.macd_positive_cross", "bearish"))


if __name__ == "__main__":
    unittest.main()
