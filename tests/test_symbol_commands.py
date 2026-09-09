from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.application.symbol_commands import (
    StoredCycle,
    StoredMatch,
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

    def load_recent_matches(self, *, limit: int = 60):
        now = datetime(2026, 9, 8, 12, tzinfo=UTC)
        return (
            StoredMatch("ASELS", "signal.macd_positive_cross", "1h", now, Direction.BULLISH),
        )

    def load_recent_cycles(self, *, limit: int = 10):
        now = datetime(2026, 9, 8, 12, tzinfo=UTC)
        return (StoredCycle("1h", now, "completed", 600, 2, 15),)


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
        self.assertIn("Sinyaller: Eşleşti", reply.text)
        self.assertIn("Teknik taramalar: Eşleşme yok", reply.text)
        self.assertIn("Hareketli ortalama: Henüz veri yok", reply.text)

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
        self.assertIn("Sinyaller: Eşleşti", reply.text)

    def test_force_is_restricted_to_scan_commands(self) -> None:
        queue = FakeQueue()
        reply = SymbolCommandService(FakeStore(snapshot()), queue).handle(
            command(CommandName.NEWS, "ASELS", "--FORCE")
        )
        self.assertIn("yalnız /tara", reply.text)
        self.assertEqual(queue.calls, 0)

    def test_analysis_report_fundamental_and_chart_are_enqueued_as_long_jobs(self) -> None:
        for name in (
            CommandName.ANALYSIS,
            CommandName.EQUITY,
            CommandName.REPORT,
            CommandName.FUNDAMENTAL,
            CommandName.CHART,
        ):
            with self.subTest(name=name):
                queue = FakeQueue()
                store = FakeStore(snapshot())
                reply = SymbolCommandService(store, queue).handle(
                    command(name, "ASELS")
                )
                self.assertEqual(store.calls, 0)
                self.assertEqual(queue.calls, 1)
                self.assertEqual(reply.queued_job_id, "job-1")

    def test_status_identity_and_chart_help_do_not_require_a_symbol(self) -> None:
        service = SymbolCommandService(
            FakeStore(snapshot()),
            clock=lambda: datetime(2026, 9, 8, 4, 15, tzinfo=ZoneInfo("Europe/Istanbul")),
        )
        status = service.handle(command(CommandName.STATUS))
        identity = service.handle(command(CommandName.IDENTITY))
        chart_help = service.handle(command(CommandName.CHART_HELP))

        self.assertIn("Borsapp çalışıyor", status.text)
        self.assertIn("Kullanıcı ID: 42", identity.text)
        self.assertIn("TELEGRAM_ALLOWED_USERS", identity.text)
        self.assertIn("/grafik ASELS", chart_help.text)

    def test_list_and_history_read_canonical_scan_store(self) -> None:
        service = SymbolCommandService(
            FakeStore(snapshot()),
            clock=lambda: datetime(2026, 9, 8, 15, tzinfo=ZoneInfo("Europe/Istanbul")),
        )

        recent = service.handle(command(CommandName.LIST))
        history = service.handle(command(CommandName.HISTORY))

        self.assertIn("ASELS", recent.text)
        self.assertIn("MACD pozitif kesişim", recent.text)
        self.assertIn("başarılı 600", history.text)
        self.assertIn("eşleşme 15", history.text)

    def test_news_reply_includes_source_url(self) -> None:
        reply = SymbolCommandService(FakeStore(snapshot())).handle(
            command(CommandName.NEWS, "ASELS")
        )
        self.assertIn("https://example.com", reply.text)

    def test_news_returns_all_kap_from_local_day_and_only_three_older(self) -> None:
        timezone = ZoneInfo("Europe/Istanbul")
        now = datetime(2026, 9, 8, 15, 30, tzinfo=timezone)
        source = snapshot()
        today_items = tuple(
            StoredNews(
                f"Bugünün KAP bildirimi {index}",
                now - timedelta(hours=index),
                f"https://example.com/today/{index}",
            )
            for index in range(1, 6)
        )
        older_items = tuple(
            StoredNews(
                f"Eski KAP bildirimi {index}",
                now - timedelta(days=index),
                f"https://example.com/old/{index}",
            )
            for index in range(1, 6)
        )
        non_kap = StoredNews("Başka kaynak", now, source="other")
        news_snapshot = SymbolSnapshot(
            source.instrument_id,
            source.symbol,
            news=(*today_items, *older_items, non_kap),
        )

        reply = SymbolCommandService(
            FakeStore(news_snapshot),
            clock=lambda: now,
        ).handle(command(CommandName.NEWS, "ASELS"))
        combined = "\n".join(reply.messages)

        self.assertIn("bugün 5 KAP · önceki 3 KAP", combined)
        for index in range(1, 6):
            self.assertIn(f"Bugünün KAP bildirimi {index}", combined)
        for index in range(1, 4):
            self.assertIn(f"Eski KAP bildirimi {index}", combined)
        self.assertNotIn("Eski KAP bildirimi 4", combined)
        self.assertNotIn("Eski KAP bildirimi 5", combined)
        self.assertNotIn("Başka kaynak", combined)

    def test_news_chunks_preserve_all_selected_disclosures(self) -> None:
        timezone = ZoneInfo("Europe/Istanbul")
        now = datetime(2026, 9, 8, 15, 30, tzinfo=timezone)
        source = snapshot()
        items = tuple(
            StoredNews(
                f"KAP-{index:02d}-" + ("X" * 700),
                now - timedelta(minutes=index),
                f"https://example.com/{index}",
            )
            for index in range(12)
        )
        news_snapshot = SymbolSnapshot(source.instrument_id, source.symbol, news=items)

        reply = SymbolCommandService(
            FakeStore(news_snapshot),
            clock=lambda: now,
        ).handle(command(CommandName.NEWS, "ASELS"))
        combined = "\n".join(reply.messages)

        self.assertGreater(len(reply.messages), 1)
        self.assertTrue(all(len(message) <= 3900 for message in reply.messages))
        for index in range(12):
            self.assertIn(f"KAP-{index:02d}-", combined)


if __name__ == "__main__":
    unittest.main()
