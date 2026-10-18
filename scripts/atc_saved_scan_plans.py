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
from market_intelligence.scanning.signal.atc_native_packet import ATC_SCRIPT_SHA256
from market_intelligence.scanning.trade_plan import build_trade_plan


class PlanLevels(NamedTuple):
    entry: float | None
    stop: float | None
    tp1: float | None
    tp2: float | None
    tp3: float | None
    price_basis: str


def _positive_display_level(value):
    """Never present zero, negative, NaN or infinite values as stock prices."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) and number > 0 else None


def model_rejected_display_levels(plan, *, frame, direction):
    """Retain only mathematically positive fields of a rejected ORIGINAL plan.

    This object is DISPLAY-ONLY. The source plan stays 'unavailable', and
    the rejection reason must remain visible in the report metadata.
    """
    if direction not in ("bullish", "bearish") or frame.is_partial:
        return None
    if frame.price_basis.value not in ("raw", "split_adjusted"):
        return None
    if not isinstance(plan, dict) or plan.get("status") != "unavailable" or plan.get("reason") not in {
        "nonpositive_level", "invalid_stop_or_target",
    }:
        return None
    if (plan.get("snapshot_id") != frame.snapshot_id
            or plan.get("timeframe") != frame.timeframe.value
            or plan.get("bar_time") != frame.through_bar_time.isoformat()
            or plan.get("price_basis") != frame.price_basis.value):
        return None
    raw = plan.get("display_levels")
    if not isinstance(raw, dict):
        return None
    if raw.get("side") != ("long" if direction == "bullish" else "short"):
        return None
    vals = tuple(_positive_display_level(raw.get(name)) for name in (
        "entry", "stop", "tp1", "tp2", "tp3",
    ))
    # If the entry itself is invalid, no reliable reference price is shown.
    if vals[0] is None or all(value is not None for value in vals):
        return None
    entry, stop, *targets = vals
    sign = 1 if direction == "bullish" else -1
    if stop is not None and sign * (entry - stop) <= 0:
        return None
    previous = entry
    unavailable_target = False
    for target in targets:
        if target is None:
            unavailable_target = True
        elif unavailable_target or sign * (target - previous) <= 0:
            # Correct source formulas have a directional, ordered target
            # prefix. Do not salvage mismatched or corrupt stored plans.
            return None
        else:
            previous = target
    return PlanLevels(*vals, frame.price_basis.value)


def complete_reference_levels(plan, direction):
    """A full directional price family, rather than a display-only fragment."""
    if not isinstance(plan, PlanLevels) or direction not in ("bullish", "bearish"):
        return False
    if plan.price_basis not in ("raw", "split_adjusted"):
        return False
    levels = tuple(_positive_display_level(value) for value in plan[:5])
    if any(value is None for value in levels):
        return False
    entry, stop, tp1, tp2, tp3 = levels
    return (stop < entry < tp1 < tp2 < tp3 if direction == "bullish"
            else tp3 < tp2 < tp1 < entry < stop)


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
        # The latest Pine native packet supports A-I LONG *and* SHORT,
        # both using the original generic 7-bar ATR plan. Neither 17 nor 18
        # has a stand-alone plan; never borrow prices from another rule.
        if number >= 17:
            continue
        native = metrics.get("trade_plan") if isinstance(metrics, dict) else None
        # Fail closed on stale Oct-14 A-I plans even if their numeric fields
        # look plausible: reconstruct only the original evaluation snapshot.
        if number <= 9 and (
            not isinstance(native, dict)
            or native.get("source_sha256") != ATC_SCRIPT_SHA256
            or native.get("version") != "atc-native-dual-direction-v3"
        ):
            saved = None
        else:
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

    A-I and 10-16 both use the native alarm packet's swing7+ATR
    directional price family. This does NOT rewrite the distinct chart-overlay
    f_plan() source. 17/18 and non-directional return None.
    """
    if frame.is_partial or direction not in ("bullish", "bearish"):
        return None
    if scanner_id not in SCANNER_ORDER[:16]:
        return None
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


def load_saved_trade_plans(
    db, *, members, evaluations, matches, timeframe, bar_time,
    include_model_failures=False,
):
    """Load verified stored finding plans; repair absent plans from EXACT OHLCV.

    Every reconstructed level is independently derived from that same
    evaluation's canonical snapshot; missing snapshots remain blank. Returns
    plan-per-(ticker,scanner-code,direction), never inferred prices.
    """
    if not matches:
        return ({}, {}) if include_model_failures else {}
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
    model_failures = {}
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
            # 17/18 don't have independent risk plans; A-I SHORT is now valid.
            if number > 16:
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
                original_plan = build_trade_plan(frame, direction)
                reason = original_plan.get("reason", "unknown")
                if original_plan.get("status") == "reference":
                    reason = "reference_plan_failed_strict_validation"
                print(
                    f"ATC missing REQUIRED Stop/TP {tf}: "
                    f"{symbol} code={number} side={state} reason={reason}",
                    flush=True,
                )
                # This is a fully computed but NON-ACTIONABLE original model,
                # not absent OHLC. A 3R SHORT below zero, or LONG with a
                # negative original stop, cannot become a legal price order.
                # Flag it explicitly without altering Pine risk or inventing TP.
                if reason in {"nonpositive_level", "invalid_stop_or_target"}:
                    model_failures[key] = reason
                    # Show positive entry/stop/targets, but never present an
                    # impossible price or mark the overall plan as actionable.
                    partial = model_rejected_display_levels(
                        original_plan, frame=frame, direction=direction,
                    )
                    # Callers that did not request the rejection metadata
                    # must not mistake display-only fields for a valid plan.
                    if partial is not None and include_model_failures:
                        saved[key] = partial
    stats["persisted_valid"] = sum(
        value is not None for key, value in saved.items()
        if key not in model_failures
    ) - stats["reconstructed_exact_snapshot"]
    stats["match_rows"] = len(matches)
    stats["snapshots_read"] = len(cache)
    stats["model_math_rejected"] = len(model_failures)
    print(f"ATC same-snapshot STOP/TP provenance {timeframe}: {dict(stats)}", flush=True)
    return (saved, model_failures) if include_model_failures else saved

def fmt_level(value, *, csv=False) -> str:
    """Report price only when positive and finite; use ASCII '-' otherwise."""
    valid = _positive_display_level(value)
    if valid is None:
        return "-"
    formatted = f"{valid:.8f}" if csv else f"{valid:.4f}"
    result = formatted.rstrip("0").rstrip(".")
    # Tiny positive prices must not accidentally render as numeric zero.
    return result if result != "0" else f"{valid:.8g}"
