from __future__ import annotations

import copy
import csv
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from scripts import atc_live_snapshot as live
from scripts.atc_universe_seed import load_pinned

IST = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 20, 11, 40, tzinfo=IST)
IDENTITY = {"test-only.py": "independent-application-identity"}
ENV = {"TELEGRAM_CHAT_ID": str(live.CHAT), "TELEGRAM_TOPIC_15M": "6"}


def synthetic_reader(symbol, **_):
    """Actual-source shape, deliberately no feature/provider network work."""
    return {
        "symbol": symbol, "status": "available", "source": "synthetic_test_only",
        "price_basis": "split_adjusted", "snapshot_id": "test:" + symbol,
        "history_bars": 600, "close": 100.0, "source_errors": [],
        "metadata": {
            "current_bucket": True, "usable_latest": True, "actual_bar_is_open": True,
            "observed_at": (NOW - timedelta(seconds=2)).isoformat(),
            "received_at": (NOW - timedelta(seconds=1)).isoformat(),
            "last_bar_open": NOW.replace(minute=30).isoformat(),
            "last_bar_close": NOW.replace(minute=45).isoformat(),
        },
        "evaluations": [{"number": n, "code": live.scanner_code(n),
            "scanner_id": scanner_id, "version": "test", "ruleset_hash": "test",
            "status": "no_match", "error_code": None, "findings": []}
            for n, scanner_id in enumerate(live.SCANNER_ORDER, 1)],
    }


class LivePreparedPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory()
        cls.symbols = load_pinned(Path("config/atc_630_symbols.txt"))
        with patch.object(live, "implementation_hashes", return_value=IDENTITY), \
                patch.object(live, "render_png", return_value=b"test-only-png"):
            cls.packet = live.prepare_report(cls.template.name, reader=synthetic_reader,
                workers=2, clock=lambda: NOW)

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "packet"
        shutil.copytree(self.template.name, self.folder)
        identity = patch.object(live, "implementation_hashes", return_value=IDENTITY)
        identity.start()
        self.addCleanup(identity.stop)

    def change_report(self, change):
        data = json.loads((self.folder / "live-snapshot.json").read_bytes())
        change(data)
        live.atomic_json(self.folder / "live-snapshot.json", data)
        manifest = json.loads((self.folder / "prepared-packet.json").read_bytes())
        manifest["files"]["live-snapshot.json"] = sha256(
            (self.folder / "live-snapshot.json").read_bytes()).hexdigest()
        live.atomic_json(self.folder / "prepared-packet.json", manifest)

    def send(self, *, sender=None, now=NOW, env=None):
        return live.publish_report(self.folder, now=now,
            transport=sender if sender is not None else Mock(send=Mock(side_effect=[101, 102, 103])),
            environ=ENV if env is None else env)

    def test_all_630_symbols_and_18_rules_remain_without_persisting(self):
        packet = self.packet
        self.assertEqual(packet["symbol_count"], 630)
        self.assertEqual(packet["counts"]["current"], 630)
        self.assertEqual(packet["counts"]["usable"], 630)
        self.assertEqual(packet["counts"]["stale"], 0)
        self.assertEqual(packet["counts"]["missing"], 0)
        self.assertTrue(packet["provisional"])
        self.assertEqual(packet["confirmed_store_writes"], 0)
        self.assertEqual(packet["orders_sent"], 0)
        data = list(csv.DictReader(io.StringIO(
            (self.folder / "live-snapshot.csv").read_text(encoding="utf-8-sig"))))
        self.assertEqual(len(data), 630 * 18)
        self.assertEqual({row["Hisse"] for row in data}, set(self.symbols))
        for symbol in self.symbols:
            self.assertEqual({row["Tarama"] for row in data if row["Hisse"] == symbol},
                             {live.scanner_code(n) for n in range(1, 19)})
        self.assertTrue(all(row["Teyit"] == "CANLI / TEYITSIZ" for row in data))
        self.assertFalse((self.folder / "publication-receipt.json").exists())

    def test_publish_uses_unchanged_prepared_files_without_refetch(self):
        sender = Mock()
        sender.send.side_effect = [101, 102, 103]
        with patch.object(live, "vendor_chain", side_effect=AssertionError("must not refetch")), \
                patch.object(live, "prepare_report", side_effect=AssertionError("must not recompute")):
            receipt = self.send(sender=sender)
        self.assertEqual(receipt["status"], "sent")
        self.assertEqual(receipt["acknowledged"], {"text": 101, "photo": 102, "csv": 103})
        for call in sender.send.call_args_list:
            self.assertEqual(call.kwargs["chat_id"], live.CHAT)
            self.assertEqual(call.kwargs["message_thread_id"], 6)
        again = Mock()
        self.send(sender=again)
        again.send.assert_not_called()

    def test_partial_delivery_retries_only_unacknowledged_parts(self):
        first = Mock()
        first.send.side_effect = [101, RuntimeError("transport disconnected")]
        with self.assertRaises(RuntimeError):
            self.send(sender=first)
        stored = json.loads((self.folder / "publication-receipt.json").read_bytes())
        self.assertEqual(stored["acknowledged"], {"text": 101})
        retry = Mock()
        retry.send.side_effect = [102, 103]
        result = self.send(sender=retry)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(retry.send.call_count, 2)
        self.assertTrue(all(call.kwargs["payload"].get("_method") in
            {"sendPhoto", "sendDocument"} for call in retry.send.call_args_list))

    def test_tampered_csv_is_rejected_before_transport(self):
        with (self.folder / "live-snapshot.csv").open("ab") as out:
            out.write(b"changed")
        sender = Mock()
        with self.assertRaisesRegex(ValueError, "prepared_file_hash_changed"):
            self.send(sender=sender)
        sender.send.assert_not_called()

    def test_implementation_change_is_rejected(self):
        with patch.object(live, "implementation_hashes", return_value={"changed.py": "changed"}), \
                self.assertRaisesRegex(ValueError, "implementation_changed"):
            self.send()

    def test_wrong_chat_or_timeframe_topic_never_uses_fallback(self):
        for env in ({**ENV, "TELEGRAM_CHAT_ID": "-1001"},
                    {**ENV, "TELEGRAM_TOPIC_15M": "7"}):
            with self.subTest(env=env):
                sender = Mock()
                with self.assertRaises(ValueError):
                    self.send(sender=sender, env=env)
                sender.send.assert_not_called()

    def test_incomplete_or_wrong_symbol_universe_cannot_publish(self):
        for wrong_symbol in (False, True):
            with self.subTest(wrong_symbol=wrong_symbol):
                def mutate(data, wrong_symbol=wrong_symbol):
                    if wrong_symbol:
                        data["rows"][0]["symbol"] = "NOT_PINNED"
                    else:
                        data["rows"].pop()
                        data["symbol_count"] = 629
                original = copy.deepcopy(self.packet)
                live.atomic_json(self.folder / "live-snapshot.json", original)
                self.change_report(mutate)
                sender = Mock()
                with self.assertRaisesRegex(ValueError, "complete_pinned"):
                    self.send(sender=sender)
                sender.send.assert_not_called()

    def test_90_percent_usable_source_boundary_and_lower_coverage(self):
        def stale(data):
            for row in data["rows"][:63]:
                row["metadata"]["current_bucket"] = False
                row["metadata"]["usable_latest"] = False
            data["counts"].update(current=567, usable=567, stale=63)
        self.change_report(stale)
        self.assertEqual(self.send()["status"], "sent")
        (self.folder / "publication-receipt.json").unlink()
        def below(data):
            data["rows"][63]["metadata"]["current_bucket"] = False
            data["rows"][63]["metadata"]["usable_latest"] = False
            data["counts"].update(current=566, usable=566, stale=64)
        self.change_report(below)
        sender = Mock()
        with self.assertRaisesRegex(ValueError, "coverage_below_90"):
            self.send(sender=sender)
        sender.send.assert_not_called()

    def test_oldest_observation_expiry_and_future_observation(self):
        with self.assertRaisesRegex(ValueError, "snapshot_expired"):
            self.send(now=NOW + timedelta(minutes=31))
        with self.assertRaisesRegex(ValueError, "snapshot_expired"):
            self.send(now=NOW - timedelta(minutes=1))

    def test_usable_last_actual_candle_is_not_mislabeled_current(self):
        def older_bucket(data):
            for row in data["rows"]:
                row["metadata"]["current_bucket"] = False
                row["metadata"]["actual_bar_is_open"] = False
            data["counts"].update(current=0)
        self.change_report(older_bucket)
        self.assertEqual(self.send()["status"], "sent")

    def test_missing_stock_still_has_18_explicit_unknown_csv_rows(self):
        packet = copy.deepcopy(self.packet)
        symbol = packet["rows"][0]["symbol"]
        packet["rows"][0] = {"symbol": symbol, "status": "source_unavailable",
            "source_errors": [{"source": "vendor", "code": "ValueError"}], "evaluations": []}
        rows = list(csv.DictReader(io.StringIO(live.csv_report(packet).decode("utf-8-sig"))))
        missing = [row for row in rows if row["Hisse"] == symbol]
        self.assertEqual(len(missing), 18)
        self.assertTrue(all(row["Durum"] == "unknown" and row["Hata"] == "source_unavailable"
                            and row["SonFiyat"] == "" for row in missing))

    def test_two_direction_all_rule_summary_fits_one_telegram_message(self):
        packet = copy.deepcopy(self.packet)
        for row in packet["rows"]:
            for scan in row["evaluations"]:
                scan["status"] = "match"
                scan["findings"] = [{"direction": direction, "plan": None}
                    for direction in ("bullish", "bearish")]
        text = live.render_summary(packet)
        self.assertLessEqual(len(text), 4096)
        self.assertIn("CANLI / TEYİTSİZ", text)

    def test_transport_requires_positive_actual_acknowledgement(self):
        sender = Mock()
        sender.send.return_value = 0
        with self.assertRaisesRegex(ValueError, "acknowledgement_required"):
            self.send(sender=sender)
        self.assertFalse((self.folder / "publication-receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
