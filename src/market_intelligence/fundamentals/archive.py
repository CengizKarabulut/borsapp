"""Append-only financial observations; source revisions are never overwritten."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


def utc_stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Observation time must include a timezone")
    return value.astimezone(UTC).isoformat()


class FinancialArchive:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "financials.sqlite3"
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS observations (
                symbol TEXT NOT NULL, source TEXT NOT NULL, kind TEXT NOT NULL,
                observed_at TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(symbol, source, kind, observed_at, digest))""")
            db.execute(
                "CREATE INDEX IF NOT EXISTS observation_lookup ON observations(symbol, source, kind, observed_at)"
            )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def put(
        self, symbol: str, source: str, kind: str, payload: dict, *, observed_at: datetime
    ) -> str:
        if not re.fullmatch(r"[A-Z0-9]{2,12}", symbol):
            raise ValueError("Invalid canonical symbol")
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
        digest = hashlib.sha256(body.encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?)",
                (symbol, source, kind, utc_stamp(observed_at), digest, body),
            )
        return digest

    def latest(self, symbol: str, source: str, kind: str, *, known_at: datetime):
        with self.connect() as db:
            row = db.execute(
                """SELECT observed_at, digest, payload FROM observations
                WHERE symbol=? AND source=? AND kind=? AND observed_at<=?
                ORDER BY observed_at DESC, rowid DESC LIMIT 1""",
                (symbol, source, kind, utc_stamp(known_at)),
            ).fetchone()
        return None if row is None else (row[0], row[1], json.loads(row[2]))

    def put_frames(
        self,
        symbol: str,
        source: str,
        *,
        frames: dict,
        info: dict,
        fast: dict,
        observed_at: datetime,
        cumulative: bool,
    ):
        # Pandas JSON handles numpy scalars and missing values without non-standard NaN.
        payload = {
            "frames": {
                key: None
                if frame is None
                else json.loads(frame.to_json(orient="split", date_format="iso", force_ascii=False))
                for key, frame in frames.items()
            },
            "info": json.loads(pd.Series(info, dtype=object).to_json()),
            "fast": json.loads(pd.Series(fast, dtype=object).to_json()),
            "cumulative": cumulative,
        }
        return self.put(symbol, source, "statements", payload, observed_at=observed_at)

    def frames(self, symbol: str, source: str, *, known_at: datetime):
        observation = self.latest(symbol, source, "statements", known_at=known_at)
        if observation is None:
            return None
        stamp, digest, payload = observation
        frames = {
            key: None
            if value is None
            else pd.DataFrame(value["data"], index=value["index"], columns=value["columns"])
            for key, value in payload["frames"].items()
        }
        return stamp, digest, frames, payload["info"], payload["fast"], payload["cumulative"]

    def backup(self, destination: Path) -> dict:
        """Snapshot SQLite, then copy immutable KAP files referenced by that snapshot."""
        destination = Path(destination).resolve()
        source_root = self.root.resolve()
        if not self.database.is_file():
            raise FileNotFoundError(self.database)
        if destination == source_root or source_root in destination.parents:
            raise ValueError("Backup destination must be outside the source archive")
        destination.mkdir(parents=True, exist_ok=False)
        target_database = destination / "financials.sqlite3"
        target = sqlite3.connect(target_database)
        try:
            with self.connect() as source:
                source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite snapshot integrity check failed")
            references = {}
            for (body,) in target.execute("SELECT payload FROM observations"):
                payload = json.loads(body)
                if payload.get("raw_path"):
                    references[payload["raw_path"]] = payload.get("raw_sha256")
                for attachment in payload.get("attachments", []):
                    if attachment.get("path"):
                        references[attachment["path"]] = attachment.get("sha256")
        finally:
            target.close()
        manifest = {}
        for relative, expected in sorted(references.items()):
            # Archive metadata can originate on Windows or Linux.
            relative = relative.replace("\\", "/")
            source = (source_root / relative).resolve()
            output = (destination / relative).resolve()
            if source_root not in source.parents or destination not in output.parents:
                raise ValueError("Archive reference escapes its directory")
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
            if expected and actual != expected:
                raise ValueError(f"Archive checksum mismatch: {relative}")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, output)
            if hashlib.sha256(output.read_bytes()).hexdigest() != actual:
                raise ValueError(f"Backup checksum mismatch: {relative}")
            manifest[relative] = actual
        manifest["financials.sqlite3"] = hashlib.sha256(target_database.read_bytes()).hexdigest()
        result = {"completed_at": datetime.now(UTC).isoformat(), "files": manifest}
        # A missing manifest identifies an incomplete backup. Existing backups are never replaced.
        (destination / "backup-manifest.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result
