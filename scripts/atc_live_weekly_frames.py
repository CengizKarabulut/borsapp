"""Authentic provider-native W1 candles for unpersisted RAM evaluation.

A weekly candle's timestamp identifies a calendar-week cohort. It is not the
last trade time and cannot prove that the quote is seconds old. Native starts
may fall on Tuesday/Wednesday after an exchange holiday, or retain a Monday
holiday label for a week with later actual sessions. Preserve that actual
provider label and its nominal seven-day end;
never manufacture a Monday bar or assemble a week from mixed daily sources.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from functools import lru_cache
from numbers import Real
from zoneinfo import ZoneInfo

from market_intelligence.core.identity import stable_hash
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.market_data.providers import FetchRequest, TimestampKind
from market_intelligence.scheduling.xist import ExchangeCalendarsXist

ISTANBUL = ZoneInfo("Europe/Istanbul")
QUALITY = "PROVISIONAL_WHAT_IF_NOT_PERSISTED"
NATIVE_WEEKLY_GRID = "tradingview_native_calendar_week"


def calendar_week_identity(value: datetime | date) -> str:
    """Monday date of the actual Istanbul calendar week, not a bar relabeling."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Weekly cohort time must be timezone-aware")
        value = value.astimezone(ISTANBUL).date()
    return (value - timedelta(days=value.weekday())).isoformat()


@lru_cache(maxsize=12)
def _session_days(first_year: int, last_year: int) -> frozenset[date]:
    return frozenset(ExchangeCalendarsXist().sessions(
        date(first_year, 1, 1), date(last_year, 12, 31)))


def _aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Weekly observation time must be timezone-aware")
    return value.astimezone(ISTANBUL)


def _symbol(value):
    return value.strip().upper().removeprefix("BIST:").removesuffix(".IS")


def expected_week_context(now, sessions):
    """Latest started BIST report session and its calendar-week cohort.

    09:45 is the live report's auction-inclusive session boundary, not a claim
    about a weekly trade. Before it, the cohort remains the previous session.
    The expected 09:00 weekly label is descriptive only: a genuine source row
    may start on a later traded weekday and is compared by week membership.
    """
    boundary = now.replace(hour=9, minute=45, second=0, microsecond=0)
    started = [day for day in sessions if day < now.date()
               or (day == now.date() and now >= boundary)]
    if not started:
        raise ValueError("No previous BIST session in weekly calendar")
    session = max(started)
    week = calendar_week_identity(session)
    first = min(day for day in sessions if calendar_week_identity(day) == week)
    opened = datetime.combine(first, datetime.min.time(), ISTANBUL).replace(hour=9)
    return session, week, opened, opened + timedelta(days=7)


def prepare_native_weekly(provider, member, *, observed_at, clock, bars):
    """Return a single-source real W1 window, never a confirmed-bar store input."""
    fetch = getattr(provider, "fetch_native_weekly", None)
    if not callable(fetch):
        raise ValueError("Weekly live snapshots require explicit native-weekly access")
    observed_at = _aware(observed_at)
    initial_sessions = _session_days(observed_at.year - 1, observed_at.year + 1)
    _, _, _, cutoff = expected_week_context(observed_at, initial_sessions)
    raw = fetch(FetchRequest(member.provider_symbol, Timeframe.W1,
                             min(5000, bars + 1), cutoff))
    received_at = _aware(clock())
    if received_at < observed_at:
        raise ValueError("Clock moved backwards while fetching weekly data")
    if raw.timeframe is not Timeframe.W1 or raw.timestamp_kind is not TimestampKind.OPEN:
        raise ValueError("Native-weekly source must return explicit W1 open timestamps")
    if _symbol(raw.provider_symbol) != _symbol(member.provider_symbol):
        raise ValueError("Native-weekly provider returned a different instrument")
    if not raw.bars:
        raise ValueError("No authentic observed native weekly candles")
    sessions = _session_days(min(item.timestamp.year for item in raw.bars), received_at.year + 1)
    session_weeks = {calendar_week_identity(day) for day in sessions}
    session, expected_week, expected_open, expected_close = expected_week_context(received_at, sessions)
    selected = []
    previous = None
    weeks = set()
    non_session_labels = []
    for item in raw.bars:
        opened = _aware(item.timestamp)
        week = calendar_week_identity(opened)
        if opened > received_at:
            raise ValueError("Native-weekly candle starts after actual receipt")
        # A W1 timestamp is a provider PERIOD label, not a trade timestamp.
        # Actual ASELS history labels 2019-07-15 (holiday) for the real 16-19
        # July traded week. Preserve it, requiring actual sessions IN the week.
        if opened.weekday() > 4 or week not in session_weeks:
            raise ValueError("Native-weekly candle has a non-session week label")
        if opened.date() not in sessions:
            non_session_labels.append(opened.date().isoformat())
        if (opened.hour, opened.minute, opened.second, opened.microsecond) != (9, 0, 0, 0):
            raise ValueError("Provider supplied a shifted native weekly 09:00 candle")
        if previous is not None and opened <= previous:
            raise ValueError("Native-weekly candles must be unique and ordered")
        if week in weeks:
            raise ValueError("Native-weekly source contains multiple candles in one calendar week")
        previous = opened
        weeks.add(week)
        values = tuple(getattr(item, field) for field in ("open", "high", "low", "close", "volume"))
        if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
               for value in values):
            raise ValueError("Native-weekly OHLCV must be finite numeric values, not booleans")
        values = tuple(float(value) for value in values)
        if min(values[:4]) <= 0:
            raise ValueError("Native-weekly OHLC prices must be positive")
        selected.append(CanonicalBar(opened, opened + timedelta(days=7), *values))
    selected = tuple(selected[-bars:])
    latest = selected[-1]
    source_week = calendar_week_identity(latest.open_time)
    current = source_week == expected_week
    nominal_open = latest.open_time <= received_at < latest.close_time
    status = "current_native_week" if current else "stale_previous_week"
    if source_week > expected_week:
        status = "native_week_before_report_session"
    identity = stable_hash({"kind": "ATC_UNPERSISTED_NATIVE_WEEKLY_WHAT_IF_V1",
        "source_grid": NATIVE_WEEKLY_GRID, "instrument_id": member.instrument_id,
        "symbol": member.symbol, "timeframe": Timeframe.W1, "source": raw.provider,
        "price_basis": raw.price_basis, "received_at": received_at,
        "bars": selected, "quality": QUALITY})
    frame = CanonicalFrame(instrument_id=member.instrument_id, symbol_at_snapshot=member.symbol,
        market=member.market, timeframe=Timeframe.W1, snapshot_id=identity, series_revision=0,
        price_basis=raw.price_basis, source=raw.provider, bars=selected, is_partial=False, quality=QUALITY)
    metadata = {
        "quality": QUALITY, "status": status, "source_grid": NATIVE_WEEKLY_GRID,
        "current_bucket": current, "usable_latest": current, "target_bucket_present": current,
        "current_native_bucket": current, "expected_market_session": session.isoformat(),
        "source_week": source_week, "expected_week": expected_week,
        "weekly_cohort_matches": current,
        "freshness_basis": "calendar_week_membership_not_last_trade_time",
        "native_bar_time_basis": "provider_week_start_and_nominal_seven_day_end_not_last_trade",
        "native_week_anchor_policy": "actual_provider_week_label_preserved",
        "calendar_non_session_week_labels": non_session_labels,
        "actual_bar_is_open": None, "actual_bar_confirmation": "unknown",
        "nominally_open": nominal_open, "temporally_open": nominal_open,
        "provider_partial_flag": raw.last_bar_is_partial,
        "observed_at": observed_at.isoformat(), "received_at": received_at.isoformat(),
        "request_cutoff": cutoff.isoformat(), "native_timeframe": Timeframe.W1.value,
        "last_bar_open": latest.open_time.isoformat(), "last_bar_close": latest.close_time.isoformat(),
        "latest_target_complete": None, "observed_prefix_end": None,
        "nominal_end_is_exchange_confirmation": False,
        "expected_bucket_open": expected_open.isoformat(), "expected_bucket_close": expected_close.isoformat(),
        "expected_native_open": expected_open.isoformat(),
        "last_actual_native_open": latest.open_time.isoformat(),
        "last_actual_native_close": latest.close_time.isoformat(),
        "latest_native_age_limit_minutes": None, "latest_native_close_age_seconds": None,
        "stale_bar_close_age_seconds": None, "last_trade_at": None, "price_delay_seconds": None,
        "bar_elapsed_seconds": max(0.0, (received_at - latest.open_time).total_seconds()),
        "history_bars": len(selected), "dropped_incomplete_history_buckets": 0,
        "session_truncated_bucket": False, "source": raw.provider,
        "price_basis": raw.price_basis.value, "persisted": False,
        "calendar_version": ExchangeCalendarsXist().version,
        "session_schedule": "Actual provider W1 OHLCV; one native row per calendar week with real sessions; native week labels and nominal ends are not trade times or confirmation",
        "nonregular_history_dates": [], "historical_nonregular_close_times_nominal": True,
    }
    return frame, metadata
