from __future__ import annotations

import unittest
from typing import Any

from market_intelligence.delivery.telegram.config import TopicKind
from market_intelligence.delivery.telegram.routing import OutboxEnvelope, PublicationKind
from market_intelligence.features.volume import RELATIVE_VOLUME_20, calculate_volume_activity
from market_intelligence.persistence.postgres.scan_store import PostgresScanStore
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.technical.volume_spike import (
    TechnicalVolumeSpikeScanner,
    VolumeSpikeConfig,
)
from tests.test_volume_spike import context, frame


class FakeTransaction:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeTransaction:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is None:
            self.connection.committed = True
        else:
            self.connection.rolled_back = True


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.next_row: tuple[str] | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.connection.queries.append((query, params))
        if "scan_evaluations" in query:
            self.next_row = ("evaluation-1",)
        elif "scan_events" in query:
            self.next_row = ("event-1",)
        elif "telegram_outbox" in query and self.connection.fail_outbox:
            raise RuntimeError("outbox unavailable")
        elif "telegram_outbox" in query:
            self.next_row = ("outbox-1",)

    def fetchone(self) -> tuple[str] | None:
        row = self.next_row
        self.next_row = None
        return row


class FakeConnection:
    def __init__(self, *, fail_outbox: bool = False) -> None:
        self.fail_outbox = fail_outbox
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.committed = False
        self.rolled_back = False

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def matched_run():
    source = frame()
    activity = calculate_volume_activity(source)
    scanner = TechnicalVolumeSpikeScanner(
        VolumeSpikeConfig(minimum_average_turnover=0.0)
    )
    return ScannerEngine().run(
        cycle_id="00000000-0000-0000-0000-000000000001",
        frame=source,
        scanner=scanner,
        context=context(source, {RELATIVE_VOLUME_20.feature_id: activity}),
    )


def envelope() -> OutboxEnvelope:
    return OutboxEnvelope(
        semantic_key="semantic-1",
        publication_kind=PublicationKind.SCAN_EVENT,
        topic_kind=TopicKind.SCANS,
        chat_id=-100123,
        message_thread_id=20,
        payload={"text": "[TECHNICAL] TEST"},
    )


class PostgresScanStoreTests(unittest.TestCase):
    def test_event_and_outbox_commit_together(self) -> None:
        connection = FakeConnection()
        persisted = PostgresScanStore(connection).persist_event_run(
            matched_run(),
            {"volume-spike": envelope()},
        )
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertEqual(persisted.event_ids, ("event-1",))
        self.assertEqual(persisted.outbox_count, 1)

    def test_outbox_failure_rolls_back_scan_event(self) -> None:
        connection = FakeConnection(fail_outbox=True)
        with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
            PostgresScanStore(connection).persist_event_run(
                matched_run(),
                {"volume-spike": envelope()},
            )
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)

    def test_orphan_outbox_is_rejected_before_transaction(self) -> None:
        connection = FakeConnection()
        with self.assertRaisesRegex(ValueError, "Finding olmadan"):
            PostgresScanStore(connection).persist_event_run(
                matched_run(),
                {"not-a-finding": envelope()},
            )
        self.assertEqual(connection.queries, [])


if __name__ == "__main__":
    unittest.main()
