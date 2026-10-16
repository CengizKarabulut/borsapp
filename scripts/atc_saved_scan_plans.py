"""Extract only genuine scanner-persisted trade scenarios for Telegram.

Reference levels come from the SAME evaluation/finding as its directional
match. No OHLCV reconstruction, arbitrary ATR approximation, cross-symbol
merge or LONG/SHORT inference is allowed at publication time.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import NamedTuple

from market_intelligence.scanning.display_codes import SCANNER_ORDER


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
        key = ticker, SCANNER_ORDER.index(scanner) + 1, state
        if key not in targets or not state:
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


def load_saved_trade_plans(db, *, members, evaluations, matches, timeframe, bar_time):
    if not matches:
        return {}
    ids = list({
        str(e[8]) for e in evaluations
        if e[1] == timeframe and e[5] == bar_time and e[6] == "match"
    })
    with db.cursor() as cursor:
        cursor.execute(EVALUATION_PLANS_SQL, (ids, ids))
        rows = cursor.fetchall()
    return plan_from_stored_rows(
        rows, members=members, evaluations=evaluations,
        matches=matches, timeframe=timeframe, bar_time=bar_time,
    )


def fmt_level(value, *, csv=False) -> str:
    if value is None:
        return "" if csv else "—"
    return f"{value:.8f}".rstrip("0").rstrip(".") if csv else f"{value:.4f}".rstrip("0").rstrip(".")
