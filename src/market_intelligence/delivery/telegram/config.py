from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class TopicKind(StrEnum):
    COMMAND = "command"
    SCANS = "scans"
    ANALYSIS = "analysis"
    CHARTS = "charts"
    NEWS = "news"
    CALENDAR = "calendar"
    REPORTS = "reports"
    SYSTEM = "system"


class DeliveryMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    LIVE = "live"


TOPIC_ENV_KEYS = {
    TopicKind.COMMAND: "TELEGRAM_TOPIC_COMMAND",
    TopicKind.SCANS: "TELEGRAM_TOPIC_SCANS",
    TopicKind.ANALYSIS: "TELEGRAM_TOPIC_ANALYSIS",
    TopicKind.CHARTS: "TELEGRAM_TOPIC_CHARTS",
    TopicKind.NEWS: "TELEGRAM_TOPIC_NEWS",
    TopicKind.CALENDAR: "TELEGRAM_TOPIC_CALENDAR",
    TopicKind.REPORTS: "TELEGRAM_TOPIC_REPORTS",
    TopicKind.SYSTEM: "TELEGRAM_TOPIC_SYSTEM",
}


def _positive_int(raw: str, key: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} sayısal olmalıdır") from exc
    if value <= 0:
        raise ValueError(f"{key} pozitif olmalıdır")
    return value


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str = field(repr=False)
    chat_id: int
    allowed_user_ids: frozenset[int]
    topic_ids: Mapping[TopicKind, int]
    delivery_mode: DeliveryMode = DeliveryMode.DISABLED
    allow_chat_admins: bool = False
    allow_chat_members: bool = False

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> TelegramSettings:
        token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN eksik")
        chat_raw = values.get("TELEGRAM_CHAT_ID", "").strip()
        if not chat_raw:
            raise ValueError("TELEGRAM_CHAT_ID eksik")
        try:
            chat_id = int(chat_raw)
        except ValueError as exc:
            raise ValueError("TELEGRAM_CHAT_ID sayısal olmalıdır") from exc

        allowed_raw = values.get("TELEGRAM_ALLOWED_USERS", "").strip()
        if not allowed_raw:
            raise ValueError("TELEGRAM_ALLOWED_USERS en az bir kullanıcı içermelidir")
        try:
            allowed = frozenset(int(item.strip()) for item in allowed_raw.split(",") if item.strip())
        except ValueError as exc:
            raise ValueError("TELEGRAM_ALLOWED_USERS virgülle ayrılmış sayılar olmalıdır") from exc
        if not allowed:
            raise ValueError("TELEGRAM_ALLOWED_USERS en az bir kullanıcı içermelidir")

        topics: dict[TopicKind, int] = {}
        missing: list[str] = []
        for kind, env_key in TOPIC_ENV_KEYS.items():
            raw = values.get(env_key, "").strip()
            if not raw:
                missing.append(env_key)
            else:
                topics[kind] = _positive_int(raw, env_key)
        if missing:
            raise ValueError("Eksik Telegram topic ayarları: " + ", ".join(missing))
        try:
            delivery_mode = DeliveryMode(
                values.get("DELIVERY_MODE", DeliveryMode.DISABLED.value).strip().casefold()
            )
        except ValueError as exc:
            raise ValueError("DELIVERY_MODE disabled, shadow veya live olmalıdır") from exc
        allow_admins_raw = values.get("TELEGRAM_ALLOW_CHAT_ADMINS", "false").strip().casefold()
        if allow_admins_raw not in {"true", "false"}:
            raise ValueError("TELEGRAM_ALLOW_CHAT_ADMINS true veya false olmalıdır")
        allow_members_raw = values.get("TELEGRAM_ALLOW_CHAT_MEMBERS", "false").strip().casefold()
        if allow_members_raw not in {"true", "false"}:
            raise ValueError("TELEGRAM_ALLOW_CHAT_MEMBERS true veya false olmalıdır")
        return cls(
            token,
            chat_id,
            allowed,
            topics,
            delivery_mode,
            allow_admins_raw == "true",
            allow_members_raw == "true",
        )

    def topic_id(self, kind: TopicKind) -> int:
        try:
            return self.topic_ids[kind]
        except KeyError as exc:
            raise ValueError(f"Telegram topic yapılandırılmamış: {kind}") from exc

    def accepts(self, *, chat_id: int, user_id: int, topic_id: int | None) -> bool:
        # Commands are safe to accept from every topic in the configured forum.
        # Authorization belongs to the chat and user; topic selection is a routing
        # concern.  Restricting ingestion to one topic made valid commands vanish
        # silently when Telegram clients posted them in General or another topic.
        return (
            chat_id == self.chat_id
            and (self.allow_chat_members or user_id in self.allowed_user_ids)
        )
