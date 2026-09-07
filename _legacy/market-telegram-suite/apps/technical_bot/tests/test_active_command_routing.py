from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import bot_runner as base
from src import bot_runner_fundamental as routed


class ActiveCommandRoutingTests(unittest.TestCase):
    @patch("src.bot_runner_fundamental.handle_research")
    def test_legacy_rapor_routes_to_current_research_bundle(self, handle_research: Mock) -> None:
        command = SimpleNamespace(name="rapor", chat_id=42, args=["ASELS"])

        routed.execute(command, {"1d", "4h"})

        handle_research.assert_called_once_with(42, ["ASELS"], "rapor")

    @patch.dict(
        os.environ,
        {"GITHUB_TOKEN": "token", "GITHUB_REPOSITORY": "owner/repo"},
        clear=False,
    )
    @patch("src.bot_runner.requests.get")
    def test_scan_history_accepts_current_and_legacy_artifact_names(self, get: Mock) -> None:
        response = Mock(ok=True)
        response.json.return_value = {
            "artifacts": [
                {
                    "name": "bist-teknik-tarama",
                    "created_at": "2026-09-05T10:00:00Z",
                    "expired": False,
                },
                {
                    "name": "bist-tarama-12345",
                    "created_at": "2026-09-06T10:00:00Z",
                    "expired": False,
                },
                {
                    "name": "teknik-rapor-ASELS-1d",
                    "created_at": "2026-09-06T11:00:00Z",
                    "expired": False,
                },
            ]
        }
        get.return_value = response

        artifacts = base.list_scan_artifacts()

        self.assertEqual([item["name"] for item in artifacts], ["bist-tarama-12345", "bist-teknik-tarama"])

    @patch("src.bot_runner._latest_scan_payload")
    @patch("src.bot_runner.send_analyst_cards")
    @patch("src.bot_runner.standardize_pages")
    @patch("src.bot_runner.render_scan_cards")
    def test_liste_uses_latest_workflow_payload(
        self,
        render_scan_cards: Mock,
        standardize_pages: Mock,
        send_analyst_cards: Mock,
        latest_payload: Mock,
    ) -> None:
        latest_payload.return_value = {
            "results": [{"ticker": "ASELS"}],
            "universe_source": "borsapy",
            "elapsed_seconds": 12.0,
        }
        render_scan_cards.return_value = ["page"]

        base.handle_list(42)

        render_scan_cards.assert_called_once()
        standardize_pages.assert_called_once_with(["page"])
        send_analyst_cards.assert_called_once_with(["page"], {})


if __name__ == "__main__":
    unittest.main()
