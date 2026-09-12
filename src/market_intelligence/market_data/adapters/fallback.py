from __future__ import annotations

from market_intelligence.market_data.providers import (
    FetchRequest,
    MarketDataProvider,
    ProviderFrame,
)


class FallbackMarketDataProvider:
    """Try providers in order; returned frame retains the actual source identity."""

    name = "fallback_chain"

    def __init__(self, providers: tuple[MarketDataProvider, ...], *, prefer_complete_history: bool = False) -> None:
        if not providers:
            raise ValueError("En az bir market data provider gereklidir")
        self.providers = providers
        self.prefer_complete_history = prefer_complete_history

    def fetch(self, request: FetchRequest) -> ProviderFrame:
        errors: list[str] = []
        best = None
        for provider in self.providers:
            try:
                frame = provider.fetch(request)
                if not self.prefer_complete_history:
                    return frame
                if best is None or len(frame.bars) > len(best.bars):
                    best = frame
                if len(frame.bars) >= request.bars:
                    return frame
            except Exception as exc:
                errors.append(f"{provider.name}:{type(exc).__name__}")
        if best is not None:
            return best  # Keep a single source; short-history instruments remain usable.
        raise RuntimeError("Tüm market data provider'ları başarısız: " + ", ".join(errors))

