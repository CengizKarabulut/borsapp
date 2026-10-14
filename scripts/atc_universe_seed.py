"""Versioned ATC_630 universe, separate from official provider BIST_ALL.

The user-maintained 630 inventory is a scanning *target*. Symbols not currently
returned by XUTUM are still retained and will be logged as unavailable on fetch;
this does not claim they are exchange-listed or have current OHLCV.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.market_data.adapters.borsapy_universe import BorsapyBistUniverseProvider
from market_intelligence.market_data.universe import (
    UniverseMember,
    build_universe_sync_plan,
    validate_universe_sync_plan,
)
from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository

TARGET = "ATC_630"


def load_pinned(path: Path) -> tuple[str, ...]:
    entries = [
        line.strip().upper()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(entries) != 630 or len(set(entries)) != 630:
        raise ValueError(
            f"ATC hedef listesi tam 630 benzersiz sembol olmalı: {len(entries)} kayıt"
        )
    from market_intelligence.market_data.adapters.borsapy_universe import SYMBOL_PATTERN
    invalid = [s for s in entries if not SYMBOL_PATTERN.fullmatch(s)]
    if invalid:
        raise ValueError(f"Geçersiz ATC sembolleri: {invalid[:10]}")
    return tuple(sorted(entries))


def reconcile(pinned: tuple[str, ...], observed: tuple[UniverseMember, ...]):
    present = {item.symbol: item for item in observed}
    missing = tuple(sorted(set(pinned) - set(present)))
    outside = tuple(sorted(set(present) - set(pinned)))
    members = tuple(
        UniverseMember(
            symbol=symbol,
            provider_symbol=present[symbol].provider_symbol if symbol in present else symbol,
            name=present[symbol].name if symbol in present else symbol,
        )
        for symbol in pinned
    )
    return members, missing, outside


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=Path, default=Path("config/atc_630_symbols.txt"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("runtime_artifacts/ATC_630_Evren_Denetimi.json"))
    args = parser.parse_args()
    pinned = load_pinned(args.symbols)
    observed = BorsapyBistUniverseProvider().list_members("BIST_ALL")
    members, missing, outside = reconcile(pinned, observed)
    as_of = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    url = os.getenv("DATABASE_URL", "")
    if not url:
        parser.error("DATABASE_URL secret gerekli; dosyaya veya koda eklemeyin")
    import psycopg
    with psycopg.connect(url) as db:
        repository = PostgresRuntimeRepository(db)
        active = repository.list_universe(TARGET, as_of=as_of)
        plan = build_universe_sync_plan(
            universe_id=TARGET,
            source="ATC:PINNED630+XUTUM_DIAGNOSTICS",
            as_of=as_of,
            members=members,
            current_symbols=tuple(item.symbol for item in active),
        )
        validate_universe_sync_plan(plan, minimum_members=630)
        result = {
            "as_of": as_of.isoformat(),
            "target": TARGET,
            "pinned": len(pinned),
            "xutum_observed": len(observed),
            "missing_from_xutum_count": len(missing),
            "missing_from_xutum": missing,
            "xutum_outside_target_count": len(outside),
            "xutum_outside_target": outside,
            "current_target_members": len(active),
            "to_add": len(plan.additions),
            "to_remove": len(plan.removals),
            "applied": False,
            "note": "Listelenmeyen semboller için gerçek OHLCV sonucu garanti edilmez.",
        }
        if args.apply:
            repository.apply_universe_sync(plan)
            result["applied"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
