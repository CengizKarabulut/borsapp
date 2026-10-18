from __future__ import annotations

import math
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts.atc_sr_evaluation import (
    BASELINE,
    CONFIGS,
    Bar,
    Config,
    Protocol,
    _outcome,
    confirmed_levels,
    evaluate_symbol,
    summarize,
    wilder_atr,
)
from scripts.atc_support_resistance import build_support_resistance

START = datetime(2020, 1, 1, tzinfo=UTC)


def bar(index, *, opening=100.0, high=101.0, low=99.0, close=100.0):
    return Bar(START + timedelta(days=index), opening, high, low, close, 100.0)


def history(count=315):
    return [bar(index, high=105 + 3 * math.cos(index / 4),
                low=95 + 3 * math.sin(index / 5)) for index in range(count)]


class PivotEvaluationTests(unittest.TestCase):
    def test_baseline_exactly_matches_installed_context_including_provenance(self):
        for count in (252, 273, 294):
            bars = history(count)
            frame = SimpleNamespace(
                bars=tuple(SimpleNamespace(**vars(value), open_time=value.close_time - timedelta(hours=8))
                           for value in bars),
                symbol_at_snapshot="TEST", source="fixture", timeframe="1d",
                price_basis="split_adjusted", snapshot_id="fixture", series_revision=1,
                quality="complete", is_partial=False,
            )
            context = build_support_resistance(frame, as_of=bars[-1].close_time)
            actual = confirmed_levels(bars, BASELINE)
            self.assertEqual(actual["support"], context["supports"])
            self.assertEqual(actual["resistance"], context["resistances"])
            for rows in actual.values():
                for value in rows:
                    self.assertLessEqual(datetime.fromisoformat(value["confirmed_at"]), bars[-1].close_time)

    def test_future_mutation_does_not_rewrite_frozen_level_or_atr(self):
        original = history(293)
        changed = original[:252] + [replace(value, high=10000, low=0.01) for value in original[252:]]
        first = evaluate_symbol(original, "TEST")["events"][:18]
        second = evaluate_symbol(changed, "TEST")["events"][:18]
        for left, right in zip(first, second, strict=True):
            for key in ("config", "side", "level", "confirmation_time", "pivot_close_time", "atr", "distance_atr"):
                self.assertEqual(left[key], right[key])
        self.assertEqual(wilder_atr(original)[:252], wilder_atr(changed)[:252])

    def test_all_nine_configs_share_warmup_and_anchor_dates(self):
        result = evaluate_symbol(history(294), "TEST")
        self.assertEqual(result["audit"]["eligible_anchors"], 2)
        self.assertEqual(result["audit"]["purged_final_tail"], 1)
        anchors = {config.id: {event["anchor_close"] for event in result["events"]
                              if event["config"] == config.id} for config in CONFIGS}
        self.assertEqual(len(anchors), 9)
        self.assertTrue(all(value == anchors[BASELINE.id] for value in anchors.values()))
        self.assertEqual(min(anchors[BASELINE.id]), history(252)[-1].close_time.isoformat())

    def test_insufficient_ipo_history_is_not_a_failed_reaction(self):
        insufficient = evaluate_symbol(history(251), "IPO")
        self.assertTrue(insufficient["audit"]["insufficient_history"])
        self.assertEqual(insufficient["events"], [])
        tail = evaluate_symbol(history(271), "IPO")
        self.assertFalse(tail["audit"]["insufficient_history"])
        self.assertEqual(tail["audit"]["purged_final_tail"], 1)
        self.assertEqual(tail["events"], [])
        enough = evaluate_symbol(history(272), "IPO")
        self.assertEqual(enough["audit"]["eligible_anchors"], 1)

    def test_sufficient_monotone_history_without_pivots_is_no_level(self):
        bars = [bar(index, opening=100 + index, high=101 + index,
                    low=99 + index, close=100 + index) for index in range(272)]
        result = evaluate_symbol(bars, "TREND")
        self.assertEqual(result["audit"]["eligible_anchors"], 1)
        self.assertEqual({event["outcome"] for event in result["events"]}, {"no_level"})

    def test_split_boundaries_purge_complete_future_window(self):
        bars = history(315)
        protocol = Protocol(validation_start=bars[260].close_time, test_start=bars[300].close_time)
        result = evaluate_symbol(bars, "TEST", protocol=protocol)
        self.assertEqual(result["audit"]["purged_split_boundary"], 2)
        events = result["events"]
        self.assertEqual({event["split"] for event in events}, {"validation"})
        self.assertEqual({event["anchor_close"] for event in events}, {bars[272].close_time.isoformat()})

    def test_wilder_seed_and_recurrence_and_zero_atr_not_invented(self):
        bars = [bar(index, opening=10, high=11, low=9, close=10) for index in range(14)]
        bars.append(bar(14, opening=10, high=15, low=10, close=10))
        values = wilder_atr(bars)
        self.assertEqual(values[:13], [None] * 13)
        self.assertEqual(values[13], 2)
        self.assertAlmostEqual(values[14], 31 / 14)
        flat = [bar(index, opening=10, high=10, low=10, close=10) for index in range(272)]
        result = evaluate_symbol(flat, "FLAT")
        self.assertEqual(result["audit"]["atr_unavailable_anchors"], 1)
        self.assertEqual(result["events"], [])

    def test_invalid_prices_time_and_config_are_rejected(self):
        bars = history(272)
        for bad in (replace(bars[0], low=-1), replace(bars[0], close=math.inf),
                    replace(bars[0], volume=math.nan), replace(bars[0], high=90),
                    replace(bars[0], close_time=START.replace(tzinfo=None))):
            with self.assertRaises(ValueError):
                evaluate_symbol([bad] + bars[1:], "TEST")
        with self.assertRaises(ValueError):
            evaluate_symbol([bars[0], bars[0]], "TEST")
        with self.assertRaises(ValueError):
            evaluate_symbol(bars, "TEST", configs=(Config(5, 3),))
        with self.assertRaises(ValueError):
            evaluate_symbol(bars, "TEST", protocol=Protocol(commonwarmup=120))

    def test_unreconciled_history_and_future_boundaries_censor_all_configs(self):
        for index in (30, 260):
            bars = history(294)
            bars[index] = replace(bars[index], open=50, low=49, close=50)
            result = evaluate_symbol(bars, "REVIEW")
            self.assertGreater(result["audit"]["purged_unverified_continuity"], 0)
            self.assertTrue(result["audit"]["flagged_boundaries"])
            self.assertEqual(result["events"], [])


class ContactOutcomeTests(unittest.TestCase):
    def future(self):
        return [bar(index, opening=101, high=101.5, low=100.5, close=101) for index in range(20)]

    def outcome(self, bars, side="support"):
        return _outcome(bars, side, 100, 2, Protocol())

    def test_no_contact_and_contact_search_horizon(self):
        future = self.future()
        self.assertEqual(self.outcome(future)["outcome"], "no_contact")
        future[10] = bar(10, low=99.5)
        self.assertEqual(self.outcome(future)["outcome"], "no_contact")

    def test_gap_through_is_separate_even_if_same_bar_spans_target(self):
        future = self.future()
        future[0] = bar(0, opening=98, low=97, high=103)
        self.assertEqual(self.outcome(future)["outcome"], "gap_through")

    def test_touchbar_target_is_not_credited_and_touchbar_both_is_ambiguous(self):
        future = self.future()
        future[0] = bar(0, high=103, low=99.5)
        result = self.outcome(future)
        self.assertEqual(result["outcome"], "timeout")
        self.assertTrue(result["ignored_touchbar_target"])
        future[0] = bar(0, high=103, low=98)
        self.assertEqual(self.outcome(future)["outcome"], "ambiguous")
        future[0] = bar(0, high=101, low=98)
        self.assertEqual(self.outcome(future)["outcome"], "break")

    def test_first_later_barrier_wins_and_samebar_remains_ambiguous(self):
        future = self.future()
        future[0] = bar(0, low=99.5)
        future[1] = bar(1, high=103, low=100)
        future[2] = bar(2, high=101, low=98)
        self.assertEqual(self.outcome(future)["outcome"], "target")
        future[1], future[2] = replace(future[2], close_time=future[1].close_time), replace(future[1], close_time=future[2].close_time)
        self.assertEqual(self.outcome(future)["outcome"], "break")
        future[1] = bar(1, high=103, low=98)
        self.assertEqual(self.outcome(future)["outcome"], "ambiguous")

    def test_contact_on_tenth_bar_has_ten_later_bars_and_no_more(self):
        future = self.future()
        future[9] = bar(9, low=99.5)
        future[19] = bar(19, high=103, low=100)
        self.assertEqual(self.outcome(future)["outcome"], "target")
        future = self.future()
        future[0] = bar(0, low=99.5)
        future[11] = bar(11, high=103, low=100)
        self.assertEqual(self.outcome(future)["outcome"], "timeout")

    def test_support_resistance_are_exact_mirrors(self):
        future = self.future()
        future[0] = bar(0, low=99.5)
        future[1] = bar(1, high=103, low=100)
        mirrored = [replace(value, open=200 - value.open, high=200 - value.low,
                            low=200 - value.high, close=200 - value.close) for value in future]
        left, right = self.outcome(future), self.outcome(mirrored, "resistance")
        self.assertEqual(left["outcome"], right["outcome"])
        self.assertEqual(left["contact_close"], right["contact_close"])
        self.assertEqual(left["target_price"], 200 - right["target_price"])
        self.assertEqual(left["break_price"], 200 - right["break_price"])

    def test_impossible_research_barrier_is_null_not_a_negative_price(self):
        result = _outcome(self.future(), "resistance", 1, 2, Protocol())
        self.assertEqual(result["outcome"], "invalid_barrier")
        self.assertIsNone(result["target_price"])
        self.assertEqual(result["break_price"], 2)


class SummaryTests(unittest.TestCase):
    def event(self, outcome, symbol="A", distance=1):
        return {"config": BASELINE.id, "split": "test", "side": "support", "symbol": symbol,
                "outcome": outcome, "distance_atr": None if outcome == "no_level" else distance}

    def test_contact_denominator_ambiguity_bounds_and_equal_weight_symbol_macro(self):
        events = [self.event("target"), self.event("target"), self.event("ambiguous"),
                  self.event("gap_through", "B"), self.event("timeout", "B"),
                  self.event("break", "B"), self.event("break", "B"),
                  self.event("no_contact", "C"), self.event("no_level", "C")]
        row, = summarize(events)
        self.assertEqual(row["anchor_count"], 9)
        self.assertEqual(row["level_count"], 8)
        self.assertEqual(row["contact_count"], 7)
        self.assertAlmostEqual(row["reaction_fraction_lower"], 2 / 7)
        self.assertAlmostEqual(row["reaction_fraction_upper"], 3 / 7)
        self.assertAlmostEqual(row["per_symbol_macro_lower"], (2 / 3 + 0) / 2)
        self.assertEqual(row["per_symbol_macro_upper"], 0.5)
        self.assertEqual(row["macro_contact_symbol_count"], 2)

    def test_absent_denominator_is_null_but_real_zero_remains_zero(self):
        no_contact, = summarize([self.event("no_level")])
        self.assertIsNone(no_contact["reaction_fraction_lower"])
        self.assertIsNone(no_contact["distance_atr_mean"])
        broken, = summarize([self.event("break")])
        self.assertEqual(broken["reaction_fraction_lower"], 0)
        self.assertEqual(broken["reaction_fraction_upper"], 0)


if __name__ == "__main__":
    unittest.main()
