from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from market_intelligence.persistence.postgres.migrations import migration_status


class DoctorConnection(Protocol):
    def cursor(self) -> Any: ...


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def healthy(self) -> bool:
        return all(check.status != "FAIL" for check in self.checks)


def inspect_runtime(
    connection: DoctorConnection,
    *,
    migrations_directory: Path,
    now: datetime,
    maximum_cycle_age: timedelta,
    strict_runtime: bool = False,
) -> DoctorReport:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("doctor saati timezone-aware olmalıdır")
    checks: list[DoctorCheck] = []
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
    checks.append(
        DoctorCheck(
            "database",
            "OK" if row and row[0] == 1 else "FAIL",
            "PostgreSQL bağlantısı hazır" if row and row[0] == 1 else "SELECT 1 başarısız",
        )
    )

    migrations = migration_status(connection, migrations_directory)
    checks.append(
        DoctorCheck(
            "migrations",
            "OK" if not migrations.pending else "FAIL",
            "güncel"
            if not migrations.pending
            else "bekleyen: " + ", ".join(migrations.pending),
        )
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM universe_memberships
            WHERE universe_id = 'BIST_ALL'
              AND valid_from <= %s
              AND (valid_to IS NULL OR valid_to >= %s)
            """,
            (now.date(), now.date()),
        )
        universe_count = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT max(finished_at)
            FROM scan_cycles
            WHERE status IN ('completed', 'completed_with_errors')
            """
        )
        last_cycle = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT
                count(*) FILTER (WHERE status = 'pending'),
                count(*) FILTER (WHERE status = 'failed')
            FROM telegram_outbox
            """
        )
        pending_outbox, failed_outbox = (int(value) for value in cursor.fetchone())

    empty_status = "FAIL" if strict_runtime else "WARN"
    checks.append(
        DoctorCheck(
            "universe",
            "OK" if universe_count else empty_status,
            f"BIST_ALL aktif üye: {universe_count}",
        )
    )
    if last_cycle is None:
        cycle_status = "FAIL" if strict_runtime else "WARN"
        cycle_detail = "tamamlanmış tarama döngüsü yok"
    else:
        stale = now.astimezone(last_cycle.tzinfo) - last_cycle > maximum_cycle_age
        cycle_status = ("FAIL" if strict_runtime else "WARN") if stale else "OK"
        cycle_detail = f"son tamamlanan: {last_cycle.isoformat()}"
    checks.append(DoctorCheck("scan-cycle", cycle_status, cycle_detail))
    checks.append(
        DoctorCheck(
            "outbox",
            "WARN" if failed_outbox else "OK",
            f"bekleyen={pending_outbox}, hatalı={failed_outbox}",
        )
    )
    return DoctorReport(tuple(checks))
