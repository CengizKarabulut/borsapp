from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.providers import (
    FetchRequest,
    ProviderFrame,
    TimestampKind,
)

INTERVALS = {
    Timeframe.M5: ("5d", "5m"),
    Timeframe.M15: ("60d", "15m"),
    Timeframe.M30: ("60d", "30m"),
    Timeframe.H1: ("730d", "60m"),
    Timeframe.D1: ("5y", "1d"),
}


class YFinanceBistProvider(BorsapyProvider):
    name = "yfinance"

    def fetch(self, request: FetchRequest) -> ProviderFrame:
        if request.timeframe not in INTERVALS:
            raise ValueError(f"yfinance doğrudan timeframe desteklemiyor: {request.timeframe}")
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ValueError("FetchRequest.as_of timezone bilgisi içermelidir")
        import yfinance as yf

        period, interval = INTERVALS[request.timeframe]
        symbol = request.provider_symbol.strip().upper()
        yahoo_symbol = symbol if symbol.endswith(".IS") else f"{symbol}.IS"
        data = yf.Ticker(yahoo_symbol).history(
            period=period,
            interval=interval,
            auto_adjust=False,
            actions=False,
        )
        bars = [
            bar
            for bar in self._convert(data)
            if self._opened_at(bar.timestamp)
            <= request.as_of.astimezone(self.schedule.timezone)
        ]
        bars = bars[-request.bars :] if request.bars > 0 else bars
        if not bars:
            raise RuntimeError(f"yfinance boş veri döndürdü: {yahoo_symbol}")
        return ProviderFrame(
            provider=self.name,
            provider_symbol=yahoo_symbol,
            timeframe=request.timeframe,
            timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone=self.timestamp_timezone,
            price_basis=PriceBasis.RAW,
            bars=tuple(bars),
            last_bar_is_partial=self._last_is_partial(
                bars[-1].timestamp,
                request.timeframe,
                request.as_of,
            ),
        )

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
        return current < opened + timedelta(minutes=timeframe.minutes or 0)
