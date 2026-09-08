from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import Protocol

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scheduling.bist import BistSessionSchedule
from market_intelligence.scheduling.watermarks import WatermarkPlanner


class SessionCalendar(Protocol):
    @property
    def version(self) -> str: ...

    def sessions(self, start: date, end: date) -> tuple[date, ...]: ...


class ExchangeCalendarsXist:
    """Holiday-aware XIST session dates from the exchange-calendars project."""

    @property
    def version(self) -> str:
        try:
            package_version = version("exchange-calendars")
        except PackageNotFoundError:
            package_version = "missing"
        return f"exchange-calendars-xist:{package_version}"

    def sessions(self, start: date, end: date) -> tuple[date, ...]:
        try:
            import exchange_calendars
        except ImportError as exc:
            raise RuntimeError(
                "exchange-calendars kurulu değil; runtime bağımlılıklarını yükleyin"
            ) from exc
        calendar = exchange_calendars.get_calendar("XIST")
        labels = calendar.sessions_in_range(start.isoformat(), end.isoformat())
        return tuple(label.date() for label in labels)


@dataclass(frozen=True)
class ScheduledBarPlanner:
    calendar: SessionCalendar
    schedule: BistSessionSchedule = BistSessionSchedule()
    maximum_lookback_days: int = 7

    def due(
        self,
        *,
        timeframe: Timeframe,
        evaluation_time: datetime,
        watermark: datetime | None,
    ) -> tuple[datetime, ...]:
        if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
            raise ValueError("evaluation_time timezone bilgisi içermelidir")
        if self.maximum_lookback_days < 1:
            raise ValueError("maximum_lookback_days pozitif olmalıdır")
        earliest = evaluation_time.date() - timedelta(days=self.maximum_lookback_days)
        start = max(earliest, watermark.date()) if watermark is not None else earliest
        closed: list[datetime] = []
        for session_date in self.calendar.sessions(start, evaluation_time.date()):
            closed.extend(self.schedule.bar_closes(session_date, timeframe))
        due = WatermarkPlanner().due(
            closed_bar_times=tuple(closed),
            evaluation_time=evaluation_time,
            watermark=watermark,
        )
        # İlk kurulumda geçmiş tarihler için point-in-time evren üyeliği
        # bilinmez. Watermark yokken günlerce geriye yürümek hem yeni eklenen
        # evreni geçmişte boş gösterir hem de yüzlerce sembolde gereksiz yük
        # üretir. İlk tur yalnız en yeni kapanmış barı işler; bundan sonraki
        # eksikler kalıcı watermark üzerinden eksiksiz yakalanır.
        if watermark is None and due:
            return (due[-1],)
        return due
