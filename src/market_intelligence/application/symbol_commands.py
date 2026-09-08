from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from market_intelligence.core.enums import Direction, EvaluationStatus
from market_intelligence.delivery.telegram.commands import CommandName, IncomingCommand


@dataclass(frozen=True)
class StoredScannerResult:
    scanner_id: str
    family: str
    timeframe: str
    bar_time: datetime
    status: EvaluationStatus
    direction: Direction | None = None
    summary: str = ""


@dataclass(frozen=True)
class StoredArtifact:
    kind: str
    summary: str
    uri: str | None
    created_at: datetime


@dataclass(frozen=True)
class StoredNews:
    headline: str
    published_at: datetime
    url: str | None = None
    source: str = "kap"


@dataclass(frozen=True)
class SymbolSnapshot:
    instrument_id: str
    symbol: str
    results: tuple[StoredScannerResult, ...] = ()
    artifacts: tuple[StoredArtifact, ...] = ()
    news: tuple[StoredNews, ...] = ()


class SymbolReadStore(Protocol):
    def load_symbol(self, symbol: str) -> SymbolSnapshot | None: ...


class LongJobQueue(Protocol):
    def enqueue(
        self,
        *,
        command: CommandName,
        symbol: str,
        requested_by: int,
        requested_topic: int,
    ) -> str: ...


@dataclass(frozen=True)
class CommandReply:
    text: str
    queued_job_id: str | None = None
    additional_texts: tuple[str, ...] = ()

    @property
    def messages(self) -> tuple[str, ...]:
        return (self.text, *self.additional_texts)


class SymbolCommandService:
    """Read scheduled results. Recalculation is only an explicit queued job."""

    def __init__(
        self,
        store: SymbolReadStore,
        job_queue: LongJobQueue | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.job_queue = job_queue
        self.clock = clock or (lambda: datetime.now(UTC))

    def handle(self, command: IncomingCommand) -> CommandReply:
        if command.name is CommandName.HELP:
            return CommandReply(
                "Komutlar: /tara SYMBOL, /taramalar SYMBOL, /analiz SYMBOL, "
                "/grafik SYMBOL, /haber SYMBOL. Yenileme: /tara SYMBOL --force"
            )
        symbol = command.args[0]
        force = any(argument.casefold() == "--force" for argument in command.args[1:])
        if force:
            if command.name not in {CommandName.SCAN, CommandName.SCANS}:
                return CommandReply("--force yalnız /tara ve /taramalar için kullanılabilir.")
            if self.job_queue is None:
                return CommandReply("Uzun iş kuyruğu bu ortamda etkin değil.")
            job_id = self.job_queue.enqueue(
                command=command.name,
                symbol=symbol,
                requested_by=command.user_id,
                requested_topic=command.topic_id,
            )
            return CommandReply(
                f"{symbol} yenilemesi kuyruğa alındı. İş: {job_id}",
                queued_job_id=job_id,
            )

        snapshot = self.store.load_symbol(symbol)
        if snapshot is None:
            return CommandReply(
                f"{symbol} için saklanmış sonuç bulunamadı. "
                f"Yeniden hesaplama için /tara {symbol} --force kullanabilirsiniz."
            )
        if command.name is CommandName.SCAN:
            return CommandReply(self._overview(snapshot))
        if command.name is CommandName.SCANS:
            return CommandReply(self._scans(snapshot))
        if command.name is CommandName.NEWS:
            chunks = self._news(snapshot)
            return CommandReply(chunks[0], additional_texts=chunks[1:])
        artifact_kind = "analysis" if command.name is CommandName.ANALYSIS else "chart"
        return CommandReply(self._artifact(snapshot, artifact_kind))

    @staticmethod
    def _overview(snapshot: SymbolSnapshot) -> str:
        priorities = {
            EvaluationStatus.NO_MATCH: 0,
            EvaluationStatus.UNKNOWN: 1,
            EvaluationStatus.MATCH: 2,
        }
        family_status: dict[str, EvaluationStatus] = {}
        for result in snapshot.results:
            current = family_status.get(result.family)
            if current is None or priorities[result.status] > priorities[current]:
                family_status[result.family] = result.status
        lines = [f"{snapshot.symbol} · saklanmış son durum"]
        for family in ("signal", "technical", "ma"):
            status = family_status.get(family)
            lines.append(f"{family.upper()}: {status.value if status else 'veri_yok'}")
        lines.append(f"HABER: {len(snapshot.news)} kayıt")
        return "\n".join(lines)

    @staticmethod
    def _scans(snapshot: SymbolSnapshot) -> str:
        if not snapshot.results:
            return f"{snapshot.symbol} için saklanmış tarama sonucu yok."
        lines = [f"{snapshot.symbol} · taramalar"]
        for result in snapshot.results:
            direction = f" · {result.direction.value}" if result.direction else ""
            lines.append(
                f"- {result.scanner_id} · {result.timeframe} · "
                f"{result.status.value}{direction} · {result.bar_time.isoformat()}"
            )
        return "\n".join(lines)

    @staticmethod
    def _artifact(snapshot: SymbolSnapshot, kind: str) -> str:
        matches = sorted(
            (artifact for artifact in snapshot.artifacts if artifact.kind == kind),
            key=lambda artifact: artifact.created_at,
            reverse=True,
        )
        if not matches:
            return f"{snapshot.symbol} için saklanmış {kind} çıktısı yok."
        artifact = matches[0]
        suffix = f"\n{artifact.uri}" if artifact.uri else ""
        return f"{snapshot.symbol} · {artifact.summary}{suffix}"

    def _news(self, snapshot: SymbolSnapshot) -> tuple[str, ...]:
        kap_items = sorted(
            (item for item in snapshot.news if item.source == "kap"),
            key=lambda news: news.published_at,
            reverse=True,
        )
        if not kap_items:
            return (f"{snapshot.symbol} için saklanmış KAP bildirimi yok.",)
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Komut saati timezone-aware olmalıdır")
        today = now.date()
        today_items = [
            item
            for item in kap_items
            if item.published_at.astimezone(now.tzinfo).date() == today
        ]
        previous_items = [
            item
            for item in kap_items
            if item.published_at.astimezone(now.tzinfo).date() < today
        ][:3]
        selected = (*today_items, *previous_items)
        if not selected:
            return (f"{snapshot.symbol} için bugüne kadar saklanmış KAP bildirimi yok.",)
        header = (
            f"{snapshot.symbol} · bugün {len(today_items)} KAP"
            f" · önceki {len(previous_items)} KAP"
        )
        entries = []
        for item in selected:
            timestamp = item.published_at.astimezone(now.tzinfo).strftime("%d.%m.%Y %H:%M")
            entry = f"- {timestamp} · {item.headline}"
            if item.url:
                entry += f"\n  {item.url}"
            entries.append(entry)
        return self._chunk_lines(header, entries)

    @staticmethod
    def _chunk_lines(
        header: str,
        entries: list[str],
        *,
        limit: int = 3900,
    ) -> tuple[str, ...]:
        chunks: list[str] = []
        current = header
        for entry in entries:
            candidate = f"{current}\n{entry}"
            if len(candidate) <= limit:
                current = candidate
                continue
            chunks.append(current)
            current = f"{header} · devam\n{entry}"
        chunks.append(current)
        return tuple(chunks)
