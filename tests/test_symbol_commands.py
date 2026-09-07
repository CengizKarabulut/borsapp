from __future__ import annotations

import unittest
from datetime import UTC, datetime

from market_intelligence.application.symbol_commands import (
    StoredNews,
    StoredScannerResult,
    SymbolCommandService,
    SymbolSnapshot,
)
from market_intelligence.core.enums import Direction, EvaluationStatus
from market_intelligence.delivery.telegram.commands import CommandName, IncomingCommand


class FakeStore:
    def __init__(self, snapshot: SymbolSnapshot | None) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def load_symbol(self, symbol: str) -> SymbolSnapshot | None:
        self.calls += 1
        return self.snapshot


class FakeQueue:
    def __init__(self) -> None:
        self.calls = 0

    def enqueue(self, **kwargs) -> str:
        self.calls += 1
        return "job-1"


def command(name: CommandName, *args: str) -> IncomingCommand:
    return IncomingCommand(
        update_id=1,
        message_id=2,
        user_id=42,
        chat_id=-100123,
        topic_id=10,
        name=name,
        args=tuple(args),
    )


def snapshot() -> SymbolSnapshot:
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    return SymbolSnapshot(
        instrument_id="instrument-1",
        symbol="ASELS",
        results=(
            StoredScannerResult(
                scanner_id="signal.macd_positive_cross",
                family="signal",
                timeframe="1h",
                bar_time=now,
                status=EvaluationStatus.MATCH,
                direction=Direction.BULLISH,
            ),
            StoredScannerResult(
                scanner_id="technical.volume_spike",
                family="technical",
                timeframe="1h",
                bar_time=now,
                status=EvaluationStatus.NO_MATCH,
            ),
        ),
        news=(StoredNews("Yeni sözleşme", now, "https://example.com"),),
    )


class SymbolCommandServiceTests(unittest.TestCase):
    def test_tara_reads_store_without_recalculation(self) -> None:
        store = FakeStore(snapshot())
        reply = SymbolCommandService(store).handle(command(CommandName.SCAN, "ASELS"))
        self.assertEqual(store.calls, 1)
        self.assertIn("SIGNAL: match", reply.text)
        self.assertIn("TECHNICAL: no_match", reply.text)
        self.assertIn("MA: veri_yok", reply.text)

    def test_force_only_enqueues_long_job(self) -> None:
        store = FakeStore(snapshot())
        queue = FakeQueue()
        reply = SymbolCommandService(store, queue).handle(
            command(CommandName.SCAN, "ASELS", "--FORCE")
        )
        self.assertEqual(store.calls, 0)
        self.assertEqual(queue.calls, 1)
        self.assertEqual(reply.queued_job_id, "job-1")

    def test_missing_symbol_does_not_implicitly_recalculate(self) -> None:
        reply = SymbolCommandService(FakeStore(None)).handle(
            command(CommandName.SCAN, "YOK")
        )
        self.assertIn("--force", reply.text)

    def test_overview_uses_strongest_status_in_each_family(self) -> None:
        source = snapshot()
        mixed = SymbolSnapshot(
            source.instrument_id,
            source.symbol,
            results=(
                StoredScannerResult(
                    "signal.a",
                    "signal",
                    "1h",
                    source.results[0].bar_time,
                    EvaluationStatus.NO_MATCH,
                ),
                StoredScannerResult(
                    "signal.b",
                    "signal",
                    "4h",
                    source.results[0].bar_time,
                    EvaluationStatus.MATCH,
                ),
            ),
        )
        reply = SymbolCommandService(FakeStore(mixed)).handle(
            command(CommandName.SCAN, "ASELS")
        )
        self.assertIn("SIGNAL: match", reply.text)

    def test_force_is_restricted_to_scan_commands(self) -> None:
        queue = FakeQueue()
        reply = SymbolCommandService(FakeStore(snapshot()), queue).handle(
            command(CommandName.NEWS, "ASELS", "--FORCE")
        )
        self.assertIn("yalnız /tara", reply.text)
        self.assertEqual(queue.calls, 0)

    def test_news_reply_includes_source_url(self) -> None:
        reply = SymbolCommandService(FakeStore(snapshot())).handle(
            command(CommandName.NEWS, "ASELS")
        )
        self.assertIn("https://example.com", reply.text)


if __name__ == "__main__":
    unittest.main()
