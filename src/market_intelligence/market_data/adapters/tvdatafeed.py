"""TradingView tvDatafeed history adapter for fallback market data.

Adapter is intentionally opt-in via runtime extra; do not require TradingView
credentials. No-login may be rate-limited or unavailable for individual symbols.
For GitHub's UTC runners, normalize naive tvDatafeed timestamps as UTC.
"""
from __future__ import annotations

from datetime import UTC
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.providers import (
    FetchRequest,
    ProviderFrame,
    TimestampKind,
)


class TvDatafeedBistProvider(BorsapyProvider):
    name = "tvdatafeed"

    _INTERVALS = {
        Timeframe.M5: "in_5_minute",
        Timeframe.M15: "in_15_minute",
        Timeframe.M30: "in_30_minute",
        Timeframe.H1: "in_1_hour",
        Timeframe.D1: "in_daily",
    }

    def __init__(self, *, client=None):
        # tvDatafeed's naive timestamps are UTC in our GitHub-hosted UTC runner.
        super().__init__(timestamp_timezone="UTC")
        self._client = client

    def fetch(self, request: FetchRequest) -> ProviderFrame:
        if request.timeframe not in self._INTERVALS:
            raise ValueError(f"tvDatafeed interval unsupported: {request.timeframe.value}")
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ValueError("FetchRequest.as_of must be timezone-aware")

        try:
            from tvDatafeed import Interval, TvDatafeed
        except ImportError as exc:
            raise RuntimeError("tvDatafeed not installed; optional atcdata extra required") from exc

        if self._client is None:
            # No secrets, no browser login. Optional fallback; free access
            # may be limited by the data origin / vendor's terms and rate limits.
            self._client = TvDatafeed()
        symbol = request.provider_symbol.strip().upper()
        if symbol.endswith(".IS"):
            symbol = symbol[:-3]
        if ":" in symbol:
            prefix, symbol = symbol.split(":", 1)
            if prefix != "BIST":
                raise ValueError(f"tvDatafeed non-BIST symbol: {request.provider_symbol}")
        interval = getattr(Interval, self._INTERVALS[request.timeframe])
        frame = self._client.get_hist(
            symbol=symbol,
            exchange="BIST",
            interval=interval,
            n_bars=min(max(request.bars + 1, 20), 5000),
        )
        if frame is None or getattr(frame, "empty", True):
            raise RuntimeError(f"tvDatafeed returned no OHLCV: BIST:{symbol}")

        # Explicitly convert inferred UTC-naive TradingView stamps into UTC-aware
        # values so that canonicalizer can apply Europe/Istanbul session bounds.
        frame = frame.copy()
        try:
            frame.index = frame.index.tz_localize(ZoneInfo("UTC"))
        except TypeError:
            frame.index = frame.index.tz_convert(UTC)
        bars = self._completed_regular_bars(frame, request)
        if not bars:
            raise RuntimeError(f"tvDatafeed returned no closed regular-session bars: BIST:{symbol}")
        return ProviderFrame(
            provider=self.name,
            provider_symbol=f"BIST:{symbol}",
            timeframe=request.timeframe,
            timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone="UTC",
            price_basis=PriceBasis.RAW,
            bars=tuple(bars),
            last_bar_is_partial=False,
        )
