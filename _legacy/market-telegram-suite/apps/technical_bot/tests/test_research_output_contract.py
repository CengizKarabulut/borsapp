"""Discoverable output-contract tests for the integrated research surface."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import fundamental_card, moving_average_card, research_card, research_chart
from src import research_telegram as telegram
from src.research_commentary_rich import _technical_paragraph_rich
from src.research_theme import apply_white_theme


class ResearchOutputContractTests(unittest.TestCase):
    def test_white_theme_keeps_pine_indicator_colours(self) -> None:
        original_pine_blue = research_chart.PINE_BLUE
        original_rsi_purple = research_chart.RSI_PURPLE

        apply_white_theme()

        self.assertEqual(fundamental_card.BG, "#FFFFFF")
        self.assertEqual(moving_average_card.BG, "#FFFFFF")
        self.assertEqual(research_card.BG, "#FFFFFF")
        self.assertEqual(research_chart.BG, "#FFFFFF")
        self.assertEqual(research_chart.PANEL, "#FFFFFF")
        self.assertNotEqual(research_chart.TEXT, "#FFFFFF")
        self.assertEqual(research_chart.PINE_BLUE, original_pine_blue)
        self.assertEqual(research_chart.RSI_PURPLE, original_rsi_purple)

    def test_rich_technical_commentary_contains_full_evidence_stack(self) -> None:
        report = SimpleNamespace(
            technical={
                "score": 62.0,
                "label": "KARIŞIK",
                "structure": {"state": "HH / HL", "event": "BOS YUKARI"},
                "weekly_structure": {"state": "HH / HL", "event": "YENİ KIRILIM YOK"},
                "monthly_structure": {"state": "LH / HL", "event": "VERİ YETERSİZ"},
                "alpha_trend_state": "FİYAT ÜSTÜNDE / YÜKSELEN",
                "bollinger_state": "ORTA BAND ÜSTÜ",
                "rsi14": 58.4,
                "latest_rsi_divergence": {"kind": "Regular Bullish"},
                "smi": 44.0,
                "smi_signal": 39.0,
                "macd_hist": 0.125,
                "obv_10d_change": 7.2,
                "rvol20": 1.65,
                "atr_pct": 3.4,
                "elliott": {
                    "primary": "YÜKSELİŞ İTKİ / DÜZELTME ADAYI",
                    "alternate": "ABC DÜZELTMESİ",
                    "confidence": 65,
                    "invalidation": 42.25,
                },
            }
        )

        text = _technical_paragraph_rich(report)
        for term in (
            "Günlük",
            "haftalık",
            "aylık",
            "BOS YUKARI",
            "AlphaTrend",
            "Bollinger",
            "RSI",
            "Regular Bullish",
            "SMI",
            "MACD",
            "OBV",
            "RVOL20",
            "ATR",
            "Elliott",
            "invalidation",
        ):
            self.assertIn(term, text)

    def test_research_bundle_sends_six_visuals_before_commentary(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_photo(token, chat_id, thread_id, image_path, caption=""):
            calls.append(("photo", Path(image_path).name))
            return {"result": {"message_id": len(calls), "photo": [{}]}}

        def fake_text(token, chat_id, thread_id, text):
            calls.append(("text", text))
            return {"result": {"message_id": len(calls), "text": text}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [
                root / name
                for name in (
                    "ozet.png",
                    "temel.png",
                    "finansal.png",
                    "degerleme.png",
                    "ma.png",
                    "teknik.png",
                )
            ]
            report = SimpleNamespace(symbol="TEST")
            with (
                patch.object(telegram, "_destination", return_value=("token", "chat", "thread")),
                patch.object(telegram, "_caption", return_value="summary caption"),
                patch.object(telegram, "commentary_messages", return_value=("yorum-1", "yorum-2")),
                patch.object(telegram, "_send_photo", side_effect=fake_photo),
                patch.object(telegram, "_send_text", side_effect=fake_text),
            ):
                results = telegram.send_research_bundle(*paths, report)

        self.assertEqual(
            [kind for kind, _ in calls],
            ["photo", "photo", "photo", "photo", "photo", "photo", "text", "text"],
        )
        self.assertEqual(
            [name for kind, name in calls if kind == "photo"],
            ["ozet.png", "temel.png", "finansal.png", "degerleme.png", "ma.png", "teknik.png"],
        )
        self.assertEqual(len(results), 8)


if __name__ == "__main__":
    unittest.main()
