"""Pine-faithful indicator calculations used by the research chart.

The implementations mirror the user-supplied TradingView scripts and defaults:
RSI(14) with Wilder RMA, RSI SMA(14) smoothing and regular divergence (5/5,
5-60); SMI(10,3,3); AlphaTrend(14,1) volume-aware MFI branch;
MACD(12,26,9 EMA); OBV; ATR(14 RMA); and price Bollinger Bands (20,2).

AlphaTrend BUY/SELL conditions are calculated exactly but remain hidden by the
report renderer because this project deliberately does not publish automatic
AL/SAT labels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DivergencePoint:
    kind: str
    index: object
    rsi: float
    price: float
    previous_index: object | None = None
    previous_rsi: float | None = None
    previous_price: float | None = None


def _series(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").astype(float)


def tv_ema(values: pd.Series, length: int) -> pd.Series:
    """TradingView-style recursive EMA."""
    source = _series(values)
    return source.ewm(span=length, adjust=False, min_periods=1).mean()


def tv_rma(values: pd.Series, length: int) -> pd.Series:
    """Wilder RMA seeded with the first complete length-value SMA."""
    source = _series(values)
    out = pd.Series(np.nan, index=source.index, dtype=float)
    if length <= 0:
        return out
    arr = source.to_numpy(dtype=float)
    if len(arr) < length:
        return out
    for end in range(length - 1, len(arr)):
        window = arr[end - length + 1 : end + 1]
        if np.isfinite(window).all():
            out.iloc[end] = float(window.mean())
            start = end + 1
            break
    else:
        return out
    alpha = 1.0 / length
    prev = float(out.iloc[start - 1])
    for i in range(start, len(arr)):
        value = arr[i]
        if not np.isfinite(value):
            out.iloc[i] = prev
            continue
        prev = alpha * value + (1.0 - alpha) * prev
        out.iloc[i] = prev
    return out


def true_range(frame: pd.DataFrame) -> pd.Series:
    high = _series(frame["High"])
    low = _series(frame["Low"])
    close = _series(frame["Close"])
    previous = close.shift(1)
    parts = pd.concat(
        [
            high - low,
            (high - previous).abs(),
            (low - previous).abs(),
        ],
        axis=1,
    )
    result = parts.max(axis=1, skipna=True)
    if not result.empty:
        result.iloc[0] = high.iloc[0] - low.iloc[0]
    return result


def rsi(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    """User-supplied TradingView RSI formula: Wilder RMA of gains/losses."""
    close = _series(frame["Close"])
    change = close.diff()
    up = tv_rma(change.clip(lower=0.0), length)
    down = tv_rma(-change.clip(upper=0.0), length)
    ratio = up / down.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + ratio))
    result = result.where(down != 0.0, 100.0)
    result = result.where(up != 0.0, 0.0)
    both_zero = (up == 0.0) & (down == 0.0)
    return result.where(~both_zero, 0.0)


def _pivot_flags(values: pd.Series, left: int, right: int, mode: str) -> pd.Series:
    source = _series(values)
    flags = pd.Series(False, index=source.index)
    arr = source.to_numpy(dtype=float)
    for i in range(left, len(arr) - right):
        window = arr[i - left : i + right + 1]
        center = arr[i]
        if not np.isfinite(center) or not np.isfinite(window).all():
            continue
        if mode == "low":
            condition = center <= np.min(window) and int(np.sum(window == center)) == 1
        else:
            condition = center >= np.max(window) and int(np.sum(window == center)) == 1
        if condition:
            flags.iloc[i] = True
    return flags


def rsi_divergences(
    frame: pd.DataFrame,
    rsi_values: pd.Series | None = None,
    *,
    left: int = 5,
    right: int = 5,
    range_lower: int = 5,
    range_upper: int = 60,
    include_hidden: bool = False,
) -> tuple[DivergencePoint, ...]:
    """Mirror the supplied TradingView RSI divergence pivot/valuewhen logic."""
    oscillator = rsi(frame) if rsi_values is None else _series(rsi_values)
    lows = _series(frame["Low"])
    highs = _series(frame["High"])
    low_flags = _pivot_flags(oscillator, left, right, "low")
    high_flags = _pivot_flags(oscillator, left, right, "high")
    points: list[DivergencePoint] = []

    previous_low: int | None = None
    previous_high: int | None = None
    low_indices = [i for i, flag in enumerate(low_flags.to_numpy()) if flag]
    high_indices = [i for i, flag in enumerate(high_flags.to_numpy()) if flag]

    for i in low_indices:
        if previous_low is not None:
            distance = i - previous_low
            if range_lower <= distance <= range_upper:
                osc_now = float(oscillator.iloc[i])
                osc_prev = float(oscillator.iloc[previous_low])
                price_now = float(lows.iloc[i])
                price_prev = float(lows.iloc[previous_low])
                if price_now < price_prev and osc_now > osc_prev:
                    points.append(
                        DivergencePoint(
                            "Regular Bullish",
                            oscillator.index[i],
                            osc_now,
                            price_now,
                            oscillator.index[previous_low],
                            osc_prev,
                            price_prev,
                        )
                    )
                elif include_hidden and price_now > price_prev and osc_now < osc_prev:
                    points.append(
                        DivergencePoint(
                            "Hidden Bullish",
                            oscillator.index[i],
                            osc_now,
                            price_now,
                            oscillator.index[previous_low],
                            osc_prev,
                            price_prev,
                        )
                    )
        previous_low = i

    for i in high_indices:
        if previous_high is not None:
            distance = i - previous_high
            if range_lower <= distance <= range_upper:
                osc_now = float(oscillator.iloc[i])
                osc_prev = float(oscillator.iloc[previous_high])
                price_now = float(highs.iloc[i])
                price_prev = float(highs.iloc[previous_high])
                if price_now > price_prev and osc_now < osc_prev:
                    points.append(
                        DivergencePoint(
                            "Regular Bearish",
                            oscillator.index[i],
                            osc_now,
                            price_now,
                            oscillator.index[previous_high],
                            osc_prev,
                            price_prev,
                        )
                    )
                elif include_hidden and price_now < price_prev and osc_now > osc_prev:
                    points.append(
                        DivergencePoint(
                            "Hidden Bearish",
                            oscillator.index[i],
                            osc_now,
                            price_now,
                            oscillator.index[previous_high],
                            osc_prev,
                            price_prev,
                        )
                    )
        previous_high = i

    return tuple(sorted(points, key=lambda point: point.index))


def smi(
    frame: pd.DataFrame,
    length_k: int = 10,
    length_d: int = 3,
    length_ema: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """User-supplied TradingView SMI 10/3/3 double-EMA formula."""
    high = _series(frame["High"])
    low = _series(frame["Low"])
    close = _series(frame["Close"])
    highest = high.rolling(length_k, min_periods=length_k).max()
    lowest = low.rolling(length_k, min_periods=length_k).min()
    high_low_range = highest - lowest
    relative = close - (highest + lowest) / 2.0
    numerator = tv_ema(tv_ema(relative, length_d), length_d)
    denominator = tv_ema(tv_ema(high_low_range, length_d), length_d)
    value = 200.0 * numerator / denominator.replace(0.0, np.nan)
    signal = tv_ema(value, length_ema)
    return value, signal


def macd(
    frame: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal_length: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    close = _series(frame["Close"])
    fast_ma = tv_ema(close, fast)
    slow_ma = tv_ema(close, slow)
    line = fast_ma - slow_ma
    signal = tv_ema(line, signal_length)
    return line, signal, line - signal


def obv(frame: pd.DataFrame) -> pd.Series:
    close = _series(frame["Close"])
    volume = _series(frame["Volume"]).fillna(0.0)
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume).cumsum()


def atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    return tv_rma(true_range(frame), length)


def bollinger(
    frame: pd.DataFrame,
    length: int = 20,
    mult: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """TradingView default price Bollinger Bands: SMA20 ± 2 population stdev."""
    close = _series(frame["Close"])
    basis = close.rolling(length, min_periods=length).mean()
    deviation = close.rolling(length, min_periods=length).std(ddof=0) * mult
    return basis, basis + deviation, basis - deviation


def money_flow_index(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    high = _series(frame["High"])
    low = _series(frame["Low"])
    close = _series(frame["Close"])
    volume = _series(frame["Volume"]).fillna(0.0)
    typical = (high + low + close) / 3.0
    flow = typical * volume
    delta = typical.diff()
    positive = flow.where(delta > 0.0, 0.0)
    negative = flow.where(delta < 0.0, 0.0)
    pos_sum = positive.rolling(length, min_periods=length).sum()
    neg_sum = negative.rolling(length, min_periods=length).sum()
    ratio = pos_sum / neg_sum.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + ratio)
    result = result.where(neg_sum != 0.0, 100.0)
    return result.where(pos_sum != 0.0, 0.0)


def alpha_trend(
    frame: pd.DataFrame,
    period: int = 14,
    multiplier: float = 1.0,
    no_volume_data: bool = False,
) -> pd.DataFrame:
    """KivancOzbilgic AlphaTrend formula with default volume-aware MFI branch."""
    tr = true_range(frame)
    atr_sma = tr.rolling(period, min_periods=period).mean()
    low = _series(frame["Low"])
    high = _series(frame["High"])
    up_t = low - atr_sma * multiplier
    down_t = high + atr_sma * multiplier
    condition = rsi(frame, period) >= 50.0 if no_volume_data else money_flow_index(frame, period) >= 50.0

    values = pd.Series(np.nan, index=frame.index, dtype=float)
    previous = 0.0
    for i in range(len(frame)):
        if not np.isfinite(up_t.iloc[i]) or not np.isfinite(down_t.iloc[i]) or pd.isna(condition.iloc[i]):
            continue
        if bool(condition.iloc[i]):
            current = previous if up_t.iloc[i] < previous else float(up_t.iloc[i])
        else:
            current = previous if down_t.iloc[i] > previous else float(down_t.iloc[i])
        values.iloc[i] = current
        previous = current

    lag2 = values.shift(2)
    buy = (values > lag2) & (values.shift(1) <= lag2.shift(1))
    sell = (values < lag2) & (values.shift(1) >= lag2.shift(1))
    return pd.DataFrame(
        {
            "AlphaTrend": values,
            "AlphaTrendLag2": lag2,
            "AlphaTrendBuy": buy,
            "AlphaTrendSell": sell,
        }
    )


def moving_averages(
    frame: pd.DataFrame,
    periods: tuple[int, ...] = (5, 8, 13, 21, 34, 55, 89, 144, 233),
) -> pd.DataFrame:
    close = _series(frame["Close"])
    return pd.DataFrame(
        {f"MA{period}": close.rolling(period, min_periods=period).mean() for period in periods},
        index=frame.index,
    )


def build_indicator_frame(
    frame: pd.DataFrame,
    *,
    include_hidden_divergence: bool = False,
) -> tuple[pd.DataFrame, tuple[DivergencePoint, ...]]:
    out = frame.copy()
    out["RSI14"] = rsi(out, 14)
    # The supplied standard RSI has maTypeInput="SMA" and maLengthInput=14.
    out["RSI_MA14"] = out["RSI14"].rolling(14, min_periods=14).mean()
    divergences = rsi_divergences(
        out,
        out["RSI14"],
        left=5,
        right=5,
        range_lower=5,
        range_upper=60,
        include_hidden=include_hidden_divergence,
    )
    out["SMI"], out["SMI_SIGNAL"] = smi(out, 10, 3, 3)
    out["MACD"], out["MACD_SIGNAL"], out["MACD_HIST"] = macd(out, 12, 26, 9)
    out["OBV"] = obv(out)
    out["ATR14"] = atr(out, 14)
    out["BB_MID"], out["BB_UPPER"], out["BB_LOWER"] = bollinger(out, 20, 2.0)
    out = out.join(alpha_trend(out, 14, 1.0, False))
    return out, divergences
