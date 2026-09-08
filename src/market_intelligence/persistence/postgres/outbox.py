from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Protocol

from market_intelligence.core.identity import canonical_json
from market_intelligence.delivery.telegram.publisher import PendingTelegramMessage
from market_intelligence.delivery.telegram.routing import OutboxEnvelope
from market_intelligence.persistence.postgres.scan_store import OUTBOX_SQL


class Cursor(Protocol):
    def execute(self, query: str, params: tuple[Any, ...]) -> Any: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def __enter__(self) -> Cursor: ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...


class Connection(Protocol):
    def transaction(self): ...

    def cursor(self) -> Cursor: ...


CLAIM_SQL = """
WITH candidates AS (
    SELECT outbox_id
    FROM telegram_outbox
    WHERE (
        status IN ('pending', 'failed') AND available_at <= %s
    ) OR (
        status = 'processing' AND lease_until <= %s
    )
    ORDER BY available_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT %s
)
UPDATE telegram_outbox AS target
SET status = 'processing',
    attempt_count = target.attempt_count + 1,
    locked_at = %s,
    lease_until = %s
FROM candidates
WHERE target.outbox_id = candidates.outbox_id
RETURNING
    target.outbox_id, target.semantic_key, target.chat_id,
    target.message_thread_id, target.payload, target.attempt_count
"""

MARK_SENT_SQL = """
UPDATE telegram_outbox
SET status = 'sent', telegram_message_id = %s, sent_at = %s,
    locked_at = NULL, lease_until = NULL, last_error = NULL
WHERE outbox_id = %s AND status = 'processing'
"""

MARK_FAILED_SQL = """
UPDATE telegram_outbox
SET status = 'failed', available_at = %s, last_error = %s,
    locked_at = NULL, lease_until = NULL
WHERE outbox_id = %s AND status = 'processing'
"""


class PostgresOutboxRepository:
    def __init__(self, connection: Connection, *, lease_minutes: int = 5) -> None:
        self.connection = connection
        self.lease_minutes = lease_minutes

    def enqueue(self, envelopes: tuple[OutboxEnvelope, ...]) -> int:
        inserted = 0
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
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
                    inserted += int(cursor.fetchone() is not None)
        return inserted

    def claim(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> tuple[PendingTelegramMessage, ...]:
        lease_until = now + timedelta(minutes=self.lease_minutes)
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(CLAIM_SQL, (now, now, limit, now, lease_until))
                rows = cursor.fetchall()
        messages = []
        for outbox_id, semantic_key, chat_id, thread_id, raw_payload, attempts in rows:
            payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
            message = payload.get("message", payload)
            messages.append(
                PendingTelegramMessage(
                    outbox_id=str(outbox_id),
                    semantic_key=str(semantic_key),
                    chat_id=int(chat_id),
                    message_thread_id=int(thread_id),
                    payload=dict(message),
                    attempt_count=int(attempts),
                )
            )
        return tuple(messages)

    def mark_sent(self, *, outbox_id: str, message_id: int, sent_at: datetime) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(MARK_SENT_SQL, (message_id, sent_at, outbox_id))

    def mark_failed(self, *, outbox_id: str, error: str, retry_at: datetime) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(MARK_FAILED_SQL, (retry_at, error, outbox_id))
