from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from market_intelligence.compat.telegram_retry import retry_legacy_telegram_posts
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport


class Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class TelegramRetryTests(unittest.TestCase):
    @patch("market_intelligence.compat.telegram_retry.time.sleep")
    def test_legacy_post_retries_429_and_rewinds_file(self, sleep: Mock) -> None:
        handle = io.BytesIO(b"image")
        responses = [
            Response(429, {"parameters": {"retry_after": 2}}),
            Response(200, {"ok": True}),
        ]
        mocked_post = Mock(side_effect=responses)
        fake_requests = SimpleNamespace(post=mocked_post)
        with patch.dict(sys.modules, {"requests": fake_requests}):
            with retry_legacy_telegram_posts():
                response = fake_requests.post(
                    "https://api.telegram.org/botTOKEN/sendPhoto",
                    files={"photo": ("x.png", handle, "image/png")},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_post.call_count, 2)
        sleep.assert_called_once_with(2.0)

    @patch("market_intelligence.delivery.telegram.http_transport.time.sleep")
    def test_modern_transport_retries_429(self, sleep: Mock) -> None:
        fake_httpx = SimpleNamespace(
            post=Mock(
                side_effect=[
                    Response(429, {"ok": False, "parameters": {"retry_after": 3}}),
                    Response(
                        200,
                        {
                            "ok": True,
                            "result": {"message_id": 9, "message_thread_id": 5},
                        },
                    ),
                ]
            )
        )
        with patch.dict(sys.modules, {"httpx": fake_httpx}):
            message_id = HttpxTelegramTransport("token").send(
                chat_id=-1001,
                message_thread_id=5,
                payload={"text": "test"},
            )
        self.assertEqual(message_id, 9)
        self.assertEqual(fake_httpx.post.call_count, 2)
        sleep.assert_called_once_with(3.0)

    def test_modern_transport_uploads_pdf_document(self) -> None:
        fake_httpx = SimpleNamespace(
            post=Mock(
                return_value=Response(
                    200,
                    {"ok": True, "result": {"message_id": 12, "message_thread_id": 70}},
                )
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ASELS.pdf"
            path.write_bytes(b"%PDF-1.4 fixture")
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                message_id = HttpxTelegramTransport("token").send(
                    chat_id=-1001,
                    message_thread_id=70,
                    payload={
                        "_method": "sendDocument",
                        "document_path": str(path),
                        "filename": "ASELS_rapor.pdf",
                        "caption": "ASELS raporu",
                    },
                )
        self.assertEqual(message_id, 12)
        call = fake_httpx.post.call_args
        self.assertEqual(call.kwargs["data"]["caption"], "ASELS raporu")
        self.assertEqual(call.kwargs["files"]["document"][0], "ASELS_rapor.pdf")

    def test_document_can_retry_from_durable_outbox_bytes_without_local_file(self) -> None:
        fake_httpx = SimpleNamespace(
            post=Mock(
                return_value=Response(
                    200,
                    {"ok": True, "result": {"message_id": 13, "message_thread_id": 70}},
                )
            )
        )
        with patch.dict(sys.modules, {"httpx": fake_httpx}):
            message_id = HttpxTelegramTransport("token").send(
                chat_id=-1001,
                message_thread_id=70,
                payload={
                    "_method": "sendDocument",
                    "document_base64": "JVBERi0xLjQgZml4dHVyZQ==",
                    "filename": "ASELS_rapor.pdf",
                },
            )
        self.assertEqual(message_id, 13)
        uploaded = fake_httpx.post.call_args.kwargs["files"]["document"][1]
        self.assertEqual(uploaded.getvalue(), b"%PDF-1.4 fixture")


if __name__ == "__main__":
    unittest.main()
