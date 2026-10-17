"""Read-only comparison: historically pinned ATC 630 vs current vendor XUTUM.

The vendor index is independent evidence, NOT definitive regulatory proof that
a given share is currently listed. Never modify the user's pinned watchlist.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.market_data.adapters.borsapy_universe import (
    BorsapyBistUniverseProvider,
)
from scripts.atc_universe_seed import load_pinned


def compare_universes(pinned, observed):
    pinned_set = set(pinned)
    current_set = {m.symbol for m in observed}
    if not current_set:
        raise ValueError("Empty current XUTUM vendor list")
    return {
        "both": sorted(pinned_set & current_set),
        "pinned_not_in_xutum": sorted(pinned_set - current_set),
        "xutum_not_in_pinned": sorted(current_set - pinned_set),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pinned = load_pinned(Path("config/atc_630_symbols.txt"))
    observed = BorsapyBistUniverseProvider().list_members("BIST_ALL")
    diff = compare_universes(pinned, observed)
    result = {
        "timestamp_istanbul": datetime.now(ZoneInfo("Europe/Istanbul")).isoformat(),
        "source": "borsapy XUTUM vendor snapshot; independent verification required",
        "pinned_count": len(pinned),
        "vendor_xutum_count": len(observed),
        "both_count": len(diff["both"]),
        "pinned_not_in_xutum_count": len(diff["pinned_not_in_xutum"]),
        "xutum_not_in_pinned_count": len(diff["xutum_not_in_pinned"]),
        **diff,
    }
    (args.out / "atc_universe_drift.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    with (args.out / "atc_universe_drift.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(("Hisse", "ATC_630", "XUTUM_VeriSaglayici", "Karsilastirma"))
        for symbol in sorted(set(pinned) | {m.symbol for m in observed}):
            in_pinned, in_live = symbol in pinned, symbol in {m.symbol for m in observed}
            status = ("ORTAK" if in_pinned and in_live else
                      "SADECE_ATC_630" if in_pinned else "SADECE_XUTUM")
            writer.writerow((symbol, int(in_pinned), int(in_live), status))
    print(json.dumps({k: v for k, v in result.items() if not isinstance(v, list)},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
