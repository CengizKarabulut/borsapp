from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from market_intelligence.fundamentals.inflation import BorsapyTcmbInflationProvider


class FakeInflationSource:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[str, str]] = []

    def tufe(self, *, start: str, end: str) -> pd.DataFrame:
        self.calls.append((start, end))
        return self.frame


class InflationProviderTests(unittest.TestCase):
    def test_exact_financial_period_month_is_selected(self) -> None:
        frame = pd.DataFrame(
            {
                "YearlyInflation": [32.11, 33.52],
                "MonthlyInflation": [0.99, 1.21],
            },
            index=pd.to_datetime(["2026-06-01", "2026-07-01"]),
        )
        source = FakeInflationSource(frame)
        provider = BorsapyTcmbInflationProvider(lambda: source)

        value = provider.fetch_yoy(period_end=datetime(2026, 6, 30))

        self.assertEqual(value, 32.11)
        self.assertEqual(source.calls, [("2026-06-01", "2026-06-30")])

    def test_missing_exact_month_returns_none(self) -> None:
        frame = pd.DataFrame(
            {"YearlyInflation": [33.52]},
            index=pd.to_datetime(["2026-07-01"]),
        )
        provider = BorsapyTcmbInflationProvider(lambda: FakeInflationSource(frame))
        self.assertIsNone(provider.fetch_yoy(period_end=datetime(2026, 6, 30)))


if __name__ == "__main__":
    unittest.main()
