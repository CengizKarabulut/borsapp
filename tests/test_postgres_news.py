from __future__ import annotations

import unittest
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from market_intelligence.delivery.telegram.config import TopicKind
from market_intelligence.delivery.telegram.routing import OutboxEnvelope, PublicationKind
from market_intelligence.news.contracts import NewsItem
from market_intelligence.persistence.postgres.news import PostgresNewsStore


class FakeTransaction(AbstractContextManager):
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.connection.committed += int(exc_type is None)
        self.connection.rolled_back += int(exc_type is not None)


class FakeCursor(AbstractContextManager):
    def __init__(self, connection) -> None:
        self.connection = connection
        self.one = None
        self.all = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.connection.queries.append((query, params))
        if "SELECT EXISTS" in query:
            self.one = (self.connection.source_exists,)
        elif "SELECT news_id" in query:
            self.all = [(value,) for value in self.connection.existing_ids]
        elif "SELECT DISTINCT ON" in query:
            self.all = list(self.connection.symbol_rows)
        elif "telegram_outbox" in query:
            self.one = ("outbox-1",)

    def fetchone(self):
        value = self.one
        self.one = None
        return value

    def fetchall(self):
        value = self.all
        self.all = []
        return value


class FakeConnection:
    def __init__(
        self,
        *,
        source_exists: bool,
        existing_ids=(),
        symbol_rows=(("ASELS", "instrument-1"),),
    ) -> None:
        self.source_exists = source_exists
        self.existing_ids = existing_ids
        self.symbol_rows = symbol_rows
        self.queries = []
        self.committed = 0
        self.rolled_back = 0

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def item() -> NewsItem:
    return NewsItem(
        news_id="kap:123",
        source="kap",
        headline="ASELS — Yeni İş İlişkisi",
        published_at=datetime(2026, 9, 7, 11, tzinfo=UTC),
        url="https://www.kap.org.tr/tr/Bildirim/123",
        symbols=("ASELS", "UNLISTED"),
        summary="Sözleşme imzalandı.",
        payload={"disclosureIndex": 123},
    )


def envelope() -> OutboxEnvelope:
    return OutboxEnvelope(
        semantic_key="kap-reply-123",
        publication_kind=PublicationKind.NEWS,
        topic_kind=TopicKind.NEWS,
        chat_id=-100123,
        message_thread_id=50,
        payload={"text": "KAP"},
    )


class PostgresNewsStoreTests(unittest.TestCase):
    def test_enriched_ids_only_uses_official_detail_payload_query(self) -> None:
        connection = FakeConnection(source_exists=True, existing_ids=("kap:123",))

        result = PostgresNewsStore(connection).enriched_ids(("kap:123",))

        self.assertEqual(result, {"kap:123"})
        self.assertTrue(any("jsonb_typeof" in query for query, _ in connection.queries))

    def test_first_source_batch_bootstraps_without_outbox(self) -> None:
        connection = FakeConnection(source_exists=False)

        result = PostgresNewsStore(connection).persist(
            source="kap",
            items=(item(),),
            observed_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
            envelopes={"kap:123": envelope()},
        )

        self.assertTrue(result.bootstrapped)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.linked_items, 1)
        self.assertEqual(result.outbox_count, 0)
        self.assertFalse(any("telegram_outbox" in query for query, _ in connection.queries))

    def test_new_linked_item_and_outbox_commit_together(self) -> None:
        connection = FakeConnection(source_exists=True)

        result = PostgresNewsStore(connection).persist(
            source="kap",
            items=(item(),),
            observed_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
            envelopes={"kap:123": envelope()},
        )

        self.assertEqual((result.inserted, result.outbox_count), (1, 1))
        self.assertTrue(any("news_item_instruments" in query for query, _ in connection.queries))
        self.assertTrue(any("telegram_outbox" in query for query, _ in connection.queries))
        self.assertEqual(connection.committed, 1)

    def test_existing_item_is_updated_without_duplicate_outbox(self) -> None:
        connection = FakeConnection(source_exists=True, existing_ids=("kap:123",))

        result = PostgresNewsStore(connection).persist(
            source="kap",
            items=(item(),),
            observed_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
            envelopes={"kap:123": envelope()},
        )

        self.assertEqual((result.inserted, result.outbox_count), (0, 0))
        self.assertFalse(any("telegram_outbox" in query for query, _ in connection.queries))

    def test_unlisted_symbol_is_stored_without_notification(self) -> None:
        connection = FakeConnection(source_exists=True, symbol_rows=())

        result = PostgresNewsStore(connection).persist(
            source="kap",
            items=(item(),),
            observed_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
            envelopes={"kap:123": envelope()},
        )

        self.assertEqual(result.linked_items, 0)
        self.assertEqual(result.outbox_count, 0)
        self.assertFalse(any("telegram_outbox" in query for query, _ in connection.queries))


if __name__ == "__main__":
    unittest.main()
