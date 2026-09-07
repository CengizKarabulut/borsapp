from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from market_intelligence.core.enums import EvaluationStatus, ResultKind
from market_intelligence.features.ma import (
    QUALIFIED_MA_PROXIMITY,
    MaProximitySnapshot,
    QualifiedMaLevel,
)
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.ma.near_zone import MaNearZoneScanner
from tests.test_volume_spike import context, frame


def level(
    ma_type: str,
    period: int,
    side: str,
    distance: float,
    quality: float,
    level_class: str = "level",
) -> QualifiedMaLevel:
    return QualifiedMaLevel(
        ma_type=ma_type,
        period=period,
        value=100.0 + distance,
        side=side,
        distance_atr=distance,
        level_class=level_class,
        touches=14,
        quality_score=quality,
    )


class MaNearZoneScannerTests(unittest.TestCase):
    def test_qualified_near_level_produces_state_with_validity(self) -> None:
        source = frame()
        next_close = source.through_bar_time + timedelta(hours=1)
        scan_context = replace(
            context(source),
            feature_values={
                QUALIFIED_MA_PROXIMITY.feature_id: MaProximitySnapshot(
                    current_price=100,
                    atr=2,
                    levels=(level("EMA", 55, "support", -0.4, 82),),
                    research_version="research-v1",
                )
            },
            declared_dependencies={"next_bar_close_time": next_close},
        )
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=MaNearZoneScanner(),
            context=scan_context,
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        finding = run.findings[0]
        self.assertEqual(finding.kind, ResultKind.STATE)
        self.assertEqual(finding.state_key, "EMA:55:support")
        self.assertEqual(finding.valid_from, source.through_bar_time)
        self.assertEqual(finding.valid_until, next_close)

    def test_unqualified_or_distant_level_is_no_match(self) -> None:
        source = frame()
        snapshot = MaProximitySnapshot(
            current_price=100,
            atr=2,
            levels=(
                level("EMA", 55, "support", -0.4, 82, "watch"),
                level("SMA", 200, "resistance", 1.5, 90),
            ),
            research_version="research-v1",
        )
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=MaNearZoneScanner(),
            context=replace(
                context(source),
                feature_values={QUALIFIED_MA_PROXIMITY.feature_id: snapshot},
            ),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.NO_MATCH)

    def test_at_most_two_levels_per_side_are_selected_by_quality(self) -> None:
        source = frame()
        snapshot = MaProximitySnapshot(
            current_price=100,
            atr=2,
            levels=(
                level("EMA", 20, "support", -0.2, 50),
                level("EMA", 55, "support", -0.5, 90),
                level("SMA", 100, "support", -0.1, 80),
            ),
            research_version="research-v1",
        )
        run = ScannerEngine().run(
            cycle_id="cycle-1",
            frame=source,
            scanner=MaNearZoneScanner(),
            context=replace(
                context(source),
                feature_values={QUALIFIED_MA_PROXIMITY.feature_id: snapshot},
            ),
        )
        self.assertEqual(len(run.findings), 2)
        self.assertEqual(
            [finding.state_key for finding in run.findings],
            ["EMA:55:support", "SMA:100:support"],
        )


if __name__ == "__main__":
    unittest.main()
