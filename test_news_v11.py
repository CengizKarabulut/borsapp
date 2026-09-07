import unittest

import news_bot_v11 as v11
from investor_takeaway import summarize_report_text


class InvestorTakeawayTests(unittest.TestCase):
    def test_company_report_turns_fields_into_grounded_takeaway(self):
        text = """
        Şirket Raporu
        Öneri: AL
        Hedef Fiyat: 185,50 TL
        Getiri Potansiyeli: %27,4
        Güçlü ciro büyümesi ve FAVÖK marjındaki iyileşme ana katalizör olarak öne çıkıyor.
        """
        result = summarize_report_text(text, "sirket_raporu")
        joined = " | ".join(result["takeaways"])
        self.assertIn("olumlu", joined)
        self.assertIn("185,50", joined)
        self.assertIn("%27,4", joined)

    def test_hold_recommendation_is_described_as_neutral(self):
        text = "Öneri: TUT\nHedef Fiyat: 92,00 TL\nGetiri Potansiyeli: %5,0"
        result = summarize_report_text(text, "sirket_raporu")
        self.assertIn("nötr", " | ".join(result["takeaways"]))

    def test_technical_report_explains_band_and_breakout_without_new_levels(self):
        text = """
        ASELS için 214,00 destek, 221,50 direnç; 225,00 üzeri kırılımda momentum güçlenebilir.
        BIMAS 705,00 destek seviyesi altında stop-loss, 728,00 ilk direnç olarak izleniyor.
        """
        result = summarize_report_text(text, "teknik_bulten")
        joined = " | ".join(result["takeaways"])
        self.assertIn("214,00", joined)
        self.assertIn("221,50", joined)
        self.assertIn("225,00", joined)
        self.assertNotIn("230", joined)

    def test_model_portfolio_change_becomes_plain_language_takeaway(self):
        text = """
        MODEL PORTFÖY
        ASELS Hedef Fiyat 245,00 TL Getiri Potansiyeli %18
        BIMAS Hedef Fiyat 760,00 TL Getiri Potansiyeli %14
        """
        result = summarize_report_text(
            text,
            "model_portfoy",
            previous_tickers=["ASELS", "THYAO"],
        )
        joined = " | ".join(result["takeaways"])
        self.assertIn("BIMAS", joined)
        self.assertIn("THYAO", joined)
        self.assertIn("değişim", joined.lower())

    def test_daily_report_lists_only_topics_present_in_text(self):
        text = """
        BIST 100 endeksi 10.850 destek ve 11.050 direnç bandında izleniyor.
        TCMB faiz kararı ve enflasyon görünümü günün ana gündeminde.
        """
        result = summarize_report_text(text, "gunluk_bulten")
        joined = " | ".join(result["takeaways"])
        self.assertIn("BIST 100", joined)
        self.assertIn("faiz", joined)
        self.assertIn("enflasyon", joined)
        self.assertNotIn("petrol", joined.lower())

    def test_empty_text_has_no_takeaway(self):
        result = summarize_report_text("", "teknik_bulten")
        self.assertEqual(result["takeaways"], [])

    def test_caption_separates_takeaway_from_source_facts_and_keeps_pdf_link(self):
        item = {
            "source": "akyatirim",
            "report_type": "sirket_raporu",
            "title": "ASELS Şirket Raporu",
            "date_text": "05.09.2026",
            "published_date": "2026-09-05",
            "page_url": "https://www.akyatirim.com.tr/arastirma/rapor",
            "document_url": "https://www.akyatirim.com.tr/arastirma/rapor.pdf",
        }
        summary = {
            "takeaways": ["Kurumun rapordaki görüşü olumlu (AL); hedef fiyat 245,00 TL; getiri potansiyeli %18."],
            "bullets": ["Öneri: AL", "Hedef fiyat: 245,00", "Getiri potansiyeli: %18"],
            "meta": {},
        }
        caption = v11._summary_caption(item, summary)
        self.assertIn("Yatırımcı için anlamı", caption)
        self.assertIn("Rapordan öne çıkanlar", caption)
        self.assertIn("Resmî araştırma kaynağını aç", caption)
        self.assertLessEqual(len(caption), v11.SUMMARY_CAPTION_LIMIT)


if __name__ == "__main__":
    unittest.main()
