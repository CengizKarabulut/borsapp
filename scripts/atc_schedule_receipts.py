"""Restore and record acknowledged snapshot deliveries, without market/DB writes."""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import zipfile
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from time import sleep as blocking_sleep
from uuid import uuid4

import httpx

from scripts.atc_snapshot_schedule import (
    IST,
    LEDGER_SCHEMA,
    SUPPORTED_TIMEFRAMES,
    _parse_timestamp,
    _scheduled_at,
    slot_key,
    validate_delivery_state,
)

API = "https://api.github.com"
MAX_ARCHIVE = 2 * 1024 * 1024
MAX_STATE = 100 * 1024
PACKET_VERSION = "atc-unpersisted-latest-candle-v1"
PACKET_FILES = ("live-snapshot.json", "live-snapshot.csv", "live-snapshot.txt", "live-snapshot.png")
SLOT_FIELDS = {"timeframe", "slot_key", "session", "target_close", "scheduled_at",
               "lateness_seconds", "missed_slot_count", "manual_only"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _retry_read(operation, *, sleep=None):
    """Retry only transient reads; malformed state never becomes a cold start."""
    wait = blocking_sleep if sleep is None else sleep
    for attempt in range(3):
        try:
            return operation()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in RETRYABLE_STATUS:
                raise
            if attempt == 2:
                raise
            delay = (2, 5)[attempt]
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    requested = float(exc.response.headers.get("Retry-After", ""))
                except ValueError:
                    requested = 0
                if math.isfinite(requested):
                    delay = min(10, max(delay, requested))
            wait(delay)


def _json_read(client: httpx.Client, url: str, *, params=None, sleep=None):
    def read():
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    return _retry_read(read, sleep=sleep)


def _atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
                             encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_slot(slot: object) -> dict:
    if not isinstance(slot, dict) or set(slot) - SLOT_FIELDS or SLOT_FIELDS - {"manual_only"} - set(slot):
        raise ValueError("invalid_schedule_slot_fields")
    tf = slot.get("timeframe")
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError("unsupported_schedule_timeframe")
    target = _parse_timestamp(slot["target_close"])
    scheduled = _parse_timestamp(slot["scheduled_at"])
    if (slot["session"] != target.date().isoformat()
            or slot["slot_key"] != slot_key(tf, target)
            or scheduled != _scheduled_at(target, tf)):
        raise ValueError("schedule_slot_identity_mismatch")
    if "manual_only" in slot and type(slot["manual_only"]) is not bool:
        raise ValueError("invalid_manual_preview_flag")
    for key in ("lateness_seconds", "missed_slot_count"):
        if type(slot[key]) is not int or slot[key] < 0:
            raise ValueError("invalid_schedule_slot_counter")
    return slot


def _verify_packet(folder: Path, slot: dict) -> tuple[dict, str]:
    _validate_slot(slot)
    manifest_path = folder / "prepared-packet.json"
    if manifest_path.is_symlink():
        raise ValueError("symlinked_prepared_packet")
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if (manifest.get("version") != PACKET_VERSION
            or set(manifest.get("files", {})) != set(PACKET_FILES)):
        raise ValueError("invalid_prepared_packet_manifest")
    for name in PACKET_FILES:
        file = folder / name
        if file.is_symlink() or sha256(file.read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError("prepared_packet_file_hash_changed")
    report = json.loads((folder / PACKET_FILES[0]).read_bytes())
    if (report.get("version") != PACKET_VERSION or report.get("timeframe") != slot["timeframe"]
            or report.get("provisional") is not True or report.get("confirmed_store_writes") != 0):
        raise ValueError("prepared_report_schedule_identity_mismatch")
    return report, sha256(raw).hexdigest()


def stamp_packet(packet_dir: Path, slot: dict) -> dict:
    folder = Path(packet_dir)
    _verify_packet(folder, slot)
    sidecar = folder / "scheduled-slot.json"
    if sidecar.exists() and json.loads(sidecar.read_bytes()) != slot:
        raise ValueError("prepared_packet_schedule_context_changed")
    _atomic_json(sidecar, slot)
    return {"status": "schedule_context_attached", "timeframe": slot["timeframe"],
            "manual_only": slot.get("manual_only", False)}


def record_receipt(packet_dir: Path, slot: dict, output_dir: Path) -> dict:
    _validate_slot(slot)
    if slot.get("manual_only") is True:
        return {"status": "manual_only_no_delivery_watermark", "timeframe": slot["timeframe"]}
    folder = Path(packet_dir)
    report, packet_hash = _verify_packet(folder, slot)
    if json.loads((folder / "scheduled-slot.json").read_bytes()) != slot:
        raise ValueError("prepared_packet_schedule_context_changed")
    receipt = json.loads((folder / "publication-receipt.json").read_bytes())
    state = {"schema": LEDGER_SCHEMA, **slot, "sent": True,
             "packet_sha256": packet_hash, "receipt": receipt,
             "observed_at": report.get("observation_end"),
             "recorded_at": datetime.now(IST).isoformat()}
    validate_delivery_state(state)
    path = Path(output_dir) / f"{slot['timeframe']}.json"
    if path.exists():
        previous = validate_delivery_state(json.loads(path.read_bytes()))
        if _parse_timestamp(previous["target_close"]) > _parse_timestamp(state["target_close"]):
            raise ValueError("delivery_watermark_cannot_move_backwards")
    _atomic_json(path, state)
    return {"status": "acknowledged_delivery_recorded", "timeframe": slot["timeframe"],
            "slot_key": slot["slot_key"]}


def _positive_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("invalid_github_artifact_identity")
    return value


def _trusted_run(run: object, repository: str, workflow: str) -> bool:
    return (isinstance(run, dict)
            and run.get("path") == f".github/workflows/{workflow}"
            and run.get("head_branch") == "main"
            and run.get("event") in ("workflow_dispatch", "schedule")
            and isinstance(run.get("head_repository"), dict)
            and run["head_repository"].get("full_name") == repository)


def _read_state_zip(raw: bytes, timeframe: str) -> dict:
    if len(raw) > MAX_ARCHIVE:
        raise ValueError("delivery_artifact_archive_too_large")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (len(entries) != 1 or entries[0].filename != f"{timeframe}.json"
                    or entries[0].file_size > MAX_STATE or entries[0].flag_bits & 1):
                raise ValueError("delivery_artifact_must_contain_one_bounded_state_file")
            with archive.open(entries[0]) as stream:
                content = stream.read(MAX_STATE + 1)
            if len(content) > MAX_STATE:
                raise ValueError("delivery_artifact_state_too_large")
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid_delivery_artifact_zip") from exc
    state = validate_delivery_state(json.loads(content))
    if state["timeframe"] != timeframe:
        raise ValueError("delivery_artifact_timeframe_mismatch")
    return state


def _download_once(client: httpx.Client, url: str) -> bytes:
    content = bytearray()
    with client.stream("GET", url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > MAX_ARCHIVE:
                raise ValueError("delivery_artifact_archive_too_large")
    return bytes(content)


def _download(client: httpx.Client, url: str, *, sleep=None) -> bytes:
    # Every retry starts from the original GitHub API URL, obtaining a fresh
    # signed redirect rather than repeatedly requesting a failed CDN URL.
    return _retry_read(lambda: _download_once(client, url), sleep=sleep)


def restore_receipts(repository: str, workflow: str, output_dir: Path, *, client=None,
                     token: str | None = None, sleep=None) -> dict:
    """Restore main-workflow ACKs, selecting by logical target, never upload time.

    A failed overall workflow may still contain valid completed timeframe ACKs.
    Such acknowledgements remain valid; untrusted forks/other workflows do not.
    The default httpx redirect behavior strips authorization cross-origin.
    """
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[A-Za-z0-9_-]+\.ya?ml", workflow)):
        raise ValueError("invalid_github_repository_or_workflow")
    if client is None:
        token = token or os.environ.get("GH_TOKEN")
        if not token:
            raise ValueError("github_read_actions_token_required")
        with httpx.Client(timeout=30, follow_redirects=True, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }) as owned:
            return restore_receipts(repository, workflow, output_dir, client=owned, sleep=sleep)

    root = f"{API}/repos/{repository}/actions"
    runs = {}
    selected = {}
    ignored = 0
    for tf in SUPPORTED_TIMEFRAMES:
        name = f"atc-scheduled-delivery-{tf}"
        listing = _json_read(client, f"{root}/artifacts", params={"name": name, "per_page": 10},
                             sleep=sleep)
        artifacts = listing.get("artifacts") if isinstance(listing, dict) else None
        if not isinstance(artifacts, list) or len(artifacts) > 10:
            raise ValueError("invalid_github_artifact_listing")
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("name") != name:
                raise ValueError("github_artifact_name_mismatch")
            if artifact.get("expired") is True:
                continue
            artifact_id = _positive_id(artifact.get("id"))
            run_info = artifact.get("workflow_run")
            if not isinstance(run_info, dict):
                raise ValueError("github_artifact_workflow_identity_missing")
            run_id = _positive_id(run_info.get("id"))
            if run_id not in runs:
                runs[run_id] = _json_read(client, f"{root}/runs/{run_id}", sleep=sleep)
            if not _trusted_run(runs[run_id], repository, workflow):
                ignored += 1
                continue
            expected_url = f"{root}/artifacts/{artifact_id}/zip"
            if artifact.get("archive_download_url") != expected_url:
                raise ValueError("github_artifact_download_url_mismatch")
            state = _read_state_zip(_download(client, expected_url, sleep=sleep), tf)
            previous = selected.get(tf)
            if previous is None or _parse_timestamp(state["target_close"]) > _parse_timestamp(previous["target_close"]):
                selected[tf] = state
    # No writes occur until every bounded trusted candidate has validated.
    for tf, state in selected.items():
        _atomic_json(Path(output_dir) / f"{tf}.json", state)
    return {"status": "restored", "timeframes": list(selected), "restored": len(selected),
            "untrusted_artifacts_ignored": ignored}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--restore", action="store_true")
    mode.add_argument("--stamp-packet", action="store_true")
    mode.add_argument("--record", action="store_true")
    parser.add_argument("--repository", default="CengizKarabulut/borsapp")
    parser.add_argument("--workflow", default="atc-scheduled-snapshots.yml")
    parser.add_argument("--packet-dir", type=Path)
    parser.add_argument("--slot-json")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.restore:
        if args.output_dir is None:
            parser.error("--restore requires --output-dir")
        result = restore_receipts(args.repository, args.workflow, args.output_dir)
    else:
        if args.packet_dir is None or args.slot_json is None:
            parser.error("packet modes require --packet-dir and --slot-json")
        slot = json.loads(args.slot_json)
        if args.stamp_packet:
            result = stamp_packet(args.packet_dir, slot)
        else:
            if args.output_dir is None:
                parser.error("--record requires --output-dir")
            result = record_receipt(args.packet_dir, slot, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return result


if __name__ == "__main__":
    main()
