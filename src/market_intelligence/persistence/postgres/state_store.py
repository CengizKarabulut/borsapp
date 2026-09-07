from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from market_intelligence.core.enums import (
    EvaluationStatus,
    ResultKind,
    StateStatus,
)
from market_intelligence.core.identity import canonical_json, stable_hash
from market_intelligence.delivery.telegram.routing import OutboxEnvelope
from market_intelligence.persistence.postgres.scan_store import (
    EVALUATION_SQL,
    OUTBOX_SQL,
    PostgresConnection,
)
from market_intelligence.scanning.contracts import Finding
from market_intelligence.scanning.engine import ScanRun
from market_intelligence.scanning.state_machine import (
    StateObservation,
    StateSnapshot,
    TransitionDecision,
    reconcile_state,
)

CURRENT_STATES_SQL = """
SELECT
    state_id, state_key, status, unknown_bars, producer_version,
    ruleset_hash, valid_from, valid_until, metrics
FROM active_states
WHERE instrument_id = %s AND scanner_id = %s AND timeframe = %s
FOR UPDATE
"""

STATE_UPSERT_SQL = """
INSERT INTO active_states (
    instrument_id, scanner_id, timeframe, state_key, status,
    producer_version, ruleset_hash, valid_from, valid_until, last_seen_at,
    unknown_bars, metrics
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (instrument_id, scanner_id, timeframe, state_key)
DO UPDATE SET
    status = EXCLUDED.status,
    producer_version = EXCLUDED.producer_version,
    ruleset_hash = EXCLUDED.ruleset_hash,
    valid_from = EXCLUDED.valid_from,
    valid_until = EXCLUDED.valid_until,
    last_seen_at = EXCLUDED.last_seen_at,
    unknown_bars = EXCLUDED.unknown_bars,
    metrics = EXCLUDED.metrics
RETURNING state_id
"""

TRANSITION_SQL = """
INSERT INTO state_transitions (
    transition_key, state_id, instrument_id, scanner_id, timeframe,
    previous_state_key, next_state_key, transition_type, reason,
    timing_uncertain, bar_time, producer_version, ruleset_hash
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (transition_key) DO NOTHING
RETURNING transition_id
"""


@dataclass(frozen=True)
class PersistedStateRun:
    evaluation_id: str
    state_ids: tuple[str, ...]
    transition_ids: tuple[str, ...]
    outbox_count: int


class StateEnvelopeFactory(Protocol):
    def __call__(
        self,
        state_key: str,
        decision: TransitionDecision,
        finding: Finding | None,
    ) -> OutboxEnvelope | None: ...


@dataclass(frozen=True)
class _StoredState:
    state_id: str
    snapshot: StateSnapshot
    valid_from: datetime
    valid_until: datetime | None
    metrics: Mapping[str, Any]


class PostgresStateStore:
    """Persist a state evaluation, projections, transitions and notifications atomically."""

    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def persist_state_run(
        self,
        run: ScanRun,
        envelopes: Mapping[str, OutboxEnvelope] | None = None,
        *,
        envelope_factory: StateEnvelopeFactory | None = None,
        instrument_halted: bool = False,
        abandon_after_unknown_bars: int = 3,
    ) -> PersistedStateRun:
        self._validate(run, envelopes or {})
        evaluation = run.evaluation
        envelope_map = dict(envelopes or {})
        state_ids: list[str] = []
        transition_ids: list[str] = []
        outbox_count = 0

        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                evaluation_id = self._persist_evaluation(cursor, run)
                previous = self._load_previous(cursor, run)
                work = self._build_work(run, previous, instrument_halted)
                for state_key, finding, stored, observed_status in work:
                    observation = StateObservation(
                        status=observed_status,
                        state_key=state_key,
                        producer_version=evaluation.scanner_version,
                        ruleset_hash=evaluation.ruleset_hash,
                    )
                    producer_changed = self._producer_changed(stored, observation)
                    decision = reconcile_state(
                        stored.snapshot if stored else None,
                        observation,
                        producer_changed=producer_changed,
                        instrument_halted=instrument_halted,
                        abandon_after_unknown_bars=abandon_after_unknown_bars,
                    )
                    state_id = self._upsert_state(
                        cursor,
                        run,
                        state_key,
                        finding,
                        stored,
                        decision,
                    )
                    state_ids.append(state_id)
                    transition_ids.extend(
                        self._persist_transitions(
                            cursor,
                            run,
                            state_id,
                            state_key,
                            stored,
                            decision,
                        )
                    )
                    envelope = envelope_map.get(state_key)
                    if envelope is None and envelope_factory is not None:
                        envelope = envelope_factory(state_key, decision, finding)
                    if decision.notify and envelope is not None:
                        outbox_count += self._persist_outbox(cursor, envelope)

        return PersistedStateRun(
            evaluation_id,
            tuple(state_ids),
            tuple(transition_ids),
            outbox_count,
        )

    @staticmethod
    def _validate(run: ScanRun, envelopes: Mapping[str, OutboxEnvelope]) -> None:
        if any(finding.kind is not ResultKind.STATE for finding in run.findings):
            raise ValueError("PostgresStateStore yalnız state finding kabul eder")
        finding_keys = {finding.state_key for finding in run.findings}
        if None in finding_keys:
            raise ValueError("State finding state_key içermelidir")
        unknown = set(envelopes) - finding_keys
        # Exit envelopes may refer to an existing state not present in this run.
        if unknown and run.evaluation.status is EvaluationStatus.MATCH:
            raise ValueError(
                "Bu MATCH değerlendirmesinde bulunmayan state için outbox verildi: "
                + ", ".join(sorted(unknown))
            )

    @staticmethod
    def _persist_evaluation(cursor: Any, run: ScanRun) -> str:
        evaluation = run.evaluation
        cursor.execute(
            EVALUATION_SQL,
            (
                evaluation.cycle_id,
                evaluation.instrument_id,
                evaluation.symbol_at_evaluation,
                evaluation.timeframe.value,
                evaluation.bar_time,
                evaluation.scanner_id,
                evaluation.scanner_version,
                evaluation.ruleset_hash,
                evaluation.snapshot_id,
                evaluation.status.value,
                evaluation.finding_count,
                evaluation.error_code,
                evaluation.error_detail,
            ),
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("scan_evaluations evaluation_id döndürmedi")
        return str(row[0])

    @staticmethod
    def _load_previous(cursor: Any, run: ScanRun) -> dict[str, _StoredState]:
        evaluation = run.evaluation
        cursor.execute(
            CURRENT_STATES_SQL,
            (
                evaluation.instrument_id,
                evaluation.scanner_id,
                evaluation.timeframe.value,
            ),
        )
        previous: dict[str, _StoredState] = {}
        for row in cursor.fetchall():
            raw_metrics = row[8]
            metrics = json.loads(raw_metrics) if isinstance(raw_metrics, str) else raw_metrics
            state_key = str(row[1])
            previous[state_key] = _StoredState(
                state_id=str(row[0]),
                snapshot=StateSnapshot(
                    status=StateStatus(str(row[2])),
                    state_key=state_key,
                    unknown_bars=int(row[3]),
                    producer_version=str(row[4]),
                    ruleset_hash=str(row[5]),
                ),
                valid_from=row[6],
                valid_until=row[7],
                metrics=dict(metrics or {}),
            )
        return previous

    @staticmethod
    def _build_work(
        run: ScanRun,
        previous: Mapping[str, _StoredState],
        instrument_halted: bool,
    ) -> list[tuple[str, Finding | None, _StoredState | None, EvaluationStatus]]:
        findings = {str(finding.state_key): finding for finding in run.findings}
        work = [
            (state_key, finding, previous.get(state_key), EvaluationStatus.MATCH)
            for state_key, finding in findings.items()
        ]
        current_statuses = {StateStatus.ACTIVE, StateStatus.UNKNOWN, StateStatus.HALTED}
        for state_key, stored in previous.items():
            if state_key in findings or stored.snapshot.status not in current_statuses:
                continue
            if instrument_halted or run.evaluation.status is EvaluationStatus.UNKNOWN:
                observed = EvaluationStatus.UNKNOWN
            else:
                observed = EvaluationStatus.NO_MATCH
            work.append((state_key, None, stored, observed))
        return work

    @staticmethod
    def _producer_changed(
        stored: _StoredState | None,
        observation: StateObservation,
    ) -> bool:
        if stored is None or stored.snapshot.status in {
            StateStatus.INACTIVE,
            StateStatus.ABANDONED,
        }:
            return False
        return (
            stored.snapshot.producer_version != observation.producer_version
            or stored.snapshot.ruleset_hash != observation.ruleset_hash
        )

    @staticmethod
    def _upsert_state(
        cursor: Any,
        run: ScanRun,
        state_key: str,
        finding: Finding | None,
        stored: _StoredState | None,
        decision: TransitionDecision,
    ) -> str:
        evaluation = run.evaluation
        continuing = stored is not None and decision.new_state.status in {
            StateStatus.ACTIVE,
            StateStatus.UNKNOWN,
            StateStatus.HALTED,
        }
        valid_from = (
            stored.valid_from
            if continuing
            else finding.valid_from
            if finding and finding.valid_from
            else evaluation.bar_time
        )
        if decision.new_state.status is StateStatus.ACTIVE and finding is not None:
            valid_until = finding.valid_until
        elif decision.new_state.status in {StateStatus.INACTIVE, StateStatus.ABANDONED}:
            valid_until = evaluation.bar_time
        else:
            valid_until = stored.valid_until if stored else None
        metrics = dict(finding.metrics) if finding is not None else dict(stored.metrics if stored else {})
        cursor.execute(
            STATE_UPSERT_SQL,
            (
                evaluation.instrument_id,
                evaluation.scanner_id,
                evaluation.timeframe.value,
                state_key,
                decision.new_state.status.value,
                evaluation.scanner_version,
                evaluation.ruleset_hash,
                valid_from,
                valid_until,
                evaluation.bar_time,
                decision.new_state.unknown_bars,
                canonical_json(metrics),
            ),
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("active_states state_id döndürmedi")
        return str(row[0])

    @staticmethod
    def _persist_transitions(
        cursor: Any,
        run: ScanRun,
        state_id: str,
        state_key: str,
        stored: _StoredState | None,
        decision: TransitionDecision,
    ) -> list[str]:
        evaluation = run.evaluation
        ids: list[str] = []
        next_key = (
            state_key
            if decision.new_state.status
            in {StateStatus.ACTIVE, StateStatus.UNKNOWN, StateStatus.HALTED}
            else None
        )
        for transition in decision.transitions:
            transition_key = stable_hash(
                {
                    "instrument_id": evaluation.instrument_id,
                    "scanner_id": evaluation.scanner_id,
                    "timeframe": evaluation.timeframe,
                    "bar_time": evaluation.bar_time,
                    "previous_state_key": stored.snapshot.state_key if stored else None,
                    "next_state_key": next_key,
                    "transition_type": transition,
                    "producer_version": evaluation.scanner_version,
                    "ruleset_hash": evaluation.ruleset_hash,
                }
            )
            cursor.execute(
                TRANSITION_SQL,
                (
                    transition_key,
                    state_id,
                    evaluation.instrument_id,
                    evaluation.scanner_id,
                    evaluation.timeframe.value,
                    stored.snapshot.state_key if stored else None,
                    next_key,
                    transition.value,
                    decision.reason.value,
                    decision.timing_uncertain,
                    evaluation.bar_time,
                    evaluation.scanner_version,
                    evaluation.ruleset_hash,
                ),
            )
            row = cursor.fetchone()
            if row:
                ids.append(str(row[0]))
        return ids

    @staticmethod
    def _persist_outbox(cursor: Any, envelope: OutboxEnvelope) -> int:
        payload = {
            "publication_kind": envelope.publication_kind.value,
            "chat_id": envelope.chat_id,
            "message_thread_id": envelope.message_thread_id,
            "message": envelope.payload,
        }
        cursor.execute(
            OUTBOX_SQL,
            (
                envelope.semantic_key,
                envelope.publication_kind.value,
                envelope.topic_kind.value,
                envelope.chat_id,
                envelope.message_thread_id,
                canonical_json(payload),
            ),
        )
        return 1 if cursor.fetchone() else 0
