"""Point-in-time MAJOR / SWING / MINOR structure hierarchy.

The analytical rules are adapted from the user's Structure-First Channel Engine:
structure is classified before diagonal lines are selected; direction uses the
same-degree HH/HL/LH/LL sequence; the dominant rail comes from structural lows
in an uptrend or structural highs in a downtrend; the counter rail is parallel;
and only confirmed rails are eligible for confluence/alerts.

This module deliberately omits TradingView drawing code. It exposes auditable
geometry and evidence that the research/chart layers may render as they choose.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DegreeConfig:
    name: str
    left: int
    right: int
    min_span: int


DEGREES = (
    DegreeConfig("MAJOR", 10, 6, 24),
    DegreeConfig("SWING", 6, 4, 14),
    DegreeConfig("MINOR", 3, 2, 7),
)


@dataclass(frozen=True)
class Rail:
    side: str
    status: str
    anchor1_pos: int
    anchor2_pos: int
    anchor1_price: float
    anchor2_price: float
    slope_per_bar: float
    touches: int
    post_anchor_reactions: int
    containment: float
    body_violation_ratio: float
    score: float
    counter_offset: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _atr(frame: pd.DataFrame) -> pd.Series:
    if "ATR" in frame.columns:
        existing = pd.to_numeric(frame["ATR"], errors="coerce")
        if existing.notna().sum() >= max(10, len(frame) // 3):
            return existing.ffill().bfill()
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    previous = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    return tr.rolling(14, min_periods=3).mean().bfill()


def _confirmed_pivots(frame: pd.DataFrame, config: DegreeConfig) -> list[dict[str, Any]]:
    """Return pivots only after their right-side confirmation bars exist."""
    highs = pd.to_numeric(frame["High"], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(frame["Low"], errors="coerce").to_numpy(dtype=float)
    atr = _atr(frame).to_numpy(dtype=float)
    pivots: list[dict[str, Any]] = []
    for pos in range(config.left, len(frame) - config.right):
        start = pos - config.left
        end = pos + config.right + 1
        high = highs[pos]
        low = lows[pos]
        if not (math.isfinite(high) and math.isfinite(low)):
            continue
        is_high = high >= np.nanmax(highs[start:end])
        is_low = low <= np.nanmin(lows[start:end])
        confirmed_pos = pos + config.right
        atr_value = atr[pos] if math.isfinite(atr[pos]) else np.nan
        if is_high:
            pivots.append(
                {
                    "type": "high",
                    "price": float(high),
                    "pos": pos,
                    "at": str(frame.index[pos]),
                    "confirmed_pos": confirmed_pos,
                    "confirmed_at": str(frame.index[confirmed_pos]),
                    "atr": float(atr_value) if math.isfinite(atr_value) else None,
                }
            )
        if is_low:
            pivots.append(
                {
                    "type": "low",
                    "price": float(low),
                    "pos": pos,
                    "at": str(frame.index[pos]),
                    "confirmed_pos": confirmed_pos,
                    "confirmed_at": str(frame.index[confirmed_pos]),
                    "atr": float(atr_value) if math.isfinite(atr_value) else None,
                }
            )
    pivots.sort(key=lambda item: (item["pos"], 0 if item["type"] == "low" else 1))
    return _label_sequence(pivots)


def _label_sequence(pivots: list[dict[str, Any]], tolerance_atr: float = 0.15) -> list[dict[str, Any]]:
    previous: dict[str, dict[str, Any]] = {}
    labelled: list[dict[str, Any]] = []
    for raw in pivots:
        item = dict(raw)
        prior = previous.get(item["type"])
        if prior is None:
            label = "H" if item["type"] == "high" else "L"
        else:
            atr_value = _finite(item.get("atr")) or _finite(prior.get("atr")) or 0.0
            tolerance = max(abs(float(item["price"])) * 0.001, atr_value * tolerance_atr)
            delta = float(item["price"]) - float(prior["price"])
            if item["type"] == "high":
                label = "HH" if delta > tolerance else "LH" if delta < -tolerance else "EH"
            else:
                label = "HL" if delta > tolerance else "LL" if delta < -tolerance else "EL"
        item["label"] = label
        labelled.append(item)
        previous[item["type"]] = item
    return labelled


def _sequence_evidence(pivots: list[dict[str, Any]]) -> dict[str, Any]:
    highs = [item for item in pivots if item["type"] == "high" and item["label"] != "H"]
    lows = [item for item in pivots if item["type"] == "low" and item["label"] != "L"]
    recent_highs = highs[-6:]
    recent_lows = lows[-6:]
    high_label = recent_highs[-1]["label"] if recent_highs else "—"
    low_label = recent_lows[-1]["label"] if recent_lows else "—"

    def weighted_count(items: list[dict[str, Any]], wanted: set[str]) -> float:
        total = 0.0
        for index, item in enumerate(items, start=1):
            if item["label"] in wanted:
                total += 0.5 + 0.5 * index / max(len(items), 1)
        return total

    up_score = weighted_count(recent_highs, {"HH", "EH"}) + weighted_count(recent_lows, {"HL"})
    down_score = weighted_count(recent_highs, {"LH"}) + weighted_count(recent_lows, {"LL", "EL"})

    if high_label == "HH" and low_label == "HL":
        state = "UP"
    elif high_label == "LH" and low_label == "LL":
        state = "DOWN"
    elif high_label == "LH" and low_label == "HL":
        state = "CONTRACTION"
    elif high_label == "HH" and low_label == "LL":
        state = "EXPANSION"
    elif high_label == "EH" and low_label == "HL":
        state = "ASCENDING_TRIANGLE"
    elif high_label == "LH" and low_label == "EL":
        state = "DESCENDING_TRIANGLE"
    elif up_score >= down_score + 1.5 and up_score >= 2.0:
        state = "UP"
    elif down_score >= up_score + 1.5 and down_score >= 2.0:
        state = "DOWN"
    elif recent_highs and recent_lows:
        state = "RANGE"
    else:
        state = "INSUFFICIENT"

    evidence_total = up_score + down_score
    directional = abs(up_score - down_score)
    confidence = 0.0 if evidence_total == 0 else min(1.0, 0.45 + 0.55 * directional / evidence_total)
    if state in {"CONTRACTION", "EXPANSION", "ASCENDING_TRIANGLE", "DESCENDING_TRIANGLE"}:
        confidence = max(confidence, 0.65)
    return {
        "state": state,
        "latest_high_label": high_label,
        "latest_low_label": low_label,
        "up_evidence": round(up_score, 2),
        "down_evidence": round(down_score, 2),
        "confidence": round(confidence, 2),
    }


def _line_value(anchor1: dict[str, Any], anchor2: dict[str, Any], pos: int) -> float:
    span = int(anchor2["pos"]) - int(anchor1["pos"])
    if span <= 0:
        return float(anchor2["price"])
    slope = (float(anchor2["price"]) - float(anchor1["price"])) / span
    return float(anchor1["price"]) + slope * (pos - int(anchor1["pos"]))


def _reaction(frame: pd.DataFrame, pivot: dict[str, Any], side: str, atr_value: float, bars: int = 5) -> bool:
    start = int(pivot["pos"]) + 1
    forward = frame.iloc[start : start + bars]
    if forward.empty or atr_value <= 0:
        return False
    price = float(pivot["price"])
    if side == "support":
        return float(pd.to_numeric(forward["High"], errors="coerce").max()) - price >= 0.75 * atr_value
    return price - float(pd.to_numeric(forward["Low"], errors="coerce").min()) >= 0.75 * atr_value


def _evaluate_pair(
    frame: pd.DataFrame,
    same_side: list[dict[str, Any]],
    opposite: list[dict[str, Any]],
    first: dict[str, Any],
    second: dict[str, Any],
    side: str,
) -> Rail | None:
    span = int(second["pos"]) - int(first["pos"])
    if span <= 0:
        return None
    slope = (float(second["price"]) - float(first["price"])) / span
    if side == "support" and slope <= 0:
        return None
    if side == "resistance" and slope >= 0:
        return None

    atr_series = _atr(frame)
    start = int(first["pos"])
    positions = range(start, len(frame))
    body_low = frame[["Open", "Close"]].min(axis=1).astype(float)
    body_high = frame[["Open", "Close"]].max(axis=1).astype(float)
    valid = 0
    contained = 0
    violations = 0
    for pos in positions:
        atr_value = _finite(atr_series.iloc[pos]) or 0.0
        line = _line_value(first, second, pos)
        tolerance = max(abs(line) * 0.002, atr_value * 0.28)
        hard = max(abs(line) * 0.003, atr_value * 0.45)
        if side == "support":
            distance = float(body_low.iloc[pos]) - line
            contained += int(distance >= -tolerance)
            violations += int(distance < -hard)
        else:
            distance = line - float(body_high.iloc[pos])
            contained += int(distance >= -tolerance)
            violations += int(distance < -hard)
        valid += 1
    containment = contained / valid if valid else 0.0
    violation_ratio = violations / valid if valid else 1.0

    touches = 0
    post_reactions = 0
    for pivot in same_side:
        if int(pivot["pos"]) < start:
            continue
        atr_value = _finite(pivot.get("atr")) or _finite(atr_series.iloc[int(pivot["pos"])]) or 0.0
        line = _line_value(first, second, int(pivot["pos"]))
        tolerance = max(abs(line) * 0.003, atr_value * 0.38)
        if abs(float(pivot["price"]) - line) <= tolerance:
            touches += 1
            if int(pivot["pos"]) > int(second["pos"]) and _reaction(frame, pivot, side, atr_value):
                post_reactions += 1

    anchor_reactions = sum(
        _reaction(frame, pivot, side, _finite(pivot.get("atr")) or 0.0)
        for pivot in (first, second)
    )
    recency = max(0.0, 1.0 - (len(frame) - 1 - int(second["pos"])) / 220.0)
    score = (
        containment * 45.0
        + min(touches, 4) * 8.0
        + anchor_reactions * 7.0
        + min(post_reactions, 2) * 12.0
        + recency * 9.0
        - violation_ratio * 60.0
    )

    status = "REJECTED"
    if containment >= 0.58 and violation_ratio <= 0.16 and score >= 48:
        status = "CANDIDATE"
    if containment >= 0.72 and violation_ratio <= 0.08 and touches >= 3 and post_reactions >= 1:
        status = "CONFIRMED"

    offsets: list[float] = []
    for pivot in opposite:
        if int(pivot["pos"]) < start:
            continue
        base = _line_value(first, second, int(pivot["pos"]))
        offset = float(pivot["price"]) - base
        if (side == "support" and offset > 0) or (side == "resistance" and offset < 0):
            offsets.append(offset)
    counter_offset = float(np.median(offsets)) if offsets else None
    return Rail(
        side=side,
        status=status,
        anchor1_pos=int(first["pos"]),
        anchor2_pos=int(second["pos"]),
        anchor1_price=round(float(first["price"]), 6),
        anchor2_price=round(float(second["price"]), 6),
        slope_per_bar=round(slope, 8),
        touches=touches,
        post_anchor_reactions=post_reactions,
        containment=round(containment, 3),
        body_violation_ratio=round(violation_ratio, 3),
        score=round(float(score), 1),
        counter_offset=None if counter_offset is None else round(counter_offset, 6),
    )


def _best_rail(frame: pd.DataFrame, pivots: list[dict[str, Any]], state: str, config: DegreeConfig) -> Rail | None:
    if state not in {"UP", "DOWN"}:
        return None
    side_type = "low" if state == "UP" else "high"
    side = "support" if state == "UP" else "resistance"
    same = [item for item in pivots if item["type"] == side_type]
    opposite = [item for item in pivots if item["type"] != side_type]
    candidates: list[Rail] = []
    for first_index in range(max(0, len(same) - 10), len(same) - 1):
        for second_index in range(first_index + 1, len(same)):
            first, second = same[first_index], same[second_index]
            if int(second["pos"]) - int(first["pos"]) < config.min_span:
                continue
            rail = _evaluate_pair(frame, same, opposite, first, second, side)
            if rail and rail.status != "REJECTED":
                candidates.append(rail)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.status == "CONFIRMED", item.score, item.anchor2_pos))


def _compression(frame: pd.DataFrame, pivots: list[dict[str, Any]]) -> dict[str, Any] | None:
    highs = [item for item in pivots if item["type"] == "high"][-4:]
    lows = [item for item in pivots if item["type"] == "low"][-4:]
    if len(highs) < 2 or len(lows) < 2:
        return None
    high_a, high_b = highs[-2:]
    low_a, low_b = lows[-2:]
    high_span = int(high_b["pos"]) - int(high_a["pos"])
    low_span = int(low_b["pos"]) - int(low_a["pos"])
    if high_span <= 0 or low_span <= 0:
        return None
    upper_slope = (float(high_b["price"]) - float(high_a["price"])) / high_span
    lower_slope = (float(low_b["price"]) - float(low_a["price"])) / low_span
    if upper_slope >= 0 or lower_slope <= 0:
        return None
    now = len(frame) - 1
    upper_now = _line_value(high_a, high_b, now)
    lower_now = _line_value(low_a, low_b, now)
    width = upper_now - lower_now
    return {
        "status": "COMPRESSION" if width > 0 else "APEX_PASSED",
        "upper_slope": round(upper_slope, 8),
        "lower_slope": round(lower_slope, 8),
        "current_width": round(width, 6),
        "confirmed": width > 0,
    }


def analyze_degree(frame: pd.DataFrame, config: DegreeConfig) -> dict[str, Any]:
    pivots = _confirmed_pivots(frame, config)
    evidence = _sequence_evidence(pivots)
    rail = _best_rail(frame, pivots, evidence["state"], config)
    compression = _compression(frame, pivots) if evidence["state"] == "CONTRACTION" else None
    return {
        "degree": config.name,
        **evidence,
        "pivot_count": len(pivots),
        "recent_pivots": pivots[-12:],
        "rail": None if rail is None else rail.to_dict(),
        "compression": compression,
        "confluence_eligible": bool(rail and rail.status == "CONFIRMED"),
    }


def hierarchy_score(hierarchy: dict[str, Any]) -> float | None:
    mapping = {
        "UP": 85.0,
        "ASCENDING_TRIANGLE": 70.0,
        "CONTRACTION": 50.0,
        "RANGE": 50.0,
        "EXPANSION": 50.0,
        "DESCENDING_TRIANGLE": 30.0,
        "DOWN": 15.0,
    }
    weights = {"MAJOR": 0.45, "SWING": 0.35, "MINOR": 0.20}
    values: list[tuple[float, float]] = []
    for degree, weight in weights.items():
        state = str((hierarchy.get(degree) or {}).get("state", "INSUFFICIENT"))
        if state in mapping:
            values.append((mapping[state], weight))
    if not values:
        return None
    total = sum(weight for _, weight in values)
    return round(sum(value * weight for value, weight in values) / total, 1)


def analyze_structure_hierarchy(frame: pd.DataFrame) -> dict[str, Any]:
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(frame.columns) or len(frame) < 40:
        return {"score": None, "summary": "VERİ YETERSİZ", "confirmed_rails": 0}
    degrees = {config.name: analyze_degree(frame, config) for config in DEGREES}
    score = hierarchy_score(degrees)
    confirmed = sum(bool((degrees[name].get("rail") or {}).get("status") == "CONFIRMED") for name in degrees)
    symbols = {
        "UP": "↑",
        "DOWN": "↓",
        "RANGE": "↔",
        "CONTRACTION": "△",
        "EXPANSION": "◇",
        "ASCENDING_TRIANGLE": "△↑",
        "DESCENDING_TRIANGLE": "△↓",
        "INSUFFICIENT": "—",
    }
    degree_codes = {"MAJOR": "M", "SWING": "S", "MINOR": "L"}
    summary = " · ".join(
        f"{degree_codes[name]}{symbols.get(str(degrees[name].get('state')), '?')}"
        for name in ("MAJOR", "SWING", "MINOR")
    )
    return {**degrees, "score": score, "summary": summary, "confirmed_rails": confirmed}
