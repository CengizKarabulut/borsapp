from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

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


@dataclass(frozen=True)
class RuntimeInstrument:
    instrument_id: str
    symbol: str
    provider_symbol: str
    market: str
    asset_class: str


class PostgresRuntimeRepository:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def resolve_instrument(
        self,
        symbol: str,
        *,
        provider: str = "borsapy",
        as_of: date | None = None,
    ) -> RuntimeInstrument | None:
        effective_date = as_of or date.today()
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
        valid_from: date | None = None,
    ) -> RuntimeInstrument:
        effective_date = valid_from or date.today()
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
    ) -> None:
        status = "completed" if failed == 0 else "completed_with_errors"
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    FINISH_CYCLE_SQL,
                    (status, successful, stale, failed, finished_at, cycle_id),
                )
