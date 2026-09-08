from __future__ import annotations

from datetime import datetime

from market_intelligence.core.identity import canonical_json
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.persistence.postgres.scan_store import PostgresConnection
from market_intelligence.shadow.compare import ShadowComparison
from market_intelligence.shadow.report import ParityScore

UPSERT_SHADOW_SQL = """
INSERT INTO shadow_comparisons (
    snapshot_id, instrument_id, scanner_id, timeframe, bar_time,
    legacy_status, new_status, category,
    legacy_finding_keys, new_finding_keys, diagnostics
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
ON CONFLICT (snapshot_id, scanner_id) DO UPDATE SET
    legacy_status = EXCLUDED.legacy_status,
    new_status = EXCLUDED.new_status,
    category = EXCLUDED.category,
    legacy_finding_keys = EXCLUDED.legacy_finding_keys,
    new_finding_keys = EXCLUDED.new_finding_keys,
    diagnostics = EXCLUDED.diagnostics
RETURNING comparison_id
"""

REPORT_SQL = """
SELECT
    scanner_id,
    timeframe,
    count(*),
    count(*) FILTER (WHERE category = 'agree_match'),
    count(*) FILTER (WHERE category = 'agree_no_match'),
    count(*) FILTER (WHERE category = 'legacy_only'),
    count(*) FILTER (WHERE category = 'new_only'),
    count(*) FILTER (WHERE category = 'finding_diff'),
    count(*) FILTER (WHERE category = 'unknown')
FROM shadow_comparisons
WHERE created_at >= %s
  AND (%s IS NULL OR scanner_id = %s)
  AND (%s IS NULL OR timeframe = %s)
GROUP BY scanner_id, timeframe
ORDER BY scanner_id, timeframe
"""


class PostgresShadowStore:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def persist(self, frame: CanonicalFrame, comparison: ShadowComparison) -> str:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    UPSERT_SHADOW_SQL,
                    (
                        comparison.snapshot_id,
                        frame.instrument_id,
                        comparison.scanner_id,
                        frame.timeframe.value,
                        frame.through_bar_time,
                        comparison.legacy_status.value,
                        comparison.new_status.value,
                        comparison.category.value,
                        canonical_json(list(comparison.legacy_finding_keys)),
                        canonical_json(list(comparison.new_finding_keys)),
                        canonical_json(list(comparison.diagnostics)),
                    ),
                )
                row = cursor.fetchone()
        if not row:
            raise RuntimeError("shadow_comparisons comparison_id döndürmedi")
        return str(row[0])

    def report(
        self,
        *,
        since: datetime,
        scanner_id: str | None = None,
        timeframe: str | None = None,
    ) -> tuple[ParityScore, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                REPORT_SQL,
                (since, scanner_id, scanner_id, timeframe, timeframe),
            )
            rows = cursor.fetchall()
        return tuple(ParityScore(*row) for row in rows)
