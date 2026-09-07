from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.application.scheduled_scan import (
    ScheduledScanRequest,
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


if __name__ == "__main__":
    unittest.main()
