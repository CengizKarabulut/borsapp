from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from market_intelligence.market_data.universe import UniverseSyncPlan
from market_intelligence.persistence.postgres.scan_store import PostgresConnection

FIND_INSTRUMENT_SQL = """
SELECT i.instrument_id, upper(s.symbol), i.market, i.asset_class
FROM instrument_symbols s
JOIN instruments i ON i.instrument_id = s.instrument_id
WHERE s.provider = %s AND upper(s.symbol) = upper(%s)
  AND s.valid_from <= %s
  AND (s.valid_to IS NULL OR s.valid_to >= %s)
  AND i.valid_from <= %s
  AND (i.valid_to IS NULL OR i.valid_to >= %s)
ORDER BY s.valid_from DESC
LIMIT 1
"""

INSERT_INSTRUMENT_SQL = """
INSERT INTO instruments (asset_class, market, name, valid_from)
VALUES (%s, %s, %s, %s)
RETURNING instrument_id
"""

INSERT_SYMBOL_SQL = """
INSERT INTO instrument_symbols (instrument_id, provider, symbol, valid_from)
VALUES (%s, %s, %s, %s)
ON CONFLICT (instrument_id, provider, symbol, valid_from) DO NOTHING
"""

INSERT_UNIVERSE_SQL = """
INSERT INTO universe_memberships (instrument_id, universe_id, valid_from)
VALUES (%s, %s, %s)
ON CONFLICT (instrument_id, universe_id, valid_from) DO NOTHING
"""

FIND_ACTIVE_MEMBERSHIP_SQL = """
SELECT valid_from
FROM universe_memberships
WHERE instrument_id = %s AND universe_id = %s
  AND valid_from <= %s
  AND (valid_to IS NULL OR valid_to >= %s)
ORDER BY valid_from DESC
LIMIT 1
"""

UPDATE_INSTRUMENT_NAME_SQL = """
UPDATE instruments
SET name = %s
WHERE instrument_id = %s AND name IS DISTINCT FROM %s
"""

DELETE_SAME_DAY_MEMBERSHIP_SQL = """
DELETE FROM universe_memberships
WHERE instrument_id = %s AND universe_id = %s AND valid_from = %s
"""

CLOSE_MEMBERSHIP_SQL = """
UPDATE universe_memberships
SET valid_to = %s
WHERE instrument_id = %s AND universe_id = %s
  AND valid_from < %s
  AND (valid_to IS NULL OR valid_to >= %s)
"""

INSERT_UNIVERSE_SYNC_RUN_SQL = """
INSERT INTO universe_sync_runs (
    universe_id, source, effective_date, observed_count, current_count,
    addition_count, removal_count, unchanged_count, content_hash
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING sync_run_id
"""

START_CYCLE_SQL = """
INSERT INTO scan_cycles (
    market, universe_id, timeframe, bar_time, status,
    expected_instruments, started_at
) VALUES (%s, %s, %s, %s, 'running', %s, %s)
ON CONFLICT (market, universe_id, timeframe, bar_time)
DO UPDATE SET
    status = 'running',
    expected_instruments = EXCLUDED.expected_instruments,
    started_at = EXCLUDED.started_at,
    finished_at = NULL
RETURNING cycle_id
"""

FINISH_CYCLE_SQL = """
UPDATE scan_cycles
SET status = %s,
    successful_instruments = %s,
    stale_instruments = %s,
    failed_instruments = %s,
    finished_at = %s
WHERE cycle_id = %s
"""

LIST_UNIVERSE_SQL = """
SELECT
    i.instrument_id,
    upper(canonical.symbol),
    upper(provider_symbol.symbol),
    i.market,
    i.asset_class
FROM universe_memberships membership
JOIN instruments i ON i.instrument_id = membership.instrument_id
JOIN instrument_symbols canonical
  ON canonical.instrument_id = i.instrument_id AND canonical.provider = 'canonical'
JOIN instrument_symbols provider_symbol
  ON provider_symbol.instrument_id = i.instrument_id AND provider_symbol.provider = 'borsapy'
WHERE membership.universe_id = %s
  AND membership.valid_from <= %s
  AND (membership.valid_to IS NULL OR membership.valid_to >= %s)
  AND i.valid_from <= %s
  AND (i.valid_to IS NULL OR i.valid_to >= %s)
  AND canonical.valid_from <= %s
  AND (canonical.valid_to IS NULL OR canonical.valid_to >= %s)
  AND provider_symbol.valid_from <= %s
  AND (provider_symbol.valid_to IS NULL OR provider_symbol.valid_to >= %s)
ORDER BY canonical.symbol
"""

WATERMARKS_SQL = """
SELECT scanner_id, last_completed_bar_time
FROM scan_watermarks
WHERE market = %s AND universe_id = %s AND timeframe = %s
  AND scanner_id = ANY(%s)
"""

UPSERT_WATERMARK_SQL = """
INSERT INTO scan_watermarks (
    market, universe_id, scanner_id, timeframe, last_completed_bar_time
) VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (market, universe_id, scanner_id, timeframe)
DO UPDATE SET
    last_completed_bar_time = GREATEST(
        scan_watermarks.last_completed_bar_time,
        EXCLUDED.last_completed_bar_time
    ),
    updated_at = now()
"""

INSERT_CYCLE_FAILURE_SQL = """
INSERT INTO scan_cycle_failures (
    cycle_id, instrument_id, symbol_at_failure, error_code, error_detail
) VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (cycle_id, instrument_id)
DO UPDATE SET
    error_code = EXCLUDED.error_code,
    error_detail = EXCLUDED.error_detail,
    observed_at = now()
"""


@dataclass(frozen=True)
class RuntimeInstrument:
    instrument_id: str
    symbol: str
    provider_symbol: str
    market: str
    asset_class: str


@dataclass(frozen=True)
class InstrumentScanFailure:
    instrument_id: str
    symbol: str
    error_code: str
    error_detail: str


class PostgresRuntimeRepository:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def resolve_instrument(
        self,
        symbol: str,
        *,
        provider: str = "borsapy",
        as_of: date,
    ) -> RuntimeInstrument | None:
        effective_date = as_of
        with self.connection.cursor() as cursor:
            cursor.execute(
                FIND_INSTRUMENT_SQL,
                (
                    provider,
                    symbol,
                    effective_date,
                    effective_date,
                    effective_date,
                    effective_date,
                ),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return RuntimeInstrument(
            instrument_id=str(row[0]),
            symbol=str(row[1]),
            provider_symbol=symbol.upper(),
            market=str(row[2]),
            asset_class=str(row[3]),
        )

    def register_instrument(
        self,
        symbol: str,
        *,
        provider_symbol: str,
        market: str = "BIST",
        asset_class: str = "equity",
        universe_id: str = "BIST_ALL",
        valid_from: date,
    ) -> RuntimeInstrument:
        effective_date = valid_from
        existing = self.resolve_instrument(
            provider_symbol,
            provider="borsapy",
            as_of=effective_date,
        )
        if existing is not None:
            return existing
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    INSERT_INSTRUMENT_SQL,
                    (asset_class, market, symbol.upper(), effective_date),
                )
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError("instruments instrument_id döndürmedi")
                instrument_id = str(row[0])
                cursor.execute(
                    INSERT_SYMBOL_SQL,
                    (instrument_id, "canonical", symbol.upper(), effective_date),
                )
                cursor.execute(
                    INSERT_SYMBOL_SQL,
                    (instrument_id, "borsapy", provider_symbol.upper(), effective_date),
                )
                cursor.execute(
                    INSERT_UNIVERSE_SQL,
                    (instrument_id, universe_id, effective_date),
                )
        return RuntimeInstrument(
            instrument_id,
            symbol.upper(),
            provider_symbol.upper(),
            market,
            asset_class,
        )

    def apply_universe_sync(self, plan: UniverseSyncPlan) -> str:
        """Apply a previously validated point-in-time universe plan atomically."""

        list_params = (plan.universe_id,) + (plan.as_of,) * 8
        expected_current = (
            ({member.symbol for member in plan.members} - set(plan.additions))
            | set(plan.removals)
        )
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(LIST_UNIVERSE_SQL, list_params)
                current_rows = cursor.fetchall()
                current_by_symbol = {str(row[1]).upper(): str(row[0]) for row in current_rows}
                if set(current_by_symbol) != expected_current:
                    raise RuntimeError(
                        "Universe üyeliği önizlemeden sonra değişti; yeniden önizleyin"
                    )

                for member in plan.members:
                    cursor.execute(
                        FIND_INSTRUMENT_SQL,
                        (
                            "borsapy",
                            member.provider_symbol,
                            plan.as_of,
                            plan.as_of,
                            plan.as_of,
                            plan.as_of,
                        ),
                    )
                    row = cursor.fetchone()
                    if row:
                        instrument_id = str(row[0])
                    else:
                        cursor.execute(
                            INSERT_INSTRUMENT_SQL,
                            (
                                member.asset_class,
                                member.market,
                                member.name,
                                plan.as_of,
                            ),
                        )
                        inserted = cursor.fetchone()
                        if not inserted:
                            raise RuntimeError("instruments instrument_id döndürmedi")
                        instrument_id = str(inserted[0])
                        cursor.execute(
                            INSERT_SYMBOL_SQL,
                            (instrument_id, "canonical", member.symbol, plan.as_of),
                        )
                        cursor.execute(
                            INSERT_SYMBOL_SQL,
                            (
                                instrument_id,
                                "borsapy",
                                member.provider_symbol,
                                plan.as_of,
                            ),
                        )
                    cursor.execute(
                        UPDATE_INSTRUMENT_NAME_SQL,
                        (member.name, instrument_id, member.name),
                    )
                    cursor.execute(
                        FIND_ACTIVE_MEMBERSHIP_SQL,
                        (instrument_id, plan.universe_id, plan.as_of, plan.as_of),
                    )
                    if not cursor.fetchone():
                        cursor.execute(
                            INSERT_UNIVERSE_SQL,
                            (instrument_id, plan.universe_id, plan.as_of),
                        )

                previous_day = plan.as_of - timedelta(days=1)
                for symbol in plan.removals:
                    instrument_id = current_by_symbol[symbol]
                    cursor.execute(
                        DELETE_SAME_DAY_MEMBERSHIP_SQL,
                        (instrument_id, plan.universe_id, plan.as_of),
                    )
                    cursor.execute(
                        CLOSE_MEMBERSHIP_SQL,
                        (
                            previous_day,
                            instrument_id,
                            plan.universe_id,
                            plan.as_of,
                            plan.as_of,
                        ),
                    )

                cursor.execute(
                    INSERT_UNIVERSE_SYNC_RUN_SQL,
                    (
                        plan.universe_id,
                        plan.source,
                        plan.as_of,
                        plan.observed_count,
                        plan.current_count,
                        len(plan.additions),
                        len(plan.removals),
                        plan.unchanged_count,
                        plan.content_hash,
                    ),
                )
                sync_row = cursor.fetchone()
                if not sync_row:
                    raise RuntimeError("universe_sync_runs sync_run_id döndürmedi")
        return str(sync_row[0])

    def start_cycle(
        self,
        *,
        market: str,
        universe_id: str,
        timeframe: str,
        bar_time: datetime,
        expected_instruments: int,
        started_at: datetime,
    ) -> str:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    START_CYCLE_SQL,
                    (
                        market,
                        universe_id,
                        timeframe,
                        bar_time,
                        expected_instruments,
                        started_at,
                    ),
                )
                row = cursor.fetchone()
        if not row:
            raise RuntimeError("scan_cycles cycle_id döndürmedi")
        return str(row[0])

    def finish_cycle(
        self,
        *,
        cycle_id: str,
        successful: int,
        stale: int,
        failed: int,
        finished_at: datetime,
        failures: tuple[InstrumentScanFailure, ...] = (),
    ) -> None:
        if failed != len(failures) and failures:
            raise ValueError("failed sayısı ile failure kayıtları uyuşmuyor")
        status = "completed" if failed == 0 else "completed_with_errors"
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                for failure in failures:
                    cursor.execute(
                        INSERT_CYCLE_FAILURE_SQL,
                        (
                            cycle_id,
                            failure.instrument_id,
                            failure.symbol,
                            failure.error_code[:120],
                            failure.error_detail[:2000],
                        ),
                    )
                cursor.execute(
                    FINISH_CYCLE_SQL,
                    (status, successful, stale, failed, finished_at, cycle_id),
                )

    def list_universe(self, universe_id: str, *, as_of: date) -> tuple[RuntimeInstrument, ...]:
        params = (universe_id,) + (as_of,) * 8
        with self.connection.cursor() as cursor:
            cursor.execute(LIST_UNIVERSE_SQL, params)
            rows = cursor.fetchall()
        return tuple(
            RuntimeInstrument(
                instrument_id=str(row[0]),
                symbol=str(row[1]),
                provider_symbol=str(row[2]),
                market=str(row[3]),
                asset_class=str(row[4]),
            )
            for row in rows
        )

    def earliest_watermark(
        self,
        *,
        market: str,
        universe_id: str,
        scanner_ids: tuple[str, ...],
        timeframe: str,
    ) -> datetime | None:
        if not scanner_ids:
            return None
        with self.connection.cursor() as cursor:
            cursor.execute(
                WATERMARKS_SQL,
                (market, universe_id, timeframe, list(scanner_ids)),
            )
            rows = cursor.fetchall()
        if len(rows) != len(set(scanner_ids)):
            return None
        return min(row[1] for row in rows)

    def update_watermarks(
        self,
        *,
        market: str,
        universe_id: str,
        scanner_ids: tuple[str, ...],
        timeframe: str,
        bar_time: datetime,
    ) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                for scanner_id in scanner_ids:
                    cursor.execute(
                        UPSERT_WATERMARK_SQL,
                        (market, universe_id, scanner_id, timeframe, bar_time),
                    )
