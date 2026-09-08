from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime

from market_intelligence.delivery.telegram.commands import (
    CommandName,
    TelegramCommandParser,
)
from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings
from market_intelligence.delivery.telegram.publisher import (
    PendingTelegramMessage,
    TelegramPublisher,
)
from tests.test_telegram_routing import environment


class FakeOutbox:
    def __init__(self, messages=()) -> None:
        self.messages = tuple(messages)
        self.claims = 0
        self.sent: list[tuple[str, int]] = []
        self.failed: list[tuple[str, str]] = []

    def claim(self, *, limit: int, now: datetime):
        self.claims += 1
        return self.messages[:limit]

    def mark_sent(self, *, outbox_id: str, message_id: int, sent_at: datetime) -> None:
        self.sent.append((outbox_id, message_id))

    def mark_failed(self, *, outbox_id: str, error: str, retry_at: datetime) -> None:
        self.failed.append((outbox_id, error))


class FakeTransport:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def send(self, *, chat_id: int, message_thread_id: int, payload: dict) -> int:
        self.calls += 1
        if self.error:
            raise self.error
        return 1234


def message() -> PendingTelegramMessage:
    return PendingTelegramMessage(
        outbox_id="outbox-1",
        semantic_key="semantic-1",
        chat_id=-100123,
        message_thread_id=20,
        payload={"text": "test"},
        attempt_count=1,
    )


class TelegramPublisherTests(unittest.TestCase):
    def test_disabled_mode_never_claims_or_sends(self) -> None:
        settings = TelegramSettings.from_mapping(environment())
        repository = FakeOutbox((message(),))
        transport = FakeTransport()
        result = TelegramPublisher(
            settings=settings,
            repository=repository,
            transport=transport,
        ).publish_batch(now=datetime.now(UTC))
        self.assertEqual(result.skipped_mode, DeliveryMode.DISABLED)
        self.assertEqual(repository.claims, 0)
        self.assertEqual(transport.calls, 0)

    def test_live_mode_marks_success(self) -> None:
        settings = replace(
            TelegramSettings.from_mapping(environment()),
            delivery_mode=DeliveryMode.LIVE,
        )
        repository = FakeOutbox((message(),))
        result = TelegramPublisher(
            settings=settings,
            repository=repository,
            transport=FakeTransport(),
        ).publish_batch(now=datetime.now(UTC))
        self.assertEqual((result.sent, result.failed), (1, 0))
        self.assertEqual(repository.sent, [("outbox-1", 1234)])

    def test_failure_is_retried_without_leaking_token(self) -> None:
        settings = replace(
            TelegramSettings.from_mapping(environment()),
            delivery_mode=DeliveryMode.LIVE,
        )
        repository = FakeOutbox((message(),))
        result = TelegramPublisher(
            settings=settings,
            repository=repository,
            transport=FakeTransport(error=RuntimeError("test-token failed")),
        ).publish_batch(now=datetime.now(UTC))
        self.assertEqual((result.sent, result.failed), (0, 1))
        self.assertNotIn("test-token", repository.failed[0][1])
        self.assertEqual(result.error_samples, ("RuntimeError: [REDACTED] failed",))


class TelegramCommandParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = TelegramSettings.from_mapping(environment())
        self.parser = TelegramCommandParser()

    @staticmethod
    def update(*, topic: int = 10, user: int = 42, text: str = "/tara ASELS"):
        return {
            "update_id": 100,
            "message": {
                "message_id": 50,
                "message_thread_id": topic,
                "from": {"id": user},
                "chat": {"id": -100123},
                "text": text,
            },
        }

    def test_authorized_scan_command_is_parsed(self) -> None:
        command = self.parser.parse(self.update(), self.settings)
        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.name, CommandName.SCAN)
        self.assertEqual(command.args, ("ASELS",))

    def test_other_topic_is_accepted_but_other_user_is_ignored(self) -> None:
        self.assertIsNotNone(self.parser.parse(self.update(topic=20), self.settings))
        self.assertIsNone(self.parser.parse(self.update(user=99), self.settings))

    def test_invalid_symbol_is_rejected(self) -> None:
        self.assertIsNone(
            self.parser.parse(self.update(text="/tara A;DROP"), self.settings)
        )

    def test_identity_command_does_not_require_a_symbol(self) -> None:
        command = self.parser.parse(self.update(text="/kimlik"), self.settings)
        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.name, CommandName.IDENTITY)
        self.assertEqual(command.args, ())


if __name__ == "__main__":
    unittest.main()
