from __future__ import annotations

import unittest
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from market_intelligence.application.command_jobs import (
    CommandJob,
    CommandJobRunner,
)
from market_intelligence.delivery.telegram.commands import CommandName
from market_intelligence.delivery.telegram.config import (
    DeliveryMode,
    TelegramSettings,
    TopicKind,
)
from market_intelligence.delivery.telegram.routing import (
    OutboxEnvelope,
    PublicationKind,
)
from market_intelligence.persistence.postgres.command_jobs import (
    PostgresCommandJobRepository,
)
from tests.test_telegram_routing import environment


class FakeRepository:
    def __init__(self, job: CommandJob | None) -> None:
        self.job = job
        self.claims = 0
        self.finished = []

    def claim(self, *, now: datetime) -> CommandJob | None:
        self.claims += 1
        job = self.job
        self.job = None
        return job

    def finish(self, **kwargs) -> None:
        self.finished.append(kwargs)


class FakeTransaction(AbstractContextManager):
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.connection.committed += int(exc_type is None)
        self.connection.rolled_back += int(exc_type is not None)


class FakeCursor(AbstractContextManager):
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.connection.queries.append((query, params))
        if "telegram_outbox" in query and self.connection.fail_outbox:
            raise RuntimeError("outbox unavailable")

    def fetchone(self):
        row = self.connection.claim_row
        self.connection.claim_row = None
        return row


class FakeConnection:
    def __init__(self, claim_row=None, *, fail_outbox: bool = False) -> None:
        self.claim_row = claim_row
        self.fail_outbox = fail_outbox
        self.queries = []
        self.committed = 0
        self.rolled_back = 0

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def job() -> CommandJob:
    return CommandJob("job-1", CommandName.SCAN, "ASELS", 42, 10, 1)


def live_settings() -> TelegramSettings:
    return replace(
        TelegramSettings.from_mapping(environment()),
        delivery_mode=DeliveryMode.LIVE,
    )


class CommandJobRunnerTests(unittest.TestCase):
    def test_success_finishes_with_command_topic_outbox(self) -> None:
        repository = FakeRepository(job())
        executed = []
        result = CommandJobRunner(
            settings=live_settings(),
            repository=repository,
            executor=executed.append,
        ).run_once(now=datetime(2026, 9, 7, tzinfo=UTC))
        self.assertEqual((result.claimed, result.completed, result.failed), (1, 1, 0))
        self.assertEqual(executed, [job()])
        finished = repository.finished[0]
        self.assertIsNone(finished["error_detail"])
        self.assertEqual(finished["envelope"].message_thread_id, 10)
        self.assertIn("tamamlandı", finished["envelope"].payload["text"])

    def test_failure_is_recorded_without_exposing_detail_in_reply(self) -> None:
        repository = FakeRepository(job())

        def fail(_job: CommandJob) -> None:
            raise RuntimeError("sensitive detail")

        result = CommandJobRunner(
            settings=live_settings(),
            repository=repository,
            executor=fail,
        ).run_once(now=datetime(2026, 9, 7, tzinfo=UTC))
        self.assertEqual((result.completed, result.failed), (0, 1))
        finished = repository.finished[0]
        self.assertIn("sensitive detail", finished["error_detail"])
        self.assertNotIn("sensitive detail", finished["envelope"].payload["text"])

    def test_scans_job_points_to_detailed_follow_up_command(self) -> None:
        source = job()
        repository = FakeRepository(replace(source, command=CommandName.SCANS))

        CommandJobRunner(
            settings=live_settings(),
            repository=repository,
            executor=lambda _job: None,
        ).run_once(now=datetime(2026, 9, 7, tzinfo=UTC))

        self.assertIn("/taramalar ASELS", repository.finished[0]["envelope"].payload["text"])

    def test_disabled_mode_does_not_claim_jobs(self) -> None:
        repository = FakeRepository(job())
        settings = TelegramSettings.from_mapping(environment())
        result = CommandJobRunner(
            settings=settings,
            repository=repository,
            executor=lambda _job: None,
        ).run_once(now=datetime(2026, 9, 7, tzinfo=UTC))
        self.assertEqual(result.claimed, 0)
        self.assertEqual(repository.claims, 0)


class PostgresCommandJobRepositoryTests(unittest.TestCase):
    def test_claim_uses_lease_and_maps_job(self) -> None:
        connection = FakeConnection(("job-1", "tara", "asels", 42, 10, 3))
        now = datetime(2026, 9, 7, tzinfo=UTC)

        claimed = PostgresCommandJobRepository(connection).claim(now=now)

        self.assertEqual(claimed, CommandJob("job-1", CommandName.SCAN, "ASELS", 42, 10, 3))
        params = connection.queries[0][1]
        self.assertEqual(params, (now, now, now + timedelta(minutes=15)))
        self.assertEqual(connection.committed, 1)

    def test_finish_commits_job_and_reply_outbox_together(self) -> None:
        connection = FakeConnection()
        envelope = OutboxEnvelope(
            semantic_key="reply-1",
            publication_kind=PublicationKind.COMMAND_REPLY,
            topic_kind=TopicKind.COMMAND,
            chat_id=-100123,
            message_thread_id=10,
            payload={"text": "tamamlandı"},
        )

        PostgresCommandJobRepository(connection).finish(
            job=job(),
            finished_at=datetime(2026, 9, 7, tzinfo=UTC),
            error_detail=None,
            envelope=envelope,
        )

        self.assertEqual(len(connection.queries), 2)
        self.assertIn("UPDATE command_jobs", connection.queries[0][0])
        self.assertIn("telegram_outbox", connection.queries[1][0])
        self.assertEqual(connection.committed, 1)

    def test_outbox_failure_rolls_back_job_completion(self) -> None:
        connection = FakeConnection(fail_outbox=True)
        envelope = OutboxEnvelope(
            semantic_key="reply-1",
            publication_kind=PublicationKind.COMMAND_REPLY,
            topic_kind=TopicKind.COMMAND,
            chat_id=-100123,
            message_thread_id=10,
            payload={"text": "tamamlandı"},
        )

        with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
            PostgresCommandJobRepository(connection).finish(
                job=job(),
                finished_at=datetime(2026, 9, 7, tzinfo=UTC),
                error_detail=None,
                envelope=envelope,
            )

        self.assertEqual(connection.committed, 0)
        self.assertEqual(connection.rolled_back, 1)


if __name__ == "__main__":
    unittest.main()
