from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.application.symbol_commands import (
    CommandReply,
    SymbolCommandService,
    SymbolSnapshot,
)
from market_intelligence.application.telegram_listener import TelegramListener
from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings, TopicKind


class FakeSource:
    def __init__(self, updates):
        self.updates = tuple(updates)
        self.offsets: list[int] = []

    def fetch(self, *, offset: int, timeout_seconds: int):
        self.offsets.append(offset)
        return self.updates


class FakeRepository:
    def __init__(self, offset: int = 0):
        self.offset = offset
        self.committed = []

    def next_offset(self) -> int:
        return self.offset

    def commit_update(self, *, update_id: int, envelopes) -> None:
        self.committed.append((update_id, envelopes))
        self.offset = max(self.offset, update_id + 1)


class FakeSymbolStore:
    def __init__(self) -> None:
        self.calls = 0

    def load_symbol(self, symbol: str):
        self.calls += 1
        if symbol != "ASELS":
            return None
        return SymbolSnapshot("instrument-1", "ASELS")


class MultipartCommandService:
    def handle(self, command):
        return CommandReply("Birinci parça", additional_texts=("İkinci parça",))


def settings(mode: DeliveryMode = DeliveryMode.LIVE) -> TelegramSettings:
    return TelegramSettings(
        bot_token="secret",
        chat_id=-100123,
        allowed_user_ids=frozenset({42}),
        topic_ids={kind: index + 10 for index, kind in enumerate(TopicKind)},
        delivery_mode=mode,
    )


def update(update_id: int, *, user_id: int = 42, text: str = "/tara ASELS"):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id + 100,
            "message_thread_id": settings().topic_id(TopicKind.COMMAND),
            "from": {"id": user_id},
            "chat": {"id": settings().chat_id},
            "date": int(datetime.now(ZoneInfo("Europe/Istanbul")).timestamp()),
            "text": text,
        },
    }


class TelegramListenerTests(unittest.TestCase):
    def test_authorized_command_reply_and_checkpoint_are_committed_together(self) -> None:
        source = FakeSource([update(7)])
        repository = FakeRepository()
        listener = TelegramListener(
            settings=settings(),
            source=source,
            repository=repository,
            command_service=SymbolCommandService(FakeSymbolStore()),
        )

        result = listener.run_once(timeout_seconds=0)

        self.assertEqual(result.accepted, 1)
        update_id, envelopes = repository.committed[0]
        self.assertEqual(update_id, 7)
        self.assertEqual(len(envelopes), 1)
        envelope = envelopes[0]
        self.assertEqual(envelope.message_thread_id, settings().topic_id(TopicKind.SCANS))
        self.assertIn("ASELS", envelope.payload["text"])

    def test_command_without_forum_topic_is_accepted_and_routed(self) -> None:
        item = update(11, text="/haber ASELS")
        del item["message"]["message_thread_id"]
        repository = FakeRepository()
        listener = TelegramListener(
            settings=settings(),
            source=FakeSource([item]),
            repository=repository,
            command_service=SymbolCommandService(FakeSymbolStore()),
        )

        result = listener.run_once(timeout_seconds=0)

        self.assertEqual(result.accepted, 1)
        _, envelopes = repository.committed[0]
        self.assertEqual(envelopes[0].message_thread_id, settings().topic_id(TopicKind.NEWS))

    def test_unauthorized_update_is_checkpointed_without_reply(self) -> None:
        repository = FakeRepository()
        listener = TelegramListener(
            settings=settings(),
            source=FakeSource([update(8, user_id=99)]),
            repository=repository,
            command_service=SymbolCommandService(FakeSymbolStore()),
        )

        result = listener.run_once(timeout_seconds=0)

        self.assertEqual(result.ignored, 1)
        self.assertEqual(repository.committed, [(8, ())])

    def test_disabled_mode_checkpoints_command_without_stale_reply_backlog(self) -> None:
        repository = FakeRepository()
        store = FakeSymbolStore()
        listener = TelegramListener(
            settings=settings(DeliveryMode.DISABLED),
            source=FakeSource([update(9)]),
            repository=repository,
            command_service=SymbolCommandService(store),
        )

        result = listener.run_once(timeout_seconds=0)

        self.assertEqual(result.accepted, 1)
        self.assertEqual(repository.committed, [(9, ())])
        self.assertEqual(store.calls, 0)

    def test_multipart_reply_is_committed_as_distinct_outbox_messages(self) -> None:
        repository = FakeRepository()
        listener = TelegramListener(
            settings=settings(),
            source=FakeSource([update(10, text="/haber ASELS")]),
            repository=repository,
            command_service=MultipartCommandService(),
        )

        result = listener.run_once(timeout_seconds=0)

        self.assertEqual(result.accepted, 1)
        _, envelopes = repository.committed[0]
        self.assertEqual(
            [item.payload["text"] for item in envelopes],
            ["Birinci parça", "İkinci parça"],
        )
        self.assertNotEqual(envelopes[0].semantic_key, envelopes[1].semantic_key)


if __name__ == "__main__":
    unittest.main()
