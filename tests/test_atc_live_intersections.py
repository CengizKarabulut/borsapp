from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from scripts import atc_live_intersections as report
from scripts import atc_live_snapshot as live
from scripts.atc_structure_report import atomic_json
from scripts.atc_universe_seed import load_pinned

NOW = datetime(2026, 10, 21, 3, 0, tzinfo=live.IST)
SESSION = datetime(2026, 10, 20, tzinfo=live.IST).date()
HASHES = {"fixture.py": "f" * 64}
ENV = {"TELEGRAM_CHAT_ID": str(live.CHAT), "TELEGRAM_TOPIC_INTERSECTIONS": "28330"}
BINDINGS = tuple(SimpleNamespace(scanner=SimpleNamespace(id=name, version="fixture-v1"),
                                 ruleset_hash=f"{index:064x}")
                 for index, name in enumerate(report.SCANNER_ORDER, 1))


def source_run(tf, run_id=42):
    return {"run_id": run_id, "head_sha": "a" * 40, "head_branch": "main",
        "event": "schedule", "head_repository": report.REPOSITORY,
        "artifact_name": "atc-scheduled-snapshot-" + tf}


def make_packet(folder, tf, symbols, *, matches=45, now=NOW):
    rows = []
    for index, symbol in enumerate(symbols):
        scans = [{"number": number, "scanner_id": binding.scanner.id,
            "version": binding.scanner.version, "ruleset_hash": binding.ruleset_hash,
            "status": "match" if index < matches and number in (1, 2) else "no_match",
            "findings": [{"direction": "bullish", "plan": {"entry": 100, "stop": 90}}]
                        if index < matches and number in (1, 2) else []}
            for number, binding in enumerate(BINDINGS, 1)]
        rows.append({"symbol": symbol, "status": "available", "source": "fixture_vendor",
            "evaluations": scans, "metadata": {"usable_latest": True,
                "observed_at": (now - timedelta(minutes=2)).isoformat(),
                "received_at": (now - timedelta(minutes=1)).isoformat(),
                "last_bar_open": "2026-10-20T18:00:00+03:00",
                "last_bar_close": "2026-10-20T18:45:00+03:00" if tf == "45m" else "2026-10-20T18:15:00+03:00",
                "last_actual_native_open": "2026-10-20T18:00:00+03:00",
                "source_grid": report.NATIVE_45M_GRID if tf == "45m" else "fixture_native_grid"}})
    packet = {"version": live.VERSION, "timeframe": tf, "symbol_count": 630,
        "provisional": True, "confirmed_store_writes": 0, "orders_sent": 0,
        "counts": {"usable": 630}, "observation_start": (now - timedelta(minutes=2)).isoformat(),
        "observation_end": (now - timedelta(minutes=1)).isoformat(), "rows": rows}
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / "live-snapshot.json", packet)
    for name in live.FILES[1:]:
        (folder / name).write_bytes(b"actual-prepared-fixture-bytes")
    reseal(folder, tf)


def reseal(folder, tf):
    manifest = {"version": live.VERSION, "implementation_files": HASHES,
        "files": {name: sha256((folder / name).read_bytes()).hexdigest() for name in live.FILES}}
    atomic_json(folder / "prepared-packet.json", manifest)
    atomic_json(folder / "publication-receipt.json", {"status": "sent", "chat_id": live.CHAT,
        "topic_id": live.TOPICS[tf], "packet_sha256": sha256((folder / "prepared-packet.json").read_bytes()).hexdigest(),
        "acknowledged": {"text": 101, "photo": 102, "csv": 103}})


class LatestKnownIntersectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory()
        cls.symbols = load_pinned(Path("config/atc_630_symbols.txt"))
        cls.packets = Path(cls.template.name) / "packets"
        for tf in ("15m", "1h", "45m"):
            make_packet(cls.packets / tf, tf, cls.symbols)

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.packets = self.base / "packets"
        shutil.copytree(type(self).packets, self.packets)
        self.sources = self.base / "source-runs.json"
        self.set_sources(("15m", "1h"))
        self.out = self.base / "out"
        patcher = patch.object(report.live, "implementation_hashes", return_value=HASHES)
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_sources(self, tfs):
        atomic_json(self.sources, {"schema": 1, "repository": report.REPOSITORY,
            "workflow": report.WORKFLOW, "sources": {tf: source_run(tf) for tf in tfs}})

    def mutate(self, tf, operation):
        folder = self.packets / tf
        data = json.loads((folder / "live-snapshot.json").read_bytes())
        operation(data)
        atomic_json(folder / "live-snapshot.json", data)
        reseal(folder, tf)

    def prepare(self, *, output=None, now=NOW):
        return report.prepare_report(self.packets, self.sources, output or self.out,
                                     now=now, bindings=BINDINGS, hashes=HASHES)

    def test_all_45_qualifying_stocks_appear_on_three_images_and_complete_csv(self):
        drawn = []
        original = ImageDraw.ImageDraw.text
        def record(draw, xy, text, *args, **kwargs):
            if text in self.symbols:
                drawn.append(text)
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", record):
            value = self.prepare()
        self.assertEqual(len(value["intersections"]), 45)
        self.assertEqual(value["image_pages"], 3)
        self.assertCountEqual(drawn, self.symbols[:45])
        files = sorted(self.out.glob("intersections-*.png"))
        self.assertEqual(len(files), 3)
        for path in files:
            with Image.open(path) as image:
                self.assertEqual(image.width, 1840)
                self.assertGreater(image.height, 500)
        rows = list(csv.DictReader(io.StringIO((self.out / "intersections.csv").read_text(encoding="utf-8-sig"))))
        self.assertEqual({row["Hisse"] for row in rows}, set(self.symbols[:45]))
        self.assertTrue(all(row["Teyit"] == "CANLI / TEYITSIZ" for row in rows))
        self.assertIn("HisseKaynakDurumlari", rows[0])
        self.assertFalse(value["stop_tp_plans_mixed"])
        self.assertFalse((self.out / "publication-receipt.json").exists())
        self.assertTrue(all(not item["timeframes"]["15m"]["plan"]["scenarios"] for item in value["intersections"]))

    def test_receipt_calendar_day_can_differ_from_actual_exchange_session(self):
        value = self.prepare()
        self.assertEqual(value["session"], "2026-10-20")
        self.assertEqual(value["inputs"]["15m"]["status"], "included")
        self.assertEqual(value["inputs"]["1h"]["status"], "included")

    def test_different_bar_closing_times_do_not_prevent_agreement(self):
        self.mutate("1h", lambda data: [row["metadata"].update(last_bar_close="2026-10-20T18:00:00+03:00") for row in data["rows"]])
        value = self.prepare()
        self.assertEqual(len(value["intersections"]), 45)
        self.assertFalse(value["criteria"]["equal_close_timestamps_required"])

    def test_two_rules_inside_each_of_two_timeframes_and_no_direction_ties(self):
        def change(data):
            data["rows"][0]["evaluations"][1].update(status="no_match", findings=[])
            for number in (2, 3):
                data["rows"][1]["evaluations"][number].update(status="match", findings=[{"direction": "bearish"}])
            data["rows"][2]["evaluations"][1].update(status="unknown", findings=[{"direction": "bullish"}])
            data["rows"][3]["evaluations"][1].update(findings=[{"direction": "neutral"}])
        self.mutate("1h", change)
        value = self.prepare()
        names = {item["symbol"] for item in value["intersections"]}
        self.assertFalse(names & set(self.symbols[:4]))
        self.assertEqual(len(names), 41)

    def test_equal_opposing_timeframe_and_rule_counts_do_not_choose_direction_by_name(self):
        def details(direction, count=2):
            return [{"symbol": "ASELS", "scanner": name, "direction": direction,
                     "plan": {"scenarios": []}} for name in report.SCANNER_ORDER[:count]]
        by_tf = {"15m": details("bullish"), "30m": details("bullish"),
                 "1h": details("bearish"), "4h": details("bearish")}
        self.assertEqual(report.current_intersections(by_tf), [])
        by_tf["2h"] = details("bullish")
        self.assertEqual(report.current_intersections(by_tf)[0]["direction"], "bullish")

    def test_valid_native_45m_packet_uses_same_rule_agreement(self):
        self.set_sources(("45m", "1h"))
        value = self.prepare()
        self.assertEqual(len(value["intersections"]), 45)
        self.assertEqual(value["inputs"]["45m"]["status"], "included")

    def test_native_weekly_packet_matches_calendar_week_not_same_day(self):
        make_packet(self.packets / "1wk", "1wk", self.symbols)
        self.mutate("1wk", lambda data: [row["metadata"].update(
            source_grid=report.NATIVE_WEEKLY_GRID,
            last_actual_native_open="2026-10-19T09:00:00+03:00") for row in data["rows"]])
        self.set_sources(("1wk", "1h"))
        value = self.prepare()
        self.assertEqual(value["inputs"]["1wk"]["status"], "included")
        self.assertEqual(len(value["intersections"]), 45)
        self.assertIn("Haftalık uygunluk", report.render_text(value))

    def test_previous_calendar_week_cannot_vote_as_current_week(self):
        make_packet(self.packets / "1wk", "1wk", self.symbols)
        self.mutate("1wk", lambda data: [row["metadata"].update(
            source_grid=report.NATIVE_WEEKLY_GRID,
            last_actual_native_open="2026-10-12T09:00:00+03:00") for row in data["rows"]])
        self.set_sources(("15m", "1h", "1wk"))
        value = self.prepare()
        self.assertEqual(value["inputs"]["1wk"]["status"], "excluded")
        self.assertEqual(len(value["intersections"]), 45)

    def test_native_multihour_packet_does_not_require_hourly_constituents(self):
        make_packet(self.packets / "4h", "4h", self.symbols)
        self.mutate("4h", lambda data: [row["metadata"].update(
            source_grid=report.NATIVE_MULTIHOUR_GRIDS["4h"],
            last_actual_native_open="2026-10-20T17:00:00+03:00",
            last_bar_close="2026-10-20T21:00:00+03:00") for row in data["rows"]])
        self.set_sources(("4h", "1h"))
        value = self.prepare()
        self.assertEqual(value["inputs"]["4h"]["status"], "included")
        self.assertEqual(len(value["intersections"]), 45)

    def test_derived_multihour_grid_is_not_silently_mixed_with_native_grid(self):
        make_packet(self.packets / "2h", "2h", self.symbols)
        self.set_sources(("15m", "1h", "2h"))
        value = self.prepare()
        self.assertEqual(value["inputs"]["2h"]["reason"], "native_multihour_source_grid_required")
        self.assertEqual(len(value["intersections"]), 45)

    def test_legacy_45m_grid_is_excluded_without_blocking_other_two_lanes(self):
        self.set_sources(("15m", "1h", "45m"))
        self.mutate("45m", lambda data: data["rows"][0]["metadata"].update(source_grid="legacy_1000_grid"))
        value = self.prepare()
        self.assertEqual(value["inputs"]["45m"]["reason"], "native_45m_source_grid_required")
        self.assertEqual(len(value["intersections"]), 45)

    def test_stale_halted_and_explicitly_blocked_rows_never_vote(self):
        def change(data):
            data["rows"][0]["metadata"]["usable_latest"] = False
            data["counts"]["usable"] = 629
            data["rows"][1]["market_status"] = {"status": "official_halt"}
            data["rows"][2]["metadata"]["eligible_for_current_signals"] = False
            data["rows"][3]["market_event"] = {"status": "official_halt"}
            data["rows"][3]["metadata"]["last_actual_native_open"] = "2026-10-19T18:00:00+03:00"
        self.mutate("1h", change)
        value = self.prepare()
        self.assertEqual(len(value["intersections"]), 41)
        self.assertEqual(value["inputs"]["1h"]["status"], "included")
        self.assertFalse({item["symbol"] for item in value["intersections"]} & set(self.symbols[:4]))

    def test_invalid_rule_identity_excludes_only_affected_lane(self):
        self.mutate("1h", lambda data: data["rows"][0]["evaluations"][0].update(ruleset_hash="bad"))
        value = self.prepare()
        self.assertEqual(value["inputs"]["1h"]["reason"], "source_scanner_identity_changed")
        self.assertEqual(value["intersections"], [])
        self.assertEqual(value["image_pages"], 0)
        self.assertIn("yeterli güncel zaman dilimi yok", (self.out / "intersections.txt").read_text(encoding="utf-8"))

    def test_source_packet_tampering_and_incomplete_ack_are_excluded(self):
        (self.packets / "15m/live-snapshot.csv").write_bytes(b"changed")
        receipt = json.loads((self.packets / "1h/publication-receipt.json").read_bytes())
        del receipt["acknowledged"]["photo"]
        atomic_json(self.packets / "1h/publication-receipt.json", receipt)
        value = self.prepare()
        self.assertEqual(value["inputs"]["15m"]["reason"], "source_packet_file_hash_changed")
        self.assertEqual(value["inputs"]["1h"]["reason"], "acknowledged_source_packet_required")

    def test_untrusted_source_run_is_excluded(self):
        value = json.loads(self.sources.read_bytes())
        value["sources"]["15m"]["head_branch"] = "fork-branch"
        atomic_json(self.sources, value)
        prepared = self.prepare()
        self.assertEqual(prepared["inputs"]["15m"]["reason"], "trusted_main_source_run_required")

    def test_changed_implementation_and_aged_observation_do_not_enter_cohort(self):
        manifest = json.loads((self.packets / "15m/prepared-packet.json").read_bytes())
        manifest["implementation_files"] = {"other.py": "0" * 64}
        atomic_json(self.packets / "15m/prepared-packet.json", manifest)
        def expire(data):
            data["observation_start"] = (NOW - timedelta(minutes=91)).isoformat()
        self.mutate("1h", expire)
        value = self.prepare()
        self.assertEqual(value["inputs"]["15m"]["reason"], "source_implementation_changed_refresh_timeframe")
        self.assertEqual(value["inputs"]["1h"]["reason"], "source_observation_expired_or_wrong_session")

    def test_incorrect_source_bar_session_and_insufficient_coverage_are_excluded(self):
        self.mutate("15m", lambda data: data["rows"][0]["metadata"].update(last_actual_native_open="2026-10-19T18:00:00+03:00"))
        def reduce(data):
            for row in data["rows"][:64]:
                row["metadata"]["usable_latest"] = False
            data["counts"]["usable"] = 566
        self.mutate("1h", reduce)
        value = self.prepare()
        self.assertEqual(value["inputs"]["15m"]["reason"], "source_symbol_observation_identity_changed")
        self.assertEqual(value["inputs"]["1h"]["reason"], "source_coverage_below_90_percent")

    def test_true_no_result_packet_has_text_and_csv_but_no_empty_image(self):
        for tf in ("15m", "1h"):
            self.mutate(tf, lambda data: [scan.update(status="no_match", findings=[]) for row in data["rows"] for scan in row["evaluations"]])
        value = self.prepare()
        self.assertEqual(value["intersections"], [])
        self.assertEqual(value["image_pages"], 0)
        self.assertEqual(list(self.out.glob("*.png")), [])
        transport = Mock()
        transport.send.side_effect = [101, 102]
        receipt = report.publish_report(self.out, now=NOW, environ=ENV, transport=transport)
        self.assertEqual(list(receipt["acknowledged"]), ["text", "csv"])
        self.assertIn("kesişim bulunmadı", transport.send.call_args_list[0].kwargs["payload"]["text"])

    def test_partial_page_failure_resumes_only_unsent_pages_and_csv(self):
        self.prepare()
        first = Mock()
        first.send.side_effect = [101, 102, RuntimeError("network")]
        with self.assertRaises(RuntimeError):
            report.publish_report(self.out, now=NOW, environ=ENV, transport=first)
        partial = json.loads((self.out / "publication-receipt.json").read_bytes())
        self.assertEqual(partial["acknowledged"], {"text": 101, "photo-001": 102})
        resumed = Mock()
        resumed.send.side_effect = [103, 104, 105]
        receipt = report.publish_report(self.out, now=NOW, environ=ENV, transport=resumed)
        self.assertEqual(resumed.send.call_count, 3)
        self.assertEqual(set(receipt["acknowledged"]), {"text", "photo-001", "photo-002", "photo-003", "csv"})
        self.assertEqual(receipt["expected_acknowledgements"], ["text", "photo-001", "photo-002", "photo-003", "csv"])
        again = Mock()
        report.publish_report(self.out, now=NOW, environ=ENV, transport=again)
        again.send.assert_not_called()
        for call in resumed.send.call_args_list:
            self.assertEqual(call.kwargs["chat_id"], live.CHAT)
            self.assertEqual(call.kwargs["message_thread_id"], 28330)

    def test_same_source_set_in_later_run_is_not_resent_or_relabelled_as_new_ack(self):
        old = self.prepare()
        first = Mock()
        first.send.side_effect = range(101, 106)
        receipt = report.publish_report(self.out, now=NOW, environ=ENV, transport=first)
        previous = self.out / "publication-receipt.json"
        next_folder = self.base / "later"
        new = self.prepare(output=next_folder, now=NOW + timedelta(minutes=1))
        self.assertEqual(old["source_set_sha256"], new["source_set_sha256"])
        sender = Mock()
        skipped = report.publish_report(next_folder, now=NOW + timedelta(minutes=1), environ=ENV,
                                        transport=sender, previous_receipt=previous)
        self.assertEqual(skipped["status"], "already_sent")
        self.assertEqual(skipped["packet_sha256"], receipt["packet_sha256"])
        self.assertNotEqual(skipped["packet_sha256"], skipped["prepared_packet_skipped_sha256"])
        sender.send.assert_not_called()
        report.publish_report(next_folder, now=NOW + timedelta(minutes=1), environ=ENV, transport=sender)
        sender.send.assert_not_called()

    def test_new_source_packet_changes_semantic_set_and_is_published(self):
        self.prepare()
        first = Mock()
        first.send.side_effect = range(101, 106)
        old = report.publish_report(self.out, now=NOW, environ=ENV, transport=first)
        previous = self.out / "publication-receipt.json"
        self.mutate("1h", lambda data: data.update(extra_observation_marker="new-source-packet"))
        next_folder = self.base / "new-source"
        value = self.prepare(output=next_folder)
        self.assertNotEqual(value["source_set_sha256"], old["source_set_sha256"])
        sender = Mock()
        sender.send.side_effect = range(201, 206)
        sent = report.publish_report(next_folder, now=NOW, environ=ENV, transport=sender, previous_receipt=previous)
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(sender.send.call_count, 5)

    def test_changed_page_stops_before_telegram_and_wrong_destination_is_rejected(self):
        self.prepare()
        (self.out / "intersections-002.png").write_bytes(b"changed")
        transport = Mock()
        with self.assertRaisesRegex(ValueError, "file_hash_changed"):
            report.publish_report(self.out, now=NOW, environ=ENV, transport=transport)
        with self.assertRaisesRegex(ValueError, "destination"):
            report.publish_report(self.out, now=NOW, environ={**ENV, "TELEGRAM_TOPIC_INTERSECTIONS": "8"}, transport=transport)
        transport.send.assert_not_called()

    def test_expired_publication_and_nonpositive_ack_are_refused(self):
        self.prepare()
        transport = Mock()
        with self.assertRaisesRegex(ValueError, "expired"):
            report.publish_report(self.out, now=NOW + timedelta(minutes=31), environ=ENV, transport=transport)
        transport.send.assert_not_called()
        transport.send.return_value = 0
        with self.assertRaisesRegex(ValueError, "acknowledgement"):
            report.publish_report(self.out, now=NOW, environ=ENV, transport=transport)
        self.assertFalse((self.out / "publication-receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
