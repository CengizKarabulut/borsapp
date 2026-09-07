from __future__ import annotations

import unittest

from market_intelligence.core.enums import (
    EvaluationStatus,
    StateStatus,
    TransitionReason,
    TransitionType,
)
from market_intelligence.scanning.state_machine import (
    StateObservation,
    StateSnapshot,
    reconcile_state,
)


class StateMachineTests(unittest.TestCase):
    def observation(
        self,
        status: EvaluationStatus,
        key: str | None = "EMA55:support",
    ) -> StateObservation:
        return StateObservation(
            status=status,
            state_key=key,
            producer_version="2",
            ruleset_hash="rules-v2",
        )

    def test_unknown_never_creates_false_exit(self) -> None:
        previous = StateSnapshot(StateStatus.ACTIVE, "EMA55:support")
        decision = reconcile_state(previous, self.observation(EvaluationStatus.UNKNOWN))
        self.assertEqual(decision.new_state.status, StateStatus.UNKNOWN)
        self.assertEqual(decision.transitions, (TransitionType.UNKNOWN,))
        self.assertFalse(decision.notify)

    def test_unknown_is_abandoned_after_threshold(self) -> None:
        previous = StateSnapshot(StateStatus.UNKNOWN, "EMA55:support", unknown_bars=2)
        decision = reconcile_state(
            previous,
            self.observation(EvaluationStatus.UNKNOWN),
            abandon_after_unknown_bars=3,
        )
        self.assertEqual(decision.new_state.status, StateStatus.ABANDONED)
        self.assertEqual(decision.transitions, (TransitionType.ABANDONED,))
        self.assertFalse(decision.notify)

    def test_unknown_recovery_is_resumed(self) -> None:
        previous = StateSnapshot(StateStatus.UNKNOWN, "EMA55:support", unknown_bars=2)
        decision = reconcile_state(previous, self.observation(EvaluationStatus.MATCH))
        self.assertEqual(decision.transitions, (TransitionType.RESUMED,))
        self.assertTrue(decision.notify)

    def test_unknown_to_no_match_is_uncertain_exit(self) -> None:
        previous = StateSnapshot(StateStatus.UNKNOWN, "EMA55:support", unknown_bars=2)
        decision = reconcile_state(previous, self.observation(EvaluationStatus.NO_MATCH))
        self.assertEqual(decision.transitions, (TransitionType.EXIT_INFERRED,))
        self.assertTrue(decision.timing_uncertain)

    def test_deploy_uses_superseded_and_adopted_without_notification(self) -> None:
        previous = StateSnapshot(
            StateStatus.ACTIVE,
            "EMA55:support",
            producer_version="1",
            ruleset_hash="rules-v1",
        )
        decision = reconcile_state(
            previous,
            self.observation(EvaluationStatus.MATCH),
            producer_changed=True,
        )
        self.assertEqual(
            decision.transitions,
            (TransitionType.SUPERSEDED, TransitionType.ADOPTED),
        )
        self.assertFalse(decision.notify)

    def test_halt_is_not_unknown(self) -> None:
        previous = StateSnapshot(StateStatus.ACTIVE, "EMA55:support")
        decision = reconcile_state(
            previous,
            self.observation(EvaluationStatus.UNKNOWN),
            instrument_halted=True,
        )
        self.assertEqual(decision.new_state.status, StateStatus.HALTED)
        self.assertEqual(decision.transitions, (TransitionType.INSTRUMENT_HALTED,))
        self.assertEqual(decision.reason, TransitionReason.INSTRUMENT_HALTED)


if __name__ == "__main__":
    unittest.main()
