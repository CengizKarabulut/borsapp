"""ATC pinned-universe retries preserve genuine successes and strict watermarks."""
from __future__ import annotations

import unittest
from collections import Counter
from datetime import UTC, datetime, timedelta

from market_intelligence.application.scheduled_scan import (
    ScheduledScanRequest,
    ScheduledScanService,
)
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.provider_cooldown import ProviderRetryCooldowns
from market_intelligence.persistence.postgres.runtime import RuntimeInstrument

BAR = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)


class StubRepository:
    def __init__(self):
        self.finished = None
        self.watermarks = []

    def earliest_watermark(self, **kwargs):
        return None

    def list_universe(self, universe_id, *, as_of):
        assert universe_id == "ATC_630"
        return tuple(
            RuntimeInstrument(f"id-{ticker}", ticker, ticker, "BIST", "equity")
            for ticker in ("AAA", "BBB", "CCC")
        )

    def start_cycle(self, **kwargs):
        return "cycle-1"

    def finish_cycle(self, **kwargs):
        self.finished = kwargs

    def update_watermarks(self, **kwargs):
        self.watermarks.append(kwargs["bar_time"])


class StubPlanner:
    def due(self, **kwargs):
        return (BAR,)


class StubScanner:
    id = "atc.test"


class StubBinding:
    scanner = StubScanner()
    shadow_timeframes = frozenset({Timeframe.W1})


class StrictRecoveryTests(unittest.TestCase):
    def request(self, retries=0):
        return ScheduledScanRequest(
            market="BIST", universe_id="ATC_630",
            timeframe=Timeframe.W1, bars=600,
            evaluation_time=BAR + timedelta(hours=1),
            retry_failed_rounds=retries, require_complete=True,
        )

    def test_only_failed_symbols_get_retried_without_reprocessing_successes(self):
        repo = StubRepository()
        calls = Counter()
        rounds = []

        def run(instrument, request, cycle, bar, notify):
            calls[instrument.symbol] += 1
            if instrument.symbol == "BBB" and calls["BBB"] <= 1:
                raise RuntimeError("temporary provider outage")
            if instrument.symbol == "CCC" and calls["CCC"] <= 2:
                raise RuntimeError("temporary websocket failure")

        def before_retry(failures, round_number):
            rounds.append((round_number, {f.symbol for f in failures}))

        service = ScheduledScanService(
            repository=repo, ingestion=None, coordinator=None,
            planner=StubPlanner(), instrument_runner=run,
            before_retry=before_retry,
        )
        result = service.run(self.request(retries=3), (StubBinding(),))
        self.assertEqual((result.successful_instruments, result.failed_instruments), (3, 0))
        self.assertEqual(calls, Counter({"AAA": 1, "BBB": 2, "CCC": 3}))
        self.assertEqual(rounds, [(1, {"BBB", "CCC"}), (2, {"CCC"})])
        self.assertEqual(repo.finished["failures"], ())
        self.assertEqual(repo.watermarks, [BAR])

    def test_strict_run_never_advances_watermark_on_missing_symbols(self):
        repo = StubRepository()

        def run(instrument, request, cycle, bar, notify):
            if instrument.symbol == "CCC":
                raise RuntimeError("source genuinely unavailable")

        service = ScheduledScanService(
            repository=repo, ingestion=None, coordinator=None,
            planner=StubPlanner(), instrument_runner=run,
        )
        result = service.run(self.request(), (StubBinding(),))
        self.assertEqual((result.successful_instruments, result.failed_instruments), (2, 1))
        self.assertEqual([f.symbol for f in repo.finished["failures"]], ["CCC"])
        self.assertEqual(repo.watermarks, [])

    def test_targeted_cooldown_override_only_unblocks_requested_symbol(self):
        cooldowns = ProviderRetryCooldowns("")
        until = datetime(2099, 1, 1, tzinfo=UTC)
        cooldowns._loaded = True
        cooldowns._active = {
            ("borsapy", "AAA", "1d"): until,
            ("tvdatafeed", "BBB", "1d"): until,
            ("yfinance", "AAA", "1h"): until,
        }
        cooldowns.allow_targeted_retry(("AAA",), "1d")
        self.assertFalse(cooldowns.skip("borsapy", "AAA", "1d"))
        self.assertTrue(cooldowns.skip("tvdatafeed", "BBB", "1d"))
        self.assertTrue(cooldowns.skip("yfinance", "AAA", "1h"))


if __name__ == "__main__":
    unittest.main()
