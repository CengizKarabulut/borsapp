from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.atc_telegram_briefings import (
    morning_messages,
    pivot_levels,
    summarize_preview,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")


class AtcTelegramBriefingTests(unittest.TestCase):
    def test_pivot_uses_previous_high_low_close(self):
        s1, s2, pivot, r1, r2 = pivot_levels(110, 90, 100)
        self.assertEqual((s2, s1, pivot, r1, r2), (80, 90, 100, 110, 120))
        with self.assertRaises(ValueError):
            pivot_levels(90, 110, 100)

    def test_morning_report_contains_all_symbols_in_excel_friendly_csv(self):
        samples = [
            (f"TEST{i:03d}", (90., 80., 100., 110., 120.), i * 2000, "TEYITLI")
            for i in range(630)
        ]
        text, csv_data = morning_messages(datetime(2026, 10, 14).date(), samples)
        self.assertIn("630 hisse", text)
        self.assertIn("önceki seans", text)
        self.assertIn("S2 80.00", text)
        data = list(csv.reader(io.StringIO(csv_data.decode("utf-8-sig"))))
        self.assertEqual(len(data), 631)  # header and all 630 shares
        self.assertEqual(data[0][2:7], ["S2", "S1", "Pivot", "R1", "R2"])
        self.assertEqual(data[1][2:7], ["80.0000", "90.0000", "100.0000", "110.0000", "120.0000"])

    def test_missing_data_does_not_fabricate_pivot_supports(self):
        samples = [
            (f"TEST{i:03d}", (90., 80., 100., 110., 120.), i, "TEYITLI")
            for i in range(590)
        ]
        samples += [(f"TEST{i:03d}", None, None, "VERI_YOK") for i in range(590, 630)]
        text, data = morning_messages(datetime(2026, 10, 14).date(), samples)
        self.assertIn("veri eksik 40", text)
        self.assertIn("VERI_YOK", data.decode("utf-8-sig"))
        with self.assertRaisesRegex(ValueError, "coverage"):
            morning_messages(datetime(2026, 10, 14).date(), samples[:30])

    def test_open_bar_preview_is_never_described_as_confirmed(self):
        stamp = datetime(2026, 10, 15, 12, 45, tzinfo=ISTANBUL)
        text, matches = summarize_preview(
            [("ASELS", [(1, ("bullish",))]), ("THYAO", [(1, ("bullish",)), (9, ("bullish",))])],
            now=stamp,
        )
        self.assertIn("CANLI / TEYİTSİZ", text)
        self.assertIn("şu anda kapansaydı", text)
        self.assertIn("#ASELS", text)
        self.assertIn("630", text)
        self.assertEqual(matches, 3)


if __name__ == "__main__":
    unittest.main()
