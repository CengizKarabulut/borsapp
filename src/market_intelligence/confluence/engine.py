from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from market_intelligence.core.enums import Direction, EvaluationStatus
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scanning.contracts import Finding


class ConfluenceMode(StrEnum):
    STRICT = "strict"
    RECENT_N = "recent_n"
    CROSS_TIMEFRAME = "cross_timeframe"


@dataclass(frozen=True)
class ConfluencePolicy:
    mode: ConfluenceMode
    minimum_families: int = 2
    recent_bars: int = 3
    cross_timeframe_max_age_bars: int = 1

    def __post_init__(self) -> None:
        if self.minimum_families < 2:
            raise ValueError("Confluence en az iki aile gerektirir")
        if self.recent_bars < 1 or self.cross_timeframe_max_age_bars < 0:
            raise ValueError("Confluence bar penceresi geçersiz")


@dataclass(frozen=True)
class FindingObservation:
    finding: Finding
    bar_age: int

    def __post_init__(self) -> None:
        if self.bar_age < 0:
            raise ValueError("bar_age negatif olamaz")

    @property
    def family(self) -> str:
        return self.finding.scanner_id.split(".", 1)[0]


@dataclass(frozen=True)
class ConfluenceReport:
    instrument_id: str
    symbol: str
    mode: ConfluenceMode
    reference_time: datetime
    reference_timeframe: Timeframe | None
    families: tuple[str, ...]
    scanner_ids: tuple[str, ...]
    directions: tuple[Direction, ...]
    direction_conflict: bool
    unknown_families: tuple[str, ...]
    no_match_families: tuple[str, ...]
    qualifies: bool


class ConfluenceEngine:
    def evaluate(
        self,
        *,
        instrument_id: str,
        symbol: str,
        reference_time: datetime,
        reference_timeframe: Timeframe | None,
        observations: tuple[FindingObservation, ...],
        coverage: dict[str, EvaluationStatus],
        policy: ConfluencePolicy,
    ) -> ConfluenceReport:
        usable = tuple(
            observation
            for observation in observations
            if observation.finding.instrument_id == instrument_id
            and self._inside_window(
                observation,
                reference_time=reference_time,
                reference_timeframe=reference_timeframe,
                policy=policy,
            )
        )
        # One scanner may produce multiple states. Family coverage, not finding
        # count, determines confluence.
        families = tuple(sorted({observation.family for observation in usable}))
        scanner_ids = tuple(
            sorted({observation.finding.scanner_id for observation in usable})
        )
        directions = tuple(
            sorted(
                {
                    observation.finding.direction
                    for observation in usable
                    if observation.finding.direction is not Direction.NEUTRAL
                },
                key=lambda value: value.value,
            )
        )
        direction_conflict = (
            Direction.BULLISH in directions and Direction.BEARISH in directions
        ) or Direction.MIXED in directions
        unknown = tuple(
            sorted(
                family
                for family, status in coverage.items()
                if status is EvaluationStatus.UNKNOWN
            )
        )
        no_match = tuple(
            sorted(
                family
                for family, status in coverage.items()
                if status is EvaluationStatus.NO_MATCH
            )
        )
        return ConfluenceReport(
            instrument_id=instrument_id,
            symbol=symbol,
            mode=policy.mode,
            reference_time=reference_time,
            reference_timeframe=reference_timeframe,
            families=families,
            scanner_ids=scanner_ids,
            directions=directions,
            direction_conflict=direction_conflict,
            unknown_families=unknown,
            no_match_families=no_match,
            qualifies=len(families) >= policy.minimum_families,
        )

    @staticmethod
    def _inside_window(
        observation: FindingObservation,
        *,
        reference_time: datetime,
        reference_timeframe: Timeframe | None,
        policy: ConfluencePolicy,
    ) -> bool:
        finding = observation.finding
        if policy.mode is ConfluenceMode.STRICT:
            return (
                reference_timeframe is not None
                and finding.timeframe is reference_timeframe
                and finding.bar_time == reference_time
                and observation.bar_age == 0
            )
        if policy.mode is ConfluenceMode.RECENT_N:
            return (
                reference_timeframe is not None
                and finding.timeframe is reference_timeframe
                and observation.bar_age < policy.recent_bars
            )
        return observation.bar_age <= policy.cross_timeframe_max_age_bars
