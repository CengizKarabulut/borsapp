from __future__ import annotations

import unittest
from dataclasses import replace

from market_intelligence.confluence.engine import (
    ConfluenceEngine,
    ConfluenceMode,
    ConfluencePolicy,
    FindingObservation,
)
from market_intelligence.core.enums import Direction, EvaluationStatus
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.volume import RELATIVE_VOLUME_20, calculate_volume_activity
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.signal.macd_positive_cross import MacdPositiveCrossScanner
from market_intelligence.scanning.technical.volume_spike import (
    TechnicalVolumeSpikeScanner,
    VolumeSpikeConfig,
)
from tests.test_macd_scanner import features
from tests.test_volume_spike import context, frame


def findings():
    source = frame()
    technical = ScannerEngine().run(
        cycle_id="cycle",
        frame=source,
        scanner=TechnicalVolumeSpikeScanner(
            VolumeSpikeConfig(minimum_average_turnover=0)
        ),
        context=context(
            source,
            {RELATIVE_VOLUME_20.feature_id: calculate_volume_activity(source)},
        ),
    ).findings[0]
    signal = ScannerEngine().run(
        cycle_id="cycle",
        frame=source,
        scanner=MacdPositiveCrossScanner(),
        context=context(source, features()),
    ).findings[0]
    return source, technical, signal


class ConfluenceTests(unittest.TestCase):
    def test_strict_requires_same_bar_and_timeframe(self) -> None:
        source, technical, signal = findings()
        report = ConfluenceEngine().evaluate(
            instrument_id=source.instrument_id,
            symbol=source.symbol_at_snapshot,
            reference_time=source.through_bar_time,
            reference_timeframe=source.timeframe,
            observations=(
                FindingObservation(technical, 0),
                FindingObservation(signal, 0),
            ),
            coverage={
                "technical": EvaluationStatus.MATCH,
                "signal": EvaluationStatus.MATCH,
                "ma": EvaluationStatus.UNKNOWN,
            },
            policy=ConfluencePolicy(ConfluenceMode.STRICT),
        )
        self.assertTrue(report.qualifies)
        self.assertEqual(report.families, ("signal", "technical"))
        self.assertEqual(report.unknown_families, ("ma",))

    def test_recent_window_uses_explicit_bar_age(self) -> None:
        source, technical, signal = findings()
        report = ConfluenceEngine().evaluate(
            instrument_id=source.instrument_id,
            symbol=source.symbol_at_snapshot,
            reference_time=source.through_bar_time,
            reference_timeframe=source.timeframe,
            observations=(
                FindingObservation(technical, 0),
                FindingObservation(signal, 3),
            ),
            coverage={},
            policy=ConfluencePolicy(ConfluenceMode.RECENT_N, recent_bars=3),
        )
        self.assertFalse(report.qualifies)

    def test_opposite_directions_are_not_hidden(self) -> None:
        source, technical, signal = findings()
        bearish_technical = replace(technical, direction=Direction.BEARISH)
        report = ConfluenceEngine().evaluate(
            instrument_id=source.instrument_id,
            symbol=source.symbol_at_snapshot,
            reference_time=source.through_bar_time,
            reference_timeframe=Timeframe.H1,
            observations=(
                FindingObservation(bearish_technical, 0),
                FindingObservation(signal, 0),
            ),
            coverage={},
            policy=ConfluencePolicy(ConfluenceMode.CROSS_TIMEFRAME),
        )
        self.assertTrue(report.qualifies)
        self.assertTrue(report.direction_conflict)


if __name__ == "__main__":
    unittest.main()
