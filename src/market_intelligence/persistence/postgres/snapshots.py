from __future__ import annotations

from typing import Any, Protocol

from market_intelligence.market_data.bars import CanonicalFrame


class Cursor(Protocol):
    def execute(self, query: str, params: tuple[Any, ...]) -> Any: ...

    def executemany(self, query: str, params: list[tuple[Any, ...]]) -> Any: ...

    def __enter__(self) -> Cursor: ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...


class Connection(Protocol):
    def transaction(self): ...

    def cursor(self) -> Cursor: ...


SNAPSHOT_SQL = """
INSERT INTO data_snapshots (
    snapshot_id, instrument_id, timeframe, through_bar_time, source,
    price_basis, series_revision, payload_hash, storage_uri, quality,
    is_provisional
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
ON CONFLICT (snapshot_id) DO NOTHING
"""

BAR_SQL = """
INSERT INTO canonical_bars (
    snapshot_id, open_time, close_time, open, high, low, close, volume
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (snapshot_id, close_time) DO NOTHING
"""


class PostgresSnapshotStore:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def save(self, frame: CanonicalFrame) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    SNAPSHOT_SQL,
                    (
                        frame.snapshot_id,
                        frame.instrument_id,
                        frame.timeframe.value,
                        frame.through_bar_time,
                        frame.source,
                        frame.price_basis.value,
                        frame.series_revision,
                        frame.snapshot_id,
                        f"postgres://canonical_bars/{frame.snapshot_id}",
                        frame.quality,
                    ),
                )
                cursor.executemany(
                    BAR_SQL,
                    [
                        (
                            frame.snapshot_id,
                            bar.open_time,
                            bar.close_time,
                            bar.open,
                            bar.high,
                            bar.low,
                            bar.close,
                            bar.volume,
                        )
                        for bar in frame.bars
                    ],
                )
