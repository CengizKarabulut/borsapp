from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.fundamental_analysis import Factor, FundamentalReport
from src.research_engine import ResearchDimension
from src.research_risk import _coverage_gate_dimension, _quality_dimension, _risk_engine
from src.research_technical import _elliott_context, _structure_event, _structure_score
from src.research_telegram import _verified_message


class ResearchFinalizationTests(unittest.TestCase):
    def test_company_quality_excludes_valuation_factor(self) -> None:
        fundamental = FundamentalReport(
            symbol="TEST",
            company_name="Test",
            price=100.0,
            sector="Industrials",
            profile="GENERIC",
            overall_score=3.0,
            coverage=1.0,
            factors=(
                Factor("Değerleme", 1.0, 1.0, ""),
                Factor("Büyüme", 5.0, 1.0, ""),
                Factor("Kârlılık", 5.0, 1.0, ""),
                Factor("Bilanço Sağlığı", 5.0, 1.0, ""),
                Factor("Nakit Akışı", 5.0, 1.0, ""),
            ),
            positives=(),
            risks=(),
            metrics={},
            note="",
        )
        dimension = _quality_dimension(SimpleNamespace(fundamental=fundamental))
        self.assertEqual(dimension.score, 100.0)
        self.assertEqual(dimension.coverage, 1.0)

    def test_low_coverage_dimension_is_not_scored(self) -> None:
        dimension = ResearchDimension("Kâr Kalitesi", 0.0, 0.27, "ZAYIF", "Sınırlı veri.")
        gated = _coverage_gate_dimension(dimension)
        self.assertIsNone(gated.score)
        self.assertEqual(gated.label, "VERİ YETERSİZ")
        self.assertIn("%27", gated.summary)

    def test_missing_evidence_does_not_create_fake_risk(self) -> None:
        main, risks = _risk_engine(
            "GENERIC",
            {"metrics": {}, "earnings_quality_score": None, "earnings_quality_coverage": 0.0},
            {"score": None, "coverage": 0.0},
            {"score": None, "average_turnover_20": None},
            (),
        )
        self.assertIsNone(main)
        self.assertEqual(risks, ())

    def test_downtrend_breaking_last_lower_high_is_upward_choch(self) -> None:
        structure = {
            "state": "LH / LL",
            "bos": "Swing High üzeri BOS",
            "last_high": {"label": "LH", "price": 110.0},
            "last_low": {"label": "LL", "price": 90.0},
        }
        self.assertEqual(_structure_event(structure), "CHoCH YUKARI")

    def test_uptrend_breaking_last_higher_low_is_downward_choch(self) -> None:
        structure = {
            "state": "HH / HL",
            "bos": "Swing Low altı BOS",
            "last_high": {"label": "HH", "price": 120.0},
            "last_low": {"label": "HL", "price": 105.0},
        }
        self.assertEqual(_structure_event(structure), "CHoCH AŞAĞI")

    def test_missing_mtf_structure_is_not_neutral_score(self) -> None:
        self.assertIsNone(_structure_score("—"))
        self.assertEqual(_structure_score("LH / HL"), 50.0)

    def test_elliott_stays_uncertain_with_too_few_confirmed_swings(self) -> None:
        result = _elliott_context(
            [
                {"type": "low", "price": 90.0},
                {"type": "high", "price": 100.0},
                {"type": "low", "price": 95.0},
            ],
            {"state": "HH / HL", "bos": "Yeni yapı kırılımı yok"},
        )
        self.assertEqual(result["primary"], "BELİRSİZ")
        self.assertLess(result["confidence"], 50)

    def test_telegram_result_must_match_requested_topic(self) -> None:
        payload = {"ok": True, "result": {"message_id": 42, "message_thread_id": 3982}}
        self.assertIs(_verified_message(payload, "3982"), payload)
        with self.assertRaises(RuntimeError):
            _verified_message(payload, "9999")

    def test_telegram_result_requires_message_id(self) -> None:
        with self.assertRaises(TypeError):
            _verified_message({"ok": True, "result": {}}, "")


if __name__ == "__main__":
    unittest.main()
