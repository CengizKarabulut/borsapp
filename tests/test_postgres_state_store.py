from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.delivery.telegram.config import TopicKind
from market_intelligence.delivery.telegram.routing import OutboxEnvelope, PublicationKind
from market_intelligence.features.ma import QUALIFIED_MA_PROXIMITY, MaProximitySnapshot
from market_intelligence.persistence.postgres.state_store import PostgresStateStore
from market_intelligence.scanning.engine import ScannerEngine, ScanRun
from market_intelligence.scanning.ma.near_zone import MaNearZoneScanner
from tests.test_ma_near_zone import level
from tests.test_volume_spike import context, frame

ISTANBUL = ZoneInfo("Europe/Istanbul")


class FakeTransaction:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.connection.committed = exc_type is None
        self.connection.rolled_back = exc_type is not None


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.next_row: tuple[Any, ...] | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.connection.queries.append((query, params))
        if "INSERT INTO scan_evaluations" in query:
            self.next_row = ("evaluation-1",)
        elif "SELECT\n    state_id" in query:
            self.connection.fetchall_result = list(self.connection.previous_rows)
        elif "INSERT INTO active_states" in query:
            self.next_row = ("state-1",)
        elif "INSERT INTO state_transitions" in query:
            self.connection.transition_counter += 1
            self.next_row = (f"transition-{self.connection.transition_counter}",)
        elif "INSERT INTO telegram_outbox" in query:
            self.next_row = ("outbox-1",)

    def fetchone(self):
        row = self.next_row
        self.next_row = None
        return row

    def fetchall(self):
        rows = self.connection.fetchall_result
        self.connection.fetchall_result = []
        return rows


class FakeConnection:
    def __init__(self, previous_rows: list[tuple[Any, ...]] | None = None) -> None:
        self.previous_rows = previous_rows or []
        self.fetchall_result: list[tuple[Any, ...]] = []
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.transition_counter = 0
        self.committed = False
        self.rolled_back = False

    def transaction(self):
        return FakeTransaction(self)

    def cursor(self):
        return FakeCursor(self)


def matched_run() -> ScanRun:
    source = frame()
    scan_context = replace(
        context(source),
        feature_values={
            QUALIFIED_MA_PROXIMITY.feature_id: MaProximitySnapshot(
                current_price=100,
                atr=2,
                levels=(level("EMA", 55, "support", -0.4, 82),),
                research_version="research-v1",
            )
        },
        declared_dependencies={
            "next_bar_close_time": source.through_bar_time + timedelta(hours=1)
        },
    )
    return ScannerEngine().run(
        cycle_id="00000000-0000-0000-0000-000000000001",
        frame=source,
        scanner=MaNearZoneScanner(),
        context=scan_context,
    )


def envelope(state_key: str) -> OutboxEnvelope:
    return OutboxEnvelope(
        semantic_key=f"semantic:{state_key}",
        publication_kind=PublicationKind.SCAN_EVENT,
        topic_kind=TopicKind.SCANS,
        chat_id=-100123,
        message_thread_id=20,
        payload={"text": f"[MA] {state_key}"},
    )


class PostgresStateStoreTests(unittest.TestCase):
    def test_enter_transitions_and_notifications_are_atomic(self) -> None:
        run = matched_run()
        envelopes = {
            str(finding.state_key): envelope(str(finding.state_key))
            for finding in run.findings
        }
        connection = FakeConnection()

        result = PostgresStateStore(connection).persist_state_run(run, envelopes)

        self.assertTrue(connection.committed)
        self.assertEqual(len(result.state_ids), len(run.findings))
        self.assertEqual(len(result.transition_ids), len(run.findings))
        self.assertEqual(result.outbox_count, len(run.findings))

    def test_unknown_increments_existing_state_without_notification(self) -> None:
        run = matched_run()
        evaluation = run.evaluation
        unknown_run = ScanRun(
            replace(
                evaluation,
                status=EvaluationStatus.UNKNOWN,
                finding_count=0,
                error_code="missing_features",
            ),
            (),
        )
        previous = [
            (
                "state-1",
                "EMA:55:support",
                "active",
                0,
                evaluation.scanner_version,
                evaluation.ruleset_hash,
                datetime(2026, 9, 7, 14, 0, tzinfo=ISTANBUL),
                None,
                {"distance_atr": 0.2},
            )
        ]
        connection = FakeConnection(previous)

        result = PostgresStateStore(connection).persist_state_run(unknown_run)

        self.assertEqual(result.outbox_count, 0)
        transition_queries = [
            params
            for query, params in connection.queries
            if "INSERT INTO state_transitions" in query
        ]
        self.assertEqual(transition_queries[0][7], "unknown")


if __name__ == "__main__":
    unittest.main()
