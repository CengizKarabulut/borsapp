"""Compare genuine BIST vendor OHLCV for Pine plans rejected on 2026-10-16.

Read-only investigation: no fabricated candle, price-level adjustment, scanner
match rewrite, Telegram publishing or live order logic. Exact original
ephemeral DB snapshots expire with the runner; independent fresh vendor
histories are investigated here, with source and price basis kept separate.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.adapters.tvdatafeed import TvDatafeedBistProvider
from market_intelligence.market_data.adapters.yfinance import YFinanceBistProvider
from market_intelligence.market_data.canonicalizer import Canonicalizer
from market_intelligence.market_data.providers import FetchRequest
from market_intelligence.scanning.trade_plan import (
    PINE_A_I,
    build_pine_a_i_plan,
    build_trade_plan,
)

AS_OF = datetime(2026, 10, 16, 18, tzinfo=ZoneInfo("Europe/Istanbul"))
CASES = {
    "1d": {
        "code": 15, "side": "bearish",
        "stocks": "BINBN BINHO INFO KLRHO PASEU PEKGY POLTK SEGMN UFUK".split(),
    },
    "1wk": {
        "code": None, "side": None,
        "stocks": {
            "LIDER": (8, "bullish"),
            "CELHA": (13, "bearish"), "EGEPO": (13, "bearish"),
            "KORDS": (13, "bearish"), "MAGEN": (13, "bearish"),
            "OZRDN": (13, "bearish"), "SELEC": (13, "bearish"),
            "TRALT": (13, "bearish"), "UNLU": (13, "bearish"),
            "BULGS": (15, "bearish"), "OTTO": (15, "bearish"),
            "SUWEN": (15, "bearish"), "VKING": (15, "bearish"),
        },
    },
}
PROVIDERS = (BorsapyProvider(), YFinanceBistProvider(), TvDatafeedBistProvider())


def numeric_diagnosis(bars, code):
    """Recalculate *unchanged* original stop/targets from one actual vendor."""
    current = bars[-1]
    atr = None
    if code <= 9:
        # Pine A-I f_ewm_alpha ta.tr(true) seeds from first bar's true range.
        for i, b in enumerate(bars):
            tr = b.high - b.low if i == 0 else max(
                b.high - b.low, abs(b.high - bars[i - 1].close),
                abs(b.low - bars[i - 1].close),
            )
            atr = tr if atr is None else (13 * atr + tr) / 14
        scanner = "signal.smi_macd_early"  # Pine letter H, original code 8
        swing, ema_n, mode, buffer, min_atr, max_atr, r1, r2, r3 = PINE_A_I[scanner]
        ema = bars[0].close
        alpha = 2.0 / (ema_n + 1.0)
        for b in bars[1:]:
            ema = alpha * b.close + (1.0 - alpha) * ema
        swing_stop = min(b.low for b in bars[-swing:]) - atr * buffer
        signal_stop = bars[-1].low - atr * buffer
        ema_stop = ema - atr * buffer
        fallback = current.close - atr * min_atr
        if mode == 1:
            raw_stop = swing_stop
        else:
            below = [z for z in (swing_stop, signal_stop, ema_stop) if z < current.close]
            raw_stop = (min(below) if mode == 2 else max(below)) if below else fallback
        risk = min(max(max(current.close - raw_stop, 0), atr * min_atr), atr * max_atr)
        stop = current.close - risk
        targets = [current.close + risk * x for x in (r1, r2, r3)]
        extra = {
            "swing_low": min(b.low for b in bars[-swing:]),
            "swing_stop": swing_stop,
            "raw_stop": raw_stop,
            "ema": ema,
            "atr_min_risk": atr * min_atr,
            "atr_max_risk": atr * max_atr,
        }
    else:
        # Generic structural-atr-v1, SHORT: stop = swing7 high + ATR buffer.
        true_ranges = [
            max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
            for a, b in zip(bars, bars[1:], strict=False)
        ]
        atr = sum(true_ranges[:14]) / 14
        for tr in true_ranges[14:]:
            atr = (atr * 13 + tr) / 14
        swing_high = max(b.high for b in bars[-7:])
        raw_stop = swing_high + 0.2 * atr
        risk = max(raw_stop - current.close, 0.75 * atr)
        stop = current.close + risk
        targets = [current.close - risk * mult for mult in (1, 2, 3)]
        extra = {
            "swing7_high": swing_high,
            "raw_stop": raw_stop,
            "atr_min_risk": 0.75 * atr,
            "maximum_positive_tp3_risk": current.close / 3,
        }
    prev = bars[-2].close if len(bars) > 1 else None
    gross_change = 100 * (current.close / prev - 1) if prev and prev > 0 else None
    return {
        "entry": current.close, "atr14": atr,
        "atr_over_entry_pct": 100 * atr / current.close,
        "risk": risk, "risk_over_entry_pct": 100 * risk / current.close,
        "stop": stop, "tp1": targets[0], "tp2": targets[1], "tp3": targets[2],
        "close_change_pct": gross_change,
        "failure": "nonpositive_stop" if stop <= 0 else (
            "nonpositive_tp" if min(targets) <= 0 else "none"
        ),
        **extra,
    }


def main():
    results = []
    canonicalizer = Canonicalizer()
    for tf_name, block in CASES.items():
        target = Timeframe.D1 if tf_name == "1d" else Timeframe.W1
        stocks = block["stocks"]
        symbols = stocks if isinstance(stocks, list) else list(stocks)
        for symbol in symbols:
            code, side = ((block["code"], block["side"]) if tf_name == "1d"
                          else stocks[symbol])
            record = {"symbol": symbol, "timeframe": tf_name, "code": code,
                      "direction": side, "sources": []}
            for provider in PROVIDERS:
                result = {"source": provider.name}
                try:
                    request = FetchRequest(
                        provider_symbol=symbol, timeframe=Timeframe.D1,
                        bars=600 if tf_name == "1d" else 3010, as_of=AS_OF,
                    )
                    raw = provider.fetch(request)
                    frame = canonicalizer.build(
                        instrument_id=f"diagnostic-{symbol}",
                        symbol_at_snapshot=symbol, market="BIST",
                        provider_frame=raw, target_timeframe=target,
                        series_revision=1,
                    )
                    if frame.through_bar_time != AS_OF:
                        raise ValueError(
                            f"target missing: {frame.through_bar_time.isoformat()}"
                        )
                    if len(frame.bars) < 15:
                        raise ValueError(f"insufficient history: {len(frame.bars)}")
                    plan = (
                        build_pine_a_i_plan(frame, "signal.smi_macd_early", side)
                        if code == 8 else build_trade_plan(frame, side)
                    )
                    metrics = numeric_diagnosis(frame.bars, code)
                    result.update({
                        "status": "verified_candle", "price_basis": frame.price_basis.value,
                        "bars": len(frame.bars), "bar_close": frame.through_bar_time.isoformat(),
                        "plan_status": plan["status"], "plan_reason": plan["reason"],
                        "metrics": metrics,
                        "last_seven_ohlcv": [
                            {"date": b.close_time.isoformat(), "open": b.open,
                             "high": b.high, "low": b.low, "close": b.close,
                             "volume": b.volume}
                            for b in frame.bars[-7:]
                        ],
                    })
                    print(
                        f"ATC ACTUAL OHLC {tf_name} {symbol} {provider.name} "
                        f"basis={frame.price_basis.value} n={len(frame.bars)} "
                        f"close={metrics['entry']:.6f} hi7="
                        f"{metrics.get('swing7_high', 0):.6f} "
                        f"atr={metrics['atr14']:.6f} risk={metrics['risk']:.6f} "
                        f"stop={metrics['stop']:.6f} tp1={metrics['tp1']:.6f} "
                        f"tp2={metrics['tp2']:.6f} tp3={metrics['tp3']:.6f} "
                        f"cause={plan['reason']} ({metrics['failure']})",
                        flush=True,
                    )
                except Exception as exc:
                    result["status"] = "error"
                    result["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
                    print(
                        f"ATC OHLC PROVIDER ERROR {tf_name} {symbol} "
                        f"{provider.name}: {result['error']}", flush=True,
                    )
                record["sources"].append(result)
            results.append(record)
    dest = Path("runtime_artifacts/atc_22_real_ohlc_diagnosis.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({
        "as_of": AS_OF.isoformat(),
        "source_type": "new independent source refetch, NOT old ephemeral DB",
        "cases": results,
    }, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"ATC DIAG COMPLETE: {len(results)} cases, "
          f"{sum(z['status']=='verified_candle' for r in results for z in r['sources'])} "
          "authentic vendor snapshots", flush=True)


if __name__ == "__main__":
    main()
