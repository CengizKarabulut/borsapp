from __future__ import annotations

import io
import json
import unittest
import zipfile
from hashlib import sha256

from scripts import atc_live_packet_restore as restore


def packet_archive(*, change=None, extra=None):
    files = {name: b"test" for name in restore.FILES}
    files["live-snapshot.json"] = json.dumps({"version": restore.VERSION,
        "timeframe": "45m", "provisional": True, "confirmed_store_writes": 0,
        "orders_sent": 0, "observation_end": "2026-10-20T18:45:00+03:00"}).encode()
    files["prepared-packet.json"] = json.dumps({"version": restore.VERSION,
        "files": {name: sha256(files[name]).hexdigest() for name in restore.FILES}}).encode()
    files["publication-receipt.json"] = json.dumps({"status": "sent", "chat_id": restore.CHAT,
        "topic_id": 9, "packet_sha256": sha256(files["prepared-packet.json"]).hexdigest(),
        "acknowledged": {"text": 1, "photo": 2, "csv": 3}}).encode()
    files["scheduled-slot.json"] = b'{"timeframe":"45m"}'
    if change:
        change(files)
    if extra:
        files.update(extra)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


class PacketRestoreTests(unittest.TestCase):
    def test_complete_previous_receipt_requires_every_declared_ack(self):
        receipt = {"version": "atc-latest-known-provisional-intersections-v1", "status": "sent",
            "chat_id": restore.CHAT, "topic_id": 28330, "source_set_sha256": "a" * 64,
            "updated_at": "2026-10-21T03:00:00+03:00",
            "expected_acknowledgements": ["text", "photo-001", "csv"],
            "acknowledged": {"text": 1, "photo-001": 2, "csv": 3}}

        def archive(value):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as packet:
                packet.writestr("publication-receipt.json", json.dumps(value))
            return output.getvalue()

        restored, _ = restore.unpack_intersection_receipt(archive(receipt))
        self.assertEqual(restored, receipt)
        receipt["acknowledged"].pop("photo-001")
        with self.assertRaisesRegex(ValueError, "complete_intersection_receipt"):
            restore.unpack_intersection_receipt(archive(receipt))

    def test_accepts_only_unchanged_acknowledged_timeframe_packet(self):
        files, observed = restore.unpack_packet(packet_archive(), "45m")
        self.assertEqual(set(files), restore.NAMES)
        self.assertEqual(observed.isoformat(), "2026-10-20T18:45:00+03:00")

    def test_tampered_source_or_missing_ack_is_rejected(self):
        def no_ack(files):
            receipt = json.loads(files["publication-receipt.json"])
            receipt["acknowledged"].pop("csv")
            files["publication-receipt.json"] = json.dumps(receipt).encode()
        for change in (lambda files: files.update({"live-snapshot.csv": b"tampered"}), no_ack):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "identity_or_acknowledgement"):
                restore.unpack_packet(packet_archive(change=change), "45m")

    def test_wrong_timeframe_and_path_traversal_are_rejected(self):
        with self.assertRaises(ValueError):
            restore.unpack_packet(packet_archive(), "15m")
        with self.assertRaisesRegex(ValueError, "file_set"):
            restore.unpack_packet(packet_archive(extra={"../unexpected": b"x"}), "45m")


if __name__ == "__main__":
    unittest.main()
