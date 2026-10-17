"""No partial 630-member results, missing Pine plans, or truncated PNG pages."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scanning.display_codes import SCANNER_ORDER
from scripts.atc_saved_scan_plans import PlanLevels
from scripts.atc_timeframe_visuals import (
    full_card_pages,
    pine_plan_required,
    require_complete_publication,
    select_verified_matches,
)

IST = ZoneInfo("Europe/Istanbul")
BAR = datetime(2026, 10, 16, 18, tzinfo=IST)
LONG = PlanLevels(100, 96, 104, 108, 112, "raw")
SHORT = PlanLevels(100, 104, 96, 92, 88, "raw")


class CompletePublicationTests(unittest.TestCase):
    def test_require_full_630_real_candles_even_when_plan_is_valid(self):
        match = ("ASELS", 1, "POZITIF")
        with self.assertRaisesRegex(ValueError, "629/630"):
            require_complete_publication(
                timeframe="1d", covered=629, matches=[match], plans={match: LONG},
            )

    def test_no_missing_pine_stop_tp_allowed_at_any_ratio(self):
        matches = [
            ("ASELS", 1, "POZITIF"),
            ("THYAO", 10, "NEGATIF"),
            ("BIMAS", 17, "POZITIF"),
            ("KRDMD", 18, "NEGATIF"),
        ]
        with self.assertRaisesRegex(ValueError, "THYAO:10:SHORT"):
            require_complete_publication(
                timeframe="1d", covered=630, matches=matches,
                plans={matches[0]: LONG},
            )
        outcome = require_complete_publication(
            timeframe="1d", covered=630, matches=matches,
            plans={matches[0]: LONG, matches[1]: SHORT},
        )
        self.assertEqual(outcome, {"verified_plans": 2, "nonplan_matches": 2})

    def test_pine_scope_keeps_native_nonplan_rules_unfabricated(self):
        self.assertTrue(pine_plan_required(("AAA", 1, "POZITIF")))
        self.assertTrue(pine_plan_required(("AAA", 9, "POZITIF")))
        self.assertFalse(pine_plan_required(("AAA", 9, "NEGATIF")))
        self.assertTrue(pine_plan_required(("AAA", 10, "NEGATIF")))
        self.assertTrue(pine_plan_required(("AAA", 16, "POZITIF")))
        self.assertFalse(pine_plan_required(("AAA", 17, "POZITIF")))
        self.assertFalse(pine_plan_required(("AAA", 18, "NEGATIF")))
        self.assertFalse(pine_plan_required(("AAA", 10, "NOTR")))

    def test_all_pages_include_every_match_in_groups_of_20(self):
        self.assertEqual(full_card_pages(0), 1)
        self.assertEqual(full_card_pages(20), 1)
        self.assertEqual(full_card_pages(200), 10)
        self.assertEqual(full_card_pages(201), 11)
        self.assertEqual(full_card_pages(475), 24)
        matches = [(f"S{i:03d}", 1, "POZITIF") for i in range(475)]
        pages = full_card_pages(len(matches))
        flattened = [
            match
            for page in range(pages)
            for match in matches[page * 20:(page + 1) * 20]
        ]
        self.assertEqual(flattened, matches)

    def test_630_member_verifier_does_not_accept_90_percent_coverage(self):
        binding = SimpleNamespace(
            scanner=SimpleNamespace(
                id=SCANNER_ORDER[0], version="test-version",
            ),
            ruleset_hash="test-rules",
            shadow_timeframes=frozenset({Timeframe.D1}),
        )
        members = [
            SimpleNamespace(instrument_id=f"i-{i}", symbol=f"H{i:03d}")
            for i in range(630)
        ]
        evaluations = [
            (
                f"i-{i}", "1d", SCANNER_ORDER[0], "test-version",
                "test-rules", BAR, "no_match", None, f"e-{i}", (),
            )
            for i in range(629)
        ]
        with self.assertRaisesRegex(ValueError, "629/630"):
            select_verified_matches(
                members, evaluations, (binding,), "1d",
                now=BAR + timedelta(hours=1),
            )
        evaluations.append((
            "i-629", "1d", SCANNER_ORDER[0], "test-version",
            "test-rules", BAR, "no_match", None, "e-629", (),
        ))
        close, covered, matches = select_verified_matches(
            members, evaluations, (binding,), "1d",
            now=BAR + timedelta(hours=1),
        )
        self.assertEqual(close, BAR)
        self.assertEqual(covered, 630)
        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
