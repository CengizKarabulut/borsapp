import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from market_intelligence.application.news_ingestion import NewsIngestionService
from market_intelligence.delivery.telegram.config import DeliveryMode
from market_intelligence.news.text import normalize_news_text, polish_news_copy
from tests.test_news_ingestion import FakeProvider, FakeStore, item, settings


class NewsRegressionTests(unittest.TestCase):
    def test_script_removed_and_paragraphs_preserved(self):
        value = normalize_news_text(
            "<p>Birinci paragraf.</p><script>tracking()</script><p>İkinci paragraf.</p>",
            preserve_paragraphs=True,
        )
        self.assertEqual(value, "Birinci paragraf.\n\nİkinci paragraf.")

    def test_title_prefix_does_not_remove_word_fragment(self):
        title, summary = polish_news_copy(
            "Kâr arttı", "Kâr arttırıldı ifadesi farklı bir kelimedir."
        )
        self.assertTrue(summary.startswith("Kâr arttırıldı"))

    def test_verified_catalog_filters_false_symbols(self):
        class Provider(FakeProvider):
            source = "tradingview"

            def fetch(self, **kwargs):
                return (replace(item(), source=self.source, symbols=("ASELS", "YENI", "SATIS")),)

        class Store(FakeStore):
            def verified_symbols(self, symbols, **kwargs):
                return {"ASELS"}

        store = Store()
        NewsIngestionService(
            provider=Provider(), store=store, telegram_settings=settings(DeliveryMode.DISABLED)
        ).run(
            from_date=date(2026, 9, 1),
            to_date=date(2026, 9, 10),
            observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        )
        self.assertEqual(store.calls[0]["items"][0].symbols, ("ASELS",))

    def test_layout_has_heading_metadata_and_no_link_preview(self):
        service = NewsIngestionService(
            provider=FakeProvider(),
            store=FakeStore(),
            telegram_settings=settings(DeliveryMode.DISABLED),
        )
        envelope = service._envelope(replace(item(), summary="İlk paragraf.\n\nİkinci paragraf."))
        self.assertTrue(envelope.payload["text"].startswith("<b>"))
        self.assertIn("İlk paragraf.\n\nİkinci paragraf.", envelope.payload["text"])
        self.assertTrue(envelope.payload["link_preview_options"]["is_disabled"])

    def test_changed_version_is_enriched_even_when_id_was_enriched_before(self):
        class Provider(FakeProvider):
            def __init__(self):
                self.pending = ()

            def enrich(self, items):
                self.pending = items
                return tuple(replace(news, summary="Yeni sürümün ayrıntısı") for news in items)

        class Store(FakeStore):
            def unchanged_enriched_ids(self, items):
                return set()

        provider = Provider()
        store = Store(enriched_ids={item().news_id})
        NewsIngestionService(
            provider=provider, store=store, telegram_settings=settings(DeliveryMode.DISABLED)
        ).run(
            from_date=date(2026, 9, 1),
            to_date=date(2026, 9, 10),
            observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        )
        self.assertEqual(len(provider.pending), 1)
        self.assertEqual(store.calls[0]["items"][0].summary, "Yeni sürümün ayrıntısı")
