from __future__ import annotations

import unittest
from datetime import date
from zoneinfo import ZoneInfo

from market_intelligence.news.kap import KAP_DISCLOSURES_URL, KapDisclosureProvider


class FakeResponse:
    def __init__(self, body) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, body) -> None:
        self.body = body
        self.calls = []

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.body)


class KapDisclosureProviderTests(unittest.TestCase):
    def test_maps_multi_symbol_disclosure_to_canonical_item(self) -> None:
        client = FakeClient(
            [
                {
                    "disclosureIndex": 123,
                    "publishDate": "07.09.2026 14:05:06",
                    "kapTitle": "Örnek Holding A.Ş.",
                    "stockCodes": "ASELS, THYAO",
                    "subject": "Yeni İş İlişkisi",
                    "summary": "Sözleşme imzalandı.",
                    "disclosureClass": "ODA",
                    "attachmentCount": 2,
                }
            ]
        )
        provider = KapDisclosureProvider(
            client,
            timezone=ZoneInfo("Europe/Istanbul"),
        )

        items = provider.fetch(
            from_date=date(2026, 9, 6),
            to_date=date(2026, 9, 7),
        )

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.news_id, "kap:123")
        self.assertEqual(item.symbols, ("ASELS", "THYAO"))
        self.assertIn("Yeni İş İlişkisi", item.headline)
        self.assertEqual(item.published_at.utcoffset().total_seconds(), 3 * 3600)
        self.assertEqual(client.calls[0][0], KAP_DISCLOSURES_URL)
        self.assertEqual(client.calls[0][1]["json"]["fromDate"], "2026-09-06")

    def test_invalid_response_shape_is_rejected(self) -> None:
        provider = KapDisclosureProvider(FakeClient({"unexpected": True}))
        with self.assertRaisesRegex(RuntimeError, "liste döndürmedi"):
            provider.fetch(from_date=date(2026, 9, 7), to_date=date(2026, 9, 7))

    def test_missing_disclosure_id_is_ignored(self) -> None:
        provider = KapDisclosureProvider(
            FakeClient([{"publishDate": "07.09.2026 14:05:06"}])
        )
        self.assertEqual(
            provider.fetch(from_date=date(2026, 9, 7), to_date=date(2026, 9, 7)),
            (),
        )


if __name__ == "__main__":
    unittest.main()
