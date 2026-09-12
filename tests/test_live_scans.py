from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

from market_intelligence.application.live_scans import (
    LABELS,
    bounded_map,
    format_summary,
    latest_target,
    summary_slot,
)
from market_intelligence.application.scheduled_scan import (
    ScheduledScanRequest,
    ScheduledScanService,
)
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scanning.catalog import load_scanner_catalog
from tests.test_scheduled_scan import Binding, Coordinator, Ingestion, Planner, Repository

TZ = ZoneInfo("Europe/Istanbul")


class Calendar:
    def sessions(self, start, end):
        return (start,) if start.weekday() < 5 else ()


class LiveScanTests(unittest.TestCase):
    def test_live_scan_skips_backlog_and_expires_late_notifications(self):
        repository = Repository()
        observed = []
        now = datetime(2026, 9, 7, 15, 0, tzinfo=TZ)
        service = ScheduledScanService(
            repository=repository, ingestion=Ingestion(), coordinator=Coordinator(), planner=Planner(),
            instrument_runner=lambda *args: observed.append(args), clock=lambda: now,
        )
        result = service.run(ScheduledScanRequest(
            market="BIST", universe_id="BIST_ALL", timeframe=Timeframe.H1, bars=320,
            evaluation_time=now - timedelta(minutes=45), latest_only=True,
        ), (Binding(),))
        self.assertEqual(result.completed_bars, 1)
        self.assertEqual(observed[0][3].hour, 14)
        self.assertFalse(observed[0][4])
        self.assertEqual(len(repository.updated), 1)

    def test_total_provider_failure_never_advances_watermark(self):
        repository = Repository()
        def fail(*args):
            raise RuntimeError("provider down")
        result = ScheduledScanService(
            repository=repository, ingestion=Ingestion(), coordinator=Coordinator(), planner=Planner(),
            instrument_runner=fail,
        ).run(ScheduledScanRequest(
            market="BIST", universe_id="BIST_ALL", timeframe=Timeframe.H1, bars=320,
            evaluation_time=datetime(2026, 9, 7, 14, 5, tzinfo=TZ), latest_only=True,
        ), (Binding(),))
        self.assertTrue(result.total_failure)
        self.assertEqual(repository.updated, [])

    def test_bounded_queue_does_not_block_other_timeframe(self):
        gate = Event()
        started = Event()
        results = []
        def slow(value):
            started.set()
            self.assertTrue(gate.wait(5))
            return value
        from threading import Thread
        with ThreadPoolExecutor(max_workers=3) as executor:
            thread = Thread(target=lambda: results.extend(bounded_map(executor, slow, range(4))))
            thread.start()
            self.assertTrue(started.wait(2))
            try:
                self.assertEqual(executor.submit(lambda: "15m").result(timeout=2), "15m")
            finally:
                gate.set()
                thread.join(timeout=5)
        self.assertEqual(sorted(results), list(range(4)))

    def test_summary_slots_respect_sessions_and_delay(self):
        calendar = Calendar()
        self.assertIsNone(summary_slot(datetime(2026, 9, 7, 10, 15, tzinfo=TZ), calendar))
        self.assertEqual(summary_slot(datetime(2026, 9, 7, 10, 44, tzinfo=TZ), calendar).minute, 30)
        self.assertIsNotNone(summary_slot(datetime(2026, 9, 7, 18, 30, tzinfo=TZ), calendar))
        self.assertIsNone(summary_slot(datetime(2026, 9, 7, 18, 45, tzinfo=TZ), calendar))
        self.assertIsNone(summary_slot(datetime(2026, 9, 12, 12, 0, tzinfo=TZ), calendar))

    def test_latest_target_applies_data_delay(self):
        from unittest.mock import Mock
        planner = Mock()
        now = datetime(2026, 9, 7, 12, 30, tzinfo=TZ)
        planner.due.return_value = (now - timedelta(minutes=15),)
        self.assertEqual(latest_target(planner, Timeframe.M15, now), now - timedelta(minutes=15))
        self.assertEqual(planner.due.call_args.kwargs['evaluation_time'], now - timedelta(minutes=15))

    def test_all_scanner_families_have_summary_labels_and_missing_is_explicit(self):
        bindings = load_scanner_catalog(Path('config/scanners.toml'))
        self.assertEqual({binding.scanner.id for binding in bindings}, set(LABELS))
        now = datetime(2026, 9, 7, 18, 30, tzinfo=TZ)
        text = format_summary(Timeframe.D1, now - timedelta(minutes=30), now, 583, bindings,
                              [('signal.macd_positive_cross', 580, 1, 2, ['ASELS'])])
        self.assertIn('ASELS', text)
        self.assertIn('3 bekleyen/erişilemeyen', text)
        self.assertIn('2 hesaplanamadı', text)
        self.assertIn('MA seviye yakınlığı', text)
        self.assertIn('Karar paneli', text)
        self.assertLess(len(text), 4096)


class LiveScanBudgetTests(unittest.TestCase):
    def test_elapsed_budget_skips_new_work_without_advancing_watermark(self):
        from unittest.mock import Mock
        repository = Repository()
        now = datetime(2026, 9, 7, 14, 5, tzinfo=TZ)
        clock = Mock(side_effect=[now, now + timedelta(minutes=13), now + timedelta(minutes=13)])
        runner = Mock()
        result = ScheduledScanService(
            repository=repository, ingestion=Ingestion(), coordinator=Coordinator(), planner=Planner(),
            instrument_runner=runner, clock=clock,
        ).run(ScheduledScanRequest(
            market="BIST", universe_id="BIST_ALL", timeframe=Timeframe.H1, bars=320,
            evaluation_time=now, latest_only=True, maximum_run_time=timedelta(minutes=12),
        ), (Binding(),))
        runner.assert_not_called()
        self.assertEqual(result.attempted_instruments, 0)
        self.assertEqual(repository.updated, [])
        self.assertEqual(repository.failures[0].error_code, 'ScanBudgetExhausted')

    def test_long_summary_preserves_every_line_under_telegram_limit(self):
        from market_intelligence.application.live_scans import split_summary
        lines = ['Summary'] + [f'Scanner {i}: ' + 'X' * 220 for i in range(30)]
        parts = split_summary('\n'.join(lines))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 3500 for part in parts))
        for line in lines[1:]:
            self.assertEqual(sum(line in part.splitlines() for part in parts), 1)
