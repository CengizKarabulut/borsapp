from __future__ import annotations

import csv
import tomllib
import unittest
from pathlib import Path

from market_intelligence.delivery.telegram.config import TOPIC_ENV_KEYS

ROOT = Path(__file__).parents[1]


class MigrationContractTests(unittest.TestCase):
    def test_verified_aliases_exist_in_both_directions(self) -> None:
        path = ROOT / "docs" / "migration" / "legacy-aliases.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        verified = [row for row in rows if row["status"] == "verified_code"]
        mappings = {
            (row["source_repo"], row["legacy_id"], row["new_id"], row["direction"])
            for row in verified
        }
        for source, legacy_id, new_id, _direction in mappings:
            self.assertIn((source, legacy_id, new_id, "legacy_to_new"), mappings)
            self.assertIn((source, legacy_id, new_id, "new_to_legacy"), mappings)

    def test_alias_evidence_files_exist(self) -> None:
        path = ROOT / "docs" / "migration" / "legacy-aliases.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            evidence_path = row["evidence"].rsplit(":", 1)[0]
            self.assertTrue((ROOT / evidence_path).is_file(), evidence_path)

    def test_notification_timeframes_are_shadowed_first(self) -> None:
        with (ROOT / "config" / "scanners.toml").open("rb") as handle:
            config = tomllib.load(handle)["technical"]["volume_spike"]
        self.assertLessEqual(
            set(config["notification_timeframes"]),
            set(config["shadow_timeframes"]),
        )
        self.assertEqual(config["partial_bar_policy"], "drop")

    def test_env_example_contains_every_topic_key(self) -> None:
        sample = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in TOPIC_ENV_KEYS.values():
            self.assertIn(f"{key}=", sample)


if __name__ == "__main__":
    unittest.main()
