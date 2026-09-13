import unittest

from market_intelligence.application.scan_intersections import (
    cross_timeframe_intersections,
    timeframe_intersections,
)


def row(symbol, scanner, direction="bullish"):
    return {"symbol": symbol, "scanner": scanner, "direction": direction, "plan": {"scenarios": []}}


class IntersectionTests(unittest.TestCase):
    def test_duplicates_and_neutral_do_not_count(self):
        items = [row("A", "one"), row("A", "one"), row("A", "two", "neutral")]
        self.assertEqual(timeframe_intersections(items), [])

    def test_names_and_conflicts_are_preserved(self):
        items = [row("A", "one"), row("A", "two"), row("A", "risk", "bearish")]
        result = timeframe_intersections(items)[0]
        self.assertEqual(result["scanners"], ["one", "two"])
        self.assertEqual(result["opposing"], ["risk"])

    def test_opposite_votes_are_not_combined(self):
        self.assertEqual(timeframe_intersections([row("A", "one"), row("A", "two", "bearish")]), [])

    def test_top20_deterministic_and_unique(self):
        items = [row(f"A{i:02}", s) for i in range(25) for s in ("one", "two")]
        result = timeframe_intersections(list(reversed(items)))
        self.assertEqual(len(result), 20)
        self.assertEqual(result[0]["symbol"], "A00")
        self.assertEqual(result[-1]["symbol"], "A19")

    def test_global_uses_untruncated_lists_and_unique_scanners(self):
        items = [row(f"A{i:02}", s) for i in range(25) for s in ("one", "two")]
        result = cross_timeframe_intersections(
            {"15m": items, "1h": [row("A24", s) for s in ("one", "two")]}
        )
        self.assertEqual(result[0]["symbol"], "A24")
        self.assertEqual(result[0]["count"], 2)
        self.assertEqual(result[0]["timeframe_count"], 2)

    def test_global_opposite_timeframes_do_not_agree(self):
        up = [row("A", s) for s in ("one", "two")]
        down = [row("A", s, "bearish") for s in ("one", "two")]
        self.assertEqual(cross_timeframe_intersections({"15m": up, "1h": down}), [])

    def test_global_ranks_timeframe_count_first(self):
        a = [row("A", s) for s in ("one", "two")]
        b = [row("B", s) for s in ("one", "two", "three")]
        result = cross_timeframe_intersections({"15m": a + b, "1h": a + b, "4h": a})
        self.assertEqual([r["symbol"] for r in result], ["A", "B"])
