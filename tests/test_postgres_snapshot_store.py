from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.persistence.postgres.snapshots import PostgresSnapshotStore

ISTANBUL = ZoneInfo("Europe/Istanbul")


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeCursor(FakeContext):
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.executed_many: list[tuple[str, list[tuple[object, ...]]]] = []

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executed.append((query, params))

    def executemany(self, query: str, params: list[tuple[object, ...]]) -> None:
        self.executed_many.append((query, params))


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.transactions = 0

    def transaction(self) -> FakeContext:
        self.transactions += 1
        return FakeContext()

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


def frame() -> CanonicalFrame:
    return CanonicalFrame(
        instrument_id="instrument-1",
        symbol_at_snapshot="TEST",
        market="BIST",
        timeframe=Timeframe.M15,
        snapshot_id="snapshot-1",
        series_revision=1,
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        source="fixture",
        bars=(
            CanonicalBar(
                open_time=datetime(2026, 9, 7, 10, 0, tzinfo=ISTANBUL),
                close_time=datetime(2026, 9, 7, 10, 15, tzinfo=ISTANBUL),
                open=10,
                high=11,
                low=9,
                close=10.5,
                volume=100,
            ),
        ),
    )


class PostgresSnapshotStoreTests(unittest.TestCase):
    def test_snapshot_and_bars_are_written_in_one_transaction(self) -> None:
        connection = FakeConnection()

        PostgresSnapshotStore(connection).save(frame())

        self.assertEqual(connection.transactions, 1)
        self.assertEqual(len(connection.cursor_instance.executed), 1)
        self.assertEqual(len(connection.cursor_instance.executed_many), 1)
        bar_rows = connection.cursor_instance.executed_many[0][1]
        self.assertEqual(len(bar_rows), 1)
        self.assertEqual(bar_rows[0][0], "snapshot-1")


if __name__ == "__main__":
    unittest.main()
