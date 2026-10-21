"""Guarded anonymous native 15/30/60/120/240-minute RAM OHLCV.

borsapy 0.11 lacks a 2h mapping and silently falls back to daily resolution for
unknown intervals. This local subclass explicitly declares both resolutions,
checks the outgoing messages, and never mutates SDK or account state.
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
RESOLUTIONS = {Timeframe.M15: "15", Timeframe.M30: "30", Timeframe.H1: "60",
               Timeframe.H2: "120", Timeframe.H4: "240"}


class BorsapyNativeMultihourProvider(BorsapyProvider):
    name = "borsapy_native_multihour"

    def __init__(self, *, sdk_client_class=None, sdk_version=None):
        super().__init__(timestamp_timezone="UTC")
        self._sdk_client_class = sdk_client_class
        self._sdk_version = sdk_version

    def fetch_native_multihour(self, request: FetchRequest) -> ProviderFrame:
        if request.timeframe not in RESOLUTIONS:
            raise ValueError("Native-multihour access supports only explicit 15m/30m/1h/2h/4h requests")
        if type(request.bars) is not int or not 1 <= request.bars <= 5000:
            raise ValueError("Native-multihour bars must be between 1 and 5000")
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ValueError("Native-multihour request must be timezone-aware")
        if (self._sdk_version or version("borsapy")) not in SUPPORTED_SDK_VERSIONS:
            raise ValueError("Unsupported borsapy native-multihour SDK version")
        sdk_base = self._sdk_client_class
        if sdk_base is None:
            from borsapy._providers.tradingview import TradingViewProvider

            sdk_base = TradingViewProvider
        if (not isinstance(getattr(sdk_base, "TIMEFRAMES", None), dict)
                or not all(callable(getattr(sdk_base, name, None))
                    for name in ("get_history", "_create_message", "_calculate_bars"))):
            raise ValueError("Unsupported borsapy native-multihour SDK interface")
        symbol = request.provider_symbol.strip().upper().removesuffix(".IS")
        if ":" in symbol:
            prefix, symbol = symbol.split(":", 1)
            if prefix != "BIST":
                raise ValueError("Native-multihour source supports BIST only")
        expected_symbol = f"BIST:{symbol}"
        requested_interval = request.timeframe.value
        resolution = RESOLUTIONS[request.timeframe]
        requested_bars = request.bars

        class NativeMultihourClient(sdk_base):
            TIMEFRAMES = {**sdk_base.TIMEFRAMES, **{tf.value: value for tf, value in RESOLUTIONS.items()}}

            def __init__(self):
                super().__init__()
                self.verified_native_messages = set()

            def _get_auth_token(self):
                return "unauthorized_user_token"

            def _calculate_bars(self, period, interval, start, end):
                if interval != requested_interval:
                    raise ValueError("Native-multihour SDK attempted a different interval")
                return requested_bars

            def _create_message(self, method, params):
                if method == "set_auth_token":
                    if params != ["unauthorized_user_token"]:
                        raise ValueError("Native-multihour source must remain anonymous")
                    self.verified_native_messages.add("anonymous")
                elif method == "resolve_symbol":
                    encoded = params[2] if len(params) >= 3 else None
                    if not isinstance(encoded, str) or not encoded.startswith("="):
                        raise ValueError("Native-multihour SDK symbol resolution is unsupported")
                    config = json.loads(encoded[1:])
                    if (config.get("symbol") != expected_symbol
                            or config.get("adjustment") != "splits"
                            or config.get("session") != "regular"):
                        raise ValueError("Native-multihour SDK changed symbol, price basis or session")
                    self.verified_native_messages.add("split_adjusted_regular_symbol")
                elif method == "create_series":
                    if len(params) < 6 or params[4] != resolution or params[5] != requested_bars:
                        raise ValueError("Native-multihour SDK did not request the exact native resolution")
                    self.verified_native_messages.add("resolution_native")
                return super()._create_message(method, params)

        client = NativeMultihourClient()
        try:
            data = client.get_history(symbol=symbol, interval=requested_interval, period="1mo", exchange="BIST")
            if client.verified_native_messages != {
                "anonymous", "split_adjusted_regular_symbol", "resolution_native",
            }:
                raise ValueError("Native-multihour SDK request was not independently verified")
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        if data is None or getattr(data, "empty", True):
            raise RuntimeError("Native-multihour source returned no actual OHLCV")
        if "volume" not in self._column_lookup(data):
            raise ValueError("Native-multihour source must supply actual volume")
        converted = self._convert(data)
        if any(bar.timestamp.tzinfo is None or bar.timestamp.utcoffset() is None for bar in converted):
            raise ValueError("Native-multihour SDK must return timezone-aware timestamps")
        bars = tuple(sorted(converted, key=lambda bar: bar.timestamp))
        if len({bar.timestamp for bar in bars}) != len(bars):
            raise ValueError("Native-multihour candles must have unique actual timestamps")
        return ProviderFrame(provider=self.name, provider_symbol=expected_symbol, timeframe=request.timeframe,
            timestamp_kind=TimestampKind.OPEN, timestamp_timezone="UTC", price_basis=PriceBasis.SPLIT_ADJUSTED,
            bars=tuple(ProviderBar(timestamp=bar.timestamp.astimezone(UTC), open=bar.open,
                high=bar.high, low=bar.low, close=bar.close, volume=bar.volume)
                for bar in bars[-request.bars:]), last_bar_is_partial=False)
