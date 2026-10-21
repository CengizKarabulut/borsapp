"""Actual native intraday OHLCV including sparse auction observations, RAM only.

The compatibility module/function names also serve native 15m/30m/1h rows.
Preserve real opening/closing auctions and full nominal interval ends, including
19:00/21:00 for 2h/4h 17:00 opens. These times do not establish confirmation
or the last trade time. Missing source intervals are never filled or spliced.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from functools import lru_cache
from numbers import Real

from market_intelligence.core.identity import stable_hash
from market_intelligence.core.timeframes import Timeframe, parse_timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.market_data.providers import FetchRequest, TimestampKind
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_live_snapshot_frames import (
    ISTANBUL,
    MAX_LATEST_NATIVE_AGE_MINUTES,
    QUALITY,
    _nonregular_session_days,
    _session_days,
)

NATIVE_MULTIHOUR_GRIDS = {
    Timeframe.M15: "tradingview_native_15m_0945_grid_including_auctions",
    Timeframe.M30: "tradingview_native_30m_0930_grid_including_auctions",
    Timeframe.H1: "tradingview_native_1h_09_grid_including_auctions",
    Timeframe.H2: "tradingview_native_2h_09_grid_including_auctions",
    Timeframe.H4: "tradingview_native_4h_09_grid_including_auctions",
}
NATIVE_INTRADAY_GRIDS = NATIVE_MULTIHOUR_GRIDS
REGULAR_ANCHORS = {Timeframe.M15: (9, 45), Timeframe.M30: (9, 30),
                   Timeframe.H1: (9, 0), Timeframe.H2: (9, 0), Timeframe.H4: (9, 0)}
SHORT_GRID_EVIDENCE_DATES = ("2025-10-28", "2026-03-19", "2026-05-26")


@lru_cache(maxsize=12)
def _historical_halfdays(first_year, last_year):
    """Only calendar-certified 10:00-12:30 sessions use the 09:30 source grid.

    Older regular market-hour regimes or other nonregular days are not silently
    classified as this half-day policy. The native grid was independently
    observed on three dated source probes, while each accepted date still
    requires its actual XIST open/close and exact source timestamps.
    """
    import exchange_calendars

    calendar = exchange_calendars.get_calendar("XIST", start=f"{min(1990, first_year)}-01-01",
        end=f"{last_year}-12-31")
    result = {}
    for stamp, row in calendar.schedule.iterrows():
        opened = row["open"].to_pydatetime().astimezone(ISTANBUL)
        closed = row["close"].to_pydatetime().astimezone(ISTANBUL)
        if ((opened.hour, opened.minute, closed.hour, closed.minute) == (10, 0, 12, 30)
                and first_year <= stamp.year <= last_year):
            result[stamp.date()] = {"calendar_open": opened.isoformat(), "calendar_close": closed.isoformat()}
    return result


def _aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Native-multihour timestamps must be timezone-aware")
    return value.astimezone(ISTANBUL)


def _symbol(value):
    return value.strip().upper().removeprefix("BIST:").removesuffix(".IS")


def expected_multihour_context(now, target, sessions):
    """Latest report session, plus its true provider native period label."""
    target = parse_timeframe(target)
    if target not in NATIVE_MULTIHOUR_GRIDS:
        raise ValueError("Native-multihour supports only 15m/30m/1h/2h/4h")
    boundary = now.replace(hour=9, minute=45, second=0, microsecond=0)
    if now.date() in sessions and now >= boundary:
        session = now.date()
        hour, minute = REGULAR_ANCHORS[target]
        first = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        final_hour = 18 if target.minutes <= 60 else 17
        cursor = min(now, first.replace(hour=final_hour, minute=0))
        duration = timedelta(minutes=target.minutes)
        opened = first + ((cursor - first) // duration) * duration
    else:
        previous = [day for day in sessions if day < now.date()]
        if not previous:
            raise ValueError("No previous BIST session in native-multihour calendar")
        session = max(previous)
        opened = datetime.combine(session, datetime.min.time(), ISTANBUL).replace(hour=18 if target.minutes <= 60 else 17)
    return session, opened, opened + timedelta(minutes=target.minutes)


def prepare_native_multihour(provider, member, *, timeframe, observed_at, clock, bars):
    """One actual source/resolution/basis; never H1 synthesis or confirmed data."""
    target = parse_timeframe(timeframe)
    if target not in NATIVE_MULTIHOUR_GRIDS:
        raise ValueError("Native-multihour supports only 15m/30m/1h/2h/4h")
    fetch = getattr(provider, "fetch_native_multihour", None)
    if not callable(fetch):
        raise ValueError("Live intraday snapshots require explicit native-multihour access")
    observed_at = _aware(observed_at)
    initial_sessions = _session_days(observed_at.year - 1, observed_at.year + 1)
    _, _, cutoff = expected_multihour_context(observed_at, target, initial_sessions)
    raw = fetch(FetchRequest(member.provider_symbol, target, min(5000, bars + 1), cutoff))
    received_at = _aware(clock())
    if received_at < observed_at:
        raise ValueError("Clock moved backwards while fetching native-multihour data")
    if raw.timeframe is not target or raw.timestamp_kind is not TimestampKind.OPEN:
        raise ValueError("Native-multihour source must return the exact requested open-time resolution")
    if _symbol(raw.provider_symbol) != _symbol(member.provider_symbol):
        raise ValueError("Native-multihour provider returned a different instrument")
    if not raw.bars:
        raise ValueError("No authentic observed native-multihour candles")
    first_year = min(item.timestamp.year for item in raw.bars)
    sessions = _session_days(first_year, received_at.year + 1)
    nonregular = _nonregular_session_days(first_year, received_at.year + 1)
    halfdays = _historical_halfdays(first_year, received_at.year + 1)
    session, expected_open, expected_close = expected_multihour_context(received_at, target, sessions)
    if session in nonregular:
        raise ValueError("Latest expected BIST session is a half-day/nonregular session; native-multihour unsupported")
    native = []
    previous = None
    short_dates = set()
    duration = timedelta(minutes=target.minutes)
    for item in raw.bars:
        opened = _aware(item.timestamp)
        if opened > received_at:
            raise ValueError("Native-multihour candle starts after actual receipt")
        if opened.date() not in sessions:
            raise ValueError("Native-multihour candle starts on a non-session date")
        hour, minute = REGULAR_ANCHORS[target]
        first = opened.replace(hour=hour, minute=minute, second=0, microsecond=0)
        final = first.replace(hour=18 if target.minutes <= 60 else 17, minute=0)
        if opened.date() in nonregular:
            if opened.date() not in halfdays or opened.date() >= received_at.date():
                raise ValueError("Unsupported historical shortened-session native-multihour grid")
            first = first.replace(hour=9, minute=30)
            final = first.replace(hour=12 if target.minutes <= 60 else 11 if target is Timeframe.H2 else 9)
            short_dates.add(opened.date())
        if not first <= opened <= final or (opened - first) % duration:
            raise ValueError("Provider supplied a shifted native-multihour candle")
        if previous is not None and opened <= previous:
            raise ValueError("Native-multihour candles must be unique and ordered")
        previous = opened
        values = tuple(getattr(item, field) for field in ("open", "high", "low", "close", "volume"))
        if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
               for value in values) or min(values[:4]) <= 0:
            raise ValueError("Native-multihour OHLCV must be finite numeric with positive prices")
        native.append(CanonicalBar(opened, opened + duration, *(float(value) for value in values)))
    selected = tuple(native[-bars:])
    latest = selected[-1]
    current = latest.open_time == expected_open and latest.close_time == expected_close
    nominal_open = latest.open_time <= received_at < latest.close_time
    first_today = received_at.replace(hour=9, minute=45, second=0, microsecond=0)
    auction_end = received_at.replace(hour=18, minute=10, second=0, microsecond=0)
    during_session = received_at.date() in sessions and first_today <= received_at < auction_end
    native_age = max(0.0, (received_at - latest.close_time).total_seconds())
    same_session = latest.open_time.date() == session
    # Absence of an actual closing-auction candle is not permission to invent
    # one. After the auction window, the real regular close is a valid final
    # observation when its native end is exactly18:00. Earlier sparse rows stay
    # stale. Keep its actual start/end and disclose the missing auction row.
    auction_open = expected_open.replace(hour=18, minute=0, second=0, microsecond=0)
    auction_observed = any(bar.open_time == auction_open for bar in selected)
    regular_close_no_auction = (target.minutes <= 60 and not during_session and same_session
        and not auction_observed and latest.open_time == auction_open - duration
        and latest.close_time == auction_open)
    usable = same_session and (native_age <= MAX_LATEST_NATIVE_AGE_MINUTES * 60 if during_session
                              else current or regular_close_no_auction)
    status = ("stale_previous_session" if not same_session else "stale_previous_bucket" if not current
              else "native_nominally_open" if nominal_open else "latest_native_observation")
    if regular_close_no_auction:
        status = "last_regular_close_without_auction"
    identity = stable_hash({"kind": "ATC_UNPERSISTED_NATIVE_MULTIHOUR_WHAT_IF_V1",
        "source_grid": NATIVE_MULTIHOUR_GRIDS[target], "instrument_id": member.instrument_id,
        "symbol": member.symbol, "timeframe": target, "source": raw.provider,
        "price_basis": raw.price_basis, "received_at": received_at, "bars": selected, "quality": QUALITY})
    frame = CanonicalFrame(instrument_id=member.instrument_id, symbol_at_snapshot=member.symbol,
        market=member.market, timeframe=target, snapshot_id=identity, series_revision=0,
        price_basis=raw.price_basis, source=raw.provider, bars=selected, is_partial=False, quality=QUALITY)
    metadata = {
        "quality": QUALITY, "status": status, "source_grid": NATIVE_MULTIHOUR_GRIDS[target],
        "current_bucket": current, "usable_latest": usable, "target_bucket_present": current,
        "current_native_bucket": current, "expected_market_session": session.isoformat(),
        "closing_auction_candle_observed": auction_observed if target.minutes <= 60 else None,
        "closing_observation_basis": "last_regular_close_without_auction_candle" if regular_close_no_auction
            else "actual_native_source_candle",
        "native_bar_time_basis": "provider_nominal_interval_not_last_trade",
        "actual_bar_is_open": None, "actual_bar_confirmation": "unknown",
        "nominally_open": nominal_open, "temporally_open": nominal_open,
        "provider_partial_flag": raw.last_bar_is_partial,
        "observed_at": observed_at.isoformat(), "received_at": received_at.isoformat(),
        "request_cutoff": cutoff.isoformat(), "native_timeframe": target.value,
        "last_bar_open": latest.open_time.isoformat(), "last_bar_close": latest.close_time.isoformat(),
        "latest_target_complete": None, "observed_prefix_end": None,
        "nominal_end_is_exchange_confirmation": False,
        "expected_bucket_open": expected_open.isoformat(), "expected_bucket_close": expected_close.isoformat(),
        "expected_native_open": expected_open.isoformat(),
        "last_actual_native_open": latest.open_time.isoformat(), "last_actual_native_close": latest.close_time.isoformat(),
        "latest_native_age_limit_minutes": MAX_LATEST_NATIVE_AGE_MINUTES,
        "latest_native_close_age_seconds": native_age, "stale_bar_close_age_seconds": native_age,
        "last_trade_at": None, "price_delay_seconds": None,
        "bar_elapsed_seconds": max(0.0, (received_at - latest.open_time).total_seconds()),
        "history_bars": len(selected), "dropped_incomplete_history_buckets": 0,
        "session_truncated_bucket": False, "source": raw.provider,
        "price_basis": raw.price_basis.value, "persisted": False,
        "calendar_version": ExchangeCalendarsXist().version,
        "session_schedule": f"Actual native {target.value} grid including auctions; nominal ends are not last-trade times",
        "nonregular_history_dates": [day.isoformat() for day in sorted(short_dates)],
        "historical_nonregular_close_times_nominal": bool(short_dates),
        "historical_nonregular_native_grid_policies": [
            {"session": day.isoformat(), "anchor": "09:30", "last_open": "12:30" if target.minutes <= 60 else "11:30" if target is Timeframe.H2 else "09:30",
             "policy": "calendar_certified_historical_1230_halfday_observed_native_0930_grid",
             **halfdays[day], "calendar_version": ExchangeCalendarsXist().version,
             "grid_evidence_dates": list(SHORT_GRID_EVIDENCE_DATES),
             "nominal_ends_are_not_last_trade_times": True} for day in sorted(short_dates)],
    }
    return frame, metadata
