from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.research_commentary_rich import (
    commentary_messages,
    compose_research_commentary,
)
from src.research_engine import LevelZone, ResearchDimension, RiskItem


class ResearchCommentaryTests(unittest.TestCase):
    def _report(self):
        dimensions = (
            ResearchDimension("Şirket Kalitesi", 78.0, 0.80, "GÜÇLÜ", ""),
            ResearchDimension("Bilanço Trendi", 62.0, 0.75, "KARIŞIK", ""),
            ResearchDimension("Kâr Kalitesi", 55.0, 0.70, "ORTA", ""),
            ResearchDimension("Değerleme", 42.0, 0.85, "PRİMLİ / ZAYIF", ""),
            ResearchDimension("Teknik Yapı", 35.0, 1.00, "ZAYIF", ""),
        )
        support = LevelZone("destek", 95.0, 96.0, 95.5, 72.0, "AKTİF DESTEK", 1.2, 3, 8, ("HL", "Fib61.8"))
        resistance = LevelZone("direnç", 108.0, 110.0, 109.0, 80.0, "KIRILMIŞ DESTEK → DİRENÇ", 2.1, 4, 5, ("LH", "EMA21"))
        main_risk = RiskItem("Teknik yapı", 74.0, "LH / LL ve BOS AŞAĞI; ATR %4.2.")
        return SimpleNamespace(
            symbol="TEST",
            price=101.50,
            profile="GENERIC",
            research_score=54.0,
            coverage=0.78,
            dimensions=dimensions,
            financial={
                "balance_score": 62.0,
                "balance_label": "KARIŞIK",
                "earnings_quality_score": 55.0,
                "earnings_quality_label": "ORTA",
                "debt_direction": "AZALIYOR",
                "metrics": {
                    "revenue_growth": 18.0,
                    "operating_growth": 12.0,
                    "operating_margin_yoy_change_pp": 1.5,
                    "current_ratio": 1.6,
                    "cfo_net_income": 1.1,
                    "fcf_margin": 8.0,
                    "accrual_ratio": 2.0,
                    "receivables_vs_sales_gap": 4.0,
                    "inventory_vs_sales_gap": -2.0,
                    "net_debt_ebitda": 1.4,
                    "net_debt_equity": 0.4,
                    "net_debt_yoy_change": -16.0,
                    "interest_coverage": 5.2,
                },
            },
            valuation={
                "score": 42.0,
                "coverage": 0.85,
                "scope": "Industrials sektörü",
                "metrics": {
                    "pe": {"value": 18.0, "percentile": 68.0},
                    "pb": {"value": 2.2, "percentile": 62.0},
                    "ev_ebitda": {"value": 10.4, "percentile": 71.0},
                },
            },
            technical={
                "score": 35.0,
                "label": "ZAYIF",
                "structure": {"state": "LH / LL", "event": "BOS AŞAĞI"},
                "weekly_structure": {"state": "LH / LL", "event": "CHoCH AŞAĞI"},
                "monthly_structure": {"state": "—", "event": "VERİ YETERSİZ"},
                "alpha_trend_state": "FİYAT ALTINDA / DÜŞEN",
                "bollinger_state": "ALT BANDA YAKIN",
                "rsi14": 34.0,
                "smi": -42.0,
                "smi_signal": -38.0,
                "macd_hist": -0.18,
                "obv_10d_change": -7.0,
                "rvol20": 1.25,
                "atr_pct": 4.2,
                "latest_rsi_divergence": {"kind": "Regular Bullish"},
                "elliott": {
                    "primary": "DÜZELTME / İTKİ AYRIMI BELİRSİZ",
                    "alternate": "ABC DÜZELTMESİ",
                    "confidence": 45.0,
                    "invalidation": 94.5,
                },
            },
            supports=(support,),
            resistances=(resistance,),
            main_risk=main_risk,
            risks=(main_risk, RiskItem("Değerleme hassasiyeti", 58.0, "")),
        )

    def test_has_one_paragraph_per_required_section(self) -> None:
        commentary = compose_research_commentary(self._report())
        self.assertEqual(len(commentary), 9)
        titles = [title for title, _ in commentary]
        self.assertEqual(
            titles,
            [
                "ŞİRKET NE DURUMDA?",
                "DEĞERLEME NASIL?",
                "BİLANÇO İYİLEŞİYOR MU?",
                "KÂR KALİTELİ Mİ?",
                "BORÇ VE NAKİT NE YÖNDE?",
                "TEKNİK YAPI NE DİYOR?",
                "KRİTİK SEVİYELER NEREDE?",
                "ASIL RİSK NE?",
                "SONUÇ",
            ],
        )
        self.assertTrue(all(len(paragraph) > 80 for _, paragraph in commentary))
        technical = dict(commentary)["TEKNİK YAPI NE DİYOR?"]
        for term in ("Bollinger", "SMI", "MACD", "RVOL20", "ATR", "Elliott"):
            self.assertIn(term, technical)

    def test_telegram_messages_respect_limit_and_preserve_sections(self) -> None:
        messages = commentary_messages(self._report(), limit=1200)
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= 1200 for message in messages))
        joined = "\n".join(messages)
        self.assertIn("ŞİRKET NE DURUMDA?", joined)
        self.assertIn("ASIL RİSK NE?", joined)
        self.assertIn("SONUÇ", joined)

    def test_low_coverage_earnings_is_explained_not_scored(self) -> None:
        report = self._report()
        dimensions = list(report.dimensions)
        dimensions[2] = ResearchDimension("Kâr Kalitesi", None, 0.20, "VERİ YETERSİZ", "")
        report.dimensions = tuple(dimensions)
        commentary = dict(compose_research_commentary(report))
        self.assertIn("veri kapsamı yeterli değil", commentary["KÂR KALİTELİ Mİ?"])
        self.assertIn("puanlanmıyor", commentary["KÂR KALİTELİ Mİ?"])


if __name__ == "__main__":
    unittest.main()
