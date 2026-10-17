"""One auditable row per pinned stock, including non-matches and data gaps.

Signal PNG pages stay match-only; this independent CSV accounts for every member
and every scanner supported on the same confirmed bar. Unknown direction is
never silently dropped or converted into a trade side.
"""
from __future__ import annotations

import csv
import io
from collections import Counter

from market_intelligence.core.timeframes import parse_timeframe
from market_intelligence.scanning.display_codes import (
    SCANNER_ORDER,
    direction_display,
    scanner_code,
)
from scripts.atc_export_dashboard import status_label

DIRECTIONAL = frozenset({
    "POZITIF", "NEGATIF", "NOTR", "KARMA", "ESLESME_YON_BELIRSIZ",
})


def universe_status_csv(members, evaluations, bindings, timeframe, bar_time):
    """Return UTF-8 BOM CSV and truthful coverage counters.

    Includes the 18 original code columns A-I / 10-18. Unsupported rules are
    explicit; missing/older/unknown/mismatched evaluations never become matches.
    """
    tf = parse_timeframe(timeframe)
    supported = {
        b.scanner.id: b for b in bindings if tf in b.shadow_timeframes
    }
    if not supported:
        raise ValueError(f"No supported scanner bindings for {timeframe}")
    ids = {str(m.instrument_id): m.symbol for m in members}
    if len(ids) != len(members) or len(set(ids.values())) != len(members):
        raise ValueError("Duplicate pinned instrument or ticker in universe")
    latest = {}
    for ev in evaluations:
        instrument, ev_tf, scanner = str(ev[0]), ev[1], ev[2]
        if instrument not in ids or ev_tf != timeframe or scanner not in supported:
            continue
        key = (instrument, scanner)
        if key in latest:
            raise ValueError(f"Duplicate latest scanner evaluation: {key}")
        latest[key] = ev

    data = io.StringIO()
    writer = csv.writer(data)
    codes = [scanner_code(i) for i in range(1, 19)]
    writer.writerow((
        "Hisse", "ZamanDilimi", "TeyitliMumTSI", "EslesmeSayisi",
        "EslesenKodlar", "DesteklenenTarama", "DogruDegerlendirilen",
        "EksikVeyaHatali", "HisseDurumu", *codes,
        *(f"{code}_Neden" for code in codes),
    ))
    totals = Counter()
    for instrument, ticker in sorted(ids.items(), key=lambda item: item[1]):
        statuses = []
        reasons = []
        hits = []
        good = 0
        problems = 0
        for index, scanner in enumerate(SCANNER_ORDER, 1):
            if scanner not in supported:
                statuses.append("DESTEKLENMIYOR")
                reasons.append("ZAMAN_DILIMI_DESTEKLENMIYOR")
                continue
            ev = latest.get((instrument, scanner))
            if ev is None:
                label = "VERI_YOK"
            elif ev[5] != bar_time:
                label = "ESKI_MUM"
            elif (ev[3] != supported[scanner].scanner.version
                  or ev[4] != supported[scanner].ruleset_hash):
                label = "SURUM_UYUSMAZLIGI"
            else:
                label = status_label(ev[6], ev[9] or ())
            if label in DIRECTIONAL:
                good += 1
                direction = direction_display(label)
                statuses.append(direction)
                hits.append(f"{scanner_code(index)}:{direction}")
                totals["match"] += 1
            elif label == "KOSUL_YOK":
                good += 1
                statuses.append("KOSUL_YOK")
            else:
                problems += 1
                statuses.append(label)
                totals[label] += 1
            if label in DIRECTIONAL or label == "KOSUL_YOK":
                reasons.append("")
            else:
                # e[7] is the persisted scanner error code. No free-form
                # exception details or provider secrets are copied into CSV.
                code = ev[7] if ev is not None else None
                reasons.append(str(code)[:96] if code else label)
        # A stock can have confirmed matches AND unknown scanner results.
        # Do not hide that match in an undifferentiated "error" bucket.
        if hits and problems:
            row_status = "ESLESME_VAR_VE_EKSIK"
        elif hits:
            row_status = "ESLESME_VAR"
        elif problems:
            row_status = "EKSIK_VEYA_HATALI"
        else:
            row_status = "KOSUL_YOK"
        writer.writerow((
            ticker, timeframe, bar_time.isoformat(), len(hits),
            " | ".join(hits), len(supported), good, problems, row_status,
            *statuses, *reasons,
        ))
        totals[row_status] += 1
        totals["matched_members"] += int(bool(hits))
        totals["matched_with_unresolved"] += int(bool(hits) and bool(problems))
        totals["unresolved_without_match"] += int(bool(problems) and not hits)
        totals["members"] += 1
        totals["unresolved_evaluations"] += problems
        totals["confirmed_evaluations"] += good

    if totals["members"] != len(members):
        raise RuntimeError("Universe CSV silently omitted a stock")
    totals["supported_scanners"] = len(supported)
    totals["expected_evaluations"] = len(members) * len(supported)
    if (totals["confirmed_evaluations"] + totals["unresolved_evaluations"]
            != totals["expected_evaluations"]):
        raise RuntimeError("Every supported scanner needs an explicit status")
    return ("\ufeff" + data.getvalue()).encode("utf-8"), dict(totals)
