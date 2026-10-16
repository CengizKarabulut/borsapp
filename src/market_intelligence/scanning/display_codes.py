"""Public, compact ATC scanner codes. No strategy formula disclosed.

The uploaded ATC Pine packet labels original scanners 1-9 A-I, and the
remaining native scanners 10-18 by their numeric IDs. This module changes
presentation ONLY; it does not modify scanner execution, findings, or plans.
"""
from __future__ import annotations

SCANNER_ORDER = (
    "signal.macd_positive_cross",
    "signal.smi_macd_positive",
    "signal.smi_macd_positive_volume_confirmed",
    "signal.ema_trend_volume",
    "signal.rsi_macd_volume",
    "signal.sma_macd_volume",
    "signal.smi_macd_full",
    "signal.smi_macd_early",
    "signal.rsi_momentum_volume",
    "technical.volume_spike",
    "technical.squeeze_volume",
    "technical.extreme_rsi",
    "technical.failed_breakout",
    "technical.decision_zone",
    "technical.trend_continuation",
    "technical.exhaustion",
    "decision.panel_v645",
    "ma.near_zone",
)

_CODES = tuple("ABCDEFGHI") + tuple(str(i) for i in range(10, 19))
_CODE_BY_ID = dict(zip(SCANNER_ORDER, _CODES, strict=True))

# These are states backed by scanner directional evidence, not a forecast.
_DIRECTIONS = {
    "POZITIF": "LONG",
    "NEGATIF": "SHORT",
    "NOTR": "NÖTR",
    "KARMA": "KARMA",
    "ESLESME_YON_BELIRSIZ": "?",
}


def scanner_code(number: int) -> str:
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= 18:
        raise ValueError(f"Unexpected ATC scanner number: {number!r}")
    return _CODES[number - 1]


def scanner_code_from_id(scanner_id: str) -> str:
    try:
        return _CODE_BY_ID[scanner_id]
    except KeyError as exc:
        raise ValueError(f"Unknown ATC scanner: {scanner_id}") from exc


def direction_display(state: str) -> str:
    try:
        return _DIRECTIONS[state]
    except KeyError as exc:
        raise ValueError(f"Unexpected ATC direction evidence state: {state}") from exc
