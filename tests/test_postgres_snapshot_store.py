from __future__ import annotations

import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.market_data.errors import SeriesRevisionConflict
from market_intelligence.persistence.postgres.snapshots import PostgresSnapshotStore

ISTANBUL = ZoneInfo("Europe/Istanbul")


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeCursor(FakeContext):
    def __init__(self, conflict: tuple[object, ...] | None = None) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.executed_many: list[tuple[str, list[tuple[object, ...]]]] = []
        self.conflict = conflict

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executed.append((query, params))

    def executemany(self, query: str, params: list[tuple[object, ...]]) -> None:
        self.executed_many.append((query, params))

    def fetchone(self) -> tuple[object, ...] | None:
        conflict = self.conflict
        self.conflict = None
        return conflict


class FakeConnection:
    def __init__(self, conflict: tuple[object, ...] | None = None) -> None:
        self.cursor_instance = FakeCursor(conflict)
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
        self.assertEqual(len(connection.cursor_instance.executed), 3)
        self.assertEqual(len(connection.cursor_instance.executed_many), 0)
        bar_rows = json.loads(connection.cursor_instance.executed[0][1][0])
        self.assertEqual(len(bar_rows), 1)
        self.assertEqual(bar_rows[0]["instrument_id"], "instrument-1")
        self.assertEqual(bar_rows[0]["timeframe"], "15m")
        snapshot_params = connection.cursor_instance.executed[2][1]
        self.assertEqual(snapshot_params[5], 1)
        self.assertIn("canonical_market_bars", snapshot_params[10])

    def test_changed_bar_requires_new_series_revision(self) -> None:
        connection = FakeConnection(("2026-09-07T10:15:00+03:00",))

        with self.assertRaisesRegex(SeriesRevisionConflict, "series_revision artırılmalıdır"):
            PostgresSnapshotStore(connection).save(frame())

        self.assertEqual(len(connection.cursor_instance.executed), 2)

    def test_latest_series_revision_is_scoped_to_canonical_series(self) -> None:
        connection = FakeConnection((4,))

        revision = PostgresSnapshotStore(connection).latest_series_revision(
            instrument_id="instrument-1",
            timeframe="1h",
            source="borsapy",
            price_basis="split_adjusted",
        )

        self.assertEqual(revision, 4)
        self.assertEqual(
            connection.cursor_instance.executed[0][1],
            ("instrument-1", "1h", "borsapy", "split_adjusted"),
        )


if __name__ == "__main__":
    unittest.main()
