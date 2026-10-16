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



# Exactly the source parameters in the owner's Pine f_plan for A-I.
# (swing lookback, EMA period, mode, ATR buffer, min risk, max risk,
#  TP1 R, TP2 R, TP3 R)
PINE_A_I = {
    "signal.macd_positive_cross": (7, 21, 3, 0.20, 0.75, 2.35, 1.0, 1.8, 2.8),
    "signal.smi_macd_positive": (6, 13, 1, 0.20, 0.70, 2.20, 0.8, 1.5, 2.4),
    "signal.smi_macd_positive_volume_confirmed": (7, 21, 2, 0.20, 0.75, 2.40, 0.8, 1.5, 2.4),
    "signal.ema_trend_volume": (8, 21, 3, 0.20, 0.80, 2.50, 1.0, 2.0, 3.2),
    "signal.rsi_macd_volume": (6, 13, 1, 0.20, 0.70, 2.20, 0.8, 1.5, 2.4),
    "signal.sma_macd_volume": (8, 21, 1, 0.20, 0.80, 2.60, 0.8, 1.5, 2.4),
    "signal.smi_macd_full": (7, 21, 1, 0.25, 0.80, 2.50, 0.8, 1.5, 2.4),
    "signal.smi_macd_early": (6, 21, 1, 0.25, 0.75, 2.25, 0.8, 1.5, 2.4),
    "signal.rsi_momentum_volume": (4, 21, 2, 0.15, 0.65, 1.90, 0.8, 1.5, 2.4),
}


def build_pine_a_i_plan(frame, scanner_id, direction):
    """Recalculate owner's A-I LONG reference formula on the saved OHLCV frame.

    This follows the Pine f_plan swing/EMA/ATR and TP multiples without
    modifying scanner rule matches or generating executable orders.
    """
    if scanner_id not in PINE_A_I:
        raise ValueError("Not a Pine A-I scanner")
    base = {
        "version": "pine-a-i-plan-v1",
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

    def unavailable(why):
        return {**base, "status": "unavailable", "reason": why, "scenarios": []}

    if frame.is_partial:
        return unavailable("partial_bar")
    if frame.price_basis.value not in ("raw", "split_adjusted"):
        return unavailable("unsupported_price_basis")
    if str(direction) != "bullish":
        return unavailable("native_a_i_no_short_side")
    bars = frame.bars
    if len(bars) < 14 or any(min(b.open, b.high, b.low, b.close) <= 0 for b in bars):
        return unavailable("insufficient_or_invalid_price_history")
    # f_ewm_alpha(ta.tr(true), 14) seeds from the FIRST true range.
    atr = None
    for idx, bar in enumerate(bars):
        tr = (bar.high - bar.low if idx == 0 else max(
            bar.high - bar.low,
            abs(bar.high - bars[idx - 1].close),
            abs(bar.low - bars[idx - 1].close),
        ))
        atr = tr if atr is None else (atr * 13.0 + tr) / 14.0
    if not isfinite(atr) or atr <= 0:
        return unavailable("nonpositive_atr")
    swing_n, ema_n, mode, buffer, min_atr, max_atr, r1, r2, r3 = PINE_A_I[scanner_id]
    alpha = 2.0 / (ema_n + 1.0)
    ema = bars[0].close
    for bar in bars[1:]:
        ema = alpha * bar.close + (1.0 - alpha) * ema
    entry = bars[-1].close
    swing_stop = min(b.low for b in bars[-swing_n:]) - atr * buffer
    signal_stop = bars[-1].low - atr * buffer
    ema_stop = ema - atr * buffer
    fallback = entry - atr * min_atr
    if mode == 1:
        raw_stop = swing_stop
    else:
        below = [level for level in (swing_stop, signal_stop, ema_stop) if level < entry]
        raw_stop = (
            (min(below) if mode == 2 else max(below)) if below else fallback
        )
    risk = max(entry - raw_stop, 0.0)
    if risk < atr * min_atr:
        risk = atr * min_atr
    elif risk > atr * max_atr:
        risk = atr * max_atr
    stop = entry - risk
    targets = [entry + risk * ratio for ratio in (r1, r2, r3)]
    if not all(isfinite(v) and v > 0 for v in (entry, stop, *targets)):
        return unavailable("invalid_stop_or_target")
    return {
        **base,
        "status": "reference", "reason": "pine_a_i_bullish_reference",
        "scenarios": [{
            "side": "long", "entry": entry, "stop": stop,
            "tp1": targets[0], "tp2": targets[1], "tp3": targets[2],
            "risk_per_share": risk,
            "risk_pct": 100.0 * risk / entry,
            "reward_risk": [r1, r2, r3],
            "atr14": atr, "wide_stop": risk / atr > 3.0,
            "stop_basis": "pine_f_plan_v1",
        }],
    }

def attach_trade_plan(finding, frame):
    # Existing scanner-specific plans retain their values and provenance.
    if "trade_plan" in finding.metrics:
        return finding
    plan = (
        build_pine_a_i_plan(frame, finding.scanner_id, finding.direction)
        if finding.scanner_id in PINE_A_I
        else build_trade_plan(frame, finding.direction)
    )
    return replace(finding, metrics={**finding.metrics, "trade_plan": plan})
