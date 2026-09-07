from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

REGIME_THRESHOLDS = {
    "directional_adx": 25.0,
    "balanced_adx": 20.0,
    "expansion_percentile": 60.0,
    "squeeze_bb_percentile": 25.0,
    "squeeze_ma_percentile": 30.0,
    "high_volatility_bb_percentile": 70.0,
}

LIQUIDITY_THRESHOLDS_TRY = {
    "low_average_turnover": 25_000_000.0,
    "high_average_turnover": 100_000_000.0,
    "low_free_float_pct": 10.0,
}


def _finite(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _close_by_day(data: pd.DataFrame) -> pd.Series:
    values = pd.Series(data["Close"].to_numpy(dtype=float), index=pd.to_datetime(data.index))
    if values.index.tz is not None:
        values.index = values.index.tz_localize(None)
    values.index = values.index.normalize()
    return values.groupby(level=0).last().dropna()


def relative_strength_context(
    stock_data: pd.DataFrame,
    benchmark_data: pd.DataFrame | None,
    benchmark_symbol: str,
) -> dict[str, Any]:
    unavailable = {
        "available": False,
        "benchmark": benchmark_symbol or "—",
        "state": "Benchmark verisi yok",
        "tone": "warning",
        "periods": {},
    }
    if benchmark_data is None or benchmark_data.empty:
        return unavailable
    aligned = pd.concat(
        [_close_by_day(stock_data).rename("stock"), _close_by_day(benchmark_data).rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 22 or (aligned <= 0).any().any():
        return unavailable

    ratio = aligned["stock"] / aligned["benchmark"]
    ratio_ema20 = ratio.ewm(span=20, adjust=False, min_periods=20).mean()
    slope_5_pct = (ratio.iloc[-1] / ratio.iloc[-6] - 1.0) * 100 if len(ratio) >= 6 else math.nan
    above_average = bool(ratio.iloc[-1] > ratio_ema20.iloc[-1])
    if above_average and slope_5_pct > 0:
        state, tone = "Göreceli güçleniyor", "positive"
    elif not above_average and slope_5_pct < 0:
        state, tone = "Göreceli zayıflıyor", "negative"
    else:
        state, tone = "Göreceli güç karışık", "warning"

    periods: dict[str, dict[str, float]] = {}
    for bars in (1, 5, 20, 60, 252):
        if len(aligned) <= bars:
            continue
        stock_return = (aligned["stock"].iloc[-1] / aligned["stock"].iloc[-bars - 1] - 1.0) * 100
        benchmark_return = (aligned["benchmark"].iloc[-1] / aligned["benchmark"].iloc[-bars - 1] - 1.0) * 100
        periods[str(bars)] = {
            "stock_return_pct": float(stock_return),
            "benchmark_return_pct": float(benchmark_return),
            "excess_return_pct": float(stock_return - benchmark_return),
        }
    return {
        "available": True,
        "benchmark": benchmark_symbol,
        "state": state,
        "tone": tone,
        "ratio": float(ratio.iloc[-1]),
        "ratio_ema20": float(ratio_ema20.iloc[-1]),
        "ratio_slope_5_pct": float(slope_5_pct),
        "periods": periods,
        "method": "Aynı işlem günlerine hizalanmış hisse/endeks kapanış oranı; temettü toplam getirisi değildir.",
    }


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    change = series.diff()
    gain = change.clip(lower=0.0)
    loss = -change.clip(upper=0.0)
    average_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    average_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = average_gain / average_loss.replace(0.0, np.nan)
    result = 100 - 100 / (1 + rs)
    both_zero = (average_gain == 0) & (average_loss == 0)
    result = result.where(~both_zero, 50.0)
    result = result.where(~((average_loss == 0) & (average_gain > 0)), 100.0)
    return result.where(~((average_gain == 0) & (average_loss > 0)), 0.0)


def _resample_ohlcv(data: pd.DataFrame, rule: str) -> pd.DataFrame:
    result = (
        data[["Open", "High", "Low", "Close", "Volume"]]
        .resample(rule)
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Open", "High", "Low", "Close"])
    )
    if result.empty:
        return result
    last_date = pd.Timestamp(data.index[-1])
    if rule == "W-FRI" and last_date.weekday() != 4 or rule == "ME" and (last_date + pd.offsets.BDay(1)).month == last_date.month:
        result = result.iloc[:-1]
    return result


def _timeframe_snapshot(data: pd.DataFrame, label: str, fast: int, slow: int) -> dict[str, Any]:
    close = data["Close"].dropna()
    if len(close) < max(slow + 2, 16):
        return {"label": label, "available": False, "state": "Yetersiz bar", "tone": "warning", "bars": len(close)}
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    rsi_value = _finite(_rsi(close).iloc[-1])
    price = float(close.iloc[-1])
    fast_value = float(ema_fast.iloc[-1])
    slow_value = float(ema_slow.iloc[-1])
    fast_rising = bool(ema_fast.iloc[-1] > ema_fast.iloc[-2])
    bullish = price > fast_value and fast_value > slow_value and fast_rising and rsi_value >= 50
    bearish = price < fast_value and fast_value < slow_value and not fast_rising and rsi_value < 50
    state = "Yukarı eğilim" if bullish else "Aşağı eğilim" if bearish else "Karışık / geçiş"
    tone = "positive" if bullish else "negative" if bearish else "warning"
    return {
        "label": label,
        "available": True,
        "state": state,
        "tone": tone,
        "bars": len(close),
        "close": price,
        "ema_fast": fast_value,
        "ema_slow": slow_value,
        "ema_lengths": [fast, slow],
        "ema_fast_rising": fast_rising,
        "rsi14": rsi_value,
    }


def multi_timeframe_context(data: pd.DataFrame) -> dict[str, Any]:
    frames = [
        _timeframe_snapshot(data, "Günlük", 20, 50),
        _timeframe_snapshot(_resample_ohlcv(data, "W-FRI"), "Haftalık", 20, 50),
        _timeframe_snapshot(_resample_ohlcv(data, "ME"), "Aylık", 10, 20),
    ]
    available = [item for item in frames if item["available"]]
    states = {item["state"] for item in available}
    if available and states == {"Yukarı eğilim"}:
        state, tone = "Zaman dilimleri yukarı uyumlu", "positive"
    elif available and states == {"Aşağı eğilim"}:
        state, tone = "Zaman dilimleri aşağı uyumlu", "negative"
    else:
        state, tone = "Zaman dilimleri karışık", "warning"
    return {
        "state": state,
        "tone": tone,
        "frames": frames,
        "method": "Günlük OHLCV serisi yeniden örneklenir; açık günlük mum ile tamamlanmamış hafta/ay dışarıda bırakılır.",
    }


def liquidity_context(data: pd.DataFrame, market: str, free_float_pct: float | None = None) -> dict[str, Any]:
    turnover = (data["Close"] * data["Volume"]).replace([np.inf, -np.inf], np.nan)
    average_20 = _finite(turnover.tail(20).mean())
    median_60 = _finite(turnover.tail(60).median())
    current = _finite(turnover.iloc[-1])
    zero_volume_pct = float((data["Volume"].tail(60) <= 0).mean() * 100)
    free_float = _finite(free_float_pct)
    if market.upper() == "BIST":
        if average_20 < LIQUIDITY_THRESHOLDS_TRY["low_average_turnover"]:
            state, tone = "Düşük TL likiditesi", "negative"
        elif average_20 < LIQUIDITY_THRESHOLDS_TRY["high_average_turnover"]:
            state, tone = "Orta TL likiditesi", "warning"
        else:
            state, tone = "Yüksek TL likiditesi", "positive"
        warnings = []
        if math.isfinite(free_float) and free_float < LIQUIDITY_THRESHOLDS_TRY["low_free_float_pct"]:
            warnings.append("Halka açıklık %10 altında")
            tone = "negative"
        if zero_volume_pct > 0:
            warnings.append(f"Son 60 barda sıfır hacim %{zero_volume_pct:.1f}")
    else:
        state, tone = "TL eşiği uygulanmadı", "neutral"
        warnings = ["Likidite eşikleri yalnız BIST için tanımlı"]
    return {
        "state": state,
        "tone": tone,
        "current_turnover": current,
        "average_turnover_20": average_20,
        "median_turnover_60": median_60,
        "free_float_pct": free_float if math.isfinite(free_float) else None,
        "zero_volume_pct_60": zero_volume_pct,
        "warnings": warnings,
        "method": "TL işlem hacmi = kapanış × lot hacmi. Eşikler sezgiseldir; manipülasyon tespiti değildir.",
    }


def risk_reference_context(
    data: pd.DataFrame,
    account_size: float = 0.0,
    risk_pct: float = 1.0,
    atr_multiple: float = 1.5,
) -> dict[str, Any]:
    price = _finite(data["Close"].iloc[-1])
    atr = _finite(data["ATR"].iloc[-1]) if "ATR" in data else math.nan
    if not math.isfinite(price) or not math.isfinite(atr) or atr <= 0 or atr_multiple <= 0:
        return {"available": False, "state": "ATR risk referansı hesaplanamadı", "tone": "warning"}
    distance = atr * atr_multiple
    risk_amount = account_size * risk_pct / 100 if account_size > 0 and risk_pct > 0 else 0.0
    quantity = math.floor(risk_amount / distance) if risk_amount > 0 else None
    return {
        "available": True,
        "state": f"{atr_multiple:.1f} ATR volatilite mesafesi",
        "tone": "neutral",
        "entry_reference": price,
        "atr": atr,
        "atr_pct": atr / price * 100,
        "atr_multiple": atr_multiple,
        "distance": distance,
        "long_reference_stop": max(price - distance, 0.0),
        "long_reference_1r": price + distance,
        "long_reference_2r": price + 2 * distance,
        "short_reference_stop": price + distance,
        "short_reference_1r": max(price - distance, 0.0),
        "short_reference_2r": max(price - 2 * distance, 0.0),
        "account_size": account_size if account_size > 0 else None,
        "risk_pct": risk_pct if risk_amount > 0 else None,
        "risk_amount": risk_amount if risk_amount > 0 else None,
        "reference_quantity": quantity,
        "method": "Mevcut kapanıştan mekanik ATR senaryosu; destek/direnç veya emir önerisi değildir.",
    }


def build_decision_context(
    data: pd.DataFrame,
    benchmark_data: pd.DataFrame | None,
    benchmark_symbol: str,
    market: str,
    free_float_pct: float | None = None,
    account_size: float = 0.0,
    risk_pct: float = 1.0,
    atr_multiple: float = 1.5,
    bar_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mtf_data = data.iloc[:-1] if bar_state and bar_state.get("is_live") and len(data) > 1 else data
    return {
        "relative_strength": relative_strength_context(data, benchmark_data, benchmark_symbol),
        "multi_timeframe": multi_timeframe_context(mtf_data),
        "liquidity": liquidity_context(data, market, free_float_pct),
        "risk_reference": risk_reference_context(data, account_size, risk_pct, atr_multiple),
        "methodology": {
            "regime_thresholds": REGIME_THRESHOLDS,
            "liquidity_thresholds_try": LIQUIDITY_THRESHOLDS_TRY,
            "validation": "Eşikler sezgiseldir ve henüz istatistiksel olarak kalibre edilmiş tahmin modeli değildir.",
        },
    }
