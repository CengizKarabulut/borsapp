from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from market_intelligence.application.ingestion import IngestionRequest, IngestionService
from market_intelligence.application.scan_frame import ScanFrameCoordinator
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.persistence.postgres.runtime import RuntimeInstrument
from market_intelligence.scanning.catalog import ScannerBinding
from market_intelligence.scheduling.xist import ScheduledBarPlanner


class ScheduleRepository(Protocol):
    def list_universe(self, universe_id: str, *, as_of): ...

    def earliest_watermark(
        self,
        *,
        market: str,
        universe_id: str,
        scanner_ids: tuple[str, ...],
        timeframe: str,
    ) -> datetime | None: ...

    def start_cycle(self, **kwargs) -> str: ...

    def finish_cycle(self, **kwargs) -> None: ...

    def update_watermarks(self, **kwargs) -> None: ...


@dataclass(frozen=True)
class ScheduledScanRequest:
    market: str
    universe_id: str
    timeframe: Timeframe
    bars: int
    evaluation_time: datetime
    series_revision: int = 1
    notification_max_age: timedelta = timedelta(minutes=30)


@dataclass(frozen=True)
class ScheduledScanResult:
    due_bars: tuple[datetime, ...]
    completed_bars: int
    successful_instruments: int
    failed_instruments: int


class ScheduledScanService:
    def __init__(
        self,
        *,
        repository: ScheduleRepository,
        ingestion: IngestionService,
        coordinator: ScanFrameCoordinator,
        planner: ScheduledBarPlanner,
    ) -> None:
        self.repository = repository
        self.ingestion = ingestion
        self.coordinator = coordinator
        self.planner = planner

    def run(
        self,
        request: ScheduledScanRequest,
        bindings: tuple[ScannerBinding, ...],
    ) -> ScheduledScanResult:
        applicable = tuple(
            binding
            for binding in bindings
            if request.timeframe in binding.shadow_timeframes
        )
        scanner_ids = tuple(binding.scanner.id for binding in applicable)
        if not scanner_ids:
            return ScheduledScanResult((), 0, 0, 0)
        watermark = self.repository.earliest_watermark(
            market=request.market,
            universe_id=request.universe_id,
            scanner_ids=scanner_ids,
            timeframe=request.timeframe.value,
        )
        due_bars = self.planner.due(
            timeframe=request.timeframe,
            evaluation_time=request.evaluation_time,
            watermark=watermark,
        )
        completed_bars = 0
        total_success = 0
        total_failed = 0
        for bar_time in due_bars:
            instruments: tuple[RuntimeInstrument, ...] = self.repository.list_universe(
                request.universe_id,
                as_of=bar_time.date(),
            )
            cycle_id = self.repository.start_cycle(
                market=request.market,
                universe_id=request.universe_id,
                timeframe=request.timeframe.value,
                bar_time=bar_time,
                expected_instruments=len(instruments),
                started_at=request.evaluation_time,
            )
            successful = 0
            failed = 0
            newest = bar_time == due_bars[-1]
            fresh = request.evaluation_time - bar_time <= request.notification_max_age
            for instrument in instruments:
                try:
                    frame = self.ingestion.ingest(
                        IngestionRequest(
                            instrument_id=instrument.instrument_id,
                            symbol=instrument.symbol,
                            provider_symbol=instrument.provider_symbol,
                            market=instrument.market,
                            timeframe=request.timeframe,
                            bars=request.bars,
                            as_of=bar_time,
                            series_revision=request.series_revision,
                        )
                    )
                    self.coordinator.run(
                        cycle_id=cycle_id,
                        frame=frame,
                        bindings=applicable,
                        evaluation_time=request.evaluation_time,
                        allow_notifications=newest and fresh,
                    )
                except Exception:
                    failed += 1
                else:
                    successful += 1
            self.repository.finish_cycle(
                cycle_id=cycle_id,
                successful=successful,
                stale=0,
                failed=failed,
                finished_at=request.evaluation_time,
            )
            total_success += successful
            total_failed += failed
            if failed:
                break
            self.repository.update_watermarks(
                market=request.market,
                universe_id=request.universe_id,
                scanner_ids=scanner_ids,
                timeframe=request.timeframe.value,
                bar_time=bar_time,
            )
            completed_bars += 1
        return ScheduledScanResult(
            due_bars,
            completed_bars,
            total_success,
            total_failed,
        )
