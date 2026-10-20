from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import zipfile
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import httpx

from scripts import atc_schedule_receipts as receipts
from scripts.atc_snapshot_schedule import SUPPORTED_TIMEFRAMES, plan
from tests.test_atc_snapshot_schedule import Calendar, acknowledged, clock, entries

REPO = "CengizKarabulut/borsapp"
WORKFLOW = "atc-scheduled-snapshots.yml"
ROOT = f"https://api.github.com/repos/{REPO}/actions"


def zip_state(state, name=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name or f"{state['timeframe']}.json", json.dumps(state))
    return output.getvalue()


def trusted_run(**overrides):
    return {"path": f".github/workflows/{WORKFLOW}", "head_branch": "main",
            "head_repository": {"full_name": REPO}, "event": "schedule",
            "conclusion": "failure", **overrides}


def artifact(artifact_id, tf="15m", run_id=123, **overrides):
    return {"id": artifact_id, "name": f"atc-scheduled-delivery-{tf}", "expired": False,
            "workflow_run": {"id": run_id},
            "archive_download_url": f"{ROOT}/artifacts/{artifact_id}/zip", **overrides}


class Api:
    def __init__(self, listings=None, archives=None, runs=None, *, redirect=False):
        self.listings = listings or {}
        self.archives = archives or {}
        self.runs = runs or {123: trusted_run()}
        self.calls = []
        self.redirect = redirect

    def handle(self, request):
        self.calls.append(request)
        path = request.url.path
        if request.url.host == "artifact.example.invalid":
            return httpx.Response(200, content=self.archives[int(path.rsplit("/", 1)[-1])])
        if path.endswith("/artifacts"):
            tf = request.url.params["name"].removeprefix("atc-scheduled-delivery-")
            assert request.url.params["per_page"] == "10"
            return httpx.Response(200, json={"artifacts": self.listings.get(tf, [])})
        if "/runs/" in path:
            return httpx.Response(200, json=self.runs[int(path.rsplit("/", 1)[-1])])
        artifact_id = int(path.split("/")[-2])
        if self.redirect:
            return httpx.Response(302, headers={
                "Location": f"https://artifact.example.invalid/blob/{artifact_id}",
            })
        return httpx.Response(200, content=self.archives[artifact_id])

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handle), follow_redirects=True,
                            headers={"Authorization": "Bearer local-test-token"}, timeout=30)


class RestoreReceiptTests(unittest.TestCase):
    def setUp(self):
        self.state = acknowledged(entries(plan(clock(), calendar=Calendar()))["15m"])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "ledger"

    def restore(self, api):
        with api.client() as client:
            return receipts.restore_receipts(REPO, WORKFLOW, self.output, client=client)

    def test_cold_start_without_artifacts_is_explicit_and_not_an_error(self):
        api = Api()
        result = self.restore(api)
        self.assertEqual(result["restored"], 0)
        self.assertEqual(len(api.calls), len(SUPPORTED_TIMEFRAMES))
        self.assertFalse(self.output.exists())

    def test_latest_logical_target_wins_even_if_older_artifact_is_listed_first(self):
        older = acknowledged(entries(plan(clock(hour=10, minute=22), calendar=Calendar()))["15m"])
        api = Api({"15m": [artifact(20), artifact(10)]},
                  {20: zip_state(older), 10: zip_state(self.state)})
        result = self.restore(api)
        self.assertEqual(result["timeframes"], ["15m"])
        restored = json.loads((self.output / "15m.json").read_bytes())
        self.assertEqual(restored, self.state)
        self.assertEqual(sum("/runs/" in request.url.path for request in api.calls), 1)

    def test_cross_origin_artifact_redirect_strips_authorization(self):
        api = Api({"15m": [artifact(10)]}, {10: zip_state(self.state)}, redirect=True)
        self.restore(api)
        api_requests = [request for request in api.calls if request.url.host == "api.github.com"]
        blob_requests = [request for request in api.calls if request.url.host != "api.github.com"]
        self.assertTrue(all(request.headers.get("Authorization") == "Bearer local-test-token"
                            for request in api_requests))
        self.assertEqual(len(blob_requests), 1)
        self.assertNotIn("Authorization", blob_requests[0].headers)

    def test_non_main_wrong_workflow_foreign_repo_and_wrong_event_are_ignored(self):
        for override in [{"head_branch": "feature"}, {"path": ".github/workflows/ci.yml"},
                         {"head_repository": {"full_name": "someone/fork"}},
                         {"event": "pull_request"}]:
            with self.subTest(override=override):
                api = Api({"15m": [artifact(10)]}, runs={123: trusted_run(**override)})
                self.assertEqual(self.restore(api)["restored"], 0)
                self.assertFalse(any(request.url.path.endswith("/zip") for request in api.calls))

    def test_expired_artifact_is_skipped_without_downloading(self):
        api = Api({"15m": [artifact(10, expired=True)]})
        self.assertEqual(self.restore(api)["restored"], 0)
        self.assertFalse(any("/runs/" in request.url.path for request in api.calls))

    def test_unexpected_download_endpoint_fails_before_credentials_can_be_sent(self):
        api = Api({"15m": [artifact(10, archive_download_url="https://untrusted.invalid/token")]})
        with self.assertRaisesRegex(ValueError, "download_url"):
            self.restore(api)
        self.assertTrue(all(request.url.host == "api.github.com" for request in api.calls))

    def test_invalid_trusted_recent_state_fails_closed_instead_of_restoring_old_state(self):
        api = Api({"15m": [artifact(10), artifact(20)]},
                  {10: zip_state(self.state), 20: b"broken trusted zip"})
        with self.assertRaisesRegex(ValueError, "invalid_delivery_artifact_zip"):
            self.restore(api)
        self.assertFalse(self.output.exists())

    def test_wrong_filename_repeated_entries_and_oversized_state_are_rejected(self):
        repeated = io.BytesIO()
        with zipfile.ZipFile(repeated, "w") as archive:
            archive.writestr("15m.json", json.dumps(self.state))
            archive.writestr("extra.json", "{}")
        huge = io.BytesIO()
        with zipfile.ZipFile(huge, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("15m.json", b"x" * (receipts.MAX_STATE + 1))
        for content in [zip_state(self.state, "../15m.json"), repeated.getvalue(), huge.getvalue()]:
            with self.subTest(size=len(content)):
                with self.assertRaisesRegex(ValueError, "one_bounded_state_file"):
                    self.restore(Api({"15m": [artifact(10)]}, {10: content}))

    def test_oversized_download_and_wrong_state_timeframe_are_rejected(self):
        other = acknowledged(entries(plan(clock(), calendar=Calendar()))["30m"])
        with self.assertRaisesRegex(ValueError, "timeframe_mismatch"):
            self.restore(Api({"15m": [artifact(10)]}, {10: zip_state(other, "15m.json")}))
        with patch.object(receipts, "MAX_ARCHIVE", 10), self.assertRaisesRegex(ValueError, "too_large"):
            self.restore(Api({"15m": [artifact(10)]}, {10: b"x" * 11}))

    def test_invalid_repository_workflow_and_api_failure_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "repository_or_workflow"):
            receipts.restore_receipts("https://foreign.invalid", WORKFLOW, self.output)
        with self.assertRaisesRegex(ValueError, "repository_or_workflow"):
            receipts.restore_receipts(REPO, "../other.yml", self.output)
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
            with self.assertRaises(httpx.HTTPStatusError):
                receipts.restore_receipts(REPO, WORKFLOW, self.output, client=client)


class RecordReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "packet"
        self.folder.mkdir()
        self.slot = entries(plan(clock(), calendar=Calendar()))["15m"]
        report = {"version": receipts.PACKET_VERSION, "timeframe": "15m", "provisional": True,
                  "confirmed_store_writes": 0, "observation_end": clock().isoformat()}
        for name in receipts.PACKET_FILES:
            content = json.dumps(report).encode() if name.endswith(".json") else b"prepared content"
            (self.folder / name).write_bytes(content)
        manifest = {"version": receipts.PACKET_VERSION, "implementation_files": {},
                    "files": {name: sha256((self.folder / name).read_bytes()).hexdigest()
                              for name in receipts.PACKET_FILES}}
        (self.folder / "prepared-packet.json").write_text(json.dumps(manifest), encoding="utf-8")
        packet_hash = sha256((self.folder / "prepared-packet.json").read_bytes()).hexdigest()
        receipt = acknowledged(self.slot)["receipt"]
        receipt["packet_sha256"] = packet_hash
        (self.folder / "publication-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        self.output = self.root / "state"

    def test_stamping_changes_only_sidecar_and_record_requires_exact_three_acks(self):
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        receipts.stamp_packet(self.folder, self.slot)
        self.assertTrue(all((self.folder / name).read_bytes() == content for name, content in before.items()))
        result = receipts.record_receipt(self.folder, self.slot, self.output)
        self.assertEqual(result["status"], "acknowledged_delivery_recorded")
        state = json.loads((self.output / "15m.json").read_bytes())
        self.assertEqual(state["slot_key"], self.slot["slot_key"])
        self.assertEqual(state["receipt"]["acknowledged"], {"text": 1, "photo": 2, "csv": 3})

    def test_report_bytes_changed_after_stamp_cannot_advance_ledger(self):
        receipts.stamp_packet(self.folder, self.slot)
        (self.folder / "live-snapshot.csv").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "file_hash_changed"):
            receipts.record_receipt(self.folder, self.slot, self.output)
        self.assertFalse(self.output.exists())

    def test_wrong_report_timeframe_missing_ack_or_changed_schedule_cannot_advance_ledger(self):
        receipts.stamp_packet(self.folder, self.slot)
        path = self.folder / "publication-receipt.json"
        original = json.loads(path.read_bytes())
        for change in [lambda r: r.update(packet_sha256="f" * 64),
                       lambda r: r["acknowledged"].pop("photo"),
                       lambda r: r.update(topic_id=28328)]:
            with self.subTest(change=change):
                receipt = copy.deepcopy(original)
                change(receipt)
                path.write_text(json.dumps(receipt), encoding="utf-8")
                with self.assertRaises(ValueError):
                    receipts.record_receipt(self.folder, self.slot, self.output)
        different = entries(plan(clock(hour=12), calendar=Calendar()))["15m"]
        with self.assertRaisesRegex(ValueError, "schedule_context_changed"):
            receipts.record_receipt(self.folder, different, self.output)
        with self.assertRaisesRegex(ValueError, "schedule_identity_mismatch"):
            receipts.stamp_packet(self.folder, entries(plan(clock(), calendar=Calendar()))["30m"])

    def test_manual_preview_never_creates_state_even_without_a_receipt(self):
        slot = entries(plan(clock(), calendar=Calendar(), force_all=True))["15m"]
        result = receipts.record_receipt(self.root / "not-present", slot, self.output)
        self.assertEqual(result["status"], "manual_only_no_delivery_watermark")
        self.assertFalse(self.output.exists())

    def test_slot_rejects_unknown_fields_bad_counters_and_naive_clock(self):
        for bad in [{**self.slot, "schema": "overwrite"}, {**self.slot, "missed_slot_count": -1},
                    {**self.slot, "lateness_seconds": True},
                    {**self.slot, "target_close": "2026-10-20T11:00:00"}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                receipts.stamp_packet(self.folder, bad)

    def test_cli_explicit_slot_json_stamps_without_publishing(self):
        with patch("builtins.print"):
            result = receipts.main(["--stamp-packet", "--packet-dir", str(self.folder),
                                    "--slot-json", json.dumps(self.slot)])
        self.assertEqual(result["status"], "schedule_context_attached")
        self.assertFalse(self.output.exists())


class RetryReceiptReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "ledger"
        self.state = acknowledged(entries(plan(clock(), calendar=Calendar()))["15m"])
        self.delays = []

    def restore(self, handler):
        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True,
                          headers={"Authorization": "Bearer local-test-token"}) as client:
            return receipts.restore_receipts(REPO, WORKFLOW, self.output, client=client,
                                             sleep=self.delays.append)

    def test_cdn_503_restarts_original_github_zip_url_and_strips_authorization(self):
        api = Api({"15m": [artifact(10)]}, {10: zip_state(self.state)}, redirect=True)
        cdn_calls = []

        def handler(request):
            if request.url.host == "artifact.example.invalid":
                cdn_calls.append(request)
                if len(cdn_calls) == 1:
                    return httpx.Response(503, text="Transient egress limit")
            return api.handle(request)

        self.assertEqual(self.restore(handler)["restored"], 1)
        self.assertEqual(self.delays, [2])
        self.assertEqual(sum(request.url.path.endswith("/artifacts/10/zip")
                             for request in api.calls), 2)
        self.assertEqual(len(cdn_calls), 2)
        self.assertTrue(all("Authorization" not in request.headers for request in cdn_calls))

    def test_persistent_503_stops_after_three_reads_and_writes_no_partial_ledger(self):
        api = Api({"15m": [artifact(10), artifact(20)]}, {10: zip_state(self.state)})
        failures = []

        def handler(request):
            if request.url.path.endswith("/artifacts/20/zip"):
                failures.append(request)
                return httpx.Response(503)
            return api.handle(request)

        with self.assertRaises(httpx.HTTPStatusError):
            self.restore(handler)
        self.assertEqual(len(failures), 3)
        self.assertEqual(self.delays, [2, 5])
        self.assertFalse(self.output.exists())

    def test_transient_transport_error_on_artifact_list_is_retried(self):
        api = Api()
        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                raise httpx.ReadError("Connection reset", request=request)
            return api.handle(request)

        self.assertEqual(self.restore(handler)["restored"], 0)
        self.assertEqual(len(calls), len(SUPPORTED_TIMEFRAMES) + 1)
        self.assertEqual(self.delays, [2])

    def test_retry_after_is_capped_and_default_second_backoff_is_five_seconds(self):
        api = Api()
        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "600"})
            if len(calls) == 2:
                return httpx.Response(500, headers={"Retry-After": "invalid"})
            return api.handle(request)

        self.assertEqual(self.restore(handler)["restored"], 0)
        self.assertEqual(self.delays, [10, 5])

    def test_each_retryable_status_works_but_403_and_404_are_not_retried(self):
        for code in [429, 500, 502, 503, 504, 403, 404]:
            with self.subTest(code=code):
                self.delays.clear()
                api = Api()
                calls = []

                def handler(request, calls=calls, code=code, api=api):
                    calls.append(request)
                    return httpx.Response(code) if len(calls) == 1 else api.handle(request)

                if code in (403, 404):
                    with self.assertRaises(httpx.HTTPStatusError):
                        self.restore(handler)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(self.delays, [])
                else:
                    self.assertEqual(self.restore(handler)["restored"], 0)
                    self.assertEqual(self.delays, [2])

    def test_stream_failure_discards_partial_bytes_before_retry(self):
        api = Api({"15m": [artifact(10)]}, {10: zip_state(self.state)})
        attempts = []

        class InterruptedStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"incomplete prefix"
                raise httpx.ReadError("Midstream reset")

        def handler(request):
            if request.url.path.endswith("/artifacts/10/zip"):
                attempts.append(request)
                if len(attempts) == 1:
                    return httpx.Response(200, stream=InterruptedStream())
            return api.handle(request)

        self.assertEqual(self.restore(handler)["restored"], 1)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(self.delays, [2])

    def test_corrupt_state_zip_and_size_limit_are_never_retried(self):
        for content in [b"not a zip", zip_state({**self.state, "sent": False})]:
            with self.subTest(size=len(content)):
                api = Api({"15m": [artifact(10)]}, {10: content})
                with self.assertRaises(ValueError):
                    self.restore(api.handle)
                self.assertEqual(sum(request.url.path.endswith("/zip") for request in api.calls), 1)
                self.assertEqual(self.delays, [])
        api = Api({"15m": [artifact(10)]}, {10: b"too large"})
        with patch.object(receipts, "MAX_ARCHIVE", 1), self.assertRaisesRegex(ValueError, "too_large"):
            self.restore(api.handle)
        self.assertEqual(self.delays, [])


if __name__ == "__main__":
    unittest.main()
