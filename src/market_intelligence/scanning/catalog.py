from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from market_intelligence.core.identity import ruleset_hash
from market_intelligence.core.timeframes import Timeframe, parse_timeframe
from market_intelligence.scanning.contracts import Scanner
from market_intelligence.scanning.ma.near_zone import MaNearZoneConfig, MaNearZoneScanner
from market_intelligence.scanning.signal.macd_positive_cross import (
    MacdPositiveCrossConfig,
    MacdPositiveCrossScanner,
    MacdTriggerMode,
)
from market_intelligence.scanning.technical.volume_spike import (
    TechnicalVolumeSpikeScanner,
    VolumeSpikeConfig,
)


@dataclass(frozen=True)
class ScannerBinding:
    scanner: Scanner
    ruleset_hash: str
    shadow_timeframes: frozenset[Timeframe]
    notification_timeframes: frozenset[Timeframe]


def _timeframes(raw: Any, key: str) -> frozenset[Timeframe]:
    if not isinstance(raw, list):
        raise ValueError(f"{key} liste olmalıdır")
    return frozenset(parse_timeframe(str(value)) for value in raw)


def _section(document: dict[str, Any], scanner_id: str) -> dict[str, Any]:
    value: Any = document
    for part in scanner_id.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"Scanner ayarı bulunamadı: {scanner_id}")
        value = value[part]
    if not isinstance(value, dict):
        raise ValueError(f"Scanner ayarı tablo olmalıdır: {scanner_id}")
    return dict(value)


def _binding(
    scanner: Scanner,
    scanner_config: Any,
    section: dict[str, Any],
    *,
    calendar_version: str,
) -> ScannerBinding:
    configured_version = str(section.get("version", ""))
    if configured_version != scanner.version:
        raise ValueError(
            f"{scanner.id}: config version={configured_version}, code version={scanner.version}"
        )
    partial_policy = str(section.get("partial_bar_policy", "drop"))
    if partial_policy != "drop":
        raise ValueError(f"{scanner.id}: yalnız drop partial bar politikası destekleniyor")
    shadow = _timeframes(section.get("shadow_timeframes", []), "shadow_timeframes")
    notifications = _timeframes(
        section.get("notification_timeframes", []),
        "notification_timeframes",
    )
    if not notifications.issubset(shadow):
        raise ValueError(f"{scanner.id}: notification timeframe önce shadow olmalıdır")
    return ScannerBinding(
        scanner=scanner,
        ruleset_hash=ruleset_hash(
            scanner_id=scanner.id,
            scanner_version=scanner.version,
            resolved_config=asdict(scanner_config),
            feature_specs=scanner.required_features,
            partial_bar_policy=partial_policy,
            calendar_version=calendar_version,
        ),
        shadow_timeframes=shadow,
        notification_timeframes=notifications,
    )


def load_scanner_catalog(
    path: Path,
    *,
    calendar_version: str = "bist-session-v1",
) -> tuple[ScannerBinding, ...]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    bindings: list[ScannerBinding] = []

    volume_section = _section(document, TechnicalVolumeSpikeScanner.id)
    volume_config = VolumeSpikeConfig(
        relative_volume_threshold=float(volume_section["relative_volume_threshold"]),
        minimum_average_turnover=float(volume_section["minimum_average_turnover"]),
        minimum_price=float(volume_section["minimum_price"]),
    )
    if bool(volume_section.get("enabled", True)):
        bindings.append(
            _binding(
                TechnicalVolumeSpikeScanner(volume_config),
                volume_config,
                volume_section,
                calendar_version=calendar_version,
            )
        )

    macd_section = _section(document, MacdPositiveCrossScanner.id)
    macd_config = MacdPositiveCrossConfig(
        minimum_rsi=float(macd_section["minimum_rsi"]),
        require_positive_macd=bool(macd_section["require_positive_macd"]),
        trigger_mode=MacdTriggerMode(str(macd_section["trigger_mode"])),
    )
    if bool(macd_section.get("enabled", True)):
        bindings.append(
            _binding(
                MacdPositiveCrossScanner(macd_config),
                macd_config,
                macd_section,
                calendar_version=calendar_version,
            )
        )

    ma_section = _section(document, MaNearZoneScanner.id)
    ma_config = MaNearZoneConfig(
        maximum_distance_atr=float(ma_section["maximum_distance_atr"]),
        accepted_level_classes=tuple(str(v) for v in ma_section["accepted_level_classes"]),
        maximum_levels_per_side=int(ma_section["maximum_levels_per_side"]),
    )
    if bool(ma_section.get("enabled", True)):
        bindings.append(
            _binding(
                MaNearZoneScanner(ma_config),
                ma_config,
                ma_section,
                calendar_version=calendar_version,
            )
        )
    return tuple(bindings)
