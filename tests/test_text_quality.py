from __future__ import annotations

import unittest

from market_intelligence.fundamentals.text_quality import (
    growth_verdict,
    guard_provider_prose,
    is_probably_turkish,
    prefer_turkish_name,
    real_growth,
)

ASELS_PROVIDER_EN = (
    "ASELSAN Elektronik Sanayi ve Ticaret Anonim Sirketi engages in research, "
    "development, engineering, production, testing, assembly, integration and sale. "
    "The company provides advanced systems and services in Türkiye."
)
ASELS_TR = (
    "Şirket; kara, hava, deniz ve uzay uygulamaları kapsamında elektronik, "
    "mikrodalga ve elektro-optik sistemlerin geliştirilmesi, üretimi ve satışı "
    "ile faaliyet göstermektedir."
)


class TextQualityTests(unittest.TestCase):
    def test_english_provider_text_is_rejected(self) -> None:
        self.assertIs(is_probably_turkish(ASELS_PROVIDER_EN), False)
        self.assertIsNone(guard_provider_prose(ASELS_PROVIDER_EN)[0])

    def test_turkish_provider_text_is_accepted(self) -> None:
        self.assertIs(is_probably_turkish(ASELS_TR), True)
        self.assertEqual(guard_provider_prose(ASELS_TR)[0], ASELS_TR)

    def test_one_turkish_proper_noun_does_not_bypass_english_detection(self) -> None:
        text = (
            "Türkiye based company provides defense systems and services "
            "for customers in the domestic and international markets."
        )
        self.assertIs(is_probably_turkish(text), False)

    def test_short_or_ambiguous_text_is_not_guessed(self) -> None:
        self.assertIsNone(is_probably_turkish("Veri yok"))
        self.assertIsNone(is_probably_turkish("ASELSAN Inc"))

    def test_official_turkish_company_name_is_preferred(self) -> None:
        folded = "ASELSAN Elektronik Sanayi ve Ticaret Anonim Sirketi"
        kap = "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş."
        self.assertEqual(prefer_turkish_name(folded, kap), kap)

    def test_real_growth_uses_fisher_relation(self) -> None:
        self.assertAlmostEqual(real_growth(24.7, 32.11), -5.6, places=1)
        self.assertAlmostEqual(real_growth(70.7, 32.11), 29.2, places=1)

    def test_missing_inflation_is_explicitly_unknown(self) -> None:
        verdict = growth_verdict(24.7, None)
        self.assertIn("UNKNOWN", verdict)
        self.assertNotIn("reel büyüme", verdict)

    def test_zero_real_growth_is_not_called_contraction(self) -> None:
        self.assertIn("reel yatay", growth_verdict(10.0, 10.0))


if __name__ == "__main__":
    unittest.main()
