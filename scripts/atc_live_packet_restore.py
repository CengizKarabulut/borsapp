"""Read bounded, acknowledged main-workflow RAM packets for latest-state intersections."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import zipfile
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import httpx

from scripts.atc_live_snapshot import CHAT, FILES, TOPICS, VERSION
from scripts.atc_schedule_receipts import API, _atomic_json, _json_read, _retry_read, _trusted_run

WORKFLOW = "atc-scheduled-snapshots.yml"
MAX_ARCHIVE = 20 * 1024 * 1024
MAX_EXPANDED = 50 * 1024 * 1024
NAMES = frozenset((*FILES, "prepared-packet.json", "publication-receipt.json", "scheduled-slot.json"))


def unpack_intersection_receipt(raw):
    if len(raw) > 100_000:
        raise ValueError("intersection_receipt_archive_too_large")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (len(entries) != 1 or entries[0].filename != "publication-receipt.json"
                or entries[0].file_size > 100_000 or entries[0].flag_bits & 1):
            raise ValueError("intersection_receipt_archive_invalid")
        receipt = json.loads(archive.read(entries[0]))
    acks = receipt.get("acknowledged", {})
    expected = receipt.get("expected_acknowledgements")
    if (receipt.get("version") != "atc-latest-known-provisional-intersections-v1"
            or receipt.get("status") not in {"sent", "already_sent"}
            or receipt.get("chat_id") != CHAT or receipt.get("topic_id") != 28330
            or not re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("source_set_sha256", "")))
            or not isinstance(acks, dict) or not isinstance(expected, list)
            or set(acks) != set(expected) or not {"text", "csv"} <= set(acks)
            or any(key not in {"text", "csv"} and not re.fullmatch(r"photo-\d{3}", key) for key in acks)
            or any(type(value) is not int or value <= 0 for value in acks.values())):
        raise ValueError("complete_intersection_receipt_required")
    updated = datetime.fromisoformat(receipt["updated_at"])
    if updated.utcoffset() is None:
        raise ValueError("aware_intersection_receipt_required")
    return receipt, updated


def unpack_packet(raw, timeframe):
    if len(raw) > MAX_ARCHIVE:
        raise ValueError("ram_packet_archive_too_large")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (len(entries) != len(NAMES) or {entry.filename for entry in entries} != NAMES
                or sum(entry.file_size for entry in entries) > MAX_EXPANDED
                or any(entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000
                       for entry in entries)):
            raise ValueError("ram_packet_archive_file_set_invalid")
        files = {entry.filename: archive.read(entry) for entry in entries}
    manifest = json.loads(files["prepared-packet.json"])
    report = json.loads(files[FILES[0]])
    receipt = json.loads(files["publication-receipt.json"])
    slot = json.loads(files["scheduled-slot.json"])
    if (manifest.get("version") != VERSION or set(manifest.get("files", {})) != set(FILES)
            or any(sha256(files[name]).hexdigest() != manifest["files"][name] for name in FILES)
            or report.get("version") != VERSION or report.get("timeframe") != timeframe
            or report.get("provisional") is not True or report.get("confirmed_store_writes") != 0
            or report.get("orders_sent") != 0 or slot.get("timeframe") != timeframe
            or receipt.get("status") != "sent" or receipt.get("chat_id") != CHAT
            or receipt.get("topic_id") != TOPICS[timeframe]
            or receipt.get("packet_sha256") != sha256(files["prepared-packet.json"]).hexdigest()
            or set(receipt.get("acknowledged", {})) != {"text", "photo", "csv"}
            or any(type(value) is not int or value <= 0 for value in receipt["acknowledged"].values())):
        raise ValueError("ram_packet_identity_or_acknowledgement_invalid")
    observed = datetime.fromisoformat(report["observation_end"])
    if observed.utcoffset() is None:
        raise ValueError("aware_packet_observation_required")
    return files, observed


def restore_packets(repository, output_dir, *, client=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid_repository")
    if client is None:
        with httpx.Client(timeout=45, follow_redirects=True, headers={
                "Authorization": "Bearer " + os.environ["GH_TOKEN"],
                "Accept": "application/vnd.github+json"}) as owned:
            return restore_packets(repository, output_dir, client=owned)
    root = f"{API}/repos/{repository}/actions"
    sources, runs = {}, {}
    output_dir = Path(output_dir)
    for tf in TOPICS:
        name = f"atc-scheduled-snapshot-{tf}"
        listing = _json_read(client, root + "/artifacts", params={"name": name, "per_page": 5})
        artifacts = listing.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) > 5:
            raise ValueError("invalid_artifact_listing")
        best = None
        for item in artifacts:
            if item.get("name") != name or item.get("expired"):
                continue
            run_id = item.get("workflow_run", {}).get("id")
            artifact_id = item.get("id")
            if type(run_id) is not int or run_id <= 0 or type(artifact_id) is not int or artifact_id <= 0:
                raise ValueError("invalid_artifact_run_identity")
            if run_id not in runs:
                runs[run_id] = _json_read(client, f"{root}/runs/{run_id}")
            run = runs[run_id]
            if (not _trusted_run(run, repository, WORKFLOW)
                    or not re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))):
                continue

            def download(artifact_id=artifact_id):
                content = bytearray()
                with client.stream("GET", f"{root}/artifacts/{artifact_id}/zip") as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_ARCHIVE:
                            raise ValueError("ram_packet_archive_too_large")
                return bytes(content)

            try:
                files, observed = unpack_packet(_retry_read(download), tf)
            except (ValueError, KeyError, zipfile.BadZipFile):
                # Failed/partial timeframe jobs have no complete publication ACK.
                continue
            if best is None or observed > best[0]:
                best = (observed, files, run_id, run)
        if best is None:
            continue
        _, files, run_id, run = best
        folder = output_dir / tf
        if folder.exists():
            raise ValueError("restore_requires_new_output_directory")
        folder.mkdir(parents=True)
        for filename, content in files.items():
            (folder / filename).write_bytes(content)
        sources[tf] = {"run_id": run_id, "head_sha": run["head_sha"], "head_branch": "main",
            "event": run["event"], "head_repository": repository, "artifact_name": name}
    name = "atc-scheduled-intersection-delivery"
    listing = _json_read(client, root + "/artifacts", params={"name": name, "per_page": 5})
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > 5:
        raise ValueError("invalid_intersection_receipt_listing")
    previous = None
    for item in artifacts:
        if item.get("name") != name or item.get("expired"):
            continue
        run_id, artifact_id = item.get("workflow_run", {}).get("id"), item.get("id")
        if type(run_id) is not int or run_id <= 0 or type(artifact_id) is not int or artifact_id <= 0:
            raise ValueError("invalid_intersection_receipt_run")
        if run_id not in runs:
            runs[run_id] = _json_read(client, f"{root}/runs/{run_id}")
        if not _trusted_run(runs[run_id], repository, WORKFLOW):
            continue

        def download_receipt(artifact_id=artifact_id):
            content = bytearray()
            with client.stream("GET", f"{root}/artifacts/{artifact_id}/zip") as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 100_000:
                        raise ValueError("intersection_receipt_archive_too_large")
            return bytes(content)

        try:
            receipt, updated = unpack_intersection_receipt(_retry_read(download_receipt))
        except (ValueError, KeyError, zipfile.BadZipFile):
            continue
        if previous is None or updated > previous[0]:
            previous = (updated, receipt)
    if previous is not None:
        _atomic_json(output_dir / "previous-intersection-receipt.json", previous[1])
    result = {"schema": 1, "repository": repository,
        "workflow": ".github/workflows/" + WORKFLOW, "sources": sources}
    _atomic_json(output_dir / "source-runs.json", result)
    return {"status": "acknowledged_main_packets_restored", "timeframes": sorted(sources)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore_packets(args.repository, args.output_dir)))


if __name__ == "__main__":
    main()
