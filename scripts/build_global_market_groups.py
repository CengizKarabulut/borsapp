#!/usr/bin/env python3
"""Build bounded, display-only market groups from a captured TradingView catalogue.

The catalogue is an input, never a guessed list. Each active page requests at most
ten qualified symbols in four timeframes (40 unique request contexts). Larger
catalogues are split into bounded source files; the manifest preserves the full
ordered universe and the global group numbers across parts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
GLOBAL_SOURCE = ROOT / "pine" / "ATC_GLOBAL_18_COKLU_ZAMAN.pine"
TEMPLATE = Path(__file__).with_name("pine_templates") / "global_market_groups_display.pine"
GROUP_SIZE = 10
TIMEFRAMES = ("60", "240", "D", "W")
MAX_SYMBOLS_PER_PART = 1000
LIMITS_URL = "https://www.tradingview.com/pine-script-docs/writing/limitations/"
APPROVED_SOURCES = frozenset({
    "tradingview-screener", "tradingview-symbol-pages", "tradingview-components",
})
SYMBOL = re.compile(r"[A-Z0-9_]+:[A-Z0-9_./!^\-]+\Z")
IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,39}\Z")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(value: Any, label: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be a non-empty string of at most {maximum} characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} contains control characters")
    return value.strip()


def validate_catalogue(value: Any) -> dict[str, Any]:
    """Require inspectable scope/provenance and one record per qualified symbol."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Catalogue schema_version must be 1")
    universe_id = _text(value.get("universe_id"), "universe_id", 40)
    if not IDENTIFIER.fullmatch(universe_id):
        raise ValueError("universe_id must contain lowercase ASCII letters/digits/hyphens")
    title = _text(value.get("title"), "title", 100)
    provenance = value.get("catalogue")
    if not isinstance(provenance, dict):
        raise ValueError("catalogue provenance is required")
    source = _text(provenance.get("source"), "catalogue.source", 80)
    if source not in APPROVED_SOURCES:
        raise ValueError("Only captured TradingView screeners, symbol pages or components are accepted")
    url = _text(provenance.get("url"), "catalogue.url", 1000)
    parsed_url = urlparse(url)
    host = (parsed_url.hostname or "").lower()
    if parsed_url.scheme != "https" or not (
        host == "tradingview.com" or host.endswith(".tradingview.com")
    ) or parsed_url.username or parsed_url.password:
        raise ValueError("catalogue.url must be a public HTTPS TradingView source URL")
    captured_at = _text(provenance.get("captured_at"), "catalogue.captured_at", 60)
    try:
        stamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("catalogue.captured_at must be an ISO-8601 timestamp") from error
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("catalogue.captured_at must include its timezone")
    scope = _text(provenance.get("scope"), "catalogue.scope", 1000)
    coverage = provenance.get("coverage")
    if coverage not in ("complete", "partial"):
        raise ValueError("catalogue.coverage must explicitly be complete or partial")
    symbols = value.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("symbols must be a non-empty list")
    if type(provenance.get("row_count")) is not int or provenance["row_count"] != len(symbols):
        raise ValueError("catalogue.row_count must equal the captured, deduplicated record count")
    normalized = []
    seen = set()
    for index, record in enumerate(symbols):
        if not isinstance(record, dict):
            raise ValueError(f"symbols[{index}] must contain symbol and name")
        symbol = _text(record.get("symbol"), f"symbols[{index}].symbol", 120)
        if not SYMBOL.fullmatch(symbol):
            raise ValueError(f"Invalid fully qualified TradingView symbol: {symbol!r}")
        if symbol in seen:
            raise ValueError(f"Duplicate qualified symbol: {symbol}")
        seen.add(symbol)
        name = _text(record.get("name"), f"symbols[{index}].name", 250)
        normalized.append({"symbol": symbol, "name": name})
    return {
        "schema_version": 1,
        "universe_id": universe_id,
        "title": title,
        "catalogue": {
            "source": source, "url": url, "captured_at": captured_at,
            "scope": scope, "coverage": coverage, "row_count": len(normalized),
        },
        "symbols": normalized,
    }


def extract_core(source: str) -> str:
    """Use the checked-in GLOBAL formulas; append only requested-context metadata."""
    start = source.index("f_global_bist_reference() =>")
    end = source.index("// Request calls execute on all chart bars", start)
    core = source[start:end].rstrip()
    metadata_marker = "\nf_mtf_bit(int mask, int id) =>"
    if core.count(metadata_marker) != 1 or core.count("result := AtcMtfFrame.new(") != 1:
        raise ValueError("GLOBAL source integration boundaries changed; review the generator")
    metadata = ("    float sourceTick\n    string sourceZone\n"
                "    string sourceCurrency\n    string sourceVolumeKind\n")
    core = core.replace(metadata_marker, metadata + metadata_marker, 1)
    constructor = re.search(r"(?m)^        result := AtcMtfFrame\.new\(([^\n]+)\)$", core)
    if constructor is None:
        raise ValueError("GLOBAL snapshot constructor must remain a reviewed scalar UDT")
    original = constructor.group(0)
    replacement = original[:-1] + ", syminfo.mintick, syminfo.timezone, syminfo.currency, syminfo.volumetype)"
    return core.replace(original, replacement, 1)


def _pine(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_part(catalogue: dict[str, Any], records: list[dict[str, str]], *,
                source: str, part_index: int, part_count: int,
                global_group_start: int) -> str:
    stamp = datetime.fromisoformat(catalogue["catalogue"]["captured_at"].replace("Z", "+00:00"))
    date_tag = stamp.strftime("%Y%m%d")
    group_count = math.ceil(len(records) / GROUP_SIZE)
    part_label = f" · {part_index}/{part_count}" if part_count > 1 else ""
    title = f"ATC {catalogue['title']} GRUP 18{part_label} · {date_tag}"
    tokens = {
        "TITLE": _pine(title),
        "CATALOGUE_ID": _pine(catalogue["universe_id"]),
        "CATALOGUE_SCOPE": _pine(catalogue["catalogue"]["scope"]),
        "CAPTURED_AT": _pine(catalogue["catalogue"]["captured_at"]),
        "COVERAGE_LABEL": _pine("TAM KATALOG" if catalogue["catalogue"]["coverage"] == "complete"
                                else "KISMİ KATALOG"),
        "CATALOGUE_URL": catalogue["catalogue"]["url"],
        "CORE": extract_core(source),
        "GROUP_COUNT": str(group_count),
        "GLOBAL_GROUP_START": str(global_group_start),
        "TOTAL_GROUP_COUNT": str(math.ceil(len(catalogue["symbols"]) / GROUP_SIZE)),
        "TOTAL_SYMBOL_COUNT": str(len(catalogue["symbols"])),
        "SYMBOLS": ",\n    ".join(_pine(record["symbol"]) for record in records),
        "NAMES": ",\n    ".join(_pine(record["name"]) for record in records),
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    expected = set(re.findall(r"@@([A-Z_]+)@@", template))
    if expected != set(tokens):
        raise ValueError(f"Unexpected template placeholders: {expected ^ set(tokens)}")
    # Substitute in one pass: captured names cannot introduce a second expansion.
    return re.sub(r"@@([A-Z_]+)@@", lambda match: tokens[match[1]], template)


def build_artifacts(raw_catalogue: Any, source: str, *,
                    max_symbols_per_part: int = MAX_SYMBOLS_PER_PART) -> dict[str, bytes]:
    if type(max_symbols_per_part) is not int or not (
        GROUP_SIZE <= max_symbols_per_part <= MAX_SYMBOLS_PER_PART
        and max_symbols_per_part % GROUP_SIZE == 0
    ):
        raise ValueError("Part size must be a multiple of 10 between 10 and 1000")
    catalogue = validate_catalogue(raw_catalogue)
    records = catalogue["symbols"]
    chunks = [records[start:start + max_symbols_per_part]
              for start in range(0, len(records), max_symbols_per_part)]
    result: dict[str, bytes] = {}
    parts = []
    group_start = 1
    for index, chunk in enumerate(chunks, 1):
        stem = catalogue["universe_id"].replace("-", "_").upper()
        name = f"ATC_{stem}_GRUP_18_{index:02d}.pine"
        content = render_part(catalogue, chunk, source=source, part_index=index,
                              part_count=len(chunks), global_group_start=group_start).encode("utf-8")
        count = math.ceil(len(chunk) / GROUP_SIZE)
        result[name] = content
        parts.append({
            "file": name, "sha256": sha256(content), "symbol_count": len(chunk),
            "group_count": count, "global_group_first": group_start,
            "global_group_last": group_start + count - 1,
            "symbols": [record["symbol"] for record in chunk],
        })
        group_start += count
    canonical = json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n"
    result["catalogue.json"] = canonical.encode("utf-8")
    manifest = {
        "schema_version": 1, "universe_id": catalogue["universe_id"],
        "catalogue": catalogue["catalogue"], "catalogue_sha256": sha256(result["catalogue.json"]),
        "global_source": "pine/ATC_GLOBAL_18_COKLU_ZAMAN.pine",
        "global_source_sha256": sha256(source.encode("utf-8")),
        "numeric_core_policy": "GLOBAL core unchanged; scalar symbol metadata appended to UDT",
        "source_symbol_metadata": ["mintick", "timezone", "currency", "volumetype"],
        "symbol_count": len(records), "group_size": GROUP_SIZE,
        "group_count": math.ceil(len(records) / GROUP_SIZE),
        "timeframes": list(TIMEFRAMES), "maximum_unique_requests": GROUP_SIZE * len(TIMEFRAMES),
        "limit_source": LIMITS_URL, "display_only": True,
        "alerts_created": False, "calibrated_profiles": False,
        "runtime_validation": "pending_tradingview_compile_and_feed_check",
        "parts": parts,
    }
    result["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path, help="Qualified, provenance-backed TradingView catalogue JSON")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", type=Path, default=GLOBAL_SOURCE)
    parser.add_argument("--max-symbols-per-part", type=int, default=MAX_SYMBOLS_PER_PART)
    parser.add_argument("--check", action="store_true", help="Verify generated bytes without changing files")
    args = parser.parse_args()
    try:
        catalogue = json.loads(args.catalogue.read_text(encoding="utf-8-sig"))
        source = args.source.read_text(encoding="utf-8")
        files = build_artifacts(catalogue, source, max_symbols_per_part=args.max_symbols_per_part)
        if args.check:
            different = [name for name, data in files.items()
                         if not (args.output / name).is_file() or (args.output / name).read_bytes() != data]
            if different:
                parser.exit(1, "Generated package differs: " + ", ".join(different) + "\n")
        else:
            args.output.mkdir(parents=True, exist_ok=True)
            for name, data in files.items():
                (args.output / name).write_bytes(data)
        manifest = json.loads(files["manifest.json"])
        print(f"{manifest['symbol_count']} symbols; {manifest['group_count']} groups; "
              f"{len(manifest['parts'])} Pine part(s); display only; runtime validation pending")
    except (ValueError, OSError) as error:
        parser.exit(2, f"Catalogue generation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
