from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from market_intelligence.cli import main
from market_intelligence.settings import ApplicationSettings, read_env_file


def valid_values() -> dict[str, str]:
    values = {
        "APP_ENV": "test",
        "APP_TIMEZONE": "Europe/Istanbul",
        "DATABASE_URL": "postgresql://user:secret@localhost/borsapp",
        "TELEGRAM_BOT_TOKEN": "123456:secret-token",
        "TELEGRAM_CHAT_ID": "-100123",
        "TELEGRAM_ALLOWED_USERS": "42",
        "DELIVERY_MODE": "disabled",
    }
    for topic in (
        "COMMAND",
        "SCANS",
        "ANALYSIS",
        "CHARTS",
        "NEWS",
        "CALENDAR",
        "REPORTS",
        "SYSTEM",
    ):
        values[f"TELEGRAM_TOPIC_{topic}"] = "10"
    return values


class SettingsTests(unittest.TestCase):
    def test_secrets_are_not_exposed_by_repr(self) -> None:
        settings = ApplicationSettings.from_mapping(valid_values())
        rendered = repr(settings)
        self.assertNotIn("secret-token", rendered)
        self.assertNotIn("user:secret", rendered)

    def test_env_file_parser_does_not_mutate_or_require_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("A=one\n# comment\nB='two'\n", encoding="utf-8")
            self.assertEqual(read_env_file(path), {"A": "one", "B": "two"})

    def test_config_check_never_prints_secrets(self) -> None:
        values = valid_values()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "\n".join(f"{key}={value}" for key, value in values.items()),
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--env-file", str(path), "config-check"])
        self.assertEqual(result, 0)
        output = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("secret-token", output)
        self.assertNotIn("user:secret", output)
        self.assertIn("delivery=disabled", output)


if __name__ == "__main__":
    unittest.main()
