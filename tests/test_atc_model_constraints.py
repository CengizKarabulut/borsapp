"""A fully measured but mathematically impossible 3R plan is not absent OHLC."""
from __future__ import annotations

import io
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

from scripts.atc_saved_scan_plans import PlanLevels
from scripts.atc_timeframe_visuals import (
    render_card_png,
    require_complete_publication,
)


class ActualPriceBoundaryTests(unittest.TestCase):
    def test_real_vendor_3r_below_zero_is_explicit_nonactionable_not_missing(self):
        short = ("BINHO", 15, "NEGATIF")
        long = ("LIDER", 8, "POZITIF")
        report = require_complete_publication(
            timeframe="1d", covered=630, matches=[short, long], plans={},
            model_failures={
                short: "nonpositive_level",
                long: "invalid_stop_or_target",
            },
        )
        self.assertEqual(report, {
            "verified_plans": 0, "model_rejected": 2, "nonplan_matches": 0,
        })

    def test_partial_display_preserves_nonactionable_model_count(self):
        short = ("BINHO", 15, "NEGATIF")
        partial = PlanLevels(30, 47, 13, None, None, "raw")
        report = require_complete_publication(
            timeframe="1d", covered=630, matches=[short],
            plans={short: partial},
            model_failures={short: "nonpositive_level"},
        )
        self.assertEqual(report, {
            "verified_plans": 0, "model_rejected": 1, "nonplan_matches": 0,
        })

    def test_bad_vendor_data_or_unknown_reason_still_blocks_delivery(self):
        short = ("BINHO", 15, "NEGATIF")
        for issue in (None, "missing_or_modified_snapshot",
                      "insufficient_history", "zero_volatility"):
            with self.subTest(issue=issue):
                with self.assertRaisesRegex(ValueError, "Stop/TP plans missing"):
                    require_complete_publication(
                        timeframe="1d", covered=630, matches=[short],
                        plans={},
                        model_failures={} if issue is None else {short: issue},
                    )

    def test_real_candle_shortfall_never_whitelisted_even_if_model_invalid(self):
        match = ("BINHO", 15, "NEGATIF")
        with self.assertRaisesRegex(ValueError, "629/630"):
            require_complete_publication(
                timeframe="1d", covered=629, matches=[match], plans={},
                model_failures={match: "nonpositive_level"},
            )

    def test_risk_model_not_actionable_is_visible_on_png_without_fake_levels(self):
        image = render_card_png(
            timeframe="1d",
            bar_time=datetime(2026, 10, 16, 18, tzinfo=ZoneInfo("Europe/Istanbul")),
            rows=[("BINHO", 15, "NEGATIF", None, "nonpositive_level")],
            matched_count=1, total_symbols=630, page=1, pages=1,
        )
        opened = Image.open(io.BytesIO(image))
        self.assertEqual(opened.format, "PNG")
        self.assertEqual(opened.width, 1840)
        self.assertGreater(len(image), 7000)


if __name__ == "__main__":
    unittest.main()
