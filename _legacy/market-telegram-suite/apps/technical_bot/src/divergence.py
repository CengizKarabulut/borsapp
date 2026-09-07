from __future__ import annotations

import itertools
from typing import Any

import numpy as np
import pandas as pd

INDICATORS = {
    "RSI": "RSI",
    "MACD": "MACD",
    "SMI": "SMI",
    "CCI": "CCI",
    "Fisher": "FISHER",
    "OBV": "OBV",
    "CMF": "CMF",
    "Momentum": "MOMENTUM",
}


def _pivot_positions(series: pd.Series, left: int, right: int, low: bool) -> list[int]:
    values = series.to_numpy(dtype=float)
    positions: list[int] = []
    for position in range(left, len(values) - right):
        window = values[position - left : position + right + 1]
        if not np.isfinite(window).all():
            continue
        neighbours = np.concatenate((window[:left], window[left + 1 :]))
        is_pivot = values[position] < np.min(neighbours) if low else values[position] > np.max(neighbours)
        if is_pivot:
            positions.append(position)
    return positions


def _event(
    data: pd.DataFrame,
    indicator: str,
    oscillator: pd.Series,
    first: int,
    second: int,
    right: int,
    bullish: bool,
    hidden: bool,
) -> dict[str, Any]:
    confirmation_position = second + right
    price_column = "Low" if bullish else "High"
    tone = "positive" if bullish else "negative"
    direction = "Pozitif" if bullish else "Negatif"
    divergence_type = "gizli" if hidden else "normal"
    if bullish and hidden:
        pivot_relation, interpretation = "HL / LL", "Olası yükseliş devamı"
    elif bullish:
        pivot_relation, interpretation = "LL / HL", "Olası yukarı dönüş"
    elif hidden:
        pivot_relation, interpretation = "LH / HH", "Olası düşüş devamı"
    else:
        pivot_relation, interpretation = "HH / LH", "Olası aşağı dönüş"
    state = f"{direction} {divergence_type} uyumsuzluk"
    return {
        "indicator": indicator,
        "event": f"{indicator} {state}",
        "state": state,
        "tone": tone,
        "bullish": bullish,
        "hidden": hidden,
        "divergence_type": divergence_type,
        "interpretation": interpretation,
        "pivot_relation": pivot_relation,
        "first_pivot_time": data.index[first].isoformat(),
        "second_pivot_time": data.index[second].isoformat(),
        "confirmation_time": data.index[confirmation_position].isoformat(),
        "event_age": len(data) - 1 - confirmation_position,
        "price_first": float(data[price_column].iloc[first]),
        "price_second": float(data[price_column].iloc[second]),
        "oscillator_first": float(oscillator.iloc[first]),
        "oscillator_second": float(oscillator.iloc[second]),
    }


def detect_divergences(
    data: pd.DataFrame,
    left: int = 5,
    right: int = 5,
    range_lower: int = 5,
    range_upper: int = 60,
    max_event_age: int = 5,
) -> dict[str, Any]:
    """Yön/momentum osilatörleri için teyitli normal/gizli uyumsuzlukları bulur.

    Pivotlar osilatörde bulunur ve fiyat aynı pivot barlarından karşılaştırılır.
    ``range_lower/range_upper`` iki pivotun mesafesidir; ``max_event_age`` ise
    teyitten sonra tablonun olayı aktif göstermeye devam ettiği ayrı penceredir.
    """
    indicators: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    settings = _settings(left, right, range_lower, range_upper, max_event_age)
    required = {"Low", "High"}
    if len(data) < left + right + range_lower + 1 or not required.issubset(data.columns):
        for name in INDICATORS:
            indicators[name] = {
                "detected": False,
                "state": "Yetersiz veri",
                "tone": "neutral",
                "event_age": None,
            }
        return {"indicators": indicators, "events": events, "settings": settings}

    for name, column in INDICATORS.items():
        if column not in data:
            indicators[name] = {
                "detected": False,
                "state": "Gösterge verisi yok",
                "tone": "neutral",
                "event_age": None,
            }
            continue
        oscillator = data[column]
        candidates: list[dict[str, Any]] = []
        low_pivots = _pivot_positions(oscillator, left, right, low=True)
        high_pivots = _pivot_positions(oscillator, left, right, low=False)
        for first, second in itertools.pairwise(low_pivots):
            if not range_lower <= second - first <= range_upper:
                continue
            oscillator_first = float(oscillator.iloc[first])
            oscillator_second = float(oscillator.iloc[second])
            price_first = float(data["Low"].iloc[first])
            price_second = float(data["Low"].iloc[second])
            if oscillator_second > oscillator_first and price_second < price_first:
                candidates.append(_event(data, name, oscillator, first, second, right, bullish=True, hidden=False))
            elif oscillator_second < oscillator_first and price_second > price_first:
                candidates.append(_event(data, name, oscillator, first, second, right, bullish=True, hidden=True))
        for first, second in itertools.pairwise(high_pivots):
            if not range_lower <= second - first <= range_upper:
                continue
            oscillator_first = float(oscillator.iloc[first])
            oscillator_second = float(oscillator.iloc[second])
            price_first = float(data["High"].iloc[first])
            price_second = float(data["High"].iloc[second])
            if oscillator_second < oscillator_first and price_second > price_first:
                candidates.append(_event(data, name, oscillator, first, second, right, bullish=False, hidden=False))
            elif oscillator_second > oscillator_first and price_second < price_first:
                candidates.append(_event(data, name, oscillator, first, second, right, bullish=False, hidden=True))
        active = [item for item in candidates if 0 <= int(item["event_age"]) <= max_event_age]
        if active:
            latest = min(active, key=lambda item: int(item["event_age"]))
            indicators[name] = {"detected": True, **latest}
            events.extend(active)
        else:
            indicators[name] = {
                "detected": False,
                "state": f"Son {max_event_age} barda aktif uyumsuzluk yok",
                "tone": "neutral",
                "event_age": None,
            }

    events.sort(key=lambda item: int(item["event_age"]))
    return {
        "indicators": indicators,
        "events": events,
        "settings": settings,
        "method": "TradingView RSI 5/5 pivot semantiği uygun osilatörlere uygulanır; normal ve gizli uyumsuzluk aynı pivot barlarındaki fiyatla hesaplanır. Stoch RSI, çift yumuşatma ve sınır doygunluğu nedeniyle uyumsuzluk taramasına dahil edilmez. Yalnız son 5 teyit barı aktif gösterilir.",
    }


def _settings(left: int, right: int, range_lower: int, range_upper: int, max_event_age: int) -> dict[str, int]:
    return {
        "lookback_left": left,
        "lookback_right": right,
        "pivot_range_lower": range_lower,
        "pivot_range_upper": range_upper,
        "active_max_age": max_event_age,
    }
