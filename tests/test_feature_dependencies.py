from __future__ import annotations

import unittest
from datetime import timedelta

from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.features.technical import (
    TECHNICAL_MARKET_CONTEXT,
    TechnicalMarketContextProvider,
)
from market_intelligence.features.volatility import WILDER_ATR_14, WilderAtr14Provider
from tests.test_volume_spike import frame


def long_frame():
    source = frame()
    bars = list(source.bars)
    for index in range(21, 80):
        prior = bars[-1]
        bars.append(
            type(prior)(
                open_time=prior.close_time,
                close_time=prior.close_time + timedelta(hours=1),
                open=10.0,
                high=10.5,
                low=9.5,
                close=10.0,
                volume=100.0 + index,
            )
        )
    return type(source)(
        instrument_id=source.instrument_id,
        symbol_at_snapshot=source.symbol_at_snapshot,
        market=source.market,
        timeframe=source.timeframe,
        snapshot_id=source.snapshot_id,
        series_revision=source.series_revision,
        price_basis=source.price_basis,
        source=source.source,
        bars=tuple(bars),
    )


class CountingAtrProvider(WilderAtr14Provider):
    def __init__(self) -> None:
        self.calls = 0

    def compute(self, frame):
        self.calls += 1
        return super().compute(frame)


class FeatureDependencyTests(unittest.TestCase):
    def test_shared_atr_dependency_is_computed_once_per_snapshot(self) -> None:
        registry = FeatureRegistry()
        atr = CountingAtrProvider()
        registry.register(atr)
        registry.register(TechnicalMarketContextProvider())
        engine = FeatureEngine(registry)
        source = long_frame()

        resolution = engine.resolve(source, [TECHNICAL_MARKET_CONTEXT, WILDER_ATR_14])

        self.assertIn(TECHNICAL_MARKET_CONTEXT.feature_id, resolution.values)
        self.assertIn(WILDER_ATR_14.feature_id, resolution.values)
        self.assertEqual(atr.calls, 1)
        self.assertEqual(resolution.computed, 2)

    def test_dependency_cycle_is_rejected(self) -> None:
        registry = FeatureRegistry()

        class Provider:
            spec = WILDER_ATR_14
            dependencies = (WILDER_ATR_14,)

            def compute_with_dependencies(self, frame, values):
                return object()

        registry.register(Provider())
        with self.assertRaisesRegex(ValueError, "bağımlılık döngüsü"):
            FeatureEngine(registry).resolve(long_frame(), [WILDER_ATR_14])


if __name__ == "__main__":
    unittest.main()
