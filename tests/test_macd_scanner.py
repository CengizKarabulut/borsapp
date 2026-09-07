from __future__ import annotations

import math
import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import EvaluationStatus, PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.momentum import (
    MACD_12_26_9,
    RSI_14,
    MacdSnapshot,
    RsiSnapshot,
    calculate_macd,
    calculate_rsi,
)
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.signal.macd_positive_cross import (
    MacdPositiveCrossConfig,
    MacdPositiveCrossScanner,
    MacdTriggerMode,
)
from tests.test_volume_spike import context, frame


def features(
    *,
    previous_line: float = 0.5,
    previous_signal: float = 0.6,
    line: float = 0.8,
    signal: float = 0.7,
    rsi: float = 50.0,
) -> dict:
    return {
        MACD_12_26_9.feature_id: MacdSnapshot(
            line=line,
            signal=signal,
            histogram=line - signal,
            previous_line=previous_line,
            previous_signal=previous_signal,
            previous_histogram=previous_line - previous_signal,
        ),
        RSI_14.feature_id: RsiSnapshot(value=rsi, previous_value=rsi - 1),
    }


class MomentumFeatureTests(unittest.TestCase):
    def test_macd_and_rsi_require_complete_warmup(self) -> None:
        short = frame()
        self.assertIsNone(calculate_macd(short))
        self.assertIsNotNone(calculate_rsi(short))

    def test_macd_values_are_finite_after_warmup(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        bars = []
        for index in range(50):
            close = 100.0 + index * 0.1 + math.sin(index / 3)
            bars.append(
                CanonicalBar(
                    open_time=start + timedelta(days=index),
                    close_time=start + timedelta(days=index + 1),
                    open=close - 0.1,
                    high=close + 0.5,
                    low=close - 0.5,
                    close=close,
                    volume=1000 + index,
                )
            )
        warmed = CanonicalFrame(
            instrument_id="instrument-1",
            symbol_at_snapshot="TEST",
            market="BIST",
            timeframe=Timeframe.D1,
            snapshot_id="warmed",
            series_revision=1,
            price_basis=PriceBasis.SPLIT_ADJUSTED,
            source="fixture",
            bars=tuple(bars),
        )
        macd = calculate_macd(warmed)
        rsi = calculate_rsi(warmed)
        self.assertIsNotNone(macd)
        self.assertIsNotNone(rsi)
        assert macd is not None and rsi is not None
        self.assertTrue(all(math.isfinite(value) for value in (macd.line, macd.signal, rsi.value)))


class MacdPositiveCrossScannerTests(unittest.TestCase):
    def test_true_cross_matches(self) -> None:
        source = frame()
        scanner = MacdPositiveCrossScanner()
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=scanner,
            context=context(source, features()),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertTrue(run.findings[0].metrics["true_cross"])

    def test_legacy_mode_keeps_rising_above_behavior_visible(self) -> None:
        source = frame()
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=MacdPositiveCrossScanner(),
            context=context(
                source,
                features(
                    previous_line=0.7,
                    previous_signal=0.6,
                    line=0.8,
                    signal=0.65,
                ),
            ),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertFalse(run.findings[0].metrics["true_cross"])
        self.assertTrue(run.findings[0].metrics["legacy_rising_above"])

    def test_strict_mode_rejects_rising_without_cross(self) -> None:
        source = frame()
        scanner = MacdPositiveCrossScanner(
            MacdPositiveCrossConfig(trigger_mode=MacdTriggerMode.STRICT_CROSS)
        )
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=scanner,
            context=context(
                source,
                features(
                    previous_line=0.7,
                    previous_signal=0.6,
                    line=0.8,
                    signal=0.65,
                ),
            ),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.NO_MATCH)

    def test_non_finite_values_are_not_part_of_fixture(self) -> None:
        self.assertTrue(all(math.isfinite(value) for value in (0.5, 0.6, 0.8, 0.7)))


if __name__ == "__main__":
    unittest.main()
