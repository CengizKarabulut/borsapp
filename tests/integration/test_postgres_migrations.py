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

        # Entegrasyon sınıfları aynı tek kullanımlık CI veritabanını paylaşır;
        # önce çalışan doctor testi şemayı hazırlamış olabilir. İlk çağrı her
        # migration'ı ya uygular ya da doğrulanmış olarak atlar.
        expected = {"000", "001", "002", "003", "004"}
        self.assertEqual(set(first.applied) | set(first.skipped), expected)
        self.assertEqual(second.applied, ())
        self.assertEqual(set(second.skipped), expected)
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
