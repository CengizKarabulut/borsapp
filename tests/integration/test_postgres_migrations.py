from __future__ import annotations

import os
import unittest
from pathlib import Path

from market_intelligence.persistence.postgres.migrations import apply_migrations

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is not set")
class PostgresMigrationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg

        cls.connection = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.connection.close()

    def test_full_schema_is_applied_and_second_run_is_idempotent(self) -> None:
        first = apply_migrations(self.connection, ROOT / "db/postgres")
        second = apply_migrations(self.connection, ROOT / "db/postgres")

        self.assertIn("000", first.applied)
        self.assertIn("001", first.applied)
        self.assertIn("002", first.applied)
        self.assertEqual(second.applied, ())
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    to_regclass('public.schema_migrations'),
                    to_regclass('public.canonical_market_bars'),
                    to_regclass('public.canonical_bars')
                """
            )
            migration_table, canonical_table, obsolete_table = cursor.fetchone()
            cursor.execute("SELECT count(*) FROM schema_migrations")
            migration_count = cursor.fetchone()[0]

        self.assertIsNotNone(migration_table)
        self.assertIsNotNone(canonical_table)
        self.assertIsNone(obsolete_table)
        self.assertEqual(migration_count, len(second.skipped))
