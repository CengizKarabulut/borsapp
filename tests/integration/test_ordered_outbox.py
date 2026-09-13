import os
import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.delivery.telegram.routing import PublicationKind, TopicRouter
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository
from market_intelligence.settings import ApplicationSettings
from tests.test_telegram_routing import environment


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is not set")
class OrderedOutboxTests(unittest.TestCase):
    def test_order_and_retry_deduplication(self):
        import psycopg

        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as c:
            with c.transaction(force_rollback=True):
                c.execute(
                    "CREATE TEMP TABLE telegram_outbox (outbox_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), semantic_key text UNIQUE, publication_kind text, topic_kind text, chat_id bigint, message_thread_id bigint, payload jsonb, status text DEFAULT 'pending', attempt_count int DEFAULT 0, available_at timestamptz DEFAULT now(), created_at timestamptz DEFAULT now(), locked_at timestamptz, lease_until timestamptz)"
                )
                router = TopicRouter(ApplicationSettings.from_mapping(environment()).telegram)
                envelopes = tuple(
                    router.route(
                        publication_kind=PublicationKind.SCAN_EVENT,
                        semantic_identity={"test": "ordered", "page": i},
                        payload={"text": str(i)},
                    )
                    for i in range(5)
                )
                repository = PostgresOutboxRepository(c)
                self.assertEqual(repository.enqueue(envelopes, ordered=True), 5)
                self.assertEqual(repository.enqueue(envelopes, ordered=True), 0)
                claimed = repository.claim(limit=10, now=datetime.now(UTC) + timedelta(minutes=1))
                self.assertEqual(
                    [v.semantic_key for v in claimed], [e.semantic_key for e in envelopes]
                )
