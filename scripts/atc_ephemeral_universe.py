"""Initialize ATC_630 in an isolated short-lived PostgreSQL scan runner.

The PINNED 630-user-symbol inventory is the truth. This avoids making the
external XUTUM list a prerequisite for an ephemeral scanner, without claiming
that missing symbols are currently listed or tradable. Real price providers
still must supply every evaluated candle; no price or signal is fabricated.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from market_intelligence.market_data.universe import (
    UniverseMember,
    build_universe_sync_plan,
    validate_universe_sync_plan,
)
from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from scripts.atc_universe_seed import load_pinned


def seed_ephemeral_universe(db, *, path: Path, on_date):
    symbols = load_pinned(path)
    members = tuple(
        UniverseMember(
            symbol=symbol, provider_symbol=symbol, name=symbol,
        )
        for symbol in symbols
    )
    repository = PostgresRuntimeRepository(db)
    current = repository.list_universe("ATC_630", as_of=on_date)
    plan = build_universe_sync_plan(
        universe_id="ATC_630",
        source="ATC:PINNED630_EPHEMERAL",
        as_of=on_date,
        members=members,
        current_symbols=tuple(x.symbol for x in current),
    )
    validate_universe_sync_plan(plan, minimum_members=630)
    repository.apply_universe_sync(plan)
    actual = repository.list_universe("ATC_630", as_of=on_date)
    if len(actual) != 630 or len(set(x.symbol for x in actual)) != 630:
        raise RuntimeError("Ephemeral BIST market contains incomplete 630-symbol list")
    return actual


def assert_local_ephemeral_url(url: str) -> None:
    """Reject every remote DB hostname, even if query/password says localhost."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("Malformed PostgreSQL URL") from exc
    if (parsed.scheme not in ("postgresql", "postgres")
            or hostname not in ("localhost", "127.0.0.1")
            or parsed.path != "/atc_scan"):
        raise ValueError(
            "Ephemeral seed requires exactly the LOCAL atc_scan PostgreSQL database"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", type=Path,
        default=Path("config/atc_630_symbols.txt"),
    )
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL must point to runner-local PostgreSQL")
    # Safeguard: NEVER initialize or mutate the user's persistent database.
    assert_local_ephemeral_url(url)
    import psycopg
    today = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    with psycopg.connect(url) as db:
        actual = seed_ephemeral_universe(db, path=args.symbols, on_date=today)
    print(f"EPHEMERAL ATC inventory seeded {len(actual)}/630; "
          "no Neon/PostgreSQL cloud data was altered", flush=True)


if __name__ == "__main__":
    main()
