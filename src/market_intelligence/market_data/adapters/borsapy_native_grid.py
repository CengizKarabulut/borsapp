"""Guarded anonymous native-45m access for RAM snapshots only.

borsapy 0.11.0 silently maps unknown intervals to daily bars. This isolated
subclass declares 45m explicitly and checks the actual outgoing series and
symbol-resolution messages. It never mutates the SDK's class/global mapping,
reads account credentials, or passes these bars through confirmed ingestion.
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
NATIVE_GRID_CONTRACT = "tradingview_native_45m_including_auctions"


class BorsapyNative45Provider(BorsapyProvider):
    name = "borsapy_native45"
    native_grid_contract = NATIVE_GRID_CONTRACT

    def __init__(self, *, sdk_client_class=None, sdk_version=None):
        super().__init__(timestamp_timezone="UTC")
        self._sdk_client_class = sdk_client_class
        self._sdk_version = sdk_version

    def fetch_native_grid(self, request: FetchRequest) -> ProviderFrame:
        if request.timeframe is not Timeframe.M45:
            raise ValueError("Guarded native-grid access supports only explicit 45m requests")
        if type(request.bars) is not int or not 1 <= request.bars <= 5000:
            raise ValueError("Native-grid bars must be between 1 and 5000")
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ValueError("Native-grid request must be timezone-aware")
        sdk_version = self._sdk_version or version("borsapy")
        if sdk_version not in SUPPORTED_SDK_VERSIONS:
            raise ValueError("Unsupported borsapy native-grid SDK version")
        sdk_base = self._sdk_client_class
        if sdk_base is None:
            from borsapy._providers.tradingview import TradingViewProvider

            sdk_base = TradingViewProvider
        if (not isinstance(getattr(sdk_base, "TIMEFRAMES", None), dict)
                or not all(callable(getattr(sdk_base, name, None))
                           for name in ("get_history", "_create_message", "_calculate_bars"))):
            raise ValueError("Unsupported borsapy native-grid SDK interface")
        symbol = request.provider_symbol.strip().upper()
        if symbol.endswith(".IS"):
            symbol = symbol[:-3]
        if ":" in symbol:
            prefix, symbol = symbol.split(":", 1)
            if prefix != "BIST":
                raise ValueError("Native-grid source supports BIST only")
        expected_symbol = f"BIST:{symbol}"
        requested_bars = request.bars

        class Native45Client(sdk_base):
            TIMEFRAMES = {**sdk_base.TIMEFRAMES, "45m": "45"}

            def __init__(self):
                super().__init__()
                self.verified_native_messages = set()

            def _get_auth_token(self):
                # Deliberately bypass the SDK's module-level account storage.
                return "unauthorized_user_token"

            def _calculate_bars(self, period, interval, start, end):
                if interval != "45m":
                    raise ValueError("Native-grid SDK attempted a different interval")
                return requested_bars

            def _create_message(self, method, params):
                if method == "set_auth_token":
                    if params != ["unauthorized_user_token"]:
                        raise ValueError("Native-grid source must remain anonymous")
                    self.verified_native_messages.add("anonymous")
                elif method == "resolve_symbol":
                    encoded = params[2] if len(params) >= 3 else None
                    if not isinstance(encoded, str) or not encoded.startswith("="):
                        raise ValueError("Native-grid SDK symbol resolution is unsupported")
                    config = json.loads(encoded[1:])
                    if (config.get("symbol") != expected_symbol
                            or config.get("adjustment") != "splits"
                            or config.get("session") != "regular"):
                        raise ValueError("Native-grid SDK changed symbol, price basis or session")
                    self.verified_native_messages.add("split_adjusted_regular_symbol")
                elif method == "create_series":
                    if len(params) < 6 or params[4] != "45" or params[5] != requested_bars:
                        raise ValueError("Native-grid SDK did not request actual 45m resolution")
                    self.verified_native_messages.add("resolution_45")
                return super()._create_message(method, params)

        client = Native45Client()
        try:
            data = client.get_history(symbol=symbol, interval="45m", period="1mo", exchange="BIST")
            if client.verified_native_messages != {
                "anonymous", "split_adjusted_regular_symbol", "resolution_45",
            }:
                raise ValueError("Native-grid SDK request was not independently verified")
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        if data is None or getattr(data, "empty", True):
            raise RuntimeError("Native-grid source returned no actual OHLCV")
        converted = self._convert(data)
        if any(bar.timestamp.tzinfo is None or bar.timestamp.utcoffset() is None for bar in converted):
            raise ValueError("Native-grid SDK must return timezone-aware timestamps")
        bars = tuple(sorted(converted, key=lambda bar: bar.timestamp))
        if len({bar.timestamp for bar in bars}) != len(bars):
            raise ValueError("Native-grid candles must have unique actual timestamps")
        # Preserve every actual open/auction bar. The RAM frame adapter checks
        # calendar, receipt and provider-grid bounds; this is not an as-of replay.
        return ProviderFrame(
            provider=self.name, provider_symbol=expected_symbol, timeframe=Timeframe.M45,
            timestamp_kind=TimestampKind.OPEN, timestamp_timezone="UTC",
            price_basis=PriceBasis.SPLIT_ADJUSTED,
            bars=tuple(ProviderBar(timestamp=bar.timestamp.astimezone(UTC),
                open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume)
                for bar in bars[-request.bars:]),
            last_bar_is_partial=False,
        )
