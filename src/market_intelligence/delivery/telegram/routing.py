from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from market_intelligence.core.identity import stable_hash
from market_intelligence.delivery.telegram.config import TelegramSettings, TopicKind


class PublicationKind(StrEnum):
    COMMAND_REPLY = "command_reply"
    SCAN_EVENT = "scan_event"
    CONFLUENCE = "confluence"
    ANALYSIS = "analysis"
    CHART = "chart"
    NEWS = "news"
    CALENDAR = "calendar"
    REPORT = "report"
    SYSTEM = "system"


DEFAULT_ROUTES = {
    PublicationKind.SCAN_EVENT: TopicKind.SCANS,
    PublicationKind.CONFLUENCE: TopicKind.SCANS,
    PublicationKind.ANALYSIS: TopicKind.ANALYSIS,
    PublicationKind.CHART: TopicKind.CHARTS,
    PublicationKind.NEWS: TopicKind.NEWS,
    PublicationKind.CALENDAR: TopicKind.CALENDAR,
    PublicationKind.REPORT: TopicKind.REPORTS,
    PublicationKind.SYSTEM: TopicKind.SYSTEM,
}


@dataclass(frozen=True)
class OutboxEnvelope:
    semantic_key: str
    publication_kind: PublicationKind
    topic_kind: TopicKind
    chat_id: int
    message_thread_id: int
    payload: dict[str, Any]


class TopicRouter:
    def __init__(self, settings: TelegramSettings) -> None:
        self.settings = settings

    def route(
        self,
        *,
        publication_kind: PublicationKind,
        semantic_identity: dict[str, Any],
        payload: dict[str, Any],
        origin_topic_id: int | None = None,
    ) -> OutboxEnvelope:
        if publication_kind is PublicationKind.COMMAND_REPLY:
            topic_kind = TopicKind.COMMAND
            topic_id = origin_topic_id or self.settings.topic_id(topic_kind)
        else:
            topic_kind = DEFAULT_ROUTES[publication_kind]
            topic_id = self.settings.topic_id(topic_kind)
        semantic_key = stable_hash(
            {
                "channel": "telegram",
                "publication_kind": publication_kind,
                "semantic_identity": semantic_identity,
                "chat_id": self.settings.chat_id,
                "message_thread_id": topic_id,
            }
        )
        return OutboxEnvelope(
            semantic_key=semantic_key,
            publication_kind=publication_kind,
            topic_kind=topic_kind,
            chat_id=self.settings.chat_id,
            message_thread_id=topic_id,
            payload=dict(payload),
        )
