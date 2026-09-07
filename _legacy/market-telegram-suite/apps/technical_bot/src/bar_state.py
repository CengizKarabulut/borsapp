from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

MARKET_SESSIONS = {
    "BIST": ("Europe/Istanbul", time(9, 40), time(18, 10)),
    "US": ("America/New_York", time(9, 30), time(16, 0)),
}


def build_bar_state(
    data: pd.DataFrame,
    market: str,
    interval: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_market = market.upper()
    timezone_name, session_open, session_close = MARKET_SESSIONS.get(
        resolved_market,
        ("UTC", time(0, 0), time(0, 0)),
    )
    timezone = ZoneInfo(timezone_name)
    current = now or datetime.now(timezone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone)
    else:
        current = current.astimezone(timezone)

    timestamp = pd.Timestamp(data.index[-1])
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone_name)
    else:
        timestamp = timestamp.tz_convert(timezone_name)

    weekday_session = current.weekday() < 5
    market_open = weekday_session and session_open <= current.time().replace(tzinfo=None) < session_close
    same_session_date = timestamp.date() == current.date()
    if interval == "1d":
        is_live = bool(market_open and same_session_date)
    else:
        durations = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}
        minutes = durations.get(interval)
        if minutes:
            is_live = bool(same_session_date and market_open and current < timestamp.to_pydatetime() + pd.Timedelta(minutes=minutes))
        elif interval == "1wk":
            # Haftalık/aylık barlar dönem dolmadan tamamlanmaz; piyasa kapalıyken de
            # devam eden bir haftanın barı "teyitli" sayılmamalıdır.
            is_live = pd.Timestamp(current).isocalendar()[:2] == timestamp.isocalendar()[:2]
        elif interval == "1mo":
            is_live = (current.year, current.month) == (timestamp.year, timestamp.month)
        else:
            is_live = False

    return {
        "is_live": is_live,
        "is_confirmed": not is_live,
        "label": "CANLI" if is_live else "TEYİTLİ",
        "exchange": resolved_market,
        "bar_time": timestamp.isoformat(),
        "market_state": "OPEN" if market_open else "CLOSED",
        "session_timezone": timezone_name,
        "session": f"{session_open.strftime('%H:%M')}–{session_close.strftime('%H:%M')}",
        "interval": interval,
        "method": "Hafta içi düzenli seans saatleri; resmi tatil/tatil yarım gün takvimi içermez.",
    }
