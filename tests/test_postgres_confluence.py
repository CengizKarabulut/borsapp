from __future__ import annotations

import unittest
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from market_intelligence.confluence.engine import ConfluenceMode, ConfluenceReport
from market_intelligence.core.enums import Direction
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.delivery.telegram.config import TopicKind
from market_intelligence.delivery.telegram.routing import OutboxEnvelope, PublicationKind
from market_intelligence.persistence.postgres.confluence import PostgresConfluenceStore


class FakeTransaction(AbstractContextManager):
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.connection.committed += int(exc_type is None)
        self.connection.rolled_back += int(exc_type is not None)


class FakeCursor(AbstractContextManager):
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.connection.queries.append((query, params))
        if "telegram_outbox" in query and self.connection.fail_outbox:
            raise RuntimeError("outbox unavailable")

    def fetchone(self):
        return ("outbox-1",)


class FakeConnection:
    def __init__(self, *, fail_outbox: bool = False) -> None:
        self.fail_outbox = fail_outbox
        self.queries = []
        self.committed = 0
        self.rolled_back = 0

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def report() -> ConfluenceReport:
    return ConfluenceReport(
        instrument_id="instrument-1",
        symbol="ASELS",
        mode=ConfluenceMode.STRICT,
        reference_time=datetime(2026, 9, 7, 12, tzinfo=UTC),
        reference_timeframe=Timeframe.H1,
        families=("signal", "technical"),
        scanner_ids=("signal.test", "technical.test"),
        directions=(Direction.BULLISH,),
        direction_conflict=False,
        unknown_families=("ma",),
        no_match_families=(),
        qualifies=True,
    )


def envelope() -> OutboxEnvelope:
    return OutboxEnvelope(
        semantic_key="confluence-1",
        publication_kind=PublicationKind.CONFLUENCE,
        topic_kind=TopicKind.SCANS,
        chat_id=-100123,
        message_thread_id=11,
        payload={"text": "[CONFLUENCE] ASELS"},
    )


class PostgresConfluenceStoreTests(unittest.TestCase):
    def test_report_and_outbox_commit_together(self) -> None:
        connection = FakeConnection()

        persisted = PostgresConfluenceStore(connection).persist(
            cycle_id="00000000-0000-0000-0000-000000000001",
            report=report(),
            evaluated_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
            envelope=envelope(),
        )

        self.assertEqual(persisted.outbox_count, 1)
        self.assertEqual(len(persisted.report_id), 64)
        self.assertEqual(len(connection.queries), 2)
        self.assertEqual(connection.committed, 1)

    def test_outbox_failure_rolls_back_report(self) -> None:
        connection = FakeConnection(fail_outbox=True)

        with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
            PostgresConfluenceStore(connection).persist(
                cycle_id="00000000-0000-0000-0000-000000000001",
                report=report(),
                evaluated_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
                envelope=envelope(),
            )

        self.assertEqual(connection.committed, 0)
        self.assertEqual(connection.rolled_back, 1)


if __name__ == "__main__":
    unittest.main()
