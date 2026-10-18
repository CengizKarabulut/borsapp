from __future__ import annotations

import io
import unittest
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from PIL import Image

from market_intelligence.scanning.signal.atc_native_packet import ATC_SCRIPT_SHA256
from market_intelligence.scanning.trade_plan import build_pine_a_i_plan, build_trade_plan
from scripts.atc_saved_scan_plans import (
    PlanLevels,
    fmt_level,
    model_rejected_display_levels,
    plan_from_stored_rows,
    validate_reference_plan,
)
from scripts.atc_timeframe_visuals import render_card_png
from tests.test_trade_plan import frame

IST = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 16, 15, tzinfo=IST)


def saved_plan(direction="long", *, snapshot="exact-snapshot"):
    reference = 100.0
    if direction == "long":
        prices = [96.0, 104.0, 108.0, 112.0]
    else:
        prices = [104.0, 96.0, 92.0, 88.0]
    return {
        "version": "atc-native-dual-direction-v3",
        "source_sha256": ATC_SCRIPT_SHA256,
        "status": "reference",
        "snapshot_id": snapshot,
        "timeframe": "1h",
        "bar_time": NOW.isoformat(),
        "price_basis": "raw",
        "scenarios": [{
            "side": direction, "entry": reference, "stop": prices[0],
            "tp1": prices[1], "tp2": prices[2], "tp3": prices[3],
        }],
    }


class PersistedStopAndTargetsTests(unittest.TestCase):
    def valid(self, plan, direction="bullish"):
        return validate_reference_plan(
            {"trade_plan": plan}, direction=direction,
            timeframe="1h", close=NOW, snapshot_id="exact-snapshot",
        )

    def test_valid_long_and_short_are_extracted_as_saved(self):
        self.assertEqual(
            self.valid(saved_plan()),
            PlanLevels(100, 96, 104, 108, 112, "raw"),
        )
        self.assertEqual(
            self.valid(saved_plan("short"), "bearish"),
            PlanLevels(100, 104, 96, 92, 88, "raw"),
        )

    def test_declared_generic_model_rejects_corrupt_ordered_target_without_capping_valid_prices(self):
        plan = saved_plan()
        plan["scenarios"][0]["tp3"] = 100000.0
        self.assertIsNone(self.valid(plan))
        plan["scenarios"][0].update(stop=1.0, tp1=199.0, tp2=298.0, tp3=397.0)
        self.assertEqual(self.valid(plan), PlanLevels(100, 1, 199, 298, 397, "raw"))

    def test_never_fabricate_for_incompatible_or_unavailable_plan(self):
        for direction in ("neutral", "mixed", "unknown"):
            with self.subTest(direction=direction):
                self.assertIsNone(self.valid(saved_plan(), direction))
        for mutate in (
            {"snapshot_id": "old-snapshot"},
            {"timeframe": "4h"},
            {"bar_time": "2026-10-15T15:00:00+03:00"},
            {"status": "unavailable"},
            {"price_basis": "unknown"},
            {"scenarios": []},
        ):
            plan = {**saved_plan(), **mutate}
            with self.subTest(mutate=mutate):
                self.assertIsNone(self.valid(plan))
        plan = saved_plan()
        plan["scenarios"][0]["tp2"] = 99
        self.assertIsNone(self.valid(plan))
        plan = saved_plan()
        plan["scenarios"][0]["stop"] = float("nan")
        self.assertIsNone(self.valid(plan))

    def test_stored_evaluation_does_not_cross_symbols_or_mum_time(self):
        members = (SimpleNamespace(instrument_id="id-A", symbol="ASELS"),
                   SimpleNamespace(instrument_id="id-T", symbol="THYAO"))
        evaluations = [
            ("id-A", "1h", "signal.macd_positive_cross", "1.0", "rule",
             NOW, "match", None, "evaluation-A", ("bullish",)),
            ("id-T", "1h", "technical.failed_breakout", "1.0", "rule",
             NOW, "match", None, "evaluation-T", ("bearish",)),
        ]
        matches = (("ASELS", 1, "POZITIF"), ("THYAO", 13, "NEGATIF"))
        one = ("id-A", "signal.macd_positive_cross", "1h", NOW, "evaluation-A",
               "bullish", {"trade_plan": saved_plan()}, "exact-snapshot")
        other = ("id-T", "technical.failed_breakout", "1h", NOW, "evaluation-T",
                 "bearish", {"trade_plan": saved_plan("short")}, "exact-snapshot")
        plans = plan_from_stored_rows(
            [one, other], members=members, evaluations=evaluations,
            matches=matches, timeframe="1h", bar_time=NOW,
        )
        self.assertEqual(plans[matches[0]].stop, 96)
        self.assertEqual(plans[matches[1]].stop, 104)
        swapped = plan_from_stored_rows(
            [(*one[:4], "evaluation-T", *one[5:])], members=members,
            evaluations=evaluations, matches=matches, timeframe="1h",
            bar_time=NOW,
        )
        self.assertIsNone(swapped[matches[0]])
        self.assertIsNone(swapped[matches[1]])
        disagree = plan_from_stored_rows(
            [one, (*one[:6], {"trade_plan": saved_plan("short")}, one[7])],
            members=members, evaluations=evaluations, matches=matches,
            timeframe="1h", bar_time=NOW,
        )
        self.assertIsNone(disagree[matches[0]])

    def test_old_native_pine_source_versions_never_pass_as_new_a_i_plans(self):
        members = (SimpleNamespace(instrument_id="id-A", symbol="ASELS"),)
        evaluation = ("id-A", "1h", "signal.macd_positive_cross", "3.0.0",
                      "hash", NOW, "match", None, "evaluation-A", ("bullish",))
        wrong = {**saved_plan(), "source_sha256": "obsolete"}
        row = ("id-A", "signal.macd_positive_cross", "1h", NOW,
               "evaluation-A", "bullish", {"trade_plan": wrong}, "exact-snapshot")
        key = ("ASELS", 1, "POZITIF")
        result = plan_from_stored_rows(
            [row], members=members, evaluations=[evaluation], matches=[key],
            timeframe="1h", bar_time=NOW,
        )
        self.assertIsNone(result[key])

    def test_png_shows_empty_fields_for_unconfirmed_rows(self):
        items = [
            ("ASELS", 1, "POZITIF", PlanLevels(100, 96, 104, 108, 112, "raw")),
            ("THYAO", 13, "NEGATIF", PlanLevels(100, 104, 96, 92, 88, "raw")),
            ("BIMAS", 10, "NOTR", None),
        ]
        image = render_card_png(
            timeframe="1h", bar_time=NOW, rows=items,
            matched_count=3, total_symbols=630, page=1, pages=1,
        )
        parsed = Image.open(io.BytesIO(image))
        self.assertEqual(parsed.format, "PNG")
        self.assertEqual(parsed.size[0], 1840)
        self.assertGreater(len(image), 8000)
        self.assertEqual(fmt_level(14.125, csv=True), "14.125")
        self.assertEqual(fmt_level(None), "-")
        self.assertEqual(fmt_level(None, csv=True), "-")
        for invalid in (0, -1, -0.001, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                self.assertEqual(fmt_level(invalid), "-")
                self.assertEqual(fmt_level(invalid, csv=True), "-")

    def test_generic_short_invalid_targets_display_only_positive_fields(self):
        f = frame()
        bars = tuple(replace(b, open=30, high=44, low=29, close=30) for b in f.bars)
        f = replace(f, bars=bars)
        original = build_trade_plan(f, "bearish")
        self.assertEqual(original["status"], "unavailable")
        self.assertEqual(original["reason"], "nonpositive_level")
        self.assertEqual(original["scenarios"], [])
        partial = model_rejected_display_levels(original, frame=f, direction="bearish")
        self.assertIsNotNone(partial)
        self.assertEqual(partial.entry, 30)
        self.assertGreater(partial.stop, partial.entry)
        self.assertGreater(partial.tp1, 0)
        self.assertIsNone(partial.tp2)
        self.assertIsNone(partial.tp3)
        self.assertEqual([fmt_level(x) for x in partial[0:5]][-2:], ["-", "-"])
        self.assertIsNone(model_rejected_display_levels(
            original, frame=replace(f, snapshot_id="other"), direction="bearish",
        ))

    def test_pine_long_invalid_stop_shows_positive_targets(self):
        f = frame()
        bars = [replace(b, open=10, high=11, low=9, close=10) for b in f.bars]
        bars[-1] = replace(bars[-1], high=1200)
        f = replace(f, bars=tuple(bars))
        original = build_pine_a_i_plan(f, "signal.smi_macd_positive", "bullish")
        self.assertEqual(original["reason"], "invalid_stop_or_target")
        partial = model_rejected_display_levels(original, frame=f, direction="bullish")
        self.assertIsNotNone(partial)
        self.assertEqual(partial.entry, 10)
        self.assertIsNone(partial.stop)
        self.assertGreater(partial.tp1, 10)
        self.assertGreater(partial.tp2, partial.tp1)
        self.assertGreater(partial.tp3, partial.tp2)


if __name__ == "__main__":
    unittest.main()
