from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.research_commentary_advanced import _technical_extension, _valuation_paragraph


class AdvancedCommentaryTests(unittest.TestCase):
    def test_valuation_commentary_names_primary_model_and_missing_inputs(self) -> None:
        report = SimpleNamespace(
            valuation={
                "score": 45.0,
                "coverage": 0.70,
                "scope": "Real Estate sektörü",
                "primary_model": "NAD / NAV",
                "model_confidence": 0.42,
                "models": [
                    {
                        "model": "NAD / NAV",
                        "status": "VERİ EKSİK",
                        "reason": "Ekspertiz portföy tablosu olmadan gerçek NAD üretilmez.",
                    },
                    {
                        "model": "F/K",
                        "status": "UYGUN DEĞİL",
                        "reason": "GYO kârı nakit olmayan değerleme kalemlerinden etkilenebilir.",
                    },
                ],
                "computed_values": {},
            }
        )
        text = _valuation_paragraph(report)
        self.assertIn("NAD / NAV", text)
        self.assertIn("hedef fiyat uydurmuyor", text)
        # text.upper() Türkçe farkında değil ("veri" -> "VERI"); ham metinde ara.
        self.assertIn("veri kapsamı", text)
        self.assertIn("içsel değer değil", text)

    def test_technical_extension_explains_hierarchy_confirmed_rail_ma_and_poc(self) -> None:
        report = SimpleNamespace(
            technical={
                "structure_hierarchy": {
                    "summary": "M↑ · S↑ · L↓",
                    "confirmed_rails": 1,
                    "MAJOR": {"state": "UP", "confidence": 0.8, "rail": {"status": "CONFIRMED"}},
                    "SWING": {"state": "UP", "confidence": 0.7, "rail": {"status": "CANDIDATE"}},
                    "MINOR": {"state": "DOWN", "confidence": 0.7, "rail": None},
                },
                "moving_average_regime": {
                    "short": {"confirmation": "TEYİTLİ"},
                    "medium": {"confirmation": "TEYİTLİ"},
                    "long": {"confirmation": "KISMİ"},
                    "extension_risk": "UZAMIŞ",
                },
                "volume_profile": {"short_poc": 100.0, "medium_poc": 95.0, "long_poc": 90.0},
                "participation": {
                    "label": "GÜÇLÜ KATILIM",
                    "relative_turnover": 1.8,
                    "price_impulse_5d_pct": 4.2,
                },
            }
        )
        text = _technical_extension(report)
        self.assertIn("MAJOR", text)
        self.assertIn("SWING", text)
        self.assertIn("MINOR", text)
        self.assertIn("candidate", text)
        self.assertIn("5/8/13", text)
        self.assertIn("kısa POC 100.00", text)
        self.assertIn("güçlü katılım", text)


if __name__ == "__main__":
    unittest.main()
