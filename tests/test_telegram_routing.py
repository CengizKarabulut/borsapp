from __future__ import annotations

import unittest

from market_intelligence.delivery.telegram.config import TelegramSettings, TopicKind
from market_intelligence.delivery.telegram.routing import PublicationKind, TopicRouter


def environment() -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "-100123",
        "TELEGRAM_ALLOWED_USERS": "42, 84",
        "TELEGRAM_TOPIC_COMMAND": "10",
        "TELEGRAM_TOPIC_SCANS": "20",
        "TELEGRAM_TOPIC_ANALYSIS": "30",
        "TELEGRAM_TOPIC_CHARTS": "40",
        "TELEGRAM_TOPIC_NEWS": "50",
        "TELEGRAM_TOPIC_CALENDAR": "60",
        "TELEGRAM_TOPIC_REPORTS": "70",
        "TELEGRAM_TOPIC_SYSTEM": "80",
    }


class TelegramSettingsTests(unittest.TestCase):
    def test_commands_are_restricted_to_chat_and_user_but_accept_any_topic(self) -> None:
        settings = TelegramSettings.from_mapping(environment())
        self.assertTrue(settings.accepts(chat_id=-100123, user_id=42, topic_id=10))
        self.assertFalse(settings.accepts(chat_id=-100123, user_id=99, topic_id=10))
        self.assertTrue(settings.accepts(chat_id=-100123, user_id=42, topic_id=20))
        self.assertTrue(settings.accepts(chat_id=-100123, user_id=42, topic_id=None))

    def test_all_topics_are_required(self) -> None:
        values = environment()
        del values["TELEGRAM_TOPIC_SYSTEM"]
        with self.assertRaisesRegex(ValueError, "TELEGRAM_TOPIC_SYSTEM"):
            TelegramSettings.from_mapping(values)

    def test_chat_admin_authorization_is_explicitly_enabled(self) -> None:
        values = environment()
        values["TELEGRAM_ALLOW_CHAT_ADMINS"] = "true"
        settings = TelegramSettings.from_mapping(values)
        self.assertTrue(settings.allow_chat_admins)

    def test_configured_chat_members_can_be_explicitly_authorized(self) -> None:
        values = environment()
        values["TELEGRAM_ALLOW_CHAT_MEMBERS"] = "true"
        settings = TelegramSettings.from_mapping(values)

        self.assertTrue(settings.accepts(chat_id=-100123, user_id=999, topic_id=20))
        self.assertFalse(settings.accepts(chat_id=-100999, user_id=999, topic_id=20))


class TopicRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = TopicRouter(TelegramSettings.from_mapping(environment()))

    def test_scheduled_scan_goes_to_combined_scans_topic(self) -> None:
        envelope = self.router.route(
            publication_kind=PublicationKind.SCAN_EVENT,
            semantic_identity={"event_id": "event-1"},
            payload={"text": "[TECHNICAL] TEST"},
        )
        self.assertEqual(envelope.topic_kind, TopicKind.SCANS)
        self.assertEqual(envelope.message_thread_id, 20)

    def test_command_reply_stays_in_origin_topic(self) -> None:
        envelope = self.router.route(
            publication_kind=PublicationKind.COMMAND_REPLY,
            semantic_identity={"command_id": "command-1"},
            payload={"text": "Hazır"},
            origin_topic_id=10,
        )
        self.assertEqual(envelope.message_thread_id, 10)

    def test_command_reply_can_be_routed_to_semantic_topic(self) -> None:
        envelope = self.router.route(
            publication_kind=PublicationKind.COMMAND_REPLY,
            semantic_identity={"command_id": "command-2"},
            payload={"text": "Tarama hazır"},
            origin_topic_id=10,
            reply_topic_kind=TopicKind.SCANS,
        )
        self.assertEqual(envelope.topic_kind, TopicKind.SCANS)
        self.assertEqual(envelope.message_thread_id, 20)

    def test_semantic_key_is_stable_and_payload_independent(self) -> None:
        first = self.router.route(
            publication_kind=PublicationKind.NEWS,
            semantic_identity={"news_id": "kap-1"},
            payload={"text": "ilk biçim"},
        )
        second = self.router.route(
            publication_kind=PublicationKind.NEWS,
            semantic_identity={"news_id": "kap-1"},
            payload={"text": "yeniden biçimlendirildi"},
        )
        self.assertEqual(first.semantic_key, second.semantic_key)


if __name__ == "__main__":
    unittest.main()
