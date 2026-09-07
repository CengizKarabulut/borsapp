from __future__ import annotations

import json
import unittest
from datetime import date
from typing import Any

from market_intelligence.market_data.universe import (
    UniverseMember,
    build_universe_sync_plan,
)
from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None


class FakeCursor(FakeContext):
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.rows: list[tuple[Any, ...]] = []
        self.row: tuple[Any, ...] | None = None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.executed.append((query, params))
        if "FROM universe_memberships membership" in query:
            self.rows = [("instrument-asels", "ASELS", "ASELS", "BIST", "equity")]
        elif "SELECT DISTINCT ON" in query:
            self.rows = [("instrument-asels", "ASELS")]
        elif "INSERT INTO universe_sync_runs" in query:
            self.row = ("sync-1",)

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self.rows
        self.rows = []
        return rows

    def fetchone(self) -> tuple[Any, ...] | None:
        row = self.row
        self.row = None
        return row


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.transactions = 0

    def transaction(self) -> FakeContext:
        self.transactions += 1
        return FakeContext()

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


class PostgresRuntimeRepositoryTests(unittest.TestCase):
    def test_universe_sync_batches_all_members_in_fixed_query_count(self) -> None:
        plan = build_universe_sync_plan(
            universe_id="BIST_ALL",
            source="borsapy:XUTUM",
            as_of=date(2026, 9, 7),
            members=(
                UniverseMember("ASELS", "ASELS", "Aselsan"),
                UniverseMember("GARAN", "GARAN", "Garanti"),
            ),
            current_symbols=("ASELS",),
        )
        connection = FakeConnection()

        sync_id = PostgresRuntimeRepository(connection).apply_universe_sync(plan)

        self.assertEqual(sync_id, "sync-1")
        self.assertEqual(connection.transactions, 1)
        self.assertEqual(len(connection.cursor_instance.executed), 7)

        instrument_query = next(
            item
            for item in connection.cursor_instance.executed
            if "INSERT INTO instruments (instrument_id" in item[0]
        )
        new_instruments = json.loads(instrument_query[1][0])
        self.assertEqual([row["name"] for row in new_instruments], ["Garanti"])

        symbol_query = next(
            item
            for item in connection.cursor_instance.executed
            if "INSERT INTO instrument_symbols" in item[0]
        )
        symbol_rows = json.loads(symbol_query[1][0])
        self.assertEqual(
            {(row["provider"], row["symbol"]) for row in symbol_rows},
            {("canonical", "GARAN"), ("borsapy", "GARAN")},
        )


if __name__ == "__main__":
    unittest.main()
