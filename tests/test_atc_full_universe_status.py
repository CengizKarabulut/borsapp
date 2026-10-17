"""Confirmed scanner matches must never vanish when direction is unknown."""
from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scanning.display_codes import SCANNER_ORDER
from scripts.atc_full_universe_status import universe_status_csv
from scripts.atc_timeframe_visuals import (
    render_card_png,
    select_verified_matches,
)

IST = ZoneInfo("Europe/Istanbul")
BAR = datetime(2026, 10, 16, 18, tzinfo=IST)
SCANNER = SCANNER_ORDER[0]


def binding():
    return SimpleNamespace(
        scanner=SimpleNamespace(id=SCANNER, version="v1"),
        ruleset_hash="valid", shadow_timeframes=frozenset({Timeframe.D1}),
    )


def member(index):
    return SimpleNamespace(instrument_id=f"i-{index}", symbol=f"SYM{index:03d}")


def eval_row(index, status, directions=(), *, bar_time=BAR, version="v1"):
    return (
        f"i-{index}", "1d", SCANNER, version, "valid",
        bar_time, status, None, f"eid-{index}", directions,
    )


def parsed(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


class FullUniverseAuditTests(unittest.TestCase):
    def test_missing_direction_does_not_remove_a_real_match_from_png_list(self):
        members = [member(i) for i in range(3)]
        ev = [
            eval_row(0, "match", ("bullish",)),
            eval_row(1, "match", ()),
            eval_row(2, "no_match"),
        ]
        close, covered, matches = select_verified_matches(
            members, ev, [binding()], "1d", now=BAR + timedelta(hours=1),
        )
        self.assertEqual(close, BAR)
        self.assertEqual(covered, 3)
        self.assertEqual(matches, [
            ("SYM000", 1, "POZITIF"),
            ("SYM001", 1, "ESLESME_YON_BELIRSIZ"),
        ])
        image = render_card_png(
            timeframe="1d", bar_time=BAR, rows=matches,
            matched_count=len(matches), total_symbols=630, page=1, pages=1,
        )
        self.assertGreater(len(image), 1000)
        data, counts = universe_status_csv(members, ev, [binding()], "1d", BAR)
        rows = parsed(data)
        self.assertEqual(counts["match"], len(matches))
        self.assertEqual([r["A"] for r in rows], ["LONG", "?", "KOSUL_YOK"])

    def test_every_stock_has_a_row_including_missing_and_stale(self):
        members = [member(i) for i in range(630)]
        ev = [
            eval_row(0, "match", ("bearish",)),
            eval_row(1, "match"),
            eval_row(2, "no_match"),
            eval_row(3, "unknown"),
            eval_row(4, "match", ("bullish",), version="old"),
            eval_row(5, "no_match", bar_time=BAR - timedelta(days=1)),
        ]
        data, counts = universe_status_csv(members, ev, [binding()], "1d", BAR)
        rows = parsed(data)
        self.assertEqual(len(rows), 630)
        self.assertEqual(len({r["Hisse"] for r in rows}), 630)
        statuses = {r["Hisse"]: r["A"] for r in rows}
        self.assertEqual(statuses["SYM000"], "SHORT")
        self.assertEqual(statuses["SYM001"], "?")
        self.assertEqual(statuses["SYM002"], "KOSUL_YOK")
        self.assertEqual(statuses["SYM003"], "HESAPLANAMADI")
        self.assertEqual(statuses["SYM004"], "SURUM_UYUSMAZLIGI")
        self.assertEqual(statuses["SYM005"], "ESKI_MUM")
        self.assertEqual(statuses["SYM006"], "VERI_YOK")
        self.assertEqual(statuses["SYM000"]["A"] if False else rows[0]["10"], "DESTEKLENMIYOR")
        self.assertEqual(counts["members"], 630)
        self.assertEqual(counts["expected_evaluations"], 630)
        self.assertEqual(counts["confirmed_evaluations"], 3)
        self.assertEqual(counts["unresolved_evaluations"], 627)
        self.assertEqual(counts["match"], 2)

    def test_no_match_is_explicit_not_empty_or_missing(self):
        members = [member(i) for i in range(630)]
        ev = [eval_row(i, "no_match") for i in range(630)]
        data, counts = universe_status_csv(members, ev, [binding()], "1d", BAR)
        self.assertEqual(counts["match"] if "match" in counts else 0, 0)
        self.assertEqual(counts["KOSUL_YOK"], 630)
        self.assertTrue(all(row["HisseDurumu"] == "KOSUL_YOK" for row in parsed(data)))


if __name__ == "__main__":
    unittest.main()
