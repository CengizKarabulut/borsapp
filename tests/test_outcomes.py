from __future__ import annotations

import unittest
from dataclasses import replace

from market_intelligence.core.enums import Direction, PriceBasis
from market_intelligence.research.outcomes import OutcomeWindow, measure
from tests.test_volume_spike import frame


class OutcomeTests(unittest.TestCase):
    def test_bearish_direction_reverses_return_and_excursions(self) -> None:
        source = frame()
        event_time = source.bars[-3].close_time
        outcome = measure(
            event_id="event-1",
            event_bar_time=event_time,
            direction=Direction.BEARISH,
            frame=source,
            benchmark=None,
            window=OutcomeWindow(2, PriceBasis.SPLIT_ADJUSTED),
        )
        self.assertAlmostEqual(outcome.raw_return or 0.0, 0.0)
        self.assertAlmostEqual(outcome.max_favorable_excursion or 0.0, 0.05)
        self.assertAlmostEqual(outcome.max_adverse_excursion or 0.0, -0.05)

    def test_incomplete_horizon_is_none_not_zero(self) -> None:
        source = frame()
        outcome = measure(
            event_id="event-2",
            event_bar_time=source.through_bar_time,
            direction=Direction.BULLISH,
            frame=source,
            benchmark=None,
            window=OutcomeWindow(5, PriceBasis.SPLIT_ADJUSTED),
        )
        self.assertFalse(outcome.complete)
        self.assertIsNone(outcome.raw_return)
        self.assertIsNone(outcome.max_favorable_excursion)

    def test_benchmark_produces_excess_return(self) -> None:
        source = frame()
        benchmark_bars = tuple(
            replace(bar, close=bar.close * 1.01, high=bar.high * 1.01, low=bar.low * 1.01, open=bar.open * 1.01)
            for bar in source.bars
        )
        benchmark = replace(
            source,
            instrument_id="xu100",
            symbol_at_snapshot="XU100",
            snapshot_id="benchmark",
            bars=benchmark_bars,
        )
        event_time = source.bars[-3].close_time
        outcome = measure(
            event_id="event-3",
            event_bar_time=event_time,
            direction=Direction.BULLISH,
            frame=source,
            benchmark=benchmark,
            window=OutcomeWindow(2, PriceBasis.SPLIT_ADJUSTED),
        )
        self.assertIsNotNone(outcome.excess_return)
        self.assertAlmostEqual(outcome.excess_return or 0.0, 0.0)

    def test_price_basis_mismatch_fails_closed(self) -> None:
        source = frame()
        with self.assertRaisesRegex(ValueError, "price_basis"):
            measure(
                event_id="event-4",
                event_bar_time=source.bars[-2].close_time,
                direction=Direction.BULLISH,
                frame=source,
                benchmark=None,
                window=OutcomeWindow(1, PriceBasis.RAW),
            )


if __name__ == "__main__":
    unittest.main()
