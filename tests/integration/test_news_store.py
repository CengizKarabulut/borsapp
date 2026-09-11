from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from market_intelligence.persistence.postgres.migrations import apply_migrations
from market_intelligence.persistence.postgres.news import PostgresNewsStore
from tests.test_news_ingestion import item


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is not set")
class NewsStoreIntegrationTests(unittest.TestCase):
    def test_empty_enriched_row_is_retried_until_body_exists(self):
        import psycopg

        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as connection:
            apply_migrations(connection, Path(__file__).resolve().parents[2] / "db/postgres")
            with connection.transaction(force_rollback=True):
                store = PostgresNewsStore(connection)
                news = replace(
                    item(),
                    news_id="news-regression-" + uuid4().hex,
                    source="tradingview",
                    summary="",
                    payload={"enriched": True},
                )
                now = datetime.now(UTC)
                store.persist(source=news.source, items=(news,), observed_at=now, envelopes={})
                self.assertEqual(store.enriched_ids((news.news_id,)), set())
                completed = replace(news, summary="Doğrulanmış haberin ayrıntılı içeriği.")
                store.persist(source=news.source, items=(completed,), observed_at=now, envelopes={})
                self.assertEqual(store.enriched_ids((news.news_id,)), {news.news_id})

    def test_versions_remain_atomic_and_list_refresh_preserves_full_body(self):
        import psycopg

        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as connection:
            apply_migrations(connection, Path(__file__).resolve().parents[2] / "db/postgres")
            with connection.transaction(force_rollback=True):
                store = PostgresNewsStore(connection)
                original = replace(
                    item(),
                    news_id="news-version-" + uuid4().hex,
                    source="tradingview",
                    headline="İlk başlık",
                    summary="Önceki sürümün çok daha uzun ve artık güncel olmayan açıklaması.",
                    payload={"enriched": True, "revision": "old"},
                )
                now = datetime.now(UTC)

                def persist(news):
                    store.persist(source=news.source, items=(news,), observed_at=now, envelopes={})

                def stored():
                    return connection.execute(
                        "SELECT headline, payload FROM news_items WHERE news_id=%s",
                        (original.news_id,),
                    ).fetchone()

                persist(original)
                revised = replace(
                    original,
                    headline="Düzeltilmiş başlık",
                    summary="Yeni kısa içerik.",
                    payload={"enriched": True, "revision": "new"},
                )
                self.assertEqual(store.unchanged_enriched_ids((revised,)), set())
                persist(revised)
                headline, payload = stored()
                self.assertEqual(
                    (headline, payload["summary"]), (revised.headline, revised.summary)
                )
                self.assertEqual(payload["raw"]["revision"], "new")
                listing = replace(revised, summary="Liste özeti", payload={"enriched": False})
                self.assertEqual(store.unchanged_enriched_ids((listing,)), {original.news_id})
                persist(listing)
                self.assertEqual(stored(), (headline, payload))
                shortened = replace(revised, summary="Son içerik.")
                persist(shortened)
                self.assertEqual(stored()[1]["summary"], "Son içerik.")
                pending = replace(listing, headline="Üçüncü başlık", summary="")
                persist(pending)
                self.assertEqual(stored()[0], pending.headline)
                self.assertEqual(stored()[1]["summary"], "")
                self.assertEqual(store.enriched_ids((original.news_id,)), set())
