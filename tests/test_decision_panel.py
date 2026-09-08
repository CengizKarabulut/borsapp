from __future__ import annotations

import math
import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import EvaluationStatus, PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.decision import (
    DECISION_PANEL_V645,
    DecisionPanelSnapshot,
    DecisionPanelV645Provider,
)
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.contracts import ScanContext
from market_intelligence.scanning.decision.panel_v645 import DecisionPanelV645Scanner
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.shadow.adapters.taramabot_decision import (
    LegacyTaramabotDecisionAdapter,
)


def daily_frame(count: int = 340) -> CanonicalFrame:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = []
    for index in range(count):
        trend = 40.0 + index * 0.12
        wave = math.sin(index / 7.0) * 1.5
        close = trend + wave
        open_price = close - math.sin(index / 3.0) * 0.4
        bars.append(
            CanonicalBar(
                open_time=start + timedelta(days=index),
                close_time=start + timedelta(days=index + 1),
                open=open_price,
                high=max(open_price, close) + 0.8,
                low=min(open_price, close) - 0.7,
                close=close,
                volume=1_000_000.0 * (1.0 + (index % 11) / 20.0),
            )
        )
    return CanonicalFrame(
        instrument_id="instrument-decision",
        symbol_at_snapshot="TEST",
        market="BIST",
        timeframe=Timeframe.D1,
        snapshot_id="snapshot-decision",
        series_revision=1,
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        source="fixture",
        bars=tuple(bars),
    )


class DecisionPanelTests(unittest.TestCase):
    def test_canonical_feature_matches_frozen_legacy_latest_decision(self) -> None:
        source = daily_frame()
        current = DecisionPanelV645Provider().compute(source)
        legacy_adapter = LegacyTaramabotDecisionAdapter()
        legacy_adapter._load()
        from market_intelligence.shadow.bridge import to_legacy_frame

        legacy = legacy_adapter._latest_decision(to_legacy_frame(source), min_score=75)

        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current.score, legacy["score"])
        self.assertEqual(current.active_setup, legacy["active_setup"])
        self.assertEqual(current.new_setup, legacy["new_setup"])
        self.assertEqual(current.entry, legacy["entry"])
        self.assertAlmostEqual(current.relative_volume, legacy["rvol"], places=10)
        self.assertAlmostEqual(current.pct20, legacy["pct20"], places=10)
        self.assertAlmostEqual(current.adx, legacy["adx"], places=10)
        self.assertEqual(current.pullback_guard, legacy["pullback_guard"])
        self.assertEqual(current.pullback_base, legacy["pullback_base"])

    def test_new_entry_becomes_bullish_event(self) -> None:
        source = daily_frame()
        snapshot = DecisionPanelSnapshot(
            score=88,
            active_setup="BREAKOUT",
            new_setup="BREAKOUT",
            entry=True,
            relative_volume=1.8,
            pct20=100.0,
            adx=31.0,
            pullback_guard=False,
            pullback_base=False,
        )
        context = ScanContext(
            evaluation_time=source.through_bar_time + timedelta(seconds=5),
            bar_close_time=source.through_bar_time,
            market_session_id="BIST:fixture",
            calendar_version="bist-session-v1",
            ruleset_hash="rules-decision",
            feature_values={DECISION_PANEL_V645.feature_id: snapshot},
        )
        run = ScannerEngine().run(
            cycle_id="cycle-decision",
            frame=source,
            scanner=DecisionPanelV645Scanner(),
            context=context,
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.findings[0].finding_key, "entry:breakout")


if __name__ == "__main__":
    unittest.main()
