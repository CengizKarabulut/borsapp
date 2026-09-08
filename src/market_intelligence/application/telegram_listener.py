from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from market_intelligence.application.symbol_commands import SymbolCommandService
from market_intelligence.delivery.telegram.commands import CommandName, TelegramCommandParser
from market_intelligence.delivery.telegram.config import (
    DeliveryMode,
    TelegramSettings,
    TopicKind,
)
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
        envelopes: tuple[OutboxEnvelope, ...],
    ) -> None: ...


@dataclass(frozen=True)
class ListenerBatchResult:
    received: int
    accepted: int
    ignored: int
    ignored_reasons: dict[str, int] = field(default_factory=dict)


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
        ignored_reasons: Counter[str] = Counter()
        for update in updates:
            update_id = update.get("update_id")
            if not isinstance(update_id, int) or update_id < offset:
                ignored += 1
                ignored_reasons["stale_update"] += 1
                continue
            command = self.parser.parse(update, self.settings)
            envelopes: tuple[OutboxEnvelope, ...] = ()
            if command is None:
                ignored += 1
                ignored_reasons[self.parser.rejection_reason(update, self.settings)] += 1
            else:
                if self.settings.delivery_mode is DeliveryMode.LIVE:
                    reply = self.command_service.handle(command)
                    reply_topic_kind = {
                        CommandName.SCAN: TopicKind.SCANS,
                        CommandName.SCANS: TopicKind.SCANS,
                        CommandName.NEWS: TopicKind.NEWS,
                    }.get(command.name, TopicKind.COMMAND)
                    envelopes = tuple(
                        self.router.route(
                            publication_kind=PublicationKind.COMMAND_REPLY,
                            semantic_identity={
                                "update_id": update_id,
                                "message_id": command.message_id,
                                "command": command.name.value,
                                "part": part,
                            },
                            payload={"text": text},
                            reply_topic_kind=reply_topic_kind,
                        )
                        for part, text in enumerate(reply.messages, 1)
                    )
                accepted += 1
            self.repository.commit_update(update_id=update_id, envelopes=envelopes)
            offset = update_id + 1
        malformed = len(received) - len(updates)
        ignored += malformed
        if malformed:
            ignored_reasons["update_id_missing"] += malformed
        return ListenerBatchResult(
            len(received),
            accepted,
            ignored,
            dict(sorted(ignored_reasons.items())),
        )
