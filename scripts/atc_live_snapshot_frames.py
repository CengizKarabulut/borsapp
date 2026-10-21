"""Authentic latest-bar snapshots for the unpersisted CANLI / TEYITSIZ scanner.

The only deliberate hypothetical assumption is that the latest observed candle
closed at the instant it was fetched.  No price, volume, missing bucket or past
bar is invented.  The returned frame is ONLY for RAM formula evaluation; its
``is_partial=False`` must never be used as proof of exchange confirmation.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import lru_cache
from numbers import Real
from zoneinfo import ZoneInfo

from market_intelligence.application.ingestion import BASE_TIMEFRAME
from market_intelligence.core.identity import stable_hash
from market_intelligence.core.timeframes import Timeframe, parse_timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.market_data.providers import FetchRequest, ProviderFrame, TimestampKind
from market_intelligence.scheduling.bist import BistSessionSchedule
from market_intelligence.scheduling.xist import ExchangeCalendarsXist

ISTANBUL = ZoneInfo("Europe/Istanbul")
QUALITY = "PROVISIONAL_WHAT_IF_NOT_PERSISTED"
NATIVE_45M_GRID = "tradingview_native_45m_including_auctions"
# Actual provider-native grid observed on this exchange-calendar-certified
# shortened session. It is historical input only, not a guessed regular grid.
NATIVE_45M_HISTORICAL_SHORT_GRIDS = {
    date(2026, 3, 19): ((9, 30), (12, 30)),
    date(2026, 5, 26): ((9, 30), (12, 30)),
}
MAX_LATEST_NATIVE_AGE_MINUTES = 30
SUPPORTED_TIMEFRAMES = (
    Timeframe.M15, Timeframe.M30, Timeframe.M45, Timeframe.H1,
    Timeframe.H2, Timeframe.H4, Timeframe.D1, Timeframe.W1,
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Observation time must be timezone-aware")
    return value.astimezone(ISTANBUL)


def _symbol(value: str) -> str:
    return value.strip().upper().removeprefix("BIST:").removesuffix(".IS")


@lru_cache(maxsize=12)
def _session_days(first_year: int, last_year: int) -> frozenset[date]:
    return frozenset(ExchangeCalendarsXist().sessions(
        date(first_year, 1, 1), date(last_year, 12, 31),
    ))


@lru_cache(maxsize=12)
def _nonregular_session_days(first_year: int, last_year: int) -> frozenset[date]:
    """The RAM adapter does not silently apply 18:00 to a half-day session."""
    import exchange_calendars

    calendar = exchange_calendars.get_calendar(
        "XIST", start=f"{min(1990, first_year)}-01-01", end=f"{last_year}-12-31",
    )
    result = set()
    for stamp, row in calendar.schedule.iterrows():
        opened = row["open"].to_pydatetime().astimezone(ISTANBUL)
        closed = row["close"].to_pydatetime().astimezone(ISTANBUL)
        if (opened.hour, opened.minute, closed.hour, closed.minute) != (10, 0, 18, 0):
            result.add(stamp.date())
    return frozenset(result)


def _bucket(opened: datetime, target: Timeframe, schedule: BistSessionSchedule):
    session_open, session_close = schedule.session_bounds(opened.date())
    if target is Timeframe.D1:
        return session_open, session_close
    duration = timedelta(minutes=target.minutes or 0)
    start = session_open + ((opened - session_open) // duration) * duration
    return start, min(start + duration, session_close)


def _expected_bucket(now, target, schedule, sessions):
    session_open, session_close = schedule.session_bounds(now.date())
    if now.date() in sessions and now >= session_open:
        day = now.date()
        cursor = min(now, session_close - timedelta(microseconds=1))
    else:
        previous = [day for day in sessions if day < now.date()]
        if not previous:
            raise ValueError("No previous BIST session in calendar")
        day = max(previous)
        cursor = schedule.session_bounds(day)[1] - timedelta(microseconds=1)
    return _bucket(cursor, target, schedule)


def _native_bars(raw: ProviderFrame, *, received_at, schedule, sessions):
    """Keep the provider's last partial row instead of Canonicalizer dropping it."""
    result = []
    seen = set()
    for item in raw.bars:
        stamp = item.timestamp
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            stamp = stamp.replace(tzinfo=ZoneInfo(raw.timestamp_timezone))
        stamp = stamp.astimezone(ISTANBUL)
        if raw.timeframe is Timeframe.D1:
            opened, closed = schedule.session_bounds(stamp.date())
        else:
            duration = timedelta(minutes=raw.timeframe.minutes or 0)
            if not raw.timeframe.is_intraday:
                raise ValueError("Weekly/monthly native bars are unsupported in live snapshots")
            if raw.timestamp_kind is TimestampKind.OPEN:
                opened, closed = stamp, stamp + duration
            else:
                opened, closed = stamp - duration, stamp
        if opened > received_at:
            raise ValueError("Provider supplied a candle that starts after receipt")
        if opened.date() not in sessions:
            raise ValueError("Provider supplied a candle on a non-session date")
        session_open, session_close = schedule.session_bounds(opened.date())
        if opened < session_open or closed > session_close:
            raise ValueError("Provider supplied an out-of-session candle")
        if raw.timeframe.is_intraday and (
            (opened - session_open) % timedelta(minutes=raw.timeframe.minutes or 0)
        ):
            raise ValueError("Provider supplied a shifted native candle")
        if opened in seen:
            raise ValueError("Provider supplied duplicate candle timestamps")
        seen.add(opened)
        bar = CanonicalBar(
            open_time=opened, close_time=closed,
            open=float(item.open), high=float(item.high), low=float(item.low),
            close=float(item.close), volume=float(item.volume),
        )
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        result.append(bar)
    return tuple(sorted(result, key=lambda bar: bar.open_time))


def _aggregate(base, *, source, target, received_at, schedule):
    if source is target:
        return base, 0, False, False
    groups = defaultdict(list)
    for bar in base:
        groups[_bucket(bar.open_time, target, schedule)].append(bar)
    result = []
    dropped = 0
    latest_group = max(groups)
    last_truncated = False
    latest_incomplete_prefix = False
    for (opened, closed), group in sorted(groups.items()):
        ordered = sorted(group, key=lambda bar: bar.open_time)
        contiguous = all(a.close_time == b.open_time for a, b in zip(
            ordered, ordered[1:], strict=False,
        ))
        # A still-open target may contain only the prefix that has ACTUALLY
        # traded. Closed historical targets must contain the complete bucket.
        complete = ordered[-1].close_time == closed
        mutable = opened <= received_at < closed
        # A delayed feed may still expose only an authentic contiguous prefix
        # just after this target's nominal end. Keep that observed prefix ONLY
        # in the RAM what-if path, with an explicit incomplete-target label.
        # Never accept an interior/start gap, old session, or >30m native lag.
        session_open, session_close = schedule.session_bounds(received_at.date())
        fresh_late_prefix = (
            (opened, closed) == latest_group and not complete and not mutable
            and opened.date() == received_at.date()
            and session_open <= received_at < session_close
            and timedelta(0) <= received_at - ordered[-1].close_time
            <= timedelta(minutes=MAX_LATEST_NATIVE_AGE_MINUTES)
        )
        truncated = (closed - opened) < timedelta(minutes=target.minutes or 0)
        # Keep the established canonical history contract (45m historical
        # session tails are not full 45m bars). Only the latest actual bucket
        # gets the explicit what-if exception, including its session tail.
        if truncated and (opened, closed) != latest_group:
            dropped += 1
            continue
        if (ordered[0].open_time != opened or not contiguous
                or ordered[-1].close_time > closed or not (complete or mutable or fresh_late_prefix)):
            if (opened, closed) == latest_group:
                raise ValueError("Latest derived candle has missing native OHLCV; no gap filling")
            dropped += 1
            continue
        result.append(CanonicalBar(
            open_time=opened, close_time=closed,
            open=ordered[0].open, high=max(bar.high for bar in ordered),
            low=min(bar.low for bar in ordered), close=ordered[-1].close,
            volume=sum(bar.volume for bar in ordered),
        ))
        last_truncated = truncated
        latest_incomplete_prefix = fresh_late_prefix
    return tuple(result), dropped, last_truncated, latest_incomplete_prefix


def _native_45m_expected(now, sessions):
    """TradingView's actual 09:45 + 45m grid includes the 18:00 auction row."""
    first = now.replace(hour=9, minute=45, second=0, microsecond=0)
    if now.date() in sessions and now >= first:
        final = now.replace(hour=18, minute=0, second=0, microsecond=0)
        cursor = min(now, final)
        opened = first + ((cursor - first) // timedelta(minutes=45)) * timedelta(minutes=45)
    else:
        previous = [day for day in sessions if day < now.date()]
        if not previous:
            raise ValueError("No previous BIST session in calendar")
        opened = datetime.combine(max(previous), datetime.min.time(), ISTANBUL).replace(hour=18)
    return opened, opened + timedelta(minutes=45)


def _prepare_native_45m(provider, member, *, observed_at, clock, bars):
    """Preserve provider-native 45m OHLCV, including genuine sparse auction bars.

    Missing native intervals are not reconstructed from smaller candles. Opens
    and nominal ends are preserved on TradingView's actual 09:45 grid. An 18:00
    auction bar has a nominal 18:45 end; that does NOT assert trading continued
    to 18:45 or identify its last trade. Only unpersisted formula evaluation may
    consume this frame; no exchange-confirmed candle status is inferred.
    """
    initial_sessions = _session_days(observed_at.year - 1, observed_at.year + 1)
    _, cutoff = _native_45m_expected(observed_at, initial_sessions)
    request = FetchRequest(provider_symbol=member.provider_symbol, timeframe=Timeframe.M45,
                           bars=min(5000, bars + 1), as_of=cutoff)
    raw = provider.fetch_native_grid(request)
    received_at = _aware(clock())
    if received_at < observed_at:
        raise ValueError("Clock moved backwards while fetching data")
    if raw.timeframe is not Timeframe.M45:
        raise ValueError("Native provider returned a different timeframe")
    if _symbol(raw.provider_symbol) != _symbol(member.provider_symbol):
        raise ValueError("Native provider returned a different instrument")
    if not raw.bars:
        raise ValueError("No authentic observed native candles")
    first_year = min(item.timestamp.year for item in raw.bars)
    sessions = _session_days(first_year, received_at.year + 1)
    nonregular = _nonregular_session_days(first_year, received_at.year + 1)
    expected_open, expected_close = _native_45m_expected(received_at, sessions)
    if expected_open.date() in nonregular:
        raise ValueError("Latest expected BIST session is a half-day/nonregular session; live adapter unsupported")
    native = []
    short_grid_dates = set()
    previous_open = None
    for item in raw.bars:
        stamp = item.timestamp
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Native grid requires timezone-aware candle timestamps")
        stamp = stamp.astimezone(ISTANBUL)
        opened = stamp if raw.timestamp_kind is TimestampKind.OPEN else stamp - timedelta(minutes=45)
        if opened > received_at:
            raise ValueError("Provider supplied a candle that starts after receipt")
        if opened.date() not in sessions:
            raise ValueError("Provider supplied a candle on a non-session date")
        grid_first, grid_final = (9, 45), (18, 0)
        if opened.date() in nonregular:
            short_grid = NATIVE_45M_HISTORICAL_SHORT_GRIDS.get(opened.date())
            if short_grid is None or opened.date() >= received_at.date():
                raise ValueError("Unsupported historical shortened-session native 45m grid")
            grid_first, grid_final = short_grid
            short_grid_dates.add(opened.date())
        first = opened.replace(hour=grid_first[0], minute=grid_first[1], second=0, microsecond=0)
        final = opened.replace(hour=grid_final[0], minute=grid_final[1], second=0, microsecond=0)
        if not first <= opened <= final or (opened - first) % timedelta(minutes=45):
            raise ValueError("Provider supplied a shifted native 45m candle")
        if previous_open is not None and opened <= previous_open:
            raise ValueError("Provider supplied duplicate or unordered native candle timestamps")
        previous_open = opened
        values = (item.open, item.high, item.low, item.close, item.volume)
        if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
               for value in values) or min(values[:4]) <= 0:
            raise ValueError("Native OHLCV values must be finite with positive OHLC prices")
        native.append(CanonicalBar(open_time=opened, close_time=opened + timedelta(minutes=45),
            open=float(item.open), high=float(item.high), low=float(item.low),
            close=float(item.close), volume=float(item.volume)))
    selected = tuple(native[-bars:])
    latest = selected[-1]
    current = latest.open_time == expected_open and latest.close_time == expected_close
    nominal_open = latest.open_time <= received_at < latest.close_time
    first_today = received_at.replace(hour=9, minute=45, second=0, microsecond=0)
    auction_end = received_at.replace(hour=18, minute=10, second=0, microsecond=0)
    during_session = received_at.date() in sessions and first_today <= received_at < auction_end
    native_age = max(0.0, (received_at - latest.close_time).total_seconds())
    # Some instruments have no actual 18:00 auction candle. Once the auction
    # window is over, their genuine 17:15-18:00 regular closing bar remains a
    # usable last observation. Preserve its exact times and OHLCV; do not
    # create, relabel or claim observation of an auction candle. Intraday age
    # limits are unchanged, and earlier sparse candles do not qualify.
    auction_open = expected_open.replace(hour=18, minute=0, second=0, microsecond=0)
    auction_observed = any(bar.open_time == auction_open for bar in selected)
    last_regular_close_no_auction = (
        not during_session and not auction_observed
        and latest.open_time == auction_open - timedelta(minutes=45)
        and latest.close_time == auction_open and received_at >= auction_open
    )
    usable = latest.open_time.date() == expected_open.date() and (
        native_age <= MAX_LATEST_NATIVE_AGE_MINUTES * 60 if during_session
        else current or last_regular_close_no_auction)
    status = ("stale_previous_session" if latest.open_time.date() < expected_open.date()
              else "last_regular_close_no_auction_candle" if last_regular_close_no_auction
              else "stale_previous_bucket" if not current
              else "live_open" if nominal_open or raw.last_bar_is_partial else "latest_closed")
    identity = stable_hash({"kind": "ATC_UNPERSISTED_NATIVE_45M_WHAT_IF_V1",
        "source_grid": NATIVE_45M_GRID, "instrument_id": member.instrument_id,
        "symbol": member.symbol, "timeframe": Timeframe.M45, "source": raw.provider,
        "price_basis": raw.price_basis, "received_at": received_at,
        "bars": selected, "quality": QUALITY})
    frame = CanonicalFrame(instrument_id=member.instrument_id, symbol_at_snapshot=member.symbol,
        market=member.market, timeframe=Timeframe.M45, snapshot_id=identity, series_revision=0,
        price_basis=raw.price_basis, source=raw.provider, bars=selected, is_partial=False, quality=QUALITY)
    metadata = {
        "quality": QUALITY, "status": status, "current_bucket": current,
        "usable_latest": usable, "source_grid": NATIVE_45M_GRID,
        "auction_observed": auction_observed,
        "native_bar_time_basis": "provider_nominal_interval_not_last_trade",
        "actual_bar_is_open": None, "actual_bar_confirmation": "unknown",
        "nominally_open": nominal_open, "temporally_open": nominal_open,
        "provider_partial_flag": raw.last_bar_is_partial,
        "observed_at": observed_at.isoformat(), "received_at": received_at.isoformat(),
        "request_cutoff": cutoff.isoformat(), "native_timeframe": Timeframe.M45.value,
        "last_bar_open": latest.open_time.isoformat(), "last_bar_close": latest.close_time.isoformat(),
        "latest_target_complete": received_at >= latest.close_time and not raw.last_bar_is_partial,
        "observed_prefix_end": latest.close_time.isoformat(),
        "expected_bucket_open": expected_open.isoformat(), "expected_bucket_close": expected_close.isoformat(),
        "expected_native_open": expected_open.isoformat(), "current_native_bucket": current,
        "target_bucket_present": current,
        "last_actual_native_open": latest.open_time.isoformat(),
        "last_actual_native_close": latest.close_time.isoformat(),
        "latest_native_age_limit_minutes": MAX_LATEST_NATIVE_AGE_MINUTES,
        "latest_native_close_age_seconds": native_age, "stale_bar_close_age_seconds": native_age,
        "last_trade_at": None, "price_delay_seconds": None,
        "bar_elapsed_seconds": max(0.0, (received_at - latest.open_time).total_seconds()),
        "history_bars": len(selected), "dropped_incomplete_history_buckets": 0,
        "session_truncated_bucket": False, "source": raw.provider,
        "price_basis": raw.price_basis.value, "persisted": False,
        "calendar_version": ExchangeCalendarsXist().version,
        "session_schedule": "BIST provider-native 45m 09:45-18:00 opens including auctions; nominal ends are not last-trade times",
        "nonregular_history_dates": sorted({bar.open_time.date().isoformat() for bar in selected
                                             if bar.open_time.date() in nonregular}),
        "historical_nonregular_close_times_nominal": any(bar.open_time.date() in nonregular for bar in selected),
        "historical_nonregular_native_grid_policies": [
            {"session": day.isoformat(), "anchor": "09:30", "last_open": "12:30",
             "policy": "verified_provider_native_45m_grid_on_calendar_short_session",
             "calendar_version": ExchangeCalendarsXist().version,
             "nominal_ends_are_not_last_trade_times": True}
            for day in sorted(short_grid_dates)],
    }
    return frame, metadata


def prepare_frame(
    provider, member, timeframe: Timeframe | str,
    now: datetime | Callable[[], datetime] | None = None, bars: int = 600,
) -> tuple[CanonicalFrame, dict]:
    """Fetch one same-source OHLCV window and return an unpersisted RAM frame.

    Production callers should omit ``now``; the clock is read before AND after
    each fetch. A callable permits controlled advancing-clock tests. A datetime
    freezes both observations for deterministic fixtures, not historical replay.
    A request cutoff at target-end merely avoids the vendor's closed-only
    filter; returned native candle opens are validated against actual receipt.
    """
    target = parse_timeframe(timeframe) if isinstance(timeframe, str) else timeframe
    if target not in SUPPORTED_TIMEFRAMES:
        raise ValueError("Live snapshot supports 15m/30m/45m/1h/2h/4h/1d/1wk")
    if not 1 <= bars <= 1250:
        raise ValueError("Requested target bars must be between 1 and 1250")
    if member.market != "BIST":
        raise ValueError("Live snapshot supports BIST only")
    clock = now if callable(now) else (
        (lambda: now) if now is not None else lambda: datetime.now(ISTANBUL)
    )
    observed_at = _aware(clock())
    if target is Timeframe.W1:
        from scripts.atc_live_weekly_frames import prepare_native_weekly

        return prepare_native_weekly(provider, member, observed_at=observed_at, clock=clock, bars=bars)
    if target is Timeframe.M45 and callable(getattr(provider, "fetch_native_grid", None)):
        return _prepare_native_45m(provider, member, observed_at=observed_at, clock=clock, bars=bars)
    if target in (Timeframe.M15, Timeframe.M30, Timeframe.H1, Timeframe.H2, Timeframe.H4) and callable(
            getattr(provider, "fetch_native_multihour", None)):
        from scripts.atc_live_multihour_frames import prepare_native_multihour

        return prepare_native_multihour(provider, member, timeframe=target,
            observed_at=observed_at, clock=clock, bars=bars)
    schedule = BistSessionSchedule()
    native = BASE_TIMEFRAME[target]
    # Let current mutable native data survive the provider's closed-only filter.
    # Never ask for a candle beyond this session's target bucket.
    session_end = schedule.session_bounds(observed_at.date())[1]
    if native is Timeframe.D1:
        cutoff = session_end
    elif schedule.session_bounds(observed_at.date())[0] <= observed_at < session_end:
        cutoff = _bucket(observed_at, target, schedule)[1]
    else:
        cutoff = observed_at
    factor = 1 if target is Timeframe.D1 else (target.minutes or 1) // (native.minutes or 1)
    request = FetchRequest(
        provider_symbol=member.provider_symbol, timeframe=native,
        bars=min(5000, bars * factor + factor), as_of=cutoff,
    )
    # Each validation is independent: a fallback never splices sources/bases.
    def build(raw):
        received_at = _aware(clock())
        if received_at < observed_at:
            raise ValueError("Clock moved backwards while fetching data")
        if raw.timeframe is not native:
            raise ValueError("Provider returned a different native timeframe")
        if _symbol(raw.provider_symbol) != _symbol(member.provider_symbol):
            raise ValueError("Provider returned a different instrument")
        first_year = min(item.timestamp.year for item in raw.bars)
        sessions = _session_days(first_year, received_at.year + 1)
        nonregular = _nonregular_session_days(first_year, received_at.year + 1)
        expected_open, expected_close = _expected_bucket(received_at, target, schedule, sessions)
        if expected_open.date() in nonregular:
            raise ValueError("Latest expected BIST session is a half-day/nonregular session; live adapter unsupported")
        base = _native_bars(raw, received_at=received_at, schedule=schedule, sessions=sessions)
        if not base:
            raise ValueError("No authentic observed native candles")
        derived, dropped, truncated, incomplete_prefix = _aggregate(
            base, source=native, target=target, received_at=received_at, schedule=schedule,
        )
        if not derived:
            raise ValueError("No authentic observed target candles")
        selected = derived[-bars:]
        latest = selected[-1]
        target_bucket_present = latest.open_time == expected_open and latest.close_time == expected_close
        expected_native_open, _ = _expected_bucket(received_at, native, schedule, sessions)
        native_current = base[-1].open_time == expected_native_open
        is_current = target_bucket_present and native_current
        temporal_open = latest.open_time <= received_at < latest.close_time
        # Native flag is additional vendor provenance, never a reason to drop
        # its actual row or to claim exchange confirmation.
        actual_open = temporal_open or raw.last_bar_is_partial
        target_complete = (base[-1].close_time == latest.close_time
                           and received_at >= latest.close_time and not raw.last_bar_is_partial)
        today_open, today_close = schedule.session_bounds(received_at.date())
        during_regular_session = received_at.date() in sessions and today_open <= received_at < today_close
        native_close_age = max(0.0, (received_at - base[-1].close_time).total_seconds())
        same_expected_session = base[-1].open_time.date() == expected_open.date()
        usable_latest = same_expected_session and (
            native_close_age <= MAX_LATEST_NATIVE_AGE_MINUTES * 60
            if during_regular_session else native_current
        )
        if incomplete_prefix:
            status = "incomplete_latest_native_prefix"
        elif latest.open_time.date() < expected_open.date():
            status = "stale_previous_session"
        elif target_bucket_present and not native_current:
            status = "stale_native_prefix"
        elif not is_current:
            status = "stale_previous_bucket"
        else:
            status = "live_open" if actual_open else "latest_closed"
        identity = stable_hash({
            "kind": "ATC_UNPERSISTED_LATEST_ACTUAL_WHAT_IF_V1",
            "instrument_id": member.instrument_id, "symbol": member.symbol,
            "timeframe": target, "source": raw.provider,
            "price_basis": raw.price_basis, "received_at": received_at,
            "bars": selected, "quality": QUALITY,
        })
        frame = CanonicalFrame(
            instrument_id=member.instrument_id, symbol_at_snapshot=member.symbol,
            market=member.market, timeframe=target, snapshot_id=identity,
            series_revision=0, price_basis=raw.price_basis, source=raw.provider,
            bars=selected, is_partial=False, quality=QUALITY,
        )
        metadata = {
            "quality": QUALITY, "status": status, "current_bucket": is_current,
            "usable_latest": usable_latest,
            "latest_native_age_limit_minutes": MAX_LATEST_NATIVE_AGE_MINUTES,
            "latest_native_close_age_seconds": native_close_age,
            "target_bucket_present": target_bucket_present, "current_native_bucket": native_current,
            "observed_at": observed_at.isoformat(), "received_at": received_at.isoformat(),
            "request_cutoff": cutoff.isoformat(), "native_timeframe": native.value,
            "provider_partial_flag": raw.last_bar_is_partial,
            "actual_bar_is_open": actual_open, "temporally_open": temporal_open,
            "last_bar_open": latest.open_time.isoformat(),
            "last_bar_close": latest.close_time.isoformat(),
            "latest_target_complete": target_complete,
            # Nominal end of the last ACTUAL native row, not a last-trade time
            # or an assertion that the remaining target interval was observed.
            "observed_prefix_end": base[-1].close_time.isoformat(),
            "expected_bucket_open": expected_open.isoformat(),
            "expected_bucket_close": expected_close.isoformat(),
            "expected_native_open": expected_native_open.isoformat(),
            "last_actual_native_open": base[-1].open_time.isoformat(),
            "last_actual_native_close": base[-1].close_time.isoformat(),
            "last_trade_at": None, "price_delay_seconds": None,
            "bar_elapsed_seconds": max(0.0, (received_at - latest.open_time).total_seconds()),
            "stale_bar_close_age_seconds": max(0.0, (received_at - latest.close_time).total_seconds()),
            "history_bars": len(selected), "dropped_incomplete_history_buckets": dropped,
            "session_truncated_bucket": truncated, "source": raw.provider,
            "price_basis": raw.price_basis.value, "persisted": False,
            "calendar_version": ExchangeCalendarsXist().version,
            "session_schedule": "BIST regular 10:00-18:00; exchange-calendars session dates",
            "nonregular_history_dates": sorted({bar.open_time.date().isoformat() for bar in base
                if bar.open_time.date() in nonregular}),
            "historical_nonregular_close_times_nominal": any(bar.open_time.date() in nonregular for bar in base),
        }
        return frame, metadata

    validated = getattr(provider, "fetch_validated", None)
    if callable(validated):
        result = {}
        def validate(raw):
            result[id(raw)] = build(raw)
        raw = validated(request, validate)
        return result[id(raw)]
    return build(provider.fetch(request))
