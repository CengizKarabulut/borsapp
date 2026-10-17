from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from market_intelligence.application.ingestion import IngestionRequest, IngestionService
from market_intelligence.application.scan_frame import ScanFrameCoordinator
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.persistence.postgres.runtime import (
    InstrumentScanFailure,
    RuntimeInstrument,
)
from market_intelligence.scanning.catalog import ScannerBinding
from market_intelligence.scheduling.xist import ScheduledBarPlanner


class ScanBudgetExhausted(TimeoutError):
    pass


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
    latest_only: bool = False
    maximum_run_time: timedelta | None = None
    start_offset: int = 0
    retry_failed_rounds: int = 0
    require_complete: bool = False


@dataclass(frozen=True)
class ScheduledScanResult:
    due_bars: tuple[datetime, ...]
    completed_bars: int
    successful_instruments: int
    failed_instruments: int
    attempted_instruments: int = 0

    @property
    def total_failure(self) -> bool:
        """Whether due work ran without a single successful instrument."""
        return (
            bool(self.due_bars) and self.successful_instruments == 0 and self.failed_instruments > 0
        )


class ScheduledScanService:
    def __init__(
        self,
        *,
        repository: ScheduleRepository,
        ingestion: IngestionService,
        coordinator: ScanFrameCoordinator,
        planner: ScheduledBarPlanner,
        instrument_runner=None,
        map_work=map,
        clock=None,
        progress=None,
        before_retry=None,
    ) -> None:
        self.repository = repository
        self.ingestion = ingestion
        self.coordinator = coordinator
        self.planner = planner
        self.instrument_runner = instrument_runner
        self.map_work = map_work
        self.clock = clock
        self.progress = progress
        self.before_retry = before_retry

    def run(
        self,
        request: ScheduledScanRequest,
        bindings: tuple[ScannerBinding, ...],
    ) -> ScheduledScanResult:
        applicable = tuple(
            binding for binding in bindings if request.timeframe in binding.shadow_timeframes
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
        if request.latest_only and due_bars:
            due_bars = (due_bars[-1],)
        completed_bars = 0
        total_success = 0
        total_failed = 0
        total_attempted = 0
        if request.retry_failed_rounds < 0 or request.retry_failed_rounds > 6:
            raise ValueError("retry_failed_rounds must be between 0 and 6")
        for bar_time in due_bars:
            # ATC_630 is a present-day *pinned watchlist*, not a historical
            # exchange membership. A run at 02:00 TRT on October 15 checks
            # the October 14 closed bar against the watchlist known NOW;
            # looking it up on the candle date can hide all 630 members.
            # Real exchange universes preserve historical point-in-time dates.
            membership_date = (
                request.evaluation_time.date()
                if request.universe_id.upper() == "ATC_630"
                else bar_time.date()
            )
            instruments: tuple[RuntimeInstrument, ...] = self.repository.list_universe(
                request.universe_id,
                as_of=membership_date,
            )
            if not instruments:
                raise ValueError(
                    f"Universe boş: {request.universe_id}; önce universe-sync --apply çalıştırın"
                )
            offset = request.start_offset % len(instruments)
            instruments = instruments[offset:] + instruments[:offset]
            started = self.clock() if self.clock else datetime.now(UTC)
            deadline = started + request.maximum_run_time if request.maximum_run_time else None
            cycle_id = self.repository.start_cycle(
                market=request.market,
                universe_id=request.universe_id,
                timeframe=request.timeframe.value,
                bar_time=bar_time,
                expected_instruments=len(instruments),
                started_at=started,
            )
            successful = 0
            failures: list[InstrumentScanFailure] = []
            newest = bar_time == due_bars[-1]

            def process(
                instrument, newest=newest, bar_time=bar_time, cycle_id=cycle_id, deadline=deadline
            ):
                try:
                    now = self.clock() if self.clock else request.evaluation_time
                    if deadline is not None and now >= deadline:
                        raise ScanBudgetExhausted("Yeni güncel muma geçmek için tur süresi doldu")
                    allow_notifications = newest and now - bar_time <= request.notification_max_age
                    if self.instrument_runner is not None:
                        self.instrument_runner(
                            instrument, request, cycle_id, bar_time, allow_notifications
                        )
                    else:
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
                            evaluation_time=now,
                            allow_notifications=allow_notifications,
                        )
                    return None
                except Exception as exc:
                    return InstrumentScanFailure(
                        instrument_id=instrument.instrument_id,
                        symbol=instrument.symbol,
                        error_code=type(exc).__name__,
                        error_detail=str(exc) or type(exc).__name__,
                    )

            pending = instruments
            for retry_round in range(request.retry_failed_rounds + 1):
                if retry_round:
                    if deadline is not None and (
                        (self.clock() if self.clock else datetime.now(UTC)) >= deadline
                    ):
                        break
                    if self.before_retry is not None:
                        self.before_retry(tuple(failures), retry_round)
                    failed_ids = {failure.instrument_id for failure in failures}
                    pending = tuple(
                        instrument for instrument in instruments
                        if instrument.instrument_id in failed_ids
                    )
                    print(
                        f"ATC retry {request.timeframe.value} round {retry_round}: "
                        f"only {len(pending)} failed symbols; previous successes retained",
                        flush=True,
                    )
                current_failures = []
                for failure in self.map_work(process, pending):
                    if failure is None:
                        successful += 1
                    else:
                        current_failures.append(failure)
                    if self.progress is not None:
                        self.progress(cycle_id, successful, len(current_failures))
                failures = current_failures
                if not failures:
                    break
            failed = len(failures)
            if failures and request.universe_id.upper() == "ATC_630":
                print(
                    f"ATC unresolved {request.timeframe.value} ({failed}): "
                    + "; ".join(
                        f"{failure.symbol}={failure.error_code}:"
                        f"{failure.error_detail[:90]}"
                        for failure in failures[:40]
                    ),
                    flush=True,
                )
            self.repository.finish_cycle(
                cycle_id=cycle_id,
                successful=successful,
                stale=0,
                failed=failed,
                finished_at=self.clock() if self.clock else datetime.now(UTC),
                failures=tuple(failures),
            )
            total_success += successful
            total_failed += failed
            total_attempted += successful + sum(
                f.error_code != "ScanBudgetExhausted" for f in failures
            )
            if (
                successful
                and not any(f.error_code == "ScanBudgetExhausted" for f in failures)
                and (not request.require_complete or not failures)
            ):
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
            total_attempted,
        )
