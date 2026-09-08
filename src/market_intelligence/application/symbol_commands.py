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
class StoredMatch:
    symbol: str
    scanner_id: str
    timeframe: str
    bar_time: datetime
    direction: Direction


@dataclass(frozen=True)
class StoredCycle:
    timeframe: str
    bar_time: datetime
    status: str
    successful: int
    failed: int
    matches: int


@dataclass(frozen=True)
class SymbolSnapshot:
    instrument_id: str
    symbol: str
    results: tuple[StoredScannerResult, ...] = ()
    artifacts: tuple[StoredArtifact, ...] = ()
    news: tuple[StoredNews, ...] = ()


class SymbolReadStore(Protocol):
    def load_symbol(self, symbol: str) -> SymbolSnapshot | None: ...

    def load_recent_matches(self, *, limit: int = 60) -> tuple[StoredMatch, ...]: ...

    def load_recent_cycles(self, *, limit: int = 10) -> tuple[StoredCycle, ...]: ...


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
                "Komutlar:\n"
                "/tara SEMBOL — son birleşik durum\n"
                "/taramalar SEMBOL — tüm tarama ayrıntıları\n"
                "/analiz SEMBOL veya /rapor SEMBOL — kapsamlı araştırma\n"
                "/temel SEMBOL — temel analiz kartı\n"
                "/grafik SEMBOL — teknik gösterge grafiği\n"
                "/haber SEMBOL — bugünün tüm KAP'ları + önceki 3 KAP\n"
                "/liste — son eşleşen BIST taramaları\n"
                "/gecmis — son tarama döngüleri\n"
                "/durum — bot çalışma durumu\n"
                "/grafikyardim — grafik açıklaması\n"
                "/tara SEMBOL --force — verileri ve MA seviyelerini yenile"
            )
        if command.name is CommandName.LIST:
            return CommandReply(self._list())
        if command.name is CommandName.HISTORY:
            return CommandReply(self._history())
        if command.name is CommandName.STATUS:
            now = self._now()
            return CommandReply(
                "🤖 Borsapp çalışıyor\n"
                f"Saat: {now.strftime('%d.%m.%Y %H:%M')} (Türkiye)\n"
                "Komut alımı: etkin\n"
                "Veri modeli: saklanmış sonuç + açıkça istenen yenileme"
            )
        if command.name is CommandName.CHART_HELP:
            return CommandReply(
                "Grafik kullanımı: /grafik ASELS\n"
                "Günlük fiyat üzerinde trend, momentum, volatilite ve hacim "
                "göstergelerini tek görselde üretir; sonuç Grafikler konusuna gelir."
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

        if command.name in {
            CommandName.ANALYSIS,
            CommandName.REPORT,
            CommandName.FUNDAMENTAL,
            CommandName.CHART,
        }:
            if self.job_queue is None:
                return CommandReply("Uzun iş kuyruğu bu ortamda etkin değil.")
            job_id = self.job_queue.enqueue(
                command=command.name,
                symbol=symbol,
                requested_by=command.user_id,
                requested_topic=command.topic_id,
            )
            output_name = {
                CommandName.ANALYSIS: "araştırma analizi",
                CommandName.REPORT: "araştırma raporu",
                CommandName.FUNDAMENTAL: "temel analiz kartı",
                CommandName.CHART: "grafiği",
            }[command.name]
            return CommandReply(
                f"{symbol} {output_name} hazırlanmak üzere kuyruğa alındı. İş: {job_id}",
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
        raise ValueError(f"Desteklenmeyen komut: {command.name.value}")

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
        labels = {
            "signal": "Sinyaller",
            "technical": "Teknik taramalar",
            "ma": "Hareketli ortalama",
        }
        lines = [f"{snapshot.symbol} · son saklanmış durum"]
        for family in ("signal", "technical", "ma"):
            status = family_status.get(family)
            rendered = _status_label(status) if status else "Henüz veri yok"
            lines.append(f"{labels[family]}: {rendered}")
        lines.append(f"KAP bildirimleri: {len(snapshot.news)} kayıt")
        return "\n".join(lines)

    def _scans(self, snapshot: SymbolSnapshot) -> str:
        if not snapshot.results:
            return f"{snapshot.symbol} için saklanmış tarama sonucu yok."
        now = self._now()
        lines = [f"{snapshot.symbol} · tarama ayrıntıları (Türkiye saati)"]
        for result in snapshot.results:
            direction = f" · {_direction_label(result.direction)}" if result.direction else ""
            scanner_name = _SCANNER_LABELS.get(result.scanner_id, result.scanner_id)
            bar_time = result.bar_time.astimezone(now.tzinfo).strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"- {scanner_name} · {result.timeframe} · "
                f"{_status_label(result.status)}{direction} · {bar_time}"
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
        now = self._now()
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

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Komut saati timezone-aware olmalıdır")
        return now

    def _list(self) -> str:
        matches = self.store.load_recent_matches(limit=60)
        if not matches:
            return "Henüz eşleşen saklanmış BIST taraması yok."
        timezone = self._now().tzinfo
        lines = ["Son eşleşen BIST taramaları"]
        for item in matches:
            scanner = _SCANNER_LABELS.get(item.scanner_id, item.scanner_id)
            stamp = item.bar_time.astimezone(timezone).strftime("%d.%m %H:%M")
            lines.append(
                f"- {item.symbol} · {scanner} · {item.timeframe} · "
                f"{_direction_label(item.direction)} · {stamp}"
            )
        return "\n".join(lines)[:3900]

    def _history(self) -> str:
        cycles = self.store.load_recent_cycles(limit=10)
        if not cycles:
            return "Henüz tamamlanmış tarama döngüsü yok."
        timezone = self._now().tzinfo
        lines = ["Son tarama döngüleri"]
        for item in cycles:
            stamp = item.bar_time.astimezone(timezone).strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"- {stamp} · {item.timeframe} · {item.status} · "
                f"başarılı {item.successful}, hata {item.failed}, eşleşme {item.matches}"
            )
        return "\n".join(lines)

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


_SCANNER_LABELS = {
    "ma.near_zone": "MA destek/direnç yakınlığı",
    "signal.ema_trend_volume": "EMA trend + hacim",
    "signal.macd_positive_cross": "MACD pozitif kesişim",
    "signal.rsi_macd_volume": "RSI + MACD + hacim",
    "signal.rsi_momentum_volume": "RSI momentum + hacim",
    "signal.sma_macd_volume": "SMA + MACD + hacim",
    "signal.smi_macd_early": "SMI + MACD erken sinyal",
    "signal.smi_macd_full": "SMI + MACD tam sinyal",
    "signal.smi_macd_positive": "SMI + MACD pozitif",
    "signal.smi_macd_positive_volume_confirmed": "SMI + MACD + hacim onayı",
    "technical.volume_spike": "Hacim artışı",
}


def _status_label(status: EvaluationStatus) -> str:
    return {
        EvaluationStatus.MATCH: "Eşleşti",
        EvaluationStatus.NO_MATCH: "Eşleşme yok",
        EvaluationStatus.UNKNOWN: "Veri yetersiz",
    }[status]


def _direction_label(direction: Direction) -> str:
    return {
        Direction.BULLISH: "Yükseliş",
        Direction.BEARISH: "Düşüş",
        Direction.NEUTRAL: "Nötr",
        Direction.MIXED: "Karışık",
    }[direction]
