from __future__ import annotations

import unittest

from market_intelligence.core.enums import Direction, EvaluationStatus, ResultKind
from market_intelligence.features.technical import (
    TECHNICAL_MARKET_CONTEXT,
    TechnicalMarketContext,
)
from market_intelligence.features.volume import RELATIVE_VOLUME_20, VolumeActivity
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.technical.market_screens import (
    DecisionZoneScanner,
    ExhaustionScanner,
    ExtremeRsiScanner,
    FailedBreakoutScanner,
    SqueezeVolumeScanner,
    TechnicalScreenConfig,
    TrendContinuationScanner,
)
from tests.test_volume_spike import context, frame


def technical(**overrides: object) -> TechnicalMarketContext:
    values: dict[str, object] = {
        "close": 10.0,
        "bb_width_percentile": 10.0,
        "rsi": 50.0,
        "adx": 15.0,
        "atr": 0.5,
        "ema21": 10.2,
        "ema55": 9.8,
        "pierced_down": False,
        "pierced_up": False,
        "stacked_direction": None,
        "squeeze_bars": 3,
        "structure_tone": "warning",
        "trend_tone": "warning",
        "setup_name": "Sıkışma / karar bölgesi",
        "setup_direction": "neutral",
        "strong_divergences": 0,
        "near_confluence": False,
    }
    values.update(overrides)
    return TechnicalMarketContext(**values)  # type: ignore[arg-type]


def feature_values(
    technical_context: TechnicalMarketContext,
    *,
    relative_volume: float = 2.0,
    average_turnover: float = 30_000_000.0,
) -> dict[str, object]:
    return {
        TECHNICAL_MARKET_CONTEXT.feature_id: technical_context,
        RELATIVE_VOLUME_20.feature_id: VolumeActivity(
            observed_volume=200.0,
            baseline_volume=100.0,
            relative_volume=relative_volume,
            average_turnover=average_turnover,
            close=10.0,
            baseline_bar_count=20,
        ),
    }


class TechnicalMarketScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ScannerEngine()

    def run_scanner(
        self,
        scanner,
        technical_context: TechnicalMarketContext,
        *,
        relative_volume: float = 2.0,
        average_turnover: float = 30_000_000.0,
    ):
        source = frame()
        return self.engine.run(
            cycle_id="cycle-technical",
            frame=source,
            scanner=scanner,
            context=context(
                source,
                feature_values(
                    technical_context,
                    relative_volume=relative_volume,
                    average_turnover=average_turnover,
                ),
            ),
        )

    def test_squeeze_volume_is_a_neutral_state(self) -> None:
        run = self.run_scanner(SqueezeVolumeScanner(), technical())
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.findings[0].kind, ResultKind.STATE)
        self.assertEqual(run.findings[0].direction, Direction.NEUTRAL)

    def test_extreme_rsi_assigns_reversal_direction(self) -> None:
        bullish = self.run_scanner(ExtremeRsiScanner(), technical(rsi=20.0))
        bearish = self.run_scanner(ExtremeRsiScanner(), technical(rsi=80.0))
        self.assertEqual(bullish.findings[0].direction, Direction.BULLISH)
        self.assertEqual(bearish.findings[0].direction, Direction.BEARISH)

    def test_failed_breakout_is_an_event(self) -> None:
        run = self.run_scanner(
            FailedBreakoutScanner(),
            technical(
                pierced_down=True,
                setup_name="Aşağı kırılım reddedilmesi",
                setup_direction="bullish",
            ),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.findings[0].kind, ResultKind.EVENT)
        self.assertIsNone(run.findings[0].valid_from)

    def test_decision_zone_matches_only_named_setup(self) -> None:
        matching = self.run_scanner(DecisionZoneScanner(), technical())
        other = self.run_scanner(DecisionZoneScanner(), technical(setup_name="İzle"))
        self.assertEqual(matching.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(other.evaluation.status, EvaluationStatus.NO_MATCH)

    def test_trend_continuation_requires_directional_context(self) -> None:
        run = self.run_scanner(
            TrendContinuationScanner(),
            technical(
                adx=30.0,
                stacked_direction="bullish",
                setup_name="Trend devamı",
                setup_direction="bullish",
            ),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.findings[0].direction, Direction.BULLISH)

    def test_exhaustion_uses_divergence_setup_direction(self) -> None:
        run = self.run_scanner(
            ExhaustionScanner(),
            technical(
                rsi=75.0,
                pierced_up=True,
                setup_name="Tükenme denemesi",
                setup_direction="bearish",
                strong_divergences=2,
            ),
        )
        self.assertEqual(run.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(run.findings[0].direction, Direction.BEARISH)

    def test_all_screens_apply_the_shared_liquidity_prefilter(self) -> None:
        scanner = SqueezeVolumeScanner(
            TechnicalScreenConfig(minimum_average_turnover=20_000_000.0)
        )
        run = self.run_scanner(scanner, technical(), average_turnover=1_000_000.0)
        self.assertEqual(run.evaluation.status, EvaluationStatus.NO_MATCH)


if __name__ == "__main__":
    unittest.main()
