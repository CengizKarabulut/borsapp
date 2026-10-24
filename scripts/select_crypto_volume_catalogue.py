#!/usr/bin/env python3
"""Select a bounded, evidence-backed Binance spot USDT display catalogue.

Inputs are captured public TradingView exports and actual qualified DOM links.
The ranking snapshot is frozen; this tool does not fetch or refresh market data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

SOURCE_URL = "https://www.tradingview.com/cex-screener/"
CATEGORY_URL = "https://www.tradingview.com/crypto-coins-screener/"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def positive(value: str) -> Decimal | None:
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError):
        return None
    return number if number.is_finite() and number > 0 else None


def select_records(pair_rows: list[dict], category_rows: list[dict], *,
                   maximum: int = 400) -> tuple[list[dict], list[dict], list[dict]]:
    """Keep only consistently classified candidates; never guess missing tags."""
    categories: dict[str, list[dict]] = defaultdict(list)
    for row in category_rows:
        categories[row["Instrument"]].append({
            "name": row["Description"],
            "categories": [part.strip() for part in row["Category"].split(",") if part.strip()],
        })
    duplicates = [key for key, count in Counter(row["Symbol"] for row in pair_rows).items()
                  if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate source pair identifiers: {duplicates}")
    eligible, excluded = [], []
    for row in pair_rows:
        pair = row["Symbol"]
        base = pair[:-4] if pair.endswith("USDT") else ""
        candidates = categories.get(base, [])
        record = {
            "source_pair": pair, "base": base, "name": row["Description"],
            "price": row["Price"], "volume_usd_24h": row["Volume in USD, 24 hours"],
            "category_candidates": candidates,
            "category_status": "missing" if not candidates else
                               "ambiguous_ticker" if len(candidates) > 1 else "matched_ticker",
        }
        reasons = []
        if row["Exchange"] != "Binance" or row["Price - Currency"] != "USDT":
            reasons.append("outside_binance_usdt_scope")
        if not base or "." in pair:
            reasons.append("not_plain_spot_usdt_identifier")
        if positive(record["price"]) is None or positive(record["volume_usd_24h"]) is None:
            reasons.append("nonpositive_or_nonfinite_price_volume")
        if any("Stablecoins" in item["categories"] for item in candidates):
            reasons.append("explicit_stablecoins_category_tag")
        if any("tokenized" in item["name"].lower() and
               any(word in item["name"].lower() for word in ("stock", "etf"))
               for item in candidates):
            reasons.append("explicit_tokenized_stock_or_etf_name")
        if row["Description"] == "Euro / TetherUS":
            reasons.append("explicit_euro_fiat_name")
        if not candidates:
            reasons.append("missing_base_category_join")
        elif any(not item["categories"] for item in candidates):
            reasons.append("unclassified_category_candidate")
        if reasons:
            excluded.append({**record, "reasons": reasons})
        else:
            eligible.append(record)
    eligible.sort(key=lambda row: (-Decimal(row["volume_usd_24h"]), row["source_pair"]))
    unique, seen_base = [], set()
    for record in eligible:
        if record["base"] in seen_base:
            excluded.append({**record, "reasons": ["duplicate_base_lower_volume"]})
        else:
            seen_base.add(record["base"])
            unique.append(record)
    selected = unique[:maximum]
    for rank, record in enumerate(selected, 1):
        record["selection_rank"] = rank
    return selected, excluded, unique[maximum:]


def qualify_records(selected: list[dict], dom_rows: list[dict]) -> list[dict]:
    """Require the actual exchange-qualified ID, URL and name for every member."""
    by_pair = {}
    for record in dom_rows:
        ticker = record["ticker"]
        if ticker in by_pair and by_pair[ticker] != record:
            raise ValueError(f"Conflicting captured DOM identity: {ticker}")
        by_pair[ticker] = record
    result = []
    for record in selected:
        pair = record["source_pair"]
        actual = by_pair.get(pair)
        if actual is None:
            raise ValueError(f"Selected pair has no actual qualified DOM proof: {pair}")
        url = urljoin(SOURCE_URL, actual["url"])
        parsed = urlparse(url)
        if (actual["symbol"] != f"BINANCE:{pair}" or parsed.hostname != "www.tradingview.com"
                or parsed.path != f"/symbols/{pair}/"
                or parse_qs(parsed.query).get("exchange") != ["BINANCE"]
                or actual["name"] != record["name"]):
            raise ValueError(f"Qualified DOM ID/URL/name disagrees with frozen CSV: {pair}")
        result.append({**record, "symbol": actual["symbol"], "url": url})
    return result


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs", type=Path)
    parser.add_argument("categories", type=Path)
    parser.add_argument("--dom", type=Path, nargs="+", required=True)
    parser.add_argument("--source-sha256", required=True, help="Pin the reviewed ranking snapshot")
    parser.add_argument("--output", type=Path, required=True, help="Catalogue JSON; sidecar is adjacent")
    args = parser.parse_args()
    if sha256(args.pairs) != args.source_sha256:
        parser.exit(2, "Frozen pair CSV hash changed; do not silently refresh the ranking\n")
    pairs, categories = read_csv(args.pairs), read_csv(args.categories)
    selected, excluded, below_cutoff = select_records(pairs, categories)
    if not 350 <= len(selected) <= 400:
        parser.exit(2, f"Reviewed scope requires 350–400 classified pairs, found {len(selected)}\n")
    dom_rows = [record for path in args.dom
                for record in json.loads(path.read_text(encoding="utf-8-sig"))]
    qualified = qualify_records(selected, dom_rows)
    captured = datetime.fromtimestamp(args.pairs.stat().st_mtime, UTC).isoformat()
    scope = (
        f"Selected {len(qualified)} distinct-base Binance spot USDT pairs from {len(pairs)} "
        "TradingView CEX Screener export rows, frozen 24h USD volume descending. "
        "Positive finite price/volume; explicit Stablecoins category-tag and tokenized-stock/ETF "
        "name hits, Euro fiat, missing/empty category joins excluded. Ambiguous ticker joins "
        "retained only if every category candidate is allowed. Actual qualified BINANCE links "
        "and displayed names verified for every selected pair. Static volume proxy, not social "
        "mentions, all coins, all venues or futures; source metadata in provenance."
    )
    catalogue = {
        "schema_version": 1, "universe_id": "crypto-coins",
        "title": f"KRİPTO {len(qualified)} HACİM",
        "catalogue": {
            "source": "tradingview-screener", "url": SOURCE_URL,
            "captured_at": captured, "scope": scope, "coverage": "partial",
            "row_count": len(qualified),
        },
        "symbols": [{"symbol": row["symbol"], "name": row["name"]} for row in qualified],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    provenance = {
        "schema_version": 1, "catalogue_file": args.output.name,
        "catalogue_sha256": sha256(args.output), "captured_at": captured,
        "timestamp_policy": "Pair CSV local file-write UTC; snapshot capture, not an exchange tick timestamp.",
        "source": {
            "url": SOURCE_URL, "filters": {"exchange": "Binance", "type": "Spot", "quote": "USDT"},
            "export_file": args.pairs.name, "export_sha256": sha256(args.pairs), "row_count": len(pairs),
            "category_url": CATEGORY_URL, "category_file": args.categories.name,
            "category_sha256": sha256(args.categories), "category_row_count": len(categories),
            "dom_captures": [{"file": path.name, "sha256": sha256(path),
                              "row_count": len(json.loads(path.read_text(encoding="utf-8-sig")))}
                             for path in args.dom],
        },
        "selection": {
            "maximum": 400, "minimum_reviewed_scope": 350, "selected_count": len(qualified),
            "metric": "Volume in USD, 24 hours", "order": "descending; exact pair ID ascending on ties",
            "unique_key": "base asset after removing USDT suffix from actual spot pair ID",
            "social_mentions_measured": False, "automatic_membership_refresh": False,
            "category_join": "Exact base ticker; all candidates retained, never claim a unique project mapping when ambiguous.",
            "category_filter_caveat": "Stablecoins is a source category/ecosystem tag, not proof the token itself is stable; USUAL is excluded by tag, not labelled intrinsically stable.",
            "unknown_policy": "Missing category join or any empty category candidate excluded; no invented classifications.",
            "retained_ambiguous_symbols": [row["symbol"] for row in qualified
                                           if row["category_status"] == "ambiguous_ticker"],
            "cutoff": {"symbol": qualified[-1]["symbol"],
                       "volume_usd_24h": qualified[-1]["volume_usd_24h"]},
        },
        "excluded_count": len(excluded), "exclusions": excluded,
        "below_cutoff_count": len(below_cutoff), "below_cutoff": below_cutoff,
        "records": qualified,
    }
    sidecar = args.output.with_name(args.output.stem + ".provenance.json")
    sidecar.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8", newline="\n")
    print(json.dumps({"selected": len(qualified), "excluded": len(excluded),
                      "groups": (len(qualified) + 9) // 10, "catalogue": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
