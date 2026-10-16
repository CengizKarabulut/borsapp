"""Export confirmed latest ATC scanner findings from a throwaway DB as tiny JSON.

This is a RESULT DIGEST, never synthetic OHLCV. For EOD Kesişim reports
the downstream workflow consumes only fully validated scanner/version hashes.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_ephemeral_universe import assert_local_ephemeral_url
from scripts.atc_export_dashboard import LATEST_SQL, SCANNER_ORDER
from scripts.atc_timeframe_visuals import select_verified_matches

ISTANBUL = ZoneInfo("Europe/Istanbul")


def verified_digest(db, *, timeframe: str, now: datetime):
    members = PostgresRuntimeRepository(db).list_universe("ATC_630", as_of=now.date())
    if len(members) != 630:
        raise ValueError(f"ATC_630 ephemeral members incomplete {len(members)}/630")
    bindings = load_scanner_catalog(
        Path("config/scanners.toml"), calendar_version=ExchangeCalendarsXist().version,
    )
    if len(bindings) != 18:
        raise ValueError("Original 18 ATC rule hashes must be loaded")
    with db.cursor() as cursor:
        cursor.execute(LATEST_SQL, ("ATC_630", [m.instrument_id for m in members]))
        evaluations = cursor.fetchall()
    bar, covered, matches = select_verified_matches(
        members, evaluations, bindings, timeframe, now=now,
    )
    return {
        "schema": "atc-verified-timeframe-digest-v1",
        "timeframe": timeframe,
        "bar_close": bar.isoformat(),
        "covered": covered,
        "universe": 630,
        "entries": [
            {"symbol": symbol, "scanner": SCANNER_ORDER[number - 1], "direction":
             "bullish" if status == "POZITIF" else "bearish"}
            for symbol, number, status in matches
            if status in ("POZITIF", "NEGATIF")
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL", "")
    assert_local_ephemeral_url(url)
    import psycopg

    with psycopg.connect(url) as db:
        data = verified_digest(
            db, timeframe=args.timeframe, now=datetime.now(ISTANBUL),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(
        f"ATC digest {data['timeframe']}: {data['covered']}/630 covered, "
        f"{len(data['entries'])} verified directional signals", flush=True,
    )


if __name__ == "__main__":
    main()
