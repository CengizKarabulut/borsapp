"""Plan the latest due RAM snapshot, never replay historical open candles.

The ledger is a delivery watermark, not market data.  A delayed invocation
selects only the newest due slot per timeframe and reports intermediate slots
it missed.  Confirmed bars, database watermarks and trading are untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Europe/Istanbul")
SUPPORTED_TIMEFRAMES = ("15m", "30m", "45m", "1h", "2h", "4h", "1d", "1wk")
MINUTES = {"15m": 15, "30m": 30, "45m": 45, "1h": 60, "2h": 120, "4h": 240}
CHAT = -1004439315048
TOPICS = {"15m": 6, "30m": 11, "45m": 9, "1h": 28326,
          "2h": 10, "4h": 28327, "1d": 28328, "1wk": 28329}
LEDGER_SCHEMA = "atc-scheduled-delivery-v1"


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_aware_timestamp_required")
    return value.astimezone(IST)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid_delivery_timestamp")
    return _aware(datetime.fromisoformat(value))


class _XistCalendar:
    """Expose actual session bounds, including unsupported shortened sessions."""

    def __init__(self, start: date, end: date):
        import exchange_calendars

        self.calendar = exchange_calendars.get_calendar(
            # Weekly slots inspect the full earliest week, including dates
            # before a midweek watermark. Extra margin also keeps holiday
            # Mondays inside the calendar's actual first-session bounds.
            "XIST", start=(start - timedelta(days=14)).isoformat(),
            end=(end + timedelta(days=14)).isoformat(),
        )

    def sessions(self, start: date, end: date) -> tuple[date, ...]:
        return tuple(label.date() for label in self.calendar.sessions_in_range(
            start.isoformat(), end.isoformat(),
        ))

    def session_bounds(self, day: date) -> tuple[datetime, datetime]:
        return (
            self.calendar.session_open(day.isoformat()).to_pydatetime().astimezone(IST),
            self.calendar.session_close(day.isoformat()).to_pydatetime().astimezone(IST),
        )


def _bounds(calendar, day: date) -> tuple[datetime, datetime]:
    if hasattr(calendar, "session_bounds"):
        opened, closed = calendar.session_bounds(day)
        return _aware(opened), _aware(closed)
    # Small injected calendars may supply dates only.  Production always uses
    # the bound-aware XIST adapter above rather than assuming a full session.
    return datetime.combine(day, time(10), IST), datetime.combine(day, time(18), IST)


def _normal_session(opened: datetime, closed: datetime) -> bool:
    return opened.time() == time(10) and closed.time() == time(18)


def _scheduled_at(target: datetime, timeframe: str) -> datetime:
    # The final exchange pass is intentionally 18:30, including intraday bars
    # ending at 18:00; the normal intraday cron ends at 17:52.
    buffer = 30 if timeframe == "1d" or target.time() == time(18) else 7
    return target + timedelta(minutes=buffer)


def slot_key(timeframe: str, target: datetime) -> str:
    target = _aware(target)
    return f"{target.date().isoformat()}:{timeframe}:{target.isoformat()}"


def _slots(calendar, day: date, timeframe: str) -> list[tuple[datetime, datetime]]:
    opened, closed = _bounds(calendar, day)
    if not _normal_session(opened, closed):
        return []
    if timeframe == "1d":
        return [(closed, _scheduled_at(closed, timeframe))]
    if timeframe == "1wk":
        monday = day - timedelta(days=day.weekday())
        week = calendar.sessions(monday, monday + timedelta(days=6))
        return [(closed, _scheduled_at(closed, timeframe))] if week and day == max(week) else []
    target = opened + timedelta(minutes=MINUTES[timeframe])
    result = []
    while target <= closed:
        result.append((target, _scheduled_at(target, timeframe)))
        target += timedelta(minutes=MINUTES[timeframe])
    # A 45-minute cadence does not divide the regular eight-hour session.
    # Still observe the real closing auction in the final pass. This is a
    # logical snapshot slot, never a relabeling of the native 09:45 grid.
    if timeframe == "45m" and result[-1][0] != closed:
        result.append((closed, _scheduled_at(closed, timeframe)))
    return result


def validate_delivery_state(state: object) -> dict:
    """Reject malformed or unacknowledged state before it can suppress a scan."""
    if not isinstance(state, dict) or state.get("schema") != LEDGER_SCHEMA:
        raise ValueError("invalid_scheduled_delivery_schema")
    tf = state.get("timeframe")
    if tf not in SUPPORTED_TIMEFRAMES or state.get("sent") is not True:
        raise ValueError("unacknowledged_scheduled_delivery")
    if state.get("manual_only") is True:
        raise ValueError("manual_preview_cannot_advance_delivery_watermark")
    target = _parse_timestamp(state.get("target_close"))
    scheduled = _parse_timestamp(state.get("scheduled_at"))
    if (state.get("session") != target.date().isoformat()
            or state.get("slot_key") != slot_key(tf, target)
            or scheduled != _scheduled_at(target, tf)):
        raise ValueError("scheduled_delivery_slot_identity_mismatch")
    if target.time() < time(10) or target.time() > time(18):
        raise ValueError("scheduled_delivery_target_outside_session")
    if tf in ("1d", "1wk"):
        valid_target = target.time() == time(18)
    else:
        elapsed = (target - datetime.combine(target.date(), time(10), IST)).total_seconds()
        valid_target = (elapsed > 0 and elapsed % (60 * MINUTES[tf]) == 0
                        or tf == "45m" and target.time() == time(18))
    if not valid_target:
        raise ValueError("scheduled_delivery_target_not_on_timeframe_anchor")
    packet = state.get("packet_sha256")
    receipt = state.get("receipt")
    if not isinstance(packet, str) or not re.fullmatch(r"[a-f0-9]{64}", packet):
        raise ValueError("scheduled_delivery_packet_hash_required")
    if (not isinstance(receipt, dict) or receipt.get("status") != "sent"
            or receipt.get("chat_id") != CHAT or receipt.get("topic_id") != TOPICS[tf]
            or receipt.get("packet_sha256") != packet):
        raise ValueError("scheduled_delivery_receipt_identity_mismatch")
    acknowledgements = receipt.get("acknowledged")
    if (not isinstance(acknowledgements, dict)
            or set(acknowledgements) != {"text", "photo", "csv"}
            or any(type(value) is not int or value <= 0 for value in acknowledgements.values())):
        raise ValueError("scheduled_delivery_three_telegram_acknowledgements_required")
    return state


def load_delivered(directory: Path) -> dict[str, dict]:
    """A missing ledger is a first run; an existing malformed ledger fails closed."""
    result = {}
    for tf in SUPPORTED_TIMEFRAMES:
        path = directory / f"{tf}.json"
        if not path.exists():
            continue
        state = validate_delivery_state(json.loads(path.read_text(encoding="utf-8")))
        if state["timeframe"] != tf:
            raise ValueError(f"scheduled_delivery_filename_mismatch:{tf}")
        result[tf] = state
    return result


def plan(now: datetime, delivered=None, force_all: bool = False, calendar=None) -> dict:
    """Return newest due slots; ``force_all`` makes eight non-watermarking previews.

    ``target_close`` is a logical interval endpoint, never an observation claim.
    A manual current-period endpoint may lie in the future and is marked
    ``manual_only`` so it cannot suppress the later scheduled delivery.
    """
    now = _aware(now)
    delivered = {} if delivered is None else delivered
    if not isinstance(delivered, dict) or set(delivered) - set(SUPPORTED_TIMEFRAMES):
        raise ValueError("invalid_delivery_watermark_mapping")
    validated = {}
    for tf, state in delivered.items():
        validate_delivery_state(state)
        if state["timeframe"] != tf:
            raise ValueError("delivery_watermark_timeframe_mismatch")
        if _parse_timestamp(state["scheduled_at"]) > now:
            raise ValueError("delivery_watermark_is_in_the_future")
        validated[tf] = state
    earliest = min([now.date() - timedelta(days=21), *(
        _parse_timestamp(state["target_close"]).date() for state in validated.values()
    )])
    calendar = calendar or _XistCalendar(earliest, now.date())
    sessions = sorted(calendar.sessions(earliest, now.date()))
    started_sessions = [day for day in sessions if _bounds(calendar, day)[0] <= now]
    if not started_sessions:
        raise ValueError("no_prior_exchange_session_available")
    latest_session = started_sessions[-1]
    opened, closed = _bounds(calendar, latest_session)
    result = {
        "schema": "atc-snapshot-plan-v1", "status": "nothing_due",
        "observation_at": now.isoformat(), "session": latest_session.isoformat(),
        "entries": [], "timeframes": [],
        "observation_policy": "latest_actual_snapshot_only_no_historical_open_replay",
    }
    if not _normal_session(opened, closed):
        return {**result, "status": "unsupported_partial_session", "unsupported": {
            "reason": "RAM_snapshot_does_not_support_shortened_exchange_sessions",
            "session": latest_session.isoformat(), "open": opened.isoformat(),
            "close": closed.isoformat(),
        }}

    for tf in SUPPORTED_TIMEFRAMES:
        possible = [(target, scheduled) for day in started_sessions
                    for target, scheduled in _slots(calendar, day, tf) if scheduled <= now]
        watermark = None
        if tf in validated:
            watermark = _parse_timestamp(validated[tf]["target_close"])
        remaining = [(target, scheduled) for target, scheduled in possible
                     if watermark is None or target > watermark]
        if force_all:
            if opened <= now < closed:
                if tf in ("1d", "1wk"):
                    target = closed
                else:
                    duration = timedelta(minutes=MINUTES[tf])
                    target = min(opened + (int((now - opened) // duration) + 1) * duration, closed)
            else:
                target = closed if tf in ("1d", "1wk") else _slots(calendar, latest_session, tf)[-1][0]
            scheduled = _scheduled_at(target, tf)
            missed = 0
        elif remaining:
            target, scheduled = remaining[-1]
            # On first install report the selected session's missed slots,
            # rather than implying that weeks of historic open data were run.
            counted = remaining if watermark is not None else [
                pair for pair in remaining if pair[0].date() == target.date()
            ]
            missed = max(0, len(counted) - 1)
        else:
            continue
        entry = {
            "timeframe": tf, "slot_key": slot_key(tf, target),
            "session": target.date().isoformat(), "target_close": target.isoformat(),
            "scheduled_at": scheduled.isoformat(),
            "lateness_seconds": max(0, int((now - scheduled).total_seconds())),
            "missed_slot_count": missed,
        }
        if force_all:
            entry["manual_only"] = True
        result["entries"].append(entry)
    result["timeframes"] = [entry["timeframe"] for entry in result["entries"]]
    result["status"] = "ready" if result["entries"] else "nothing_due"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", type=Path, default=Path("runtime_artifacts/ledger"))
    parser.add_argument("--all", action="store_true", dest="force_all")
    parser.add_argument("--now", type=datetime.fromisoformat, help="Aware clock fixture; never market data")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = plan(args.now or datetime.now(IST), load_delivered(args.ledger_dir), args.force_all)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if output := os.getenv("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("matrix=" + json.dumps(result["entries"], separators=(",", ":")) + "\n")
            stream.write("timeframes=" + json.dumps(result["timeframes"]) + "\n")
            stream.write("plan_status=" + result["status"] + "\n")
    print(text)
    return result


if __name__ == "__main__":
    main()
