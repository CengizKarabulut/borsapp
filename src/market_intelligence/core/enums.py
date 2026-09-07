from __future__ import annotations

from enum import StrEnum


class ResultKind(StrEnum):
    EVENT = "event"
    STATE = "state"


class EvaluationStatus(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    UNKNOWN = "unknown"


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class StateStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"
    HALTED = "halted"


class TransitionType(StrEnum):
    ENTER = "enter"
    CHANGE = "change"
    EXIT = "exit"
    UNKNOWN = "unknown"
    RESUMED = "resumed"
    EXIT_INFERRED = "exit_inferred"
    SUPERSEDED = "superseded"
    ADOPTED = "adopted"
    ABANDONED = "abandoned"
    INSTRUMENT_HALTED = "instrument_halted"


class TransitionReason(StrEnum):
    MARKET = "market"
    CONFIG_CHANGE = "config_change"
    ENGINE_UPGRADE = "engine_upgrade"
    DATA_CORRECTION = "data_correction"
    TIMEOUT = "timeout"
    MANUAL = "manual"
    BACKFILL = "backfill"
    SUPERSEDED = "superseded"
    INSTRUMENT_HALTED = "instrument_halted"


class PriceBasis(StrEnum):
    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    TOTAL_RETURN_ADJUSTED = "total_return_adjusted"
