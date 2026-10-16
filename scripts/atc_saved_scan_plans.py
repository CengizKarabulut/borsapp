"""Extract only genuine scanner-persisted trade scenarios for Telegram.

Reference levels come from the SAME evaluation/finding as its directional
match. No OHLCV reconstruction, arbitrary ATR approximation, cross-symbol
merge or LONG/SHORT inference is allowed at publication time.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import isfinite
from typing import NamedTuple

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import parse_timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.display_codes import SCANNER_ORDER
from market_intelligence.scanning.trade_plan import build_pine_a_i_plan, build_trade_plan


class PlanLevels(NamedTuple):
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    price_basis: str


EVALUATION_PLANS_SQL = """
SELECT e.instrument_id::text, e.scanner_id, e.timeframe, e.bar_time,
       e.evaluation_id::text, f.direction, f.metrics, e.snapshot_id
FROM scan_evaluations e
JOIN scan_events f ON f.evaluation_id = e.evaluation_id
WHERE e.evaluation_id = ANY(%s::uuid[])
UNION ALL
SELECT e.instrument_id::text, e.scanner_id, e.timeframe, e.bar_time,
       e.evaluation_id::text, st.metrics->>'_atc_direction', st.metrics, e.snapshot_id
FROM scan_evaluations e
JOIN active_states st
  ON st.instrument_id = e.instrument_id
 AND st.scanner_id = e.scanner_id
 AND st.timeframe = e.timeframe
 AND st.producer_version = e.scanner_version
 AND st.ruleset_hash = e.ruleset_hash
 AND st.last_seen_at = e.bar_time
 AND st.status = 'active'
WHERE e.evaluation_id = ANY(%s::uuid[])
"""


def validate_reference_plan(metrics, *, direction: str, timeframe: str,
                            close: datetime, snapshot_id: str) -> PlanLevels | None:
    """Return only a single positive finite scenario with correct chronology."""
    if direction not in ("bullish", "bearish") or not isinstance(metrics, dict):
        return None
    plan = metrics.get("trade_plan")
    if not isinstance(plan, dict) or plan.get("status") != "reference":
        return None
    if plan.get("snapshot_id") != snapshot_id or plan.get("timeframe") != timeframe:
        return None
    try:
        stamped = datetime.fromisoformat(plan["bar_time"])
    except (ValueError, TypeError, KeyError):
        return None
    if stamped.tzinfo is None or stamped != close:
        return None
    basis = plan.get("price_basis")
    if basis not in ("raw", "split_adjusted"):
        return None
    scenarios = plan.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 1:
        return None
    candidate = scenarios[0]
    if not isinstance(candidate, dict):
        return None
    side = "long" if direction == "bullish" else "short"
    if candidate.get("side") != side:
        return None
    fields = ("entry", "stop", "tp1", "tp2", "tp3")
    values = []
    for key in fields:
        item = candidate.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        value = float(item)
        if not isfinite(value) or value <= 0:
            return None
        values.append(value)
    entry, stop, tp1, tp2, tp3 = values
    if side == "long" and not (stop < entry < tp1 < tp2 < tp3):
        return None
    if side == "short" and not (tp3 < tp2 < tp1 < entry < stop):
        return None
    return PlanLevels(entry, stop, tp1, tp2, tp3, basis)


def plan_from_stored_rows(rows, *, members, evaluations, matches, timeframe, bar_time):
    """A single validated event/state trade plan or a genuinely blank slot.

    Multiple distinct plans on the same scanner/direction are ambiguous and
    therefore suppressed. No aggregation or winner-picking across findings.
    """
    member_ids = {str(member.instrument_id): member.symbol for member in members}
    evaluation_ids = {
        str(e[8]): (str(e[0]), e[2])
        for e in evaluations if e[1] == timeframe and e[5] == bar_time and e[6] == "match"
    }
    targets = set(matches)
    collected = {}
    for row in rows:
        inst, scanner, tf, close, evaluation_id, direction, metrics, snapshot_id = row
        expected = evaluation_ids.get(str(evaluation_id))
        if expected != (str(inst), scanner) or tf != timeframe or close != bar_time:
            continue
        state = "POZITIF" if direction == "bullish" else "NEGATIF" if direction == "bearish" else ""
        ticker = member_ids.get(str(inst))
        if scanner not in SCANNER_ORDER or not ticker:
            continue
        number = SCANNER_ORDER.index(scanner) + 1
        key = ticker, number, state
        if key not in targets or not state:
            continue
        # The user's Pine model exposes standalone A-I bullish plans and
        # generic 10-16 directional plans. Rules 17/18 do not own a valid
        # standalone stop/target family and must never borrow an unrelated one.
        if number >= 17 or (number <= 9 and state != "POZITIF"):
            continue
        saved = validate_reference_plan(
            metrics, direction=direction, timeframe=timeframe, close=bar_time,
            snapshot_id=str(snapshot_id),
        )
        collected.setdefault(key, []).append(saved)
    result = {}
    for key in matches:
        candidates = collected.get(key, [])
        # An unavailable or conflicting candidate fails closed; never invent.
        result[key] = candidates[0] if candidates and all(
            candidate is not None and candidate == candidates[0] for candidate in candidates
        ) else None
    return result


SNAPSHOT_IDENTITIES_SQL = """
SELECT e.evaluation_id::text, e.instrument_id::text, e.scanner_id,
       e.snapshot_id, s.source, s.price_basis, s.series_revision,
       s.frame_start_time, s.through_bar_time, s.bar_count, e.timeframe, e.bar_time
FROM scan_evaluations e
JOIN data_snapshots s
  ON s.snapshot_id = e.snapshot_id
 AND s.instrument_id = e.instrument_id
 AND s.timeframe = e.timeframe
WHERE e.evaluation_id = ANY(%s::uuid[])
"""

EXACT_SNAPSHOT_BARS_SQL = """
SELECT open_time, close_time, open, high, low, close, volume
FROM canonical_market_bars
WHERE instrument_id = %s AND timeframe = %s
  AND source = %s AND price_basis = %s AND series_revision = %s
  AND open_time >= %s AND close_time <= %s
ORDER BY close_time ASC
"""


def reconstruct_pine_plan(frame: CanonicalFrame, scanner_id: str, direction: str):
    """Use only original confirmed OHLCV frame, never an unrelated market quote.

    A-I use the owner's f_plan; 10-16 use the original Python/Pine generic
    swing7+ATR directional formula. 17/18 and non-directional return None.
    """
    if frame.is_partial or direction not in ("bullish", "bearish"):
        return None
    if scanner_id not in SCANNER_ORDER[:16]:
        return None
    number = SCANNER_ORDER.index(scanner_id) + 1
    if number <= 9:
        if direction != "bullish":
            return None
        raw = build_pine_a_i_plan(frame, scanner_id, direction)
    else:
        raw = build_trade_plan(frame, direction)
    return validate_reference_plan(
        {"trade_plan": raw}, direction=direction,
        timeframe=frame.timeframe.value, close=frame.through_bar_time,
        snapshot_id=frame.snapshot_id,
    )


def _exact_frame_from_saved_bars(cursor, identity):
    """Reconstruct exactly one scanner snapshot from its persisted OHLCV.

    No source/revision/basis mixing. Never use tomorrow's or another snapshot's
    candles and never silently truncate the original calculation history.
    """
    (evaluation_id, instrument_id, scanner_id, snapshot_id, source, basis,
     revision, start, end, bar_count, timeframe, evaluated_close) = identity
    if end != evaluated_close or bar_count < 15 or bar_count > 3500:
        return None
    if basis not in ("raw", "split_adjusted"):
        return None
    cursor.execute(EXACT_SNAPSHOT_BARS_SQL, (
        instrument_id, timeframe, source, basis, revision, start, end,
    ))
    original = cursor.fetchall()
    if len(original) != bar_count or not original:
        return None
    if original[0][0] != start or original[-1][1] != end:
        return None
    bars = tuple(
        CanonicalBar(
            open_time=item[0], close_time=item[1], open=item[2],
            high=item[3], low=item[4], close=item[5], volume=item[6],
        ) for item in original
    )
    return CanonicalFrame(
        instrument_id=str(instrument_id), symbol_at_snapshot="SNAPSHOT",
        market="BIST", timeframe=parse_timeframe(timeframe),
        snapshot_id=str(snapshot_id), series_revision=int(revision),
        price_basis=PriceBasis(basis), source=source,
        bars=bars, is_partial=False,
    )


def load_saved_trade_plans(db, *, members, evaluations, matches, timeframe, bar_time):
    """Load verified stored finding plans; repair absent plans from EXACT OHLCV.

    Every reconstructed level is independently derived from that same
    evaluation's canonical snapshot; missing snapshots remain blank. Returns
    plan-per-(ticker,scanner-code,direction), never inferred prices.
    """
    if not matches:
        return {}
    ids = list({
        str(e[8]) for e in evaluations
        if e[1] == timeframe and e[5] == bar_time and e[6] == "match"
    })
    with db.cursor() as cursor:
        cursor.execute(EVALUATION_PLANS_SQL, (ids, ids))
        rows = cursor.fetchall()
        cursor.execute(SNAPSHOT_IDENTITIES_SQL, (ids,))
        identities = cursor.fetchall()
    saved = plan_from_stored_rows(
        rows, members=members, evaluations=evaluations,
        matches=matches, timeframe=timeframe, bar_time=bar_time,
    )
    member_symbols = {str(m.instrument_id): m.symbol for m in members}
    match_set = set(matches)
    valid_evaluations = {
        str(e[8]): (str(e[0]), e[2]) for e in evaluations
        if e[1] == timeframe and e[5] == bar_time and e[6] == "match"
    }
    stats = Counter()
    cache = {}
    for identity in identities:
        (eid, instrument, scanner, snapshot_id, source, basis, revision,
         start, end, count, tf, close) = identity
        if valid_evaluations.get(str(eid)) != (str(instrument), scanner):
            stats["mismatched_evaluation"] += 1
            continue
        if tf != timeframe or close != bar_time or scanner not in SCANNER_ORDER:
            stats["wrong_bar"] += 1
            continue
        symbol = member_symbols.get(str(instrument))
        if not symbol:
            continue
        number = SCANNER_ORDER.index(scanner) + 1
        for state, direction in (("POZITIF", "bullish"), ("NEGATIF", "bearish")):
            key = symbol, number, state
            if key not in match_set or saved.get(key) is not None:
                continue
            # Cache by complete data snapshot identity; scanner-specific plans
            # can reuse bars for the same exact saved series.
            identity_key = (str(snapshot_id), str(instrument), source, basis, revision)
            if identity_key not in cache:
                with db.cursor() as cursor:
                    try:
                        cache[identity_key] = _exact_frame_from_saved_bars(cursor, identity)
                    except (ValueError, TypeError):
                        cache[identity_key] = None
            frame = cache[identity_key]
            if frame is None:
                stats["missing_or_modified_snapshot"] += 1
                continue
            calculated = reconstruct_pine_plan(frame, scanner, direction)
            if calculated is not None:
                saved[key] = calculated
                stats["reconstructed_exact_snapshot"] += 1
            else:
                stats["unsupported_or_invalid_plan"] += 1
    stats["persisted_valid"] = sum(v is not None for v in saved.values()) - stats["reconstructed_exact_snapshot"]
    stats["match_rows"] = len(matches)
    stats["snapshots_read"] = len(cache)
    print(f"ATC same-snapshot STOP/TP provenance {timeframe}: {dict(stats)}", flush=True)
    return saved

def fmt_level(value, *, csv=False) -> str:
    if value is None:
        return "" if csv else "—"
    return f"{value:.8f}".rstrip("0").rstrip(".") if csv else f"{value:.4f}".rstrip("0").rstrip(".")
