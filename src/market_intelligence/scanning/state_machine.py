from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import (
    EvaluationStatus,
    StateStatus,
    TransitionReason,
    TransitionType,
)


@dataclass(frozen=True)
class StateSnapshot:
    status: StateStatus
    state_key: str | None = None
    unknown_bars: int = 0
    producer_version: str | None = None
    ruleset_hash: str | None = None


@dataclass(frozen=True)
class StateObservation:
    status: EvaluationStatus
    state_key: str | None = None
    producer_version: str | None = None
    ruleset_hash: str | None = None
    reason: TransitionReason = TransitionReason.MARKET


@dataclass(frozen=True)
class TransitionDecision:
    new_state: StateSnapshot
    transitions: tuple[TransitionType, ...] = ()
    reason: TransitionReason = TransitionReason.MARKET
    timing_uncertain: bool = False
    notify: bool = False


def reconcile_state(
    previous: StateSnapshot | None,
    observation: StateObservation,
    *,
    producer_changed: bool = False,
    instrument_halted: bool = False,
    abandon_after_unknown_bars: int | None = None,
) -> TransitionDecision:
    if abandon_after_unknown_bars is not None and abandon_after_unknown_bars < 1:
        raise ValueError("ABANDONED eşiği en az bir bar olmalıdır")

    if instrument_halted:
        transition = (
            ()
            if previous is not None and previous.status is StateStatus.HALTED
            else (TransitionType.INSTRUMENT_HALTED,)
        )
        return TransitionDecision(
            StateSnapshot(
                status=StateStatus.HALTED,
                state_key=previous.state_key if previous else observation.state_key,
                producer_version=observation.producer_version,
                ruleset_hash=observation.ruleset_hash,
            ),
            transition,
            TransitionReason.INSTRUMENT_HALTED,
            notify=False,
        )

    if producer_changed:
        transitions: list[TransitionType] = []
        if previous is not None and previous.status not in {
            StateStatus.INACTIVE,
            StateStatus.SUPERSEDED,
        }:
            transitions.append(TransitionType.SUPERSEDED)
        if observation.status is EvaluationStatus.MATCH:
            transitions.append(TransitionType.ADOPTED)
            new_status = StateStatus.ACTIVE
        elif observation.status is EvaluationStatus.NO_MATCH:
            new_status = StateStatus.INACTIVE
        else:
            new_status = StateStatus.UNKNOWN
        return TransitionDecision(
            StateSnapshot(
                status=new_status,
                state_key=observation.state_key,
                unknown_bars=1 if new_status is StateStatus.UNKNOWN else 0,
                producer_version=observation.producer_version,
                ruleset_hash=observation.ruleset_hash,
            ),
            tuple(transitions),
            observation.reason,
            notify=False,
        )

    if observation.status is EvaluationStatus.UNKNOWN:
        unknown_bars = (
            previous.unknown_bars + 1
            if previous is not None and previous.status is StateStatus.UNKNOWN
            else 1
        )
        if (
            abandon_after_unknown_bars is not None
            and unknown_bars >= abandon_after_unknown_bars
        ):
            return TransitionDecision(
                StateSnapshot(
                    status=StateStatus.ABANDONED,
                    state_key=previous.state_key if previous else observation.state_key,
                    unknown_bars=unknown_bars,
                    producer_version=observation.producer_version,
                    ruleset_hash=observation.ruleset_hash,
                ),
                (TransitionType.ABANDONED,),
                TransitionReason.TIMEOUT,
                notify=False,
            )
        transition = (
            ()
            if previous is not None and previous.status is StateStatus.UNKNOWN
            else (TransitionType.UNKNOWN,)
        )
        return TransitionDecision(
            StateSnapshot(
                status=StateStatus.UNKNOWN,
                state_key=previous.state_key if previous else observation.state_key,
                unknown_bars=unknown_bars,
                producer_version=observation.producer_version,
                ruleset_hash=observation.ruleset_hash,
            ),
            transition,
            observation.reason,
            notify=False,
        )

    if observation.status is EvaluationStatus.MATCH:
        new_state = StateSnapshot(
            status=StateStatus.ACTIVE,
            state_key=observation.state_key,
            producer_version=observation.producer_version,
            ruleset_hash=observation.ruleset_hash,
        )
        if previous is None or previous.status in {
            StateStatus.INACTIVE,
            StateStatus.ABANDONED,
            StateStatus.HALTED,
        }:
            return TransitionDecision(
                new_state,
                (TransitionType.ENTER,),
                observation.reason,
                notify=True,
            )
        if previous.status is StateStatus.UNKNOWN:
            return TransitionDecision(
                new_state,
                (TransitionType.RESUMED,),
                observation.reason,
                notify=True,
            )
        if previous.state_key != observation.state_key:
            return TransitionDecision(
                new_state,
                (TransitionType.CHANGE,),
                observation.reason,
                notify=True,
            )
        return TransitionDecision(new_state, reason=observation.reason)

    new_state = StateSnapshot(
        status=StateStatus.INACTIVE,
        producer_version=observation.producer_version,
        ruleset_hash=observation.ruleset_hash,
    )
    if previous is None or previous.status in {
        StateStatus.INACTIVE,
        StateStatus.ABANDONED,
        StateStatus.HALTED,
    }:
        return TransitionDecision(new_state, reason=observation.reason)
    if previous.status is StateStatus.UNKNOWN:
        return TransitionDecision(
            new_state,
            (TransitionType.EXIT_INFERRED,),
            observation.reason,
            timing_uncertain=True,
            notify=True,
        )
    return TransitionDecision(
        new_state,
        (TransitionType.EXIT,),
        observation.reason,
        notify=True,
    )
