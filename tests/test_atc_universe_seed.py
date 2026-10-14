from __future__ import annotations

import unittest
from pathlib import Path

from market_intelligence.market_data.universe import UniverseMember
from scripts.atc_universe_seed import load_pinned, reconcile


ROOT = Path(__file__).resolve().parents[1]


class AtcPinnedUniverseTests(unittest.TestCase):
    def test_original_630_watchlist_is_complete_and_unique(self):
        tickers = load_pinned(ROOT / "config/atc_630_symbols.txt")
        self.assertEqual(len(tickers), 630)
        self.assertEqual(len(set(tickers)), 630)
        self.assertIn("ASELS", tickers)
        self.assertIn("BOBET", tickers)

    def test_provider_mismatch_is_reported_not_silently_deleted(self):
        pinned = ("ABC", "DEF")
        observed = (
            UniverseMember(symbol="ABC", provider_symbol="ABC", name="ABC Corp"),
            UniverseMember(symbol="ZZZ", provider_symbol="ZZZ", name="Other"),
        )
        members, missing, outside = reconcile(pinned, observed)
        self.assertEqual(tuple(m.symbol for m in members), pinned)
        self.assertEqual(missing, ("DEF",))
        self.assertEqual(outside, ("ZZZ",))
        self.assertEqual(members[1].provider_symbol, "DEF")


if __name__ == "__main__":
    unittest.main()
