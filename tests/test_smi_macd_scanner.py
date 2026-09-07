from __future__ import annotations

import math
import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import EvaluationStatus, PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.momentum import (
    MACD_12_26_9,
    SMI_10_3_3,
    MacdSnapshot,
    SmiSnapshot,
    calculate_smi,
)
from market_intelligence.features.trend import (
    INCLUSIVE_VOLUME_SMA_20,
    SMA_200,
    InclusiveVolumeSma20Provider,
    InclusiveVolumeSnapshot,
    MovingAverageSnapshot,
    Sma200Provider,
)
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.signal.smi_macd_positive import (
    SmiMacdPositiveScanner,
    SmiMacdPositiveVolumeConfirmedScanner,
)
from tests.test_volume_spike import context


def long_frame() -> CanonicalFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = []
    for index in range(220):
        close = 100.0 + index * 0.2 + math.sin(index / 4)
        bars.append(
            CanonicalBar(
                open_time=start + timedelta(hours=index),
                close_time=start + timedelta(hours=index + 1),
                open=close - 0.1,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1000.0,
            )
        )
    return CanonicalFrame(
        instrument_id="instrument-1",
        symbol_at_snapshot="TEST",
        market="BIST",
        timeframe=Timeframe.H1,
        snapshot_id="smi-frame",
        series_revision=1,
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        source="fixture",
        bars=tuple(bars),
    )


def momentum_features() -> dict[str, object]:
    return {
        SMI_10_3_3.feature_id: SmiSnapshot(
            value=25.0,
            signal=20.0,
            previous_value=18.0,
            previous_signal=19.0,
        ),
        MACD_12_26_9.feature_id: MacdSnapshot(
            line=1.2,
            signal=1.0,
            histogram=0.2,
            previous_line=1.0,
            previous_signal=0.9,
            previous_histogram=0.1,
        ),
    }


class SmiFeatureTests(unittest.TestCase):
    def test_smi_is_finite_after_legacy_warmup(self) -> None:
        result = calculate_smi(long_frame())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(
            all(
                math.isfinite(value)
                for value in (
                    result.value,
                    result.signal,
                    result.previous_value,
                    result.previous_signal,
                )
            )
        )
        self.assertAlmostEqual(result.previous_value, 11.317560974193796)
        self.assertAlmostEqual(result.previous_signal, 18.95671606917423)
        self.assertAlmostEqual(result.value, 8.68189240778027)
        self.assertAlmostEqual(result.signal, 13.819304238477251)

    def test_confirmation_features_use_complete_legacy_windows(self) -> None:
        source = long_frame()
        average = Sma200Provider().compute(source)
        volume = InclusiveVolumeSma20Provider().compute(source)
        self.assertIsNotNone(average)
        self.assertIsNotNone(volume)
        assert average is not None and volume is not None
        self.assertAlmostEqual(
            average.value,
            sum(bar.close for bar in source.bars[-200:]) / 200,
        )
        self.assertEqual(volume.observed_volume, 1000.0)
        self.assertEqual(volume.mean_volume, 1000.0)
        self.assertEqual(volume.ratio, 1.0)


class SmiMacdScannerTests(unittest.TestCase):
    def test_s_m_1_matches_positive_rising_momentum(self) -> None:
        source = long_frame()
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=SmiMacdPositiveScanner(),
            context=context(source, momentum_features()),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.findings[0].finding_key, "smi-macd-positive")

    def test_s_m_v_1_requires_sma200_and_inclusive_volume_confirmation(self) -> None:
        source = long_frame()
        values = {
            **momentum_features(),
            SMA_200.feature_id: MovingAverageSnapshot(value=100.0, close=120.0),
            INCLUSIVE_VOLUME_SMA_20.feature_id: InclusiveVolumeSnapshot(
                observed_volume=1600.0,
                mean_volume=1000.0,
                ratio=1.6,
            ),
        }
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=SmiMacdPositiveVolumeConfirmedScanner(),
            context=context(source, values),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(
            run.findings[0].finding_key,
            "smi-macd-positive-volume-confirmed",
        )

    def test_s_m_v_1_rejects_weak_volume(self) -> None:
        source = long_frame()
        values = {
            **momentum_features(),
            SMA_200.feature_id: MovingAverageSnapshot(value=100.0, close=120.0),
            INCLUSIVE_VOLUME_SMA_20.feature_id: InclusiveVolumeSnapshot(
                observed_volume=1400.0,
                mean_volume=1000.0,
                ratio=1.4,
            ),
        }
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=SmiMacdPositiveVolumeConfirmedScanner(),
            context=context(source, values),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.NO_MATCH)


if __name__ == "__main__":
    unittest.main()
