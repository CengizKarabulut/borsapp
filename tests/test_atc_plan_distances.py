"""Distance disclosures describe whole source plans without fitting their prices."""
from __future__ import annotations

import csv
import io
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import patch

from PIL import Image, ImageDraw

from scripts.atc_saved_scan_plans import PlanLevels, plan_distance_percentages
from scripts.atc_timeframe_visuals import confirmed_match_csv, render_card_png
from scripts.e_manual_bridge import format_plan_line


class PlanDistanceTests(unittest.TestCase):
    def test_long_and_short_distances_use_the_same_original_entry(self):
        for direction, plan in (
            ("bullish", PlanLevels(100, 96, 104, 108, 112, "raw")),
            ("bearish", PlanLevels(100, 104, 96, 92, 88, "split_adjusted")),
        ):
            with self.subTest(direction=direction):
                result = plan_distance_percentages(plan, direction)
                self.assertAlmostEqual(result["stop"], 4)
                self.assertAlmostEqual(result["tp3"], 12)

    def test_large_positive_distance_remains_exact_and_is_not_a_price_cap(self):
        plan = PlanLevels(100, 1, 199, 298, 397, "raw")
        original = deepcopy(plan)
        result = plan_distance_percentages(plan, "bullish")
        self.assertEqual(result, {"stop": 99, "tp3": 297})
        self.assertEqual(plan, original)

    def test_incomplete_nonfinite_wrong_side_and_unavailable_basis_have_no_pair(self):
        for plan in (
            None, (100, 96, 104, 108, 112, "raw"),
            PlanLevels(100, 96, 104, 108, None, "raw"),
            PlanLevels(100, 96, 104, 108, -1, "raw"),
            PlanLevels(100, 96, 104, 108, float("inf"), "raw"),
            PlanLevels(100, 104, 96, 92, 88, "raw"),
            PlanLevels(100, 96, 104, 108, 112, "unknown"),
        ):
            with self.subTest(plan=plan):
                self.assertIsNone(plan_distance_percentages(plan, "bullish"))
        self.assertIsNone(plan_distance_percentages(
            PlanLevels(100, 96, 104, 108, 112, "raw"), "neutral",
        ))

    def test_csv_preserves_source_prices_and_labels_and_appends_distances(self):
        valid, invalid = ("TEST", 1, "POZITIF"), ("SHORT", 2, "NEGATIF")
        plans = {valid: PlanLevels(100, 1, 199, 298, 397, "raw"),
                 invalid: PlanLevels(30, 47, 13, None, None, "raw")}
        rows = list(csv.DictReader(io.StringIO(confirmed_match_csv(
            matches=[valid, invalid], plans=plans,
            model_failures={invalid: "nonpositive_level"},
            bar_time=datetime(2026, 10, 18, tzinfo=UTC),
        ).decode("utf-8-sig"))))
        self.assertEqual([rows[0][key] for key in ("Giris", "Stop", "TP1", "TP2", "TP3")],
                         ["100", "1", "199", "298", "397"])
        self.assertEqual(rows[0]["StopMesafesiYuzde"], "99")
        self.assertEqual(rows[0]["TP3MesafesiYuzde"], "297")
        self.assertEqual(rows[1]["PlanDurumu"], "RISK_MODELI_UYGULANAMAZ")
        self.assertEqual(rows[1]["PlanNedeni"], "nonpositive_level")
        self.assertEqual(rows[1]["TP2"], "-")
        self.assertEqual(rows[1]["StopMesafesiYuzde"], "")
        self.assertEqual(rows[1]["TP3MesafesiYuzde"], "")

    def test_png_second_line_only_describes_complete_plans_and_fits_the_column(self):
        recorded = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, position, text, *args, **kwargs):
            recorded.append((position, text, draw.textbbox(position, text, font=kwargs["font"])))
            return original_text(draw, position, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            png = render_card_png(
                timeframe="1d", bar_time=datetime(2026, 10, 18, tzinfo=UTC),
                rows=[("TEST", 1, "POZITIF", PlanLevels(100, 1, 199, 298, 397, "raw")),
                      ("SHORT", 2, "NEGATIF", PlanLevels(30, 47, 13, None, None, "raw"),
                       "nonpositive_level")],
                matched_count=2, total_symbols=630, page=1, pages=1,
            )
        image = Image.open(io.BytesIO(png))
        percentages = [row for row in recorded if row[1].startswith("Stop %")]
        self.assertEqual([row[1] for row in percentages], ["Stop %99.00"])
        self.assertEqual(percentages[0][0], (1640, 291))
        self.assertLess(percentages[0][2][2], image.width - 43)
        self.assertLess(percentages[0][2][3], 267 + 44)

    def test_e_text_preserves_nearest_whole_calibrated_scenario_and_prices(self):
        nearest = {"side": "short", "entry": 100.0, "stop": 105.0,
                   "tp1": 95.0, "tp2": 90.0, "tp3": 85.0,
                   "profile_id": "verified-profile", "stop_basis": "validated_fixed_atr_multiplier"}
        farther = dict(nearest, stop=110.0, tp1=90.0, tp2=80.0, tp3=70.0)
        item = {"direction": "bearish", "plan": {
            "status": "calibrated_reference", "scenarios": [farther, nearest],
        }}
        original = deepcopy(item)
        text = format_plan_line(item, lambda row: "legacy")
        self.assertIn("Stop 105.00 · TP1 95.00 · TP2 90.00 · TP3 85.00", text)
        self.assertIn("Kalibre referans · Stop mesafesi %5.00 · TP3 mesafesi %15.00", text)
        self.assertNotIn("Stop 110.00", text)
        self.assertEqual(item, original)

    def test_e_text_does_not_resize_large_reference_or_borrow_missing_target(self):
        scenario = {"side": "long", "entry": 100.0, "stop": 1.0,
                    "tp1": 199.0, "tp2": 298.0, "tp3": 397.0}
        item = {"direction": "bullish", "plan": {"status": "reference", "scenarios": [scenario]}}
        text = format_plan_line(item, lambda row: "legacy")
        self.assertIn("TP3 397.00 · Referans · Stop mesafesi %99.00 · TP3 mesafesi %297.00", text)
        scenario["tp3"] = None
        self.assertEqual(format_plan_line(item, lambda row: "legacy"), "legacy")


if __name__ == "__main__":
    unittest.main()
