from __future__ import annotations

import unittest

from scripts.atc_ephemeral_universe import assert_local_ephemeral_url


class EphemeralDatabaseSafetyTests(unittest.TestCase):
    def test_exact_local_database_allowed(self):
        self.assertIsNone(
            assert_local_ephemeral_url(
                "postgresql://user:password@localhost:5432/atc_scan"
            )
        )

    def test_remote_neon_and_other_local_databases_are_rejected(self):
        addresses = (
            "postgresql://user:pw@ep-big.neon.tech/atc_scan",
            "postgresql://user:pw@localhost:5432/production",
            "postgresql://user:pw@ep-big.neon.tech/atc_scan?query=@localhost:",
            "https://localhost:5432/atc_scan",
        )
        for url in addresses:
            with self.subTest(url=url), self.assertRaises(ValueError):
                assert_local_ephemeral_url(url)


if __name__ == "__main__":
    unittest.main()
