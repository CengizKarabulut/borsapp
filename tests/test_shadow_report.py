from __future__ import annotations

import unittest

from market_intelligence.shadow.report import ParityScore


class ParityScoreTests(unittest.TestCase):
    def test_unknown_samples_are_removed_from_agreement_denominator(self) -> None:
        score = ParityScore("scanner", "1h", 100, 10, 80, 0, 0, 0, 10)
        self.assertEqual(score.comparable, 90)
        self.assertEqual(score.agreement, 1.0)

    def test_legacy_only_always_blocks_gate(self) -> None:
        score = ParityScore("scanner", "1h", 500, 20, 479, 1, 0, 0, 0)
        self.assertFalse(score.passes())

    def test_default_gate_requires_samples_and_agreement(self) -> None:
        passing = ParityScore("scanner", "1h", 200, 10, 189, 0, 1, 0, 0)
        too_small = ParityScore("scanner", "1h", 199, 10, 189, 0, 0, 0, 0)
        self.assertTrue(passing.passes())
        self.assertFalse(too_small.passes())
