from __future__ import annotations

import base64
import csv
import io
import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from PIL import Image

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.delivery.telegram.config import TelegramSettings
from scripts.atc_confirmed_intersections import (
    build_confirmed_intersections, export_intersections_csv, make_envelopes,
)
from scripts.atc_export_dashboard import SCANNER_ORDER
from tests.test_telegram_routing import environment

IST = ZoneInfo("Europe/Istanbul")


class ConfirmedIntersectionTests(unittest.TestCase):
    def fixture(self, *, confirmed=True):
        members = tuple(
            SimpleNamespace(instrument_id=f"member-{n}", symbol=f"TEST{n}")
            for n in range(3)
        )
        bindings = tuple(SimpleNamespace(
            scanner=SimpleNamespace(id=name, version="v1"),
            ruleset_hash="expected",
            shadow_timeframes=frozenset((Timeframe.H1, Timeframe.D1)),
        ) for name in SCANNER_ORDER[:2])
        evaluations = []
        dates = {"1h": datetime(2026, 10, 15, 15, tzinfo=IST),
                 "1d": datetime(2026, 10, 14, 18, tzinfo=IST)}
        for tf, timestamp in dates.items():
            for member in members:
                for name in SCANNER_ORDER[:2]:
                    direction = ("bullish",) if member.symbol == "TEST0" else ("bearish",)
                    status = "match" if member.symbol == "TEST0" else "no_match"
                    evaluations.append((
                        member.instrument_id, tf, name,
                        "v1" if confirmed else "mismatched", "expected",
                        timestamp, status, None, 1, direction,
                    ))
        return members, evaluations, bindings

    def test_only_verified_two_scanners_in_two_timeframes_qualify(self):
        members, evaluations, bindings = self.fixture()
        rows, closings, coverages, issues = build_confirmed_intersections(
            members, evaluations, bindings, ("1h", "1d"),
            now=datetime(2026, 10, 15, 16, tzinfo=IST),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "TEST0")
        self.assertEqual(rows[0]["timeframe_count"], 2)
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(coverages, {"1h": 3, "1d": 3})
        self.assertEqual(issues, {})
        csv_bytes = export_intersections_csv(
            rows, closings, generated=datetime(2026, 10, 15, 16, tzinfo=IST),
        )
        table = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
        self.assertEqual(len(table), 2)
        self.assertEqual(table[1][0], "TEST0")
        settings = TelegramSettings.from_mapping(environment())
        cards = make_envelopes(
            settings, 28330, ranked=rows, closings=closings,
            coverage=coverages, now=datetime(2026, 10, 15, 16, tzinfo=IST),
        )
        self.assertEqual(len(cards), 2)
        self.assertEqual(tuple(x.message_thread_id for x in cards), (28330, 28330))
        self.assertEqual(cards[0].payload["_method"], "sendPhoto")
        image = Image.open(io.BytesIO(base64.b64decode(cards[0].payload["photo_base64"])))
        self.assertEqual(image.format, "PNG")

    def test_stale_or_wrong_scanner_version_never_becomes_intersection(self):
        members, evaluations, bindings = self.fixture(confirmed=False)
        rows, *_ = build_confirmed_intersections(
            members, evaluations, bindings, ("1h", "1d"),
            now=datetime(2026, 10, 15, 16, tzinfo=IST),
        )
        self.assertEqual(rows, [])
        # Insufficient two-frame overlap must not invent a global intersection.
        with self.assertRaisesRegex(ValueError, "two sufficiently covered"):
            build_confirmed_intersections(
                members, [v for v in evaluations if v[1] == "1d"], bindings,
                ("1h", "1d"), now=datetime(2026, 10, 15, 16, tzinfo=IST),
            )


if __name__ == "__main__":
    unittest.main()
