from __future__ import annotations

from typing import Any


class TelegramUpdateError(RuntimeError):
    pass


class HttpxTelegramUpdateSource:
    def __init__(self, bot_token: str, *, request_timeout_seconds: float = 40.0) -> None:
        if not bot_token:
            raise ValueError("Telegram bot token boş olamaz")
        self._bot_token = bot_token
        self.request_timeout_seconds = request_timeout_seconds

    def fetch(
        self,
        *,
        offset: int,
        timeout_seconds: int = 25,
    ) -> tuple[dict[str, Any], ...]:
        try:
            import httpx
        except ImportError as exc:
            raise TelegramUpdateError(
                "httpx kurulu değil; runtime bağımlılıklarını yükleyin"
            ) from exc
        url = f"https://api.telegram.org/bot{self._bot_token}/getUpdates"
        try:
            response = httpx.get(
                url,
                params={
                    "offset": offset,
                    "timeout": timeout_seconds,
                    "allowed_updates": '["message"]',
                },
                timeout=max(self.request_timeout_seconds, timeout_seconds + 5),
            )
        except Exception as exc:
            raise TelegramUpdateError(
                f"Telegram update ağ hatası: {type(exc).__name__}"
            ) from exc
        try:
            body = response.json()
        except Exception as exc:
            raise TelegramUpdateError(
                f"Telegram geçersiz update yanıtı: HTTP {response.status_code}"
            ) from exc
        if response.status_code >= 400 or not body.get("ok"):
            description = str(body.get("description", "getUpdates başarısız"))
            raise TelegramUpdateError(description[:500])
        result = body.get("result")
        if not isinstance(result, list):
            raise TelegramUpdateError("getUpdates result listesi döndürmedi")
        return tuple(item for item in result if isinstance(item, dict))

    def fetch_chat_administrator_ids(self, *, chat_id: int) -> frozenset[int]:
        try:
            import httpx
        except ImportError as exc:
            raise TelegramUpdateError(
                "httpx kurulu değil; runtime bağımlılıklarını yükleyin"
            ) from exc
        url = f"https://api.telegram.org/bot{self._bot_token}/getChatAdministrators"
        try:
            response = httpx.get(
                url,
                params={"chat_id": chat_id},
                timeout=self.request_timeout_seconds,
            )
        except Exception as exc:
            raise TelegramUpdateError(
                f"Telegram yönetici sorgusu ağ hatası: {type(exc).__name__}"
            ) from exc
        try:
            body = response.json()
        except Exception as exc:
            raise TelegramUpdateError(
                f"Telegram geçersiz yönetici yanıtı: HTTP {response.status_code}"
            ) from exc
        if response.status_code >= 400 or not body.get("ok"):
            description = str(body.get("description", "getChatAdministrators başarısız"))
            raise TelegramUpdateError(description[:500])
        result = body.get("result")
        if not isinstance(result, list):
            raise TelegramUpdateError("getChatAdministrators result listesi döndürmedi")
        return frozenset(
            int(user_id)
            for item in result
            if isinstance(item, dict)
            and isinstance(item.get("user"), dict)
            and isinstance(user_id := item["user"].get("id"), int)
            and not bool(item["user"].get("is_bot"))
        )
