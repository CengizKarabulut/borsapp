from __future__ import annotations

import time
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
        if method != "sendMessage":
            raise TelegramDeliveryError(f"Desteklenmeyen Telegram yöntemi: {method}")
        data["chat_id"] = chat_id
        data["message_thread_id"] = message_thread_id
        url = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        body: dict[str, Any] = {}
        for attempt in range(5):
            try:
                response = httpx.post(url, data=data, timeout=self.timeout_seconds)
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
