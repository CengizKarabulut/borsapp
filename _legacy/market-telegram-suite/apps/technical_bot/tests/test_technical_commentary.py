import unittest

import pandas as pd

from src.technical_commentary import build_technical_commentary


def data_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Close": 100.0, "RSI": 48.0, "MACD_HIST": -0.2,
                "SMI": -10.0, "SMI_EMA": -8.0,
            },
            {
                "Close": 100.2, "RSI": 52.0, "MACD_HIST": 0.1,
                "SMI": 5.0, "SMI_EMA": 2.0,
            },
        ]
    )


def context(regime: str = "Denge / sıkışma") -> dict:
    divergence = {
        "indicator": "SMI", "state": "Pozitif gizli uyumsuzluk",
        "quality": "Orta", "event_age": 2,
    }
    return {
        "regime": {"state": regime, "candidate": regime, "tone": "warning", "adx": 22.0, "adx_delta": 1.0},
        "structure": {"state": "HH / HL", "high": 110.0, "low": 95.0, "tone": "positive"},
        "profile": {
            "position": "Value Area içinde", "tone": "neutral",
            "developing_acceptance": "Developing profile kabulü oluşmadı",
            "poc": 101.0, "vah": 106.0, "val": 96.0, "poc_migration": "Yatay",
        },
        "events": [],
        "semantic": {
            "price_action": {
                "state": "Güçlü alıcı kapanışı", "tone": "positive", "patterns": [],
                "summary": "Kapanış gün içi tepeye yakın; alıcılar seans sonuna kadar kontrolü korudu.",
            },
            "trend_quality": {
                "state": "Tam bullish EMA dizilimi", "tone": "positive", "spread_state": "genişliyor",
                "summary": "EMA dizilimi bullish ve ortalama dağılımı genişliyor.",
            },
            "momentum_character": {
                "state": "Pozitif ve genişleyen momentum", "tone": "positive",
                "summary": "RSI pozitif bölgede; MACD histogramı genişliyor.",
                "macd": {"histogram_character": "pozitif histogram genişliyor"},
                "active_divergences": [divergence],
            },
            "participation": {
                "state": "Düşük katılım", "tone": "warning", "rvol_1": 0.7,
                "summary": "RVOL 0,70x; hareketin katılım teyidi sınırlı.",
            },
            "level_confluence": {
                "summary": "En yakın alt referans AVWAP 99,00; en yakın üst referans POC 101,00.",
                "nearest_support": {"name": "AVWAP", "value": 99.0, "family": "VWAP"},
                "nearest_resistance": {"name": "POC", "value": 101.0, "family": "Profil"},
                "clusters": [],
            },
        },
    }


def decision() -> dict:
    return {
        "relative_strength": {
            "available": True, "state": "Göreceli zayıflıyor", "benchmark": "XU100", "tone": "negative",
            "ratio_slope_5_pct": -1.2,
            "periods": {"20": {"stock_return_pct": 2.0, "benchmark_return_pct": 5.0, "excess_return_pct": -3.0}},
        },
        "multi_timeframe": {"state": "Zaman dilimleri karışık", "tone": "warning"},
        "liquidity": {"state": "Yüksek TL likiditesi"},
    }


class TechnicalCommentaryV2Tests(unittest.TestCase):
    def test_squeeze_requires_expansion_and_acceptance(self) -> None:
        result = build_technical_commentary(data_frame(), context(), decision(), {"is_live": False})
        self.assertEqual(result["version"], "2.4")
        self.assertIn("Denge / teyit bekliyor", result["stance"])
        self.assertIn("bant genişlemesi", result["headline"])
        self.assertTrue(any("Bantlar genişlemeden" in item for item in result["scenario_map"]["neutral"]))

    def test_commentary_exposes_counter_evidence_and_divergence_quality(self) -> None:
        result = build_technical_commentary(data_frame(), context(), decision(), {"is_live": True})
        self.assertTrue(any("Göreceli güç" in item for item in result["conflicts"]))
        self.assertTrue(any("CANLI" in item for item in result["conflicts"]))
        self.assertIn("Pozitif gizli uyumsuzluk", result["analyst_note"])
        self.assertIn("Orta kalite", result["analyst_note"])

    def test_method_uses_independent_families_without_vote_score(self) -> None:
        result = build_technical_commentary(data_frame(), context(), decision(), {"is_live": False})
        self.assertIn("birleşik AL/SAT puanı üretmez", result["method"])
        self.assertEqual(len(result["state_map"]), 12)
        self.assertNotIn("/4", result["analyst_note"])
        self.assertIn(result["clarity"]["state"], {"Yüksek", "Orta", "Düşük"})

    def test_four_user_schemas_are_explained_with_confirmation_and_risk(self) -> None:
        result = build_technical_commentary(data_frame(), context(), decision(), {"is_live": False})
        schemas = result["indicator_schemas"]
        self.assertEqual(
            [item["name"] for item in schemas],
            [
                "1 · Bollinger / MACD / SMI / OBV",
                "2 · Ichimoku / RSI / CCI / ATR",
                "3 · Parabolic SAR / Stoch RSI / Auto AVWAP / ADX-DMI",
                "4 · Supertrend / Fisher / CMF / Momentum",
            ],
        )
        for item in schemas:
            self.assertTrue(item["plain"])
            self.assertTrue(item["guide"])
            self.assertIn("Genel okuma:", item["guide"])
            self.assertIn("Bu hissede", item["stock_comment"])
            self.assertIn("Teyit", item["confirmation"])
            self.assertTrue(item["risk"])
        self.assertIn("Hikâye şöyle", result["market_story"])
        self.assertIn("Net sonuç:", result["general_interpretation"])
        self.assertIn("Dört Gösterge Şeması", result["telegram_detail"])
        self.assertIn("Nasıl okunur?", result["telegram_detail"])
        self.assertIn("Bu hisse özelinde:", result["telegram_detail"])
        self.assertNotIn("Yönün doğrulanması için: Teyit için", result["telegram_detail"])
        self.assertIn("Genel Yorum", result["telegram_detail"])

    def test_equal_indicator_boundaries_remain_neutral(self) -> None:
        from src.technical_commentary_v2 import _indicator_schemas

        row = {
            "Close": 100.0,
            "BB_MID": 100.0, "BB_UPPER": 100.0, "BB_LOWER": 100.0, "BB_WIDTH": 0.0,
            "MACD_HIST": 0.0, "SMI": 0.0, "SMI_EMA": 0.0, "OBV": 0.0, "OBV_SMA": 0.0,
            "VISIBLE_SPAN_A": 100.0, "VISIBLE_SPAN_B": 100.0,
            "RSI": 50.0, "RSI_MA": 50.0, "CCI": 0.0, "CCI_MA": 0.0, "ATR_PCT": 0.0,
            "PSAR": 100.0, "STOCH_K": 50.0, "STOCH_D": 50.0, "VWAP": 100.0,
            "ADX": 0.0, "PLUS_DI": 0.0, "MINUS_DI": 0.0,
            "SUPERTREND": 100.0, "FISHER": 0.0, "FISHER_TRIGGER": 0.0,
            "CMF": 0.0, "MOMENTUM": 0.0,
        }
        schemas = _indicator_schemas(pd.DataFrame([row, row]))
        comments = [item["stock_comment"] for item in schemas]

        self.assertIn("aynı seviyede", comments[0])
        self.assertIn("tam 50 seviyesinde", comments[1])
        self.assertIn("tam sıfır seviyesinde", comments[1])
        self.assertIn("DI çizgileri dengede", comments[2])
        self.assertIn("nötr (sıfır)", comments[3])
        self.assertIn("Momentum10 tam sıfır seviyesinde", comments[3])

    def test_missing_indicator_values_are_not_reported_as_bearish(self) -> None:
        from src.technical_commentary_v2 import _indicator_schemas

        schemas = _indicator_schemas(pd.DataFrame([{"Close": 100.0}, {"Close": 100.0}]))
        for item in schemas:
            self.assertIn("hesaplanamadı", item["stock_comment"])
        self.assertNotIn("CMF negatif", schemas[3]["stock_comment"])
        self.assertNotIn("Momentum10 sıfır altında", schemas[3]["stock_comment"])

    def test_literature_note_discloses_data_mining_and_cost_limits(self) -> None:
        result = build_technical_commentary(data_frame(), context(), decision(), {"is_live": False})
        self.assertGreaterEqual(len(result["literature_basis"]), 5)
        self.assertIn("işlem maliyet", result["literature_note"])
        self.assertTrue(any("veri madenciliği" in item for item in result["limitations"]))

    def test_changes_and_scenario_invalidation_are_explicit(self) -> None:
        result = build_technical_commentary(data_frame(), context(), decision(), {"is_live": False})
        self.assertTrue(any("MACD histogramı negatiften pozitife" in item for item in result["changes"]))
        self.assertIn("95.00", result["levels"]["invalidation"])
        self.assertTrue(result["scenario_map"]["strengthen"])
        self.assertTrue(result["scenario_map"]["weaken"])


if __name__ == "__main__":
    unittest.main()
