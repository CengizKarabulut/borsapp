from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.persistence.postgres.migrations import apply_migrations
from market_intelligence.persistence.postgres.shadow import PostgresShadowStore
from market_intelligence.shadow.compare import ShadowCategory, ShadowComparison
from tests.test_volume_spike import frame

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is not set")
class PostgresShadowStoreIntegrationTests(unittest.TestCase):
    def test_comparison_upsert_and_report_are_real_postgres_operations(self) -> None:
        import psycopg

        instrument_id = str(uuid4())
        snapshot_id = f"integration-shadow-{uuid4()}"
        source = replace(frame(), instrument_id=instrument_id, snapshot_id=snapshot_id)
        comparison = ShadowComparison(
            snapshot_id=snapshot_id,
            scanner_id="technical.volume_spike",
            legacy_status=EvaluationStatus.NO_MATCH,
            new_status=EvaluationStatus.NO_MATCH,
            legacy_finding_keys=(),
            new_finding_keys=(),
            category=ShadowCategory.AGREE_NO_MATCH,
            diagnostics=(),
        )
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as connection:
            apply_migrations(connection, ROOT / "db/postgres")
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO instruments (
                        instrument_id, asset_class, market, name, valid_from
                    ) VALUES (%s, 'equity', 'BIST', 'Shadow fixture', %s)
                    """,
                    (instrument_id, datetime.now(UTC).date()),
                )
                cursor.execute(
                    """
                    INSERT INTO data_snapshots (
                        snapshot_id, instrument_id, timeframe, through_bar_time,
                        source, price_basis, series_revision, payload_hash,
                        storage_uri, quality
                    ) VALUES (%s, %s, '1h', %s, 'fixture', 'split_adjusted', 1,
                              'hash', 'postgres://canonical_market_bars', 'complete')
                    """,
                    (snapshot_id, instrument_id, source.through_bar_time),
                )
            store = PostgresShadowStore(connection)
            first_id = store.persist(source, comparison)
            second_id = store.persist(source, comparison)
            scores = store.report(
                since=datetime.now(UTC) - timedelta(minutes=1),
                scanner_id="technical.volume_spike",
                timeframe="1h",
            )

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0].samples, 1)
        self.assertEqual(scores[0].agreement, 1.0)
