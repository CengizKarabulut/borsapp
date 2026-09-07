from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from src.divergence import detect_divergences
from src.semantic_features import build_semantic_features
from src.setup_recognition import build_setup_context


def _number(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _pct_distance(price: float, level: float) -> float:
    return (price / level - 1.0) * 100 if level and math.isfinite(level) else math.nan


def _slope(series: pd.Series, length: int = 5) -> float:
    values = series.dropna().tail(length).to_numpy(dtype=float)
    if len(values) < length:
        return math.nan
    return float(np.polyfit(np.arange(length, dtype=float), values, 1)[0])


def diagnostics(series: pd.Series) -> dict[str, float]:
    clean = series.dropna()
    if len(clean) < 6:
        return {"delta_1": math.nan, "delta_3": math.nan, "slope_5": math.nan}
    return {
        "delta_1": float(clean.iloc[-1] - clean.iloc[-2]),
        "delta_3": float(clean.iloc[-1] - clean.iloc[-4]),
        "slope_5": _slope(clean, 5),
    }


def normalized_gap_state(main: pd.Series, signal: pd.Series, lookback: int = 50, near_ratio: float = 0.25) -> str:
    gap = (main - signal).dropna()
    if len(gap) < 3:
        return "—"
    current = float(gap.iloc[-1])
    absolute = gap.abs()
    narrowing = absolute.iloc[-1] < absolute.iloc[-2]
    narrowing_twice = narrowing and absolute.iloc[-2] < absolute.iloc[-3]
    average = float(absolute.tail(lookback).mean())
    near = narrowing_twice and average > 0 and absolute.iloc[-1] / average <= near_ratio
    if near:
        return "↑ Kesişime yakın" if current < 0 else "↓ Kesişime yakın"
    if current > 0:
        return "Pozitif fark daralıyor" if narrowing else "Pozitif fark açılıyor"
    if current < 0:
        return "Negatif fark daralıyor" if narrowing else "Negatif fark açılıyor"
    return "Çizgiler eşit"


def _anchored_vwap(data: pd.DataFrame, mask: pd.Series) -> float:
    selected = data.loc[mask]
    if selected.empty:
        return math.nan
    typical = (selected["High"] + selected["Low"] + selected["Close"]) / 3
    volume = selected["Volume"].fillna(0.0)
    total_volume = float(volume.sum())
    return float((typical * volume).sum() / total_volume) if total_volume > 0 else math.nan


def anchored_vwaps(data: pd.DataFrame, anchor_date: str = "") -> dict[str, float | str]:
    latest = pd.Timestamp(data.index[-1])
    index = pd.DatetimeIndex(data.index)
    result: dict[str, float | str] = {
        "year": _anchored_vwap(data, pd.Series(index.year == latest.year, index=data.index)),
        "quarter": _anchored_vwap(
            data,
            pd.Series((index.year == latest.year) & (((index.month - 1) // 3) == ((latest.month - 1) // 3)), index=data.index),
        ),
        "month": _anchored_vwap(
            data,
            pd.Series((index.year == latest.year) & (index.month == latest.month), index=data.index),
        ),
    }
    if anchor_date.strip():
        try:
            anchor = pd.Timestamp(anchor_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Geçersiz AVWAP anchor tarihi: {anchor_date!r}. YYYY-MM-DD biçimini kullanın.") from exc
        if pd.isna(anchor):
            raise ValueError(f"Geçersiz AVWAP anchor tarihi: {anchor_date!r}. YYYY-MM-DD biçimini kullanın.")
        if latest.tzinfo is not None and anchor.tzinfo is None:
            anchor = anchor.tz_localize(latest.tzinfo)
        elif latest.tzinfo is None and anchor.tzinfo is not None:
            anchor = anchor.tz_localize(None)
        first = pd.Timestamp(index[0])
        if anchor.normalize() < first.normalize():
            raise ValueError(
                f"AVWAP anchor tarihi {anchor.date()} indirilen verinin başlangıcından "
                f"({first.date()}) önce. Daha uzun bir period seçin veya anchor tarihini değiştirin."
            )
        if anchor.normalize() > latest.normalize():
            raise ValueError(
                f"AVWAP anchor tarihi {anchor.date()} son mum tarihinden ({latest.date()}) sonra olamaz."
            )
        result["manual"] = _anchored_vwap(data, pd.Series(index >= anchor, index=data.index))
        result["manual_anchor"] = anchor.isoformat()
    else:
        result["manual"] = result["year"]
        result["manual_anchor"] = "Yıl başlangıcı"
    previous_mask = pd.Series(index < latest, index=data.index)
    if anchor_date.strip():
        previous_mask &= pd.Series(index >= anchor, index=data.index)
    else:
        previous_mask &= pd.Series(index.year == latest.year, index=data.index)
    result["manual_previous"] = _anchored_vwap(data, previous_mask)
    current_manual = float(result["manual"])
    previous_manual = float(result["manual_previous"])
    result["manual_direction"] = "Yükseliyor" if current_manual > previous_manual else "Düşüyor" if current_manual < previous_manual else "Yatay"
    return result


def approximate_volume_profile(data: pd.DataFrame, lookback: int = 100, bins: int = 48, value_area: float = 0.70) -> dict[str, float]:
    window = data.tail(lookback)
    low = float(window["Low"].min())
    high = float(window["High"].max())
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        return {"poc": math.nan, "vah": math.nan, "val": math.nan, "width_pct": math.nan, "bin_width": math.nan}
    edges = np.linspace(low, high, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    profile = np.zeros(bins, dtype=float)
    for row in window.itertuples():
        bar_low = _number(row.Low)
        bar_high = _number(row.High)
        volume = max(_number(row.Volume, 0.0), 0.0)
        if not math.isfinite(bar_low) or not math.isfinite(bar_high) or volume <= 0:
            continue
        first = max(int(np.searchsorted(edges, bar_low, side="right") - 1), 0)
        last = min(int(np.searchsorted(edges, bar_high, side="left")), bins - 1)
        count = max(last - first + 1, 1)
        profile[first : last + 1] += volume / count
    total = float(profile.sum())
    if total <= 0:
        return {"poc": math.nan, "vah": math.nan, "val": math.nan, "width_pct": math.nan, "bin_width": math.nan}
    poc_index = int(profile.argmax())
    selected = {poc_index}
    cumulative = float(profile[poc_index])
    lower = poc_index - 1
    upper = poc_index + 1
    target = total * value_area
    while cumulative < target and (lower >= 0 or upper < bins):
        lower_volume = profile[lower] if lower >= 0 else -1.0
        upper_volume = profile[upper] if upper < bins else -1.0
        chosen = upper if upper_volume >= lower_volume else lower
        selected.add(chosen)
        cumulative += float(profile[chosen])
        if chosen == upper:
            upper += 1
        else:
            lower -= 1
    val = float(edges[min(selected)])
    vah = float(edges[max(selected) + 1])
    poc = float(centers[poc_index])
    return {
        "poc": poc,
        "vah": vah,
        "val": val,
        "width_pct": (vah / val - 1) * 100 if val else math.nan,
        "bin_width": float(edges[1] - edges[0]),
    }


def rolling_volume_profile_levels(
    data: pd.DataFrame,
    lookback: int = 100,
    bins: int = 48,
    value_area: float = 0.70,
    min_periods: int = 2,
) -> pd.DataFrame:
    """Her bar için yalnızca o anda mevcut olan OHLCV verisiyle profil seviyeleri üretir."""
    result = pd.DataFrame(index=data.index, columns=["poc", "vah", "val"], dtype=float)
    for position in range(len(data)):
        start = max(0, position - lookback + 1)
        window = data.iloc[start : position + 1]
        if len(window) < min_periods:
            continue
        levels = approximate_volume_profile(window, lookback=lookback, bins=bins, value_area=value_area)
        result.loc[data.index[position], ["poc", "vah", "val"]] = [levels["poc"], levels["vah"], levels["val"]]
    return result


def profile_context(data: pd.DataFrame, lookback: int = 100) -> dict[str, Any]:
    current = approximate_volume_profile(data, lookback=lookback)
    previous = approximate_volume_profile(data.iloc[:-1], lookback=lookback)
    previous_3 = approximate_volume_profile(data.iloc[:-3], lookback=lookback)
    price = float(data["Close"].iloc[-1])
    atr = _number(data["ATR"].iloc[-1]) if "ATR" in data else math.nan
    poc = current["poc"]
    vah = current["vah"]
    val = current["val"]
    if price > vah:
        position = "Value Area üzerinde"
        tone = "positive"
    elif price < val:
        position = "Value Area altında"
        tone = "negative"
    else:
        position = "Value Area içinde"
        tone = "neutral"
    migration_delta = poc - previous["poc"]
    migration_delta_3 = poc - previous_3["poc"]
    va_width_delta = current["width_pct"] - previous["width_pct"]
    va_state = "Genişliyor" if va_width_delta > 0.05 else "Daralıyor" if va_width_delta < -0.05 else "Değişmiyor"
    bin_width = current["bin_width"]
    atr_threshold = atr * 0.05 if math.isfinite(atr) else 0.0
    migration_threshold = max(bin_width * 0.5, atr_threshold) if math.isfinite(bin_width) else atr_threshold
    migration_bins = migration_delta / bin_width if bin_width and math.isfinite(bin_width) else math.nan
    if abs(migration_delta) <= migration_threshold:
        migration = "Yatay"
    elif migration_delta > 0:
        migration = "Hafif yukarı göç" if migration_bins < 1.5 else "Belirgin yukarı göç"
    else:
        migration = "Hafif aşağı göç" if migration_bins > -1.5 else "Belirgin aşağı göç"
    closes = data["Close"]
    above_count = 0
    below_count = 0
    for value in reversed(closes.tail(10).tolist()):
        if value > vah and below_count == 0:
            above_count += 1
        elif value < val and above_count == 0:
            below_count += 1
        else:
            break
    last = data.iloc[-1]
    if last["High"] > vah and last["Close"] <= vah:
        acceptance = "Mevcut VAH üzeri reddedildi; Value Area'ya döndü"
        acceptance_tone = "warning"
    elif last["Low"] < val and last["Close"] >= val:
        acceptance = "Mevcut VAL altı reddedildi; Value Area'ya döndü"
        acceptance_tone = "warning"
    elif above_count >= 2:
        acceptance = f"Mevcut VAH üzerinde: {above_count} bar"
        acceptance_tone = "positive"
    elif below_count >= 2:
        acceptance = f"Mevcut VAL altında: {below_count} bar"
        acceptance_tone = "negative"
    else:
        acceptance = "Mevcut Value Area içinde rotasyon" if val <= price <= vah else "Mevcut profile göre kabul oluşmadı"
        acceptance_tone = "neutral"

    profile_source = data.tail(lookback + 9)
    developing = rolling_volume_profile_levels(profile_source, lookback=lookback)
    developing_tail = developing.tail(10)
    developing_close = profile_source["Close"].tail(10)
    developing_above = 0
    developing_below = 0
    for close_value, rolling_vah, rolling_val in reversed(
        list(zip(developing_close.tolist(), developing_tail["vah"].tolist(), developing_tail["val"].tolist()))
    ):
        if math.isfinite(rolling_vah) and close_value > rolling_vah and developing_below == 0:
            developing_above += 1
        elif math.isfinite(rolling_val) and close_value < rolling_val and developing_above == 0:
            developing_below += 1
        else:
            break
    if developing_above >= 2:
        developing_acceptance = f"Developing VAH üzerinde kabul: {developing_above} bar"
        developing_tone = "positive"
    elif developing_below >= 2:
        developing_acceptance = f"Developing VAL altında kabul: {developing_below} bar"
        developing_tone = "negative"
    else:
        developing_acceptance = "Developing profile kabulü oluşmadı"
        developing_tone = "neutral"
    return {
        **current,
        "position": position,
        "tone": tone,
        "poc_distance_pct": _pct_distance(price, poc),
        "poc_distance_atr": (price - poc) / atr if atr and math.isfinite(atr) else math.nan,
        "poc_migration": migration,
        "poc_delta": migration_delta,
        "poc_delta_3": migration_delta_3,
        "poc_migration_bins": migration_bins,
        "poc_migration_threshold": migration_threshold,
        "value_area_state": va_state,
        "value_area_width_delta": va_width_delta,
        "acceptance": acceptance,
        "acceptance_tone": acceptance_tone,
        "current_profile_acceptance": acceptance,
        "developing_acceptance": developing_acceptance,
        "developing_acceptance_tone": developing_tone,
        "note": f"Son {min(lookback, len(data))} bar OHLCV yaklaşık profili",
    }


def previous_levels(data: pd.DataFrame) -> dict[str, float]:
    previous = data.iloc[-2]
    result = {
        "pdh": float(previous["High"]),
        "pdl": float(previous["Low"]),
        "pdc": float(previous["Close"]),
        "current_open": float(data["Open"].iloc[-1]),
    }
    index = pd.DatetimeIndex(data.index)
    iso = index.isocalendar()
    weekly = data.assign(_year=iso.year.to_numpy(), _week=iso.week.to_numpy()).groupby(["_year", "_week"])
    summaries = weekly.agg({"High": "max", "Low": "min", "Close": "last", "Open": "first"})
    if len(summaries) >= 2:
        prior_week = summaries.iloc[-2]
        current_week = summaries.iloc[-1]
        result.update(
            {
                "pwh": float(prior_week["High"]),
                "pwl": float(prior_week["Low"]),
                "pwc": float(prior_week["Close"]),
                "current_week_open": float(current_week["Open"]),
            }
        )
    return result


def market_structure(data: pd.DataFrame, left: int = 5, right: int = 5) -> dict[str, Any]:
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    high_values = data["High"].to_numpy(dtype=float)
    low_values = data["Low"].to_numpy(dtype=float)
    for index in range(left, len(data) - right):
        high_window = high_values[index - left : index + right + 1]
        low_window = low_values[index - left : index + right + 1]
        if high_values[index] == np.max(high_window):
            highs.append((index, float(high_values[index])))
        if low_values[index] == np.min(low_window):
            lows.append((index, float(low_values[index])))
    if len(highs) < 2 or len(lows) < 2:
        return {"state": "Yetersiz pivot", "event": "—", "high": math.nan, "low": math.nan, "tone": "neutral"}
    high_state = "HH" if highs[-1][1] > highs[-2][1] else "LH"
    low_state = "HL" if lows[-1][1] > lows[-2][1] else "LL"
    state = f"{high_state} / {low_state}"
    tone = "positive" if state == "HH / HL" else "negative" if state == "LH / LL" else "warning"
    close = data["Close"].to_numpy(dtype=float)
    last_high_index, last_high = highs[-1]
    last_low_index, last_low = lows[-1]
    events: list[tuple[int, str]] = []
    for index in range(last_high_index + 1, len(data)):
        if close[index] > last_high and close[index - 1] <= last_high:
            events.append((len(data) - 1 - index, "Swing High üzeri BOS"))
    for index in range(last_low_index + 1, len(data)):
        if close[index] < last_low and close[index - 1] >= last_low:
            events.append((len(data) - 1 - index, "Swing Low altı BOS"))
    event = min(events, default=(math.inf, "Yeni yapı kırılımı yok"), key=lambda item: item[0])
    return {
        "state": state,
        "event": event[1],
        "event_age": None if not math.isfinite(event[0]) else int(event[0]),
        "high": last_high,
        "low": last_low,
        "high_time": data.index[last_high_index].isoformat(),
        "low_time": data.index[last_low_index].isoformat(),
        "tone": tone,
        "confirmed": True,
    }


def relative_volume(data: pd.DataFrame, length: int = 20) -> float:
    if len(data) < 2:
        return math.nan
    index = pd.DatetimeIndex(data.index)
    median_hours = index.to_series().diff().dropna().dt.total_seconds().median() / 3600
    current = float(data["Volume"].iloc[-1])
    if median_hours < 20:
        slots = pd.Series(list(zip(index.hour, index.minute)), index=data.index)
        same_slot = data.loc[slots == slots.iloc[-1], "Volume"].iloc[:-1].tail(length)
        baseline = float(same_slot.mean()) if len(same_slot) >= 3 else math.nan
    else:
        baseline = float(data["Volume"].iloc[-length - 1 : -1].mean())
    return current / baseline if baseline and math.isfinite(baseline) else math.nan


def order_flow_proxy(data: pd.DataFrame) -> dict[str, float | str]:
    bar_range = (data["High"] - data["Low"]).replace(0, np.nan)
    buy_share = ((data["Close"] - data["Low"]) / bar_range).clip(0, 1).fillna(0.5)
    buy = data["Volume"] * buy_share
    sell = data["Volume"] - buy
    delta = buy - sell
    cumulative = delta.cumsum()
    current_volume = float(data["Volume"].iloc[-1])
    return {
        "buy": float(buy.iloc[-1]),
        "sell": float(sell.iloc[-1]),
        "delta": float(delta.iloc[-1]),
        "delta_pct": float(delta.iloc[-1] / current_volume * 100) if current_volume else math.nan,
        "delta_3": float(delta.tail(3).sum()),
        "cvd": float(cumulative.iloc[-1]),
        "cvd_slope_5": _slope(cumulative, 5),
        "method": "OHLCV kapanış-konumu tahmini; gerçek footprint delta değildir",
    }


def _last_cross_age(main: pd.Series, signal: pd.Series | float, upward: bool) -> int | None:
    if isinstance(signal, (float, int)):
        previous_relation = main.shift(1) <= signal if upward else main.shift(1) >= signal
        current_relation = main > signal if upward else main < signal
    else:
        previous_relation = main.shift(1) <= signal.shift(1) if upward else main.shift(1) >= signal.shift(1)
        current_relation = main > signal if upward else main < signal
    events = (previous_relation & current_relation).fillna(False).to_numpy()
    positions = np.flatnonzero(events)
    return int(len(events) - 1 - positions[-1]) if len(positions) else None


def recent_events(
    data: pd.DataFrame,
    structure: dict[str, Any],
    profile: dict[str, Any],
    limit: int = 12,
    bar_state: dict[str, Any] | None = None,
    divergences: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    definitions: list[tuple[str, pd.Series, pd.Series | float, bool]] = [
        ("MACD ↑ Signal", data["MACD"], data["MACD_SIGNAL"], True),
        ("MACD ↓ Signal", data["MACD"], data["MACD_SIGNAL"], False),
        ("MACD ↑ 0", data["MACD"], 0.0, True),
        ("MACD ↓ 0", data["MACD"], 0.0, False),
        ("RSI ↑ MA", data["RSI"], data["RSI_MA"], True),
        ("RSI ↓ MA", data["RSI"], data["RSI_MA"], False),
        ("RSI ↑ 30", data["RSI"], 30.0, True),
        ("RSI ↓ 30", data["RSI"], 30.0, False),
        ("RSI ↑ 50", data["RSI"], 50.0, True),
        ("RSI ↓ 50", data["RSI"], 50.0, False),
        ("RSI ↑ 70", data["RSI"], 70.0, True),
        ("RSI ↓ 70", data["RSI"], 70.0, False),
        ("Stoch RSI K ↑ D", data["STOCH_K"], data["STOCH_D"], True),
        ("Stoch RSI K ↓ D", data["STOCH_K"], data["STOCH_D"], False),
        ("Stoch RSI ↑ 20", data["STOCH_K"], 20.0, True),
        ("Stoch RSI ↓ 20", data["STOCH_K"], 20.0, False),
        ("Stoch RSI ↑ 80", data["STOCH_K"], 80.0, True),
        ("Stoch RSI ↓ 80", data["STOCH_K"], 80.0, False),
        ("SMI ↑ Signal", data["SMI"], data["SMI_EMA"], True),
        ("SMI ↓ Signal", data["SMI"], data["SMI_EMA"], False),
        ("SMI ↑ -40", data["SMI"], -40.0, True),
        ("SMI ↓ -40", data["SMI"], -40.0, False),
        ("SMI ↑ 0", data["SMI"], 0.0, True),
        ("SMI ↓ 0", data["SMI"], 0.0, False),
        ("SMI ↑ 40", data["SMI"], 40.0, True),
        ("SMI ↓ 40", data["SMI"], 40.0, False),
        ("MFI ↑ MA", data["MFI"], data["MFI_MA"], True),
        ("MFI ↓ MA", data["MFI"], data["MFI_MA"], False),
        ("CCI ↑ MA", data["CCI"], data["CCI_MA"], True),
        ("CCI ↓ MA", data["CCI"], data["CCI_MA"], False),
        ("+DI ↑ -DI", data["PLUS_DI"], data["MINUS_DI"], True),
        ("+DI ↓ -DI", data["PLUS_DI"], data["MINUS_DI"], False),
        ("Tenkan ↑ Kijun", data["TENKAN"], data["KIJUN"], True),
        ("Tenkan ↓ Kijun", data["TENKAN"], data["KIJUN"], False),
        ("Fiyat ↑ BB üst", data["Close"], data["BB_UPPER"], True),
        ("Fiyat ↓ BB üst", data["Close"], data["BB_UPPER"], False),
        ("Fiyat ↑ BB orta", data["Close"], data["BB_MID"], True),
        ("Fiyat ↓ BB orta", data["Close"], data["BB_MID"], False),
        ("Fiyat ↑ BB alt", data["Close"], data["BB_LOWER"], True),
        ("Fiyat ↓ BB alt", data["Close"], data["BB_LOWER"], False),
        ("Fiyat ↑ Dataset VWAP", data["Close"], data["VWAP"], True),
        ("Fiyat ↓ Dataset VWAP", data["Close"], data["VWAP"], False),
        ("Fiyat ↑ SAR", data["Close"], data["PSAR"], True),
        ("Fiyat ↓ SAR", data["Close"], data["PSAR"], False),
        ("Fiyat ↑ Supertrend", data["Close"], data["SUPERTREND"], True),
        ("Fiyat ↓ Supertrend", data["Close"], data["SUPERTREND"], False),
    ]
    events: list[dict[str, Any]] = []

    def confirmation(age: int, suffix: str = "") -> str:
        label = "CANLI" if age == 0 and bar_state and bar_state.get("is_live") else "TEYİTLİ"
        return f"{label} {suffix}".strip()

    for name, main, signal, upward in definitions:
        age = _last_cross_age(main, signal, upward)
        if age is not None:
            events.append({"event": name, "age": age, "state": confirmation(age)})
    structure_age = structure.get("event_age")
    if structure_age is not None:
        events.append({"event": structure["event"], "age": structure_age, "state": confirmation(structure_age)})
    profile_lookback = 100
    event_window = min(100, len(data))
    profile_source = data.tail(profile_lookback + event_window - 1)
    rolling_profile = rolling_volume_profile_levels(profile_source, lookback=profile_lookback)
    price = profile_source["Close"].tail(event_window)
    for label, column, upward in [
        ("VAH ↑", "vah", True),
        ("VAH ↓", "vah", False),
        ("VAL ↑", "val", True),
        ("VAL ↓", "val", False),
        ("POC ↑", "poc", True),
        ("POC ↓", "poc", False),
    ]:
        known_level = rolling_profile[column].shift(1).tail(event_window)
        previous_relation = price.shift(1) <= known_level if upward else price.shift(1) >= known_level
        current_relation = price > known_level if upward else price < known_level
        positions = np.flatnonzero((previous_relation & current_relation).fillna(False).to_numpy())
        age = int(len(price) - 1 - positions[-1]) if len(positions) else None
        if age is not None:
            events.append({"event": label, "age": age, "state": confirmation(age, "OHLCV PROFİL t-1")})
    for item in (divergences or {}).get("events", []):
        age = int(item["event_age"])
        events.append({"event": item["event"], "age": age, "state": confirmation(age, "PİVOT 5/5")})
    events.sort(key=lambda item: item["age"])
    return events[:limit]


def build_market_context(
    data: pd.DataFrame,
    ma_periods: list[int],
    anchor_date: str = "",
    bar_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = data.iloc[-1]
    price = float(row["Close"])
    profile = profile_context(data)
    structure = market_structure(data)
    divergences = detect_divergences(data)
    levels = previous_levels(data)
    vwaps = anchored_vwaps(data, anchor_date)
    flow = order_flow_proxy(data)
    rvol = relative_volume(data)
    semantic = build_semantic_features(data, ma_periods, levels, profile, vwaps, structure, divergences)

    ma_values = np.array([float(row[f"EMA_{length}"]) for length in ma_periods], dtype=float)
    valid_ma = ma_values[np.isfinite(ma_values)]
    ma_above = int(np.count_nonzero(price > valid_ma))
    ma_rising = sum(float(data[f"EMA_{length}"].iloc[-1]) > float(data[f"EMA_{length}"].iloc[-2]) for length in ma_periods)
    ma_spread_pct = float(row["MA_SPREAD_PCT"])
    ma_spread_rank = float(row["MA_SPREAD_RANK"])
    adx = float(row["ADX"])
    atr_rank = float(row["ATR_RANK"])
    bb_rank = float(row["BB_WIDTH_RANK"])
    bb_widening = float(row["BB_WIDTH"]) > float(data["BB_WIDTH"].iloc[-2])
    adx_delta = float(row["ADX"] - data["ADX"].iloc[-2])
    spread_delta = float(row["MA_SPREAD_PCT"] - data["MA_SPREAD_PCT"].iloc[-2])

    def candidate_regime(item: pd.Series, previous_item: pd.Series) -> str:
        item_adx = float(item["ADX"])
        item_atr_rank = float(item["ATR_RANK"])
        item_bb_rank = float(item["BB_WIDTH_RANK"])
        item_spread_rank = float(item["MA_SPREAD_RANK"])
        item_adx_delta = float(item["ADX"] - previous_item["ADX"])
        item_spread_delta = float(item["MA_SPREAD_PCT"] - previous_item["MA_SPREAD_PCT"])
        expanding = item_atr_rank >= 60 or item_bb_rank >= 60
        if item_adx >= 25 and expanding and item_adx_delta > 0 and item_spread_delta > 0:
            return "Trend genişliyor"
        if item_adx >= 25 and item_adx_delta < 0 and item_spread_delta < 0:
            return "Trend yavaşlıyor"
        if item_adx >= 25 and item_adx_delta > 0:
            return "Trend oluşuyor"
        if item_adx >= 25:
            return "Yönlü / kontrollü piyasa"
        if item_adx < 20 and item_bb_rank <= 25 and item_spread_rank <= 30:
            return "Denge / sıkışma"
        if item_adx < 20 and item_bb_rank >= 70:
            return "Volatilite genişlemesi / yönsüz"
        return "Geçiş / karma piyasa"

    candidates = []
    for position in range(max(1, len(data) - 20), len(data)):
        if data[["ADX", "ATR_RANK", "BB_WIDTH_RANK", "MA_SPREAD_RANK", "MA_SPREAD_PCT"]].iloc[position].isna().any():
            continue
        candidates.append(candidate_regime(data.iloc[position], data.iloc[position - 1]))
    regime = candidates[0] if candidates else "Geçiş / karma piyasa"
    pending = regime
    pending_count = 0
    for candidate in candidates[1:]:
        if candidate == regime:
            pending, pending_count = candidate, 0
        elif candidate == pending:
            pending_count += 1
            if pending_count >= 2:
                regime, pending_count = candidate, 0
        else:
            pending, pending_count = candidate, 1
    current_candidate = candidates[-1] if candidates else regime
    if regime.startswith(("Trend", "Yönlü")):
        regime_tone = "positive" if row["PLUS_DI"] > row["MINUS_DI"] else "negative"
    elif "sıkışma" in regime or "Volatilite" in regime:
        regime_tone = "warning"
    else:
        regime_tone = "neutral"

    momentum_feature = semantic["momentum_character"]
    momentum_state = momentum_feature["state"]
    momentum_tone = momentum_feature["tone"]
    active_divergences = [
        f"{item['indicator']} {item['state']} / kalite {item['quality']} (teyit {item['event_age']} bar önce, pivot 5 bar öncesi)"
        for item in momentum_feature["active_divergences"]
    ]
    divergence_state = " | ".join(active_divergences) if active_divergences else "Son 5 barda aktif uyumsuzluk yok"
    momentum_rsi = momentum_feature["rsi"]
    momentum_headline = (
        f"RSI {momentum_rsi['value']:.1f} ({momentum_rsi['zone']}, eğim5 {momentum_rsi['slope_5']:+.2f}) | "
        f"MACD {momentum_feature['macd']['histogram_character']} | {divergence_state}"
    )
    participation_feature = semantic["participation"]
    volume_state = participation_feature["state"]
    volume_tone = participation_feature["tone"]
    volatility_state = ("Genişliyor" if bb_widening else "Daralıyor") + f" | ATR perc %{atr_rank:.0f}"
    volatility_tone = "purple" if atr_rank >= 70 else "blue" if atr_rank <= 30 else "neutral"
    ma_groups_definition = {
        "Çok kısa": [5, 8, 10, 13],
        "Kısa": [20, 21, 34, 50, 55],
        "Orta": [89, 100, 144],
        "Uzun": [200, 233, 377],
    }
    ma_groups = {}
    for group_name, group_periods in ma_groups_definition.items():
        periods = [length for length in group_periods if f"EMA_{length}" in data]
        if not periods:
            continue
        group_values = [float(row[f"EMA_{length}"]) for length in periods]
        ma_groups[group_name] = {
            "above": sum(price > value for value in group_values if math.isfinite(value)),
            "rising": sum(float(data[f"EMA_{length}"].iloc[-1]) > float(data[f"EMA_{length}"].iloc[-2]) for length in periods),
            "total": len(periods),
            "periods": periods,
        }
    ma_state = " | ".join(f"{name} {item['above']}/{item['total']}" for name, item in ma_groups.items())
    location_state = profile["position"]

    setup_context = build_setup_context(
        data,
        {"regime": {"state": regime, "adx": adx}, "structure": structure, "profile": profile},
        semantic,
    )
    setup = setup_context["setup"]
    participation_reading = setup_context["participation_reading"]

    families = [
        ["KURULUM", setup["name"], f"Eğilim: {setup['bias']} | {setup_context['duration']['summary']}", setup["tone"]],
        ["REJİM", regime, f"Aday {current_candidate} | ADX Δ {adx_delta:+.2f} | Spread Δ {spread_delta:+.3f}", regime_tone],
        ["YAPI", structure["state"], structure["event"], structure["tone"]],
        ["KONUM", location_state, profile["developing_acceptance"], profile["tone"]],
        ["TREND", ma_state, f"EMA spread %{ma_spread_pct:.2f} | perc %{ma_spread_rank:.0f}", "positive" if ma_above >= 10 else "negative" if ma_above <= 5 else "warning"],
        ["MOMENTUM", momentum_state, momentum_headline, momentum_tone],
        ["KATILIM", participation_reading["state"], f"RVOL 1b {participation_feature['rvol_1']:.2f}x | 3b {participation_feature['rvol_3_average']:.2f}x | Delta tah. %{flow['delta_pct']:.1f}", participation_reading["tone"]],
        ["VOLATİLİTE", volatility_state, f"BB perc %{bb_rank:.0f}", volatility_tone],
    ]

    location_rows = [
        ["POC / VA", f"POC {profile['poc']:.2f} | VAH {profile['vah']:.2f} | VAL {profile['val']:.2f} | {profile['poc_distance_atr']:+.2f} ATR", profile["position"], profile["tone"]],
        ["POC göçü", f"Δ1 {profile['poc_delta']:+.2f} | {profile['poc_migration_bins']:+.2f} bin | Eşik {profile['poc_migration_threshold']:.2f}", profile["poc_migration"], "positive" if "yukarı" in profile["poc_migration"] else "negative" if "aşağı" in profile["poc_migration"] else "neutral"],
        ["Mevcut profil", f"{profile['note']} | VA {profile['value_area_state']}", profile["current_profile_acceptance"], profile["acceptance_tone"]],
        ["Developing profil", "Her barda geriye dönük 100 bar VAH/VAL", profile["developing_acceptance"], profile["developing_acceptance_tone"]],
        ["AVWAP", f"{vwaps['manual']:.2f} | Mesafe {_pct_distance(price, float(vwaps['manual'])):+.2f}% | Anchor {vwaps['manual_anchor']}", f"Fiyat {'üstünde' if price > float(vwaps['manual']) else 'altında'} | AVWAP {vwaps['manual_direction']}", "positive" if price > float(vwaps["manual"]) else "negative"],
        ["VWAP dönem", f"Ay {vwaps['month']:.2f} | Çeyrek {vwaps['quarter']:.2f} | Yıl {vwaps['year']:.2f}", "Fiyat dönem VWAP'larıyla karşılaştırıldı", "neutral"],
        ["Önceki gün", f"PDH {levels['pdh']:.2f} | PDL {levels['pdl']:.2f} | PDC {levels['pdc']:.2f} | D Açılış {levels['current_open']:.2f}", "PDH üzeri" if price > levels["pdh"] else "PDL altı" if price < levels["pdl"] else "Önceki gün aralığında", "positive" if price > levels["pdh"] else "negative" if price < levels["pdl"] else "neutral"],
    ]
    location_rows.append(
        ["Market Structure", f"Swing H {structure['high']:.2f} | Swing L {structure['low']:.2f}", f"{structure['state']} | {structure['event']} | TEYİTLİ", structure["tone"]]
    )
    if "pwh" in levels:
        location_rows.append(
            ["Önceki hafta", f"PWH {levels['pwh']:.2f} | PWL {levels['pwl']:.2f} | PWC {levels['pwc']:.2f} | W Açılış {levels['current_week_open']:.2f}", "PWH üzeri" if price > levels["pwh"] else "PWL altı" if price < levels["pwl"] else "Önceki hafta aralığında", "positive" if price > levels["pwh"] else "negative" if price < levels["pwl"] else "neutral"]
        )

    participation_rows = [
        ["Hacim / RVOL", f"{row['Volume']:,.0f} | 1b {participation_feature['rvol_1']:.2f}x | 3b {participation_feature['rvol_3_average']:.2f}x", volume_state, volume_tone],
        ["Buy/Sell tah.", f"Buy {flow['buy']:,.0f} | Sell {flow['sell']:,.0f}", f"Delta {flow['delta']:+,.0f} | %{flow['delta_pct']:+.1f}", "positive" if flow["delta"] > 0 else "negative"],
        ["CVD tah.", f"{flow['cvd']:+,.0f}", f"Slope5 {flow['cvd_slope_5']:+,.0f}", "positive" if flow["cvd_slope_5"] > 0 else "negative"],
        ["OBV", f"{row['OBV']:,.0f}", f"Slope5 {_slope(data['OBV'], 5):+,.0f}", "positive" if _slope(data["OBV"], 5) > 0 else "negative"],
        ["MFI", f"{row['MFI']:.2f} | MA {row['MFI_MA']:.2f}", normalized_gap_state(data["MFI"], data["MFI_MA"]), "positive" if row["MFI"] > row["MFI_MA"] else "negative"],
        ["Yöntem notu", "OHLCV proxy", str(flow["method"]), "warning"],
    ]

    return {
        "regime": {"state": regime, "candidate": current_candidate, "tone": regime_tone, "adx": adx, "adx_delta": adx_delta, "ma_spread_delta": spread_delta, "atr_percentile": atr_rank, "bb_percentile": bb_rank, "persistence_bars": 2},
        "families": families,
        "profile": profile,
        "structure": structure,
        "levels": levels,
        "anchored_vwaps": vwaps,
        "order_flow_proxy": flow,
        "relative_volume": rvol,
        "semantic": semantic,
        "setup_context": setup_context,
        "ma_structure": {"above": ma_above, "rising": ma_rising, "total": len(valid_ma), "spread_pct": ma_spread_pct, "spread_percentile": ma_spread_rank, "groups": ma_groups},
        "divergences": divergences,
        "location_rows": location_rows,
        "participation_rows": participation_rows,
        "events": recent_events(data, structure, profile, bar_state=bar_state, divergences=divergences),
    }
