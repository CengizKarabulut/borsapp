from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from market_intelligence.delivery.telegram.commands import CommandName
from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings
from market_intelligence.delivery.telegram.routing import (
    OutboxEnvelope,
    PublicationKind,
    TopicRouter,
)


@dataclass(frozen=True)
class CommandJob:
    job_id: str
    command: CommandName
    symbol: str
    requested_by: int
    requested_topic: int
    attempt_count: int
    instrument_id: str | None = None


@dataclass(frozen=True)
class CommandArtifact:
    report_id: str
    instrument_id: str
    artifact_kind: str
    timeframe: str | None
    bar_time: datetime | None
    summary: str
    storage_uri: str
    content_hash: str


@dataclass(frozen=True)
class CommandJobOutput:
    envelopes: tuple[OutboxEnvelope, ...] = ()
    artifact: CommandArtifact | None = None


class CommandJobRepository(Protocol):
    def claim(self, *, now: datetime) -> CommandJob | None: ...

    def finish(
        self,
        *,
        job: CommandJob,
        finished_at: datetime,
        error_detail: str | None,
        envelopes: tuple[OutboxEnvelope, ...],
        artifact: CommandArtifact | None,
    ) -> None: ...


class CommandJobExecutor(Protocol):
    def __call__(self, job: CommandJob) -> CommandJobOutput | None: ...


@dataclass(frozen=True)
class CommandJobRun:
    claimed: int
    completed: int
    failed: int


class CommandJobRunner:
    def __init__(
        self,
        *,
        settings: TelegramSettings,
        repository: CommandJobRepository,
        executor: CommandJobExecutor,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.executor = executor
        self.router = TopicRouter(settings)

    def run_once(self, *, now: datetime) -> CommandJobRun:
        if self.settings.delivery_mode is not DeliveryMode.LIVE:
            return CommandJobRun(0, 0, 0)
        job = self.repository.claim(now=now)
        if job is None:
            return CommandJobRun(0, 0, 0)
        error: str | None = None
        output = CommandJobOutput()
        try:
            output = self.executor(job) or CommandJobOutput()
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
            output = CommandJobOutput()
        if job.command is CommandName.ANALYSIS:
            success_text = f"{job.symbol} analizi tamamlandı; Analizler konusuna gönderildi."
        elif job.command is CommandName.REPORT:
            success_text = f"{job.symbol} raporu tamamlandı; Raporlar konusuna gönderildi."
        elif job.command is CommandName.FUNDAMENTAL:
            success_text = (
                f"{job.symbol} temel analizi tamamlandı; Analizler konusuna gönderildi."
            )
        elif job.command is CommandName.CHART:
            success_text = f"{job.symbol} grafiği tamamlandı; Grafikler konusuna gönderildi."
        else:
            follow_up = "/taramalar" if job.command is CommandName.SCANS else "/tara"
            success_text = f"{job.symbol} yenilemesi tamamlandı. {follow_up} {job.symbol}"
        status_text = success_text if error is None else (
            f"{job.symbol} {job.command.value} işi başarısız oldu: {type_name(error)}"
        )
        envelope = self.router.route(
            publication_kind=PublicationKind.COMMAND_REPLY,
            semantic_identity={
                "job_id": job.job_id,
                "status": "completed" if error is None else "failed",
            },
            payload={"text": status_text},
            origin_topic_id=job.requested_topic,
        )
        self.repository.finish(
            job=job,
            finished_at=now,
            error_detail=error,
            envelopes=(*output.envelopes, envelope),
            artifact=output.artifact,
        )
        return CommandJobRun(1, int(error is None), int(error is not None))


def type_name(error: str) -> str:
    return error.split(":", 1)[0]
