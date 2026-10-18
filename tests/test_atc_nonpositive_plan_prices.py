"""Impossible source formula prices never become trade or report prices."""
from __future__ import annotations

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import ImageDraw

from market_intelligence.core.enums import PriceBasis
from market_intelligence.scanning.signal.atc_native_packet import (
    ATC_NATIVE_SIGNAL_IDS,
    ATC_SCRIPT_SHA256,
    AtcNativeSignalScanner,
)
from market_intelligence.scanning.trade_plan import build_trade_plan
from scripts.atc_saved_scan_plans import (
    PlanLevels,
    complete_reference_levels,
    load_saved_trade_plans,
    model_rejected_display_levels,
)
from scripts.atc_timeframe_visuals import render_card_png, require_complete_publication
from tests.test_atc_native_packet import context
from tests.test_trade_plan import frame


def volatile_frame(*, entry=30, high=44, low=29):
    source = frame()
    return replace(source, bars=tuple(
        replace(bar, open=entry, high=high, low=low, close=entry)
        for bar in source.bars
    ))


class NonpositivePlanPriceTests(unittest.TestCase):
    def test_negative_short_formula_keeps_exact_positive_prices_not_a_price_floor(self):
        plan = build_trade_plan(volatile_frame(), "bearish")
        # ATR15, original swing7 stop44+0.2*15=47, risk17. The original
        # 2R/3R outputs -4/-21 cannot be prices; positive 1R remains 13.
        self.assertEqual(plan["status"], "unavailable")
        self.assertEqual(plan["scenarios"], [])
        self.assertFalse(plan["executable_order"])
        self.assertEqual(plan["display_levels"], {
            "side": "short", "entry": 30, "stop": 47,
            "tp1": 13, "tp2": None, "tp3": None,
        })
        self.assertEqual(plan["invalid_level_fields"], ["tp2", "tp3"])
        json.dumps(plan, allow_nan=False)

    def test_zero_short_target_is_unavailable_and_not_a_valid_reference(self):
        source = volatile_frame(entry=9, high=11.5, low=9)
        plan = build_trade_plan(source, "bearish")
        self.assertEqual(plan["display_levels"], {
            "side": "short", "entry": 9, "stop": 12,
            "tp1": 6, "tp2": 3, "tp3": None,
        })
        self.assertEqual(plan["invalid_level_fields"], ["tp3"])
        partial = model_rejected_display_levels(plan, frame=source, direction="bearish")
        self.assertFalse(complete_reference_levels(partial, "bearish"))

    def test_a_i_bearish_finding_inherits_unavailable_not_negative_native_prices(self):
        source = volatile_frame()
        scanner = AtcNativeSignalScanner(ATC_NATIVE_SIGNAL_IDS[0])
        packet = SimpleNamespace(flags=(True,) + (False,) * 8,
                                 directions=(-1,) + (0,) * 8, bars=30)
        with patch.object(scanner, "_packet", return_value=packet):
            finding, = scanner.evaluate(source, context(source))
        self.assertEqual(finding.direction.value, "bearish")
        plan = finding.metrics["trade_plan"]
        self.assertEqual(plan["source_sha256"], ATC_SCRIPT_SHA256)
        self.assertEqual(plan["version"], "atc-native-dual-direction-v3")
        self.assertEqual(plan["status"], "unavailable")
        self.assertEqual(plan["display_levels"]["tp1"], 13)
        self.assertIsNone(plan["display_levels"]["tp2"])
        self.assertIsNone(plan["display_levels"]["tp3"])

    def test_partial_display_rejects_wrong_side_order_direction_and_basis(self):
        source = volatile_frame()
        plan = build_trade_plan(source, "bearish")
        for mutate in (
            {"side": "long"}, {"stop": 29}, {"tp1": 31},
            {"tp1": None, "tp2": 5}, {"tp2": 20, "tp3": None},
        ):
            with self.subTest(mutate=mutate):
                altered = {**plan, "display_levels": {**plan["display_levels"], **mutate}}
                self.assertIsNone(model_rejected_display_levels(
                    altered, frame=source, direction="bearish",
                ))
        for direction in ("neutral", "mixed", "unknown"):
            self.assertIsNone(model_rejected_display_levels(plan, frame=source,
                                                           direction=direction))
        self.assertIsNone(model_rejected_display_levels(
            plan, frame=replace(source, is_partial=True), direction="bearish",
        ))
        adjusted = replace(source, price_basis=PriceBasis.TOTAL_RETURN_ADJUSTED)
        altered = {**plan, "price_basis": "total_return_adjusted"}
        self.assertIsNone(model_rejected_display_levels(altered, frame=adjusted,
                                                       direction="bearish"))

    def test_old_saved_negative_diagnostics_are_safely_rendered_without_rewriting_them(self):
        source = volatile_frame()
        plan = build_trade_plan(source, "bearish")
        legacy = {**plan, "display_levels": {
            **plan["display_levels"], "tp2": -4, "tp3": -21,
        }}
        self.assertEqual(model_rejected_display_levels(legacy, frame=source,
                                                       direction="bearish"),
                         PlanLevels(30, 47, 13, None, None, "raw"))
        self.assertEqual(legacy["display_levels"]["tp2"], -4)

    def test_partial_plan_cannot_pass_publication_without_nonactionable_metadata(self):
        match = ("TEST", 1, "NEGATIF")
        for levels in (
            PlanLevels(30, 47, 13, None, None, "raw"),
            PlanLevels(30, 47, 13, -4, -21, "raw"),
            PlanLevels(30, 47, 13, 20, 5, "raw"),
        ):
            with self.subTest(levels=levels), self.assertRaisesRegex(ValueError, "plans missing"):
                require_complete_publication(timeframe="1h", covered=630,
                                             matches=[match], plans={match: levels})

    def test_closed_same_snapshot_loader_flags_short_and_long_impossible_models(self):
        for direction, source, state in (
            ("bearish", volatile_frame(), "NEGATIF"),
            ("bullish", volatile_frame(entry=10, high=1200, low=9), "POZITIF"),
        ):
            for include_metadata in (True, False):
                with self.subTest(direction=direction, include_metadata=include_metadata):
                    member = SimpleNamespace(instrument_id=source.instrument_id, symbol="TEST")
                    close = source.through_bar_time
                    scanner = ATC_NATIVE_SIGNAL_IDS[0]
                    evaluation = (source.instrument_id, "1h", scanner, "3.0.0", "rules",
                                  close, "match", None, "evaluation-id", (direction,))
                    identity = ("evaluation-id", source.instrument_id, scanner,
                                source.snapshot_id, source.source, "raw", 1,
                                source.bars[0].open_time, close, len(source.bars), "1h", close)
                    candles = [(b.open_time, b.close_time, b.open, b.high, b.low,
                                b.close, b.volume) for b in source.bars]
                    db = MagicMock()
                    db.cursor.return_value.__enter__.return_value.fetchall.side_effect = [
                        [], [identity], candles,
                    ]
                    key = ("TEST", 1, state)
                    with patch("builtins.print"):
                        result = load_saved_trade_plans(
                            db, members=[member], evaluations=[evaluation], matches=[key],
                            timeframe="1h", bar_time=close, include_model_failures=include_metadata,
                        )
                    if include_metadata:
                        levels, failures = result
                        self.assertEqual(failures[key], "nonpositive_level")
                        self.assertIsNotNone(levels[key])
                        self.assertFalse(complete_reference_levels(levels[key], direction))
                    else:
                        self.assertIsNone(result[key])

    def test_png_explains_each_nonactionable_row_and_never_draws_negative_price(self):
        source = volatile_frame()
        texts = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, position, text, *args, **kwargs):
            texts.append(text)
            return original_text(draw, position, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            render_card_png(
                timeframe="1h", bar_time=source.through_bar_time,
                rows=[("TEST", 1, "NEGATIF", PlanLevels(30, 47, 13, -4, -21, "raw"),
                       "nonpositive_level")], matched_count=1,
                total_symbols=630, page=1, pages=1,
            )
        self.assertIn("UYGULANAMAZ", texts)
        self.assertIn("13", texts)
        self.assertNotIn("-4", texts)
        self.assertNotIn("-21", texts)
        self.assertEqual(texts.count("-"), 2)


if __name__ == "__main__":
    unittest.main()
