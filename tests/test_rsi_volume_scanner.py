from __future__ import annotations

import unittest

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.features.momentum import (
    LEGACY_RSI_7,
    LEGACY_RSI_14,
    MACD_12_26_9,
    MacdSnapshot,
    RsiSnapshot,
    calculate_legacy_rsi,
)
from market_intelligence.features.trend import (
    INCLUSIVE_VOLUME_SMA_10,
    INCLUSIVE_VOLUME_SMA_20,
    InclusiveVolumeSnapshot,
)
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.signal.rsi_volume import (
    RsiMacdVolumeScanner,
    RsiMomentumVolumeScanner,
)
from tests.test_smi_macd_scanner import long_frame
from tests.test_volume_spike import context


def volume(period: int, ratio: float) -> tuple[str, InclusiveVolumeSnapshot]:
    feature = INCLUSIVE_VOLUME_SMA_10 if period == 10 else INCLUSIVE_VOLUME_SMA_20
    return feature.feature_id, InclusiveVolumeSnapshot(
        observed_volume=1000.0 * ratio,
        mean_volume=1000.0,
        ratio=ratio,
    )


class LegacyRsiFeatureTests(unittest.TestCase):
    def test_rsi7_matches_legacy_pandas_golden_values(self) -> None:
        result = calculate_legacy_rsi(long_frame(), 7)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result.previous_value, 85.7229862112372)
        self.assertAlmostEqual(result.value, 88.06355986880865)


class RsiVolumeScannerTests(unittest.TestCase):
    def test_r_v_1_matches_strength_rise_and_volume(self) -> None:
        source = long_frame()
        volume_key, volume_value = volume(10, 1.6)
        values = {
            LEGACY_RSI_7.feature_id: RsiSnapshot(65.0, 59.0),
            volume_key: volume_value,
        }
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=RsiMomentumVolumeScanner(),
            context=context(source, values),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)

    def test_r_m_v_1_matches_without_requiring_positive_macd(self) -> None:
        source = long_frame()
        volume_key, volume_value = volume(20, 1.6)
        values = {
            LEGACY_RSI_14.feature_id: RsiSnapshot(60.0, 55.0),
            MACD_12_26_9.feature_id: MacdSnapshot(
                line=-0.5,
                signal=-0.6,
                histogram=0.1,
                previous_line=-0.7,
                previous_signal=-0.6,
                previous_histogram=-0.1,
            ),
            volume_key: volume_value,
        }
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=RsiMacdVolumeScanner(),
            context=context(source, values),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)

    def test_r_m_v_1_rejects_rsi_at_upper_boundary(self) -> None:
        source = long_frame()
        volume_key, volume_value = volume(20, 1.6)
        values = {
            LEGACY_RSI_14.feature_id: RsiSnapshot(70.0, 60.0),
            MACD_12_26_9.feature_id: MacdSnapshot(
                line=0.5,
                signal=0.4,
                histogram=0.1,
                previous_line=0.3,
                previous_signal=0.4,
                previous_histogram=-0.1,
            ),
            volume_key: volume_value,
        }
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=RsiMacdVolumeScanner(),
            context=context(source, values),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.NO_MATCH)


if __name__ == "__main__":
    unittest.main()
