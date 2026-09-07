from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.structure_hierarchy import (
    DegreeConfig,
    _confirmed_pivots,
    _sequence_evidence,
    analyze_structure_hierarchy,
)


class StructureHierarchyTests(unittest.TestCase):
    def test_same_degree_sequence_classifies_core_states(self) -> None:
        up = [
            {"type": "high", "label": "HH"},
            {"type": "low", "label": "HL"},
            {"type": "high", "label": "HH"},
            {"type": "low", "label": "HL"},
        ]
        down = [
            {"type": "high", "label": "LH"},
            {"type": "low", "label": "LL"},
            {"type": "high", "label": "LH"},
            {"type": "low", "label": "LL"},
        ]
        contraction = [
            {"type": "high", "label": "LH"},
            {"type": "low", "label": "HL"},
        ]
        self.assertEqual(_sequence_evidence(up)["state"], "UP")
        self.assertEqual(_sequence_evidence(down)["state"], "DOWN")
        self.assertEqual(_sequence_evidence(contraction)["state"], "CONTRACTION")

    def test_pivot_is_not_available_before_right_confirmation(self) -> None:
        index = pd.date_range("2026-01-01", periods=11, freq="D")
        close = np.array([10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10], dtype=float)
        frame = pd.DataFrame(
            {
                "Open": close,
                "High": close + 0.5,
                "Low": close - 0.5,
                "Close": close,
                "Volume": 1000,
            },
            index=index,
        )
        pivots = _confirmed_pivots(frame, DegreeConfig("TEST", 2, 2, 2))
        high = next(item for item in pivots if item["type"] == "high" and item["pos"] == 5)
        self.assertEqual(high["confirmed_pos"], 7)
        self.assertEqual(high["confirmed_at"], str(index[7]))

    def test_candidate_rail_never_becomes_confluence_by_name_only(self) -> None:
        # Public output contract: confluence eligibility is tied to CONFIRMED status.
        index = pd.date_range("2025-01-01", periods=120, freq="D")
        trend = np.linspace(50.0, 80.0, len(index))
        wave = np.sin(np.arange(len(index)) / 3.0) * 2.0
        close = trend + wave
        frame = pd.DataFrame(
            {
                "Open": close - 0.2,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": 1000 + (np.arange(len(index)) % 10) * 100,
            },
            index=index,
        )
        result = analyze_structure_hierarchy(frame)
        for degree in ("MAJOR", "SWING", "MINOR"):
            item = result.get(degree) or {}
            rail = item.get("rail") or {}
            if rail.get("status") != "CONFIRMED":
                self.assertFalse(item.get("confluence_eligible"))

    def test_summary_uses_major_swing_local_symbols(self) -> None:
        index = pd.date_range("2024-01-01", periods=160, freq="D")
        close = 100 + np.sin(np.arange(len(index)) / 5.0) * 8 + np.arange(len(index)) * 0.08
        frame = pd.DataFrame(
            {
                "Open": close - 0.2,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": 1000,
            },
            index=index,
        )
        summary = analyze_structure_hierarchy(frame)["summary"]
        self.assertIn("M", summary)
        self.assertIn("S", summary)
        self.assertIn("L", summary)


if __name__ == "__main__":
    unittest.main()
