"""Export actual same-snapshot OHLC and risk diagnostics for model-rejected matches.

Read only canonical bars stored by the scanner run; never use substitute prices.
"""
import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.scanning.display_codes import SCANNER_ORDER
from scripts.atc_export_dashboard import LATEST_SQL
from scripts.atc_risk_parity_audit import diagnose
from scripts.atc_saved_scan_plans import (
    SNAPSHOT_IDENTITIES_SQL,
    _exact_frame_from_saved_bars,
    load_saved_trade_plans,
)
from scripts.atc_timeframe_visuals import select_verified_matches
from market_intelligence.scanning.catalog import load_scanner_catalog
from scripts.atc_timeframe_visuals import ISTANBUL
from market_intelligence.scheduling.xist import ExchangeCalendarsXist


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", choices=["1d", "1wk"], required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        members = PostgresRuntimeRepository(db).list_universe("ATC_630", as_of=datetime.now(ISTANBUL).date())
        if len(members) != 630:
            raise RuntimeError(f"Expected 630 symbols; got {len(members)}")
        bindings = load_scanner_catalog(Path("config/scanners.toml"), calendar_version=ExchangeCalendarsXist().version)
        with db.cursor() as cur:
            cur.execute(LATEST_SQL, ("ATC_630", [m.instrument_id for m in members]))
            evaluations = cur.fetchall()
        close, covered, matches = select_verified_matches(members, evaluations, bindings, args.timeframe, now=datetime.now(ISTANBUL))
        if covered != 630:
            raise RuntimeError(f"Incomplete source coverage: {covered}/630")
        _plans, failures = load_saved_trade_plans(db, members=members, evaluations=evaluations,
            matches=matches, timeframe=args.timeframe, bar_time=close, include_model_failures=True)
        ids = list({str(e[8]) for e in evaluations if e[1] == args.timeframe and e[5] == close and e[6] == "match"})
        with db.cursor() as cur:
            cur.execute(SNAPSHOT_IDENTITIES_SQL, (ids,))
            identities = cur.fetchall()
        symbols = {str(m.instrument_id): m.symbol for m in members}
        rows = []
        for identity in identities:
            eid, instrument, scanner, snapshot_id, source, basis, revision, start, end, count, tf, evaluated_close = identity
            if scanner not in SCANNER_ORDER or tf != args.timeframe or evaluated_close != close:
                continue
            number = SCANNER_ORDER.index(scanner) + 1
            symbol = symbols.get(str(instrument))
            for state, direction in (("POZITIF", "bullish"), ("NEGATIF", "bearish")):
                key = symbol, number, state
                if key not in failures:
                    continue
                with db.cursor() as cur:
                    frame = _exact_frame_from_saved_bars(cur, identity)
                if frame is None:
                    raise RuntimeError(f"Exact snapshot missing for {key}")
                ohlc = [{"open": float(b.open), "high": float(b.high),
                         "low": float(b.low), "close": float(b.close)} for b in frame.bars]
                diagnostic = diagnose(ohlc, scanner, direction)
                diagnostic.update({"symbol": symbol, "timeframe": tf,
                    "scanner_code": number, "direction": state, "snapshot_id": str(snapshot_id),
                    "source": source, "price_basis": basis, "series_revision": revision,
                    "bar_close": str(close), "model_reason": failures[key]})
                rows.append(diagnostic)
                with (out / f"{args.timeframe}_{symbol}_{number}_{state}_ohlc.csv").open("w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=["open", "high", "low", "close"])
                    writer.writeheader()
                    writer.writerows(ohlc)
        if len(rows) != len(failures):
            raise RuntimeError(f"Diagnostic rows {len(rows)} != model failures {len(failures)}")
        (out / f"{args.timeframe}_risk_diagnostics.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        print(f"Verified exact OHLC risk diagnostics: {args.timeframe} {len(rows)} model-rejected plans", flush=True)


if __name__ == "__main__":
    main()
