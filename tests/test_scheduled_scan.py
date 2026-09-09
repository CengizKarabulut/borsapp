from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.application.scheduled_scan import (
    ScheduledScanRequest,
    ScheduledScanResult,
    ScheduledScanService,
)
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.persistence.postgres.runtime import RuntimeInstrument

ISTANBUL = ZoneInfo("Europe/Istanbul")


class Repository:
    def __init__(self):
        self.updated = []

    def earliest_watermark(self, **kwargs):
        return datetime(2026, 9, 7, 12, 0, tzinfo=ISTANBUL)

    def list_universe(self, universe_id, *, as_of):
        return (RuntimeInstrument("i-1", "TEST", "TEST", "BIST", "equity"),)

    def start_cycle(self, **kwargs):
        return "cycle-1"

    def finish_cycle(self, **kwargs):
        self.failures = kwargs.get("failures", ())
        return None

    def update_watermarks(self, **kwargs):
        self.updated.append(kwargs["bar_time"])


class Planner:
    def due(self, **kwargs):
        return (
            datetime(2026, 9, 7, 13, 0, tzinfo=ISTANBUL),
            datetime(2026, 9, 7, 14, 0, tzinfo=ISTANBUL),
        )


class Ingestion:
    def ingest(self, request):
        return object()


class Coordinator:
    def __init__(self):
        self.notification_flags = []

    def run(self, **kwargs):
        self.notification_flags.append(kwargs["allow_notifications"])


class Binding:
    shadow_timeframes = frozenset({Timeframe.H1})

    class Scanner:
        id = "technical.test"

    scanner = Scanner()


class ScheduledScanServiceTests(unittest.TestCase):
    def test_partial_instrument_failure_is_not_an_operational_failure(self) -> None:
        result = ScheduledScanResult(
            due_bars=(datetime(2026, 9, 7, 13, 0, tzinfo=ISTANBUL),),
            completed_bars=1,
            successful_instruments=583,
            failed_instruments=1,
        )
        self.assertFalse(result.total_failure)

    def test_all_instruments_failing_is_an_operational_failure(self) -> None:
        result = ScheduledScanResult(
            due_bars=(datetime(2026, 9, 7, 13, 0, tzinfo=ISTANBUL),),
            completed_bars=1,
            successful_instruments=0,
            failed_instruments=584,
        )
        self.assertTrue(result.total_failure)

    def test_no_due_bar_is_not_an_operational_failure(self) -> None:
        self.assertFalse(ScheduledScanResult((), 0, 0, 0).total_failure)

    def test_only_freshest_catchup_bar_can_notify(self) -> None:
        repository = Repository()
        coordinator = Coordinator()
        service = ScheduledScanService(
            repository=repository,
            ingestion=Ingestion(),
            coordinator=coordinator,
            planner=Planner(),
        )
        result = service.run(
            ScheduledScanRequest(
                market="BIST",
                universe_id="BIST_ALL",
                timeframe=Timeframe.H1,
                bars=100,
                evaluation_time=datetime(2026, 9, 7, 14, 5, tzinfo=ISTANBUL),
                notification_max_age=timedelta(minutes=30),
            ),
            (Binding(),),
        )
        self.assertEqual(result.completed_bars, 2)
        self.assertEqual(coordinator.notification_flags, [False, True])
        self.assertEqual(len(repository.updated), 2)

    def test_one_bad_instrument_does_not_block_universe_watermark(self) -> None:
        class TwoInstrumentRepository(Repository):
            def list_universe(self, universe_id, *, as_of):
                return (
                    RuntimeInstrument("i-1", "GOOD", "GOOD", "BIST", "equity"),
                    RuntimeInstrument("i-2", "BAD", "BAD", "BIST", "equity"),
                )

        class OneBarPlanner:
            def due(self, **kwargs):
                return (datetime(2026, 9, 7, 13, 0, tzinfo=ISTANBUL),)

        class PartialFailureIngestion:
            def ingest(self, request):
                if request.symbol == "BAD":
                    raise RuntimeError("provider unavailable")
                return object()

        repository = TwoInstrumentRepository()
        service = ScheduledScanService(
            repository=repository,
            ingestion=PartialFailureIngestion(),
            coordinator=Coordinator(),
            planner=OneBarPlanner(),
        )
        result = service.run(
            ScheduledScanRequest(
                market="BIST",
                universe_id="BIST_ALL",
                timeframe=Timeframe.H1,
                bars=100,
                evaluation_time=datetime(2026, 9, 7, 13, 5, tzinfo=ISTANBUL),
            ),
            (Binding(),),
        )
        self.assertEqual(result.completed_bars, 1)
        self.assertEqual(result.successful_instruments, 1)
        self.assertEqual(result.failed_instruments, 1)
        self.assertEqual(repository.updated, [datetime(2026, 9, 7, 13, 0, tzinfo=ISTANBUL)])
        self.assertEqual(repository.failures[0].symbol, "BAD")

    def test_empty_universe_fails_loudly(self) -> None:
        class EmptyRepository(Repository):
            def list_universe(self, universe_id, *, as_of):
                return ()

        service = ScheduledScanService(
            repository=EmptyRepository(),
            ingestion=Ingestion(),
            coordinator=Coordinator(),
            planner=Planner(),
        )
        with self.assertRaisesRegex(ValueError, "Universe boş"):
            service.run(
                ScheduledScanRequest(
                    market="BIST",
                    universe_id="BIST_ALL",
                    timeframe=Timeframe.H1,
                    bars=100,
                    evaluation_time=datetime(2026, 9, 7, 14, 5, tzinfo=ISTANBUL),
                ),
                (Binding(),),
            )


if __name__ == "__main__":
    unittest.main()
