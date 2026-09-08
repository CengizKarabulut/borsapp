from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_intelligence.news.legacy_general import LegacyGeneralNewsProvider


class LegacyGeneralNewsProviderTests(unittest.TestCase):
    def test_rss_item_becomes_canonical_news_and_extracts_bist_candidate(self) -> None:
        module = SimpleNamespace(
            fetch_rss_source=lambda source: [
                {
                    "source": source,
                    "id": "rss-1",
                    "title": "ASELS yeni sözleşme açıkladı",
                    "link": "https://example.com/asels",
                    "published": "Mon, 07 Sep 2026 10:00:00 +0300",
                    "summary": "Şirket ihracat anlaşmasını duyurdu.",
                    "provider": "NTV Para",
                }
            ]
        )
        provider = LegacyGeneralNewsProvider("ntvpara")
        with patch(
            "market_intelligence.news.legacy_general._legacy_module",
            return_value=module,
        ):
            items = provider.fetch(
                from_date=date(2026, 9, 7),
                to_date=date(2026, 9, 8),
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].news_id, "ntvpara:rss-1")
        self.assertIn("ASELS", items[0].symbols)
        self.assertEqual(items[0].published_at.utcoffset().total_seconds(), 3 * 3600)

    def test_dated_old_item_is_not_replayed(self) -> None:
        module = SimpleNamespace(
            fetch_tradingview=lambda: [
                {
                    "source": "tradingview",
                    "id": "old-1",
                    "title": "Eski haber",
                    "published": "2025-01-01T10:00:00Z",
                }
            ]
        )
        provider = LegacyGeneralNewsProvider(
            "tradingview",
            timezone=ZoneInfo("Europe/Istanbul"),
        )
        with patch(
            "market_intelligence.news.legacy_general._legacy_module",
            return_value=module,
        ):
            items = provider.fetch(
                from_date=datetime(2026, 9, 7).date(),
                to_date=datetime(2026, 9, 8).date(),
            )

        self.assertEqual(items, ())


if __name__ == "__main__":
    unittest.main()
