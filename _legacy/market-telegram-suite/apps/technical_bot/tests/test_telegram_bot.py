import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.intervals import INTERVALS
from src.telegram_bot import (
    Command,
    allowed_users,
    is_authorized,
    load_offset,
    parse_command,
    save_offset,
    validate_report_args,
    validate_scan_args,
)

INTERVAL_SET = set(INTERVALS)


def update(text: str, user_id: int = 42, update_id: int = 7) -> dict:
    return {
        "update_id": update_id,
        "message": {"text": text, "chat": {"id": -100}, "from": {"id": user_id, "username": "cengiz"}},
    }


class ParsingTests(unittest.TestCase):
    def test_simple_command_is_parsed(self) -> None:
        command = parse_command(update("/rapor THYAO"))
        self.assertEqual(command.name, "rapor")
        self.assertEqual(command.args, ["THYAO"])

    def test_command_with_bot_mention_is_parsed(self) -> None:
        """Grupta privacy mode açıksa komutlar /rapor@BotAdı biçiminde gelir."""
        command = parse_command(update("/rapor@BistTeknikBot THYAO 4h"))
        self.assertEqual(command.name, "rapor")
        self.assertEqual(command.args, ["THYAO", "4h"])

    def test_turkish_command_name_is_parsed(self) -> None:
        self.assertEqual(parse_command(update("/yardım")).name, "yardım")

    def test_non_command_is_ignored(self) -> None:
        self.assertIsNone(parse_command(update("merhaba")))

    def test_empty_update_is_ignored(self) -> None:
        self.assertIsNone(parse_command({"update_id": 1}))

    def test_sender_details_are_captured(self) -> None:
        command = parse_command(update("/liste", user_id=99))
        self.assertEqual(command.user_id, 99)
        self.assertEqual(command.user_name, "cengiz")


class AuthorizationTests(unittest.TestCase):
    def _command(self, user_id: int) -> Command:
        return Command("rapor", ["THYAO"], -100, user_id, "test", 1)

    def test_empty_allowlist_permits_everyone(self) -> None:
        self.assertTrue(is_authorized(self._command(1), set()))

    def test_listed_user_is_permitted(self) -> None:
        self.assertTrue(is_authorized(self._command(42), {42, 43}))

    def test_unlisted_user_is_rejected(self) -> None:
        self.assertFalse(is_authorized(self._command(7), {42}))

    def test_rejects_command_from_another_chat(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "-200"}, clear=False):
            self.assertFalse(is_authorized(self._command(1), set()))

    def test_rejects_command_from_another_topic(self) -> None:
        command = Command("rapor", ["THYAO"], -100, 1, "test", 1, 99)
        with patch.dict(
            os.environ,
            {"TELEGRAM_CHAT_ID": "-100", "TELEGRAM_MESSAGE_THREAD_ID": "3982"},
            clear=False,
        ):
            self.assertFalse(is_authorized(command, set()))

    def test_accepts_command_from_configured_topic(self) -> None:
        command = Command("rapor", ["THYAO"], -100, 1, "test", 1, 3982)
        with patch.dict(
            os.environ,
            {"TELEGRAM_CHAT_ID": "-100", "TELEGRAM_MESSAGE_THREAD_ID": "3982"},
            clear=False,
        ):
            self.assertTrue(is_authorized(command, set()))

    def test_allowlist_is_read_from_environment(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "42, 43 44"}, clear=True):
            self.assertEqual(allowed_users(), {42, 43, 44})

    def test_blank_environment_means_no_restriction(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "  "}, clear=True):
            self.assertEqual(allowed_users(), set())


class ValidationTests(unittest.TestCase):
    def test_report_defaults_to_daily(self) -> None:
        ticker, interval, error = validate_report_args(["THYAO"], INTERVAL_SET)
        self.assertEqual((ticker, interval, error), ("THYAO", "1d", None))

    def test_report_accepts_explicit_interval(self) -> None:
        self.assertEqual(validate_report_args(["thyao", "4h"], INTERVAL_SET)[:2], ("THYAO", "4h"))

    def test_report_rejects_bad_ticker(self) -> None:
        self.assertIsNotNone(validate_report_args(["TH"], INTERVAL_SET)[2])

    def test_report_rejects_unknown_interval(self) -> None:
        error = validate_report_args(["THYAO", "3h"], INTERVAL_SET)[2]
        self.assertIn("Geçersiz aralık", error)

    def test_report_requires_a_symbol(self) -> None:
        self.assertIn("Sembol belirtilmedi", validate_report_args([], INTERVAL_SET)[2])

    def test_scan_defaults_to_clock_based_selection(self) -> None:
        """Argümansız /tara saate göre çözülür; sabit liste seans dışında yanlış olur."""
        self.assertEqual(validate_scan_args([], INTERVAL_SET), ("auto", None))

    def test_scan_accepts_multiple_intervals(self) -> None:
        self.assertEqual(validate_scan_args(["1h,4h"], INTERVAL_SET)[0], "1h,4h")

    def test_scan_rejects_unknown_interval(self) -> None:
        self.assertIn("Geçersiz aralık", validate_scan_args(["7m"], INTERVAL_SET)[1])


class OffsetTests(unittest.TestCase):
    def test_offset_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "offset.json"
            save_offset(120, path)
            self.assertEqual(load_offset(path), 120)

    def test_missing_file_returns_zero(self) -> None:
        self.assertEqual(load_offset(Path("/tmp/yok_boyle_bir_dosya.json")), 0)

    def test_corrupt_file_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "offset.json"
            path.write_text("bozuk", encoding="utf-8")
            self.assertEqual(load_offset(path), 0)

    def test_saved_payload_is_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "offset.json"
            save_offset(5, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["offset"], 5)


if __name__ == "__main__":
    unittest.main()


class LongPollingTests(unittest.TestCase):
    def test_long_poll_parameter_is_sent_to_telegram(self) -> None:
        """Uzun yoklama olmadan komutlar ancak koşu başında görülür."""
        from unittest.mock import Mock, patch

        from src.telegram_bot import fetch_updates

        response = Mock(ok=True, json=lambda: {"result": []})
        with patch("src.telegram_bot.requests.get", return_value=response) as get:
            fetch_updates("token", 5, long_poll=25)
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["timeout"], 25)
        self.assertEqual(params["offset"], 6)

    def test_request_timeout_exceeds_long_poll(self) -> None:
        """HTTP zaman aşımı, uzun yoklama süresinden kısa olursa bağlantı kopar."""
        from unittest.mock import Mock, patch

        from src.telegram_bot import fetch_updates

        response = Mock(ok=True, json=lambda: {"result": []})
        with patch("src.telegram_bot.requests.get", return_value=response) as get:
            fetch_updates("token", 0, timeout=10, long_poll=25)
        self.assertGreater(get.call_args.kwargs["timeout"], 25)

    def test_failed_request_raises(self) -> None:
        from unittest.mock import Mock, patch

        from src.telegram_bot import fetch_updates

        response = Mock(ok=False, status_code=401, text="unauthorized")
        with patch("src.telegram_bot.requests.get", return_value=response), self.assertRaises(RuntimeError):
            fetch_updates("token", 0)


class ScanDefaultTests(unittest.TestCase):
    def test_bare_scan_command_defers_to_the_clock(self) -> None:
        """Sabit bir aralık listesi seans dışında yanlış olur."""
        self.assertEqual(validate_scan_args([], INTERVAL_SET), ("auto", None))
