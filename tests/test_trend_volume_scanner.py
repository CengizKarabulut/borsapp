from __future__ import annotations

import unittest

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.features.momentum import MACD_12_26_9, MacdSnapshot
from market_intelligence.features.trend import (
    INCLUSIVE_VOLUME_SMA_20,
    LEGACY_TREND_MA_SET,
    InclusiveVolumeSnapshot,
)
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.signal.trend_volume import (
    EmaTrendVolumeScanner,
    SmaMacdVolumeScanner,
)
from tests.test_smi_macd_scanner import long_frame, trend_snapshot
from tests.test_volume_spike import context


def confirmed_features() -> dict[str, object]:
    return {
        LEGACY_TREND_MA_SET.feature_id: trend_snapshot(),
        INCLUSIVE_VOLUME_SMA_20.feature_id: InclusiveVolumeSnapshot(1600.0, 1000.0, 1.6),
        MACD_12_26_9.feature_id: MacdSnapshot(
            line=1.0,
            signal=0.8,
            histogram=0.2,
            previous_line=0.7,
            previous_signal=0.8,
            previous_histogram=-0.1,
        ),
    }


class TrendVolumeScannerTests(unittest.TestCase):
    def test_a_m_v_1_matches_all_sma_macd_and_volume_conditions(self) -> None:
        source = long_frame()
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=SmaMacdVolumeScanner(),
            context=context(source, confirmed_features()),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.findings[0].finding_key, "sma-macd-volume")

    def test_e_v_1_matches_all_ema_and_volume_conditions(self) -> None:
        source = long_frame()
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=EmaTrendVolumeScanner(),
            context=context(source, confirmed_features()),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.findings[0].finding_key, "ema-trend-volume")

    def test_both_trend_scanners_reject_boundary_volume_ratio(self) -> None:
        source = long_frame()
        values = confirmed_features()
        values[INCLUSIVE_VOLUME_SMA_20.feature_id] = InclusiveVolumeSnapshot(
            1500.0, 1000.0, 1.5
        )
        for scanner in (SmaMacdVolumeScanner(), EmaTrendVolumeScanner()):
            with self.subTest(scanner=scanner.id):
                run = ScannerEngine().run(
                    cycle_id="cycle-1",
                    frame=source,
                    scanner=scanner,
                    context=context(source, values),
                )
                self.assertEqual(run.evaluation.status, EvaluationStatus.NO_MATCH)


if __name__ == "__main__":
    unittest.main()
