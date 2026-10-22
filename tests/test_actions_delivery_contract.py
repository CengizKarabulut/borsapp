"""Guard the active Telegram delivery routes against retired automatic writers."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def triggers(content: str) -> str:
    return content.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]


class ActionsDeliveryContractTests(unittest.TestCase):
    def test_only_current_database_free_reports_are_scheduled(self):
        scheduled = {
            path.name
            for path in WORKFLOWS.glob("*.yml")
            if re.search(r"^  schedule:", triggers(path.read_text(encoding="utf-8")), re.M)
        }
        self.assertEqual(
            scheduled, {"atc-scheduled-snapshots.yml", "atc-ephemeral-morning.yml"},
        )
        for name in scheduled:
            with self.subTest(workflow=name):
                content = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertNotIn("DATABASE_URL", content)
                self.assertNotIn("borsapp db-", content)
                self.assertNotIn("publisher-once", content)
                self.assertIn("github.ref == 'refs/heads/main'", content)

    def test_code_changes_cannot_run_maintenance_or_live_publication(self):
        for path in WORKFLOWS.glob("*.yml"):
            content = path.read_text(encoding="utf-8")
            if path.name == "ci.yml":
                self.assertIn("  push:", triggers(content))
                self.assertIn("  pull_request:", triggers(content))
                continue
            with self.subTest(workflow=path.name):
                self.assertNotRegex(triggers(content), r"(?m)^  (push|pull_request):")
                self.assertIn("  workflow_dispatch:", triggers(content))
                self.assertNotRegex(content, r"(?m)^\s+ref: (fix/|atc-.*20261017)")

    def test_manual_live_packets_default_to_preview_and_retain_receipts(self):
        for name in ("atc-live-snapshot.yml", "atc-support-pivot-report.yml"):
            content = (WORKFLOWS / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                self.assertIn("options: [preview, publish]", content)
                self.assertIn("default: preview", content)
                self.assertIn("Publication requires main", content)
                self.assertIn("actions/upload-artifact@v4", content)
                self.assertRegex(content, r"(publication-receipt|delivery)\.json")


if __name__ == "__main__":
    unittest.main()
