from __future__ import annotations

import io
import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from PIL import Image

from scripts.atc_saved_scan_plans import (
    PlanLevels,
    fmt_level,
    plan_from_stored_rows,
    validate_reference_plan,
)
from scripts.atc_timeframe_visuals import render_card_png

IST = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 16, 15, tzinfo=IST)


def saved_plan(direction="long", *, snapshot="exact-snapshot"):
    reference = 100.0
    if direction == "long":
        prices = [96.0, 104.0, 108.0, 112.0]
    else:
        prices = [104.0, 96.0, 92.0, 88.0]
    return {
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
            ("id-T", "1h", "signal.macd_positive_cross", "1.0", "rule",
             NOW, "match", None, "evaluation-T", ("bearish",)),
        ]
        matches = (("ASELS", 1, "POZITIF"), ("THYAO", 1, "NEGATIF"))
        one = ("id-A", "signal.macd_positive_cross", "1h", NOW, "evaluation-A",
               "bullish", {"trade_plan": saved_plan()}, "exact-snapshot")
        other = ("id-T", "signal.macd_positive_cross", "1h", NOW, "evaluation-T",
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
        self.assertEqual(fmt_level(None), "—")


if __name__ == "__main__":
    unittest.main()
