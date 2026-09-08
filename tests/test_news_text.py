from __future__ import annotations

import unittest
from datetime import UTC, datetime

from market_intelligence.news.text import (
    canonical_news_url,
    news_dedup_key,
    normalize_news_text,
    sentence_excerpt,
)


class NewsTextTests(unittest.TestCase):
    def test_repairs_common_turkish_mojibake_and_html(self) -> None:
        self.assertEqual(
            normalize_news_text("<p>TÃ¼rkiye'nin bÃ¼yÃ¼mesi &amp; ihracatÄ±</p>"),
            "Türkiye'nin büyümesi & ihracatı",
        )

    def test_excerpt_prefers_complete_sentence(self) -> None:
        text = "İlk cümle bütün olarak kalmalıdır. İkinci cümle oldukça uzundur ve kesilecektir."
        excerpt = sentence_excerpt(text, max_chars=55)
        self.assertTrue(excerpt.startswith("İlk cümle bütün olarak kalmalıdır."))
        self.assertTrue(excerpt.endswith("…"))

    def test_tracking_parameters_do_not_create_duplicate_identity(self) -> None:
        first = canonical_news_url("https://example.com/haber?utm_source=x&id=3")
        second = canonical_news_url("https://www.example.com/haber?id=3")
        self.assertEqual(first, second)
        now = datetime(2026, 9, 8, tzinfo=UTC)
        self.assertEqual(
            news_dedup_key(
                source="ntvpara", news_id="a", headline="Haber", url=first, published_at=now
            ),
            news_dedup_key(
                source="trthaber", news_id="b", headline="Haber", url=second, published_at=now
            ),
        )


if __name__ == "__main__":
    unittest.main()
