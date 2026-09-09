from __future__ import annotations

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from market_intelligence.application.command_jobs import CommandArtifact, CommandJob
from market_intelligence.core.identity import canonical_json
from market_intelligence.delivery.telegram.commands import CommandName
from market_intelligence.delivery.telegram.routing import OutboxEnvelope
from market_intelligence.persistence.postgres.scan_store import (
    OUTBOX_SQL,
    PostgresConnection,
)

CLAIM_JOB_SQL = """
WITH candidate AS (
    SELECT job_id
    FROM command_jobs
    WHERE status = 'pending'
       OR (status = 'running' AND lease_until <= %s)
    ORDER BY requested_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE command_jobs target
SET status = 'running',
    attempt_count = target.attempt_count + 1,
    started_at = %s,
    lease_until = %s,
    error_detail = NULL
FROM candidate
WHERE target.job_id = candidate.job_id
RETURNING target.job_id, target.command_name, target.symbol_at_request,
          target.requested_by, target.requested_topic, target.attempt_count,
          target.instrument_id
"""

FINISH_JOB_SQL = """
UPDATE command_jobs
SET status = %s, finished_at = %s, lease_until = NULL, error_detail = %s
WHERE job_id = %s AND status = 'running'
"""

INSERT_ARTIFACT_SQL = """
INSERT INTO research_artifacts (
    artifact_id, instrument_id, artifact_kind, timeframe, bar_time,
    summary, storage_uri, content_hash, created_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (artifact_id)
DO UPDATE SET
    summary = EXCLUDED.summary,
    storage_uri = EXCLUDED.storage_uri,
    content_hash = EXCLUDED.content_hash,
    created_at = EXCLUDED.created_at
"""


class PostgresCommandJobRepository:
    def __init__(self, connection: PostgresConnection, *, lease_minutes: int = 15) -> None:
        self.connection = connection
        self.lease_minutes = lease_minutes

    def claim(self, *, now: datetime) -> CommandJob | None:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    CLAIM_JOB_SQL,
                    (now, now, now + timedelta(minutes=self.lease_minutes)),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return CommandJob(
            job_id=str(row[0]),
            command=CommandName(str(row[1])),
            symbol=str(row[2]).upper(),
            requested_by=int(row[3]),
            requested_topic=int(row[4]),
            attempt_count=int(row[5]),
            instrument_id=str(row[6]),
        )

    def finish(
        self,
        *,
        job: CommandJob,
        finished_at: datetime,
        error_detail: str | None,
        envelopes: tuple[OutboxEnvelope, ...],
        artifact: CommandArtifact | None,
    ) -> None:
        status = "completed" if error_detail is None else "failed"
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    FINISH_JOB_SQL,
                    (status, finished_at, error_detail, job.job_id),
                )
                if artifact is not None and error_detail is None:
                    cursor.execute(
                        INSERT_ARTIFACT_SQL,
                        (
                            str(uuid5(NAMESPACE_URL, artifact.report_id)),
                            artifact.instrument_id,
                            artifact.artifact_kind,
                            artifact.timeframe,
                            artifact.bar_time,
                            artifact.summary,
                            artifact.storage_uri,
                            artifact.content_hash,
                            finished_at,
                        ),
                    )
                for envelope in envelopes:
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
