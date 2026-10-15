"""Fail closed before large ATC scan writes approach Neon free storage limit.

Pure read-only safety check. Configuration uses decimal MB (1,000,000 bytes).
Does not alter existing market history or Telegram state.
"""
from __future__ import annotations

import argparse
import os


def check_database_capacity(database_bytes: int, *, soft_limit_mb: int = 900) -> None:
    """Reject unsafe new scans; no rows are changed."""
    if soft_limit_mb < 100:
        raise ValueError("soft_limit_mb must be at least 100")
    used_mb = database_bytes / 1_000_000
    print(
        f"ATC storage guard: {used_mb:.1f} MB used / "
        f"{soft_limit_mb} MB user-configurable safe limit",
        flush=True,
    )
    if database_bytes >= soft_limit_mb * 1_000_000:
        raise RuntimeError(
            f"ATC PostgreSQL storage too high: {used_mb:.1f} MB. "
            "Market scan BLOCKED to preserve remaining free space. "
            "Existing results are untouched. Archive/compact historical "
            "canonical_market_bars before resuming; do NOT delete blindly."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit-mb", type=int,
        default=int(os.environ.get("ATC_DB_SOFT_LIMIT_MB") or "900"),
    )
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL secret is required")
    import psycopg

    with psycopg.connect(url, connect_timeout=15) as db:
        db_bytes = db.execute(
            "SELECT pg_database_size(current_database())"
        ).fetchone()[0]
    check_database_capacity(db_bytes, soft_limit_mb=args.limit_mb)


if __name__ == "__main__":
    main()
