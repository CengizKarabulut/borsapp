"""Causal daily support/resistance research; structural contacts, never orders.

Each anchor freezes a confirmed pivot and past-only Wilder ATR. The next ten
bars may contact it; ten further bars assess a reaction. OHLC cannot reveal
within-bar order, so competing barriers remain explicitly ambiguous. This is
not a fill simulator, strategy return, or automatic parameter deployment.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, median

ISTANBUL = timezone(timedelta(hours=3), "Europe/Istanbul")


@dataclass(frozen=True)
class Bar:
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Config:
    lookback: int
    width: int

    @property
    def id(self):
        return f"lb{self.lookback}-w{self.width}"


CONFIGS = tuple(Config(lookback, width) for lookback in (60, 120, 252) for width in (2, 3, 5))
BASELINE = Config(120, 3)


@dataclass(frozen=True)
class Protocol:
    commonwarmup: int = 252
    stride: int = 21
    touch_bars: int = 10
    reaction_bars: int = 10
    target_atr: float = 1.0
    break_atr: float = 0.5
    max_overnight_gap_fraction: float = 0.30
    validation_start: datetime = datetime(2022, 10, 1, tzinfo=ISTANBUL)
    test_start: datetime = datetime(2024, 10, 1, tzinfo=ISTANBUL)


DEFAULT_PROTOCOL = Protocol()


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _validate(bars, configs, protocol):
    if not configs or len({config.id for config in configs}) != len(configs):
        raise ValueError("configs_must_be_nonempty_and_unique")
    for config in configs:
        if (type(config.width) is not int or config.width < 1
                or type(config.lookback) is not int or config.lookback < 2 * config.width + 1):
            raise ValueError("invalid_pivot_config")
    for name in ("commonwarmup", "stride", "touch_bars", "reaction_bars"):
        if type(getattr(protocol, name)) is not int or getattr(protocol, name) < 1:
            raise ValueError("protocol_counts_must_be_positive_integers")
    if protocol.commonwarmup < max(14, max(config.lookback for config in configs)):
        raise ValueError("common_warmup_must_cover_all_configs_and_atr")
    if not _positive(protocol.target_atr) or not _positive(protocol.break_atr):
        raise ValueError("protocol_barriers_must_be_positive_finite")
    if not _positive(protocol.max_overnight_gap_fraction) or protocol.max_overnight_gap_fraction >= 1:
        raise ValueError("continuity_threshold_must_be_between_zero_and_one")
    if (not _aware(protocol.validation_start) or not _aware(protocol.test_start)
            or protocol.validation_start >= protocol.test_start):
        raise ValueError("ordered_aware_split_boundaries_required")
    previous = None
    for bar in bars:
        if not _aware(bar.close_time) or previous is not None and bar.close_time <= previous:
            raise ValueError("bars_need_ordered_unique_aware_closes")
        previous = bar.close_time
        if (not all(_positive(value) for value in (bar.open, bar.high, bar.low, bar.close))
                or not bar.low <= bar.open <= bar.high or not bar.low <= bar.close <= bar.high):
            raise ValueError("bars_need_positive_finite_consistent_ohlc")
        if type(bar.volume) not in (int, float) or not math.isfinite(bar.volume) or bar.volume < 0:
            raise ValueError("volume_must_be_finite_nonnegative")


def wilder_atr(bars, period=14):
    """ATR at each closed bar, seeded by the first period true ranges."""
    if type(period) is not int or period < 1:
        raise ValueError("atr_period_must_be_positive_integer")
    result, ranges, previous_atr = [], [], None
    for index, bar in enumerate(bars):
        tr = bar.high - bar.low
        if index:
            previous_close = bars[index - 1].close
            tr = max(tr, abs(bar.high - previous_close), abs(bar.low - previous_close))
        if index < period:
            ranges.append(tr)
        if index == period - 1:
            previous_atr = sum(ranges) / period
        elif index >= period:
            previous_atr = (previous_atr * (period - 1) + tr) / period
        result.append(previous_atr)
    return result


def confirmed_levels(bars, config):
    """The current context's strict-side, proximity-first confirmed pivot port.

    Three nearest distinct levels use the same >1% separation rule as the
    production baseline. The evaluator freezes only the nearest one per side.
    """
    window = bars[-config.lookback:]
    if not window:
        return {"support": [], "resistance": []}
    reference, width = window[-1].close, config.width
    candidates = {"support": [], "resistance": []}
    for index in range(width, len(window) - width):
        pivot, neighbours = window[index], window[index - width:index + width + 1]
        common = {"pivot_close_time": pivot.close_time.isoformat(),
                  "confirmed_at": window[index + width].close_time.isoformat()}
        if pivot.low < reference and pivot.low == min(bar.low for bar in neighbours):
            candidates["support"].append({"price": pivot.low, **common})
        if pivot.high > reference and pivot.high == max(bar.high for bar in neighbours):
            candidates["resistance"].append({"price": pivot.high, **common})
    selected = {"support": [], "resistance": []}
    for side in selected:
        for candidate in sorted(candidates[side], key=lambda row: row["price"], reverse=side == "support"):
            if all(abs(candidate["price"] - row["price"]) / reference > 0.01 for row in selected[side]):
                selected[side].append(candidate)
            if len(selected[side]) == 3:
                break
    return selected


def _split(close_time, protocol):
    if close_time < protocol.validation_start:
        return "train"
    return "validation" if close_time < protocol.test_start else "test"


def _outcome(future, side, level, atr, protocol):
    sign = 1 if side == "support" else -1
    target = level + sign * protocol.target_atr * atr
    barrier = level - sign * protocol.break_atr * atr

    def crossed(bar):
        return ((bar.high >= target, bar.low <= barrier) if sign == 1
                else (bar.low <= target, bar.high >= barrier))

    base = {"contact_close": None, "outcome_close": None, "ignored_touchbar_target": False,
            "target_price": target if _positive(target) else None,
            "break_price": barrier if _positive(barrier) else None}
    if not _positive(target) or not _positive(barrier):
        return {**base, "outcome": "invalid_barrier"}
    for contact_index, bar in enumerate(future[:protocol.touch_bars]):
        contact = bar.low <= level if sign == 1 else bar.high >= level
        if not contact:
            continue
        base["contact_close"] = bar.close_time.isoformat()
        gap = bar.open <= barrier if sign == 1 else bar.open >= barrier
        if gap:
            return {**base, "outcome": "gap_through", "outcome_close": base["contact_close"]}
        target_hit, broken = crossed(bar)
        base["ignored_touchbar_target"] = target_hit
        if broken:
            return {**base, "outcome": "ambiguous" if target_hit else "break",
                    "outcome_close": base["contact_close"]}
        for following in future[contact_index + 1:contact_index + 1 + protocol.reaction_bars]:
            target_hit, broken = crossed(following)
            if target_hit or broken:
                outcome = "ambiguous" if target_hit and broken else "target" if target_hit else "break"
                return {**base, "outcome": outcome, "outcome_close": following.close_time.isoformat()}
        return {**base, "outcome": "timeout"}
    return {**base, "outcome": "no_contact"}


def evaluate_symbol(bars, symbol, configs=CONFIGS, protocol=DEFAULT_PROTOCOL):
    """Return auditable frozen-level events with shared, purged anchor dates."""
    bars, configs = tuple(bars), tuple(configs)
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol_required")
    _validate(bars, configs, protocol)
    audit = {"symbol": symbol, "total_bars": len(bars), "candidate_anchors": 0,
             "eligible_anchors": 0, "insufficient_history": len(bars) < protocol.commonwarmup,
             "purged_final_tail": 0, "purged_split_boundary": 0, "atr_unavailable_anchors": 0}
    boundaries = {index: bars[index].open / bars[index - 1].close - 1
                  for index in range(1, len(bars))
                  if abs(bars[index].open / bars[index - 1].close - 1) > protocol.max_overnight_gap_fraction}
    audit["purged_unverified_continuity"] = 0
    audit["flagged_boundaries"] = [
        {"close_time": bars[index].close_time.isoformat(), "overnight_fraction": ratio}
        for index, ratio in boundaries.items()]
    events, atr_values = [], wilder_atr(bars)
    horizon = protocol.touch_bars + protocol.reaction_bars
    for index in range(protocol.commonwarmup - 1, len(bars), protocol.stride):
        audit["candidate_anchors"] += 1
        if index + horizon >= len(bars):
            audit["purged_final_tail"] += 1
            continue
        split = _split(bars[index].close_time, protocol)
        future = bars[index + 1:index + 1 + horizon]
        if _split(future[-1].close_time, protocol) != split:
            audit["purged_split_boundary"] += 1
            continue
        # This is retrospective data-quality censoring, not a real-time trading
        # condition. Never learn reactions across an unreconciled scale change.
        # The 30% threshold flags investigation; it does not prove a split or
        # authorize rescaling any original price.
        if any(boundary in boundaries for boundary in range(
            max(1, index - protocol.commonwarmup + 1), index + horizon + 1,
        )):
            audit["purged_unverified_continuity"] += 1
            continue
        atr = atr_values[index]
        if not _positive(atr):
            audit["atr_unavailable_anchors"] += 1
            continue
        audit["eligible_anchors"] += 1
        for config in configs:
            levels = confirmed_levels(bars[:index + 1], config)
            for side in ("support", "resistance"):
                selected = levels[side][0] if levels[side] else None
                level = selected["price"] if selected else None
                event = {"config": config.id, "lookback": config.lookback, "width": config.width,
                         "symbol": symbol, "side": side, "split": split,
                         "anchor_close": bars[index].close_time.isoformat(),
                         "reference_price": bars[index].close, "level": level,
                         "confirmation_time": selected["confirmed_at"] if selected else None,
                         "pivot_close_time": selected["pivot_close_time"] if selected else None,
                         "atr": atr, "distance_atr": abs(level - bars[index].close) / atr if selected else None}
                event.update(_outcome(future, side, level, atr, protocol) if selected else {
                    "outcome": "no_level", "contact_close": None, "outcome_close": None,
                    "ignored_touchbar_target": False, "target_price": None, "break_price": None})
                events.append(event)
    return {"events": events, "audit": audit}


def summarize(events):
    """Aggregate structural reaction bounds; no-contact and no-level are separate.

    The denominator is all contacts including gaps; timeouts and gaps receive
    no reaction credit. Ambiguous bars provide only upper-bound credit. Macro
    fractions give equal weight to symbols with at least one contact.
    """
    groups = defaultdict(list)
    for event in events:
        groups[(event["config"], event["split"], event["side"])].append(event)
    rows = []
    for (config, split, side), grouped in sorted(groups.items()):
        counts = Counter(event["outcome"] for event in grouped)
        contacts = sum(counts[key] for key in ("gap_through", "target", "break", "ambiguous", "timeout"))
        per_symbol = defaultdict(Counter)
        for event in grouped:
            per_symbol[event["symbol"]][event["outcome"]] += 1
        macro = []
        for counter in per_symbol.values():
            total = sum(counter[key] for key in ("gap_through", "target", "break", "ambiguous", "timeout"))
            if total:
                macro.append((counter["target"] / total, (counter["target"] + counter["ambiguous"]) / total))
        distances = [event["distance_atr"] for event in grouped if event["distance_atr"] is not None]
        rows.append({"config": config, "split": split, "side": side,
                     "anchor_count": len(grouped), "level_count": len(grouped) - counts["no_level"],
                     "contact_count": contacts, "symbol_count": len(per_symbol),
                     **{f"{key}_count": counts[key] for key in (
                         "no_level", "no_contact", "gap_through", "target", "break", "ambiguous", "timeout",
                         "invalid_barrier")},
                     "reaction_fraction_lower": counts["target"] / contacts if contacts else None,
                     "reaction_fraction_upper": (counts["target"] + counts["ambiguous"]) / contacts if contacts else None,
                     "per_symbol_macro_lower": mean(row[0] for row in macro) if macro else None,
                     "per_symbol_macro_upper": mean(row[1] for row in macro) if macro else None,
                     "macro_contact_symbol_count": len(macro),
                     "distance_atr_mean": mean(distances) if distances else None,
                     "distance_atr_median": median(distances) if distances else None})
    return rows
