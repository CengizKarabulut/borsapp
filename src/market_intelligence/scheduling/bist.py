from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe


class PartialBarPolicy(StrEnum):
    DROP = "drop"
    INCLUDE_PROVISIONAL = "include_provisional"


@dataclass(frozen=True)
class BistSessionSchedule:
    """Generate bar closes from the session anchor, never from wall-clock modulo."""

    timezone_name: str = "Europe/Istanbul"
    open_time: time = time(10, 0)
    close_time: time = time(18, 0)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def session_bounds(self, session_date: date) -> tuple[datetime, datetime]:
        opened = datetime.combine(session_date, self.open_time, self.timezone)
        closed = datetime.combine(session_date, self.close_time, self.timezone)
        if closed <= opened:
            raise ValueError("Seans kapanışı açılıştan sonra olmalıdır")
        return opened, closed

    def bar_closes(
        self,
        session_date: date,
        timeframe: Timeframe,
        *,
        partial_policy: PartialBarPolicy = PartialBarPolicy.DROP,
    ) -> tuple[datetime, ...]:
        opened, closed = self.session_bounds(session_date)
        if timeframe is Timeframe.D1:
            return (closed,)
        if not timeframe.is_intraday:
            raise ValueError(
                "Haftalık/aylık kapanış için point-in-time işlem takvimi gerekir"
            )
        duration = timedelta(minutes=timeframe.minutes or 0)
        cursor = opened + duration
        result: list[datetime] = []
        while cursor <= closed:
            result.append(cursor)
            cursor += duration
        if partial_policy is PartialBarPolicy.INCLUDE_PROVISIONAL:
            last_start = result[-1] if result else opened
            if last_start < closed and (not result or result[-1] != closed):
                result.append(closed)
        return tuple(result)
