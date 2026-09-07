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
    LEGACY_TREND_MA_SET,
    InclusiveVolumeSma20Provider,
    InclusiveVolumeSnapshot,
    LegacyTrendMaProvider,
    LegacyTrendMaSnapshot,
)
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.signal.smi_macd_positive import (
    SmiMacdEarlyScanner,
    SmiMacdFullScanner,
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


def trend_snapshot(close: float = 120.0, long_average: float = 100.0) -> LegacyTrendMaSnapshot:
    return LegacyTrendMaSnapshot(
        close=close,
        sma={5: 115.0, 8: 114.0, 21: 112.0, 50: 108.0, 55: 107.0, 200: long_average},
        ema={5: 119.0, 8: 118.0, 13: 117.0, 21: 112.0, 55: 108.0, 200: 100.0},
        previous_ema={5: 117.0, 8: 116.0, 13: 116.5, 21: 111.0, 55: 107.0, 200: 99.0},
    )


def negative_momentum_features() -> dict[str, object]:
    return {
        SMI_10_3_3.feature_id: SmiSnapshot(
            value=-20.0,
            signal=-25.0,
            previous_value=-30.0,
            previous_signal=-28.0,
        ),
        MACD_12_26_9.feature_id: MacdSnapshot(
            line=-1.0,
            signal=-0.9,
            histogram=-0.1,
            previous_line=-1.2,
            previous_signal=-1.0,
            previous_histogram=-0.2,
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
        average = LegacyTrendMaProvider().compute(source)
        volume = InclusiveVolumeSma20Provider().compute(source)
        self.assertIsNotNone(average)
        self.assertIsNotNone(volume)
        assert average is not None and volume is not None
        self.assertAlmostEqual(
            average.sma[200],
            sum(bar.close for bar in source.bars[-200:]) / 200,
        )
        self.assertAlmostEqual(average.sma[5], 142.69925007169462)
        self.assertAlmostEqual(average.sma[55], 138.337497768505)
        self.assertAlmostEqual(average.ema[5], 142.72781953933813)
        self.assertAlmostEqual(average.previous_ema[5], 142.67880403562785)
        self.assertAlmostEqual(average.ema[200], 126.13405357428543)
        self.assertAlmostEqual(average.previous_ema[200], 125.96629682079323)
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
            LEGACY_TREND_MA_SET.feature_id: trend_snapshot(),
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
            LEGACY_TREND_MA_SET.feature_id: trend_snapshot(),
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

    def test_s_m_2_and_s_m_v_2_are_mutually_exclusive(self) -> None:
        source = long_frame()
        early_values = {
            **negative_momentum_features(),
            LEGACY_TREND_MA_SET.feature_id: trend_snapshot(close=90.0),
            INCLUSIVE_VOLUME_SMA_20.feature_id: InclusiveVolumeSnapshot(1000.0, 1000.0, 1.0),
        }
        early = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=SmiMacdEarlyScanner(),
            context=context(source, early_values),
        )
        full_on_early = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=SmiMacdFullScanner(),
            context=context(source, early_values),
        )
        self.assertEqual(early.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(full_on_early.evaluation.status, EvaluationStatus.NO_MATCH)

        full_values = {
            **negative_momentum_features(),
            LEGACY_TREND_MA_SET.feature_id: trend_snapshot(),
            INCLUSIVE_VOLUME_SMA_20.feature_id: InclusiveVolumeSnapshot(1600.0, 1000.0, 1.6),
        }
        early_on_full = ScannerEngine().run(
            cycle_id="cycle-2",
            frame=source,
            scanner=SmiMacdEarlyScanner(),
            context=context(source, full_values),
        )
        full = ScannerEngine().run(
            cycle_id="cycle-2",
            frame=source,
            scanner=SmiMacdFullScanner(),
            context=context(source, full_values),
        )
        self.assertEqual(early_on_full.evaluation.status, EvaluationStatus.NO_MATCH)
        self.assertEqual(full.evaluation.status, EvaluationStatus.MATCH)


if __name__ == "__main__":
    unittest.main()
