from __future__ import annotations

from market_intelligence.market_data.providers import (
    FetchRequest,
    MarketDataProvider,
    ProviderFrame,
)


class FallbackMarketDataProvider:
    """Try providers in order; returned frame retains the actual source identity."""

    name = "fallback_chain"

    def __init__(self, providers: tuple[MarketDataProvider, ...]) -> None:
        if not providers:
            raise ValueError("En az bir market data provider gereklidir")
        self.providers = providers

    def fetch(self, request: FetchRequest) -> ProviderFrame:
        errors: list[str] = []
        for provider in self.providers:
            try:
                return provider.fetch(request)
            except Exception as exc:
                errors.append(f"{provider.name}:{type(exc).__name__}")
        raise RuntimeError("Tüm market data provider'ları başarısız: " + ", ".join(errors))

