from __future__ import annotations

from typing import Any, Protocol

from market_intelligence.core.identity import canonical_json, stable_hash
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.market_data.errors import SeriesRevisionConflict


class Cursor(Protocol):
    def execute(self, query: str, params: tuple[Any, ...]) -> Any: ...

    def executemany(self, query: str, params: list[tuple[Any, ...]]) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def __enter__(self) -> Cursor: ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...


class Connection(Protocol):
    def transaction(self): ...

    def cursor(self) -> Cursor: ...


SNAPSHOT_SQL = """
INSERT INTO data_snapshots (
    snapshot_id, instrument_id, timeframe, frame_start_time, through_bar_time,
    bar_count, source, price_basis, series_revision, payload_hash, storage_uri,
    quality, is_provisional
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
ON CONFLICT (snapshot_id) DO UPDATE SET
    frame_start_time = COALESCE(data_snapshots.frame_start_time, EXCLUDED.frame_start_time),
    bar_count = COALESCE(data_snapshots.bar_count, EXCLUDED.bar_count),
    storage_uri = EXCLUDED.storage_uri
"""

INSERT_BARS_SQL = """
INSERT INTO canonical_market_bars (
    instrument_id, timeframe, source, price_basis, series_revision,
    open_time, close_time, open, high, low, close, volume, content_hash
)
SELECT
    value.instrument_id, value.timeframe, value.source, value.price_basis,
    value.series_revision, value.open_time, value.close_time, value.open,
    value.high, value.low, value.close, value.volume, value.content_hash
FROM jsonb_to_recordset(%s::jsonb) AS value(
    instrument_id UUID, timeframe TEXT, source TEXT, price_basis TEXT,
    series_revision BIGINT, open_time TIMESTAMPTZ, close_time TIMESTAMPTZ,
    open DOUBLE PRECISION, high DOUBLE PRECISION, low DOUBLE PRECISION,
    close DOUBLE PRECISION, volume DOUBLE PRECISION, content_hash TEXT
)
ON CONFLICT (
    instrument_id, timeframe, source, price_basis, series_revision, close_time
) DO NOTHING
"""

FIND_REVISION_CONFLICT_SQL = """
SELECT value.close_time
FROM jsonb_to_recordset(%s::jsonb) AS value(
    instrument_id UUID, timeframe TEXT, source TEXT, price_basis TEXT,
    series_revision BIGINT, close_time TIMESTAMPTZ, content_hash TEXT
)
JOIN canonical_market_bars stored
  ON stored.instrument_id = value.instrument_id
 AND stored.timeframe = value.timeframe
 AND stored.source = value.source
 AND stored.price_basis = value.price_basis
 AND stored.series_revision = value.series_revision
 AND stored.close_time = value.close_time
WHERE stored.content_hash IS DISTINCT FROM value.content_hash
LIMIT 1
"""

LATEST_REVISION_SQL = """
SELECT COALESCE(MAX(series_revision), 0)
FROM canonical_market_bars
WHERE instrument_id = %s
  AND timeframe = %s
  AND source = %s
  AND price_basis = %s
"""


class PostgresSnapshotStore:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def latest_series_revision(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        source: str,
        price_basis: str,
    ) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                LATEST_REVISION_SQL,
                (instrument_id, timeframe, source, price_basis),
            )
            row = cursor.fetchone()
        return int(row[0]) if row else 0

    def save(self, frame: CanonicalFrame) -> None:
        bar_rows = [
            {
                "instrument_id": frame.instrument_id,
                "timeframe": frame.timeframe.value,
                "source": frame.source,
                "price_basis": frame.price_basis.value,
                "series_revision": frame.series_revision,
                "open_time": bar.open_time,
                "close_time": bar.close_time,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "content_hash": stable_hash(bar),
            }
            for bar in frame.bars
        ]
        serialized_bars = canonical_json(bar_rows)
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(INSERT_BARS_SQL, (serialized_bars,))
                cursor.execute(FIND_REVISION_CONFLICT_SQL, (serialized_bars,))
                conflict = cursor.fetchone()
                if conflict:
                    raise SeriesRevisionConflict(
                        "Canonical bar içeriği aynı series_revision içinde değişti: "
                        f"{conflict[0]}; series_revision artırılmalıdır"
                    )
                cursor.execute(
                    SNAPSHOT_SQL,
                    (
                        frame.snapshot_id,
                        frame.instrument_id,
                        frame.timeframe.value,
                        frame.bars[0].open_time,
                        frame.through_bar_time,
                        len(frame.bars),
                        frame.source,
                        frame.price_basis.value,
                        frame.series_revision,
                        frame.snapshot_id,
                        f"postgres://canonical_market_bars/{frame.snapshot_id}",
                        frame.quality,
                    ),
                )
