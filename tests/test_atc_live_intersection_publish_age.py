"""Publication-time freshness, independent of when the report was prepared."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from itertools import count
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import atc_live_intersections as report
from scripts.atc_live_packet_contract import (
    VERSION as PACKET_VERSION,
)
from scripts.atc_live_packet_contract import (
    acknowledgement_keys,
    direction_metadata,
    packet_files,
)
from scripts.atc_structure_report import atomic_json
from scripts.atc_universe_seed import load_pinned
from tests.test_atc_live_intersections import (
    BINDINGS,
    ENV,
    HASHES,
    NOW,
    make_packet,
    source_run,
)


class IntersectionPublishAgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.packets = self.base / "packets"
        symbols = load_pinned(Path("config/atc_630_symbols.txt"))
        # The fixture builder starts observation two minutes before its `now`.
        # At preparation, 15m is 44 minutes old and valid against its 45m limit.
        for tf in ("15m", "1h"):
            make_packet(self.packets / tf, tf, symbols, matches=1,
                        now=NOW - timedelta(minutes=42))
            self.seal_current_packet(tf)
        self.sources = self.base / "source-runs.json"
        atomic_json(self.sources, {"schema": 1, "repository": report.REPOSITORY,
            "workflow": report.WORKFLOW,
            "sources": {tf: source_run(tf) for tf in ("15m", "1h")}})
        self.out = self.base / "out"
        patcher = patch.object(report.live, "implementation_hashes", return_value=HASHES)
        patcher.start()
        self.addCleanup(patcher.stop)

    def seal_current_packet(self, tf):
        """Use the shared v2 contract while the broader fixture migration runs."""
        folder = self.packets / tf
        packet = json.loads((folder / "live-snapshot.json").read_bytes())
        packet["direction_groups"] = direction_metadata(packet)
        atomic_json(folder / "live-snapshot.json", packet)
        names = packet_files(packet)
        for name in names:
            if not (folder / name).exists():
                (folder / name).write_bytes(b"fixture-direction-page-bytes")
        atomic_json(folder / "prepared-packet.json", {"version": PACKET_VERSION,
            "implementation_files": HASHES,
            "files": {name: sha256((folder / name).read_bytes()).hexdigest() for name in names}})
        keys = acknowledgement_keys(packet)
        atomic_json(folder / "publication-receipt.json", {"status": "sent",
            "packet_version": PACKET_VERSION, "chat_id": report.live.CHAT,
            "topic_id": report.live.TOPICS[tf],
            "packet_sha256": sha256((folder / "prepared-packet.json").read_bytes()).hexdigest(),
            "expected_acknowledgements": keys,
            "acknowledged": {key: index for index, key in enumerate(keys, 101)}})

    def prepare(self):
        value = report.prepare_report(self.packets, self.sources, self.out,
                                      now=NOW, bindings=BINDINGS, hashes=HASHES)
        self.assertEqual(value["inputs"]["15m"]["status"], "included")
        self.assertEqual(value["inputs"]["15m"]["maximum_age_minutes"], 45)
        self.assertEqual(len(value["intersections"]), 1)
        self.expected_sends = 2 + value["image_pages"]
        return value

    def sender(self):
        transport = Mock()
        transport.send.side_effect = count(701)
        return transport

    def test_fresh_source_sends_despite_missing_other_timeframe_lanes(self):
        self.prepare()
        transport = self.sender()
        value = report.publish_report(self.out, now=NOW, environ=ENV, transport=transport)
        self.assertEqual(value["status"], "sent")
        self.assertEqual(transport.send.call_count, self.expected_sends)

    def test_exact_45_minute_source_age_is_inclusive(self):
        self.prepare()
        transport = self.sender()
        value = report.publish_report(self.out, now=NOW + timedelta(minutes=1),
                                      environ=ENV, transport=transport)
        self.assertEqual(value["status"], "sent")

    def test_source_expires_after_preparation_before_first_post(self):
        self.prepare()
        transport = self.sender()
        with self.assertRaisesRegex(ValueError, "expired|observation"):
            report.publish_report(self.out, now=NOW + timedelta(minutes=2),
                                  environ=ENV, transport=transport)
        transport.send.assert_not_called()
        self.assertFalse((self.out / "publication-receipt.json").exists())

    def test_one_microsecond_after_source_limit_is_rejected_without_post(self):
        self.prepare()
        transport = self.sender()
        with self.assertRaisesRegex(ValueError, "expired|observation"):
            report.publish_report(self.out,
                now=NOW + timedelta(minutes=1, microseconds=1), environ=ENV, transport=transport)
        transport.send.assert_not_called()

    def test_partial_receipt_resume_cannot_send_expired_remaining_pages(self):
        self.prepare()
        failed = Mock()
        failed.send.side_effect = [801, ValueError("simulated_transport_error")]
        with self.assertRaisesRegex(ValueError, "simulated_transport_error"):
            report.publish_report(self.out, now=NOW, environ=ENV, transport=failed)
        receipt = json.loads((self.out / "publication-receipt.json").read_bytes())
        self.assertEqual(receipt["acknowledged"], {"text": 801})
        retry = self.sender()
        with self.assertRaisesRegex(ValueError, "expired|observation"):
            report.publish_report(self.out, now=NOW + timedelta(minutes=2),
                                  environ=ENV, transport=retry)
        retry.send.assert_not_called()
        self.assertEqual(json.loads((self.out / "publication-receipt.json").read_bytes()), receipt)

    def test_utc_observations_and_istanbul_publication_share_same_age_boundary(self):
        for tf in ("15m", "1h"):
            folder = self.packets / tf
            packet = json.loads((folder / "live-snapshot.json").read_bytes())
            for key in ("observation_start", "observation_end"):
                packet[key] = report.live.aware(
                    datetime.fromisoformat(packet[key])).astimezone(UTC).isoformat()
            for row in packet["rows"]:
                for key in ("observed_at", "received_at"):
                    row["metadata"][key] = report.live.aware(
                        datetime.fromisoformat(row["metadata"][key])).astimezone(UTC).isoformat()
            atomic_json(folder / "live-snapshot.json", packet)
            self.seal_current_packet(tf)
        self.prepare()
        transport = self.sender()
        value = report.publish_report(self.out,
            now=(NOW + timedelta(minutes=1)).astimezone(UTC), environ=ENV, transport=transport)
        self.assertEqual(value["status"], "sent")
        self.assertEqual(transport.send.call_count, self.expected_sends)


if __name__ == "__main__":
    unittest.main()
