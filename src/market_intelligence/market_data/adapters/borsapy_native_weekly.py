"""Guarded anonymous native W1 access exclusively for RAM weekly snapshots.

Verify the actual SDK message requests 1W, split-adjusted regular-session
prices. Do not use the SDK's unknown-interval daily fallback, account storage,
or the closed daily-to-weekly ingestion path.
"""
from __future__ import annotations

import json
from datetime import UTC
from importlib.metadata import version

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.providers import (
    FetchRequest,
    ProviderBar,
    ProviderFrame,
    TimestampKind,
)

SUPPORTED_SDK_VERSIONS = frozenset({"0.11.0"})
NATIVE_WEEKLY_CONTRACT = "tradingview_native_calendar_week"


class BorsapyNativeWeeklyProvider(BorsapyProvider):
    name = "borsapy_native_weekly"
    native_weekly_contract = NATIVE_WEEKLY_CONTRACT

    def __init__(self, *, sdk_client_class=None, sdk_version=None):
        super().__init__(timestamp_timezone="UTC")
        self._sdk_client_class = sdk_client_class
        self._sdk_version = sdk_version

    def fetch_native_weekly(self, request: FetchRequest) -> ProviderFrame:
        if request.timeframe is not Timeframe.W1:
            raise ValueError("Native-weekly access supports only explicit W1 requests")
        if type(request.bars) is not int or not 1 <= request.bars <= 5000:
            raise ValueError("Native-weekly bars must be between 1 and 5000")
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ValueError("Native-weekly request must be timezone-aware")
        if (self._sdk_version or version("borsapy")) not in SUPPORTED_SDK_VERSIONS:
            raise ValueError("Unsupported borsapy native-weekly SDK version")
        sdk_base = self._sdk_client_class
        if sdk_base is None:
            from borsapy._providers.tradingview import TradingViewProvider

            sdk_base = TradingViewProvider
        if (not isinstance(getattr(sdk_base, "TIMEFRAMES", None), dict)
                or sdk_base.TIMEFRAMES.get("1wk") != "1W"
                or not all(callable(getattr(sdk_base, name, None))
                    for name in ("get_history", "_create_message", "_calculate_bars"))):
            raise ValueError("Unsupported borsapy native-weekly SDK interface")
        symbol = request.provider_symbol.strip().upper().removesuffix(".IS")
        if ":" in symbol:
            prefix, symbol = symbol.split(":", 1)
            if prefix != "BIST":
                raise ValueError("Native-weekly source supports BIST only")
        expected_symbol = f"BIST:{symbol}"
        requested_bars = request.bars

        class NativeWeeklyClient(sdk_base):
            def __init__(self):
                super().__init__()
                self.verified_native_messages = set()

            def _get_auth_token(self):
                return "unauthorized_user_token"

            def _calculate_bars(self, period, interval, start, end):
                if interval != "1wk":
                    raise ValueError("Native-weekly SDK attempted a different interval")
                return requested_bars

            def _create_message(self, method, params):
                if method == "set_auth_token":
                    if params != ["unauthorized_user_token"]:
                        raise ValueError("Native-weekly source must remain anonymous")
                    self.verified_native_messages.add("anonymous")
                elif method == "resolve_symbol":
                    encoded = params[2] if len(params) >= 3 else None
                    if not isinstance(encoded, str) or not encoded.startswith("="):
                        raise ValueError("Native-weekly SDK symbol resolution is unsupported")
                    config = json.loads(encoded[1:])
                    if (config.get("symbol") != expected_symbol
                            or config.get("adjustment") != "splits"
                            or config.get("session") != "regular"):
                        raise ValueError("Native-weekly SDK changed symbol, price basis or session")
                    self.verified_native_messages.add("split_adjusted_regular_symbol")
                elif method == "create_series":
                    if len(params) < 6 or params[4] != "1W" or params[5] != requested_bars:
                        raise ValueError("Native-weekly SDK did not request actual 1W resolution")
                    self.verified_native_messages.add("resolution_1W")
                return super()._create_message(method, params)

        client = NativeWeeklyClient()
        try:
            data = client.get_history(symbol=symbol, interval="1wk", period="1mo", exchange="BIST")
            if client.verified_native_messages != {
                "anonymous", "split_adjusted_regular_symbol", "resolution_1W",
            }:
                raise ValueError("Native-weekly SDK request was not independently verified")
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        if data is None or getattr(data, "empty", True):
            raise RuntimeError("Native-weekly source returned no actual OHLCV")
        if "volume" not in self._column_lookup(data):
            raise ValueError("Native-weekly source must supply actual volume")
        converted = self._convert(data)
        if any(bar.timestamp.tzinfo is None or bar.timestamp.utcoffset() is None for bar in converted):
            raise ValueError("Native-weekly SDK must return timezone-aware timestamps")
        bars = tuple(sorted(converted, key=lambda bar: bar.timestamp))
        if len({bar.timestamp for bar in bars}) != len(bars):
            raise ValueError("Native-weekly candles must have unique actual timestamps")
        return ProviderFrame(provider=self.name, provider_symbol=expected_symbol, timeframe=Timeframe.W1,
            timestamp_kind=TimestampKind.OPEN, timestamp_timezone="UTC", price_basis=PriceBasis.SPLIT_ADJUSTED,
            bars=tuple(ProviderBar(timestamp=bar.timestamp.astimezone(UTC), open=bar.open,
                high=bar.high, low=bar.low, close=bar.close, volume=bar.volume)
                for bar in bars[-request.bars:]), last_bar_is_partial=False)
