from __future__ import annotations

import os
import unittest
from pathlib import Path

from market_intelligence.market_data.provider_cooldown import ProviderRetryCooldowns
from market_intelligence.persistence.postgres.migrations import apply_migrations

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL required")
class ProviderCooldownIntegrationTests(unittest.TestCase):
    def test_cooldown_persists_across_independent_github_worker_instances(self):
        import psycopg

        url = os.environ["TEST_DATABASE_URL"]
        with psycopg.connect(url) as db:
            apply_migrations(db, ROOT / "db/postgres")
        first = ProviderRetryCooldowns(url)
        next_run = ProviderRetryCooldowns(url)
        try:
            self.assertFalse(first.skip("borsapy", "ATC_CI_TEST", "1d"))
            first.failed("borsapy", "ATC_CI_TEST", "1d", "NoData")
            self.assertTrue(first.skip("borsapy", "ATC_CI_TEST", "1d"))
            self.assertTrue(next_run.skip("borsapy", "ATC_CI_TEST", "1d"))
            self.assertFalse(next_run.skip("borsapy", "ATC_CI_TEST", "1h"))
            first.failed("borsapy", "ATC_CI_TEST", "1d", "NoData")
            with psycopg.connect(url) as db:
                row = db.execute(
                    "SELECT failures FROM provider_retry_cooldowns WHERE provider=%s AND provider_symbol=%s AND timeframe=%s",
                    ("borsapy", "ATC_CI_TEST", "1d"),
                ).fetchone()
                self.assertEqual(row[0], 2)
            first.recovered("borsapy", "ATC_CI_TEST", "1d")
            self.assertFalse(ProviderRetryCooldowns(url).skip("borsapy", "ATC_CI_TEST", "1d"))
        finally:
            with psycopg.connect(url, autocommit=True) as db:
                db.execute(
                    "DELETE FROM provider_retry_cooldowns WHERE provider_symbol=%s",
                    ("ATC_CI_TEST",),
                )


if __name__ == "__main__":
    unittest.main()
