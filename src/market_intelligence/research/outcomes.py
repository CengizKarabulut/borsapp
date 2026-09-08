from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from market_intelligence.core.enums import Direction, PriceBasis
from market_intelligence.market_data.bars import CanonicalFrame


@dataclass(frozen=True)
class OutcomeWindow:
    horizon_bars: int
    price_basis: PriceBasis
    methodology_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.horizon_bars < 1:
            raise ValueError("Outcome ufku en az bir bar olmalıdır")


@dataclass(frozen=True)
class Outcome:
    event_id: str
    horizon_bars: int
    raw_return: float | None
    benchmark_return: float | None
    excess_return: float | None
    max_favorable_excursion: float | None
    max_adverse_excursion: float | None
    price_basis: PriceBasis
    methodology_version: str

    @property
    def complete(self) -> bool:
        return self.raw_return is not None


def _directional_return(entry: float, price: float, direction: Direction) -> float:
    change = price / entry - 1.0
    return -change if direction is Direction.BEARISH else change


def _window(
    frame: CanonicalFrame,
    event_bar_time: datetime,
    horizon_bars: int,
) -> tuple[object, tuple[object, ...]] | None:
    positions = [
        index for index, bar in enumerate(frame.bars) if bar.close_time == event_bar_time
    ]
    if len(positions) != 1:
        return None
    event_position = positions[0]
    end = event_position + horizon_bars
    if end >= len(frame.bars):
        return None
    return frame.bars[event_position], frame.bars[event_position + 1 : end + 1]


def measure(
    *,
    event_id: str,
    event_bar_time: datetime,
    direction: Direction,
    frame: CanonicalFrame,
    benchmark: CanonicalFrame | None,
    window: OutcomeWindow,
) -> Outcome:
    """Measure a closed-bar forward window without treating missing data as zero."""
    if frame.price_basis is not window.price_basis:
        raise ValueError("Outcome price_basis ile canonical frame uyuşmuyor")
    observed = _window(frame, event_bar_time, window.horizon_bars)
    if observed is None:
        return Outcome(
            event_id,
            window.horizon_bars,
            None,
            None,
            None,
            None,
            None,
            window.price_basis,
            window.methodology_version,
        )
    event_bar, forward = observed
    entry = event_bar.close
    raw = _directional_return(entry, forward[-1].close, direction)
    excursions: list[float] = []
    for bar in forward:
        excursions.extend(
            (
                _directional_return(entry, bar.high, direction),
                _directional_return(entry, bar.low, direction),
            )
        )
    favorable = max(excursions)
    adverse = min(excursions)

    benchmark_return: float | None = None
    if benchmark is not None:
        benchmark_window = _window(benchmark, event_bar_time, window.horizon_bars)
        if benchmark_window is not None:
            benchmark_event, benchmark_forward = benchmark_window
            benchmark_return = _directional_return(
                benchmark_event.close,
                benchmark_forward[-1].close,
                direction,
            )
    return Outcome(
        event_id=event_id,
        horizon_bars=window.horizon_bars,
        raw_return=raw,
        benchmark_return=benchmark_return,
        excess_return=raw - benchmark_return if benchmark_return is not None else None,
        max_favorable_excursion=favorable,
        max_adverse_excursion=adverse,
        price_basis=window.price_basis,
        methodology_version=window.methodology_version,
    )
