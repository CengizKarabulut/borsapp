from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from market_intelligence.core.enums import ResultKind
from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings
from market_intelligence.delivery.telegram.routing import PublicationKind, TopicRouter
from market_intelligence.features.registry import FeatureEngine
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.persistence.postgres.scan_store import PersistedScan
from market_intelligence.persistence.postgres.state_store import (
    PersistedStateRun,
    TransitionDecision,
)
from market_intelligence.scanning.catalog import ScannerBinding
from market_intelligence.scanning.contracts import Finding, ScanContext
from market_intelligence.scanning.engine import ScanRun
from market_intelligence.scanning.pipeline import ScanPipeline


class EventRunStore(Protocol):
    def persist_event_run(self, run: ScanRun, envelopes=None) -> PersistedScan: ...


class StateRunStore(Protocol):
    def persist_state_run(
        self,
        run: ScanRun,
        envelopes=None,
        *,
        envelope_factory=None,
        instrument_halted: bool = False,
        abandon_after_unknown_bars: int = 3,
    ) -> PersistedStateRun: ...


@dataclass(frozen=True)
class ScanFrameResult:
    runs: tuple[ScanRun, ...]
    event_count: int
    transition_count: int
    outbox_count: int


class ScanFrameCoordinator:
    """Run all scanner families on one immutable canonical frame."""

    def __init__(
        self,
        *,
        feature_engine: FeatureEngine,
        event_store: EventRunStore,
        state_store: StateRunStore,
        telegram_settings: TelegramSettings,
        calendar_version: str = "bist-session-v1",
    ) -> None:
        self.pipeline = ScanPipeline(feature_engine)
        self.event_store = event_store
        self.state_store = state_store
        self.telegram_settings = telegram_settings
        self.router = TopicRouter(telegram_settings)
        self.calendar_version = calendar_version

    def run(
        self,
        *,
        cycle_id: str,
        frame: CanonicalFrame,
        bindings: tuple[ScannerBinding, ...],
        evaluation_time: datetime,
        instrument_halted: bool = False,
    ) -> ScanFrameResult:
        if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
            raise ValueError("evaluation_time timezone bilgisi içermelidir")
        runs: list[ScanRun] = []
        event_count = 0
        transition_count = 0
        outbox_count = 0
        for binding in bindings:
            if frame.timeframe not in binding.shadow_timeframes:
                continue
            context = ScanContext(
                evaluation_time=evaluation_time,
                bar_close_time=frame.through_bar_time,
                market_session_id=f"{frame.market}:{frame.through_bar_time.date().isoformat()}",
                calendar_version=self.calendar_version,
                ruleset_hash=binding.ruleset_hash,
            )
            pipeline_run = self.pipeline.run(
                cycle_id=cycle_id,
                frame=frame,
                scanner=binding.scanner,
                context=context,
            )
            run = pipeline_run.scan
            runs.append(run)
            can_notify = (
                self.telegram_settings.delivery_mode is DeliveryMode.LIVE
                and frame.timeframe in binding.notification_timeframes
            )
            if binding.scanner.result_kind is ResultKind.EVENT:
                envelopes = {
                    finding.finding_key: self._event_envelope(finding)
                    for finding in run.findings
                } if can_notify else {}
                persisted = self.event_store.persist_event_run(run, envelopes)
                event_count += len(persisted.event_ids)
                outbox_count += persisted.outbox_count
            else:
                factory = self._state_envelope_factory(run) if can_notify else None
                persisted_state = self.state_store.persist_state_run(
                    run,
                    envelope_factory=factory,
                    instrument_halted=instrument_halted,
                )
                transition_count += len(persisted_state.transition_ids)
                outbox_count += persisted_state.outbox_count
        return ScanFrameResult(tuple(runs), event_count, transition_count, outbox_count)

    def _event_envelope(self, finding: Finding):
        return self.router.route(
            publication_kind=PublicationKind.SCAN_EVENT,
            semantic_identity={
                "instrument_id": finding.instrument_id,
                "scanner_id": finding.scanner_id,
                "finding_key": finding.finding_key,
                "timeframe": finding.timeframe,
                "bar_time": finding.bar_time,
            },
            payload={"text": self._finding_text(finding)},
        )

    def _state_envelope_factory(self, run: ScanRun):
        def factory(
            state_key: str,
            decision: TransitionDecision,
            finding: Finding | None,
        ):
            if not decision.notify or not decision.transitions:
                return None
            transition = decision.transitions[-1]
            symbol = run.evaluation.symbol_at_evaluation
            text = (
                self._finding_text(finding)
                if finding is not None
                else f"[MA] {symbol} · {state_key} · {transition.value}"
            )
            return self.router.route(
                publication_kind=PublicationKind.SCAN_EVENT,
                semantic_identity={
                    "instrument_id": run.evaluation.instrument_id,
                    "scanner_id": run.evaluation.scanner_id,
                    "state_key": state_key,
                    "transition": transition,
                    "timeframe": run.evaluation.timeframe,
                    "bar_time": run.evaluation.bar_time,
                },
                payload={"text": text},
            )

        return factory

    @staticmethod
    def _finding_text(finding: Finding) -> str:
        family = finding.scanner_id.split(".", 1)[0].upper()
        return (
            f"[{family}] {finding.symbol_at_event} · {finding.timeframe.value} · "
            f"{finding.scanner_id} · {finding.direction.value} · "
            f"{finding.bar_time.isoformat()}"
        )
