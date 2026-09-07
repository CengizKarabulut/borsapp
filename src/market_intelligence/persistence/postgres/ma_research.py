from __future__ import annotations

from market_intelligence.core.identity import canonical_json
from market_intelligence.features.ma import MaQualification
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.persistence.postgres.scan_store import PostgresConnection
from market_intelligence.research.ma_levels import ResearchedMaLevel

ACTIVE_LEVELS_SQL = """
SELECT ma_type, period, level_class, touches, quality_score, research_version,
       qualification_side
FROM ma_research_levels
WHERE instrument_id = %s
  AND timeframe = %s
  AND valid_from <= %s
  AND (valid_until IS NULL OR valid_until > %s)
ORDER BY quality_score DESC, touches DESC, ma_type, period
"""

CLOSE_LEVELS_SQL = """
UPDATE ma_research_levels
SET valid_until = %s
WHERE instrument_id = %s AND timeframe = %s
  AND valid_from < %s
  AND (valid_until IS NULL OR valid_until > %s)
"""

UPSERT_LEVEL_SQL = """
INSERT INTO ma_research_levels (
    instrument_id, timeframe, ma_type, period, qualification_side,
    level_class, touches, quality_score, research_version,
    valid_from, valid_until, metrics
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s::jsonb)
ON CONFLICT (
    instrument_id, timeframe, ma_type, period, research_version, valid_from
)
DO UPDATE SET
    qualification_side = EXCLUDED.qualification_side,
    level_class = EXCLUDED.level_class,
    touches = EXCLUDED.touches,
    quality_score = EXCLUDED.quality_score,
    metrics = EXCLUDED.metrics,
    valid_until = NULL
"""

LATEST_LEVEL_TIME_SQL = """
SELECT max(valid_from)
FROM ma_research_levels
WHERE instrument_id = %s AND timeframe = %s
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
                qualification_side=str(row[6]),
            )
            for row in rows
        )


class PostgresMaResearchStore:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def replace(
        self,
        frame: CanonicalFrame,
        levels: tuple[ResearchedMaLevel, ...],
    ) -> int:
        through = frame.through_bar_time
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    LATEST_LEVEL_TIME_SQL,
                    (frame.instrument_id, frame.timeframe.value),
                )
                latest_row = cursor.fetchone()
                latest = latest_row[0] if latest_row else None
                if latest is not None and latest > through:
                    raise ValueError("Daha yeni MA Research seviyesinin üzerine eski frame yazılamaz")
                cursor.execute(
                    CLOSE_LEVELS_SQL,
                    (
                        through,
                        frame.instrument_id,
                        frame.timeframe.value,
                        through,
                        through,
                    ),
                )
                for level in levels:
                    cursor.execute(
                        UPSERT_LEVEL_SQL,
                        (
                            frame.instrument_id,
                            frame.timeframe.value,
                            level.ma_type,
                            level.period,
                            level.qualification_side,
                            level.level_class,
                            level.touches,
                            level.quality_score,
                            level.research_version,
                            through,
                            canonical_json(level.metrics),
                        ),
                    )
        return len(levels)
