from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from market_intelligence.core.enums import Direction, EvaluationStatus, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.specs import FeatureSpec


@dataclass(frozen=True)
class InstrumentRef:
    instrument_id: str
    symbol: str
    market: str
    asset_class: str
    valid_from: date
    valid_to: date | None = None
    provider_symbols: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FrameIdentity:
    instrument_id: str
    timeframe: Timeframe
    through_bar_time: datetime
    series_revision: int
    price_basis: str
    source: str
    snapshot_id: str
    is_partial: bool = False
    quality: str = "complete"


@dataclass(frozen=True)
class ScanContext:
    evaluation_time: datetime
    bar_close_time: datetime
    market_session_id: str
    calendar_version: str
    ruleset_hash: str
    feature_values: Mapping[str, Any] = field(default_factory=dict)
    declared_dependencies: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    finding_key: str
    instrument_id: str
    symbol_at_event: str
    timeframe: Timeframe
    scanner_id: str
    scanner_version: str
    ruleset_hash: str
    kind: ResultKind
    bar_time: datetime
    direction: Direction
    state_key: str | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    valid_from: datetime | None = None
    valid_until: datetime | None = None


@dataclass(frozen=True)
class ScanEvaluation:
    cycle_id: str
    instrument_id: str
    symbol_at_evaluation: str
    timeframe: Timeframe
    scanner_id: str
    scanner_version: str
    ruleset_hash: str
    bar_time: datetime
    status: EvaluationStatus
    finding_count: int
    snapshot_id: str
    error_code: str | None = None
    error_detail: str | None = None


class Scanner(Protocol):
    id: str
    family: str
    version: str
    result_kind: ResultKind
    supported_timeframes: set[Timeframe]
    required_features: Sequence[FeatureSpec]
    accepts_partial_bars: bool

    def prefilter(self, frame: Any, context: ScanContext) -> bool:
        """Cheap candidate selection without I/O or delivery side effects."""
        ...

    def evaluate(self, frame: Any, context: ScanContext) -> Sequence[Finding]:
        """Return zero or more findings from an immutable prepared input."""
        ...
