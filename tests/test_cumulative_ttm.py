from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from market_intelligence.fundamentals.providers import (
    _filter_as_of,
    _period,
    _sum4,
    _ttm_cumulative,
)

D = datetime

ASELS_NET_INCOME = [
    (D(2026, 6, 30), 14_439_306_000),
    (D(2026, 3, 31), 5_539_312_000),
    (D(2025, 12, 31), 35_268_093_342),
    (D(2025, 9, 30), 11_650_688_000),
    (D(2025, 6, 30), 8_461_244_000),
    (D(2025, 3, 31), 2_976_938_000),
    (D(2024, 12, 31), 20_024_880_987),
    (D(2024, 9, 30), 8_186_540_000),
]


class CumulativeTtmTests(unittest.TestCase):
    def test_borsapy_quarter_label_resolves_to_quarter_end(self) -> None:
        self.assertEqual(_period("2026Q2"), D(2026, 6, 30))

    def test_as_of_filter_does_not_admit_an_unfinished_quarter(self) -> None:
        frame = pd.DataFrame({"2026Q2": [1.0], "2026Q1": [2.0]}, index=["revenue"])
        filtered = _filter_as_of(frame, D(2026, 5, 15))
        self.assertIsNotNone(filtered)
        self.assertEqual(list(filtered.columns), ["2026Q1"])

    def test_asels_cumulative_ttm_does_not_double_count_quarters(self) -> None:
        legacy = _sum4([value for _, value in ASELS_NET_INCOME])
        fixed = _ttm_cumulative(ASELS_NET_INCOME)
        self.assertAlmostEqual(legacy / 1e9, 66.90, places=1)
        self.assertAlmostEqual(fixed / 1e9, 41.25, places=1)

    def test_q4_cumulative_value_is_already_full_year(self) -> None:
        only_q4 = [item for item in ASELS_NET_INCOME if item[0].month == 12]
        self.assertEqual(_ttm_cumulative(only_q4), 35_268_093_342)

    def test_missing_reference_returns_none(self) -> None:
        self.assertIsNone(_ttm_cumulative(ASELS_NET_INCOME[:2]))
        self.assertIsNone(_ttm_cumulative([]))

    def test_previous_ttm_uses_calendar_quarter_when_middle_period_is_missing(self) -> None:
        cumulative = [
            (D(2026, 6, 30), 120.0),
            (D(2026, 3, 31), 50.0),
            (D(2025, 12, 31), 180.0),
            # 2025Q3 is deliberately missing.
            (D(2025, 6, 30), 90.0),
            (D(2025, 3, 31), 40.0),
            (D(2024, 12, 31), 140.0),
            (D(2024, 9, 30), 80.0),
            (D(2024, 6, 30), 50.0),
            (D(2024, 3, 31), 20.0),
        ]
        self.assertEqual(_ttm_cumulative(cumulative), 210.0)
        self.assertEqual(_ttm_cumulative(cumulative, 4), 180.0)

    def test_missing_exact_lagged_quarter_returns_none(self) -> None:
        without_prior_same = [
            item for item in ASELS_NET_INCOME if item[0] != D(2025, 6, 30)
        ]
        self.assertIsNone(_ttm_cumulative(without_prior_same, 4))

    def test_negative_lag_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _ttm_cumulative(ASELS_NET_INCOME, -1)

    def test_discrete_quarters_keep_sum4_behavior(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
        self.assertEqual(_sum4(values), 100.0)
        self.assertEqual(_sum4(values, 4), 260.0)


if __name__ == "__main__":
    unittest.main()
