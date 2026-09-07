"""Teknik bot dinleme zinciri yeniden başlatma testleri."""

import os
import unittest
from unittest.mock import Mock, patch

from src import bot_runner


class RestartSelfTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "GITHUB_TOKEN": "workflow-token",
            "GH_PAT": "stale-pat",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_REF_NAME": "main",
        },
        clear=True,
    )
    @patch("src.bot_runner.send_text")
    @patch("src.bot_runner.requests.post")
    def test_workflow_token_bypasses_stale_pat(self, post: Mock, send_text: Mock) -> None:
        post.return_value = Mock(status_code=204, text="")

        self.assertTrue(bot_runner.restart_self())

        self.assertEqual(post.call_count, 1)
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer workflow-token",
        )
        send_text.assert_not_called()

    @patch.dict(
        os.environ,
        {
            "GITHUB_TOKEN": "expired-workflow-token",
            "GH_PAT": "working-pat",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_REF_NAME": "main",
        },
        clear=True,
    )
    @patch("src.bot_runner.send_text")
    @patch("src.bot_runner.requests.post")
    def test_failed_primary_token_falls_back(self, post: Mock, send_text: Mock) -> None:
        post.side_effect = [
            Mock(status_code=403, text="forbidden"),
            Mock(status_code=204, text=""),
        ]

        self.assertTrue(bot_runner.restart_self())

        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args_list[1].kwargs["headers"]["Authorization"],
            "Bearer working-pat",
        )
        send_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
