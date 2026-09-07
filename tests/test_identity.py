from __future__ import annotations

import unittest

from market_intelligence.core.identity import ruleset_hash, stable_hash
from market_intelligence.features.specs import FeatureSpec, WarmupSpec


class IdentityTests(unittest.TestCase):
    def test_mapping_order_does_not_change_hash(self) -> None:
        self.assertEqual(stable_hash({"a": 1, "b": 2}), stable_hash({"b": 2, "a": 1}))

    def test_effective_config_changes_ruleset_hash(self) -> None:
        first = ruleset_hash(
            scanner_id="ma.near_zone",
            scanner_version="1",
            resolved_config={"distance_atr": 0.2},
        )
        second = ruleset_hash(
            scanner_id="ma.near_zone",
            scanner_version="1",
            resolved_config={"distance_atr": 0.3},
        )
        self.assertNotEqual(first, second)

    def test_warmup_is_part_of_feature_identity(self) -> None:
        short = FeatureSpec("ema", "classic", "1", {"period": 55}, WarmupSpec(100, "sma"))
        long = FeatureSpec("ema", "classic", "1", {"period": 55}, WarmupSpec(250, "sma"))
        self.assertNotEqual(short.identity_hash, long.identity_hash)


if __name__ == "__main__":
    unittest.main()
