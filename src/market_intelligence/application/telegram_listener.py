from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from market_intelligence.application.symbol_commands import SymbolCommandService
from market_intelligence.delivery.telegram.commands import TelegramCommandParser
from market_intelligence.delivery.telegram.config import TelegramSettings
from market_intelligence.delivery.telegram.routing import (
    OutboxEnvelope,
    PublicationKind,
    TopicRouter,
)


class TelegramUpdateSource(Protocol):
    def fetch(
        self,
        *,
        offset: int,
        timeout_seconds: int,
    ) -> tuple[dict[str, Any], ...]: ...


class TelegramUpdateRepository(Protocol):
    def next_offset(self) -> int: ...

    def commit_update(
        self,
        *,
        update_id: int,
        envelope: OutboxEnvelope | None,
    ) -> None: ...


@dataclass(frozen=True)
class ListenerBatchResult:
    received: int
    accepted: int
    ignored: int


class TelegramListener:
    def __init__(
        self,
        *,
        settings: TelegramSettings,
        source: TelegramUpdateSource,
        repository: TelegramUpdateRepository,
        command_service: SymbolCommandService,
    ) -> None:
        self.settings = settings
        self.source = source
        self.repository = repository
        self.command_service = command_service
        self.parser = TelegramCommandParser()
        self.router = TopicRouter(settings)

    def run_once(self, *, timeout_seconds: int = 25) -> ListenerBatchResult:
        offset = self.repository.next_offset()
        received = self.source.fetch(offset=offset, timeout_seconds=timeout_seconds)
        updates = sorted(
            (
                item
                for item in received
                if isinstance(item.get("update_id"), int)
            ),
            key=lambda item: item["update_id"],
        )
        accepted = 0
        ignored = 0
        for update in updates:
            update_id = update.get("update_id")
            if not isinstance(update_id, int) or update_id < offset:
                ignored += 1
                continue
            command = self.parser.parse(update, self.settings)
            envelope = None
            if command is None:
                ignored += 1
            else:
                reply = self.command_service.handle(command)
                envelope = self.router.route(
                    publication_kind=PublicationKind.COMMAND_REPLY,
                    semantic_identity={
                        "update_id": update_id,
                        "message_id": command.message_id,
                        "command": command.name.value,
                    },
                    payload={"text": reply.text},
                    origin_topic_id=command.topic_id,
                )
                accepted += 1
            self.repository.commit_update(update_id=update_id, envelope=envelope)
            offset = update_id + 1
        ignored += len(received) - len(updates)
        return ListenerBatchResult(len(received), accepted, ignored)
