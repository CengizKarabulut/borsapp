from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.fallback import FallbackMarketDataProvider
from market_intelligence.market_data.provider_cooldown import ProviderRetryCooldowns
from market_intelligence.market_data.providers import FetchRequest


class FakeCooldown:
    def __init__(self):
        self.blocked = set()
        self.failures = []
        self.successes = []

    def skip(self, provider, symbol, timeframe):
        return (provider, symbol, timeframe) in self.blocked

    def failed(self, provider, symbol, timeframe, error):
        self.failures.append((provider, symbol, timeframe, error))
        self.blocked.add((provider, symbol, timeframe))

    def recovered(self, provider, symbol, timeframe):
        self.successes.append((provider, symbol, timeframe))


class Stub:
    def __init__(self, name, *, fails=False):
        self.name = name
        self.fails = fails
        self.called = 0

    def fetch(self, request):
        self.called += 1
        if self.fails:
            raise RuntimeError("provider empty")
        return SimpleNamespace(provider=self.name, bars=tuple(range(request.bars)))


class ProviderCooldownTests(unittest.TestCase):
    def test_failing_source_is_skipped_but_healthy_fallback_runs(self):
        state = FakeCooldown()
        first = Stub("borsapy", fails=True)
        second = Stub("tvdatafeed")
        chain = FallbackMarketDataProvider(
            (first, second), prefer_complete_history=True, cooldowns=state
        )
        request = FetchRequest(
            "TEST", Timeframe.D1, 30, datetime(2026, 10, 15, tzinfo=UTC)
        )
        self.assertEqual(chain.fetch(request).provider, "tvdatafeed")
        self.assertEqual(first.called, 1)
        self.assertEqual(state.failures, [("borsapy", "TEST", "1d", "RuntimeError")])
        self.assertEqual(chain.fetch(request).provider, "tvdatafeed")
        self.assertEqual(first.called, 1)  # Cooldown prevented a second failed call.
        self.assertEqual(second.called, 2)

    def test_blocked_source_is_never_silently_used_for_cached_overlap(self):
        state = FakeCooldown()
        state.blocked.add(("borsapy", "TEST", "1d"))
        chain = FallbackMarketDataProvider((Stub("borsapy"), Stub("yfinance")), cooldowns=state)
        request = FetchRequest("TEST", Timeframe.D1, 12, datetime(2026, 10, 15, tzinfo=UTC))
        with self.assertRaisesRegex(RuntimeError, "cooldown"):
            chain.fetch_from_source("borsapy", request)
        self.assertEqual(chain.fetch(request).provider, "yfinance")

    def test_disabled_retry_database_is_fail_open(self):
        state = ProviderRetryCooldowns("")
        self.assertFalse(state.skip("borsapy", "TEST", "1d"))
        state.failed("borsapy", "TEST", "1d", "TestError")
        self.assertFalse(state.skip("borsapy", "TEST", "1d"))


if __name__ == "__main__":
    unittest.main()
