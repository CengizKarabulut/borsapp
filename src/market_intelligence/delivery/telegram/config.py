from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
    bot_token: str
    chat_id: int
    allowed_user_ids: frozenset[int]
    topic_ids: Mapping[TopicKind, int]

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
        return cls(token, chat_id, allowed, topics)

    def topic_id(self, kind: TopicKind) -> int:
        try:
            return self.topic_ids[kind]
        except KeyError as exc:
            raise ValueError(f"Telegram topic yapılandırılmamış: {kind}") from exc

    def accepts(self, *, chat_id: int, user_id: int, topic_id: int | None) -> bool:
        return (
            chat_id == self.chat_id
            and user_id in self.allowed_user_ids
            and topic_id == self.topic_id(TopicKind.COMMAND)
        )
