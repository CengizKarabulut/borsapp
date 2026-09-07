import os
import unittest
from datetime import date

os.environ["DRY_RUN"] = "1"
os.environ["RESEARCH_MAX_AGE_DAYS"] = "0"

from bs4 import BeautifulSoup

import news_bot_v8 as v8


class ResearchFreshnessTests(unittest.TestCase):
    def test_stale_report_is_rejected(self):
        item = {
            "source": "demo",
            "report_type": "teknik_bulten",
            "title": "Teknik Bülten 04.09.2026",
            "page_url": "https://example.com/teknik-bulten/04.09.2026",
            "document_url": "",
            "date_text": "04.09.2026",
        }
        normalized, reason = v8.normalize_candidate(item, today=date(2026, 9, 5))
        self.assertIsNone(normalized)
        self.assertEqual(reason, "stale_date")

    def test_current_report_is_accepted(self):
        item = {
            "source": "demo",
            "report_type": "model_portfoy",
            "title": "Model Portföy 05.09.2026",
            "page_url": "https://example.com/model-portfoy/05.09.2026",
            "document_url": "",
            "date_text": "05.09.2026",
        }
        normalized, reason = v8.normalize_candidate(item, today=date(2026, 9, 5))
        self.assertEqual(reason, "")
        self.assertEqual(normalized["published_date"], "2026-09-05")

    def test_conflicting_url_date_is_rejected(self):
        item = {
            "source": "ziraat",
            "report_type": "gunluk_bulten",
            "title": "Sabah Stratejisi 05.09.2026",
            "page_url": "https://example.com/arastirma",
            "document_url": "https://example.com/media/ss-07-07-2026.pdf",
            "date_text": "05.09.2026",
        }
        normalized, reason = v8.normalize_candidate(item, today=date(2026, 9, 5))
        self.assertIsNone(normalized)
        self.assertEqual(reason, "date_conflict")

    def test_static_url_can_be_new_again_on_a_new_date(self):
        first = {
            "source": "demo",
            "report_type": "model_portfoy",
            "title": "Model Portföy",
            "page_url": "https://example.com/model-portfoy",
            "document_url": "",
            "date_text": "05.09.2026",
        }
        second = dict(first, date_text="06.09.2026")
        first_norm, _ = v8.normalize_candidate(first, today=date(2026, 9, 5))
        second_norm, _ = v8.normalize_candidate(second, today=date(2026, 9, 6))
        self.assertNotEqual(first_norm["key"], second_norm["key"])
        self.assertNotEqual(first_norm["semantic_key"], second_norm["semantic_key"])

    def test_navigation_anchor_is_detected(self):
        soup = BeautifulSoup(
            '<header><nav><a href="/model-portfoy">Model Portföy</a></nav></header>',
            "html.parser",
        )
        self.assertTrue(v8._inside_navigation(soup.find("a")))

    def test_social_and_corporate_links_are_blocked(self):
        self.assertTrue(v8._is_blocked_url("https://www.instagram.com/demo"))
        self.assertTrue(v8._is_blocked_url("https://example.com/kariyer"))
        self.assertFalse(v8._is_blocked_url("https://example.com/arastirma/teknik-bulten-05.09.2026.pdf"))

    def test_same_daily_report_dedupes_pdf_and_landing_page(self):
        landing = {
            "source": "demo",
            "report_type": "gunluk_bulten",
            "title": "Günlük Bülten 05.09.2026",
            "page_url": "https://example.com/gunluk-bulten",
            "document_url": "",
            "date_text": "05.09.2026",
        }
        pdf = dict(
            landing,
            page_url="https://example.com/arastirma",
            document_url="https://example.com/Gunluk_Bulten_05.09.2026.pdf",
        )
        landing_norm, _ = v8.normalize_candidate(landing, today=date(2026, 9, 5))
        pdf_norm, _ = v8.normalize_candidate(pdf, today=date(2026, 9, 5))
        unique = v8._dedupe_candidates([landing_norm, pdf_norm])
        self.assertEqual(len(unique), 1)
        self.assertTrue(unique[0]["document_url"])


if __name__ == "__main__":
    unittest.main()
