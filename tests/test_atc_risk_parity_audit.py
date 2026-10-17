"""Regression tests for risk-model boundary conditions.

These are mathematical invariants, not proof of live-feed Pine parity.
"""
import unittest

from scripts.atc_risk_parity_audit import diagnose
from market_intelligence.scanning.trade_plan import PINE_A_I


def bars(count=80, price=30.0, low=29.0, high=31.0):
    return [{"open": price, "high": high, "low": low, "close": price}
            for _ in range(count)]


class RiskParityAuditTests(unittest.TestCase):
    def test_generic_short_three_r_below_zero_is_reported_not_clamped(self):
        data = bars()
        data[-7:] = bars(7, price=30, low=29, high=44)
        result = diagnose(data, "rule.15", "bearish")
        self.assertEqual(result["status"], "invalid_price")
        self.assertLessEqual(result["tp3"], 0)
        self.assertIn("tp3", result["invalid_fields"])
        self.assertGreater(result["stop"], result["entry"])

    def test_generic_normal_short_is_valid(self):
        result = diagnose(bars(), "rule.15", "bearish")
        self.assertEqual(result["status"], "valid")
        self.assertLess(result["tp3"], result["tp2"])
        self.assertLess(result["tp2"], result["tp1"])

    def test_pine_ai_parameter_sets(self):
        for scanner in PINE_A_I:
            with self.subTest(scanner=scanner):
                result = diagnose(bars(), scanner, "bullish")
                self.assertEqual(result["status"], "valid")
                self.assertLess(result["stop"], result["entry"])

    def test_pine_ai_long_stop_below_zero_is_reported(self):
        data = bars(price=10, low=9, high=11)
        data[-1]["high"] = 1200  # anomalous final-bar range inflates ATR
        result = diagnose(data, "signal.smi_macd_positive", "bullish")
        self.assertEqual(result["status"], "invalid_price")
        self.assertIn("stop", result["invalid_fields"])

    def test_invalid_ohlc_is_rejected(self):
        data = bars()
        data[2]["low"] = -1
        with self.assertRaises(ValueError):
            diagnose(data, "rule.15", "bearish")


if __name__ == "__main__":
    unittest.main()
