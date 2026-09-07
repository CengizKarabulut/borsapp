from __future__ import annotations

from market_intelligence.features.ma import MaQualification
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.persistence.postgres.scan_store import PostgresConnection

ACTIVE_LEVELS_SQL = """
SELECT ma_type, period, level_class, touches, quality_score, research_version
FROM ma_research_levels
WHERE instrument_id = %s
  AND timeframe = %s
  AND valid_from <= %s
  AND (valid_until IS NULL OR valid_until > %s)
ORDER BY quality_score DESC, touches DESC, ma_type, period
"""


class PostgresMaQualificationSource:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def load(self, frame: CanonicalFrame) -> tuple[MaQualification, ...]:
        through = frame.through_bar_time
        with self.connection.cursor() as cursor:
            cursor.execute(
                ACTIVE_LEVELS_SQL,
                (frame.instrument_id, frame.timeframe.value, through, through),
            )
            rows = cursor.fetchall()
        return tuple(
            MaQualification(
                ma_type=str(row[0]).upper(),
                period=int(row[1]),
                level_class=str(row[2]),
                touches=int(row[3]),
                quality_score=float(row[4]),
                research_version=str(row[5]),
            )
            for row in rows
        )
