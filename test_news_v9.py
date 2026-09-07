import os
import unittest
from unittest.mock import patch

import news_bot_v9 as v9


class FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
        self.status_code = status_code
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class SourceHealthTests(unittest.TestCase):
    def test_tcmb_rss_parses_with_stdlib_xml(self):
        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
        <rss><channel><item>
          <title>Para Politikasi Kurulu Karari</title>
          <link>https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Duyurular/Basin/2026/DUY2026-01</link>
          <pubDate>Fri, 04 Sep 2026 14:00:00 +0300</pubDate>
        </item></channel></rss>"""
        # Gerçek akışta v6.install_official_sources() TCMB etiketini fetch çağrısından önce kurar.
        with patch.dict(v9.base.SOURCE_LABELS, {"tcmb": "TCMB"}, clear=False):
            items = v9.fetch_tcmb(session=FakeSession(FakeResponse(xml)))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "tcmb")
        self.assertIn("Para Politikasi", items[0]["title"])
        self.assertIn("tcmb.gov.tr", items[0]["link"])

    def test_reuters_is_disabled_by_default_filter(self):
        sources = ["kap", "reuters", "cnbce", "tradingview"]
        self.assertEqual(
            v9.filter_news_sources(sources, enable_reuters=False),
            ["kap", "cnbce", "tradingview"],
        )
        self.assertIn("reuters", v9.filter_news_sources(sources, enable_reuters=True))

    def test_research_allowlist_is_authoritative(self):
        selected = v9.configured_research_sources("tera,seker,global,tera,unknown")
        self.assertEqual(selected, ["tera", "seker", "global"])

    def test_known_research_urls_are_updated(self):
        old_v5_seker = v9.v5.BROKER_CONFIGS["seker"]["url"]
        old_v5_is = v9.v5.BROKER_CONFIGS["isyatirim"]["url"]
        old_v6_seker = v9.v6.RESEARCH_PAGE_CONFIGS["seker"]["url"]
        old_v6_is = v9.v6.RESEARCH_PAGE_CONFIGS["isyatirim"]["url"]
        try:
            v9.apply_known_url_fixes()
            self.assertTrue(v9.v5.BROKER_CONFIGS["seker"]["url"].endswith("/Arastirma/Raporlar"))
            self.assertIn("/Sayfalar/default.aspx", v9.v5.BROKER_CONFIGS["isyatirim"]["url"])
            self.assertEqual(
                v9.v6.RESEARCH_PAGE_CONFIGS["seker"]["url"],
                v9.v5.BROKER_CONFIGS["seker"]["url"],
            )
        finally:
            v9.v5.BROKER_CONFIGS["seker"]["url"] = old_v5_seker
            v9.v5.BROKER_CONFIGS["isyatirim"]["url"] = old_v5_is
            v9.v6.RESEARCH_PAGE_CONFIGS["seker"]["url"] = old_v6_seker
            v9.v6.RESEARCH_PAGE_CONFIGS["isyatirim"]["url"] = old_v6_is

    def test_default_healthy_list_excludes_known_broken_sources(self):
        with patch.dict(os.environ, {"BULLETIN_SOURCES": v9.DEFAULT_HEALTHY_RESEARCH_SOURCES}, clear=False):
            selected = v9.configured_research_sources()
        for source in ("info", "global", "unlu", "integral", "halk"):
            self.assertNotIn(source, selected)
        for source in ("tera", "seker", "isyatirim", "gedik"):
            self.assertIn(source, selected)


if __name__ == "__main__":
    unittest.main()
