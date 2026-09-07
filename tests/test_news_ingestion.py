from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from market_intelligence.application.news_ingestion import (
    NewsIngestionService,
    PersistedNewsBatch,
)
from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings
from market_intelligence.news.contracts import NewsItem
from tests.test_telegram_routing import environment


def item() -> NewsItem:
    return NewsItem(
        news_id="kap:123",
        source="kap",
        headline="ASELS — Yeni iş ilişkisi <test>",
        published_at=datetime(2026, 9, 7, 11, tzinfo=UTC),
        url="https://www.kap.org.tr/tr/Bildirim/123",
        symbols=("ASELS",),
        summary="A&B sözleşmesi",
        attachment_count=1,
    )


class FakeProvider:
    source = "kap"

    def fetch(self, *, from_date: date, to_date: date):
        return (item(),)


class FakeStore:
    def __init__(self) -> None:
        self.calls = []

    def persist(self, **kwargs):
        self.calls.append(kwargs)
        return PersistedNewsBatch(1, 1, len(kwargs["envelopes"]), False)


def settings(mode: DeliveryMode) -> TelegramSettings:
    return replace(TelegramSettings.from_mapping(environment()), delivery_mode=mode)


class NewsIngestionServiceTests(unittest.TestCase):
    def test_live_notification_routes_escaped_message_to_news_topic(self) -> None:
        store = FakeStore()
        result = NewsIngestionService(
            provider=FakeProvider(),
            store=store,
            telegram_settings=settings(DeliveryMode.LIVE),
        ).run(
            from_date=date(2026, 9, 6),
            to_date=date(2026, 9, 7),
            observed_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
            notify=True,
        )

        envelope = store.calls[0]["envelopes"]["kap:123"]
        self.assertEqual(result.outbox_count, 1)
        self.assertEqual(envelope.message_thread_id, 50)
        self.assertIn("&lt;test&gt;", envelope.payload["text"])
        self.assertIn("A&amp;B", envelope.payload["text"])

    def test_non_live_notification_is_rejected_before_fetch(self) -> None:
        store = FakeStore()
        with self.assertRaisesRegex(ValueError, "DELIVERY_MODE=live"):
            NewsIngestionService(
                provider=FakeProvider(),
                store=store,
                telegram_settings=settings(DeliveryMode.DISABLED),
            ).run(
                from_date=date(2026, 9, 7),
                to_date=date(2026, 9, 7),
                observed_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
                notify=True,
            )
        self.assertEqual(store.calls, [])


if __name__ == "__main__":
    unittest.main()
