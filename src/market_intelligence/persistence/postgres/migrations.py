from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{3,})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationChecksumError(RuntimeError):
    pass


class MigrationConnection(Protocol):
    def cursor(self) -> Any: ...

    def transaction(self) -> Any: ...


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    checksum: str


@dataclass(frozen=True)
class MigrationResult:
    applied: tuple[str, ...]
    skipped: tuple[str, ...]
    pending: tuple[str, ...] = ()


def discover(directory: Path) -> tuple[Migration, ...]:
    if not directory.is_dir():
        raise ValueError(f"Migration dizini bulunamadı: {directory}")
    migrations: list[Migration] = []
    versions: set[str] = set()
    for path in directory.glob("*.sql"):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Geçersiz migration dosya adı: {path.name}")
        version = match.group("version")
        if version in versions:
            raise ValueError(f"Tekrarlanan migration sürümü: {version}")
        versions.add(version)
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return tuple(sorted(migrations, key=lambda item: int(item.version)))


def _migration_table_exists(connection: MigrationConnection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.schema_migrations')")
        row = cursor.fetchone()
    return bool(row and row[0])


def _applied(connection: MigrationConnection) -> dict[str, str]:
    if not _migration_table_exists(connection):
        return {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT version, checksum FROM schema_migrations ORDER BY version")
        rows = cursor.fetchall()
    return {str(version): str(checksum) for version, checksum in rows}


def apply_migrations(
    connection: MigrationConnection,
    directory: Path,
    *,
    dry_run: bool = False,
    baseline: str | None = None,
) -> MigrationResult:
    migrations = discover(directory)
    applied_versions = _applied(connection)
    for migration in migrations:
        recorded = applied_versions.get(migration.version)
        # SQL execution below uses read_text's universal newline conversion.
        # Accept only the LF/CRLF encodings of that same text; never change stored checksums.
        raw = migration.path.read_bytes()
        normalized = raw.replace(b"\r\n", b"\n")
        equivalent = {
            migration.checksum,
            hashlib.sha256(normalized).hexdigest(),
            hashlib.sha256(normalized.replace(b"\n", b"\r\n")).hexdigest(),
        }
        if recorded is not None and recorded not in equivalent:
            raise MigrationChecksumError(f"Uygulanmış migration değişmiş: {migration.path.name}")

    pending = tuple(
        migration for migration in migrations if migration.version not in applied_versions
    )
    if dry_run:
        return MigrationResult(
            (),
            tuple(m.version for m in migrations if m.version in applied_versions),
            tuple(m.version for m in pending),
        )

    if baseline is not None:
        eligible = [m for m in pending if int(m.version) <= int(baseline)]
        if not eligible or baseline not in {m.version for m in migrations}:
            raise ValueError(f"Baseline migration bulunamadı veya zaten uygulanmış: {baseline}")
        bootstrap = migrations[0]
        if bootstrap.version not in applied_versions:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(bootstrap.path.read_text(encoding="utf-8"))
        with connection.transaction():
            with connection.cursor() as cursor:
                for migration in eligible:
                    cursor.execute(
                        """
                        INSERT INTO schema_migrations (version, name, checksum, duration_ms)
                        VALUES (%s, %s, %s, 0)
                        ON CONFLICT (version) DO NOTHING
                        """,
                        (migration.version, migration.name, migration.checksum),
                    )
        applied_versions.update({m.version: m.checksum for m in eligible})
        pending = tuple(m for m in pending if m.version not in applied_versions)

    newly_applied: list[str] = []
    for migration in pending:
        started = time.monotonic()
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(migration.path.read_text(encoding="utf-8"))
                duration_ms = max(0, round((time.monotonic() - started) * 1000))
                cursor.execute(
                    """
                    INSERT INTO schema_migrations (version, name, checksum, duration_ms)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum, duration_ms),
                )
        newly_applied.append(migration.version)
        applied_versions[migration.version] = migration.checksum
    return MigrationResult(
        tuple(newly_applied),
        tuple(m.version for m in migrations if m.version not in newly_applied),
    )


def migration_status(
    connection: MigrationConnection,
    directory: Path,
) -> MigrationResult:
    return apply_migrations(connection, directory, dry_run=True)
