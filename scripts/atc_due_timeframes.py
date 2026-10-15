"""Select only intervals with a newly closed real BIST bar for the schedule.

This lightweight routing decision must never invent market observations.
The actual scan-due command still uses persisted watermarks and exchange data.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scheduling.bist import BistSessionSchedule
from market_intelligence.scheduling.xist import ExchangeCalendarsXist

ISTANBUL = ZoneInfo("Europe/Istanbul")
SCANNED = (
    Timeframe.M15, Timeframe.M30, Timeframe.M45, Timeframe.H1,
    Timeframe.H2, Timeframe.H4, Timeframe.D1, Timeframe.W1,
)


def due_timeframes(now: datetime, calendar=None) -> tuple[str, ...]:
    """Filter matrix launch; scanners decide whether watermarks are actually due."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    local = now.astimezone(ISTANBUL)
    calendar = calendar or ExchangeCalendarsXist()
    today = local.date()
    if today not in calendar.sessions(today, today):
        return ()
    schedule = BistSessionSchedule()
    _, market_close = schedule.session_bounds(today)
    # 18:30 scheduled close pass also covers 18:00 interval candles.
    final_pass = market_close + timedelta(minutes=20) <= local <= (
        market_close + timedelta(minutes=100)
    )
    if final_pass:
        eligible = [
            tf.value for tf in SCANNED
            if tf not in (Timeframe.D1, Timeframe.W1)
            and market_close in schedule.bar_closes(today, tf)
        ]
        eligible.append(Timeframe.D1.value)
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        weekly_sessions = calendar.sessions(monday, sunday)
        if weekly_sessions and weekly_sessions[-1] == today:
            eligible.append(Timeframe.W1.value)
        return tuple(eligible)

    if not schedule.session_bounds(today)[0] <= local <= market_close + timedelta(
        minutes=19
    ):
        return ()
    recent_cutoff = local - timedelta(minutes=12)
    return tuple(
        tf.value for tf in SCANNED
        if tf not in (Timeframe.D1, Timeframe.W1)
        and any(
            recent_cutoff <= bar_close <= local
            for bar_close in schedule.bar_closes(today, tf)
        )
    )


def main() -> None:
    selected = due_timeframes(datetime.now(ISTANBUL))
    print(f"Scheduled ATC newly closed timeframes: {', '.join(selected) or 'none'}")
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("timeframes=" + json.dumps(selected) + "\n")


if __name__ == "__main__":
    main()
