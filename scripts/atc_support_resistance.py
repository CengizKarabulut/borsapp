"""Portable, read-only support/resistance context for the ATC manual scan.

This small port reuses the upstream research confirmed-pivot method without
importing its feature graph or changing the installed/calibrated scan runtime.
It produces context only: it never selects, replaces or sends a trade plan.
Only closed bars known by ``as_of`` may confirm a pivot. Volume is not used.
"""
from __future__ import annotations

import math
from datetime import datetime

VERSION = "atc-support-resistance-context-v1"
UPSTREAM_COMMIT = "ece29600759072976a0f7b26a9b95cfd6fe96e9e"
UPSTREAM_FUNCTION_SHA256 = "b2e109f6e355b25723f10785a40e3cca28ab0aaf8d824107559135e2f64bdfd1"
UPSTREAM_FUNCTION_PATH = "src/market_intelligence/features/research.py::_support_resistance"
PIVOT_WIDTH = 3
MAX_LEVELS_PER_SIDE = 3
MINIMUM_SEPARATION_FRACTION = 0.01


def _aware(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}_must_be_timezone_aware")
    return value


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _label(value):
    return str(getattr(value, "value", value)) if value is not None else ""


def build_support_resistance(frame, *, as_of, reference_price=None, lookback=120):
    """Return JSON-ready confirmed-pivot context for a CanonicalFrame-like value.

    ``frame`` supplies bars with aware ``open_time``/``close_time`` and positive
    ``high``/``low``/``close``, plus canonical source/timeframe/price metadata.
    ``open`` is validated when present; volume is optional and never used.
    A marked trailing partial bar is excluded even if its timestamp is stale.

    The default reference is the latest eligible CLOSED close. A caller may
    explicitly supply a current positive price to classify the same confirmed
    pivots around that price; metadata preserves both prices and their basis.
    A level equal to the reference is neither support nor resistance. This
    strict-side guard fixes the upstream helper's equality-as-resistance edge.
    """
    _aware(as_of, "as_of")
    if type(lookback) is not int or lookback < PIVOT_WIDTH * 2 + 1:
        raise ValueError("lookback_must_allow_confirmed_pivot")
    if reference_price is not None and not _positive(reference_price):
        raise ValueError("reference_price_must_be_positive_finite")
    bars = tuple(getattr(frame, "bars", ()))
    metadata = {
        "schema": VERSION,
        "status": "insufficient_history",
        "symbol": _label(getattr(frame, "symbol_at_snapshot", None)),
        "source": _label(getattr(frame, "source", None)),
        "timeframe": _label(getattr(frame, "timeframe", None)),
        "price_basis": _label(getattr(frame, "price_basis", None)),
        "snapshot_id": _label(getattr(frame, "snapshot_id", None)),
        "series_revision": getattr(frame, "series_revision", None),
        "as_of": as_of.isoformat(),
        "input_quality": _label(getattr(frame, "quality", "complete")),
        "reference_price": reference_price,
        "reference_basis": "supplied_current_price" if reference_price is not None else "last_closed_bar",
        "closed_reference_price": None,
        "last_closed_bar_time": None,
        "window_start": None,
        "lookback_requested": lookback,
        "lookback_used": 0,
        "closed_bars_available": 0,
        "minimum_required_bars": PIVOT_WIDTH * 2 + 1,
        "history_is_shorter_than_requested": True,
        "excluded_open_or_future_bars": 0,
        "supports": [],
        "resistances": [],
        "algorithm": {
            "method": "confirmed_symmetric_price_pivots",
            "upstream_commit": UPSTREAM_COMMIT,
            "upstream_function": UPSTREAM_FUNCTION_PATH,
            "upstream_function_sha256": UPSTREAM_FUNCTION_SHA256,
            "pivot_left_bars": PIVOT_WIDTH,
            "pivot_right_closed_bars": PIVOT_WIDTH,
            "max_levels_per_side": MAX_LEVELS_PER_SIDE,
            "minimum_separation_fraction_of_reference": MINIMUM_SEPARATION_FRACTION,
            "strict_reference_side_guard": True,
            "volume_used": False,
            "changes_stop_tp": False,
        },
    }
    if not all(metadata[key] for key in ("symbol", "source", "timeframe", "price_basis")):
        raise ValueError("frame_source_price_metadata_required")
    if type(metadata["series_revision"]) is not int or metadata["series_revision"] < 0:
        raise ValueError("frame_series_revision_required")
    previous_close = None
    closed = []
    for index, bar in enumerate(bars):
        opened = _aware(bar.open_time, "bar_open_time")
        ended = _aware(bar.close_time, "bar_close_time")
        if ended <= opened:
            raise ValueError("bar_close_must_follow_open")
        if previous_close is not None and ended <= previous_close:
            raise ValueError("bars_must_have_ordered_unique_closes")
        previous_close = ended
        marked_partial = index == len(bars) - 1 and getattr(frame, "is_partial", False)
        if ended > as_of or marked_partial:
            metadata["excluded_open_or_future_bars"] += 1
            continue
        prices = [bar.high, bar.low, bar.close]
        if hasattr(bar, "open"):
            prices.append(bar.open)
        if (not all(_positive(value) for value in prices)
                or bar.high < bar.low or not bar.low <= bar.close <= bar.high
                or hasattr(bar, "open") and not bar.low <= bar.open <= bar.high):
            raise ValueError("bar_prices_must_be_positive_consistent_ohlc")
        closed.append(bar)
    metadata["closed_bars_available"] = len(closed)
    if closed:
        metadata["closed_reference_price"] = closed[-1].close
        metadata["last_closed_bar_time"] = closed[-1].close_time.isoformat()
        if reference_price is None:
            metadata["reference_price"] = closed[-1].close
    window = closed[-lookback:]
    metadata["lookback_used"] = len(window)
    metadata["history_is_shorter_than_requested"] = len(window) < lookback
    if window:
        metadata["window_start"] = window[0].close_time.isoformat()
    # Preliminary denotes only the explicitly excluded trailing open bar. Any
    # other quality problem remains unavailable rather than a fabricated level.
    if metadata["input_quality"] not in ("complete", "preliminary") or (
        metadata["input_quality"] == "preliminary" and not getattr(frame, "is_partial", False)
    ):
        metadata["status"] = "unavailable_data_quality"
        return metadata
    if len(window) < metadata["minimum_required_bars"]:
        return metadata

    lows = []
    highs = []
    for index in range(PIVOT_WIDTH, len(window) - PIVOT_WIDTH):
        pivot = window[index]
        neighbours = window[index - PIVOT_WIDTH:index + PIVOT_WIDTH + 1]
        confirmation = window[index + PIVOT_WIDTH].close_time
        if pivot.low == min(bar.low for bar in neighbours):
            lows.append((pivot.low, pivot.close_time, confirmation))
        if pivot.high == max(bar.high for bar in neighbours):
            highs.append((pivot.high, pivot.close_time, confirmation))
    reference = metadata["reference_price"]

    def distinct(candidates, *, below):
        selected = []
        candidates = sorted(
            (row for row in candidates if row[0] < reference),
            key=lambda row: row[0], reverse=True,
        ) if below else sorted(
            (row for row in candidates if row[0] > reference), key=lambda row: row[0]
        )
        for value, pivot_time, confirmation in candidates:
            if all(abs(value - other["price"]) / reference > MINIMUM_SEPARATION_FRACTION
                   for other in selected):
                selected.append({"price": value, "pivot_close_time": pivot_time.isoformat(),
                                 "confirmed_at": confirmation.isoformat()})
            if len(selected) == MAX_LEVELS_PER_SIDE:
                break
        return selected

    metadata["supports"] = distinct(lows, below=True)
    metadata["resistances"] = distinct(highs, below=False)
    metadata["status"] = "ready"
    return metadata
