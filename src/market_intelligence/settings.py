from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from market_intelligence.delivery.telegram.config import TelegramSettings


def read_env_file(path: Path) -> dict[str, str]:
    """Read a small KEY=VALUE env file without mutating process environment."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number} geçersiz KEY=VALUE satırı")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"{path}:{line_number} boş ayar anahtarı")
        values[key] = value.strip().strip('"').strip("'")
    return values


def merged_environment(
    process_values: Mapping[str, str],
    env_file: Path | None = None,
) -> dict[str, str]:
    values = read_env_file(env_file) if env_file is not None else {}
    values.update(process_values)
    return values


@dataclass(frozen=True)
class RuntimeSettings:
    app_env: str
    timezone: ZoneInfo
    database_url: str = field(repr=False)
    enable_shadow_parity: bool = False
    artifact_root: Path = Path("runtime_artifacts")
    financial_archive_root: Path = Path("data/financial_archive")

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> RuntimeSettings:
        app_env = values.get("APP_ENV", "development").strip() or "development"
        timezone_name = values.get("APP_TIMEZONE", "Europe/Istanbul").strip()
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"APP_TIMEZONE bulunamadı: {timezone_name}") from exc
        database_url = values.get("DATABASE_URL", "").strip()
        if not database_url:
            raise ValueError("DATABASE_URL eksik")
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL PostgreSQL adresi olmalıdır")
        shadow_raw = values.get("ENABLE_SHADOW_PARITY", "false").strip().casefold()
        if shadow_raw not in {"true", "false"}:
            raise ValueError("ENABLE_SHADOW_PARITY true veya false olmalıdır")
        artifact_root = Path(
            values.get("BORSAPP_ARTIFACT_ROOT", "runtime_artifacts").strip()
            or "runtime_artifacts"
        )
        return cls(
            app_env=app_env,
            timezone=timezone,
            database_url=database_url,
            enable_shadow_parity=shadow_raw == "true",
            artifact_root=artifact_root,
            financial_archive_root=Path(values.get("BORSAPP_FINANCIAL_ARCHIVE", "data/financial_archive")),
        )


@dataclass(frozen=True)
class ApplicationSettings:
    runtime: RuntimeSettings
    telegram: TelegramSettings

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> ApplicationSettings:
        return cls(
            runtime=RuntimeSettings.from_mapping(values),
            telegram=TelegramSettings.from_mapping(values),
        )
