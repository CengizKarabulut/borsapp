from __future__ import annotations

import unittest
from datetime import UTC, datetime

from market_intelligence.persistence.postgres.symbol_commands import (
    NEWS_SQL,
    PostgresSymbolReadStore,
)


class PostgresSymbolReadStoreTests(unittest.TestCase):
    def test_news_mapping_preserves_kap_provider_title(self) -> None:
        published_at = datetime(2026, 9, 10, tzinfo=UTC)
        item = PostgresSymbolReadStore._news(
            (
                "Finansal Rapor",
                published_at,
                "https://www.kap.org.tr/tr/Bildirim/1",
                "kap",
                "Özet",
                "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.",
            )
        )

        self.assertEqual(item.provider, "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.")
        self.assertEqual(item.published_at, published_at)
        self.assertIn("payload->>'provider'", NEWS_SQL)


if __name__ == "__main__":
    unittest.main()
