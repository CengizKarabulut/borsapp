"""Schedule eight real ATC scanners without touching cloud PostgreSQL.

Each intraday cron checks the exchange's real completed bars. The 18:30
Istanbul close pass computes all seven daily timeframe snapshots; the weekly
snapshot is included only on the final trading session of the week.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scheduling.bist import BistSessionSchedule
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_due_timeframes import due_timeframes

ISTANBUL = ZoneInfo("Europe/Istanbul")
INTRADAY = ("15m", "30m", "45m", "1h", "2h", "4h")
EVERY = (*INTRADAY, "1d", "1wk")


def select_timeframes(now: datetime, *, all_scans: bool = False, calendar=None):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware current time required")
    local = now.astimezone(ISTANBUL)
    if all_scans:
        return EVERY
    calendar = calendar or ExchangeCalendarsXist()
    today = local.date()
    if today not in calendar.sessions(today, today):
        return ()
    _open, close = BistSessionSchedule().session_bounds(today)
    # Whole-of-day close digest; 45m candles end 17:30, not 18:00.
    if close + timedelta(minutes=20) <= local <= close + timedelta(minutes=85):
        selections = (*INTRADAY, "1d")
        monday = today - timedelta(days=today.weekday())
        friday_window = calendar.sessions(monday, monday + timedelta(days=6))
        return (*selections, "1wk") if friday_window and today == friday_window[-1] else selections
    return tuple(tf for tf in due_timeframes(local, calendar) if tf in INTRADAY)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", dest="all_scans")
    args = parser.parse_args()
    found = select_timeframes(datetime.now(ISTANBUL), all_scans=args.all_scans)
    print("ATC ephemeral real closed timeframes:", ", ".join(found) or "none", flush=True)
    if output := os.getenv("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as file:
            file.write("timeframes=" + json.dumps(found) + "\n")
            file.write("is_eod=" + ("true" if "1d" in found else "false") + "\n")


if __name__ == "__main__":
    main()
