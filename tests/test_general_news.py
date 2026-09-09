from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from market_intelligence.news.general import GeneralNewsProvider


class GeneralNewsProviderTests(unittest.TestCase):
    def test_rss_item_becomes_canonical_news_and_extracts_bist_candidate(self) -> None:
        provider = GeneralNewsProvider(
            "ntvpara",
            row_fetcher=lambda source, _now: [
                {
                    "source": source,
                    "id": "rss-1",
                    "title": "ASELS yeni sözleşme açıkladı",
                    "link": "https://example.com/asels",
                    "published": "Mon, 07 Sep 2026 10:00:00 +0300",
                    "summary": "Şirket ihracat anlaşmasını duyurdu.",
                    "provider": "NTV Para",
                }
            ],
        )
        items = provider.fetch(
            from_date=date(2026, 9, 7),
            to_date=date(2026, 9, 8),
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].news_id, "ntvpara:rss-1")
        self.assertIn("ASELS", items[0].symbols)
        self.assertEqual(items[0].published_at.utcoffset().total_seconds(), 3 * 3600)

    def test_dated_old_item_is_not_replayed(self) -> None:
        provider = GeneralNewsProvider(
            "tradingview",
            timezone=ZoneInfo("Europe/Istanbul"),
            row_fetcher=lambda _source, _now: [
                {
                    "source": "tradingview",
                    "id": "old-1",
                    "title": "Eski haber",
                    "published": "2025-01-01T10:00:00Z",
                }
            ],
        )
        items = provider.fetch(
            from_date=datetime(2026, 9, 7).date(),
            to_date=datetime(2026, 9, 8).date(),
        )

        self.assertEqual(items, ())

    def test_article_enrichment_adds_complete_native_summary(self) -> None:
        class Response:
            text = (
                "<html><head><meta property='og:description' "
                "content='Şirket yeni sözleşmenin ayrıntılarını açıkladı.'></head>"
                "<body><article><p>Sözleşme teslimatları üç yıl boyunca sürecek "
                "ve ihracat gelirlerine katkı sağlayacak.</p></article></body></html>"
            )
            encoding = "utf-8"

            def raise_for_status(self) -> None:
                return None

        class Session:
            @staticmethod
            def get(*_args, **_kwargs):
                return Response()

        provider = GeneralNewsProvider(
            "ntvpara",
            session=Session(),
            row_fetcher=lambda source, _now: [
                {
                    "source": source,
                    "id": "rss-2",
                    "title": "ASELS yeni sözleşme açıkladı",
                    "link": "https://example.com/asels-detay",
                    "published": "Mon, 07 Sep 2026 10:00:00 +0300",
                    "summary": "Kısa özet.",
                }
            ],
        )
        item = provider.fetch(
            from_date=date(2026, 9, 7),
            to_date=date(2026, 9, 8),
        )[0]
        enriched = provider.enrich((item,))[0]

        self.assertIn("üç yıl boyunca sürecek", enriched.summary)
        self.assertTrue(enriched.payload["enriched"])

    def test_runtime_provider_does_not_import_legacy_source_tree(self) -> None:
        import market_intelligence.news.general as module

        self.assertNotIn("_legacy", module.__file__)

    def test_epoch_timestamp_is_preserved_in_market_timezone(self) -> None:
        epoch = int(datetime(2026, 9, 7, 7, 0, tzinfo=ZoneInfo("UTC")).timestamp())
        provider = GeneralNewsProvider(
            "tradingview",
            row_fetcher=lambda _source, _now: [
                {
                    "id": "tv-1",
                    "title": "ASELS hakkında piyasa haberi",
                    "link": "https://example.com/tv-1",
                    "published": epoch,
                }
            ],
        )
        item = provider.fetch(
            from_date=date(2026, 9, 7),
            to_date=date(2026, 9, 7),
        )[0]

        self.assertEqual(item.published_at.hour, 10)


if __name__ == "__main__":
    unittest.main()
