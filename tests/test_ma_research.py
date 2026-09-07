from __future__ import annotations

import math
import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.research.ma_levels import MaResearchConfig, research_ma_levels


def oscillating_frame(length: int = 500) -> CanonicalFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars = []
    for index in range(length):
        close = 100.0 + 8.0 * math.sin(index / 7.0)
        bars.append(
            CanonicalBar(
                open_time=start + timedelta(days=index),
                close_time=start + timedelta(days=index + 1),
                open=close,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1_000_000.0,
            )
        )
    return CanonicalFrame(
        instrument_id="instrument-1",
        symbol_at_snapshot="TEST",
        market="BIST",
        timeframe=Timeframe.D1,
        snapshot_id="snapshot-research",
        series_revision=1,
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        source="fixture",
        bars=tuple(bars),
    )


class MaResearchTests(unittest.TestCase):
    def test_observation_engine_is_deterministic_and_directional(self) -> None:
        config = MaResearchConfig(
            ma_types=("SMA",),
            periods=(20,),
            separation_atr=1.0,
            independence_bars=5,
            reaction_bars=4,
            hold_bars=3,
            evidence_target_touches=4,
        )
        first = research_ma_levels(oscillating_frame(), config)
        second = research_ma_levels(oscillating_frame(), config)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertIn(first[0].qualification_side, {"support", "resistance"})
        self.assertGreater(first[0].touches, 0)
        self.assertEqual(len(first[0].research_version), 64)

    def test_partial_frame_is_never_researched(self) -> None:
        frame = oscillating_frame()
        partial = CanonicalFrame(
            instrument_id=frame.instrument_id,
            symbol_at_snapshot=frame.symbol_at_snapshot,
            market=frame.market,
            timeframe=frame.timeframe,
            snapshot_id=frame.snapshot_id,
            series_revision=frame.series_revision,
            price_basis=frame.price_basis,
            source=frame.source,
            bars=frame.bars,
            is_partial=True,
        )
        with self.assertRaisesRegex(ValueError, "kısmi"):
            research_ma_levels(partial)


if __name__ == "__main__":
    unittest.main()
