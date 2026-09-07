import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["DRY_RUN"] = "1"

import news_bot


class SourceAndDuplicateTests(unittest.TestCase):
    def test_source_priority_is_fixed(self):
        self.assertEqual(
            news_bot.ENABLED_SOURCES,
            [
                "kap", "bloomberght", "forexfactory", "investing",
                "ntvpara", "trthaber", "tradingview",
            ],
        )

    def test_forex_factory_returns_only_actionable_high_impact_events(self):
        rows = [
            {
                "title": "CPI m/m", "country": "USD",
                "date": "2026-08-15T10:45:00+00:00", "impact": "High",
                "forecast": "0.3%", "previous": "0.2%",
            },
            {
                "title": "Retail Sales", "country": "EUR",
                "date": "2026-08-15T10:30:00+00:00", "impact": "Low",
            },
            {
                "title": "CPI", "country": "CNY",
                "date": "2026-08-15T10:40:00+00:00", "impact": "High",
            },
            {
                "title": "FOMC Statement", "country": "USD",
                "date": "2026-08-15T14:00:00+00:00", "impact": "High",
            },
        ]
        items = news_bot.fetch_forex_factory(
            _Session(_Response(data=rows)),
            now=datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("UTC")),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "USD — CPI m/m")
        self.assertIn("Beklenti: 0.3%", items[0]["summary"])
        self.assertTrue(items[0]["id"].startswith("upcoming:USD:"))

    def test_forex_factory_retries_rate_limit(self):
        event = {
            "title": "CPI m/m", "country": "USD",
            "date": "2026-08-15T10:45:00+00:00", "impact": "High",
        }
        session = _SequenceSession([
            _Response(status_code=429, headers={"Retry-After": "0"}),
            _Response(data=[event]),
        ])
        items = news_bot.fetch_forex_factory(
            session,
            now=datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("UTC")),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(session.calls, 2)

    def test_released_forex_event_has_a_separate_stable_key(self):
        rows = [{
            "title": "Non-Farm Employment Change", "country": "USD",
            "date": "2026-08-15T09:50:00+00:00", "impact": "High",
            "actual": "210K", "forecast": "190K", "previous": "175K",
        }]
        items = news_bot.fetch_forex_factory(
            _Session(_Response(data=rows)),
            now=datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("UTC")),
        )
        self.assertEqual(len(items), 1)
        self.assertIn("Açıklanan: 210K", items[0]["summary"])
        self.assertTrue(items[0]["id"].startswith("released:USD:"))

    def test_similar_cross_source_story_is_duplicate(self):
        kap = news_bot.blank_item(
            "kap",
            "THYAO — Yeni uçak alımına ilişkin açıklama",
            "https://kap/1",
            summary="Türk Hava Yolları yeni uçak alım kararı aldı.",
        )
        bloomberg = news_bot.blank_item(
            "bloomberght",
            "THYAO yeni uçak alım kararı aldı",
            "https://bloomberg/1",
            summary="Türk Hava Yolları yeni uçak alımına ilişkin açıklama yaptı.",
        )
        history = []
        news_bot.remember_story(kap, history)
        self.assertTrue(news_bot.is_cross_source_duplicate(bloomberg, history))

    def test_forex_release_is_not_blocked_by_its_own_upcoming_alert(self):
        upcoming = news_bot.blank_item(
            "forexfactory", "USD — CPI m/m", "https://forexfactory/calendar",
            summary="Yaklaşık 45 dakika sonra · Etki: Yüksek · Beklenti: 0.3%",
        )
        released = news_bot.blank_item(
            "forexfactory", "USD — CPI m/m", "https://forexfactory/calendar",
            summary="Yeni açıklandı · Etki: Yüksek · Açıklanan: 0.4% · Beklenti: 0.3%",
        )
        history = []
        news_bot.remember_story(upcoming, history)
        self.assertFalse(news_bot.is_cross_source_duplicate(released, history))

    def test_unrelated_story_is_not_duplicate(self):
        history = []
        news_bot.remember_story(
            news_bot.blank_item("kap", "ASELS yeni sözleşme imzaladı", "https://kap/1"),
            history,
        )
        unrelated = news_bot.blank_item(
            "investing", "Euro Bölgesi enflasyonu geriledi", "https://investing/1"
        )
        self.assertFalse(news_bot.is_cross_source_duplicate(unrelated, history))

    def test_rss_is_parsed_and_html_summary_is_cleaned(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item><title>Dolar/TL hareketlendi</title>
        <link>https://example.com/dolar</link><guid>fx-1</guid>
        <pubDate>Sat, 15 Aug 2026 10:00:00 GMT</pubDate>
        <description><![CDATA[<p>Kurda yeni hareket görüldü.</p>]]></description>
        </item></channel></rss>""".encode("utf-8")
        items = news_bot.fetch_rss_source("ntvpara", _Session(_Response(xml)))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["summary"], "Kurda yeni hareket görüldü.")

    def test_atom_feed_is_parsed(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>Piyasalarda gün ortası</title>
        <link rel="alternate" href="https://example.com/piyasa" />
        <id>atom-1</id><updated>2026-08-15T11:00:00+03:00</updated>
        <summary>Endeks ve döviz piyasaları izlendi.</summary>
        </entry></feed>""".encode("utf-8")
        items = news_bot.fetch_rss_source("ntvpara", _Session(_Response(xml)))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["link"], "https://example.com/piyasa")
        self.assertEqual(items[0]["id"], "atom-1")


class _Response:
    def __init__(self, content=b"", data=None, status_code=200, headers=None):
        self.content = content
        self.data = data
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.data


class _Session:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


class _SequenceSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return next(self.responses)


if __name__ == "__main__":
    unittest.main()
