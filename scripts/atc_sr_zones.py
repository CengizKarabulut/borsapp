"""Research-only causal pivot zones; no trading, fetching or production hooks.

This is one frozen hypothesis, not an optimized or validated replacement for
the existing support/resistance context. Scores are NOT win probabilities.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

VERSION = "causal-pivot-zone-memory-v1"
PIVOT_WIDTH = 3
ZONE_LIFETIME = 120
ATR_PERIOD = 14
MINIMUM_HISTORY = 30
ZONE_HALF_WIDTH_ATR = 0.25
MEMORY_HALF_LIFE = 60
EPISODE_HORIZON = 10
BOUNCE_ATR = 1.0
PENETRATION_ATR = 0.5
DISCONTINUITY_FACTOR = 1.5


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _aware(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name}_must_be_timezone_aware")
    return value


def _label(value):
    return str(getattr(value, "value", value)) if value is not None else ""


@dataclass(frozen=True)
class _Geometry:
    zone_id: str
    side: str
    center: float
    lower: float
    upper: float
    creation_atr: float
    pivot_index: int
    confirmed_index: int
    pivot_at: str
    confirmed_at: str


@dataclass
class _Zone:
    geometry: _Geometry
    members: list = field(default_factory=list)
    episodes: list = field(default_factory=list)
    pending: dict | None = None
    armed: bool = False
    retired: bool = False
    rearm_distance: float = 0.0


def _approach_far(zone, price):
    geometry = zone.geometry
    if geometry.side == "support":
        return price >= geometry.upper + zone.rearm_distance
    return price <= geometry.lower - zone.rearm_distance


def _new_zone(side, pivot, pivot_index, confirmed, confirmed_index, atr, tick_size):
    center = pivot.low if side == "support" else pivot.high
    width = max(ZONE_HALF_WIDTH_ATR * atr, tick_size or 0.0)
    if center - width <= 0:
        return None
    geometry = _Geometry(
        f"{side}:{confirmed.close_time.isoformat()}:{pivot_index}", side,
        float(center), float(center - width), float(center + width), float(atr),
        pivot_index, confirmed_index, pivot.close_time.isoformat(),
        confirmed.close_time.isoformat(),
    )
    zone = _Zone(geometry, rearm_distance=atr)
    zone.armed = _approach_far(zone, confirmed.close)
    zone.members.append({"pivot_at": geometry.pivot_at, "confirmed_at": geometry.confirmed_at,
                         "price": geometry.center})
    return zone


def _finish(zone, status, index, bar):
    episode = zone.pending
    episode.update(status=status, resolved_index=index, resolved_at=bar.close_time.isoformat())
    zone.episodes.append(episode)
    zone.pending = None
    zone.armed = False


def _evaluate_pending(zone, bar, index, *, entry=False):
    episode = zone.pending
    if zone.geometry.side == "support":
        bounce_hit = bar.high >= episode["bounce_barrier"]
        penetration_hit = bar.low <= episode["penetration_barrier"]
    else:
        bounce_hit = bar.low <= episode["bounce_barrier"]
        penetration_hit = bar.high >= episode["penetration_barrier"]
    if bounce_hit and penetration_hit:
        _finish(zone, "ambiguous_both_barriers", index, bar)
    elif entry and bounce_hit and not episode["entry_at_open"]:
        # The favorable high/low could have occurred before the intrabar entry.
        _finish(zone, "ambiguous_entry_bar", index, bar)
    elif penetration_hit:
        _finish(zone, "penetration", index, bar)
    elif bounce_hit:
        _finish(zone, "bounce", index, bar)
    elif index - episode["entry_index"] + 1 >= EPISODE_HORIZON:
        _finish(zone, "timeout", index, bar)


def _step_zone(zone, bar, index, atr, previous_close, *, allow_entry=True):
    geometry = zone.geometry
    if zone.retired:
        return
    if index - geometry.pivot_index >= ZONE_LIFETIME:
        if zone.pending is not None:
            _finish(zone, "censored_expiry", index, bar)
        zone.retired = True
        zone.armed = False
        return
    if zone.pending is not None:
        _evaluate_pending(zone, bar, index)
    elif allow_entry and zone.armed and atr is not None:
        support = geometry.side == "support"
        from_approach = (previous_close > geometry.upper if support
                         else previous_close < geometry.lower)
        touches = bar.low <= geometry.upper if support else bar.high >= geometry.lower
        if from_approach and touches:
            gap_beyond = bar.open < geometry.lower if support else bar.open > geometry.upper
            zone.rearm_distance = atr
            zone.pending = {
                "zone_id": geometry.zone_id, "side": geometry.side,
                "entry_index": index, "entry_at": bar.close_time.isoformat(),
                "entry_at_open": geometry.lower <= bar.open <= geometry.upper,
                "entry_atr": float(atr), "lower": geometry.lower, "upper": geometry.upper,
                "bounce_barrier": (geometry.upper + BOUNCE_ATR * atr if support
                                   else geometry.lower - BOUNCE_ATR * atr),
                "penetration_barrier": (geometry.lower - PENETRATION_ATR * atr if support
                                        else geometry.upper + PENETRATION_ATR * atr),
                "status": "pending", "resolved_at": None, "resolved_index": None,
            }
            zone.armed = False
            if gap_beyond:
                # A gap skipped the entry region; OHLC cannot establish a fill/touch sequence.
                _finish(zone, "ambiguous_gap_entry", index, bar)
            else:
                _evaluate_pending(zone, bar, index, entry=True)
    if zone.pending is None and _approach_far(zone, bar.close):
        # A new visit can only start on a later bar, after this observed close.
        zone.armed = True


def _zone_row(zone, index, reference, current_atr):
    geometry = zone.geometry
    eligible = [episode for episode in zone.episodes
                if episode["status"] in ("bounce", "penetration")]
    bounce_weight = sum(2 ** (-(index - row["resolved_index"]) / MEMORY_HALF_LIFE)
                        for row in eligible if row["status"] == "bounce")
    penetration_weight = sum(2 ** (-(index - row["resolved_index"]) / MEMORY_HALF_LIFE)
                             for row in eligible if row["status"] == "penetration")
    strict_side = geometry.upper < reference if geometry.side == "support" else geometry.lower > reference
    return {
        "zone_id": geometry.zone_id, "side": geometry.side,
        "center": geometry.center, "lower": geometry.lower, "upper": geometry.upper,
        "creation_atr": geometry.creation_atr, "pivot_at": geometry.pivot_at,
        "confirmed_at": geometry.confirmed_at, "age_bars": index - geometry.pivot_index,
        "member_count": len(zone.members), "member_pivots": list(zone.members),
        "completed_visits": len(eligible), "bounce_weight": bounce_weight,
        "penetration_weight": penetration_weight,
        "memory_score": (1 + bounce_weight) / (2 + bounce_weight + penetration_weight),
        "score_is_probability": False,
        "last_resolved_at": eligible[-1]["resolved_at"] if eligible else None,
        "pending_episode": dict(zone.pending) if zone.pending is not None else None,
        "retired": zone.retired, "strict_reference_side": strict_side,
        "memory_ready": len(eligible) >= 2,
        "distance_atr": abs(reference - geometry.center) / current_atr if current_atr else None,
    }


def build_sr_zones(frame, *, as_of, discontinuity_policy="reject", reset_at=(), tick_size=None):
    """Replay one fixed research hypothesis on a CanonicalFrame-like object.

    ``reset_at`` contains explicit aware close timestamps at which prior state
    must be forgotten. Suspicious >=1.5x changes default to unavailable; the
    explicit ``reset`` policy instead starts a new 30-bar warm-up. Such a reset
    is NOT an adjustment or corporate-action verification. Calendar completeness
    and a corrected/common price basis remain prerequisites outside this helper.
    Missing volume is allowed because this candidate never uses volume.
    """
    _aware(as_of, "as_of")
    if discontinuity_policy not in ("reject", "reset"):
        raise ValueError("discontinuity_policy_must_be_reject_or_reset")
    if tick_size is not None and not _positive(tick_size):
        raise ValueError("tick_size_must_be_positive_finite_or_none")
    resets = {_aware(value, "reset_at") for value in reset_at}
    bars = tuple(getattr(frame, "bars", ()))
    result = {
        "schema": VERSION, "research_only": True, "production_validated": False,
        "unvalidated_on_corrected_feed": True, "status": "insufficient_history",
        "symbol": _label(getattr(frame, "symbol_at_snapshot", None)),
        "source": _label(getattr(frame, "source", None)),
        "timeframe": _label(getattr(frame, "timeframe", None)),
        "price_basis": _label(getattr(frame, "price_basis", None)),
        "snapshot_id": _label(getattr(frame, "snapshot_id", None)),
        "series_revision": getattr(frame, "series_revision", None),
        "as_of": as_of.isoformat(), "last_closed_at": None, "reference_price": None,
        "excluded_open_or_future_bars": 0, "closed_bars_available": 0,
        "segment_bars_available": 0, "minimum_required_bars": MINIMUM_HISTORY,
        "supports": [], "resistances": [], "zones": [], "episodes": [],
        "discontinuities": [], "reset_events": [],
        "algorithm": {
            "pivot_left": PIVOT_WIDTH, "pivot_right_closed": PIVOT_WIDTH,
            "ties": "rightmost_within_confirmation_window",
            "zone_lifetime_bars": ZONE_LIFETIME, "atr_period": ATR_PERIOD,
            "atr_seed": "mean_first_14_true_ranges_then_wilder",
            "zone_half_width_atr": ZONE_HALF_WIDTH_ATR, "memory_half_life_bars": MEMORY_HALF_LIFE,
            "episode_horizon_bars": EPISODE_HORIZON, "bounce_atr": BOUNCE_ATR,
            "penetration_atr": PENETRATION_ATR, "max_levels_per_side": 3,
            "minimum_completed_visits": 2, "discontinuity_factor": DISCONTINUITY_FACTOR,
            "discontinuity_policy": discontinuity_policy, "tick_size": tick_size,
            "episode_overlap": "one_per_symbol_side_closest_approach_edge_first",
            "volume_used": False, "changes_stop_tp": False, "score_is_probability": False,
        },
    }
    if not all(result[name] for name in ("symbol", "source", "timeframe", "price_basis", "snapshot_id")):
        raise ValueError("frame_source_snapshot_price_metadata_required")
    if type(result["series_revision"]) is not int or result["series_revision"] < 0:
        raise ValueError("frame_series_revision_required")
    quality = _label(getattr(frame, "quality", ""))
    if quality not in ("complete", "preliminary") or (
        quality == "preliminary" and not getattr(frame, "is_partial", False)
    ):
        result["status"] = "unavailable_data_quality"
        return result

    closed = []
    previous_ended = None
    for position, bar in enumerate(bars):
        opened, ended = _aware(bar.open_time, "bar_open"), _aware(bar.close_time, "bar_close")
        if ended <= opened or previous_ended is not None and opened < previous_ended:
            raise ValueError("bars_must_be_nonoverlapping_ordered_unique")
        previous_ended = ended
        partial = position == len(bars) - 1 and getattr(frame, "is_partial", False)
        if ended > as_of or partial:
            result["excluded_open_or_future_bars"] += 1
            continue
        if not all(_positive(getattr(bar, name, None)) for name in ("open", "high", "low", "close")):
            raise ValueError("positive_finite_ohlc_required")
        if bar.high < bar.low or not bar.low <= bar.open <= bar.high or not bar.low <= bar.close <= bar.high:
            raise ValueError("consistent_ohlc_required")
        closed.append(bar)
    result["closed_bars_available"] = len(closed)
    if not closed:
        return result
    result["last_closed_at"] = closed[-1].close_time.isoformat()
    result["reference_price"] = float(closed[-1].close)
    visible_resets = resets.intersection(bar.close_time for bar in closed)
    unused_past_resets = {value for value in resets if value <= as_of} - visible_resets
    if unused_past_resets:
        raise ValueError("reset_timestamp_must_match_an_eligible_closed_bar")

    zones, finished_episodes, segment, true_ranges = [], [], [], []
    previous_close = None
    atr = None
    for index, bar in enumerate(closed):
        ratio = (max(bar.open / previous_close, previous_close / bar.open,
                     bar.close / previous_close, previous_close / bar.close)
                 if previous_close is not None else 1.0)
        suspicious = ratio >= DISCONTINUITY_FACTOR
        explicit_reset = bar.close_time in visible_resets
        if suspicious:
            result["discontinuities"].append({"at": bar.close_time.isoformat(),
                                               "factor": ratio, "verified_corporate_action": False})
        if suspicious and not explicit_reset and discontinuity_policy == "reject":
            result["status"] = "unavailable_suspected_discontinuity"
            result["supports"], result["resistances"] = [], []
            return result
        if explicit_reset or suspicious:
            for zone in zones:
                if zone.pending is not None:
                    _finish(zone, "censored_reset", index, bar)
                finished_episodes.extend(zone.episodes)
            zones, segment, true_ranges = [], [], []
            atr, previous_close = None, None
            result["reset_events"].append({"at": bar.close_time.isoformat(),
                                           "reason": "explicit_boundary" if explicit_reset else "suspected_discontinuity"})
        previous_atr = atr
        tr = max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)) \
            if previous_close is not None else bar.high - bar.low
        true_ranges.append(tr)
        if len(true_ranges) == ATR_PERIOD:
            atr = sum(true_ranges) / ATR_PERIOD
        elif len(true_ranges) > ATR_PERIOD:
            atr = ((ATR_PERIOD - 1) * atr + tr) / ATR_PERIOD
        usable_atr = atr if atr is not None and atr > 0 else None
        # Entry scale was observable before this bar; its own range cannot widen
        # the barriers after seeing the movement to be evaluated.
        entry_atr = previous_atr if previous_atr is not None and previous_atr > 0 else None
        # One shared move cannot start independent episodes at several regions
        # on the same side. A side occupied at the bar's start stays reserved
        # for that entire OHLC bar, even if its episode resolves within it.
        occupied_sides = {zone.geometry.side for zone in zones if zone.pending is not None}
        ordered_zones = sorted(zones, key=lambda zone: (
            abs((previous_close if previous_close is not None else bar.open)
                - (zone.geometry.upper if zone.geometry.side == "support" else zone.geometry.lower)),
            zone.geometry.confirmed_index,
        ))
        for zone in ordered_zones:
            prior_episode_count = len(zone.episodes)
            _step_zone(zone, bar, index, entry_atr, previous_close,
                       allow_entry=zone.geometry.side not in occupied_sides)
            if zone.pending is not None or len(zone.episodes) > prior_episode_count:
                occupied_sides.add(zone.geometry.side)
        segment.append((index, bar))
        if len(segment) >= MINIMUM_HISTORY and usable_atr is not None:
            window = segment[-(2 * PIVOT_WIDTH + 1):]
            pivot_index, pivot = window[PIVOT_WIDTH]
            left = [value for _, value in window[:PIVOT_WIDTH]]
            right = [value for _, value in window[PIVOT_WIDTH + 1:]]
            candidates = []
            if all(pivot.low <= value.low for value in left) and all(pivot.low < value.low for value in right):
                candidates.append("support")
            if all(pivot.high >= value.high for value in left) and all(pivot.high > value.high for value in right):
                candidates.append("resistance")
            for side in candidates:
                price = pivot.low if side == "support" else pivot.high
                matches = [zone for zone in zones if not zone.retired and zone.geometry.side == side
                           and zone.geometry.lower <= price <= zone.geometry.upper]
                if matches:
                    chosen = min(matches, key=lambda zone: (abs(price - zone.geometry.center),
                                                           zone.geometry.confirmed_index))
                    chosen.members.append({"pivot_at": pivot.close_time.isoformat(),
                                           "confirmed_at": bar.close_time.isoformat(), "price": float(price)})
                else:
                    zone = _new_zone(side, pivot, pivot_index, bar, index, usable_atr, tick_size)
                    if zone is not None:
                        zones.append(zone)
        previous_close = bar.close
    result["segment_bars_available"] = len(segment)
    result["episodes"] = finished_episodes + [dict(episode) for zone in zones for episode in zone.episodes]
    if len(segment) < MINIMUM_HISTORY or atr is None or atr <= 0:
        result["status"] = "insufficient_history"
        return result
    result["status"] = "ready_research_only"
    result["zones"] = [_zone_row(zone, len(closed) - 1, closed[-1].close, atr) for zone in zones]
    for side, key in (("support", "supports"), ("resistance", "resistances")):
        eligible = [row for row in result["zones"] if row["side"] == side and not row["retired"]
                    and row["strict_reference_side"] and row["memory_ready"]]
        result[key] = sorted(eligible, key=lambda row: (-row["memory_score"], row["distance_atr"],
                                                       row["confirmed_at"]))[:3]
    return result
