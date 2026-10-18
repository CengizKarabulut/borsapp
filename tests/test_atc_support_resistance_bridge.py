from __future__ import annotations

import ast
import json
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from scripts.atc_support_resistance import (
    UPSTREAM_FUNCTION_SHA256,
    build_support_resistance,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def frame_for(lows, highs=None, closes=None, **changes):
    highs = highs or [max(110.0, value + 5) for value in lows]
    closes = closes or [100.0 for _ in lows]
    bars = tuple(SimpleNamespace(
        open_time=START + timedelta(days=index),
        close_time=START + timedelta(days=index + 1),
        open=close, low=low, high=high, close=close,
    ) for index, (low, high, close) in enumerate(zip(lows, highs, closes, strict=True)))
    values = dict(symbol_at_snapshot="TEST", source="fixture-source", timeframe="1d",
                  price_basis="split_adjusted", snapshot_id="fixture-snapshot", series_revision=2,
                  quality="complete", is_partial=False, bars=bars)
    values.update(changes)
    return SimpleNamespace(**values)


def run(frame, **options):
    return build_support_resistance(frame, as_of=START + timedelta(days=500), **options)


class SupportResistanceBridgeTests(unittest.TestCase):
    def test_matches_actual_upstream_helper_on_closed_fixture(self):
        path = Path(__file__).parents[1] / "src/market_intelligence/features/research.py"
        source = path.read_text(encoding="utf-8")
        function = next(node for node in ast.parse(source).body
                        if isinstance(node, ast.FunctionDef) and node.name == "_support_resistance")
        definition = "\n".join(source.splitlines()[function.lineno - 1:function.end_lineno]) + "\n"
        self.assertEqual(sha256(definition.encode()).hexdigest(), UPSTREAM_FUNCTION_SHA256)
        namespace = {"CanonicalFrame": object}
        exec(compile("from __future__ import annotations\n" + definition, str(path), "exec"), namespace)
        lows = [95, 94, 93, 80, 92, 93, 94, 95, 85, 94, 95, 96, 97, 88, 97, 98, 99]
        highs = [105, 106, 107, 130, 108, 107, 106, 105, 125, 106, 105, 104, 103, 120, 103, 102, 101]
        frame = frame_for(lows, highs)
        expected_supports, expected_resistances = namespace["_support_resistance"](frame)
        result = run(frame)
        self.assertEqual(tuple(row["price"] for row in result["supports"]), expected_supports)
        self.assertEqual(tuple(row["price"] for row in result["resistances"]), expected_resistances)
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["algorithm"]["changes_stop_tp"])

    def test_three_right_closed_bars_required_to_confirm_extreme(self):
        frame = frame_for([95, 94, 93, 80, 92, 93, 94])
        early = build_support_resistance(frame, as_of=frame.bars[-2].close_time)
        result = run(frame)
        self.assertEqual(early["status"], "insufficient_history")
        self.assertEqual(early["supports"], [])
        self.assertEqual(result["supports"][0]["price"], 80)
        self.assertEqual(result["supports"][0]["confirmed_at"], frame.bars[-1].close_time.isoformat())

    def test_future_and_open_extremes_cannot_rewrite_closed_levels(self):
        frame = frame_for([95, 94, 93, 80, 92, 93, 94, 95, 96])
        cutoff = frame.bars[6].close_time
        prefix = deepcopy(frame)
        prefix.bars = prefix.bars[:7]
        expected = build_support_resistance(prefix, as_of=cutoff)
        future = deepcopy(frame)
        future.bars[7].low = 0.01
        future.bars[7].high = 10000
        actual = build_support_resistance(future, as_of=cutoff)
        for key in ("supports", "resistances", "reference_price", "last_closed_bar_time"):
            self.assertEqual(actual[key], expected[key])
        self.assertEqual(actual["excluded_open_or_future_bars"], 2)
        stale_partial = deepcopy(frame)
        stale_partial.is_partial = True
        stale_partial.quality = "preliminary"
        last = stale_partial.bars[-1]
        last.low, last.high, last.close = 0.01, 10000, 9000
        actual = run(stale_partial)
        self.assertEqual(actual["closed_reference_price"], 100)
        self.assertEqual(actual["excluded_open_or_future_bars"], 1)

    def test_equal_reference_price_is_not_a_resistance(self):
        frame = frame_for([90] * 7, [100] * 7)
        result = run(frame)
        self.assertEqual(result["resistances"], [])
        self.assertEqual([row["price"] for row in result["supports"]], [90])

    def test_positive_live_reference_only_reclassifies_confirmed_levels(self):
        frame = frame_for([95, 94, 93, 80, 92, 93, 94], [105, 106, 107, 120, 108, 107, 106])
        result = run(frame, reference_price=125)
        self.assertEqual(result["reference_basis"], "supplied_current_price")
        self.assertEqual(result["closed_reference_price"], 100)
        self.assertEqual(result["reference_price"], 125)
        self.assertEqual(result["resistances"], [])
        self.assertEqual([row["price"] for row in result["supports"]], [80])

    def test_short_history_is_distinct_from_no_pivots(self):
        insufficient = run(frame_for([90] * 6))
        self.assertEqual(insufficient["status"], "insufficient_history")
        self.assertEqual(insufficient["minimum_required_bars"], 7)
        monotone = frame_for(list(range(80, 90)), list(range(110, 120)))
        enough = run(monotone)
        self.assertEqual(enough["status"], "ready")
        self.assertEqual(enough["supports"], [])
        self.assertEqual(enough["resistances"], [])
        self.assertTrue(enough["history_is_shorter_than_requested"])

    def test_source_adjustment_asof_and_confirmation_metadata_is_json_ready(self):
        result = run(frame_for([95, 94, 93, 80, 92, 93, 94]))
        self.assertEqual(result["source"], "fixture-source")
        self.assertEqual(result["price_basis"], "split_adjusted")
        self.assertEqual(result["timeframe"], "1d")
        self.assertEqual(result["snapshot_id"], "fixture-snapshot")
        self.assertEqual(result["series_revision"], 2)
        self.assertEqual(result["lookback_used"], 7)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertFalse(result["algorithm"]["volume_used"])
        for row in result["supports"]:
            self.assertLess(row["price"], result["reference_price"])
            self.assertLessEqual(datetime.fromisoformat(row["confirmed_at"]),
                                 datetime.fromisoformat(result["as_of"]))

    def test_lookback_excludes_old_confirmed_extremes(self):
        lows = [95, 94, 93, 70, 92, 93, 94, 95, 94, 93, 85, 92, 93, 94]
        frame = frame_for(lows)
        self.assertIn(70, [row["price"] for row in run(frame)["supports"]])
        result = run(frame, lookback=7)
        self.assertEqual([row["price"] for row in result["supports"]], [85])
        self.assertEqual(result["lookback_used"], 7)

    def test_nearby_levels_are_deduplicated_and_limited(self):
        lows = [95] * 35
        for index, level in ((3, 85), (10, 85.5), (17, 80), (24, 75), (31, 70)):
            lows[index] = level
        result = run(frame_for(lows))
        self.assertEqual([row["price"] for row in result["supports"]], [85.5, 80, 75])

    def test_data_quality_does_not_fabricate_levels(self):
        result = run(frame_for([95, 94, 93, 80, 92, 93, 94], quality="incomplete"))
        self.assertEqual(result["status"], "unavailable_data_quality")
        self.assertEqual(result["supports"], [])
        result = run(frame_for([95] * 7, quality="preliminary", is_partial=False))
        self.assertEqual(result["status"], "unavailable_data_quality")

    def test_invalid_time_order_metadata_and_ohlc_fail_explicitly(self):
        frame = frame_for([95] * 7)
        cases = []
        naive = deepcopy(frame)
        naive.bars[0].close_time = datetime(2026, 1, 2)
        cases.append(naive)
        duplicate = deepcopy(frame)
        duplicate.bars[1].close_time = duplicate.bars[0].close_time
        cases.append(duplicate)
        bad_price = deepcopy(frame)
        bad_price.bars[0].low = -1
        cases.append(bad_price)
        nan = deepcopy(frame)
        nan.bars[0].high = float("nan")
        cases.append(nan)
        no_basis = deepcopy(frame)
        no_basis.price_basis = ""
        cases.append(no_basis)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                run(value)
        with self.assertRaises(ValueError):
            build_support_resistance(frame, as_of=datetime(2026, 1, 10))

    def test_invalid_inputs_and_mutation_are_not_silent(self):
        frame = frame_for([95, 94, 93, 80, 92, 93, 94])
        original = deepcopy(frame)
        for price in (-1, 0, float("inf"), True):
            with self.subTest(price=price), self.assertRaises(ValueError):
                run(frame, reference_price=price)
        for lookback in (0, 6, True, 12.5):
            with self.subTest(lookback=lookback), self.assertRaises(ValueError):
                run(frame, lookback=lookback)
        run(frame)
        self.assertEqual(frame, original)


if __name__ == "__main__":
    unittest.main()
