from __future__ import annotations

import base64
import csv
import io
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from PIL import Image

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.delivery.telegram.config import TelegramSettings
from market_intelligence.delivery.telegram.timeframe_topics import (
    route_timeframe_image,
    timeframe_topic_ids,
)
from scripts.atc_timeframe_visuals import (
    preview_visual_envelopes,
    preview_visual_identity,
    render_card_png,
    select_verified_matches,
)
from tests.test_telegram_routing import environment

IST = ZoneInfo("Europe/Istanbul")


class OldTimeframeTopicTests(unittest.TestCase):
    def test_restore_preexisting_topic_ids_from_old_github_keys(self):
        existing = {
            "TELEGRAM_TOPIC_15M": "177",
            "TELEGRAM_TOPIC_60M": "260",
            "TELEGRAM_TOPIC_4H": "440",
            "TELEGRAM_TOPIC_DAILY": "580",
            "TELEGRAM_TOPIC_HAFTALIK": "620",
        }
        mapped = timeframe_topic_ids(existing)
        self.assertEqual(
            mapped,
            {
                Timeframe.M15: 177, Timeframe.H1: 260, Timeframe.H4: 440,
                Timeframe.D1: 580, Timeframe.W1: 620,
            },
        )
        settings = TelegramSettings.from_mapping(environment())
        envelope = route_timeframe_image(
            settings, mapped, Timeframe.H4,
            identity={"bar": "2026-10-14T18:00", "page": 1},
            payload={"_method": "sendPhoto", "photo_base64": "AA=="},
        )
        self.assertEqual(envelope.message_thread_id, 440)
        self.assertEqual(envelope.payload["_method"], "sendPhoto")
        self.assertEqual(envelope.chat_id, settings.chat_id)
        with self.assertRaisesRegex(ValueError, "KAYITLI"):
            route_timeframe_image(
                settings, mapped, Timeframe.M30, identity={"test": 1}, payload={}
            )

    def test_message_links_never_become_telegram_thread_ids(self):
        configured = {
            "TELEGRAM_CHAT_ID": "-1004439315048",
            "TELEGRAM_TOPIC_SCANS": "5",
        }
        # A historical t.me/c/.../328 link was rejected by the Bot API as
        # 'message thread not found'. No screenshot-derived hardcoded fallback.
        self.assertEqual(timeframe_topic_ids(configured), {})
        self.assertEqual(timeframe_topic_ids({
            "TELEGRAM_CHAT_ID": "-1001234567890"
        }), {})
        self.assertEqual(timeframe_topic_ids({
            **configured, "TELEGRAM_TOPIC_1H": "999"
        })[Timeframe.H1], 999)

    def test_json_mapping_and_disallow_duplicate_topic_reuse(self):
        mapped = timeframe_topic_ids({
            "TELEGRAM_TIMEFRAME_TOPICS": '{"15m":170,"1h":100,"1d":900}',
        })
        self.assertEqual(mapped[Timeframe.D1], 900)
        self.assertEqual(mapped[Timeframe.H1], 100)
        with self.assertRaisesRegex(ValueError, "aynı topic"):
            timeframe_topic_ids({
                "TELEGRAM_TOPIC_15M": "111",
                "TELEGRAM_TOPIC_1H": "111",
            })
        with self.assertRaisesRegex(ValueError, "geçerli"):
            timeframe_topic_ids({"TELEGRAM_TOPIC_1H": "not-a-number"})

    def test_card_png_shows_real_rows_and_existing_interval(self):
        moment = datetime(2026, 10, 14, 18, 0, tzinfo=IST)
        png = render_card_png(
            timeframe="4h", bar_time=moment,
            rows=[("ASELS", 1, "POZITIF"), ("THYAO", 7, "NEGATIF")],
            matched_count=2, total_symbols=610, page=1, pages=1,
        )
        image = Image.open(io.BytesIO(png))
        self.assertEqual(image.format, "PNG")
        self.assertGreater(image.width, 900)
        self.assertGreater(image.height, 350)

    def test_provisional_daily_card_and_complete_csv_share_verified_topic(self):
        settings = TelegramSettings.from_mapping(environment())
        now = datetime(2026, 10, 15, 12, 45, tzinfo=IST)
        slot = now.replace(minute=0)
        finished = [
            (f"TEST{i:03d}", [(1, ("bullish",)), (2, ("bearish",))])
            for i in range(25)
        ]
        finished.append(("UNKNOWN", [(3, ())]))
        cards = preview_visual_envelopes(
            settings, {Timeframe.D1: 328}, now=now, slot=slot,
            finished=finished, expected=630,
        )
        self.assertEqual(len(cards), 2)
        self.assertEqual([e.message_thread_id for e in cards], [328, 328])
        self.assertEqual(cards[0].payload["_method"], "sendPhoto")
        self.assertEqual(cards[1].payload["_method"], "sendDocument")
        img = Image.open(io.BytesIO(base64.b64decode(cards[0].payload["photo_base64"])))
        self.assertGreater(img.width, 900)
        self.assertIn("TEYITSIZ", cards[1].payload["filename"])
        records = list(csv.reader(io.StringIO(
            base64.b64decode(cards[1].payload["document_base64"]).decode("utf-8-sig")
        )))
        self.assertEqual(len(records), 52)  # header + 51 actual matches
        self.assertEqual(records[-1][3], "ESLESME_YON_BELIRSIZ")
        self.assertEqual(
            preview_visual_identity(slot, "photo")["format"], "photo",
        )
        with self.assertRaises(ValueError):
            preview_visual_identity(slot, "unknown")

    def test_stale_and_wrong_ruleset_cannot_become_visible_match(self):
        settings = SimpleNamespace(
            scanner=SimpleNamespace(id="signal.macd_positive_cross", version="x1"),
            ruleset_hash="correct",
            shadow_timeframes=frozenset({Timeframe.D1}),
        )
        inst = SimpleNamespace(instrument_id="stock1", symbol="TEST")
        bar = datetime(2026, 10, 14, 18, tzinfo=IST)
        def entry(version="x1", hash_value="correct", when=bar):
            return ("stock1", "1d", "signal.macd_positive_cross",
                    version, hash_value, when, "match", None, 1, ("bullish",))
        time = datetime(2026, 10, 15, 8, tzinfo=IST)
        _close, _covered, rows = select_verified_matches(
            [inst], [entry(version="old")], [settings], "1d", now=time
        )
        self.assertEqual(rows, [])
        with self.assertRaisesRegex(ValueError, "stale"):
            select_verified_matches(
                [inst], [entry(when=bar - timedelta(days=8))],
                [settings], "1d", now=time,
            )
        _close, _covered, good = select_verified_matches(
            [inst], [entry()], [settings], "1d", now=time
        )
        self.assertEqual(good, [("TEST", 1, "POZITIF")])


if __name__ == "__main__":
    unittest.main()
