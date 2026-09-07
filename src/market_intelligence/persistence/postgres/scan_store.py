from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from market_intelligence.core.identity import canonical_json
from market_intelligence.delivery.telegram.routing import OutboxEnvelope
from market_intelligence.scanning.engine import ScanRun


class Cursor(Protocol):
    def execute(self, query: str, params: Sequence[Any]) -> Any: ...

    def fetchone(self) -> Sequence[Any] | None: ...

    def __enter__(self) -> Cursor: ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...


class PostgresConnection(Protocol):
    def transaction(self) -> AbstractContextManager[Any]: ...

    def cursor(self) -> Cursor: ...


@dataclass(frozen=True)
class PersistedScan:
    evaluation_id: str
    event_ids: tuple[str, ...]
    outbox_count: int


EVALUATION_SQL = """
INSERT INTO scan_evaluations (
    cycle_id, instrument_id, symbol_at_evaluation, timeframe, bar_time,
    scanner_id, scanner_version, ruleset_hash, snapshot_id, status,
    finding_count, error_code, error_detail
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (
    instrument_id, scanner_id, scanner_version, ruleset_hash, snapshot_id
) DO UPDATE SET
    cycle_id = EXCLUDED.cycle_id,
    status = EXCLUDED.status,
    finding_count = EXCLUDED.finding_count,
    error_code = EXCLUDED.error_code,
    error_detail = EXCLUDED.error_detail
RETURNING evaluation_id
"""

EVENT_SQL = """
INSERT INTO scan_events (
    evaluation_id, instrument_id, symbol_at_event, scanner_id, finding_key,
    timeframe, bar_time, direction, metrics, evidence
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
ON CONFLICT (instrument_id, scanner_id, finding_key, timeframe, bar_time)
DO UPDATE SET
    evaluation_id = EXCLUDED.evaluation_id,
    direction = EXCLUDED.direction,
    metrics = EXCLUDED.metrics,
    evidence = EXCLUDED.evidence
RETURNING event_id
"""

OUTBOX_SQL = """
INSERT INTO telegram_outbox (
    semantic_key, publication_kind, topic_kind, chat_id, message_thread_id, payload
)
VALUES (%s, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (semantic_key) DO NOTHING
RETURNING outbox_id
"""


class PostgresScanStore:
    """Persist evaluation, events and their notifications atomically."""

    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def persist_event_run(
        self,
        run: ScanRun,
        envelopes: Mapping[str, OutboxEnvelope] | None = None,
    ) -> PersistedScan:
        envelope_map = dict(envelopes or {})
        finding_keys = {finding.finding_key for finding in run.findings}
        unknown_envelopes = set(envelope_map) - finding_keys
        if unknown_envelopes:
            raise ValueError(
                "Finding olmadan outbox kaydı oluşturulamaz: "
                + ", ".join(sorted(unknown_envelopes))
            )

        evaluation = run.evaluation
        event_ids: list[str] = []
        outbox_count = 0
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    EVALUATION_SQL,
                    (
                        evaluation.cycle_id,
                        evaluation.instrument_id,
                        evaluation.symbol_at_evaluation,
                        evaluation.timeframe.value,
                        evaluation.bar_time,
                        evaluation.scanner_id,
                        evaluation.scanner_version,
                        evaluation.ruleset_hash,
                        evaluation.snapshot_id,
                        evaluation.status.value,
                        evaluation.finding_count,
                        evaluation.error_code,
                        evaluation.error_detail,
                    ),
                )
                evaluation_row = cursor.fetchone()
                if not evaluation_row:
                    raise RuntimeError("scan_evaluations evaluation_id döndürmedi")
                evaluation_id = str(evaluation_row[0])

                for finding in run.findings:
                    cursor.execute(
                        EVENT_SQL,
                        (
                            evaluation_id,
                            finding.instrument_id,
                            finding.symbol_at_event,
                            finding.scanner_id,
                            finding.finding_key,
                            finding.timeframe.value,
                            finding.bar_time,
                            finding.direction.value,
                            canonical_json(dict(finding.metrics)),
                            canonical_json(list(finding.evidence)),
                        ),
                    )
                    event_row = cursor.fetchone()
                    if not event_row:
                        raise RuntimeError("scan_events event_id döndürmedi")
                    event_ids.append(str(event_row[0]))

                    envelope = envelope_map.get(finding.finding_key)
                    if envelope is None:
                        continue
                    payload = {
                        "publication_kind": envelope.publication_kind.value,
                        "chat_id": envelope.chat_id,
                        "message_thread_id": envelope.message_thread_id,
                        "message": envelope.payload,
                    }
                    cursor.execute(
                        OUTBOX_SQL,
                        (
                            envelope.semantic_key,
                            envelope.publication_kind.value,
                            envelope.topic_kind.value,
                            envelope.chat_id,
                            envelope.message_thread_id,
                            canonical_json(payload),
                        ),
                    )
                    if cursor.fetchone():
                        outbox_count += 1
        return PersistedScan(evaluation_id, tuple(event_ids), outbox_count)
