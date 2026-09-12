from __future__ import annotations

import unittest
from datetime import UTC, datetime

from market_intelligence.fundamentals.providers import (
    FinancialProviderChain,
    FinancialSnapshot,
)
from market_intelligence.market_data.adapters.fallback import FallbackMarketDataProvider
from market_intelligence.market_data.providers import FetchRequest, ProviderFrame


class BrokenMarketProvider:
    name = "broken"

    def fetch(self, request):
        raise RuntimeError("provider down")


class WorkingMarketProvider:
    name = "working"

    def __init__(self, frame: ProviderFrame) -> None:
        self.frame = frame

    def fetch(self, request):
        return self.frame


class StubFinancialProvider:
    def __init__(self, provider_id: str, metrics: dict[str, float | None]) -> None:
        self.provider_id = provider_id
        self.metrics = metrics

    def fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot:
        return FinancialSnapshot(
            symbol=symbol,
            as_of=as_of,
            company_name=None,
            sector=None,
            currency="TRY",
            metrics=self.metrics,
            metric_sources={key: self.provider_id for key, value in self.metrics.items() if value is not None},
            statement_periods=("2026-06-30",),
            providers_used=(self.provider_id,),
        )


class ProviderFallbackTests(unittest.TestCase):
    def test_market_chain_returns_actual_fallback_frame(self) -> None:
        frame = object()
        chain = FallbackMarketDataProvider((BrokenMarketProvider(), WorkingMarketProvider(frame)))

        result = chain.fetch(FetchRequest("ASELS", "1d", 20, datetime.now(UTC)))

        self.assertIs(result, frame)

    def test_financial_chain_only_fills_missing_primary_fields(self) -> None:
        chain = FinancialProviderChain(
            (
                StubFinancialProvider("primary", {"revenue_ttm": 100.0, "equity": None}),
                StubFinancialProvider("fallback", {"revenue_ttm": 999.0, "equity": 40.0}),
            )
        )

        result = chain.fetch("ASELS", as_of=datetime(2026, 9, 7, tzinfo=UTC))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.metrics["revenue_ttm"], 100.0)
        self.assertEqual(result.metric_sources["revenue_ttm"], "primary")
        self.assertEqual(result.metrics["equity"], 40.0)
        self.assertEqual(result.metric_sources["equity"], "fallback")


if __name__ == "__main__":
    unittest.main()



class CompleteHistoryFallbackTests(unittest.TestCase):
    def test_short_primary_uses_longer_fallback_without_combining_sources(self):
        from types import SimpleNamespace
        short = SimpleNamespace(bars=(1, 2), provider="primary")
        long = SimpleNamespace(bars=(7, 8, 9, 10), provider="secondary")
        chain = FallbackMarketDataProvider((WorkingMarketProvider(short), WorkingMarketProvider(long)), prefer_complete_history=True)
        self.assertIs(chain.fetch(FetchRequest("ASELS", "1d", 4, datetime.now(UTC))), long)

    def test_short_listing_is_kept_when_no_provider_has_full_history(self):
        from types import SimpleNamespace
        frame = SimpleNamespace(bars=(1, 2), provider="primary")
        chain = FallbackMarketDataProvider((WorkingMarketProvider(frame), BrokenMarketProvider()), prefer_complete_history=True)
        self.assertIs(chain.fetch(FetchRequest("ASELS", "1d", 400, datetime.now(UTC))), frame)
