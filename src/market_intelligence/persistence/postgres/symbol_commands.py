from __future__ import annotations

from typing import Any

from market_intelligence.application.symbol_commands import (
    StoredArtifact,
    StoredCycle,
    StoredMatch,
    StoredNews,
    StoredScannerResult,
    SymbolSnapshot,
)
from market_intelligence.core.enums import Direction, EvaluationStatus
from market_intelligence.delivery.telegram.commands import CommandName
from market_intelligence.persistence.postgres.scan_store import PostgresConnection

INSTRUMENT_SQL = """
SELECT i.instrument_id, s.symbol
FROM instrument_symbols s
JOIN instruments i ON i.instrument_id = s.instrument_id
WHERE upper(s.symbol) = upper(%s)
  AND s.valid_from <= CURRENT_DATE
  AND (s.valid_to IS NULL OR s.valid_to >= CURRENT_DATE)
  AND i.valid_from <= CURRENT_DATE
  AND (i.valid_to IS NULL OR i.valid_to >= CURRENT_DATE)
ORDER BY CASE WHEN s.provider = 'canonical' THEN 0 ELSE 1 END, s.valid_from DESC
LIMIT 1
"""

RESULTS_SQL = """
SELECT DISTINCT ON (e.scanner_id, e.timeframe)
    e.scanner_id,
    split_part(e.scanner_id, '.', 1) AS family,
    e.timeframe,
    e.bar_time,
    e.status,
    latest_event.direction
FROM scan_evaluations e
LEFT JOIN LATERAL (
    SELECT direction
    FROM scan_events event
    WHERE event.evaluation_id = e.evaluation_id
    ORDER BY event.bar_time DESC
    LIMIT 1
) latest_event ON TRUE
WHERE e.instrument_id = %s
ORDER BY e.scanner_id, e.timeframe, e.bar_time DESC, e.evaluated_at DESC
"""

ARTIFACTS_SQL = """
SELECT artifact_kind, summary, storage_uri, created_at
FROM research_artifacts
WHERE instrument_id = %s
ORDER BY created_at DESC
LIMIT 20
"""

NEWS_SQL = """
SELECT DISTINCT n.headline, n.published_at, n.url, n.source,
       COALESCE(n.payload->>'summary', '') AS summary
FROM news_items n
LEFT JOIN news_item_instruments link ON link.news_id = n.news_id
WHERE n.instrument_id = %s OR link.instrument_id = %s
ORDER BY n.published_at DESC
"""

RECENT_MATCHES_SQL = """
SELECT symbol_at_event, scanner_id, timeframe, bar_time, direction
FROM scan_events
ORDER BY bar_time DESC, symbol_at_event, scanner_id
LIMIT %s
"""

RECENT_CYCLES_SQL = """
SELECT c.timeframe, c.bar_time, c.status,
       c.successful_instruments, c.failed_instruments,
       count(*) FILTER (WHERE e.status = 'match') AS matches
FROM scan_cycles c
LEFT JOIN scan_evaluations e ON e.cycle_id = c.cycle_id
GROUP BY c.cycle_id
ORDER BY c.started_at DESC
LIMIT %s
"""

ENQUEUE_SQL = """
INSERT INTO command_jobs (
    command_name, instrument_id, symbol_at_request, requested_by, requested_topic
)
SELECT %s, i.instrument_id, %s, %s, %s
FROM instruments i
JOIN instrument_symbols s ON s.instrument_id = i.instrument_id
WHERE upper(s.symbol) = upper(%s)
  AND s.valid_from <= CURRENT_DATE
  AND (s.valid_to IS NULL OR s.valid_to >= CURRENT_DATE)
ORDER BY s.valid_from DESC
LIMIT 1
RETURNING job_id
"""


class PostgresSymbolReadStore:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def load_symbol(self, symbol: str) -> SymbolSnapshot | None:
        with self.connection.cursor() as cursor:
            cursor.execute(INSTRUMENT_SQL, (symbol,))
            instrument = cursor.fetchone()
            if not instrument:
                return None
            instrument_id, canonical_symbol = str(instrument[0]), str(instrument[1]).upper()
            cursor.execute(RESULTS_SQL, (instrument_id,))
            results = tuple(self._result(row) for row in cursor.fetchall())
            cursor.execute(ARTIFACTS_SQL, (instrument_id,))
            artifacts = tuple(
                StoredArtifact(str(row[0]), str(row[1]), row[2], row[3])
                for row in cursor.fetchall()
            )
            cursor.execute(NEWS_SQL, (instrument_id, instrument_id))
            news = tuple(
                StoredNews(str(row[0]), row[1], row[2], str(row[3]), str(row[4] or ""))
                for row in cursor.fetchall()
            )
        return SymbolSnapshot(instrument_id, canonical_symbol, results, artifacts, news)

    def load_recent_matches(self, *, limit: int = 60) -> tuple[StoredMatch, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(RECENT_MATCHES_SQL, (limit,))
            rows = cursor.fetchall()
        return tuple(
            StoredMatch(
                symbol=str(row[0]).upper(),
                scanner_id=str(row[1]),
                timeframe=str(row[2]),
                bar_time=row[3],
                direction=Direction(str(row[4])),
            )
            for row in rows
        )

    def load_recent_cycles(self, *, limit: int = 10) -> tuple[StoredCycle, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(RECENT_CYCLES_SQL, (limit,))
            rows = cursor.fetchall()
        return tuple(
            StoredCycle(
                timeframe=str(row[0]),
                bar_time=row[1],
                status=str(row[2]),
                successful=int(row[3]),
                failed=int(row[4]),
                matches=int(row[5]),
            )
            for row in rows
        )

    @staticmethod
    def _result(row: tuple[Any, ...]) -> StoredScannerResult:
        direction = Direction(str(row[5])) if row[5] is not None else None
        return StoredScannerResult(
            scanner_id=str(row[0]),
            family=str(row[1]),
            timeframe=str(row[2]),
            bar_time=row[3],
            status=EvaluationStatus(str(row[4])),
            direction=direction,
        )


class PostgresLongJobQueue:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def enqueue(
        self,
        *,
        command: CommandName,
        symbol: str,
        requested_by: int,
        requested_topic: int,
    ) -> str:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    ENQUEUE_SQL,
                    (
                        command.value,
                        symbol,
                        requested_by,
                        requested_topic,
                        symbol,
                    ),
                )
                row = cursor.fetchone()
        if not row:
            raise ValueError(f"Aktif enstrüman bulunamadı: {symbol}")
        return str(row[0])
