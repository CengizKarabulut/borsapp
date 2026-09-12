from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.providers import (
    FetchRequest,
    ProviderBar,
    ProviderFrame,
    TimestampKind,
)
from market_intelligence.scheduling.bist import BistSessionSchedule

PERIODS = {
    Timeframe.M5: "5d",
    Timeframe.M15: "1mo",
    Timeframe.M30: "1mo",
    Timeframe.H1: "3mo",
    Timeframe.D1: "5y",
}


class BorsapyProvider:
    name = "borsapy"

    def __init__(self, *, timestamp_timezone: str = "Europe/Istanbul") -> None:
        self.timestamp_timezone = timestamp_timezone
        self.schedule = BistSessionSchedule()

    def fetch(self, request: FetchRequest) -> ProviderFrame:
        if request.timeframe not in PERIODS:
            raise ValueError(
                f"borsapy doğrudan timeframe desteklemiyor: {request.timeframe}"
            )
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ValueError("FetchRequest.as_of timezone bilgisi içermelidir")
        try:
            import borsapy as bp
        except ImportError as exc:
            raise RuntimeError(
                "borsapy kurulu değil; runtime bağımlılıklarını yükleyin"
            ) from exc
        instrument = bp.Ticker(request.provider_symbol)
        data = instrument.history(
            period=self._history_period(request),
            interval=request.timeframe.value,
        )
        bars = self._completed_regular_bars(data, request)
        if not bars:
            raise RuntimeError(
                f"borsapy boş veri döndürdü: {request.provider_symbol}"
            )
        return ProviderFrame(
            provider=self.name,
            provider_symbol=request.provider_symbol,
            timeframe=request.timeframe,
            timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone=self.timestamp_timezone,
            price_basis=PriceBasis.SPLIT_ADJUSTED,
            bars=tuple(bars),
            last_bar_is_partial=False,
        )

    def _history_period(self, request: FetchRequest) -> str:
        if request.timeframe is Timeframe.D1:
            return "5y" if request.bars <= 1250 else "max"
        # Official borsapy period names; its fallback for unknown strings is only 30 days.
        daily_bars = 480 / request.timeframe.minutes
        required_days = (max(request.bars, 1) + 2) / daily_bars * 1.4
        for period, days in (("5d", 5), ("1mo", 30), ("3mo", 90), ("6mo", 180), ("1y", 365), ("2y", 730)):
            if days >= required_days:
                return period
        return "5y"

    def _completed_regular_bars(self, data: Any, request: FetchRequest) -> list[ProviderBar]:
        result = []
        cutoff = request.as_of.astimezone(self.schedule.timezone)
        for bar in self._convert(data):
            stamp = self._opened_at(bar.timestamp)
            opened, closed = self.schedule.session_bounds(stamp.date())
            if request.timeframe is not Timeframe.D1:
                duration = timedelta(minutes=request.timeframe.minutes or 0)
                # Reject shifted/vendor session buckets instead of relabelling their OHLC.
                if stamp < opened or stamp + duration > closed or (stamp - opened) % duration:
                    continue
                closed = stamp + duration
            if closed <= cutoff:
                result.append(bar)
        return result[-request.bars:] if request.bars > 0 else result

    def _opened_at(self, timestamp: datetime) -> datetime:
        timezone = ZoneInfo(self.timestamp_timezone)
        aware = timestamp.replace(tzinfo=timezone) if timestamp.tzinfo is None else timestamp
        return aware.astimezone(self.schedule.timezone)

    @staticmethod
    def _column_lookup(data: Any) -> dict[str, Any]:
        columns = data.columns
        if getattr(columns, "nlevels", 1) > 1:
            columns = [column[0] for column in columns]
            data.columns = columns
        return {str(column).strip().casefold(): column for column in columns}

    def _convert(self, data: Any) -> list[ProviderBar]:
        if data is None or getattr(data, "empty", True):
            return []
        lookup = self._column_lookup(data)
        required = ("open", "high", "low", "close")
        missing = [name for name in required if name not in lookup]
        if missing:
            raise ValueError("borsapy OHLC kolonları eksik: " + ", ".join(missing))
        volume_column = lookup.get("volume")
        bars: list[ProviderBar] = []
        for timestamp, row in data.iterrows():
            stamp = (
                timestamp.to_pydatetime()
                if hasattr(timestamp, "to_pydatetime")
                else timestamp
            )
            if not isinstance(stamp, datetime):
                raise ValueError("borsapy index datetime olmalıdır")
            bars.append(
                ProviderBar(
                    timestamp=stamp,
                    open=float(row[lookup["open"]]),
                    high=float(row[lookup["high"]]),
                    low=float(row[lookup["low"]]),
                    close=float(row[lookup["close"]]),
                    volume=float(row[volume_column]) if volume_column is not None else 0.0,
                )
            )
        return bars

    def _last_is_partial(
        self,
        timestamp: datetime,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> bool:
        timezone = ZoneInfo(self.timestamp_timezone)
        opened = timestamp.replace(tzinfo=timezone) if timestamp.tzinfo is None else timestamp
        opened = opened.astimezone(self.schedule.timezone)
        current = as_of.astimezone(self.schedule.timezone)
        if timeframe is Timeframe.D1:
            _session_open, closed = self.schedule.session_bounds(opened.date())
            return opened.date() == current.date() and current < closed
        duration = timedelta(minutes=timeframe.minutes or 0)
        return current < opened + duration
