from __future__ import annotations

import copy
import io
import json
import unittest
from unittest.mock import patch

from PIL import Image

from market_intelligence.scanning.display_codes import SCANNER_ORDER, scanner_code
from scripts import atc_live_timeframe_pages as pages


def scan(number, direction="bullish", **changes):
    result = {"scanner_id": SCANNER_ORDER[number - 1], "number": number,
        "code": scanner_code(number), "status": "match", "findings": [{"direction": direction}]}
    result.update(changes)
    return result


def stock(symbol="ASELS", evaluations=None, **changes):
    result = {"symbol": symbol, "close": 342.75, "status": "available", "snapshot_id": "source:" + symbol,
        "metadata": {"usable_latest": True, "status": "latest_native_observation"},
        "evaluations": evaluations if evaluations is not None else [scan(1), scan(2)]}
    result.update(changes)
    return result


def report(rows=None, timeframe="15m"):
    return {"timeframe": timeframe, "observation_start": "2026-10-21T09:00:00+03:00",
        "observation_end": "2026-10-21T09:10:00+03:00", "rows": rows if rows is not None else [stock()]}


class TimeframePageMetadataTests(unittest.TestCase):
    def test_normal_groups_one_vote_and_same_tf_groups_require_two_distinct_scanners(self):
        source = report([stock(evaluations=[scan(1), scan(2), scan(3, "bearish")])])
        normal = pages.build_timeframe_metadata(source, minimum_scanners=1)
        same_tf = pages.build_timeframe_metadata(source, minimum_scanners=2)
        self.assertEqual(normal["mode"], "all_direction_matches")
        self.assertEqual(same_tf["mode"], "same_timeframe_intersections")
        self.assertEqual(normal["directions"]["bearish"]["stock_count"], 1)
        self.assertEqual(same_tf["directions"]["bearish"]["stock_count"], 0)
        self.assertEqual(same_tf["directions"]["bullish"]["pages"][0]["stocks"][0]["scanner_codes"], ["A", "B"])
        self.assertFalse(same_tf["criteria"]["different_timeframes_required"])

    def test_duplicate_findings_evaluations_and_identical_stock_rows_do_not_inflate_votes(self):
        repeated = scan(1, findings=[{"direction": "bullish"}, {"direction": "bullish"}])
        row = stock(evaluations=[repeated, copy.deepcopy(repeated)])
        source = report([row, copy.deepcopy(row)])
        normal = pages.build_timeframe_metadata(source)
        self.assertEqual(normal["directions"]["bullish"]["pages"][0]["stocks"][0]["scanner_count"], 1)
        self.assertEqual(normal["source_stock_count"], 1)
        self.assertEqual(normal["duplicate_identical_rows_ignored"], 1)
        self.assertEqual(pages.build_timeframe_metadata(source, minimum_scanners=2)["directions"]["bullish"]["pages"], [])

    def test_conflicting_duplicate_source_snapshots_are_not_combined_into_a_false_intersection(self):
        with self.assertRaisesRegex(ValueError, "conflicting_duplicate"):
            pages.build_timeframe_metadata(report([
                stock(evaluations=[scan(1)]), stock(evaluations=[scan(2)], snapshot_id="different-source")]), minimum_scanners=2)

    def test_same_stock_can_have_independent_long_and_short_groups_without_mixing_plans(self):
        evaluations = [scan(1), scan(2), scan(3, "bearish"), scan(4, "bearish")]
        evaluations[0]["findings"][0]["plan"] = {"entry": 342.75, "stop": 300, "tp1": 380}
        evaluations[2]["findings"][0]["plan"] = {"entry": 342.75, "stop": 400, "tp1": 250}
        result = pages.build_timeframe_metadata(report([stock(evaluations=evaluations)]), minimum_scanners=2)
        long = result["directions"]["bullish"]["pages"][0]["stocks"][0]
        short = result["directions"]["bearish"]["pages"][0]["stocks"][0]
        self.assertEqual(long["scanner_codes"], ["A", "B"])
        self.assertEqual(short["scanner_codes"], ["C", "D"])
        self.assertTrue(long["has_opposite_direction_matches"])
        self.assertFalse(result["stop_tp_plans_mixed"])
        serialized = json.dumps(result)
        for forbidden in ('"plan"', '"entry"', '"stop"', '"tp1"'):
            self.assertNotIn(forbidden, serialized)

    def test_no_match_unknown_neutral_unknown_scanner_or_forged_identity_are_not_votes(self):
        invalid = [scan(1, status="unknown"), scan(2, status="no_match"), scan(3, direction="neutral"),
            scan(4, scanner_id="not.a.scanner"), scan(5, scanner_id=["invalid"]),
            {**scan(6), "number": True}, {**scan(7), "number": 7.0}, scan(8, code="A"),
            scan(9, findings=[{"direction": ["bullish"]}])]
        result = pages.build_timeframe_metadata(report([stock(evaluations=invalid)]))
        self.assertEqual(result["directions"]["bullish"]["stock_count"], 0)
        self.assertEqual(result["directions"]["bearish"]["stock_count"], 0)

    def test_unavailable_stale_halted_and_ineligible_rows_do_not_vote(self):
        rows = [stock("GOOD"), stock("MISSING", status="source_unavailable"),
            stock("STALE", metadata={"usable_latest": False}),
            stock("HALT1", market_event={"status": "official_halt"}),
            stock("HALT2", metadata={"usable_latest": True, "market_status": {"status": "halted"}}),
            stock("HALT3", metadata={"usable_latest": True, "status": "official_halt_last_real_source"}),
            stock("BLOCKED", metadata={"usable_latest": True, "eligible_for_current_signals": False})]
        result = pages.build_timeframe_metadata(report(rows))
        self.assertEqual(result["eligible_stock_count"], 1)
        self.assertEqual(result["directions"]["bullish"]["pages"][0]["symbols"], ["GOOD"])
        self.assertEqual(result["excluded_counts"]["market_halt"], 3)

    def test_existing_explicit_usable_prefix_and_regular_close_policy_is_preserved(self):
        rows = [stock("PREFIX", metadata={"usable_latest": True, "status": "stale_previous_bucket"}),
            stock("REGULAR", metadata={"usable_latest": True, "status": "last_regular_close_without_auction"})]
        result = pages.build_timeframe_metadata(report(rows))
        self.assertEqual(result["eligible_stock_count"], 2)

    def test_invalid_source_prices_are_not_invented_or_allowed_into_metadata(self):
        rows = [stock("ZERO", close=0), stock("NEGATIVE", close=-1), stock("NAN", close=float("nan")),
                stock("INF", close=float("inf")), stock("BOOL", close=True)]
        result = pages.build_timeframe_metadata(report(rows))
        self.assertEqual(result["eligible_stock_count"], 0)
        self.assertEqual(result["excluded_counts"]["invalid_source_price"], 5)
        json.dumps(result, allow_nan=False)

    def test_unlimited_pagination_keeps_every_stock_and_one_stock_last_page(self):
        source = report([stock(f"S{i:03}") for i in range(41)])
        result = pages.build_timeframe_metadata(source, minimum_scanners=2)
        group = result["directions"]["bullish"]
        self.assertEqual(group["stock_count"], 41)
        self.assertEqual([p["stock_count"] for p in group["pages"]], [20, 20, 1])
        self.assertEqual([s for p in group["pages"] for s in p["symbols"]], [f"S{i:03}" for i in range(41)])
        self.assertEqual(group["omitted_stock_count"], 0)

    def test_optional20_cap_discloses_omissions_and_ranks_by_distinct_matches_then_symbol(self):
        rows = [stock(f"S{i:03}") for i in range(25)]
        rows += [stock("ZZZ", evaluations=[scan(1), scan(2), scan(3)])]
        result = pages.build_timeframe_metadata(report(rows), minimum_scanners=2, max_stocks_per_direction=20)
        group = result["directions"]["bullish"]
        self.assertEqual(group["total_stock_count"], 26)
        self.assertEqual(group["stock_count"], 20)
        self.assertEqual(group["omitted_stock_count"], 6)
        self.assertEqual(group["pages"][0]["symbols"][:3], ["ZZZ", "S000", "S001"])
        self.assertEqual(group["page_count"], 1)

    def test_metadata_is_deterministic_after_source_reordering_and_declared_metadata_insertion(self):
        source = report([stock("ZZZ"), stock("AAA", evaluations=[scan(2), scan(1)])])
        expected = pages.build_timeframe_metadata(source, minimum_scanners=2, max_stocks_per_direction=20)
        source["rows"].reverse()
        source["same_timeframe_intersections"] = copy.deepcopy(expected)
        self.assertEqual(pages.build_timeframe_metadata(source, minimum_scanners=2, max_stocks_per_direction=20), expected)
        self.assertNotIn("files", expected)
        self.assertNotIn("sha256", json.dumps(expected))

    def test_normal_and_intersection_names_are_ascii_disjoint_and_timeframe_labels_are_turkish(self):
        source = report([stock(evaluations=[scan(1), scan(2), scan(3, "bearish"), scan(4, "bearish")])], "1wk")
        normal = pages.build_timeframe_metadata(source)
        same = pages.build_timeframe_metadata(source, minimum_scanners=2)
        normal_names = [p["filename"] for g in normal["directions"].values() for p in g["pages"]]
        same_names = [p["filename"] for g in same["directions"].values() for p in g["pages"]]
        self.assertFalse(set(normal_names) & set(same_names))
        self.assertTrue(all(name.isascii() for name in normal_names + same_names))
        self.assertEqual(same["timeframe_label"], "Haftalık")
        self.assertIn("SHORT", same["directions"]["bearish"]["display_title"])

    def test_metadata_never_needs_fonts_or_image_rendering_and_source_is_not_mutated(self):
        source = report()
        original = copy.deepcopy(source)
        with patch.object(pages, "_render_page", side_effect=AssertionError("No image rendering")):
            pages.build_timeframe_metadata(source)
        self.assertEqual(source, original)

    def test_invalid_limits_and_unknown_timeframes_fail_explicitly(self):
        for minimum in (True, 0, 3):
            with self.assertRaises(ValueError):
                pages.build_timeframe_metadata(report(), minimum_scanners=minimum)
        for cap in (True, 0, 10, 21):
            with self.assertRaises(ValueError):
                pages.build_timeframe_metadata(report(), max_stocks_per_direction=cap)
        with self.assertRaises(ValueError):
            pages.build_timeframe_metadata(report(timeframe="1mo"))


class TimeframePageImageTests(unittest.TestCase):
    def test_no_empty_direction_creates_a_blank_image(self):
        with patch.object(pages, "_render_page", side_effect=AssertionError("No empty image")):
            metadata, images = pages.build_timeframe_pages(report([stock(evaluations=[])]))
        self.assertEqual(images, {})
        self.assertTrue(all(group["page_count"] == 0 for group in metadata["directions"].values()))

    def test_actual_png_bytes_match_declared_nonempty_pages_and_one_stock_is_allowed(self):
        source = report([stock(evaluations=[scan(1, "bearish"), scan(2, "bearish")])])
        metadata, images = pages.build_timeframe_pages(source, minimum_scanners=2, max_stocks_per_direction=20)
        self.assertEqual(metadata, pages.build_timeframe_metadata(source, minimum_scanners=2, max_stocks_per_direction=20))
        self.assertEqual(len(images), 1)
        self.assertEqual(metadata["directions"]["bullish"]["pages"], [])
        page = metadata["directions"]["bearish"]["pages"][0]
        self.assertEqual(page["stock_count"], 1)
        image = Image.open(io.BytesIO(images[page["filename"]]))
        self.assertEqual(image.width, 1840)
        self.assertGreater(image.height, 350)
        image.verify()


if __name__ == "__main__":
    unittest.main()
