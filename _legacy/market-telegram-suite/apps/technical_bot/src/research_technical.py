"""Technical research layer driven by the same original indicators as the chart.

Price structure stays primary. Indicator families are confirmation, not separate
buy/sell votes.  MAJOR/SWING/MINOR structure, structural rails, MA families,
volume-price POC horizons and participation are exposed as context.  Candidate
rails never count as confirmed confluence.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src import research_engine as core
from src.original_indicators import build_indicator_frame
from src.research_engine import LevelZone
from src.structure_hierarchy import analyze_structure_hierarchy


def _structure_score(state: str) -> float | None:
    if state == "HH / HL":
        return 85.0
    if state == "LH / LL":
        return 15.0
    if state in {"HH / LL", "LH / HL"}:
        return 50.0
    return None


def _structure_event(structure: dict[str, Any]) -> str:
    """Classify a confirmed break as continuation BOS or conservative CHoCH."""
    bos = str(structure.get("bos", ""))
    last_high = structure.get("last_high") or {}
    last_low = structure.get("last_low") or {}
    high_label = str(last_high.get("label", ""))
    low_label = str(last_low.get("label", ""))

    if "Swing High üzeri BOS" in bos:
        if high_label == "LH" or low_label == "LL":
            return "CHoCH YUKARI"
        return "BOS YUKARI"
    if "Swing Low altı BOS" in bos:
        if high_label == "HH" or low_label == "HL":
            return "CHoCH AŞAĞI"
        return "BOS AŞAĞI"
    return "YENİ KIRILIM YOK"


def _collapse_alternating(pivots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for pivot in pivots:
        if not result or result[-1]["type"] != pivot["type"]:
            result.append(pivot)
            continue
        previous = result[-1]
        if (
            pivot["type"] == "high"
            and float(pivot["price"]) >= float(previous["price"])
        ) or (
            pivot["type"] == "low"
            and float(pivot["price"]) <= float(previous["price"])
        ):
            result[-1] = pivot
    return result


def _elliott_context(pivots: list[dict[str, Any]], structure: dict[str, Any]) -> dict[str, Any]:
    """Return a non-forced Elliott hypothesis with confidence and invalidation."""
    alternating = _collapse_alternating(pivots[-14:])
    state = str(structure.get("state", "—"))
    event = _structure_event(structure)
    if len(alternating) < 5:
        return {
            "primary": "BELİRSİZ",
            "alternate": "—",
            "confidence": 20,
            "invalidation": None,
            "note": "Yeterli teyitli alternatif swing yok; dalga sayımı zorlanmadı.",
        }

    highs = [item for item in alternating if item["type"] == "high"]
    lows = [item for item in alternating if item["type"] == "low"]
    if state == "HH / HL":
        invalidation = float(lows[-1]["price"]) if lows else None
        confidence = 65 if event == "BOS YUKARI" else 55
        return {
            "primary": "YÜKSELİŞ İTKİ / DÜZELTME ADAYI",
            "alternate": "ABC DÜZELTMESİ",
            "confidence": confidence,
            "invalidation": invalidation,
            "note": "Kesin 1-5 etiketi verilmez; teyitli swing dizisi ve yapı kullanılır.",
        }
    if state == "LH / LL":
        invalidation = float(highs[-1]["price"]) if highs else None
        confidence = 65 if event == "BOS AŞAĞI" else 55
        return {
            "primary": "DÜŞÜŞ İTKİ / DÜZELTME ADAYI",
            "alternate": "ABC TEPKİSİ",
            "confidence": confidence,
            "invalidation": invalidation,
            "note": "Kesin 1-5 etiketi verilmez; teyitli swing dizisi ve yapı kullanılır.",
        }
    return {
        "primary": "BELİRSİZ",
        "alternate": "YATAY / KOMPLEKS DÜZELTME",
        "confidence": 30,
        "invalidation": None,
        "note": "Karışık piyasa yapısında Elliott bağlamı karar girdisi yapılmaz.",
    }


def _resample_context(
    prepared: pd.DataFrame,
    rule: str,
    *,
    left: int,
    right: int,
) -> dict[str, Any]:
    frame = (
        prepared[["Open", "High", "Low", "Close", "Volume"]]
        .resample(rule)
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna()
    )
    if len(frame) < left + right + 8:
        return {"state": "—", "bos": "—", "event": "VERİ YETERSİZ"}
    context = core._prepare_prices(frame)
    pivots = core._pivots(context, left=left, right=right)
    structure = core._structure(context, pivots) if pivots else {"state": "—", "bos": "—"}
    return {**structure, "event": _structure_event(structure)}


def _wma(series: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda values: float(np.dot(values, weights) / weights.sum()), raw=True)


def _ma_family(close: pd.Series, periods: tuple[int, int, int]) -> dict[str, Any]:
    last_price = float(close.iloc[-1])
    ema = [core._finite(close.ewm(span=period, adjust=False).mean().iloc[-1]) for period in periods]
    sma = [core._finite(close.rolling(period).mean().iloc[-1]) for period in periods]
    wma = [core._finite(_wma(close, period).iloc[-1]) for period in periods]

    def family_state(values: list[float | None]) -> dict[str, Any]:
        available = [value for value in values if value is not None]
        above = sum(last_price > value for value in available)
        ascending = len(available) == 3 and available[0] > available[1] > available[2]
        descending = len(available) == 3 and available[0] < available[1] < available[2]
        if above == 3 and ascending:
            label = "GÜÇLÜ POZİTİF"
        elif above == 3:
            label = "POZİTİF"
        elif above == 2:
            label = "KISMİ POZİTİF"
        elif above == 1:
            label = "ZAYIF"
        elif len(available) == 3 and descending:
            label = "GÜÇLÜ NEGATİF"
        else:
            label = "NEGATİF" if available else "VERİ YETERSİZ"
        return {"values": values, "above_count": above, "ascending": ascending, "descending": descending, "label": label}

    ema_state = family_state(ema)
    sma_state = family_state(sma)
    wma_state = family_state(wma)
    confirmation = sum(
        state["above_count"] >= 2
        for state in (ema_state, sma_state, wma_state)
        if state["values"]
    )
    return {
        "periods": periods,
        "ema": ema_state,
        "sma": sma_state,
        "wma": wma_state,
        "confirmation": "TEYİTLİ" if confirmation == 3 else "KISMİ" if confirmation >= 2 else "ZAYIF",
    }


def _moving_average_context(daily: pd.DataFrame, price: float, atr: float | None) -> dict[str, Any]:
    close = daily["Close"].astype(float)
    groups = {
        "short": _ma_family(close, (5, 8, 13)),
        "medium": _ma_family(close, (21, 34, 55)),
        "long": _ma_family(close, (89, 144, 233)),
    }
    short_ema = groups["short"]["ema"]["values"]
    distances = [abs(price / value - 1.0) * 100.0 for value in short_ema if value not in (None, 0)]
    mean_distance = float(np.mean(distances)) if distances else None
    atr_distance = None
    if atr and atr > 0 and short_ema and short_ema[0] is not None:
        atr_distance = abs(price - float(short_ema[0])) / atr
    if mean_distance is None:
        extension = "VERİ YETERSİZ"
    elif mean_distance >= 10 or (atr_distance is not None and atr_distance >= 2.5):
        extension = "AŞIRI UZAK / MEAN-REVERSION RİSKİ"
    elif mean_distance >= 5 or (atr_distance is not None and atr_distance >= 1.5):
        extension = "UZAMIŞ"
    else:
        extension = "NORMAL"
    return {
        **groups,
        "short_ema_mean_distance_pct": None if mean_distance is None else round(mean_distance, 2),
        "ema5_distance_atr": None if atr_distance is None else round(atr_distance, 2),
        "extension_risk": extension,
    }


def _volume_poc_window(data: pd.DataFrame, bars: int, bins: int = 36) -> float | None:
    window = data.tail(bars)
    if len(window) < max(10, bars // 3):
        return None
    typical = ((window["High"] + window["Low"] + window["Close"]) / 3.0).astype(float)
    volume = pd.to_numeric(window["Volume"], errors="coerce").fillna(0.0).astype(float)
    lo, hi = float(typical.min()), float(typical.max())
    if not np.isfinite([lo, hi]).all() or hi <= lo or volume.sum() <= 0:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    bucket = np.clip(np.digitize(typical.to_numpy(), edges) - 1, 0, bins - 1)
    totals = np.bincount(bucket, weights=volume.to_numpy(), minlength=bins)
    index = int(np.argmax(totals))
    return float((edges[index] + edges[index + 1]) / 2.0)


def _participation_context(daily: pd.DataFrame, rvol: float | None) -> dict[str, Any]:
    turnover = (daily["Close"] * daily["Volume"]).astype(float)
    current = core._finite(turnover.iloc[-1])
    baseline = core._finite(turnover.iloc[-21:-1].median()) if len(turnover) >= 21 else None
    relative_turnover = core._ratio(current, baseline)
    impulse = None
    if len(daily) >= 6:
        impulse = (float(daily["Close"].iloc[-1]) / float(daily["Close"].iloc[-6]) - 1.0) * 100.0
    if rvol is not None and rvol >= 1.5 and relative_turnover is not None and relative_turnover >= 1.3:
        label = "GÜÇLÜ KATILIM"
    elif rvol is not None and rvol < 0.8:
        label = "ZAYIF KATILIM"
    else:
        label = "NORMAL / KARIŞIK"
    return {
        "rvol20": rvol,
        "relative_turnover": relative_turnover,
        "price_impulse_5d_pct": impulse,
        "label": label,
    }


def _technical_analysis(symbol: str) -> tuple[dict[str, Any], tuple[LevelZone, ...], tuple[LevelZone, ...]]:
    import borsapy as bp

    stock = bp.Ticker(symbol)
    prepared = core._prepare_prices(stock.history(period="2y", interval="1d"))
    daily, divergences = build_indicator_frame(prepared, include_hidden_divergence=False)
    daily = daily.dropna(subset=["ATR14"]).copy()
    if len(daily) < 80:
        raise RuntimeError("Insufficient daily history for technical research")

    pivot_frame = prepared.dropna(subset=["ATR"])
    pivots = core._pivots(pivot_frame)
    structure = core._structure(pivot_frame, pivots)
    structure = {**structure, "event": _structure_event(structure)}
    hierarchy = analyze_structure_hierarchy(pivot_frame)
    supports, resistances = core._level_zones(pivot_frame, pivots)
    row = daily.iloc[-1]
    price = float(row["Close"])

    alpha = core._finite(row.get("AlphaTrend"))
    alpha_lag2 = core._finite(row.get("AlphaTrendLag2"))
    if alpha is None or alpha_lag2 is None:
        alpha_score = None
        alpha_state = "VERİ YETERSİZ"
    elif price > alpha > alpha_lag2:
        alpha_score = 90.0
        alpha_state = "FİYAT ÜSTÜNDE / YÜKSELEN"
    elif price < alpha < alpha_lag2:
        alpha_score = 10.0
        alpha_state = "FİYAT ALTINDA / DÜŞEN"
    else:
        alpha_score = 50.0
        alpha_state = "KARIŞIK"

    rsi_value = core._finite(row.get("RSI14"))
    macd_hist = core._finite(row.get("MACD_HIST"))
    smi_value = core._finite(row.get("SMI"))
    smi_signal = core._finite(row.get("SMI_SIGNAL"))
    obv_series = daily["OBV"].dropna()
    obv_change = None
    if len(obv_series) >= 11 and abs(float(obv_series.iloc[-11])) > 1e-9:
        old_obv = float(obv_series.iloc[-11])
        new_obv = float(obv_series.iloc[-1])
        obv_change = (new_obv - old_obv) / abs(old_obv) * 100.0

    smi_score = None
    if smi_value is not None and smi_signal is not None:
        if smi_value > smi_signal and smi_value > 0:
            smi_score = 85.0
        elif smi_value < smi_signal and smi_value < 0:
            smi_score = 15.0
        else:
            smi_score = 50.0

    momentum_score, momentum_cov = core._weighted(
        [
            (core._score_target(rsi_value, 50.0, 68.0, 25.0, 85.0), 1.0),
            (core._score_higher(macd_hist, -abs(price) * 0.01, abs(price) * 0.01), 1.0),
            (smi_score, 1.0),
            (core._score_higher(obv_change, -10.0, 10.0), 0.7),
        ]
    )

    weekly_structure = _resample_context(prepared, "W-FRI", left=2, right=2)
    monthly_structure = _resample_context(prepared, "ME", left=1, right=1)
    mtf = {"1G": structure, "1Hf": weekly_structure, "1A": monthly_structure}
    weekly_score = _structure_score(str(weekly_structure.get("state", "—")))
    monthly_score = _structure_score(str(monthly_structure.get("state", "—")))
    hierarchy_score = core._finite(hierarchy.get("score"))
    primary_structure_score = hierarchy_score if hierarchy_score is not None else _structure_score(str(structure.get("state", "—")))

    technical_score, technical_cov = core._weighted(
        [
            (primary_structure_score, 1.4),
            (alpha_score, 1.0),
            (momentum_score, 1.1),
            (weekly_score, 1.0),
            (monthly_score, 0.6),
        ]
    )

    atr_value = core._finite(row.get("ATR14"))
    atr_pct = atr_value / price * 100.0 if atr_value is not None and price else None
    turnover = (daily["Close"] * daily["Volume"]).tail(20)
    avg_turnover = core._finite(turnover.mean())
    volume_mean = core._finite(daily["Volume"].iloc[-21:-1].mean())
    rvol = core._ratio(core._finite(row.get("Volume")), volume_mean)
    latest_divergence = None
    visible_divergences = [point for point in divergences if point.index >= daily.index[-60]]
    if visible_divergences:
        latest = visible_divergences[-1]
        latest_divergence = {"kind": latest.kind, "time": str(latest.index), "rsi": latest.rsi, "price": latest.price}

    bb_upper = core._finite(row.get("BB_UPPER"))
    bb_lower = core._finite(row.get("BB_LOWER"))
    bb_mid = core._finite(row.get("BB_MID"))
    if bb_upper is not None and price > bb_upper:
        bb_state = "ÜST BAND ÜZERİ"
    elif bb_lower is not None and price < bb_lower:
        bb_state = "ALT BAND ALTI"
    elif bb_mid is not None and price >= bb_mid:
        bb_state = "ORTA BAND ÜSTÜ"
    elif bb_mid is not None:
        bb_state = "ORTA BAND ALTI"
    else:
        bb_state = "VERİ YETERSİZ"

    moving_averages = _moving_average_context(daily, price, atr_value)
    volume_profile = {
        "short_poc": _volume_poc_window(daily, 20),
        "medium_poc": _volume_poc_window(daily, 60),
        "long_poc": _volume_poc_window(daily, 180),
    }
    participation = _participation_context(daily, rvol)

    return (
        {
            "score": technical_score,
            "coverage": technical_cov,
            "label": core._label(technical_score, "POZİTİF", "KARIŞIK", "ZAYIF"),
            "structure": structure,
            "structure_hierarchy": hierarchy,
            "weekly_structure": weekly_structure,
            "monthly_structure": monthly_structure,
            "mtf": mtf,
            "elliott": _elliott_context(pivots, structure),
            "moving_average_regime": moving_averages,
            "volume_profile": volume_profile,
            "participation": participation,
            "rsi14": rsi_value,
            "macd_hist": macd_hist,
            "smi": smi_value,
            "smi_signal": smi_signal,
            "obv_10d_change": obv_change,
            "alpha_trend": alpha,
            "alpha_trend_lag2": alpha_lag2,
            "alpha_trend_state": alpha_state,
            "bollinger_state": bb_state,
            "latest_rsi_divergence": latest_divergence,
            "momentum_score": momentum_score,
            "momentum_coverage": momentum_cov,
            "atr": atr_value,
            "atr_pct": atr_pct,
            "rvol20": rvol,
            "average_turnover_20": avg_turnover,
            "pivots": pivots[-12:],
        },
        supports,
        resistances,
    )
