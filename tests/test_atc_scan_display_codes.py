from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.scanning.display_codes import (
    SCANNER_ORDER,
    direction_display,
    scanner_code,
    scanner_code_from_id,
)
from scripts.atc_confirmed_intersections import export_intersections_csv
from scripts.atc_export_dashboard import status_label
from scripts.atc_telegram_briefings import summarize_preview

IST = ZoneInfo("Europe/Istanbul")


class AtcPublicScanCodesTests(unittest.TestCase):
    def test_exact_uploaded_pine_a_to_i_then_numeric_ten_to_eighteen(self):
        self.assertEqual(len(SCANNER_ORDER), 18)
        self.assertEqual(len(set(SCANNER_ORDER)), 18)
        self.assertEqual(
            [scanner_code(i) for i in range(1, 19)],
            list("ABCDEFGHI") + [str(i) for i in range(10, 19)],
        )
        for number, name in enumerate(SCANNER_ORDER, 1):
            self.assertEqual(scanner_code_from_id(name), scanner_code(number))
        for invalid in (0, 19, True):
            with self.assertRaises(ValueError):
                scanner_code(invalid)
        with self.assertRaises(ValueError):
            scanner_code_from_id("unknown.formula")

    def test_direction_labels_never_invent_long_or_short(self):
        labels = {
            (): "?",
            ("bullish",): "LONG",
            ("bearish",): "SHORT",
            ("neutral",): "NÖTR",
            ("bullish", "bearish"): "KARMA",
            ("mixed",): "KARMA",
        }
        for evidence, target in labels.items():
            with self.subTest(evidence=evidence):
                self.assertEqual(
                    direction_display(status_label("match", evidence)), target,
                )
        with self.assertRaises(ValueError):
            direction_display("HESAPLANAMADI")

    def test_provisional_text_reports_compact_codes_and_real_directions(self):
        now = datetime(2026, 10, 16, 12, 45, tzinfo=IST)
        message, n = summarize_preview(
            [
                ("ASELS", [(1, ("bullish",)), (10, ("neutral",))]),
                ("THYAO", [(12, ("bearish",)), (18, ("bearish",))]),
                ("BIMAS", [(3, ("bullish", "bearish"))]),
                ("TUPRS", [(4, ())]),
            ],
            now=now,
        )
        self.assertEqual(n, 6)
        self.assertIn("A · LONG · 1 · #ASELS", message)
        self.assertIn("10 · NÖTR · 1 · #ASELS", message)
        self.assertIn("12 · SHORT · 1 · #THYAO", message)
        self.assertIn("18 · SHORT · 1 · #THYAO", message)
        self.assertIn("C · KARMA · 1 · #BIMAS", message)
        self.assertIn("D · ? · 1 · #TUPRS", message)
        self.assertNotIn("MACD", message)
        self.assertNotIn("RSI", message)
        self.assertIn("TEYİTSİZ", message)

    def test_intersection_csv_uses_only_codes_not_indicator_names(self):
        sample = [{
            "symbol": "TEST", "direction": "bearish",
            "timeframe_count": 2, "count": 2,
            "timeframes": {"1h": {}, "4h": {}},
            "scanners": [SCANNER_ORDER[0], SCANNER_ORDER[12]],
            "opposing_timeframes": [],
        }]
        closes = {
            "1h": datetime(2026, 10, 16, 14, tzinfo=IST),
            "4h": datetime(2026, 10, 16, 14, tzinfo=IST),
        }
        raw = export_intersections_csv(
            sample, closes, generated=datetime(2026, 10, 16, 15, tzinfo=IST),
        ).decode("utf-8-sig")
        records = list(csv.reader(io.StringIO(raw)))
        self.assertEqual(records[0][5], "TaramaKodlari")
        self.assertEqual(records[1][1], "SHORT")
        self.assertEqual(records[1][5], "A,13")
        self.assertNotIn("signal.macd", raw)
        self.assertNotIn("failed_breakout", raw)


if __name__ == "__main__":
    unittest.main()
