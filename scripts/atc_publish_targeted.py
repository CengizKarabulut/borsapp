"""Publish only the ATC bulletin(s) from this scheduled slot, not old backlog.

This is a restricted adapter around the existing PostgreSQL outbox and Telegram
publisher. It never claims, retries, or sends unrelated queued messages.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.delivery.telegram.config import TelegramSettings
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.delivery.telegram.publisher import (
    PendingTelegramMessage,
    TelegramPublisher,
)
from market_intelligence.delivery.telegram.routing import PublicationKind, TopicRouter
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_telegram_briefings import last_closed_session

ISTANBUL = ZoneInfo("Europe/Istanbul")

TARGET_CLAIM_SQL = """
WITH candidates AS (
    SELECT outbox_id FROM telegram_outbox
    WHERE semantic_key = ANY(%s::text[])
      AND ((status IN ('pending', 'failed') AND available_at <= %s)
        OR (status = 'processing' AND lease_until <= %s))
    ORDER BY available_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT %s
), updated AS (
    UPDATE telegram_outbox AS target
    SET status='processing', attempt_count=attempt_count + 1,
        locked_at=%s, lease_until=%s
    FROM candidates
    WHERE target.outbox_id=candidates.outbox_id
    RETURNING target.outbox_id, target.semantic_key, target.chat_id,
              target.message_thread_id, target.payload, target.attempt_count,
              target.available_at
)
SELECT outbox_id, semantic_key, chat_id, message_thread_id, payload, attempt_count
FROM updated ORDER BY available_at, outbox_id
"""


class AtcOnlyOutbox(PostgresOutboxRepository):
    def __init__(self, connection, semantic_keys):
        super().__init__(connection)
        self.semantic_keys = tuple(semantic_keys)
        if not self.semantic_keys:
            raise ValueError("At least one ATC semantic identity is required")

    def claim(self, *, limit, now):
        lease_until = now + timedelta(minutes=self.lease_minutes)
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    TARGET_CLAIM_SQL,
                    (list(self.semantic_keys), now, now, limit, now, lease_until),
                )
                rows = cursor.fetchall()
        results = []
        for outbox_id, semantic_key, chat_id, thread_id, raw, attempts in rows:
            record = json.loads(raw) if isinstance(raw, str) else raw
            payload = record.get("message", record)
            results.append(PendingTelegramMessage(
                outbox_id=str(outbox_id),
                semantic_key=str(semantic_key),
                chat_id=int(chat_id),
                message_thread_id=int(thread_id),
                payload=dict(payload),
                attempt_count=int(attempts),
            ))
        return tuple(results)


def target_keys(settings, *, mode: str, now):
    router = TopicRouter(settings)
    if mode == "morning":
        previous = last_closed_session(ExchangeCalendarsXist(), now.date())
        slot, kind, count = f"morning:{previous}", PublicationKind.REPORT, 2
    elif mode == "eod":
        slot, kind, count = f"eod:{now.date()}", PublicationKind.REPORT, 1
    elif mode == "preview":
        hour = now.replace(minute=0, second=0, microsecond=0)
        slot, kind, count = f"preview:{hour.isoformat()}", PublicationKind.SCAN_EVENT, 1
    else:
        raise ValueError("Unknown ATC Telegram report mode")
    return tuple(router.route(
        publication_kind=kind,
        semantic_identity={"source": "atc-bulletins-v1", "slot": slot, "part": index},
        payload={},
    ).semantic_key for index in range(count))


def publish(mode: str, *, now=None):
    now = now or datetime.now(ISTANBUL)
    settings = TelegramSettings.from_mapping({**os.environ, "DELIVERY_MODE": "live"})
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise ValueError("DATABASE_URL secret required")
    import psycopg

    keys = target_keys(settings, mode=mode, now=now)
    with psycopg.connect(database_url) as connection:
        repository = AtcOnlyOutbox(connection, keys)
        publisher = TelegramPublisher(
            settings=settings, repository=repository,
            transport=HttpxTelegramTransport(settings.bot_token),
        )
        result = publisher.publish_batch(now=now, limit=len(keys))
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT semantic_key, status FROM telegram_outbox "
                "WHERE semantic_key=ANY(%s::text[])",
                (list(keys),),
            )
            states = {str(key): str(status) for key, status in cursor.fetchall()}
    print(
        f"ATC targeted Telegram mode={mode}: claimed={result.claimed}, "
        f"sent={result.sent}, failed={result.failed}, "
        f"outbox_states={sorted(states.values())}",
        flush=True,
    )
    for message in result.error_samples:
        print("Telegram send error:", message, flush=True)
    if len(states) != len(keys) or any(states.get(key) != "sent" for key in keys):
        raise RuntimeError(
            f"Targeted ATC bulletin not fully delivered: "
            f"{len(states)}/{len(keys)} tracked, "
            f"states={sorted(states.values())}"
        )
    return result.sent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["morning", "preview", "eod"])
    args = parser.parse_args()
    publish(args.mode)


if __name__ == "__main__":
    main()
