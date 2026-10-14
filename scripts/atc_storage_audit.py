#!/usr/bin/env python3
"""Read-only storage audit for ATC's immutable canonical OHLCV history.

Candidates are informational. Do NOT delete history referenced by snapshots,
MA research or backtests without an archived backup and referential audit.
"""
from __future__ import annotations

import json
import os

SQL = """
WITH ranked AS (
    SELECT timeframe,
           row_number() OVER (
               PARTITION BY instrument_id, timeframe, source, price_basis, series_revision
               ORDER BY close_time DESC
           ) AS age_rank
    FROM canonical_market_bars
)
SELECT timeframe,
       count(*) AS stored,
       count(*) FILTER (
           WHERE age_rank > CASE
               WHEN timeframe = '1wk' THEN 800
               ELSE 1000
           END
       ) AS beyond_maintenance_threshold
FROM ranked GROUP BY timeframe ORDER BY timeframe
"""


def main() -> None:
    uri = os.getenv("DATABASE_URL")
    if not uri:
        raise SystemExit("DATABASE_URL secret missing")
    import psycopg

    with psycopg.connect(uri) as db, db.cursor() as cursor:
        cursor.execute(SQL)
        rows = [
            {
                "timeframe": timeframe,
                "stored_bars": stored,
                "older_than_window": older,
                "deleted": 0,
            }
            for timeframe, stored, older in cursor.fetchall()
        ]
    print(json.dumps(
        {
            "retention_policy": "AUDIT_ONLY",
            "minimum_proposed_keep": {"weekly": 800, "other_timeframes": 1000},
            "details": rows,
            "note": (
                "Rows older than the window are NOT automatically safe to delete: "
                "snapshot references, audit history, adjustment revisions and "
                "backtest reproducibility must be checked before pruning."
            ),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
