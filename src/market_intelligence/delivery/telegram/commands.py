from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from market_intelligence.delivery.telegram.config import TelegramSettings, TopicKind


class CommandName(StrEnum):
    SCAN = "tara"
    SCANS = "taramalar"
    ANALYSIS = "analiz"
    EQUITY = "hisse"
    REPORT = "rapor"
    FUNDAMENTAL = "temel"
    CHART = "grafik"
    CHART_HELP = "grafikyardim"
    NEWS = "haber"
    LIST = "liste"
    HISTORY = "gecmis"
    STATUS = "durum"
    IDENTITY = "kimlik"
    HELP = "yardim"


@dataclass(frozen=True)
class IncomingCommand:
    update_id: int
    message_id: int
    user_id: int
    chat_id: int
    topic_id: int
    name: CommandName
    args: tuple[str, ...]


_SYMBOL = re.compile(r"^[A-Z0-9._=-]{1,24}$")
_NO_SYMBOL_COMMANDS = frozenset(
    {
        CommandName.HELP,
        CommandName.CHART_HELP,
        CommandName.LIST,
        CommandName.HISTORY,
        CommandName.STATUS,
        CommandName.IDENTITY,
    }
)


class TelegramCommandParser:
    def rejection_reason(
        self,
        update: dict[str, Any],
        settings: TelegramSettings,
    ) -> str:
        message = update.get("message")
        if not isinstance(message, dict):
            return "message_missing"
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        if not all(isinstance(value, int) for value in (chat_id, user_id)):
            return "context_missing"
        if chat_id != settings.chat_id:
            return "chat_mismatch"
        if user_id not in settings.allowed_user_ids:
            return "user_not_allowed"
        text = str(message.get("text", "")).strip()
        if not text.startswith("/"):
            return "not_a_command"
        parts = text.split()
        command_text = parts[0][1:].split("@", 1)[0].casefold()
        try:
            name = CommandName(command_text)
        except ValueError:
            return "unknown_command"
        args = tuple(part.strip().upper() for part in parts[1:] if part.strip())
        if name not in _NO_SYMBOL_COMMANDS and not args:
            return "symbol_missing"
        if name not in _NO_SYMBOL_COMMANDS and not _SYMBOL.fullmatch(args[0]):
            return "symbol_invalid"
        return "accepted"

    def parse(
        self,
        update: dict[str, Any],
        settings: TelegramSettings,
    ) -> IncomingCommand | None:
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        topic_id = message.get("message_thread_id")
        if not all(isinstance(value, int) for value in (chat_id, user_id)):
            return None
        if not settings.accepts(chat_id=chat_id, user_id=user_id, topic_id=topic_id):
            return None
        if not isinstance(topic_id, int):
            topic_id = settings.topic_id(TopicKind.COMMAND)
        text = str(message.get("text", "")).strip()
        if not text.startswith("/"):
            return None
        parts = text.split()
        command_text = parts[0][1:].split("@", 1)[0].casefold()
        try:
            name = CommandName(command_text)
        except ValueError:
            return None
        args = tuple(part.strip().upper() for part in parts[1:] if part.strip())
        if name not in _NO_SYMBOL_COMMANDS:
            if not args or not _SYMBOL.fullmatch(args[0]):
                return None
        return IncomingCommand(
            update_id=int(update["update_id"]),
            message_id=int(message["message_id"]),
            user_id=user_id,
            chat_id=chat_id,
            topic_id=topic_id,
            name=name,
            args=args,
        )
