from __future__ import annotations

import unittest

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.features.ma import (
    QUALIFIED_MA_PROXIMITY,
    MaProximitySnapshot,
    QualifiedMaLevel,
)
from market_intelligence.shadow.adapters.ma_live import LegacyMaLiveAdapter
from tests.test_volume_spike import frame


def level(
    ma_type: str,
    period: int,
    side: str,
    distance: float,
    quality: float,
    level_class: str = "level",
    *,
    active: bool = True,
) -> QualifiedMaLevel:
    return QualifiedMaLevel(
        ma_type=ma_type,
        period=period,
        value=10.0 + distance * 0.5,
        side=side,
        distance_atr=distance,
        level_class=level_class,
        touches=15,
        quality_score=quality,
        active_side=active,
    )


class MaLiveShadowAdapterTests(unittest.TestCase):
    def test_legacy_live_decision_uses_same_qualified_research_snapshot(self) -> None:
        source = frame()
        snapshot = MaProximitySnapshot(
            current_price=10.0,
            atr=0.5,
            levels=(
                level("EMA", 55, "support", -0.4, 80.0),
                level("SMA", 200, "resistance", 0.8, 70.0),
                level("WMA", 34, "support", -1.3, 90.0),
                level("HMA", 21, "support", -0.2, 99.0, active=False),
            ),
            research_version="research-v1",
        )

        result = LegacyMaLiveAdapter().evaluate(
            source,
            feature_values={QUALIFIED_MA_PROXIMITY.feature_id: snapshot},
        )

        self.assertEqual(result.status, EvaluationStatus.MATCH)
        self.assertEqual(
            result.finding_keys,
            ("near-zone:EMA:55:support", "near-zone:SMA:200:resistance"),
        )
        self.assertIn("ma_research_qualification:held_fixed", result.diagnostics)

    def test_missing_research_snapshot_is_unknown(self) -> None:
        result = LegacyMaLiveAdapter().evaluate(frame(), feature_values={})
        self.assertEqual(result.status, EvaluationStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
