from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from market_intelligence.operations.doctor import inspect_runtime
from market_intelligence.persistence.postgres.migrations import apply_migrations

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is not set")
class DoctorIntegrationTests(unittest.TestCase):
    def test_fresh_migrated_database_is_operational_with_bootstrap_warnings(self) -> None:
        import psycopg

        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as connection:
            apply_migrations(connection, ROOT / "db/postgres")
            report = inspect_runtime(
                connection,
                migrations_directory=ROOT / "db/postgres",
                now=datetime.now(UTC),
                maximum_cycle_age=timedelta(hours=48),
            )

        self.assertTrue(report.healthy)
        statuses = {check.name: check.status for check in report.checks}
        self.assertEqual(statuses["database"], "OK")
        self.assertEqual(statuses["migrations"], "OK")
        self.assertEqual(statuses["universe"], "WARN")
