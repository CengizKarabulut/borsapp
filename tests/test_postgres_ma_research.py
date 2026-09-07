from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.persistence.postgres.ma_research import PostgresMaResearchStore
from market_intelligence.research.ma_levels import ResearchedMaLevel


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeCursor(FakeContext):
    def __init__(self, latest=None) -> None:
        self.latest = latest
        self.queries = []

    def execute(self, query, params) -> None:
        self.queries.append((query, params))

    def fetchone(self):
        return (self.latest,)


class FakeConnection:
    def __init__(self, latest=None) -> None:
        self.cursor_instance = FakeCursor(latest)
        self.transactions = 0

    def transaction(self):
        self.transactions += 1
        return FakeContext()

    def cursor(self):
        return self.cursor_instance


def frame() -> CanonicalFrame:
    start = datetime(2026, 9, 6, tzinfo=UTC)
    return CanonicalFrame(
        instrument_id="instrument-1",
        symbol_at_snapshot="TEST",
        market="BIST",
        timeframe=Timeframe.D1,
        snapshot_id="snapshot-1",
        series_revision=1,
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        source="fixture",
        bars=(
            CanonicalBar(
                open_time=start,
                close_time=start + timedelta(days=1),
                open=100,
                high=102,
                low=99,
                close=101,
                volume=1000,
            ),
        ),
    )


class PostgresMaResearchStoreTests(unittest.TestCase):
    def test_levels_are_closed_and_replaced_in_one_transaction(self) -> None:
        connection = FakeConnection()
        level = ResearchedMaLevel(
            ma_type="EMA",
            period=55,
            qualification_side="support",
            level_class="strong_level",
            touches=12,
            quality_score=51.0,
            research_version="research-v1",
            metrics={"hold_rate_pct": 80.0},
        )
        stored = PostgresMaResearchStore(connection).replace(frame(), (level,))
        self.assertEqual(stored, 1)
        self.assertEqual(connection.transactions, 1)
        inserts = [
            params
            for query, params in connection.cursor_instance.queries
            if "INSERT INTO ma_research_levels" in query
        ]
        self.assertEqual(inserts[0][4], "support")
        self.assertIn('"hold_rate_pct":80.0', inserts[0][-1])

    def test_older_research_cannot_supersede_newer_levels(self) -> None:
        connection = FakeConnection(frame().through_bar_time + timedelta(days=1))
        with self.assertRaisesRegex(ValueError, "Daha yeni"):
            PostgresMaResearchStore(connection).replace(frame(), ())


if __name__ == "__main__":
    unittest.main()
