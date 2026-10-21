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
            "status": "live_open",
            "observed_at": (NOW - timedelta(seconds=2)).isoformat(),
            "received_at": (NOW - timedelta(seconds=1)).isoformat(),
            "last_bar_open": NOW.replace(minute=30).isoformat(),
            "last_bar_close": NOW.replace(minute=45).isoformat(),
            "latest_target_complete": False,
            "observed_prefix_end": NOW.replace(minute=45).isoformat(),
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
        try:
            data["direction_groups"] = live.direction_metadata(data)
        except ValueError:
            pass  # Deliberately malformed-universe test retains its own invalidity.
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
        self.assertEqual(receipt["acknowledged"], {"text": 101, "csv": 102})
        self.assertEqual(receipt["expected_acknowledgements"], ["text", "csv"])
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
        self.assertEqual(retry.send.call_count, 1)
        self.assertTrue(all(call.kwargs["payload"].get("_method") in
            {"sendPhoto", "sendDocument"} for call in retry.send.call_args_list))

    def test_both_directions_and_same_timeframe_intersections_require_every_image_ack(self):
        selected = set(self.symbols[:3])
        def reader(symbol, **_):
            row = synthetic_reader(symbol)
            if symbol in selected:
                for index, direction in enumerate(("bullish", "bullish", "bearish", "bearish")):
                    row["evaluations"][index].update(status="match", findings=[{"direction": direction}])
            return row
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            value = live.prepare_report(folder, reader=reader, clock=lambda: NOW)
            self.assertEqual(len(live.packet_pages(value)), 4)
            first = Mock()
            first.send.side_effect = [101, 102, RuntimeError("interrupted")]
            with self.assertRaises(RuntimeError):
                live.publish_report(folder, now=NOW, transport=first, environ=ENV)
            receipt = json.loads((folder / "publication-receipt.json").read_bytes())
            self.assertEqual(set(receipt["acknowledged"]), {"text", "photo-tf-15m-LONG-001"})
            retry = Mock()
            retry.send.side_effect = range(103, 120)
            done = live.publish_report(folder, now=NOW, transport=retry, environ=ENV)
            self.assertEqual(retry.send.call_count, 4)
            self.assertEqual(set(done["acknowledged"]), set(live.acknowledgement_keys(value)))
            self.assertEqual([len(page["symbols"]) for page in live.packet_pages(value)], [3] * 4)
            repeat = Mock()
            live.publish_report(folder, now=NOW, transport=repeat, environ=ENV)
            repeat.send.assert_not_called()

    def test_tampered_csv_is_rejected_before_transport(self):
        with (self.folder / "live-snapshot.csv").open("ab") as out:
            out.write(b"changed")
        sender = Mock()
        with self.assertRaisesRegex(ValueError, "prepared_file_hash_changed"):
            self.send(sender=sender)
        sender.send.assert_not_called()

    def test_same_message_id_cannot_acknowledge_two_different_parts(self):
        sender = Mock(send=Mock(return_value=101))
        with self.assertRaisesRegex(ValueError, "acknowledgement_required"):
            self.send(sender=sender)
        receipt = json.loads((self.folder / "publication-receipt.json").read_bytes())
        self.assertEqual(receipt["acknowledged"], {"text": 101})
        self.assertNotEqual(receipt.get("status"), "sent")

    def test_duplicated_saved_message_id_is_rejected_without_any_resend(self):
        self.send()
        path = self.folder / "publication-receipt.json"
        value = json.loads(path.read_bytes())
        value["acknowledged"]["csv"] = value["acknowledged"]["text"]
        live.atomic_json(path, value)
        sender = Mock()
        with self.assertRaisesRegex(ValueError, "receipt_identity_changed"):
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

    def test_latest_observed_prefix_is_counted_with_native_end_and_missing_stock_preserved(self):
        prefix_symbol, regular_symbol, missing_symbol = self.symbols[:3]
        prefix_end = NOW.replace(minute=15).isoformat()

        def reader(symbol, **options):
            if symbol == missing_symbol:
                return {"symbol": symbol, "status": "source_unavailable",
                    "source_errors": [{"source": "vendor", "code": "ValueError"}], "evaluations": []}
            row = synthetic_reader(symbol, **options)
            if symbol == prefix_symbol:
                row["metadata"].update(status="incomplete_latest_native_prefix",
                    current_bucket=False, actual_bar_is_open=False, latest_target_complete=False,
                    last_bar_open=NOW.replace(hour=10, minute=45).isoformat(),
                    last_bar_close=NOW.replace(minute=30).isoformat(), observed_prefix_end=prefix_end)
            return row

        folder = Path(self.tmp.name) / "prefix-packet"
        with patch.object(live, "render_png", return_value=b"test-only-png"):
            packet = live.prepare_report(folder, timeframe="45m", symbols=self.symbols[:3],
                reader=reader, clock=lambda: NOW)
        self.assertEqual(packet["counts"], {"usable": 2, "current": 1, "stale": 0,
            "halted": 0, "calculated": 2, "missing": 1, "incomplete_latest": 1})
        self.assertIn("Eksik son aralık: 1", (folder / "live-snapshot.txt").read_text(encoding="utf-8"))
        rows = list(csv.DictReader(io.StringIO((folder / "live-snapshot.csv").read_text(encoding="utf-8-sig"))))
        self.assertEqual(len(rows), 3 * 18)
        prefix_rows = [row for row in rows if row["Hisse"] == prefix_symbol]
        self.assertTrue(all(row["SonHedefAralikTam"] == "False" and row["GozlenenOnEkSonu"] == prefix_end
            and row["GuncelMum"] == "False" and row["SonMumDurumu"] == "incomplete_latest_native_prefix"
            for row in prefix_rows))
        self.assertTrue(all(row["Durum"] == "unknown" and row["SonFiyat"] == ""
            for row in rows if row["Hisse"] == missing_symbol))
        self.assertTrue(all(row["SonHedefAralikTam"] == "False" and row["SonMumDurumu"] == "live_open"
            for row in rows if row["Hisse"] == regular_symbol))

    def test_only_exact_application_value_error_reason_is_exposed_without_provider_secrets(self):
        reason = "Latest derived candle has missing native OHLCV; no gap filling"
        providers = [Mock(), Mock(), Mock()]
        for number, provider in enumerate(providers):
            provider.name = f"vendor_{number}"
        private_error = "https://vendor.example/?sessionid=PRIVATE_TEST_VALUE"
        with patch.object(live, "prepare_frame", side_effect=[ValueError(reason),
                ValueError(private_error), RuntimeError(reason)]):
            row = live.read_symbol("ASELS", timeframe="45m", bindings=(),
                calendar_version="test", providers=providers, clock=lambda: NOW)
        self.assertEqual(row["status"], "source_unavailable")
        self.assertEqual(row["source_errors"], [
            {"source": "vendor_0", "code": "ValueError", "reason": reason},
            {"source": "vendor_1", "code": "ValueError"},
            {"source": "vendor_2", "code": "RuntimeError"}])
        csv_text = live.csv_report({"timeframe": "45m", "rows": [row]}).decode("utf-8-sig")
        self.assertIn(reason, csv_text)
        self.assertNotIn("PRIVATE_TEST_VALUE", json.dumps(row) + csv_text)
        csv_rows = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(len(csv_rows), 18)
        self.assertEqual(json.loads(csv_rows[0]["KaynakHatalari"]), row["source_errors"])

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
