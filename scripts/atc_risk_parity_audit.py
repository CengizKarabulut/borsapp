"""Diagnostic-only Pine/Python stop-TP parity audit; does not alter scanner rules.

Usage:
  python -m scripts.atc_risk_parity_audit --csv /path/to/ohlcv.csv --scanner signal.smi_macd_positive --direction bullish

CSV columns: open,high,low,close (chronological, unadjusted or consistently adjusted).
The output explains risk inputs and invalid-price conditions without inventing levels.
"""
from __future__ import annotations

import argparse
import csv
import json
from math import isfinite

from market_intelligence.scanning.trade_plan import PINE_A_I


def diagnose(bars, scanner, direction):
    if len(bars) < 15:
        raise ValueError("At least 15 complete bars required")
    if any(not all(isfinite(b[k]) and b[k] > 0 for k in ("open", "high", "low", "close")) for b in bars):
        raise ValueError("Nonpositive/nonfinite OHLC; verify corporate-action adjustments")
    tr = []
    for i, b in enumerate(bars):
        tr.append(b["high"] - b["low"] if i == 0 else max(
            b["high"] - b["low"],
            abs(b["high"] - bars[i - 1]["close"]),
            abs(b["low"] - bars[i - 1]["close"]),
        ))
    pine_atr = tr[0]
    for value in tr[1:]:
        pine_atr = (pine_atr * 13 + value) / 14
    # Python generic structural-atr-v1 intentionally uses a different seed.
    generic_atr = sum(tr[1:15]) / 14
    for value in tr[15:]:
        generic_atr = (generic_atr * 13 + value) / 14
    entry = bars[-1]["close"]
    if scanner in PINE_A_I:
        if direction != "bullish":
            return {"status": "not_supported", "reason": "A-I has no standalone short plan"}
        n, ema_n, mode, buffer, min_mult, max_mult, r1, r2, r3 = PINE_A_I[scanner]
        alpha = 2 / (ema_n + 1)
        ema = bars[0]["close"]
        for b in bars[1:]:
            ema = alpha * b["close"] + (1 - alpha) * ema
        swing = min(b["low"] for b in bars[-n:]) - pine_atr * buffer
        signal = bars[-1]["low"] - pine_atr * buffer
        ema_stop = ema - pine_atr * buffer
        fallback = entry - pine_atr * min_mult
        eligible = [x for x in (swing, signal, ema_stop) if x < entry]
        raw = swing if mode == 1 else (min(eligible) if mode == 2 else max(eligible)) if eligible else fallback
        risk = min(max(max(entry - raw, 0), pine_atr * min_mult), pine_atr * max_mult)
        side = "long"
        stop = entry - risk
        tps = [entry + risk * r for r in (r1, r2, r3)]
        extra = {"swing_stop": swing, "signal_stop": signal, "ema_stop": ema_stop,
                 "raw_stop": raw, "ema": ema, "min_risk": pine_atr * min_mult,
                 "max_risk": pine_atr * max_mult, "atr14": pine_atr}
    else:
        if direction not in ("bullish", "bearish"):
            raise ValueError("Direction must be bullish or bearish")
        risk_atr = generic_atr
        if direction == "bullish":
            structural = min(b["low"] for b in bars[-7:]) - .2 * risk_atr
            risk = max(entry - structural, .75 * risk_atr)
            stop = entry - risk
            tps = [entry + risk * r for r in (1, 2, 3)]
            side = "long"
        else:
            structural = max(b["high"] for b in bars[-7:]) + .2 * risk_atr
            risk = max(structural - entry, .75 * risk_atr)
            stop = entry + risk
            tps = [entry - risk * r for r in (1, 2, 3)]
            side = "short"
        extra = {"structural_stop": structural, "atr14": risk_atr,
                 "atr14_pine_seed_for_comparison": pine_atr}
    valid = all(isfinite(x) and x > 0 for x in (entry, stop, *tps))
    return {"status": "valid" if valid else "invalid_price", "scanner": scanner,
            "side": side, "bars": len(bars), "entry": entry, "risk": risk,
            "risk_pct": 100 * risk / entry, "stop": stop,
            "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
            "invalid_fields": [name for name, val in zip(
                ("stop", "tp1", "tp2", "tp3"), (stop, *tps), strict=True) if val <= 0 or not isfinite(val)],
            **extra}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--scanner", required=True)
    p.add_argument("--direction", choices=["bullish", "bearish"], required=True)
    args = p.parse_args()
    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        bars = [{k: float(row[k]) for k in ("open", "high", "low", "close")}
                for row in csv.DictReader(f)]
    print(json.dumps(diagnose(bars, args.scanner, args.direction),
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
