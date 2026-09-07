import unittest

import news_bot_v10 as v10
from research_summary import summarize_report_text


class ResearchSummaryTests(unittest.TestCase):
    def test_model_portfolio_detects_added_and_removed_tickers(self):
        text = """
        MODEL PORTFÖY
        ASELS Hedef Fiyat 245,00 TL Getiri Potansiyeli %18
        BIMAS Hedef Fiyat 760,00 TL Getiri Potansiyeli %14
        Portföy ağırlık ve öneri tablosu
        """
        result = summarize_report_text(
            text,
            "model_portfoy",
            previous_tickers=["ASELS", "THYAO"],
        )
        joined = " | ".join(result["bullets"])
        self.assertIn("BIMAS", joined)
        self.assertIn("THYAO", joined)
        self.assertIn("ASELS", result["meta"]["tickers"])

    def test_company_report_extracts_recommendation_target_and_upside(self):
        text = """
        Şirket Raporu
        Öneri: AL
        Hedef Fiyat: 185,50 TL
        Getiri Potansiyeli: %27,4
        Güçlü ciro büyümesi ve FAVÖK marjındaki iyileşme ana katalizör olarak öne çıkıyor.
        """
        result = summarize_report_text(text, "sirket_raporu")
        joined = " | ".join(result["bullets"])
        self.assertIn("Öneri: AL", joined)
        self.assertIn("Hedef fiyat: 185,50", joined)
        self.assertIn("Getiri potansiyeli: %27,4", joined)

    def test_technical_report_prefers_levels_and_tickers(self):
        text = """
        Teknik Bülten
        ASELS için 214,00 destek, 221,50 direnç; 225,00 üzeri kırılımda momentum güçlenebilir.
        BIMAS 705,00 destek seviyesi altında stop-loss, 728,00 ilk direnç olarak izleniyor.
        BIST 100 endeksi 10.850 destek ve 11.050 direnç bandında hareket ediyor.
        """
        result = summarize_report_text(text, "teknik_bulten")
        joined = " | ".join(result["bullets"])
        self.assertIn("ASELS", joined)
        self.assertTrue("destek" in joined.lower() or "direnç" in joined.lower())

    def test_empty_text_does_not_invent_summary(self):
        result = summarize_report_text("", "sirket_raporu")
        self.assertEqual(result["bullets"], [])

    def test_caption_keeps_pdf_summary_and_official_link(self):
        item = {
            "source": "akyatirim",
            "report_type": "sirket_raporu",
            "title": "ASELS Şirket Raporu",
            "date_text": "05.09.2026",
            "published_date": "2026-09-05",
            "page_url": "https://www.akyatirim.com.tr/arastirma/rapor",
            "document_url": "https://www.akyatirim.com.tr/arastirma/rapor.pdf",
        }
        summary = {"bullets": ["Öneri: AL", "Hedef fiyat: 245,00"], "meta": {}}
        caption = v10._summary_caption(item, summary)
        self.assertIn("Kısa özet", caption)
        self.assertIn("Hedef fiyat", caption)
        self.assertIn("Resmî araştırma kaynağını aç", caption)
        self.assertLessEqual(len(caption), v10.SUMMARY_CAPTION_LIMIT)

    def test_caption_fallback_is_transparent_when_pdf_text_unreadable(self):
        item = {
            "source": "tera",
            "report_type": "gunluk_bulten",
            "title": "Günlük Bülten",
            "date_text": "05.09.2026",
            "published_date": "2026-09-05",
            "page_url": "https://www.terayatirim.com/arastirma/gunluk-bulten",
            "document_url": "https://www.terayatirim.com/report.pdf",
        }
        caption = v10._summary_caption(item, {"bullets": [], "meta": {}}, extraction_error="parse")
        self.assertIn("metin katmanı", caption)
        self.assertIn("PDF ektedir", caption)


if __name__ == "__main__":
    unittest.main()
