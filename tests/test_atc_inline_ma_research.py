"""MA Rule18 exact-frame fallback does not manufacture research evidence."""
from __future__ import annotations

import unittest

from market_intelligence.features.ma import MaQualification
from market_intelligence.research.ma_inline import ExactFrameMaQualificationSource
from market_intelligence.research.ma_levels import MaResearchConfig
from tests.test_atc_native_packet import price_frame


class FakeSource:
    def __init__(self, rows=()):
        self.rows = rows

    def load(self, frame):
        return self.rows


class InlineResearchTests(unittest.TestCase):
    def test_never_overwrites_existing_qualified_research(self):
        level = MaQualification(
            "EMA", 21, "strong_level", 8, 57.0, "real-v1", "support",
        )
        source = ExactFrameMaQualificationSource(FakeSource((level,)))
        self.assertEqual(source.load(price_frame([100] * 450)), (level,))

    def test_closed_snapshot_produces_actual_measured_levels(self):
        source = ExactFrameMaQualificationSource(
            FakeSource(),
            config=MaResearchConfig(ma_types=("SMA",), periods=(21,)),
        )
        frame = price_frame([100.0 + 3.0 * (i % 9 - 4) / 13 for i in range(450)])
        rows = source.load(frame)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ma_type, "SMA")
        self.assertEqual(rows[0].period, 21)
        self.assertTrue(rows[0].research_version)
        self.assertGreaterEqual(rows[0].touches, 0)
        self.assertGreaterEqual(rows[0].quality_score, 0)

    def test_partial_or_short_history_never_fabricates_research(self):
        source = ExactFrameMaQualificationSource(FakeSource())
        self.assertEqual(source.load(price_frame([100.0] * 30)), ())


if __name__ == "__main__":
    unittest.main()
