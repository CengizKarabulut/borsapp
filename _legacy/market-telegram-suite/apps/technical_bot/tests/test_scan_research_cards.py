import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PIL import Image

from src.scan_card import _level_text, render_scan_cards, render_scan_detail_card
from src.screener_cli import enrich_scan_results


def _frame() -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=140)
    phase = np.linspace(0, 9 * np.pi, len(index))
    close = 100 + np.sin(phase) * 8 + np.linspace(0, 6, len(index))
    return pd.DataFrame(
        {
            "Open": close * 0.998,
            "High": close * 1.012,
            "Low": close * 0.988,
            "Close": close,
            "Volume": np.linspace(25_000_000, 38_000_000, len(index)),
        },
        index=index,
    )


def _item(number: int) -> dict:
    reference = 100.0 + number
    return {
        "ticker": f"T{number:03d}",
        "close": reference,
        "score": 6.0 + number / 10,
        "screens": ["karar_bolgesi", "sikisma_hacim"],
        "setup": "Sıkışma / karar bölgesi",
        "setup_bias": "iki yönlü",
        "rvol": 1.8,
        "bb_width_percentile": 12.0,
        "rsi": 52.0,
        "atr_pct": 2.1,
        "excess_return_20": 1.4,
        "matched_intervals": ["1h", "4h"],
        "structure": {"state": "HH / HL", "event": "Yeni yapı kırılımı yok"},
        "profile": {"poc": reference - 0.5, "vah": reference + 2, "val": reference - 2, "position": "Value Area içinde"},
        "active_levels": {
            "lower": reference - 3,
            "reference_close": reference,
            "upper": reference + 4,
            "lower_source": "Teyitli swing dip",
            "upper_source": "Teyitli swing tepe",
        },
    }


class ScanResearchCardTests(unittest.TestCase):
    def test_fifteen_candidates_make_three_balanced_pages(self) -> None:
        payload = {
            "requested": 758,
            "processed": 629,
            "matched": 15,
            "illiquid": 100,
            "no_match": 514,
            "error_kinds": {},
            "results": [_item(index) for index in range(1, 16)],
            "options": {"bb_rank_max": 20, "rvol_min": 1.5, "rvol_spike": 3.0, "min_turnover": 20_000_000},
            "intervals": ["1h", "4h"],
            "timestamp": "06.09.2026 12:50",
            "freshness": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            cards = render_scan_cards(payload, Path(directory), "borsapy", 90.0)
            self.assertEqual(len(cards), 3)
            sizes = []
            for card in cards:
                self.assertTrue(card.exists())
                with Image.open(card) as image:
                    sizes.append(image.size)
            self.assertEqual(len(set(sizes)), 1, "tarama sayfaları aynı mobil ölçüde olmalı")

    def test_raw_swing_levels_are_not_used_as_active_thresholds(self) -> None:
        item = {
            "close": 21.0,
            "levels": {"swing_low": 27.98, "swing_high": 40.50},
        }
        text = _level_text(item)
        self.assertIn("doğrulanamadı", text)
        self.assertNotIn("27.98", text)
        self.assertNotIn("40.50", text)

    def test_active_levels_must_surround_reference_close(self) -> None:
        valid = {
            "active_levels": {
                "lower": 114.40,
                "reference_close": 117.40,
                "upper": 118.00,
                "lower_source": "Kırılmış swing tepe / destek",
                "upper_source": "Kırılmış swing dip / reclaim",
            }
        }
        self.assertIn("114.40", _level_text(valid))
        invalid = {
            "active_levels": {
                "lower": 120.0,
                "reference_close": 117.40,
                "upper": 130.0,
            }
        }
        self.assertIn("doğrulanamadı", _level_text(invalid))

    def test_candidate_detail_is_one_readable_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.png"
            path = render_scan_detail_card(_item(1), _frame(), output, "1d")
            self.assertEqual(path, output)
            with Image.open(path) as image:
                self.assertGreater(image.width, 800)
                self.assertGreater(image.height, image.width)

    def test_multitimeframe_enrichment_is_saved_on_result(self) -> None:
        payload = {
            "results": [
                {
                    "ticker": "TEST",
                    "intervals": {
                        "1h": {"screens": ["karar_bolgesi"], "setup": "Sıkışma / karar bölgesi"},
                        "4h": {"screens": ["karar_bolgesi"], "setup": "Sıkışma / karar bölgesi"},
                    },
                }
            ]
        }
        frames = {"TEST": {"1h": _frame(), "4h": _frame()}}
        context_1h = {
            "structure": {"state": "HH / HL", "event": "Yeni yapı kırılımı yok"},
            "profile": {"poc": 101.0},
            "active_levels": {"lower": 99.0, "reference_close": 100.0, "upper": 103.0},
        }
        context_4h = {
            "structure": {"state": "LH / HL", "event": "Yeni yapı kırılımı yok"},
            "profile": {"poc": 100.0},
            "active_levels": {"lower": 96.0, "reference_close": 100.0, "upper": 106.0},
        }
        with patch("src.screener_cli._enrich_one_interval", side_effect=[context_1h, context_4h]):
            enriched = enrich_scan_results(payload, frames)
        item = enriched["results"][0]
        self.assertEqual(item["structure"]["state"], "HH / HL")
        self.assertEqual(item["active_levels"]["lower"], 99.0)
        self.assertIn("structure", item["intervals"]["4h"])
        self.assertIn("active_levels", item["intervals"]["1h"])


if __name__ == "__main__":
    unittest.main()
