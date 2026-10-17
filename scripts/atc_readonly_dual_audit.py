"""Export ALL 630 verified scan outcomes without sending any Telegram messages."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_ephemeral_universe import assert_local_ephemeral_url
from scripts.atc_export_dashboard import LATEST_SQL
from scripts.atc_full_universe_status import universe_status_csv
from scripts.atc_saved_scan_plans import load_saved_trade_plans
from scripts.atc_timeframe_visuals import require_complete_publication, select_verified_matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify-plans", action="store_true",
                        help="Validate every directional same-snapshot Stop/TP before any Telegram publish")
    args = parser.parse_args()
    url = os.environ["DATABASE_URL"]
    assert_local_ephemeral_url(url)
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    import psycopg

    with psycopg.connect(url, autocommit=True) as db:
        members = PostgresRuntimeRepository(db).list_universe("ATC_630", as_of=now.date())
        if len(members) != 630:
            raise ValueError(f"Real universe must have 630, got {len(members)}")
        bindings = load_scanner_catalog(
            Path("config/scanners.toml"),
            calendar_version=ExchangeCalendarsXist().version,
        )
        with db.cursor() as cur:
            cur.execute(LATEST_SQL, ("ATC_630", [m.instrument_id for m in members]))
            evaluations = cur.fetchall()
    close, covered, matches = select_verified_matches(
        members, evaluations, bindings, args.timeframe, now=now,
    )
    data, counts = universe_status_csv(
        members, evaluations, bindings, args.timeframe, close,
    )
    if covered != 630 or counts["members"] != 630 or counts.get("match", 0) != len(matches):
        raise RuntimeError("Real scanner evidence is not exactly 630/630")
    sides = Counter()
    for _symbol, number, state in matches:
        if 1 <= number <= 9:
            sides[state] += 1
    plan_audit = None
    if args.verify_plans:
        with psycopg.connect(url, autocommit=True) as db:
            plans, failures = load_saved_trade_plans(
                db, members=members, evaluations=evaluations, matches=matches,
                timeframe=args.timeframe, bar_time=close,
                include_model_failures=True,
            )
        plan_audit = require_complete_publication(
            timeframe=args.timeframe, covered=covered, matches=matches,
            plans=plans, model_failures=failures,
        )
    report = {
        "timeframe": args.timeframe, "confirmed_bar": close.isoformat(),
        "covered": covered, "matches": len(matches),
        "A_I_directions": dict(sides), **counts,
        "read_only": True, "telegram_sent": False,
        "pine_modified": False,
        "risk_gate_checked": bool(args.verify_plans),
        "risk_gate": plan_audit,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ATC_630_TUM_KOSULLAR.csv").write_bytes(data)
    (args.out / "ATC_readonly_diagnostics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print("ATC READ ONLY COMPLETE AUDIT " + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
