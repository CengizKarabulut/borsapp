from __future__ import annotations

import io
import unittest
from datetime import date

from PIL import Image

from scripts.atc_morning_visuals import build_visual_pages, render_morning_png


class AtcMorningVisualCardsTests(unittest.TestCase):
    def test_630_verified_pivots_produce_32_paginated_real_pngs(self):
        items = [
            (f"EQ{i:03d}", (96.0, 92.0, 100.0, 104.0, 108.0),
             float(i), "TEYITLI", "yfinance/raw")
            for i in range(630)
        ]
        pages = build_visual_pages(
            last_session=date(2026, 10, 15), rows=items,
            total_verified=630,
        )
        self.assertEqual(len(pages), 32)
        self.assertEqual(sum(len(entries) for _, entries, _ in pages), 630)
        self.assertEqual([len(entries) for _, entries, _ in pages[:2]], [20, 20])
        self.assertEqual(len(pages[-1][1]), 10)
        self.assertEqual(pages[0][1][0][0], "EQ000")
        self.assertEqual(pages[-1][1][-1][0], "EQ629")
        for page, _entries, pic in pages:
            with self.subTest(page=page):
                image = Image.open(io.BytesIO(pic))
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.width, 1536)
                self.assertGreater(image.height, 500)
                self.assertGreater(len(pic), 2000)

    def test_missing_price_is_shown_as_missing_not_fabricated(self):
        picture = render_morning_png(
            last_session=date(2026, 10, 15),
            rows=[("ASELS", None, None, "VERI_YOK", "source:missing")],
            page=1, pages=32, total_verified=629,
        )
        self.assertGreater(len(picture), 2000)

    def test_visual_is_identical_regardless_of_provider_source_metadata(self):
        """CSV keeps the vendor; the actual PNG must not reveal it."""
        basic = ("ASELS", (96., 92., 100., 104., 108.),
                 150000., "TEYITLI")
        first = render_morning_png(
            last_session=date(2026, 10, 15),
            rows=[(*basic, "borsapy/raw")],
            page=1, pages=32, total_verified=630,
        )
        second = render_morning_png(
            last_session=date(2026, 10, 15),
            rows=[(*basic, "yfinance/split_adjusted")],
            page=1, pages=32, total_verified=630,
        )
        self.assertEqual(first, second)

    def test_mismatched_inventory_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "630"):
            build_visual_pages(
                last_session=date(2026, 10, 15),
                rows=[("ASELS", (90, 80, 100, 110, 120), 1, "TEYITLI")],
                total_verified=1,
            )


if __name__ == "__main__":
    unittest.main()
