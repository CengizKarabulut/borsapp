from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.research_commentary import _levels_paragraph, _score_phrase
from src.turkish_text import tr_lower


class TurkishTextTests(unittest.TestCase):
    def test_tr_lower_handles_turkish_i_variants(self) -> None:
        cases = {
            "KATILIM": "katılım",
            "TEYİTLİ": "teyitli",
            "KISMİ": "kısmi",
            "UZAMIŞ": "uzamış",
            "KIRILMIŞ DESTEK": "kırılmış destek",
            "VERİ YETERSİZ": "veri yetersiz",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(tr_lower(source), expected)

    def test_score_phrase_keeps_turkish_label_spelling(self) -> None:
        item = SimpleNamespace(score=72.0, label="İYİ")
        self.assertIn("iyi görünüm", _score_phrase(item))

    def test_broken_support_status_is_rendered_and_detected_in_turkish(self) -> None:
        resistance = SimpleNamespace(
            low=100.0,
            high=102.0,
            score=81.0,
            distance_atr=0.8,
            status="KIRILMIŞ DESTEK",
        )
        report = SimpleNamespace(price=98.0, supports=[], resistances=[resistance])
        text = _levels_paragraph(report)
        self.assertIn("kırılmış destek", text)
        self.assertIn("rol değiştirerek direnç/reclaim alanı", text)
        self.assertNotIn("kirilmiş", text)


if __name__ == "__main__":
    unittest.main()
