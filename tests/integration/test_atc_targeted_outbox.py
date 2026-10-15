from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_intelligence.delivery.telegram.config import TelegramSettings
from market_intelligence.delivery.telegram.routing import PublicationKind, TopicRouter
from scripts.atc_publish_targeted import AtcOnlyOutbox, target_keys
from tests.test_telegram_routing import environment

ISTANBUL = ZoneInfo("Europe/Istanbul")


class TargetKeyTests(unittest.TestCase):
    def test_only_requested_morning_message_keys_are_derived(self):
        settings = TelegramSettings.from_mapping(environment())
        at = datetime(2026, 10, 15, 5, 30, tzinfo=ISTANBUL)
        with patch("scripts.atc_publish_targeted.last_closed_session",
                   return_value=datetime(2026, 10, 14).date()):
            keys = target_keys(settings, mode="morning", now=at)
        router = TopicRouter(settings)
        expected = tuple(router.route(
            publication_kind=PublicationKind.REPORT,
            semantic_identity={
                "source": "atc-bulletins-v1", "slot": "morning:2026-10-14",
                "part": i,
            },
            payload={},
        ).semantic_key for i in range(2))
        self.assertEqual(keys, expected)
        self.assertEqual(len(set(keys)), 2)
        with self.assertRaises(ValueError):
            target_keys(settings, mode="unknown", now=at)


    def test_preview_keys_target_verified_daily_thread_only(self):
        env = {
            **environment(),
            "TELEGRAM_CHAT_ID": "-1004439315048",
            "TELEGRAM_TOPIC_1D": "555",
            "ENABLE_TIMEFRAME_IMAGE_REPORTS": "true",
        }
        now = datetime(2026, 10, 15, 12, 45, tzinfo=ISTANBUL)
        with patch.dict(os.environ, env, clear=True):
            settings = TelegramSettings.from_mapping(env)
            keys = target_keys(settings, mode="preview", now=now)
            from market_intelligence.core.timeframes import Timeframe
            from market_intelligence.delivery.telegram.timeframe_topics import (
                route_timeframe_image,
            )
            from scripts.atc_timeframe_visuals import preview_visual_identity

            slot = now.replace(minute=0, second=0, microsecond=0)
            pictures = tuple(route_timeframe_image(
                settings, {Timeframe.D1: 555}, Timeframe.D1,
                identity=preview_visual_identity(slot, media),
                payload={},
            ).semantic_key for media in ("photo", "csv"))
            self.assertEqual(len(keys), 3)
            self.assertEqual(keys[1:], pictures)
            self.assertEqual(len(set(keys)), 3)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL required")
class TargetedOutboxIntegrationTests(unittest.TestCase):
    def test_older_pending_messages_are_never_claimed(self):
        import psycopg

        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as db:
            with db.transaction(force_rollback=True):
                db.execute(
                    "CREATE TEMP TABLE telegram_outbox "
                    "(outbox_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
                    "semantic_key text UNIQUE, publication_kind text, topic_kind text,"
                    "chat_id bigint, message_thread_id bigint, payload jsonb,"
                    "status text DEFAULT 'pending', attempt_count int DEFAULT 0,"
                    "available_at timestamptz DEFAULT now(),"
                    "created_at timestamptz DEFAULT now(),"
                    "locked_at timestamptz, lease_until timestamptz)"
                )
                from market_intelligence.persistence.postgres.outbox import (
                    PostgresOutboxRepository,
                )

                settings = TelegramSettings.from_mapping(environment())
                router = TopicRouter(settings)
                old = router.route(
                    publication_kind=PublicationKind.REPORT,
                    semantic_identity={"test": "unrelated-old"},
                    payload={"text": "OLD; NEVER SEND"},
                )
                current = tuple(router.route(
                    publication_kind=PublicationKind.REPORT,
                    semantic_identity={"test": "ATC morning", "part": i},
                    payload={"text": f"ATC {i}"},
                ) for i in range(2))
                regular = PostgresOutboxRepository(db)
                self.assertEqual(regular.enqueue((old, *current)), 3)
                # The unrelated old row has the earliest available_at.
                selector = AtcOnlyOutbox(db, [x.semantic_key for x in current])
                selected = selector.claim(limit=25, now=datetime.now(UTC) + timedelta(seconds=2))
                self.assertEqual({x.semantic_key for x in selected},
                                 {x.semantic_key for x in current})
                record = db.execute(
                    "SELECT status FROM telegram_outbox WHERE semantic_key=%s",
                    (old.semantic_key,),
                ).fetchone()
                self.assertEqual(record[0], "pending")
                self.assertEqual(len(selected), 2)


if __name__ == "__main__":
    unittest.main()
