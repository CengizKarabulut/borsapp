"""Traditional previous-session pivot levels, independent of swing detection.

Formula reference: TradingView's Pivot Points Standard, Traditional section:
https://www.tradingview.com/support/solutions/43000521824-pivot-points-standard/

These formula levels are not confirmed historical touches or success estimates.
The caller must supply one actual, completed session's high, low and close.
"""
from __future__ import annotations

import math
from numbers import Real

METHOD = "traditional_previous_session_hlc"
LEVEL_FIELDS = ("P", "S1", "S2", "S3", "R1", "R2", "R3")


def traditional_pivot_ladder(high: object, low: object, close: object) -> dict[str, object]:
    """Return three traditional support/resistance pairs or explicit unavailability.

    Negative or nonfinite formula outputs remain unavailable; they are never
    converted with ``abs``, clamped, or replaced with another pivot method.
    A flat session honestly retains the seven coincident numeric levels.
    """
    result: dict[str, object] = {
        "method": METHOD,
        "status": "unavailable_invalid_ohlc",
        **dict.fromkeys(LEVEL_FIELDS),
        "invalid_fields": [],
        "reason": None,
    }
    values: dict[str, float] = {}
    invalid = []
    for name, value in (("high", high), ("low", low), ("close", close)):
        if isinstance(value, bool) or not isinstance(value, Real):
            invalid.append(name)
            continue
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError):
            invalid.append(name)
            continue
        if not math.isfinite(number) or number <= 0:
            invalid.append(name)
        else:
            values[name] = number
    if invalid:
        result.update(invalid_fields=invalid, reason="finite_positive_numeric_hlc_required")
        return result

    h, lo, c = values["high"], values["low"], values["close"]
    if not lo <= c <= h:
        result.update(invalid_fields=["high", "low", "close"],
                      reason="high_low_close_geometry_invalid")
        return result
    if h == lo:
        result.update({field: h for field in LEVEL_FIELDS})
        result.update(status="flat_session_coincident_levels",
                      reason="previous_session_has_zero_range_levels_coincide")
        return result

    # Algebraically identical to TradingView's formulas. Dividing before the
    # sum and subtracting before multiplication avoids unnecessary overflow for
    # large but finite HLC inputs; genuinely unrepresentable outputs stay None.
    p = math.fsum((h / 3, lo / 3, c / 3))
    spread = h - lo
    calculated = {
        "P": p,
        "S1": p - (h - p),
        "S2": p - spread,
        "S3": lo - 2 * (h - p),
        "R1": p + (p - lo),
        "R2": p + spread,
        "R3": h + 2 * (p - lo),
    }
    invalid = [field for field, value in calculated.items()
               if not math.isfinite(value) or value <= 0]
    result.update({field: None if field in invalid else value
                   for field, value in calculated.items()})
    result.update(
        status="partial_nonpositive_levels" if invalid else "ready",
        invalid_fields=invalid,
        reason="formula_produced_nonpositive_or_nonfinite_levels" if invalid else None,
    )
    return result
