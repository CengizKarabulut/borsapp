from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import EvaluationStatus, PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.registry import (
    FeatureEngine,
    FeatureRegistry,
    InMemoryFeatureCache,
)
from market_intelligence.features.volume import (
    RELATIVE_VOLUME_20,
    RelativeVolume20Provider,
    calculate_volume_activity,
)
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.contracts import ScanContext
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.pipeline import ScanPipeline
from market_intelligence.scanning.technical.volume_spike import (
    TechnicalVolumeSpikeScanner,
    VolumeSpikeConfig,
)


def frame(*, last_volume: float = 400.0, partial: bool = False) -> CanonicalFrame:
    start = datetime(2026, 9, 1, 7, 0, tzinfo=UTC)
    bars = []
    for index in range(21):
        open_time = start + timedelta(hours=index)
        volume = last_volume if index == 20 else 100.0
        bars.append(
            CanonicalBar(
                open_time=open_time,
                close_time=open_time + timedelta(hours=1),
                open=10.0,
                high=10.5,
                low=9.5,
                close=10.0,
                volume=volume,
            )
        )
    return CanonicalFrame(
        instrument_id="instrument-1",
        symbol_at_snapshot="TEST",
        market="BIST",
        timeframe=Timeframe.H1,
        snapshot_id="snapshot-1",
        series_revision=1,
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        source="fixture",
        bars=tuple(bars),
        is_partial=partial,
    )


def context(source: CanonicalFrame, features: dict | None = None) -> ScanContext:
    return ScanContext(
        evaluation_time=source.through_bar_time + timedelta(seconds=5),
        bar_close_time=source.through_bar_time,
        market_session_id="BIST:2026-09-01",
        calendar_version="bist-v1",
        ruleset_hash="ruleset-1",
        feature_values=features or {},
    )


class VolumeFeatureTests(unittest.TestCase):
    def test_current_bar_is_excluded_from_baseline(self) -> None:
        activity = calculate_volume_activity(frame())
        self.assertIsNotNone(activity)
        assert activity is not None
        self.assertEqual(activity.baseline_volume, 100.0)
        self.assertEqual(activity.relative_volume, 4.0)
        self.assertEqual(activity.baseline_bar_count, 20)

    def test_partial_bar_does_not_produce_feature(self) -> None:
        self.assertIsNone(calculate_volume_activity(frame(partial=True)))

    def test_feature_is_computed_once_per_canonical_snapshot(self) -> None:
        registry = FeatureRegistry()
        registry.register(RelativeVolume20Provider())
        engine = FeatureEngine(registry, InMemoryFeatureCache())
        source = frame()
        first = engine.resolve(source, [RELATIVE_VOLUME_20])
        second = engine.resolve(source, [RELATIVE_VOLUME_20])
        self.assertEqual((first.computed, first.cache_hits), (1, 0))
        self.assertEqual((second.computed, second.cache_hits), (0, 1))

    def test_partial_feature_is_cached_as_unavailable(self) -> None:
        registry = FeatureRegistry()
        registry.register(RelativeVolume20Provider())
        engine = FeatureEngine(registry)
        source = frame(partial=True)
        first = engine.resolve(source, [RELATIVE_VOLUME_20])
        second = engine.resolve(source, [RELATIVE_VOLUME_20])
        self.assertEqual(first.unavailable, (RELATIVE_VOLUME_20.feature_id,))
        self.assertEqual((second.computed, second.cache_hits), (0, 1))


class VolumeSpikeScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ScannerEngine()
        self.scanner = TechnicalVolumeSpikeScanner(
            VolumeSpikeConfig(
                relative_volume_threshold=3.0,
                minimum_average_turnover=0.0,
                minimum_price=1.0,
            )
        )

    def test_closed_bar_matches(self) -> None:
        source = frame()
        activity = calculate_volume_activity(source)
        run = self.engine.run(
            cycle_id="cycle-1",
            frame=source,
            scanner=self.scanner,
            context=context(source, {RELATIVE_VOLUME_20.feature_id: activity}),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.evaluation.finding_count, 1)
        self.assertEqual(run.findings[0].metrics["relative_volume"], 4.0)

    def test_below_threshold_is_no_match(self) -> None:
        source = frame(last_volume=200.0)
        activity = calculate_volume_activity(source)
        run = self.engine.run(
            cycle_id="cycle-1",
            frame=source,
            scanner=self.scanner,
            context=context(source, {RELATIVE_VOLUME_20.feature_id: activity}),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.NO_MATCH)

    def test_missing_feature_is_unknown(self) -> None:
        source = frame()
        run = self.engine.run(
            cycle_id="cycle-1",
            frame=source,
            scanner=self.scanner,
            context=context(source),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.UNKNOWN)
        self.assertEqual(run.evaluation.error_code, "missing_features")

    def test_partial_bar_is_unknown_not_no_match(self) -> None:
        source = frame(partial=True)
        run = self.engine.run(
            cycle_id="cycle-1",
            frame=source,
            scanner=self.scanner,
            context=context(source, {RELATIVE_VOLUME_20.feature_id: object()}),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.UNKNOWN)
        self.assertEqual(run.evaluation.error_code, "partial_bar_rejected")

    def test_pipeline_resolves_feature_and_runs_scanner(self) -> None:
        registry = FeatureRegistry()
        registry.register(RelativeVolume20Provider())
        pipeline = ScanPipeline(FeatureEngine(registry))
        source = frame()
        result = pipeline.run(
            cycle_id="cycle-1",
            frame=source,
            scanner=self.scanner,
            context=context(source),
        )
        self.assertEqual(result.features.computed, 1)
        self.assertEqual(result.scan.evaluation.status, EvaluationStatus.MATCH)


if __name__ == "__main__":
    unittest.main()
