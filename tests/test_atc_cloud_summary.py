from __future__ import annotations

import unittest
from datetime import date

from scripts.atc_cloud_summary import prepare_daily_report


def row(symbol, status, bar_time="2026-10-14T15:00:00+00:00", scanner=1):
    return {
        "Hisse": symbol,
        "ZamanDilimi": "1d",
        "TaramaNo": str(scanner),
        "Durum": status,
        "MumKapanisiUTC": bar_time,
    }


class CloudSummaryTests(unittest.TestCase):
    def test_current_evaluated_rows_produce_directional_summary(self):
        text, coverage = prepare_daily_report(
            [
                row("ASELS", "POZITIF"),
                row("AKBNK", "KOSUL_YOK"),
                row("ASELS", "NEGATIF", scanner=2),
            ],
            as_of=date(2026, 10, 14),
        )
        self.assertEqual(coverage["fresh_symbols"], 2)
        self.assertEqual(coverage["expected_symbols"], 2)
        self.assertEqual(coverage["matched_conditions"], 2)
        self.assertIn("01: +1 -0", text)
        self.assertIn("02: +0 -1", text)

    def test_old_and_unknown_results_cannot_generate_new_report(self):
        with self.assertRaisesRegex(ValueError, "Güncel tarama kapsamı"):
            prepare_daily_report(
                [row("ASELS", "POZITIF", "2026-10-13T15:00:00+00:00"),
                 row("AKBNK", "VERI_YOK")],
                as_of=date(2026, 10, 14),
            )

    def test_partial_coverage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Güncel tarama kapsamı"):
            prepare_daily_report(
                [row("ASELS", "POZITIF"), row("AKBNK", "VERI_YOK")],
                as_of=date(2026, 10, 14),
            )


if __name__ == "__main__":
    unittest.main()
