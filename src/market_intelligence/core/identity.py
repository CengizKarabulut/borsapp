from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any


def _normalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(item) for item in value), key=repr)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("Ruleset kimliği sonlu olmayan float içeremez")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def ruleset_hash(
    *,
    scanner_id: str,
    scanner_version: str,
    resolved_config: Mapping[str, Any],
    feature_specs: Sequence[Any] = (),
    partial_bar_policy: str = "drop",
    calendar_version: str = "unversioned",
) -> str:
    return stable_hash(
        {
            "scanner_id": scanner_id,
            "scanner_version": scanner_version,
            "resolved_config": resolved_config,
            "feature_specs": feature_specs,
            "partial_bar_policy": partial_bar_policy,
            "calendar_version": calendar_version,
        }
    )
