"""Separate LONG/SHORT pages for latest-state results within ONE timeframe.

Metadata is deterministic and independent of fonts, image bytes and wall time.
The publisher can recompute it from the prepared report without rendering
again. Source eligibility/freshness is supplied by that report; publication
still owns the packet-age and destination checks. This module never sends.
"""
from __future__ import annotations

import io
import math
import re
import textwrap
from collections import Counter
from numbers import Real

from market_intelligence.core.timeframes import Timeframe, parse_timeframe
from market_intelligence.scanning.display_codes import SCANNER_ORDER, scanner_code

VERSION = "atc-same-timeframe-direction-pages-v1"
PAGE_SIZE = 20
DIRECTIONS = (("bullish", "LONG"), ("bearish", "SHORT"))
LABELS = {Timeframe.M15: "15 dk", Timeframe.M30: "30 dk", Timeframe.M45: "45 dk",
          Timeframe.H1: "1 saat", Timeframe.H2: "2 saat", Timeframe.H4: "4 saat",
          Timeframe.D1: "Günlük", Timeframe.W1: "Haftalık"}
SCANNER_IDENTITIES = {identity: (number, scanner_code(number))
    for number, identity in enumerate(SCANNER_ORDER, 1)}
HALT_STATES = frozenset({"halted", "official_halt", "trading_halted", "official_halt_last_real_source"})


def _halted(row, meta):
    for state in (row.get("market_event"), meta.get("market_event"),
                  row.get("market_status"), meta.get("market_status")):
        label = state.get("status") if isinstance(state, dict) else state
        if isinstance(label, str) and label.casefold() in HALT_STATES:
            return True
    label = meta.get("status")
    return isinstance(label, str) and label.casefold() in HALT_STATES


def _ineligible_reason(row):
    if row.get("status") != "available":
        return "source_unavailable"
    meta = row.get("metadata")
    if not isinstance(meta, dict):
        return "invalid_source_metadata"
    if _halted(row, meta):
        return "market_halt"
    if meta.get("usable_latest") is not True:
        return "latest_source_not_usable"
    if meta.get("eligible_for_current_signals") is False:
        return "ineligible_for_current_signals"
    price = row.get("close")
    if (isinstance(price, bool) or not isinstance(price, Real)
            or not math.isfinite(price) or price <= 0):
        return "invalid_source_price"
    return None


def _votes(row):
    votes = {direction: set() for direction, _ in DIRECTIONS}
    scans = row.get("evaluations", [])
    if not isinstance(scans, list):
        return votes
    for scan in scans:
        if not isinstance(scan, dict) or scan.get("status") != "match":
            continue
        identity = scan.get("scanner_id")
        if not isinstance(identity, str):
            continue
        expected = SCANNER_IDENTITIES.get(identity)
        if expected is None:
            continue
        number, code = expected
        # Never count an unknown code or relabel another scanner as this one.
        if (("number" in scan and (type(scan["number"]) is not int or scan["number"] != number))
                or scan.get("code", code) != code):
            continue
        findings = scan.get("findings", [])
        if not isinstance(findings, list):
            continue
        for finding in findings:
            direction = finding.get("direction") if isinstance(finding, dict) else None
            if isinstance(direction, str) and direction in votes:
                votes[direction].add(identity)
    return votes


def build_timeframe_metadata(report, *, minimum_scanners=1, max_stocks_per_direction=None):
    """Return verifiable JSON metadata for all matches or same-TF intersections.

    ``minimum_scanners=1`` groups normal results. ``2`` requires two DISTINCT
    same-direction scanner identities for that stock in this timeframe. Votes
    never cross timeframes, symbols or source snapshots. LONG and SHORT are
    independent evidence groups, so a stock can appear in both.

    ``max_stocks_per_direction=None`` paginates ALL stocks in groups of 20.
    ``20`` retains the first 20 in each direction and discloses omissions; the
    publisher's complete CSV remains the source for the unabridged results.
    """
    if type(minimum_scanners) is not int or minimum_scanners not in (1, 2):
        raise ValueError("minimum_scanners_must_be_1_or_2")
    if max_stocks_per_direction is not None and (
            type(max_stocks_per_direction) is not int or max_stocks_per_direction != 20):
        raise ValueError("direction_limit_must_be_none_or_20")
    if not isinstance(report, dict) or not isinstance(report.get("rows"), list):
        raise ValueError("timeframe_report_rows_required")
    target = parse_timeframe(report.get("timeframe", ""))
    if target not in LABELS:
        raise ValueError("unsupported_direction_page_timeframe")
    mode = "all_direction_matches" if minimum_scanners == 1 else "same_timeframe_intersections"
    prefix = "tf" if minimum_scanners == 1 else "same-tf"
    grouped = {direction: [] for direction, _ in DIRECTIONS}
    excluded = Counter()
    seen = {}
    eligible = 0
    duplicate_rows = 0
    for row in report["rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("symbol"), str):
            raise ValueError("invalid_direction_page_symbol_row")
        symbol = row["symbol"].strip().upper()
        if not re.fullmatch(r"[A-Z0-9.]{1,16}", symbol):
            raise ValueError("invalid_direction_page_symbol")
        if symbol in seen:
            if row != seen[symbol]:
                raise ValueError("conflicting_duplicate_symbol_rows")
            duplicate_rows += 1
            continue
        seen[symbol] = row
        reason = _ineligible_reason(row)
        if reason:
            excluded[reason] += 1
            continue
        eligible += 1
        votes = _votes(row)
        for direction, _label in DIRECTIONS:
            identities = sorted(votes[direction], key=lambda key: SCANNER_IDENTITIES[key][0])
            if len(identities) < minimum_scanners:
                continue
            opposite = "bearish" if direction == "bullish" else "bullish"
            grouped[direction].append({"symbol": symbol, "close": float(row["close"]),
                "scanner_count": len(identities), "scanner_ids": identities,
                "scanner_codes": [SCANNER_IDENTITIES[key][1] for key in identities],
                "has_opposite_direction_matches": bool(votes[opposite])})
    metadata = {"version": VERSION, "mode": mode, "timeframe": target.value,
        "timeframe_label": LABELS[target], "minimum_scanners": minimum_scanners,
        "max_stocks_per_direction": max_stocks_per_direction, "page_size": PAGE_SIZE,
        "criteria": {"distinct_same_direction_scanners_per_stock": minimum_scanners,
                     "same_timeframe_only": True, "different_timeframes_required": False,
                     "directions_are_independent": True},
        "selection_order": "distinct_scanner_count_desc_then_symbol_ascending",
        "source_stock_count": len(seen), "eligible_stock_count": eligible,
        "duplicate_identical_rows_ignored": duplicate_rows,
        "excluded_counts": dict(sorted(excluded.items())),
        "observation_start": report.get("observation_start"), "observation_end": report.get("observation_end"),
        "stop_tp_plans_mixed": False, "directions": {}}
    for direction, label in DIRECTIONS:
        ordered = sorted(grouped[direction], key=lambda item: (-item["scanner_count"], item["symbol"]))
        total = len(ordered)
        shown = ordered if max_stocks_per_direction is None else ordered[:max_stocks_per_direction]
        page_count = (len(shown) + PAGE_SIZE - 1) // PAGE_SIZE
        method = ("Aynı dilimde en az 2 farklı tarama" if minimum_scanners == 2 else "Tarama eşleşmeleri")
        pages = []
        for offset in range(0, len(shown), PAGE_SIZE):
            stocks = shown[offset:offset + PAGE_SIZE]
            index = offset // PAGE_SIZE + 1
            pages.append({"filename": f"{prefix}-{target.value}-{label}-{index:03}.png",
                "index": index, "page_count": page_count, "stock_count": len(stocks),
                "symbols": [stock["symbol"] for stock in stocks], "stocks": stocks})
        metadata["directions"][direction] = {"label": label, "display_title": f"{LABELS[target]} {label} · {method}",
            "total_stock_count": total, "stock_count": len(shown), "omitted_stock_count": total - len(shown),
            "page_count": page_count, "pages": pages}
    return metadata


def _price(value):
    return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _render_page(metadata, group, page):
    from PIL import Image, ImageDraw

    from scripts.atc_timeframe_visuals import _font

    wrapped = [textwrap.wrap(", ".join(stock["scanner_codes"]), width=76, break_long_words=False) or [""]
               for stock in page["stocks"]]
    heights = [max(72, 26 * len(lines) + 28) for lines in wrapped]
    image = Image.new("RGB", (1840, 350 + sum(heights)), "#F1F5F9")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1840, 130), fill="#112E4A")
    draw.text((32, 25), group["display_title"], font=_font(30, bold=True), fill="white")
    observed = metadata.get("observation_end") or "Kaynak rapordaki son gözlem"
    draw.text((32, 81), f"CANLI / TEYİTSİZ · Gözlem: {observed}", font=_font(19), fill="white")
    shown, total = group["stock_count"], group["total_stock_count"]
    caption = f"{shown}/{total} hisse · Sayfa {page['index']}/{page['page_count']} · Bu sayfada {page['stock_count']} hisse"
    if group["omitted_stock_count"]:
        caption += f" · {group['omitted_stock_count']} diğer hisse CSV'de"
    draw.text((32, 159), caption, font=_font(22), fill="#112E4A")
    for x, title in ((32, "HİSSE"), (280, "SON FİYAT"), (520, "TARAMA SAYISI"), (780, "TARAMA KODLARI")):
        draw.text((x, 207), title, font=_font(20, bold=True), fill="#52697F")
    y = 246
    for index, (stock, lines, height) in enumerate(zip(page["stocks"], wrapped, heights, strict=True)):
        draw.rectangle((20, y, 1820, y + height - 2), fill="white" if index % 2 == 0 else "#E5EDF5")
        draw.text((32, y + 18), stock["symbol"], font=_font(23, bold=True), fill="#112E4A")
        draw.text((280, y + 18), _price(stock["close"]), font=_font(22), fill="#112E4A")
        draw.text((520, y + 18), str(stock["scanner_count"]), font=_font(22), fill="#112E4A")
        draw.multiline_text((780, y + 16), "\n".join(lines), font=_font(20), fill="#112E4A", spacing=5)
        y += height
    draw.text((32, image.height - 84), "Stop/TP her taramanın kendi kaydındadır; burada seviyeler birleştirilmez.",
              font=_font(20), fill="#52697F")
    draw.text((32, image.height - 48), "Bir hisse iki yönde de bulunabilir · CSV'de tüm sonuçlar · Emir değildir.",
              font=_font(19), fill="#52697F")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_timeframe_pages(report, *, minimum_scanners=1, max_stocks_per_direction=None):
    """Return (metadata, {ASCII filename: PNG bytes}); add no hashes or side effects."""
    metadata = build_timeframe_metadata(report, minimum_scanners=minimum_scanners,
        max_stocks_per_direction=max_stocks_per_direction)
    images = {page["filename"]: _render_page(metadata, group, page)
              for group in metadata["directions"].values() for page in group["pages"]}
    return metadata, images
