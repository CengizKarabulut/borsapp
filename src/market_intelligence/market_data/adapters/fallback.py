from __future__ import annotations

from market_intelligence.market_data.providers import (
    FetchRequest,
    MarketDataProvider,
    ProviderFrame,
)


class FallbackMarketDataProvider:
    """Try providers in order; returned frame retains the actual source identity."""

    name = "fallback_chain"

    def __init__(
        self, providers: tuple[MarketDataProvider, ...], *,
        prefer_complete_history: bool = False, cooldowns=None,
    ) -> None:
        if not providers:
            raise ValueError("En az bir market data provider gereklidir")
        self.providers = providers
        self.prefer_complete_history = prefer_complete_history
        self.cooldowns = cooldowns

    def _fetch(self, provider, request: FetchRequest) -> ProviderFrame:
        if self.cooldowns is not None and self.cooldowns.skip(
            provider.name, request.provider_symbol, request.timeframe.value
        ):
            raise RuntimeError(f"provider cooldown active: {provider.name}")
        try:
            frame = provider.fetch(request)
        except Exception as exc:
            # Never retry a known temporarily unavailable feed for every
            # timeframe/symbol within the cooldown period. A different
            # provider is still tried by the fallback chain.
            if self.cooldowns is not None:
                self.cooldowns.failed(
                    provider.name, request.provider_symbol,
                    request.timeframe.value, type(exc).__name__,
                )
            raise
        if self.cooldowns is not None:
            self.cooldowns.recovered(
                provider.name, request.provider_symbol, request.timeframe.value
            )
        return frame

    def fetch_from_source(self, source: str, request: FetchRequest) -> ProviderFrame:
        """Refresh a persisted canonical history from its OWN source only."""
        for provider in self.providers:
            if provider.name == source:
                return self._fetch(provider, request)
        raise RuntimeError(f"Source not configured: {source}")

    def fetch_validated(self, request: FetchRequest, validate) -> ProviderFrame:
        """Choose a REAL source that passes the caller's finished-bar rules.

        Long history is not useful if its OHLCV is inconsistent or the
        requested completed candle is absent. Try every independent vendor
        before admitting the symbol is unavailable; never merge price bases.
        """
        failures: list[str] = []
        best: ProviderFrame | None = None
        for provider in self.providers:
            try:
                frame = self._fetch(provider, request)
                validate(frame)
                if not self.prefer_complete_history:
                    return frame
                if best is None or len(frame.bars) > len(best.bars):
                    best = frame
                if len(frame.bars) >= request.bars:
                    return frame
            except Exception as exc:
                failures.append(f"{provider.name}:{type(exc).__name__}")
        if best is not None:
            return best
        raise RuntimeError(
            "No provider supplied an authentic, valid target candle: "
            + ", ".join(failures)
        )

    def fetch(self, request: FetchRequest) -> ProviderFrame:
        errors: list[str] = []
        best = None
        for provider in self.providers:
            try:
                frame = self._fetch(provider, request)
                if not self.prefer_complete_history:
                    return frame
                if best is None or len(frame.bars) > len(best.bars):
                    best = frame
                if len(frame.bars) >= request.bars:
                    return frame
            except Exception as exc:
                errors.append(f"{provider.name}:{type(exc).__name__}")
        if best is not None:
            return best  # Keep one source; short-history instruments remain usable.
        raise RuntimeError("Tüm market data provider'ları başarısız: " + ", ".join(errors))
