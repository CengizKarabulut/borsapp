"""TradingView tvDatafeed history adapter for fallback market data.

Adapter is intentionally opt-in via runtime extra; do not require TradingView
credentials. No-login may be rate-limited or unavailable for individual symbols.
The SDK constructs naive datetimes with ``datetime.fromtimestamp``: they are
host-local, not unconditionally UTC. Normalize actual instants before filtering.
Native 45m access is opt-in and preserves the provider's auction-inclusive grid.
"""
from __future__ import annotations

from datetime import UTC, datetime
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
    native_grid_contract = "tradingview_native_45m_including_auctions"
    native_weekly_contract = "tradingview_native_calendar_week"

    _INTERVALS = {
        Timeframe.M5: "in_5_minute",
        Timeframe.M15: "in_15_minute",
        Timeframe.M30: "in_30_minute",
        Timeframe.M45: "in_45_minute",
        Timeframe.H1: "in_1_hour",
        Timeframe.H2: "in_2_hour",
        Timeframe.H4: "in_4_hour",
        Timeframe.D1: "in_daily",
        Timeframe.W1: "in_weekly",
    }

    def __init__(self, *, client=None, naive_timestamp_timezone: str | None = None):
        super().__init__(timestamp_timezone="UTC")
        self._client = client
        # Injected fixtures/clients may explicitly declare their naive clock.
        # The real SDK uses the process's local timezone on each source date.
        self._naive_timestamp_timezone = (
            ZoneInfo(naive_timestamp_timezone) if naive_timestamp_timezone is not None else None
        )

    def fetch(self, request: FetchRequest) -> ProviderFrame:
        if request.timeframe is Timeframe.M45:
            raise ValueError("Native 45m requires explicit native-grid RAM access")
        if request.timeframe is Timeframe.W1:
            raise ValueError("Native W1 requires explicit native-weekly RAM access")
        if request.timeframe in (Timeframe.H2, Timeframe.H4):
            raise ValueError("Native 2h/4h requires explicit native-multihour RAM access")
        symbol, frame = self._download(request)
        bars = self._completed_regular_bars(frame, request)
        if not bars:
            raise RuntimeError(f"tvDatafeed returned no closed regular-session bars: BIST:{symbol}")
        return self._provider_frame(request, symbol, bars)

    def fetch_native_grid(self, request: FetchRequest) -> ProviderFrame:
        """Return actual 45m bars without reanchoring or filling empty periods.

        This is not the confirmed-bar ingestion API. The RAM caller validates
        receipt times, native grid and auction-session bounds independently.
        ``as_of`` does not turn the current vendor response into historical data.
        """
        if request.timeframe is not Timeframe.M45:
            raise ValueError("Native-grid access supports only explicit 45m requests")
        if type(request.bars) is not int or not 1 <= request.bars <= 5000:
            raise ValueError("Native-grid bars must be between 1 and 5000")
        symbol, frame = self._download(request, native_grid=True)
        bars = sorted(self._convert(frame), key=lambda bar: bar.timestamp)
        if not bars or len({bar.timestamp for bar in bars}) != len(bars):
            raise ValueError("Native-grid candles must have unique actual timestamps")
        return self._provider_frame(request, symbol, bars[-request.bars:])

    def fetch_native_weekly(self, request: FetchRequest) -> ProviderFrame:
        """Preserve actual mutable W1 OHLCV and provider weekly start labels.

        The weekly label is not a last-trade timestamp. Only the separate RAM
        weekly adapter may evaluate its calendar-week cohort eligibility.
        """
        if request.timeframe is not Timeframe.W1:
            raise ValueError("Native-weekly access supports only explicit W1 requests")
        if type(request.bars) is not int or not 1 <= request.bars <= 5000:
            raise ValueError("Native-weekly bars must be between 1 and 5000")
        symbol, frame = self._download(request, native_grid=True)
        if "volume" not in self._column_lookup(frame):
            raise ValueError("Native-weekly source must supply actual volume")
        bars = sorted(self._convert(frame), key=lambda bar: bar.timestamp)
        if not bars or len({bar.timestamp for bar in bars}) != len(bars):
            raise ValueError("Native-weekly candles must have unique actual timestamps")
        return self._provider_frame(request, symbol, bars[-request.bars:])

    def fetch_native_multihour(self, request: FetchRequest) -> ProviderFrame:
        """Preserve actual native intraday OHLCV, including opening/closing auctions.

        Compatibility name retained; confirmed ``fetch`` keeps its existing
        regular-session contract. Only explicit RAM access is extended here.
        """
        if request.timeframe not in (Timeframe.M15, Timeframe.M30, Timeframe.H1, Timeframe.H2, Timeframe.H4):
            raise ValueError("Native-multihour access supports only explicit 15m/30m/1h/2h/4h requests")
        if type(request.bars) is not int or not 1 <= request.bars <= 5000:
            raise ValueError("Native-multihour bars must be between 1 and 5000")
        symbol, frame = self._download(request, native_grid=True)
        if "volume" not in self._column_lookup(frame):
            raise ValueError("Native-multihour source must supply actual volume")
        bars = sorted(self._convert(frame), key=lambda bar: bar.timestamp)
        if not bars or len({bar.timestamp for bar in bars}) != len(bars):
            raise ValueError("Native-multihour candles must have unique actual timestamps")
        return self._provider_frame(request, symbol, bars[-request.bars:])

    def _download(self, request: FetchRequest, *, native_grid=False):
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
            n_bars=min(max(request.bars + (0 if native_grid else 1), 20), 5000),
        )
        if frame is None or getattr(frame, "empty", True):
            raise RuntimeError(f"tvDatafeed returned no OHLCV: BIST:{symbol}")

        # SDK datetime.fromtimestamp(epoch) returns host-local naive values.
        # A fixed UTC assumption shifts Windows data three hours into the future.
        import pandas as pd

        frame = frame.copy()
        timestamps = []
        for value in frame.index:
            stamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
            if not isinstance(stamp, datetime):
                raise ValueError("tvDatafeed index must contain actual datetime timestamps")
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                if self._naive_timestamp_timezone is not None:
                    stamp = stamp.replace(tzinfo=self._naive_timestamp_timezone)
                # Without an explicit fixture clock, astimezone interprets the
                # naive value in the host's historical local timezone.
            timestamps.append(stamp.astimezone(UTC))
        frame.index = pd.DatetimeIndex(timestamps)
        return symbol, frame

    def _provider_frame(self, request, symbol, bars):
        return ProviderFrame(
            provider=self.name,
            provider_symbol=f"BIST:{symbol}",
            timeframe=request.timeframe,
            timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone="UTC",
            # tvDatafeed.get_hist resolves the symbol with adjustment="splits".
            price_basis=PriceBasis.SPLIT_ADJUSTED,
            bars=tuple(bars),
            last_bar_is_partial=False,
        )
