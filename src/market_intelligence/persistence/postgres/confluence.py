from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from market_intelligence.confluence.engine import ConfluenceReport
from market_intelligence.core.identity import canonical_json, stable_hash
from market_intelligence.delivery.telegram.routing import OutboxEnvelope
from market_intelligence.persistence.postgres.scan_store import (
    OUTBOX_SQL,
    PostgresConnection,
)

UPSERT_REPORT_SQL = """
INSERT INTO confluence_reports (
    report_id, cycle_id, instrument_id, symbol_at_report, mode,
    reference_time, reference_timeframe, families, scanner_ids, directions,
    direction_conflict, unknown_families, no_match_families, qualifies,
    evaluated_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
    %s, %s::jsonb, %s::jsonb, %s, %s
)
ON CONFLICT (report_id) DO UPDATE SET
    cycle_id = EXCLUDED.cycle_id,
    families = EXCLUDED.families,
    scanner_ids = EXCLUDED.scanner_ids,
    directions = EXCLUDED.directions,
    direction_conflict = EXCLUDED.direction_conflict,
    unknown_families = EXCLUDED.unknown_families,
    no_match_families = EXCLUDED.no_match_families,
    qualifies = EXCLUDED.qualifies,
    evaluated_at = EXCLUDED.evaluated_at
"""


@dataclass(frozen=True)
class PersistedConfluence:
    report_id: str
    outbox_count: int


class PostgresConfluenceStore:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def persist(
        self,
        *,
        cycle_id: str,
        report: ConfluenceReport,
        evaluated_at: datetime,
        envelope: OutboxEnvelope | None = None,
    ) -> PersistedConfluence:
        report_id = stable_hash(
            {
                "instrument_id": report.instrument_id,
                "mode": report.mode,
                "reference_time": report.reference_time,
                "reference_timeframe": report.reference_timeframe,
            }
        )
        outbox_count = 0
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    UPSERT_REPORT_SQL,
                    (
                        report_id,
                        cycle_id,
                        report.instrument_id,
                        report.symbol,
                        report.mode.value,
                        report.reference_time,
                        report.reference_timeframe.value
                        if report.reference_timeframe
                        else None,
                        canonical_json(report.families),
                        canonical_json(report.scanner_ids),
                        canonical_json(tuple(value.value for value in report.directions)),
                        report.direction_conflict,
                        canonical_json(report.unknown_families),
                        canonical_json(report.no_match_families),
                        report.qualifies,
                        evaluated_at,
                    ),
                )
                if envelope is not None:
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
                    outbox_count = int(cursor.fetchone() is not None)
        return PersistedConfluence(report_id, outbox_count)
