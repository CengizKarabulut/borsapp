"""TradingView All Candlestick Patterns mantığının pandas uyarlaması.

Formasyonlar kapanmış mumlarda, SMA50/SMA200 trend filtresiyle sınıflandırılır.
Tek başına sinyal değildir; konum, hacim ve trend bağlamıyla birlikte okunur.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def detect_candlestick_patterns(data: pd.DataFrame) -> dict[str, pd.Series]:
    open_ = data["Open"].astype(float)
    high = data["High"].astype(float)
    low = data["Low"].astype(float)
    close = data["Close"].astype(float)
    index = data.index

    body_high = pd.concat([open_, close], axis=1).max(axis=1)
    body_low = pd.concat([open_, close], axis=1).min(axis=1)
    body = body_high - body_low
    body_avg = body.ewm(span=14, adjust=False, min_periods=14).mean()
    small = body < body_avg
    long = body > body_avg
    upper = high - body_high
    lower = body_low - low
    range_ = high - low
    white = close > open_
    black = close < open_
    doji_body = (range_ > 0) & (body <= range_ * 0.05)
    shadow_equal = (
        upper.eq(lower)
        | ((upper - lower).abs() / lower.replace(0, np.nan) * 100 < 100)
        & ((lower - upper).abs() / upper.replace(0, np.nan) * 100 < 100)
    )
    doji = doji_body & shadow_equal
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    uptrend = (close > sma50) & (sma50 > sma200)
    downtrend = (close < sma50) & (sma50 < sma200)
    body_mid_previous = (body / 2 + body_low).shift(1)

    names: list[list[str]] = [[] for _ in range(len(data))]
    codes: list[list[str]] = [[] for _ in range(len(data))]
    tones: list[list[str]] = [[] for _ in range(len(data))]

    def add(mask: pd.Series, name: str, code: str, tone: str) -> None:
        valid = mask.fillna(False).to_numpy(dtype=bool)
        for position in np.flatnonzero(valid):
            names[position].append(name)
            codes[position].append(code)
            tones[position].append(tone)

    # Tek mum.
    add(doji, "Doji", "D", "neutral")
    add(doji_body & (upper <= body), "Dragonfly Doji", "DD", "bullish")
    add(doji_body & (lower <= body), "Gravestone Doji", "GD", "bearish")
    add(downtrend & small & (lower > 2 * body) & (upper <= body), "Hammer", "H", "bullish")
    add(uptrend & small & (lower > 2 * body) & (upper <= body), "Hanging Man", "HM", "bearish")
    add(downtrend & small & (upper > 2 * body) & (lower <= body), "Inverted Hammer", "IH", "bullish")
    add(uptrend & small & (upper > 2 * body) & (lower <= body), "Shooting Star", "SS", "bearish")
    add(lower > range_ * 0.75, "Long Lower Shadow", "LLS", "bullish")
    add(upper > range_ * 0.75, "Long Upper Shadow", "LUS", "bearish")
    marubozu = long & (upper <= body * 0.05) & (lower <= body * 0.05)
    add(marubozu & white, "Marubozu White", "MW", "bullish")
    add(marubozu & black, "Marubozu Black", "MB", "bearish")
    spinning = (lower >= range_ * 0.34) & (upper >= range_ * 0.34) & ~doji_body
    add(spinning & white, "Spinning Top White", "STW", "neutral")
    add(spinning & black, "Spinning Top Black", "STB", "neutral")

    # İki mum.
    bull_engulf = downtrend & white & long & black.shift(1) & small.shift(1) & (close >= open_.shift(1)) & (open_ <= close.shift(1))
    bear_engulf = uptrend & black & long & white.shift(1) & small.shift(1) & (close <= open_.shift(1)) & (open_ >= close.shift(1))
    add(bull_engulf, "Engulfing Bullish", "BE", "bullish")
    add(bear_engulf, "Engulfing Bearish", "BE", "bearish")
    inside_previous = (high <= body_high.shift(1)) & (low >= body_low.shift(1))
    add(downtrend.shift(1) & long.shift(1) & black.shift(1) & white & small & inside_previous, "Harami Bullish", "BH", "bullish")
    add(uptrend.shift(1) & long.shift(1) & white.shift(1) & black & small & inside_previous, "Harami Bearish", "BH", "bearish")
    add(downtrend.shift(1) & long.shift(1) & black.shift(1) & doji_body & inside_previous, "Harami Cross Bullish", "HC", "bullish")
    add(uptrend.shift(1) & long.shift(1) & white.shift(1) & doji_body & inside_previous, "Harami Cross Bearish", "HC", "bearish")
    add(downtrend.shift(1) & black.shift(1) & long.shift(1) & white & (open_ < close.shift(1)) & (close > body_mid_previous) & (close < open_.shift(1)), "Piercing", "P", "bullish")
    add(uptrend.shift(1) & white.shift(1) & long.shift(1) & black & (open_ >= high.shift(1)) & (close < body_mid_previous) & (close > open_.shift(1)), "Dark Cloud Cover", "DCC", "bearish")
    tolerance = body_avg * 0.05
    add(downtrend.shift(1) & black.shift(1) & white & long.shift(1) & ((low - low.shift(1)).abs() <= tolerance), "Tweezer Bottom", "TB", "bullish")
    add(uptrend.shift(1) & white.shift(1) & black & long.shift(1) & ((high - high.shift(1)).abs() <= tolerance), "Tweezer Top", "TT", "bearish")
    add(uptrend.shift(1) & (low > high.shift(1)), "Rising Window", "RW", "bullish")
    add(downtrend.shift(1) & (high < low.shift(1)), "Falling Window", "FW", "bearish")

    # Üç mum ve güçlü devam/dönüş kalıpları.
    morning = downtrend.shift(2) & black.shift(2) & long.shift(2) & small.shift(1) & white & long & (close > (body_low.shift(2) + body.shift(2) / 2))
    evening = uptrend.shift(2) & white.shift(2) & long.shift(2) & small.shift(1) & black & long & (close < (body_low.shift(2) + body.shift(2) / 2))
    add(morning, "Morning Star", "MS", "bullish")
    add(evening, "Evening Star", "ES", "bearish")
    add(morning & doji_body.shift(1), "Morning Doji Star", "MDS", "bullish")
    add(evening & doji_body.shift(1), "Evening Doji Star", "EDS", "bearish")

    small_upper = range_ * 0.05 > upper
    small_lower = range_ * 0.05 > lower
    soldiers = (
        long & long.shift(1) & long.shift(2) & white & white.shift(1) & white.shift(2)
        & (close > close.shift(1)) & (close.shift(1) > close.shift(2))
        & (open_ < close.shift(1)) & (open_ > open_.shift(1))
        & (open_.shift(1) < close.shift(2)) & (open_.shift(1) > open_.shift(2))
        & small_upper & small_upper.shift(1) & small_upper.shift(2)
    )
    crows = (
        long & long.shift(1) & long.shift(2) & black & black.shift(1) & black.shift(2)
        & (close < close.shift(1)) & (close.shift(1) < close.shift(2))
        & (open_ > close.shift(1)) & (open_ < open_.shift(1))
        & (open_.shift(1) > close.shift(2)) & (open_.shift(1) < open_.shift(2))
        & small_lower & small_lower.shift(1) & small_lower.shift(2)
    )
    add(soldiers, "Three White Soldiers", "3WS", "bullish")
    add(crows, "Three Black Crows", "3BC", "bearish")

    # Grafiği boğmamak için aynı bardaki etiketler tek rozet içinde birleştirilir.
    bull_labels, bear_labels, neutral_labels = [], [], []
    bull_names, bear_names, neutral_names = [], [], []
    for item_names, item_codes, item_tones in zip(names, codes, tones):
        bull_labels.append("/".join(code for code, tone in zip(item_codes, item_tones) if tone == "bullish"))
        bear_labels.append("/".join(code for code, tone in zip(item_codes, item_tones) if tone == "bearish"))
        neutral_labels.append("/".join(code for code, tone in zip(item_codes, item_tones) if tone == "neutral"))
        bull_names.append("; ".join(name for name, tone in zip(item_names, item_tones) if tone == "bullish"))
        bear_names.append("; ".join(name for name, tone in zip(item_names, item_tones) if tone == "bearish"))
        neutral_names.append("; ".join(name for name, tone in zip(item_names, item_tones) if tone == "neutral"))

    true_range = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr30 = true_range.ewm(alpha=1 / 30, adjust=False, min_periods=30).mean()
    return {
        "CANDLE_BULL_Y": (low - atr30 * 0.6).where(pd.Series(bull_labels, index=index).ne("")),
        "CANDLE_BEAR_Y": (high + atr30 * 0.6).where(pd.Series(bear_labels, index=index).ne("")),
        "CANDLE_NEUTRAL_Y": (low - atr30 * 0.35).where(pd.Series(neutral_labels, index=index).ne("")),
        "CANDLE_BULL_LABEL": pd.Series(bull_labels, index=index, dtype="object"),
        "CANDLE_BEAR_LABEL": pd.Series(bear_labels, index=index, dtype="object"),
        "CANDLE_NEUTRAL_LABEL": pd.Series(neutral_labels, index=index, dtype="object"),
        "CANDLE_BULL_NAMES": pd.Series(bull_names, index=index, dtype="object"),
        "CANDLE_BEAR_NAMES": pd.Series(bear_names, index=index, dtype="object"),
        "CANDLE_NEUTRAL_NAMES": pd.Series(neutral_names, index=index, dtype="object"),
    }
