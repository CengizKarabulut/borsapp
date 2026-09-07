from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np
import pandas as pd

# Trend kalitesinde öne çıkarılan Fibonacci üçlüsü; grafikle aynı olmalıdır.
KEY_EMA_PERIODS = (21, 55, 233)


def _number(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _fmt(value: Any, digits: int = 2) -> str:
    number = _number(value)
    return "—" if not math.isfinite(number) else f"{number:,.{digits}f}"


def _change(series: pd.Series, bars: int) -> float:
    clean = series.dropna()
    return float(clean.iloc[-1] - clean.iloc[-bars - 1]) if len(clean) > bars else math.nan


def _slope(series: pd.Series, bars: int = 5) -> float:
    clean = series.dropna().tail(bars).to_numpy(dtype=float)
    if len(clean) < bars:
        return math.nan
    return float(np.polyfit(np.arange(bars, dtype=float), clean, 1)[0])


def _percentile(series: pd.Series, lookback: int = 60) -> float:
    clean = series.dropna().tail(lookback)
    if clean.empty:
        return math.nan
    return float((clean <= clean.iloc[-1]).mean() * 100)


def _streak(values: pd.Series, upward: bool) -> int:
    differences = values.diff().dropna().to_numpy(dtype=float)
    count = 0
    for value in reversed(differences):
        if (value > 0) == upward and value != 0:
            count += 1
        else:
            break
    return count


def price_action_context(data: pd.DataFrame) -> dict[str, Any]:
    row = data.iloc[-1]
    previous = data.iloc[-2]
    bar_range = max(_number(row["High"]) - _number(row["Low"]), 0.0)
    body = abs(_number(row["Close"]) - _number(row["Open"]))
    upper_wick = max(_number(row["High"]) - max(_number(row["Open"]), _number(row["Close"])), 0.0)
    lower_wick = max(min(_number(row["Open"]), _number(row["Close"])) - _number(row["Low"]), 0.0)
    close_location = (_number(row["Close"]) - _number(row["Low"])) / bar_range * 100 if bar_range else 50.0
    body_pct = body / bar_range * 100 if bar_range else 0.0
    gap_pct = (_number(row["Open"]) / _number(previous["Close"]) - 1) * 100 if _number(previous["Close"]) else math.nan
    ranges = data["High"] - data["Low"]
    range_percentile = _percentile(ranges, 60)
    atr = _number(row.get("ATR"))
    range_atr = bar_range / atr if atr > 0 else math.nan
    high_20 = _number(data["High"].tail(20).max())
    low_20 = _number(data["Low"].tail(20).min())
    range_position_20 = (_number(row["Close"]) - low_20) / (high_20 - low_20) * 100 if high_20 > low_20 else 50.0
    inside = bool(row["High"] < previous["High"] and row["Low"] > previous["Low"])
    outside = bool(row["High"] > previous["High"] and row["Low"] < previous["Low"])
    nr4 = bool(len(ranges.dropna()) >= 4 and bar_range <= ranges.dropna().tail(4).min())
    nr7 = bool(len(ranges.dropna()) >= 7 and bar_range <= ranges.dropna().tail(7).min())
    patterns: list[str] = []
    candle_patterns = [
        str(row.get(column, ""))
        for column in ("CANDLE_BULL_NAMES", "CANDLE_BEAR_NAMES", "CANDLE_NEUTRAL_NAMES")
        if str(row.get(column, "")) not in {"", "nan"}
    ]
    patterns.extend(candle_patterns)
    if inside:
        patterns.append("Inside bar")
    if outside:
        patterns.append("Outside bar")
    if nr7:
        patterns.append("NR7")
    elif nr4:
        patterns.append("NR4")
    if range_percentile >= 90:
        patterns.append("Geniş aralıklı bar")
    if close_location >= 80 and body_pct >= 50:
        state, tone = "Güçlü alıcı kapanışı", "positive"
        meaning = "Kapanış gün içi tepeye yakın; alıcılar seans sonuna kadar kontrolü korudu."
    elif close_location <= 20 and body_pct >= 50:
        state, tone = "Güçlü satıcı kapanışı", "negative"
        meaning = "Kapanış gün içi dibe yakın; satış baskısı seans sonuna kadar sürdü."
    elif upper_wick >= max(body * 1.5, bar_range * 0.25) and close_location < 65:
        state, tone = "Üst fitil / arz tepkisi", "warning"
        meaning = "Gün içi yukarı hareketin bir bölümü geri verildi; üst bölgede arz tepkisi oluştu."
    elif lower_wick >= max(body * 1.5, bar_range * 0.25) and close_location > 35:
        state, tone = "Alt fitil / talep tepkisi", "warning"
        meaning = "Gün içi aşağı hareketin bir bölümü geri alındı; alt bölgede talep tepkisi oluştu."
    else:
        state, tone = "Dengeli bar", "neutral"
        meaning = "Kapanış bar aralığının orta bölümünde; tek bar belirgin kontrol göstermiyor."
    return {
        "state": state,
        "tone": tone,
        "meaning": meaning,
        "close_location_pct": close_location,
        "body_pct": body_pct,
        "upper_wick_pct": upper_wick / bar_range * 100 if bar_range else 0.0,
        "lower_wick_pct": lower_wick / bar_range * 100 if bar_range else 0.0,
        "upper_wick_body_ratio": upper_wick / body if body else math.nan,
        "lower_wick_body_ratio": lower_wick / body if body else math.nan,
        "gap_pct": gap_pct,
        "range_percentile_60": range_percentile,
        "range_atr": range_atr,
        "range_position_20_pct": range_position_20,
        "higher_close_streak": _streak(data["Close"], True),
        "lower_close_streak": _streak(data["Close"], False),
        "patterns": patterns,
        "summary": (
            f"{state}; kapanış bar aralığının %{close_location:.0f} seviyesinde, gövde %{body_pct:.0f}, "
            f"range son 60 barın %{range_percentile:.0f} yüzdeliğinde ({_fmt(range_atr)} ATR). {meaning}"
            + (f" Teyitli mum kalıbı: {'; '.join(candle_patterns)}." if candle_patterns else "")
        ),
        "method": "TradingView All Patterns morfolojisi ve SMA50/SMA200 trend bağlamı; mum formasyonu tek başına yön teyidi değildir.",
    }


def _ema_slope_atr(data: pd.DataFrame, period: int, bars: int = 5) -> float:
    column = f"EMA_{period}"
    if column not in data or len(data) <= bars:
        return math.nan
    atr = _number(data["ATR"].iloc[-1])
    return (_number(data[column].iloc[-1]) - _number(data[column].iloc[-bars - 1])) / atr if atr > 0 else math.nan


def trend_quality_context(data: pd.DataFrame, ma_periods: list[int]) -> dict[str, Any]:
    row = data.iloc[-1]
    ordered = [period for period in ma_periods if f"EMA_{period}" in data and math.isfinite(_number(row[f"EMA_{period}"]))]
    values = [_number(row[f"EMA_{period}"]) for period in ordered]
    bullish_pairs = sum(left > right for left, right in itertools.pairwise(values))
    bearish_pairs = sum(left < right for left, right in itertools.pairwise(values))
    pair_total = max(len(values) - 1, 0)
    if pair_total and bullish_pairs == pair_total:
        alignment, tone = "Tam bullish EMA dizilimi", "positive"
    elif pair_total and bearish_pairs == pair_total:
        alignment, tone = "Tam bearish EMA dizilimi", "negative"
    elif pair_total and bullish_pairs / pair_total >= 0.75:
        alignment, tone = "Bullish dizilim büyük ölçüde oluşmuş", "positive"
    elif pair_total and bearish_pairs / pair_total >= 0.75:
        alignment, tone = "Bearish dizilim büyük ölçüde oluşmuş", "negative"
    else:
        alignment, tone = "EMA dizilimi parçalı", "warning"
    highlighted = [period for period in KEY_EMA_PERIODS if f"EMA_{period}" in data] or ma_periods[-3:]
    slopes = {str(period): _ema_slope_atr(data, period) for period in highlighted if f"EMA_{period}" in data}
    slope_parts = []
    for period, value in slopes.items():
        direction = "yukarı" if value > 0.05 else "aşağı" if value < -0.05 else "yatay"
        slope_parts.append(f"EMA{period} {direction} ({value:+.2f} ATR/5b)")
    spread_rank = _number(row.get("MA_SPREAD_RANK"))
    spread = _number(row.get("MA_SPREAD_PCT"))
    spread_previous = _number(data["MA_SPREAD_PCT"].iloc[-2]) if "MA_SPREAD_PCT" in data else math.nan
    spread_state = "genişliyor" if spread > spread_previous else "daralıyor" if spread < spread_previous else "yatay"
    atr = _number(row.get("ATR"))
    price = _number(row["Close"])
    distances = {
        str(period): (price - _number(row[f"EMA_{period}"])) / atr
        for period in highlighted
        if f"EMA_{period}" in data and atr > 0
    }
    return {
        "state": alignment,
        "tone": tone,
        "bullish_pairs": bullish_pairs,
        "bearish_pairs": bearish_pairs,
        "pair_total": pair_total,
        "slopes_atr_5": slopes,
        "distances_atr": distances,
        "spread_pct": spread,
        "spread_percentile": spread_rank,
        "spread_state": spread_state,
        "summary": f"{alignment}; {'; '.join(slope_parts)}. EMA dağılımı %{spread:.2f} ve {spread_state}.",
        "method": "EMA sıralaması ve 5 barlık EMA değişiminin güncel ATR'ye oranı; bağımsız sinyal puanı değildir.",
    }


def _gap_character(main: pd.Series, signal: pd.Series) -> str:
    gap = (main - signal).dropna()
    if len(gap) < 2:
        return "veri yetersiz"
    current, previous = float(gap.iloc[-1]), float(gap.iloc[-2])
    widening = abs(current) > abs(previous)
    if current > 0:
        return "pozitif fark genişliyor" if widening else "pozitif fark daralıyor"
    if current < 0:
        return "negatif fark genişliyor" if widening else "negatif fark daralıyor"
    return "çizgiler eşit"


def momentum_character_context(data: pd.DataFrame, divergences: dict[str, Any]) -> dict[str, Any]:
    row = data.iloc[-1]
    previous = data.iloc[-2]
    rsi = _number(row["RSI"])
    rsi_slope = _slope(data["RSI"], 5)
    hist = _number(row["MACD_HIST"])
    previous_hist = _number(previous["MACD_HIST"])
    macd_above_signal = _number(row["MACD"]) > _number(row["MACD_SIGNAL"])
    if hist > 0 and hist > previous_hist and rsi >= 50 and rsi_slope > 0:
        state, tone = "Pozitif ve genişleyen momentum", "positive"
    elif macd_above_signal and hist > 0 and hist <= previous_hist:
        state, tone = "Pozitif fakat yavaşlayan momentum", "warning"
    elif hist < 0 and hist > previous_hist:
        state, tone = "Negatiften toparlanan momentum", "warning"
    elif hist < 0 and hist < previous_hist and rsi < 50:
        state, tone = "Negatif ve genişleyen momentum", "negative"
    else:
        state, tone = "Dağınık / geçiş momentumu", "warning"
    histogram = (
        "pozitif histogram genişliyor" if hist > 0 and hist > previous_hist
        else "pozitif histogram daralıyor" if hist > 0
        else "negatif histogram daralıyor" if hist > previous_hist
        else "negatif histogram genişliyor"
    )
    active_divergences = []
    atr = _number(row.get("ATR"))
    important_levels = []
    for item in divergences.get("indicators", {}).values():
        if not item.get("detected"):
            continue
        points = 1
        reasons = ["teyitli pivot"]
        if int(item.get("event_age", 99)) <= 2:
            points += 1
            reasons.append("güncel")
        price_difference = abs(_number(item.get("price_second")) - _number(item.get("price_first")))
        if atr > 0 and price_difference / atr >= 0.75:
            points += 1
            reasons.append("belirgin fiyat ayrışması")
        oscillator_difference = abs(_number(item.get("oscillator_second")) - _number(item.get("oscillator_first")))
        if oscillator_difference >= 5:
            points += 1
            reasons.append("belirgin osilatör ayrışması")
        quality = "Güçlü" if points >= 4 else "Orta" if points >= 3 else "Zayıf"
        active_divergences.append({**item, "quality": quality, "quality_reasons": reasons})
        important_levels.append(_number(item.get("price_second")))
    rsi_zone = "aşırı alım" if rsi >= 70 else "aşırı satım" if rsi <= 30 else "pozitif bölge" if rsi >= 50 else "negatif bölge"
    return {
        "state": state,
        "tone": tone,
        "rsi": {
            "value": rsi,
            "zone": rsi_zone,
            "delta_1": _change(data["RSI"], 1),
            "delta_3": _change(data["RSI"], 3),
            "slope_5": rsi_slope,
            "gap": _gap_character(data["RSI"], data["RSI_MA"]),
        },
        "macd": {
            "above_signal": macd_above_signal,
            "above_zero": _number(row["MACD"]) > 0,
            "histogram": hist,
            "histogram_character": histogram,
            "gap": _gap_character(data["MACD"], data["MACD_SIGNAL"]),
        },
        "smi": {
            "value": _number(row["SMI"]),
            "zone": "+40 üzeri" if _number(row["SMI"]) > 40 else "-40 altı" if _number(row["SMI"]) < -40 else "orta bölge",
            "gap": _gap_character(data["SMI"], data["SMI_EMA"]),
            "slope_5": _slope(data["SMI"], 5),
        },
        "stoch_rsi": {
            "role": "Kısa vadeli timing",
            "zone": "aşırı alım" if _number(row["STOCH_K"]) >= 80 else "aşırı satım" if _number(row["STOCH_K"]) <= 20 else "orta bölge",
            "gap": _gap_character(data["STOCH_K"], data["STOCH_D"]),
        },
        "active_divergences": active_divergences,
        "important_divergence_levels": important_levels,
        "summary": (
            f"{state}. RSI {_fmt(rsi)} ({rsi_zone}, 5 bar eğim {rsi_slope:+.2f}); MACD {histogram}; "
            f"SMI {_gap_character(data['SMI'], data['SMI_EMA'])}. Stoch RSI kısa vadeli timing olarak değerlendirilir."
        ),
        "method": "Momentum ailesi ortak karakter olarak okunur; RSI/MACD/SMI/Stoch RSI ayrı oylar gibi toplanmaz.",
    }


def _rvol_series(data: pd.DataFrame, length: int = 20) -> pd.Series:
    baseline = data["Volume"].shift(1).rolling(length, min_periods=min(5, length)).mean()
    return data["Volume"] / baseline.replace(0, np.nan)


def participation_context(data: pd.DataFrame) -> dict[str, Any]:
    row = data.iloc[-1]
    rvol_series = _rvol_series(data)
    rvol_1 = _number(rvol_series.iloc[-1])
    rvol_3 = _number(rvol_series.tail(3).mean())
    rvol_5 = _number(rvol_series.tail(5).mean())
    obv_slope_5 = _slope(data["OBV"], 5)
    obv_slope_20 = _slope(data["OBV"], 20)
    volume_slope_5 = _slope(data["Volume"], 5)
    returns = data["Close"].pct_change()
    up_volume = _number(data.loc[returns > 0, "Volume"].tail(10).mean())
    down_volume = _number(data.loc[returns < 0, "Volume"].tail(10).mean())
    up_down_ratio = up_volume / down_volume if down_volume > 0 else math.nan
    price_change_5 = (_number(row["Close"]) / _number(data["Close"].iloc[-6]) - 1) * 100 if len(data) >= 6 else math.nan
    # Son barın kendi yönü. Beş barlık eğilim yukarı olsa bile bugün sert düşen
    # bir hissede "yükseliş yönünde katılım" demek okuyanı yanıltır.
    price_change_1 = (_number(row["Close"]) / _number(data["Close"].iloc[-2]) - 1) * 100 if len(data) >= 2 else math.nan
    bar_agrees_up = not math.isfinite(price_change_1) or price_change_1 >= 0
    bar_agrees_down = not math.isfinite(price_change_1) or price_change_1 <= 0
    if rvol_1 >= 1.5 and price_change_5 > 0 and obv_slope_5 > 0 and bar_agrees_up:
        state, tone = "Yükseliş yönünde güçlü katılım", "positive"
    elif rvol_1 >= 1.5 and price_change_5 < 0 and obv_slope_5 < 0 and bar_agrees_down:
        state, tone = "Düşüş yönünde güçlü katılım", "negative"
    elif rvol_1 >= 1.5 and math.isfinite(price_change_1) and price_change_5 * price_change_1 < 0:
        state, tone = "Yüksek katılım, yön çelişkili", "warning"
    elif rvol_1 < 0.8:
        state, tone = "Düşük katılım", "warning"
    elif obv_slope_5 > 0 and obv_slope_20 > 0:
        state, tone = "Birikimli katılım pozitif", "positive"
    elif obv_slope_5 < 0 and obv_slope_20 < 0:
        state, tone = "Birikimli katılım negatif", "negative"
    else:
        state, tone = "Katılım karışık", "warning"
    low_progress_high_volume = abs(price_change_5) <= 1 and rvol_3 >= 1.3
    caution = (
        "Yüksek hacme rağmen fiyat ilerlemesi sınırlı; alıcı-satıcı mücadelesi veya olası emilimle uyumlu olabilir, gerçek order-flow olmadan teyit edilemez."
        if low_progress_high_volume
        else ""
    )
    return {
        "state": state,
        "price_change_1": price_change_1,
        "tone": tone,
        "rvol_1": rvol_1,
        "rvol_3_average": rvol_3,
        "rvol_5_average": rvol_5,
        "volume_slope_5": volume_slope_5,
        "obv_slope_5": obv_slope_5,
        "obv_slope_20": obv_slope_20,
        "up_down_volume_ratio_10": up_down_ratio,
        "price_change_5_pct": price_change_5,
        "low_progress_high_volume": low_progress_high_volume,
        "caution": caution,
        "summary": (
            f"{state}; RVOL 1b {rvol_1:.2f}x, 3b ort. {rvol_3:.2f}x, 5b ort. {rvol_5:.2f}x; "
            f"OBV eğimi 5b {obv_slope_5:+,.0f}, 20b {obv_slope_20:+,.0f}. {caution}"
        ).strip(),
        "method": "RVOL mevcut hacmi önceki 20 tamamlanmış bar ortalamasıyla karşılaştırır; kurumsal akış ölçümü değildir.",
    }


def level_confluence_context(
    data: pd.DataFrame,
    levels: dict[str, float],
    profile: dict[str, Any],
    vwaps: dict[str, Any],
    structure: dict[str, Any],
    threshold_atr: float = 0.25,
) -> dict[str, Any]:
    row = data.iloc[-1]
    price = _number(row["Close"])
    atr = _number(row.get("ATR"))
    threshold = atr * threshold_atr if atr > 0 else price * 0.005
    candidates: list[dict[str, Any]] = []

    def add(name: str, value: Any, family: str) -> None:
        number = _number(value)
        if math.isfinite(number):
            candidates.append({"name": name, "value": number, "family": family})

    for period in (20, 21, 34, 50, 55, 100, 200, 233):
        add(f"EMA{period}", row.get(f"EMA_{period}"), "EMA")
    for name in ("poc", "vah", "val"):
        add(name.upper(), profile.get(name), "Profil")
    for name in ("manual", "month", "quarter", "year"):
        add("AVWAP" if name == "manual" else f"{name.title()} VWAP", vwaps.get(name), "VWAP")
    for name, value in levels.items():
        if not name.startswith("current"):
            add(name.upper(), value, "Önceki seviye")
    add("Swing High", structure.get("high"), "Yapı")
    add("Swing Low", structure.get("low"), "Yapı")
    add("BB Üst", row.get("BB_UPPER"), "Volatilite")
    add("BB Orta", row.get("BB_MID"), "Volatilite")
    add("BB Alt", row.get("BB_LOWER"), "Volatilite")
    add("Supertrend", row.get("SUPERTREND"), "Trend")
    candidates.sort(key=lambda item: item["value"])
    clusters: list[list[dict[str, Any]]] = []
    for item in candidates:
        if not clusters or item["value"] - clusters[-1][0]["value"] > threshold:
            clusters.append([item])
        else:
            clusters[-1].append(item)
    results = []
    for cluster in clusters:
        families = sorted({item["family"] for item in cluster})
        if len(cluster) < 2 or len(families) < 2:
            continue
        low = min(item["value"] for item in cluster)
        high = max(item["value"] for item in cluster)
        midpoint = (low + high) / 2
        results.append(
            {
                "low": low,
                "high": high,
                "midpoint": midpoint,
                "side": "destek" if midpoint < price else "direnç",
                "distance_atr": (midpoint - price) / atr if atr > 0 else math.nan,
                "members": [item["name"] for item in cluster],
                "families": families,
                "strength": "Güçlü" if len(families) >= 3 else "Orta",
            }
        )
    results.sort(key=lambda item: abs(item["distance_atr"]))
    support = max((item for item in candidates if item["value"] < price), key=lambda item: item["value"], default=None)
    resistance = min((item for item in candidates if item["value"] > price), key=lambda item: item["value"], default=None)
    return {
        "clusters": results[:6],
        "nearest_support": support,
        "nearest_resistance": resistance,
        "threshold_atr": threshold_atr,
        "summary": (
            f"En yakın alt referans {support['name']} {_fmt(support['value'])}" if support else "Yakın alt referans yok"
        ) + (f"; en yakın üst referans {resistance['name']} {_fmt(resistance['value'])}." if resistance else "; yakın üst referans yok."),
        "method": "Farklı teknik ailelerden seviyeler 0,25 ATR içinde kümelenir; destek/direnç kesin dönüş garantisi değildir.",
    }


def build_semantic_features(
    data: pd.DataFrame,
    ma_periods: list[int],
    levels: dict[str, float],
    profile: dict[str, Any],
    vwaps: dict[str, Any],
    structure: dict[str, Any],
    divergences: dict[str, Any],
) -> dict[str, Any]:
    return {
        "price_action": price_action_context(data),
        "trend_quality": trend_quality_context(data, ma_periods),
        "momentum_character": momentum_character_context(data, divergences),
        "participation": participation_context(data),
        "level_confluence": level_confluence_context(data, levels, profile, vwaps, structure),
    }
