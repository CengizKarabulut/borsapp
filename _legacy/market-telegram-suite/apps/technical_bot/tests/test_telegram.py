import io
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.telegram_client import (
    CAPTION_LIMIT,
    MESSAGE_LIMIT,
    build_caption,
    send_photo,
    send_report_detail,
    split_message,
)

STATUS = {
    "symbol": "THYAO",
    "price": 305.25,
    "change_pct": -0.89,
    "timestamp": "2026-08-14T09:00:00+03:00",
    "data_provider": "borsapy/TradingView",
    "bar_state": {"label": "TEYİTLİ", "market_state": "CLOSED"},
    "market_context": {
        "regime": {"state": "Dengeli / sıkışan piyasa", "atr_percentile": 45.0, "bb_percentile": 20.0},
        "structure": {"state": "LH / LL", "event": "Swing Low altı BOS"},
        "profile": {
            "position": "Value Area içinde",
            "poc": 326.62,
            "vah": 336.25,
            "val": 301.25,
            "acceptance": "Value Area içinde rotasyon",
        },
        "relative_volume": 0.68,
        "divergences": {
            "indicators": {
                "SMI": {"detected": True, "state": "Negatif normal uyumsuzluk", "event_age": 3},
            }
        },
    },
    "technical_commentary": {
        "headline": "Denge rejiminde hacim ve kabul teyidi bekleniyor.",
        "telegram_detail": "🧭 Analist Notu\nAyrıntılı okuma metni.",
    },
}


class TelegramClientTests(unittest.TestCase):
    def _send_photo_payload(self, environment: dict[str, str]) -> dict:
        response = Mock(ok=True, status_code=200, text='{"ok":true}')
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(Path, "open", return_value=io.BytesIO(b"png")),
            patch("src.telegram_client.requests.post", return_value=response) as post,
        ):
            send_photo(Path("report.png"), STATUS)
        return post.call_args.kwargs["data"]

    def test_general_topic_omits_message_thread_id(self) -> None:
        payload = self._send_photo_payload(
            {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "-1003502567927"}
        )
        self.assertNotIn("message_thread_id", payload)

    def test_explicit_topic_adds_message_thread_id(self) -> None:
        payload = self._send_photo_payload(
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_CHAT_ID": "-1003502567927",
                "TELEGRAM_MESSAGE_THREAD_ID": "99",
            }
        )
        self.assertEqual(payload["message_thread_id"], "99")

    def test_photos_carry_no_caption_by_default(self) -> None:
        payload = self._send_photo_payload(
            {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "-1003502567927"}
        )
        self.assertNotIn("caption", payload)

    def test_caption_can_be_enabled_and_is_bounded(self) -> None:
        payload = self._send_photo_payload(
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_CHAT_ID": "-1003502567927",
                "TELEGRAM_SEND_CAPTION": "1",
            }
        )
        self.assertIn("Teknik Piyasa Durumu", payload["caption"])
        self.assertIn("SMI Negatif normal uyumsuzluk (3 bar)", payload["caption"])
        self.assertLessEqual(len(payload["caption"]), CAPTION_LIMIT)

    def test_build_caption_contains_current_commentary(self) -> None:
        caption = build_caption(STATUS)
        self.assertIn("Teknik yorum:", caption)
        self.assertIn("Denge rejiminde hacim ve kabul teyidi bekleniyor.", caption)

    @patch("src.telegram_client.send_text")
    def test_text_detail_is_disabled_by_default(self, send_text: Mock) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "-1003502567927"},
            clear=True,
        ):
            self.assertFalse(send_report_detail(STATUS))
        send_text.assert_not_called()

    @patch("src.telegram_client.send_text")
    def test_text_detail_can_be_enabled(self, send_text: Mock) -> None:
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_CHAT_ID": "-1003502567927",
                "TELEGRAM_SEND_TEXT_DETAIL": "1",
            },
            clear=True,
        ):
            self.assertTrue(send_report_detail(STATUS))
        self.assertIn("Ayrıntılı okuma metni.", send_text.call_args.args[0])

    def test_split_message_respects_limit_and_keeps_content(self) -> None:
        text = "\n".join(f"satır {index} " + "x" * 80 for index in range(150))
        parts = split_message(text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= MESSAGE_LIMIT for part in parts))
        self.assertIn("satır 149", parts[-1])


if __name__ == "__main__":
    unittest.main()
