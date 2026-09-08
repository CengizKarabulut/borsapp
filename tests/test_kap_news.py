from __future__ import annotations

import unittest
from datetime import date
from zoneinfo import ZoneInfo

from market_intelligence.news.kap import KAP_DETAIL_URL, KAP_DISCLOSURES_URL, KapDisclosureProvider


class FakeResponse:
    def __init__(self, body) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, body, detail_body=None) -> None:
        self.body = body
        self.detail_body = detail_body
        self.calls = []

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.body)

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.detail_body)


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
        provider = KapDisclosureProvider(FakeClient([{"publishDate": "07.09.2026 14:05:06"}]))
        self.assertEqual(
            provider.fetch(from_date=date(2026, 9, 7), to_date=date(2026, 9, 7)),
            (),
        )

    def test_new_disclosure_can_be_enriched_from_official_detail_body(self) -> None:
        client = FakeClient(
            [
                {
                    "disclosureIndex": 123,
                    "publishDate": "07.09.2026 14:05",
                    "stockCodes": "ASELS",
                    "summary": "Kısa özet",
                }
            ],
            [
                {
                    "disclosure": {"disclosureBasic": {"summary": "Yeni sözleşme açıklaması"}},
                    "disclosureBody": [
                        "<div><span class='content-tr'>Sözleşme tutarı 100 milyon avrodur.</span><span class='content-en'>English text</span></div>"
                    ],
                }
            ],
        )
        provider = KapDisclosureProvider(client)
        item = provider.fetch(from_date=date(2026, 9, 7), to_date=date(2026, 9, 7))[0]

        enriched = provider.enrich((item,))[0]

        self.assertIn("100 milyon avrodur", enriched.summary)
        self.assertNotIn("English text", enriched.summary)
        self.assertEqual(client.calls[-1][0], f"{KAP_DETAIL_URL}/123")


if __name__ == "__main__":
    unittest.main()
