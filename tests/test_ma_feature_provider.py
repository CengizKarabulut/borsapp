from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.ma import (
    MaQualification,
    QualifiedMaResearchProvider,
)
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame


class Source:
    def load(self, frame):
        return (
            MaQualification("SMA", 20, "level", 12, 45.0, "research-v1"),
            MaQualification("EMA", 20, "strong_level", 20, 60.0, "research-v1"),
        )


def frame() -> CanonicalFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = []
    for index in range(40):
        close = 100.0 + index
        bars.append(
            CanonicalBar(
                open_time=start + timedelta(days=index),
                close_time=start + timedelta(days=index + 1),
                open=close - 0.5,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1000 + index,
            )
        )
    return CanonicalFrame(
        instrument_id="instrument-1",
        symbol_at_snapshot="TEST",
        market="BIST",
        timeframe=Timeframe.D1,
        snapshot_id="snapshot-1",
        series_revision=1,
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        source="fixture",
        bars=tuple(bars),
    )


class QualifiedMaResearchProviderTests(unittest.TestCase):
    def test_research_qualification_becomes_live_proximity_on_canonical_frame(self) -> None:
        result = QualifiedMaResearchProvider(Source()).compute(frame())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result.levels), 2)
        self.assertTrue(all(level.side == "support" for level in result.levels))
        sma = next(level for level in result.levels if level.ma_type == "SMA")
        self.assertAlmostEqual(sma.value, sum(range(120, 140)) / 20)
        self.assertLess(sma.distance_atr, 0)
        self.assertEqual(len(result.research_version), 64)


if __name__ == "__main__":
    unittest.main()
