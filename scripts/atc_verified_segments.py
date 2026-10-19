"""Partition observed history at unverified dates without repairing candles.

This read-only helper has no provider, store, E-drive, order or notification
dependency. Partitioning is diagnostic. Eligible frame preparation additionally
requires source-bound independent price-basis evidence and a reset contract.
It never runs a scanner, backtest, profile export or activation.
"""
from __future__ import annotations

import json
import re
from bisect import bisect_left
from dataclasses import dataclass, replace
from datetime import date, datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

VERSION = "atc-gap-separated-observed-history-v1"
MINIMUM_CLOSED_BARS = 60
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_VERIFICATION_METHODS = frozenset({
    "independent_source_reconciliation",
    "pinned_capture_and_independent_corporate_action_check",
})


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_timestamp_required")
    return value


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("canonical_date_required")
    return value


def _digest(value):
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError("sha256_required")
    return value


@dataclass(frozen=True)
class BasisVerification:
    """Attestation to an independently reviewed receipt, not a provider label.

    The caller must verify the referenced evidence file and its methodology.
    If a frame builder also consumes a daily reconciliation source, bind the
    hash of the complete immutable source-reference packet, not hourly alone.
    This pure helper binds that attestation to the exact immutable source hash;
    it does not itself certify numerical corporate-action adjustment. A saved
    ``adjustment='splits'`` string alone is insufficient.
    """

    source_sha256: str
    evidence_sha256: str
    verification_method: str
    price_basis: str = "split_adjusted"
    verified: bool = False

    def permits(self, source_sha256):
        return (
            self.verified is True
            and self.price_basis == "split_adjusted"
            and self.verification_method in _VERIFICATION_METHODS
            and isinstance(self.evidence_sha256, str)
            and bool(_DIGEST.fullmatch(self.evidence_sha256))
            and self.source_sha256 == source_sha256
        )


def unverified_dates(coverage, *, documented_excluded_dates=()):
    """Include entirely missing sessions as well as partially missing buckets.

    A caller may supply independently documented calendar exclusions already
    handled by its native frame builder. This helper has no built-in calendar
    assumptions or permission to infer a no-trade day from absent data.
    """
    boundaries = {_date(value) for value in coverage.get("missing_dates", ())}
    for failure in coverage.get("reconciliation_failures", ()):
        if failure.get("code") == "missing_hourly_day":
            boundaries.add(_date(failure["date"]))
    excluded = {_date(value) for value in documented_excluded_dates}
    return tuple(sorted(boundaries - excluded))


def partition_observed_history(rows, boundaries, *, as_of, timezone="Europe/Istanbul"):
    """Return independent spans; never concatenate observations across a gap.

    The input rows must be flat, JSON-compatible observed OHLCV-like mappings
    with ordered aware timestamps. Row values are copied unchanged. The caller
    remains responsible for full OHLCV/schema validation at frame preparation.
    ``as_of`` prevents future source observations entering a diagnostic span.
    """
    observed = _aware(as_of)
    zone = ZoneInfo(timezone)
    blocked = tuple(sorted({_date(value) for value in boundaries}))
    values = tuple(dict(row) for row in rows)
    if any(isinstance(value, (dict, list, tuple)) for row in values for value in row.values()):
        raise ValueError("flat_source_rows_required")
    stamps = [_aware(row["timestamp"]) for row in values]
    if any(a >= b for a, b in zip(stamps, stamps[1:], strict=False)):
        raise ValueError("strictly_ordered_source_required")
    if any(stamp > observed for stamp in stamps):
        raise ValueError("future_source_observation")
    # Reject NaN and other non-JSON evidence rather than fingerprinting it.
    _hash(values)
    groups = [[] for _ in range(len(blocked) + 1)]
    for row, stamp in zip(values, stamps, strict=True):
        local = stamp.astimezone(zone).date().isoformat()
        index = bisect_left(blocked, local)
        if index < len(blocked) and blocked[index] == local:
            continue
        groups[index].append(row)
    outputs = []
    for index, selected in enumerate(groups):
        if not selected:
            continue
        description = {
            "policy": VERSION,
            "partition_index": index,
            "after_excluded_date": blocked[index-1] if index else None,
            "before_excluded_date": blocked[index] if index < len(blocked) else None,
            "first_source_date": _aware(selected[0]["timestamp"]).astimezone(zone).date().isoformat(),
            "last_source_date": _aware(selected[-1]["timestamp"]).astimezone(zone).date().isoformat(),
            "selected_row_count": len(selected),
            "selected_rows_sha256": _hash(selected),
            "excluded_boundary_dates": list(blocked),
            "as_of": observed.isoformat(),
            "timezone": timezone,
            "synthetic_rows_created": 0,
            "source_prices_changed": 0,
            "source_timestamps_shifted": 0,
        }
        outputs.append({**description, "segment_id": _hash(description), "rows": tuple(selected)})
    return tuple(outputs)


def prepare_verified_segments(rows, boundaries, *, source_sha256, as_of, prepare_frame,
                              basis_verification=None, reset_each_segment=False,
                              carry_positions=False, minimum_closed_bars=60,
                              timezone="Europe/Istanbul"):
    """Gate independent frame preparation; return diagnostic metadata and frames.

    ``prepare_frame`` receives only this span's rows, ``as_of``, a derived
    ``segment_id`` and ``reset_state=True``. It must create a fresh frame after
    validating raw OHLCV, bucket completeness and session rules. The callback
    must not be a live scanner or backtest. Its frame supplies ``bars`` with
    aware ``open_time``/``close_time``, ``price_basis`` and ``quality``. A returned
    frame must be a dataclass supporting a newly derived ``snapshot_id``.

    No callback is invoked without verified source-bound adjustment evidence
    and explicit all-state reset. No position or indicator state is passed from
    one segment to another. A future research runner must enforce the same
    reset contract, and must not trade across excluded boundaries.
    """
    _digest(source_sha256)
    observed = _aware(as_of)
    if type(minimum_closed_bars) is not int or minimum_closed_bars < MINIMUM_CLOSED_BARS:
        raise ValueError("cannot_weaken_60_closed_bar_minimum")
    partitions = partition_observed_history(rows, boundaries, as_of=observed, timezone=timezone)
    verified = isinstance(basis_verification, BasisVerification) and basis_verification.permits(source_sha256)
    outputs = []
    for partition in partitions:
        selected = partition["rows"]
        context = {key: value for key, value in partition.items() if key != "rows"}
        context.update({
            "source_sha256": source_sha256,
            "basis_evidence_sha256": basis_verification.evidence_sha256 if verified else None,
            "economic_adjustment_verified": bool(verified),
            "minimum_closed_bars": minimum_closed_bars,
            "state_reset_required": True,
            "positions_may_cross_boundaries": False,
            "eligible_for_research": False,
            "profile_activation_allowed": False,
        })
        frame = None
        if not verified:
            context["status"] = "blocked_unverified_price_basis"
        elif reset_each_segment is not True or carry_positions is not False:
            context["status"] = "blocked_state_reset_contract"
        else:
            # Every call gets a fresh explicit context and no prior engine state.
            frame = prepare_frame(selected, as_of=observed,
                                  segment_id=context["segment_id"], reset_state=True)
            if _hash(selected) != context["selected_rows_sha256"]:
                raise ValueError("frame_builder_changed_source_rows")
            bars = tuple(frame.bars)
            if len(bars) > len(selected):
                raise ValueError("prepared_frame_has_more_bars_than_observations")
            basis = str(getattr(frame.price_basis, "value", frame.price_basis))
            if (basis != "split_adjusted" or frame.quality != "complete"
                    or getattr(frame, "is_partial", False)):
                raise ValueError("prepared_frame_basis_or_quality_rejected")
            opens = [_aware(bar.open_time) for bar in bars]
            closes = [_aware(bar.close_time) for bar in bars]
            if (any(a >= b for a, b in zip(opens, opens[1:], strict=False))
                    or any(a >= b for a, b in zip(closes, closes[1:], strict=False))):
                raise ValueError("prepared_frame_order_rejected")
            if any(opened < previous_close for opened, previous_close
                   in zip(opens[1:], closes[:-1], strict=True)):
                raise ValueError("prepared_frame_overlap_rejected")
            if any(opened >= closed or closed > observed
                   for opened, closed in zip(opens, closes, strict=True)):
                raise ValueError("prepared_frame_not_closed_at_observation")
            zone = ZoneInfo(timezone)
            if any(not context["first_source_date"] <= opened.astimezone(zone).date().isoformat()
                   <= context["last_source_date"] for opened in opens):
                raise ValueError("prepared_frame_outside_selected_span")
            if any(closed.astimezone(zone).date().isoformat() > context["last_source_date"]
                   for closed in closes):
                raise ValueError("prepared_frame_crosses_selected_span")
            context["closed_bars"] = len(bars)
            if len(bars) < minimum_closed_bars:
                context["status"] = "insufficient_segment_history"
                frame = None
            else:
                context.update({"status": "eligible_independent_segment",
                                "eligible_for_research": True,
                                "first_close": closes[0].isoformat(),
                                "last_close": closes[-1].isoformat()})
                context["prepared_snapshot_id"] = _digest(frame.snapshot_id)
                context["derived_snapshot_id"] = _hash(context)
                frame = replace(frame, snapshot_id=context["derived_snapshot_id"])
        outputs.append({"frame": frame, "metadata": context})
    return tuple(outputs)
