from __future__ import annotations

from typing import Any

from market_intelligence.application.symbol_commands import (
    StoredArtifact,
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
SELECT headline, published_at, url
FROM news_items
WHERE instrument_id = %s
ORDER BY published_at DESC
LIMIT 20
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
            cursor.execute(NEWS_SQL, (instrument_id,))
            news = tuple(
                StoredNews(str(row[0]), row[1], row[2]) for row in cursor.fetchall()
            )
        return SymbolSnapshot(instrument_id, canonical_symbol, results, artifacts, news)

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
