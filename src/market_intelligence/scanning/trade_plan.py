"""Versioned reference scenarios; not executable orders or validated strategy exits."""

from __future__ import annotations

from dataclasses import replace
from math import isfinite

VERSION = "structural-atr-v1"


def build_trade_plan(frame, direction):
    meta = {
        "version": VERSION,
        "snapshot_id": frame.snapshot_id,
        "source": frame.source,
        "price_basis": frame.price_basis.value,
        "bar_time": frame.through_bar_time.isoformat(),
        "timeframe": frame.timeframe.value,
        "entry_basis": "signal_close_reference",
        "validation": "not_backtested",
        "costs_included": False,
        "executable_order": False,
    }

    def unavailable(reason):
        return {**meta, "status": "unavailable", "reason": reason, "scenarios": []}

    if frame.is_partial:
        return unavailable("partial_bar")
    if frame.price_basis.value not in {"raw", "split_adjusted"}:
        return unavailable("unsupported_price_basis")
    if len(frame.bars) < 15:
        return unavailable("insufficient_history")
    bars = frame.bars
    if any(min(b.open, b.high, b.low, b.close) <= 0 for b in bars):
        return unavailable("invalid_price")
    tr = [
        max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
        for a, b in zip(bars, bars[1:], strict=False)
    ]
    atr = sum(tr[:14]) / 14
    for value in tr[14:]:
        atr = (atr * 13 + value) / 14
    if not isfinite(atr) or atr <= 0:
        return unavailable("zero_volatility")
    entry = bars[-1].close
    directions = {
        "bullish": ("long",),
        "bearish": ("short",),
        "neutral": ("long", "short"),
        "mixed": ("long", "short"),
    }
    sides = directions.get(str(direction))
    if sides is None:
        return unavailable("unknown_direction")
    scenarios = []
    for side in sides:
        sign = 1 if side == "long" else -1
        structural = (
            min(b.low for b in bars[-7:]) - 0.2 * atr
            if sign == 1
            else max(b.high for b in bars[-7:]) + 0.2 * atr
        )
        # Never pull a structural stop inward to make risk look smaller.
        risk = max(sign * (entry - structural), 0.75 * atr)
        stop = entry - sign * risk
        targets = [entry + sign * risk * r for r in (1, 2, 3)]
        if min(stop, *targets) <= 0 or not all(isfinite(x) for x in (stop, *targets, risk)):
            continue
        scenarios.append(
            {
                "side": side,
                "entry": entry,
                "stop": stop,
                "tp1": targets[0],
                "tp2": targets[1],
                "tp3": targets[2],
                "risk_per_share": risk,
                "risk_pct": 100 * risk / entry,
                "reward_risk": [1.0, 2.0, 3.0],
                "atr14": atr,
                "wide_stop": risk / atr > 3,
                "stop_basis": "swing7_buffer_0.2atr_minrisk_0.75atr",
            }
        )
    if not scenarios:
        return unavailable("nonpositive_level")
    return {
        **meta,
        "status": "conditional" if len(sides) > 1 else "reference",
        "reason": "direction_unconfirmed" if len(sides) > 1 else "signal_direction",
        "scenarios": scenarios,
    }


def attach_trade_plan(finding, frame):
    # Existing scanner-specific plans retain their values and provenance.
    if "trade_plan" in finding.metrics:
        return finding
    return replace(
        finding,
        metrics={**finding.metrics, "trade_plan": build_trade_plan(frame, finding.direction)},
    )
