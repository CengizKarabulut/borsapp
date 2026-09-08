from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings


@dataclass(frozen=True)
class PendingTelegramMessage:
    outbox_id: str
    semantic_key: str
    chat_id: int
    message_thread_id: int
    payload: dict[str, Any]
    attempt_count: int


class OutboxRepository(Protocol):
    def claim(self, *, limit: int, now: datetime) -> tuple[PendingTelegramMessage, ...]: ...

    def mark_sent(self, *, outbox_id: str, message_id: int, sent_at: datetime) -> None: ...

    def mark_failed(self, *, outbox_id: str, error: str, retry_at: datetime) -> None: ...


class TelegramTransport(Protocol):
    def send(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        payload: dict[str, Any],
    ) -> int: ...


@dataclass(frozen=True)
class PublishBatchResult:
    claimed: int
    sent: int
    failed: int
    skipped_mode: DeliveryMode | None = None
    error_samples: tuple[str, ...] = ()


class TelegramPublisher:
    def __init__(
        self,
        *,
        settings: TelegramSettings,
        repository: OutboxRepository,
        transport: TelegramTransport,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.transport = transport

    def publish_batch(
        self,
        *,
        now: datetime,
        limit: int = 20,
    ) -> PublishBatchResult:
        if self.settings.delivery_mode is not DeliveryMode.LIVE:
            return PublishBatchResult(0, 0, 0, self.settings.delivery_mode)
        messages = self.repository.claim(limit=limit, now=now)
        sent = 0
        failed = 0
        error_samples: list[str] = []
        for item in messages:
            try:
                message_id = self.transport.send(
                    chat_id=item.chat_id,
                    message_thread_id=item.message_thread_id,
                    payload=item.payload,
                )
            except Exception as exc:
                failed += 1
                delay_seconds = min(30 * (2 ** max(item.attempt_count - 1, 0)), 3600)
                safe_error = f"{type(exc).__name__}: {exc}".replace(
                    self.settings.bot_token, "[REDACTED]"
                )[:1000]
                if safe_error not in error_samples and len(error_samples) < 5:
                    error_samples.append(safe_error)
                self.repository.mark_failed(
                    outbox_id=item.outbox_id,
                    error=safe_error,
                    retry_at=now + timedelta(seconds=delay_seconds),
                )
                continue
            self.repository.mark_sent(
                outbox_id=item.outbox_id,
                message_id=message_id,
                sent_at=now,
            )
            sent += 1
        return PublishBatchResult(
            len(messages),
            sent,
            failed,
            error_samples=tuple(error_samples),
        )
