from __future__ import annotations

from typing import Any

from market_intelligence.core.identity import canonical_json
from market_intelligence.delivery.telegram.routing import OutboxEnvelope
from market_intelligence.persistence.postgres.scan_store import OUTBOX_SQL, PostgresConnection

CONSUMER_KEY = "telegram.commands.v1"

NEXT_OFFSET_SQL = """
SELECT last_update_id + 1
FROM telegram_consumers
WHERE consumer_key = %s
"""

CHECKPOINT_SQL = """
INSERT INTO telegram_consumers (consumer_key, last_update_id)
VALUES (%s, %s)
ON CONFLICT (consumer_key)
DO UPDATE SET
    last_update_id = GREATEST(telegram_consumers.last_update_id, EXCLUDED.last_update_id),
    updated_at = now()
"""

TRY_LOCK_SQL = "SELECT pg_try_advisory_lock(hashtext(%s))"
UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtext(%s))"


class PostgresTelegramUpdateRepository:
    """Checkpoint Telegram updates together with their command reply outbox row."""

    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def next_offset(self) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(NEXT_OFFSET_SQL, (CONSUMER_KEY,))
            row = cursor.fetchone()
        return int(row[0]) if row else 0

    def acquire_listener_lock(self) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(TRY_LOCK_SQL, (CONSUMER_KEY,))
            row = cursor.fetchone()
        return bool(row and row[0])

    def release_listener_lock(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(UNLOCK_SQL, (CONSUMER_KEY,))

    def commit_update(
        self,
        *,
        update_id: int,
        envelope: OutboxEnvelope | None,
    ) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                if envelope is not None:
                    payload: dict[str, Any] = {
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
                    cursor.fetchone()
                cursor.execute(CHECKPOINT_SQL, (CONSUMER_KEY, update_id))
