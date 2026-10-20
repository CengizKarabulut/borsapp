from __future__ import annotations

import json
import math
import unittest
from decimal import Decimal

from scripts.atc_pivot_ladder import LEVEL_FIELDS, METHOD, traditional_pivot_ladder


class TraditionalPivotLadderTests(unittest.TestCase):
    def test_independent_symmetric_three_pair_fixture(self):
        result = traditional_pivot_ladder(110, 90, 100)
        self.assertEqual(result["method"], METHOD)
        self.assertEqual(result["status"], "ready")
        self.assertEqual({key: result[key] for key in LEVEL_FIELDS}, {
            "P": 100.0, "S1": 90.0, "S2": 80.0, "S3": 70.0,
            "R1": 110.0, "R2": 120.0, "R3": 130.0,
        })
        self.assertEqual(result["invalid_fields"], [])
        self.assertIsNone(result["reason"])

    def test_asymmetric_fixture_uses_traditional_not_classic_third_level(self):
        # Decimal arithmetic provides independent expectations rather than
        # reusing the helper's floating-point calculation path.
        high, low, close = Decimal("113.7"), Decimal("97.2"), Decimal("109.4")
        pivot = (high + low + close) / 3
        expected = {
            "P": pivot, "S1": 2 * pivot - high,
            "S2": pivot - (high - low), "S3": 2 * pivot - (2 * high - low),
            "R1": 2 * pivot - low, "R2": pivot + (high - low),
            "R3": 2 * pivot + (high - 2 * low),
        }
        result = traditional_pivot_ladder(float(high), float(low), float(close))
        for field, value in expected.items():
            self.assertAlmostEqual(result[field], float(value), places=12)
        self.assertNotAlmostEqual(result["R3"], float(pivot + 2 * (high - low)))
        self.assertNotAlmostEqual(result["S3"], float(pivot - 2 * (high - low)))

    def test_flat_session_keeps_coincident_levels_without_fake_distances(self):
        for price in (1.1, 100, 1e308):
            with self.subTest(price=price):
                result = traditional_pivot_ladder(price, price, price)
                self.assertEqual(result["status"], "flat_session_coincident_levels")
                self.assertEqual({result[key] for key in LEVEL_FIELDS}, {float(price)})
                self.assertEqual(result["invalid_fields"], [])
                self.assertIn("coincide", result["reason"])

    def test_extreme_range_does_not_turn_negative_supports_into_prices(self):
        result = traditional_pivot_ladder(100, 1, 1)
        self.assertEqual(result["status"], "partial_nonpositive_levels")
        self.assertEqual(result["invalid_fields"], ["S1", "S2", "S3"])
        for key in ("S1", "S2", "S3"):
            self.assertIsNone(result[key])
        self.assertEqual(result["P"], 34)
        self.assertEqual(result["R1"], 67)
        self.assertEqual(result["R2"], 133)
        self.assertEqual(result["R3"], 166)
        json.dumps(result, allow_nan=False)

    def test_exact_zero_level_is_unavailable(self):
        result = traditional_pivot_ladder(4, 1, 1)
        self.assertIsNone(result["S1"])
        self.assertIn("S1", result["invalid_fields"])

    def test_rejects_bad_input_values_in_each_position(self):
        invalid_values = (None, "100", True, False, float("nan"), float("inf"),
                          float("-inf"), 0, -1, 10 ** 400, Decimal("100"), complex(1, 0))
        for value in invalid_values:
            for index, field in enumerate(("high", "low", "close")):
                with self.subTest(value=repr(value), field=field):
                    args = [110, 90, 100]
                    args[index] = value
                    result = traditional_pivot_ladder(*args)
                    self.assertEqual(result["status"], "unavailable_invalid_ohlc")
                    self.assertIn(field, result["invalid_fields"])
                    self.assertTrue(all(result[key] is None for key in LEVEL_FIELDS))
                    json.dumps(result, allow_nan=False)

    def test_rejects_impossible_high_low_close_geometry(self):
        for args in ((90, 110, 100), (110, 90, 111), (110, 90, 89), (100, 100, 99)):
            with self.subTest(args=args):
                result = traditional_pivot_ladder(*args)
                self.assertEqual(result["status"], "unavailable_invalid_ohlc")
                self.assertEqual(result["reason"], "high_low_close_geometry_invalid")
                self.assertTrue(all(result[key] is None for key in LEVEL_FIELDS))

    def test_valid_close_can_equal_either_session_extreme(self):
        for close in (90, 110):
            result = traditional_pivot_ladder(110, 90, close)
            self.assertEqual(result["status"], "ready")

    def test_overflow_output_is_serializable_and_never_reported_as_infinity(self):
        result = traditional_pivot_ladder(1.7e308, 1e308, 1.7e308)
        self.assertEqual(result["status"], "partial_nonpositive_levels")
        self.assertIn("R3", result["invalid_fields"])
        for key in LEVEL_FIELDS:
            value = result[key]
            self.assertTrue(value is None or math.isfinite(value) and value > 0)
        json.dumps(result, allow_nan=False)

    def test_large_finite_inputs_avoid_unnecessary_sum_overflow(self):
        result = traditional_pivot_ladder(1.7e308, 1.6e308, 1.65e308)
        self.assertTrue(math.isfinite(result["P"]))
        self.assertAlmostEqual(result["P"] / 1e308, 1.65)


if __name__ == "__main__":
    unittest.main()
