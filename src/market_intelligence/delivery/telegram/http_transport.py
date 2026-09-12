from __future__ import annotations

import base64
import binascii
import io
import json
import time
from pathlib import Path
from typing import Any


class TelegramDeliveryError(RuntimeError):
    pass


class HttpxTelegramTransport:
    """Small Bot API adapter. Scanner and application code never import it."""

    def __init__(self, bot_token: str, *, timeout_seconds: float = 20.0) -> None:
        if not bot_token:
            raise ValueError("Telegram bot token boş olamaz")
        self._bot_token = bot_token
        self.timeout_seconds = timeout_seconds

    def send(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        payload: dict[str, Any],
    ) -> int:
        try:
            import httpx
        except ImportError as exc:
            raise TelegramDeliveryError(
                "httpx kurulu değil; runtime bağımlılıklarını yükleyin"
            ) from exc
        data = dict(payload)
        method = str(data.pop("_method", "sendMessage"))
        if method not in {"sendMessage", "sendDocument", "sendPhoto"}:
            raise TelegramDeliveryError(f"Desteklenmeyen Telegram yöntemi: {method}")
        document_path: Path | None = None
        document_bytes: bytes | None = None
        document_name: str | None = None
        media_field = "photo" if method == "sendPhoto" else "document"
        media_mime = "image/png" if method == "sendPhoto" else "application/pdf"
        if method in {"sendDocument", "sendPhoto"}:
            raw_path = data.pop(f"{media_field}_path", None)
            raw_base64 = data.pop(f"{media_field}_base64", None)
            document_name = str(data.pop("filename", "")).strip() or None
            if isinstance(raw_path, str) and raw_path.strip():
                candidate = Path(raw_path).resolve()
                if candidate.is_file():
                    document_path = candidate
            if document_path is None and isinstance(raw_base64, str) and raw_base64:
                try:
                    document_bytes = base64.b64decode(raw_base64, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise TelegramDeliveryError("Telegram belge içeriği geçersiz") from exc
            if document_path is None and document_bytes is None:
                raise TelegramDeliveryError("Telegram belgesi bulunamadı")
            size = (
                document_path.stat().st_size
                if document_path is not None
                else len(document_bytes or b"")
            )
            if size > (9 if method == "sendPhoto" else 49) * 1024 * 1024:
                raise TelegramDeliveryError("Telegram belgesi 49 MB sınırını aşıyor")
        data["chat_id"] = chat_id
        data["message_thread_id"] = message_thread_id
        # Bot API multipart/form-data ve application/x-www-form-urlencoded
        # isteklerinde nesne alanlarını JSON metni olarak bekler. httpx bir
        # dict'i doğrudan form alanına koyduğunda Python gösterimi gönderilir
        # ve Telegram \"can't parse ... JSON object\" ile bütün kuyruğu reddeder.
        data = {
            key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if isinstance(value, (dict, list))
            else value
            for key, value in data.items()
        }
        url = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        body: dict[str, Any] = {}
        for attempt in range(5):
            try:
                if document_path is None and document_bytes is None:
                    response = httpx.post(url, data=data, timeout=self.timeout_seconds)
                elif document_path is not None:
                    with document_path.open("rb") as document:
                        response = httpx.post(
                            url,
                            data=data,
                            files={
                                media_field: (
                                    document_name or document_path.name,
                                    document,
                                    media_mime,
                                )
                            },
                            timeout=max(self.timeout_seconds, 60.0),
                        )
                else:
                    document = io.BytesIO(document_bytes or b"")
                    response = httpx.post(
                        url,
                        data=data,
                        files={
                            media_field: (
                                document_name or "borsapp-rapor.pdf",
                                document,
                                media_mime,
                            )
                        },
                        timeout=max(self.timeout_seconds, 60.0),
                    )
            except Exception as exc:
                raise TelegramDeliveryError(
                    f"Telegram ağ hatası: {type(exc).__name__}"
                ) from exc
            try:
                body = response.json()
            except Exception as exc:
                raise TelegramDeliveryError(
                    f"Telegram geçersiz yanıt döndürdü: HTTP {response.status_code}"
                ) from exc
            if response.status_code != 429 or attempt == 4:
                break
            raw_delay = body.get("parameters", {}).get("retry_after", 1)
            try:
                delay = min(max(float(raw_delay), 1.0), 120.0)
            except (TypeError, ValueError):
                delay = 1.0
            time.sleep(delay)
        if response.status_code >= 400 or not body.get("ok"):
            description = str(body.get("description", "Bot API isteği başarısız"))
            raise TelegramDeliveryError(description[:500])
        result = body.get("result", {})
        actual_thread = result.get("message_thread_id")
        if actual_thread is not None and int(actual_thread) != message_thread_id:
            raise TelegramDeliveryError(
                "Telegram yanıt topic doğrulaması başarısız"
            )
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise TelegramDeliveryError("Telegram message_id döndürmedi")
        return message_id
