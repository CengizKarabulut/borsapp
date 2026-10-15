from __future__ import annotations

import unittest

from scripts.atc_database_capacity import check_database_capacity


class AtcCapacityTests(unittest.TestCase):
    def test_does_not_block_database_with_healthy_headroom(self):
        self.assertIsNone(check_database_capacity(700_000_000, soft_limit_mb=900))

    def test_stops_exactly_at_safety_threshold(self):
        with self.assertRaisesRegex(RuntimeError, "BLOCKED"):
            check_database_capacity(900_000_000, soft_limit_mb=900)

    def test_stops_full_neon_database_without_deletion(self):
        with self.assertRaisesRegex(RuntimeError, "Archive/compact"):
            check_database_capacity(1_050_009_600, soft_limit_mb=900)

    def test_rejects_invalid_soft_limit(self):
        with self.assertRaisesRegex(ValueError, "soft_limit"):
            check_database_capacity(1, soft_limit_mb=90)


if __name__ == "__main__":
    unittest.main()
