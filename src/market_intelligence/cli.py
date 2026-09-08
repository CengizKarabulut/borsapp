from __future__ import annotations

import argparse
import base64
import os
import signal
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import FrameType

from market_intelligence.application.command_jobs import (
    CommandArtifact,
    CommandJob,
    CommandJobOutput,
    CommandJobRunner,
)
from market_intelligence.application.equity_reports import EquityReportService
from market_intelligence.application.ingestion import IngestionRequest, IngestionService
from market_intelligence.application.news_ingestion import NewsIngestionService
from market_intelligence.application.scan_frame import ScanFrameCoordinator
from market_intelligence.application.scheduled_scan import (
    ScheduledScanRequest,
    ScheduledScanService,
)
from market_intelligence.application.symbol_commands import SymbolCommandService
from market_intelligence.application.telegram_listener import TelegramListener
from market_intelligence.compat.legacy_suite import (
    generate_and_send_chart,
)
from market_intelligence.core.timeframes import Timeframe, parse_timeframe
from market_intelligence.delivery.telegram.commands import CommandName, IncomingCommand
from market_intelligence.delivery.telegram.config import DeliveryMode, TopicKind
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.delivery.telegram.publisher import TelegramPublisher
from market_intelligence.delivery.telegram.routing import PublicationKind, TopicRouter
from market_intelligence.delivery.telegram.updates import HttpxTelegramUpdateSource
from market_intelligence.features.decision import DecisionPanelV645Provider
from market_intelligence.features.ma import QualifiedMaResearchProvider
from market_intelligence.features.momentum import (
    LegacyRsi7Provider,
    LegacyRsi14Provider,
    MacdProvider,
    RsiProvider,
    SmiProvider,
)
from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.features.research import ResearchTechnicalSnapshotProvider
from market_intelligence.features.technical import TechnicalMarketContextProvider
from market_intelligence.features.trend import (
    InclusiveVolumeSma10Provider,
    InclusiveVolumeSma20Provider,
    LegacyTrendMaProvider,
)
from market_intelligence.features.volatility import WilderAtr14Provider
from market_intelligence.features.volume import RelativeVolume20Provider
from market_intelligence.fundamentals.presentation import fundamental_message
from market_intelligence.fundamentals.providers import (
    BorsapyKapFinancialProvider,
    FinancialProviderChain,
    YFinanceFinancialProvider,
)
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.adapters.borsapy_universe import (
    BorsapyBistUniverseProvider,
)
from market_intelligence.market_data.adapters.fallback import FallbackMarketDataProvider
from market_intelligence.market_data.adapters.yfinance import YFinanceBistProvider
from market_intelligence.market_data.universe import (
    build_universe_sync_plan,
    validate_universe_sync_plan,
)
from market_intelligence.news.kap import KapDisclosureProvider
from market_intelligence.news.legacy_general import (
    SUPPORTED_SOURCES,
    LegacyGeneralNewsProvider,
)
from market_intelligence.operations.doctor import inspect_runtime
from market_intelligence.persistence.postgres.command_jobs import (
    PostgresCommandJobRepository,
)
from market_intelligence.persistence.postgres.confluence import PostgresConfluenceStore
from market_intelligence.persistence.postgres.ma_research import (
    PostgresMaQualificationSource,
    PostgresMaResearchStore,
)
from market_intelligence.persistence.postgres.migrations import (
    apply_migrations,
    migration_status,
)
from market_intelligence.persistence.postgres.news import PostgresNewsStore
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository
from market_intelligence.persistence.postgres.outcomes import PostgresOutcomeStore
from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.persistence.postgres.scan_store import PostgresScanStore
from market_intelligence.persistence.postgres.shadow import PostgresShadowStore
from market_intelligence.persistence.postgres.snapshots import PostgresSnapshotStore
from market_intelligence.persistence.postgres.state_store import PostgresStateStore
from market_intelligence.persistence.postgres.symbol_commands import (
    PostgresLongJobQueue,
    PostgresSymbolReadStore,
)
from market_intelligence.persistence.postgres.telegram_updates import (
    PostgresTelegramUpdateRepository,
)
from market_intelligence.research.equity_report import analysis_message
from market_intelligence.research.ma_levels import research_ma_levels
from market_intelligence.research.outcomes import OutcomeWindow, measure
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scheduling.xist import ExchangeCalendarsXist, ScheduledBarPlanner
from market_intelligence.settings import ApplicationSettings, merged_environment
from market_intelligence.shadow.recorder import ShadowRecorder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="borsapp",
        description="borsapp Market Intelligence runtime araçları",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="İsteğe bağlı .env yolu; process environment değerleri önceliklidir.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("config-check", help="DB ve Telegram ayarlarını doğrula")

    doctor = subparsers.add_parser(
        "doctor",
        help="PostgreSQL, migration, BIST evreni, tarama ve outbox sağlığını denetle",
    )
    doctor.add_argument("--directory", type=Path, default=Path("db/postgres"))
    doctor.add_argument("--max-cycle-age-hours", type=float, default=48.0)
    doctor.add_argument("--strict-runtime", action="store_true")

    init = subparsers.add_parser(
        "db-init",
        help="Geriye uyumlu alias: bekleyen PostgreSQL migration'larını uygula",
    )
    init.add_argument("--directory", type=Path, default=Path("db/postgres"))

    migrate = subparsers.add_parser(
        "db-migrate",
        help="Bekleyen PostgreSQL migration'larını sırayla uygula",
    )
    migrate.add_argument("--directory", type=Path, default=Path("db/postgres"))
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument(
        "--baseline",
        help="Mevcut şemayı belirtilen migration sürümüne kadar uygulanmış say.",
    )

    version = subparsers.add_parser(
        "db-version",
        help="Uygulanmış ve bekleyen PostgreSQL migration sürümlerini göster",
    )
    version.add_argument("--directory", type=Path, default=Path("db/postgres"))

    shadow_report = subparsers.add_parser(
        "shadow-report",
        help="Kalıcı legacy/new karşılaştırmalarını scanner ve timeframe bazında raporla",
    )
    shadow_report.add_argument("--days", type=int, default=30)
    shadow_report.add_argument("--scanner")
    shadow_report.add_argument("--timeframe")

    shadow_gate = subparsers.add_parser(
        "shadow-gate",
        help="Bir scanner/timeframe parity eşiğini karşılamıyorsa başarısız dön",
    )
    shadow_gate.add_argument("--scanner", required=True)
    shadow_gate.add_argument("--timeframe", required=True)
    shadow_gate.add_argument("--days", type=int, default=30)
    shadow_gate.add_argument("--min-samples", type=int, default=200)
    shadow_gate.add_argument("--min-agreement", type=float, default=0.995)

    outcomes_backfill = subparsers.add_parser(
        "outcomes-backfill",
        help="Kapanmış event ufukları için idempotent sonuç ölçümü üret",
    )
    outcomes_backfill.add_argument("--horizon", default="5,10,20")
    outcomes_backfill.add_argument("--days", type=int, default=90)
    outcomes_backfill.add_argument("--scanner")

    outcomes_report = subparsers.add_parser(
        "outcomes-report",
        help="Scanner/timeframe/ufuk bazında geçmiş sonuçları raporla",
    )
    outcomes_report.add_argument("--days", type=int, default=90)
    outcomes_report.add_argument("--min-samples", type=int, default=30)

    once = subparsers.add_parser(
        "publisher-once",
        help="Telegram outbox'tan tek güvenli batch işle",
    )
    once.add_argument("--limit", type=int, default=20)

    loop = subparsers.add_parser(
        "publisher-loop",
        help="Tek merkezi Telegram publisher döngüsünü çalıştır",
    )
    loop.add_argument("--limit", type=int, default=20)
    loop.add_argument("--interval", type=float, default=2.0)

    listener_once = subparsers.add_parser(
        "listener-once",
        help="Telegram komut update'lerini bir kez al ve outbox'a yaz",
    )
    listener_once.add_argument("--timeout", type=int, default=0)

    listener_loop = subparsers.add_parser(
        "listener-loop",
        help="Tek merkezi Telegram komut listener'ını çalıştır",
    )
    listener_loop.add_argument("--timeout", type=int, default=25)

    register = subparsers.add_parser(
        "instrument-register",
        help="Canonical sembolü ve borsapy eşlemesini kaydet",
    )
    register.add_argument("symbol")
    register.add_argument("--provider-symbol")
    register.add_argument("--universe", default="BIST_ALL")

    universe_sync = subparsers.add_parser(
        "universe-sync",
        help="Borsapy XUTUM bileşenlerini BIST_ALL evreniyle güvenli eşitle",
    )
    universe_sync.add_argument("--universe", default="BIST_ALL")
    universe_sync.add_argument(
        "--apply",
        action="store_true",
        help="Önizlenen değişiklikleri atomik olarak uygula.",
    )

    research_symbol = subparsers.add_parser(
        "ma-research-symbol",
        help="Bir sembolün gözlemsel MA seviyelerini canonical veriyle üret",
    )
    research_symbol.add_argument("symbol")
    research_symbol.add_argument("--timeframe", default="1d")
    research_symbol.add_argument("--bars", type=int, default=1000)

    research_universe = subparsers.add_parser(
        "ma-research-universe",
        help="BIST_ALL için MA Research seviyelerini yenile",
    )
    research_universe.add_argument("--universe", default="BIST_ALL")
    research_universe.add_argument("--timeframe", default="1d")
    research_universe.add_argument("--bars", type=int, default=1000)
    universe_sync.add_argument(
        "--allow-large-removal",
        action="store_true",
        help="Yüzde 10'dan büyük üyelik daralmasını bilinçli olarak onayla.",
    )

    scan = subparsers.add_parser(
        "scan-symbol",
        help="Bir sembolü tüm uygun scanner aileleriyle çalıştır",
    )
    scan.add_argument("symbol")
    scan.add_argument("--timeframe", default="1h")
    scan.add_argument("--bars", type=int, default=320)
    scan.add_argument("--scanners", type=Path, default=Path("config/scanners.toml"))
    scan.add_argument(
        "--notify",
        action="store_true",
        help="Yalnız DELIVERY_MODE=live ise uygun finding'leri outbox'a ekler.",
    )

    due = subparsers.add_parser(
        "scan-due",
        help="XIST takvimi ve watermark'a göre zamanı gelen universe taramalarını çalıştır",
    )
    due.add_argument("--timeframe", default="1h")
    due.add_argument("--universe", default="BIST_ALL")
    due.add_argument("--bars", type=int, default=320)
    due.add_argument("--lookback-days", type=int, default=7)
    due.add_argument("--scanners", type=Path, default=Path("config/scanners.toml"))
    due.add_argument("--notify", action="store_true")

    worker = subparsers.add_parser(
        "scan-worker",
        help="Zamanı gelen timeframe'leri sürekli watermark kontrollü çalıştır",
    )
    worker.add_argument(
        "--timeframes",
        default="15m,30m,45m,1h,2h,4h,1d",
    )
    worker.add_argument("--universe", default="BIST_ALL")
    worker.add_argument("--bars", type=int, default=320)
    worker.add_argument("--lookback-days", type=int, default=7)
    worker.add_argument("--poll-seconds", type=float, default=60.0)
    worker.add_argument("--scanners", type=Path, default=Path("config/scanners.toml"))
    worker.add_argument("--notify", action="store_true")

    command_once = subparsers.add_parser(
        "command-worker-once",
        help="Telegram --force kuyruğundan tek işi güvenle çalıştır",
    )
    command_once.add_argument("--timeframe", default="1h")
    command_once.add_argument("--bars", type=int, default=320)
    command_once.add_argument("--scanners", type=Path, default=Path("config/scanners.toml"))

    command_loop = subparsers.add_parser(
        "command-worker-loop",
        help="Telegram --force kuyruğunu sürekli tüket",
    )
    command_loop.add_argument("--timeframe", default="1h")
    command_loop.add_argument("--bars", type=int, default=320)
    command_loop.add_argument("--interval", type=float, default=2.0)
    command_loop.add_argument("--scanners", type=Path, default=Path("config/scanners.toml"))

    command_status = subparsers.add_parser(
        "command-jobs-status",
        help="Son Telegram uzun işlerinin güvenli durum ve hata özetini göster",
    )
    command_status.add_argument("--limit", type=int, default=20)

    news_kap = subparsers.add_parser(
        "news-kap-sync",
        help="KAP bildirimlerini canonical haber deposuna eşitle",
    )
    news_kap.add_argument("--lookback-days", type=int, default=1)
    news_kap.add_argument("--notify", action="store_true")

    news_backfill = subparsers.add_parser(
        "news-kap-backfill",
        help="KAP geçmişini API sınırına takılmadan küçük tarih aralıklarıyla doldur",
    )
    news_backfill.add_argument("--days", type=int, default=60)
    news_backfill.add_argument("--chunk-days", type=int, default=3)

    general_news = subparsers.add_parser(
        "news-general-sync",
        help="Kaynak depodaki genel haber ve ekonomik takvim akışlarını eşitle",
    )
    general_news.add_argument("--lookback-days", type=int, default=1)
    general_news.add_argument("--sources", default=",".join(SUPPORTED_SOURCES))
    general_news.add_argument("--notify", action="store_true")

    telegram_smoke = subparsers.add_parser(
        "telegram-smoke-symbol",
        help="Bir sembol için tüm Telegram komut yanıtlarını canlı kuyruğa yaz",
    )
    telegram_smoke.add_argument("symbol")
    telegram_smoke.add_argument(
        "--confirm-live",
        action="store_true",
        help="Gerçek Telegram grubuna mesaj gönderimini açıkça onaylar.",
    )
    return parser


def _connect(database_url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            'psycopg kurulu değil; python -m pip install -e ".[runtime]" çalıştırın'
        ) from exc
    return psycopg.connect(database_url, autocommit=True)


def _publisher(settings: ApplicationSettings, connection) -> TelegramPublisher:
    return TelegramPublisher(
        settings=settings.telegram,
        repository=PostgresOutboxRepository(connection),
        transport=HttpxTelegramTransport(settings.telegram.bot_token),
    )


def _config_check(settings: ApplicationSettings) -> int:
    print(
        "Yapılandırma geçerli: "
        f"env={settings.runtime.app_env}, "
        f"timezone={settings.runtime.timezone.key}, "
        f"delivery={settings.telegram.delivery_mode.value}, "
        f"topics={len(settings.telegram.topic_ids)}"
    )
    return 0


def _doctor(
    settings: ApplicationSettings,
    directory: Path,
    *,
    maximum_cycle_age_hours: float,
    strict_runtime: bool,
) -> int:
    if maximum_cycle_age_hours <= 0:
        raise ValueError("--max-cycle-age-hours pozitif olmalıdır")
    try:
        with _connect(settings.runtime.database_url) as connection:
            report = inspect_runtime(
                connection,
                migrations_directory=directory,
                now=datetime.now(settings.runtime.timezone),
                maximum_cycle_age=timedelta(hours=maximum_cycle_age_hours),
                strict_runtime=strict_runtime,
            )
    except Exception as exc:
        raise RuntimeError(f"doctor PostgreSQL denetimi başarısız: {type(exc).__name__}: {exc}") from exc
    for check in report.checks:
        print(f"{check.status:4} {check.name}: {check.detail}")
    return 0 if report.healthy else 1


def _db_migrate(
    settings: ApplicationSettings,
    directory: Path,
    *,
    dry_run: bool = False,
    baseline: str | None = None,
) -> int:
    with _connect(settings.runtime.database_url) as connection:
        result = apply_migrations(
            connection,
            directory,
            dry_run=dry_run,
            baseline=baseline,
        )
    if dry_run:
        pending = ", ".join(result.pending) or "yok"
        print(f"Bekleyen migration: {pending}")
    else:
        applied = ", ".join(result.applied) or "yok"
        print(f"PostgreSQL migration tamamlandı: uygulanan={applied}")
    return 0


def _db_version(settings: ApplicationSettings, directory: Path) -> int:
    with _connect(settings.runtime.database_url) as connection:
        result = migration_status(connection, directory)
    applied = ", ".join(result.skipped) or "yok"
    pending = ", ".join(result.pending) or "yok"
    print(f"Uygulanmış migration: {applied}\nBekleyen migration: {pending}")
    return 0


def _shadow_scores(
    settings: ApplicationSettings,
    *,
    days: int,
    scanner_id: str | None = None,
    timeframe: str | None = None,
):
    if days < 1 or days > 3650:
        raise ValueError("--days 1 ile 3650 arasında olmalıdır")
    if timeframe is not None:
        timeframe = parse_timeframe(timeframe).value
    since = datetime.now(settings.runtime.timezone) - timedelta(days=days)
    with _connect(settings.runtime.database_url) as connection:
        return PostgresShadowStore(connection).report(
            since=since,
            scanner_id=scanner_id,
            timeframe=timeframe,
        )


def _shadow_report(
    settings: ApplicationSettings,
    *,
    days: int,
    scanner_id: str | None,
    timeframe: str | None,
) -> int:
    scores = _shadow_scores(
        settings,
        days=days,
        scanner_id=scanner_id,
        timeframe=timeframe,
    )
    if not scores:
        print("Seçilen aralıkta shadow karşılaştırması yok.")
        return 0
    print("scanner · timeframe · samples · agreement · legacy_only · new_only · unknown")
    for score in scores:
        print(
            f"{score.scanner_id} · {score.timeframe} · {score.samples} · "
            f"{score.agreement:.4%} · {score.legacy_only} · "
            f"{score.new_only} · {score.unknown}"
        )
    return 0


def _shadow_gate(
    settings: ApplicationSettings,
    *,
    scanner_id: str,
    timeframe: str,
    days: int,
    minimum_samples: int,
    minimum_agreement: float,
) -> int:
    if minimum_samples < 1:
        raise ValueError("--min-samples pozitif olmalıdır")
    if not 0 <= minimum_agreement <= 1:
        raise ValueError("--min-agreement 0 ile 1 arasında olmalıdır")
    canonical_timeframe = parse_timeframe(timeframe).value
    scores = _shadow_scores(
        settings,
        days=days,
        scanner_id=scanner_id,
        timeframe=canonical_timeframe,
    )
    if len(scores) != 1:
        print(
            f"PARITY FAIL · {scanner_id} · {canonical_timeframe} · karşılaştırma yok",
            file=sys.stderr,
        )
        return 1
    score = scores[0]
    passed = score.passes(
        minimum_samples=minimum_samples,
        minimum_agreement=minimum_agreement,
    )
    print(
        f"PARITY {'PASS' if passed else 'FAIL'} · {scanner_id} · {canonical_timeframe} · "
        f"samples={score.samples} · agreement={score.agreement:.4%} · "
        f"legacy_only={score.legacy_only}"
    )
    return 0 if passed else 1


def _outcome_horizons(raw: str) -> tuple[int, ...]:
    try:
        values = tuple(sorted({int(value.strip()) for value in raw.split(",")}))
    except ValueError as exc:
        raise ValueError("--horizon virgülle ayrılmış pozitif tam sayılar olmalıdır") from exc
    if not values or values[0] < 1 or values[-1] > 500:
        raise ValueError("--horizon değerleri 1 ile 500 arasında olmalıdır")
    return values


def _outcomes_backfill(
    settings: ApplicationSettings,
    *,
    horizon_raw: str,
    days: int,
    scanner_id: str | None,
) -> int:
    if days < 1 or days > 3650:
        raise ValueError("--days 1 ile 3650 arasında olmalıdır")
    horizons = _outcome_horizons(horizon_raw)
    now = datetime.now(settings.runtime.timezone)
    since = now - timedelta(days=days)
    completed = 0
    waiting = 0
    with _connect(settings.runtime.database_url) as connection:
        store = PostgresOutcomeStore(connection)
        candidates = store.candidates(since=since, scanner_id=scanner_id)
        for candidate in candidates:
            source = store.load_frame(candidate, maximum_horizon=max(horizons))
            if source is None:
                waiting += len(horizons)
                continue
            benchmark = store.load_benchmark(candidate, maximum_horizon=max(horizons))
            outcomes = tuple(
                measure(
                    event_id=candidate.event_id,
                    event_bar_time=candidate.event_bar_time,
                    direction=candidate.direction,
                    frame=source,
                    benchmark=benchmark,
                    window=OutcomeWindow(
                        horizon_bars=horizon,
                        price_basis=candidate.price_basis,
                    ),
                )
                for horizon in horizons
            )
            completed += store.save(outcomes, observed_at=now)
            waiting += sum(not outcome.complete for outcome in outcomes)
    print(
        f"Outcome backfill tamamlandı: events={len(candidates)}, "
        f"written={completed}, waiting={waiting}, horizons={horizons}"
    )
    return 0


def _outcomes_report(
    settings: ApplicationSettings,
    *,
    days: int,
    minimum_samples: int,
) -> int:
    if days < 1 or days > 3650 or minimum_samples < 1:
        raise ValueError("--days ve --min-samples pozitif olmalıdır")
    since = datetime.now(settings.runtime.timezone) - timedelta(days=days)
    with _connect(settings.runtime.database_url) as connection:
        rows = PostgresOutcomeStore(connection).report(
            since=since,
            minimum_samples=minimum_samples,
        )
    if not rows:
        print("Seçilen aralık ve örnek eşiğinde tamamlanmış outcome yok.")
        return 0
    print("scanner · tf · horizon · n · raw · excess · win · mfe · mae")
    for row in rows:
        excess = "UNKNOWN" if row.average_excess_return is None else f"{row.average_excess_return:.2%}"
        print(
            f"{row.scanner_id} · {row.timeframe} · {row.horizon_bars} · "
            f"{row.samples} · {row.average_raw_return:.2%} · {excess} · "
            f"{row.win_rate:.2%} · {row.average_mfe:.2%} · {row.average_mae:.2%}"
        )
    print("Not: Geçmiş sonuç ölçümü yatırım tavsiyesi veya gelecek getiri garantisi değildir.")
    return 0


def _publisher_once(
    settings: ApplicationSettings,
    *,
    limit: int,
) -> int:
    if limit < 1 or limit > 500:
        raise ValueError("--limit 1 ile 500 arasında olmalıdır")
    with _connect(settings.runtime.database_url) as connection:
        result = _publisher(settings, connection).publish_batch(
            now=datetime.now(settings.runtime.timezone),
            limit=limit,
        )
    if result.skipped_mode is not None:
        print(f"Publisher güvenlik kapısı nedeniyle atlandı: {result.skipped_mode.value}")
    else:
        print(
            f"Publisher tamamlandı: claimed={result.claimed}, "
            f"sent={result.sent}, failed={result.failed}"
        )
    return 0 if result.failed == 0 else 1


def _publisher_loop(
    settings: ApplicationSettings,
    *,
    limit: int,
    interval: float,
) -> int:
    if interval < 0.2:
        raise ValueError("--interval en az 0.2 saniye olmalıdır")
    stopped = False

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    with _connect(settings.runtime.database_url) as connection:
        publisher = _publisher(settings, connection)
        while not stopped:
            result = publisher.publish_batch(
                now=datetime.now(settings.runtime.timezone),
                limit=limit,
            )
            if result.failed:
                print(f"Publisher batch hatası: {result.failed}", file=sys.stderr)
            if result.skipped_mode is not None:
                print(
                    "Publisher teslimat kapısı kapalı: "
                    f"{result.skipped_mode.value}; servis durduruldu."
                )
                return 0
            time.sleep(interval)
    return 0


def _listener(settings: ApplicationSettings, connection) -> TelegramListener:
    source = HttpxTelegramUpdateSource(settings.telegram.bot_token)
    telegram_settings = settings.telegram
    if telegram_settings.allow_chat_admins:
        administrator_ids = source.fetch_chat_administrator_ids(chat_id=telegram_settings.chat_id)
        telegram_settings = replace(
            telegram_settings,
            allowed_user_ids=telegram_settings.allowed_user_ids | administrator_ids,
        )
    return TelegramListener(
        settings=telegram_settings,
        source=source,
        repository=PostgresTelegramUpdateRepository(connection),
        command_service=SymbolCommandService(
            PostgresSymbolReadStore(connection),
            PostgresLongJobQueue(connection),
            clock=lambda: datetime.now(settings.runtime.timezone),
        ),
    )


def _listener_once(settings: ApplicationSettings, *, timeout: int) -> int:
    if timeout < 0 or timeout > 50:
        raise ValueError("--timeout 0 ile 50 saniye arasında olmalıdır")
    with _connect(settings.runtime.database_url) as connection:
        repository = PostgresTelegramUpdateRepository(connection)
        if not repository.acquire_listener_lock():
            raise RuntimeError("Başka bir merkezi Telegram listener çalışıyor")
        try:
            result = _listener(settings, connection).run_once(timeout_seconds=timeout)
        finally:
            repository.release_listener_lock()
    print(
        f"Listener tamamlandı: received={result.received}, "
        f"accepted={result.accepted}, ignored={result.ignored}, "
        f"reasons={result.ignored_reasons}"
    )
    return 0


def _listener_loop(settings: ApplicationSettings, *, timeout: int) -> int:
    if timeout < 1 or timeout > 50:
        raise ValueError("--timeout 1 ile 50 saniye arasında olmalıdır")
    stopped = False

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    with _connect(settings.runtime.database_url) as connection:
        repository = PostgresTelegramUpdateRepository(connection)
        if not repository.acquire_listener_lock():
            raise RuntimeError("Başka bir merkezi Telegram listener çalışıyor")
        try:
            listener = _listener(settings, connection)
            while not stopped:
                listener.run_once(timeout_seconds=timeout)
        finally:
            repository.release_listener_lock()
    return 0


def _register_instrument(
    settings: ApplicationSettings,
    *,
    symbol: str,
    provider_symbol: str | None,
    universe: str,
) -> int:
    canonical = symbol.strip().upper()
    provider_value = (provider_symbol or canonical).strip().upper()
    if not canonical or not provider_value or not universe.strip():
        raise ValueError("Sembol ve universe boş olamaz")
    with _connect(settings.runtime.database_url) as connection:
        effective_date = datetime.now(settings.runtime.timezone).date()
        instrument = PostgresRuntimeRepository(connection).register_instrument(
            canonical,
            provider_symbol=provider_value,
            universe_id=universe.strip(),
            valid_from=effective_date,
        )
    print(
        f"Enstrüman hazır: {instrument.symbol} · provider={instrument.provider_symbol} "
        f"· id={instrument.instrument_id}"
    )
    return 0


def _sync_universe(
    settings: ApplicationSettings,
    *,
    universe: str,
    apply: bool,
    allow_large_removal: bool,
) -> int:
    universe_id = universe.strip().upper()
    if universe_id != "BIST_ALL":
        raise ValueError("Bu sürümde otomatik eşitleme yalnız BIST_ALL destekler")
    evaluation_time = datetime.now(settings.runtime.timezone)
    provider = BorsapyBistUniverseProvider()
    members = provider.list_members(universe_id)
    with _connect(settings.runtime.database_url) as connection:
        repository = PostgresRuntimeRepository(connection)
        current = repository.list_universe(universe_id, as_of=evaluation_time.date())
        plan = build_universe_sync_plan(
            universe_id=universe_id,
            source=provider.source,
            as_of=evaluation_time.date(),
            members=members,
            current_symbols=tuple(item.symbol for item in current),
        )
        validate_universe_sync_plan(
            plan,
            allow_large_removal=allow_large_removal,
        )
        summary = (
            f"Universe önizleme: {plan.universe_id} · kaynak={plan.source} · "
            f"mevcut={plan.current_count} · gözlenen={plan.observed_count} · "
            f"eklenecek={len(plan.additions)} · çıkarılacak={len(plan.removals)}"
        )
        print(summary)
        if not apply:
            print("Değişiklik uygulanmadı. Uygulamak için --apply kullanın.")
            return 0
        sync_run_id = repository.apply_universe_sync(plan)
    print(f"Universe eşitlemesi uygulandı: sync_run_id={sync_run_id}")
    return 0


def _feature_engine(connection) -> FeatureEngine:
    registry = FeatureRegistry()
    for provider in (
        RelativeVolume20Provider(),
        MacdProvider(),
        RsiProvider(),
        SmiProvider(),
        LegacyRsi7Provider(),
        LegacyRsi14Provider(),
        LegacyTrendMaProvider(),
        InclusiveVolumeSma10Provider(),
        InclusiveVolumeSma20Provider(),
        WilderAtr14Provider(),
        DecisionPanelV645Provider(),
        TechnicalMarketContextProvider(),
        ResearchTechnicalSnapshotProvider(),
        QualifiedMaResearchProvider(PostgresMaQualificationSource(connection)),
    ):
        registry.register(provider)
    return FeatureEngine(registry)


def _market_data_provider(settings: ApplicationSettings) -> FallbackMarketDataProvider:
    return FallbackMarketDataProvider(
        (
            BorsapyProvider(timestamp_timezone=settings.runtime.timezone.key),
            YFinanceBistProvider(timestamp_timezone=settings.runtime.timezone.key),
        )
    )


def _shadow_recorder(settings: ApplicationSettings, connection):
    if not settings.runtime.enable_shadow_parity:
        return None
    return ShadowRecorder(PostgresShadowStore(connection))


def _research_instrument(
    *,
    settings: ApplicationSettings,
    connection,
    instrument,
    timeframe,
    bars: int,
    evaluation_time: datetime,
) -> tuple[int, int]:
    frame = IngestionService(
        provider=_market_data_provider(settings),
        store=PostgresSnapshotStore(connection),
    ).ingest(
        IngestionRequest(
            instrument_id=instrument.instrument_id,
            symbol=instrument.symbol,
            provider_symbol=instrument.provider_symbol,
            market=instrument.market,
            timeframe=timeframe,
            bars=bars,
            as_of=evaluation_time,
            series_revision=1,
        )
    )
    levels = research_ma_levels(frame)
    stored = PostgresMaResearchStore(connection).replace(frame, levels)
    qualified = sum(level.level_class in {"strong_level", "level"} for level in levels)
    return stored, qualified


def _ma_research_symbol(
    settings: ApplicationSettings,
    *,
    symbol: str,
    timeframe_raw: str,
    bars: int,
) -> int:
    if bars < 420 or bars > 5000:
        raise ValueError("MA Research --bars 420 ile 5000 arasında olmalıdır")
    timeframe = parse_timeframe(timeframe_raw)
    evaluation_time = datetime.now(settings.runtime.timezone)
    with _connect(settings.runtime.database_url) as connection:
        instrument = PostgresRuntimeRepository(connection).resolve_instrument(
            symbol.strip().upper(),
            as_of=evaluation_time.date(),
        )
        if instrument is None:
            raise ValueError(
                f"Enstrüman kayıtlı değil: {symbol}; önce universe-sync --apply çalıştırın"
            )
        stored, qualified = _research_instrument(
            settings=settings,
            connection=connection,
            instrument=instrument,
            timeframe=timeframe,
            bars=bars,
            evaluation_time=evaluation_time,
        )
    print(
        f"MA Research tamamlandı: {instrument.symbol} {timeframe.value} · "
        f"seviye={stored} · nitelikli={qualified}"
    )
    return 0


def _ma_research_universe(
    settings: ApplicationSettings,
    *,
    universe: str,
    timeframe_raw: str,
    bars: int,
) -> int:
    if bars < 420 or bars > 5000:
        raise ValueError("MA Research --bars 420 ile 5000 arasında olmalıdır")
    universe_id = universe.strip().upper()
    timeframe = parse_timeframe(timeframe_raw)
    evaluation_time = datetime.now(settings.runtime.timezone)
    successful = 0
    failed = 0
    qualified = 0
    with _connect(settings.runtime.database_url) as connection:
        runtime = PostgresRuntimeRepository(connection)
        instruments = runtime.list_universe(universe_id, as_of=evaluation_time.date())
        if not instruments:
            raise ValueError(f"Universe boş: {universe_id}; önce universe-sync --apply çalıştırın")
        for instrument in instruments:
            try:
                _stored, instrument_qualified = _research_instrument(
                    settings=settings,
                    connection=connection,
                    instrument=instrument,
                    timeframe=timeframe,
                    bars=bars,
                    evaluation_time=evaluation_time,
                )
            except Exception as exc:
                failed += 1
                print(
                    f"MA Research hatası: {instrument.symbol} · {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            else:
                successful += 1
                qualified += instrument_qualified
    print(
        f"MA Research universe: {universe_id} {timeframe.value} · "
        f"başarılı={successful} · hatalı={failed} · nitelikli_seviye={qualified}"
    )
    return 0 if failed == 0 else 1


def _scan_symbol(
    settings: ApplicationSettings,
    *,
    symbol: str,
    timeframe_raw: str,
    bars: int,
    scanners_path: Path,
    notify: bool,
) -> int:
    if bars < 40 or bars > 5000:
        raise ValueError("--bars 40 ile 5000 arasında olmalıdır")
    timeframe = parse_timeframe(timeframe_raw)
    if notify and settings.telegram.delivery_mode.value != "live":
        raise ValueError("--notify için DELIVERY_MODE=live olmalıdır")
    effective_telegram = (
        settings.telegram
        if notify
        else replace(settings.telegram, delivery_mode=DeliveryMode.DISABLED)
    )
    evaluation_time = datetime.now(settings.runtime.timezone)
    with _connect(settings.runtime.database_url) as connection:
        runtime = PostgresRuntimeRepository(connection)
        instrument = runtime.resolve_instrument(symbol, as_of=evaluation_time.date())
        if instrument is None:
            raise ValueError(
                f"Enstrüman kayıtlı değil: {symbol}; önce instrument-register kullanın"
            )
        frame = IngestionService(
            provider=_market_data_provider(settings),
            store=PostgresSnapshotStore(connection),
        ).ingest(
            IngestionRequest(
                instrument_id=instrument.instrument_id,
                symbol=instrument.symbol,
                provider_symbol=instrument.provider_symbol,
                market=instrument.market,
                timeframe=timeframe,
                bars=bars,
                as_of=evaluation_time,
                series_revision=1,
            )
        )
        cycle_id = runtime.start_cycle(
            market=instrument.market,
            universe_id=f"manual:{instrument.symbol}",
            timeframe=timeframe.value,
            bar_time=frame.through_bar_time,
            expected_instruments=1,
            started_at=evaluation_time,
        )
        try:
            coordinator = ScanFrameCoordinator(
                feature_engine=_feature_engine(connection),
                event_store=PostgresScanStore(connection),
                state_store=PostgresStateStore(connection),
                telegram_settings=effective_telegram,
                confluence_store=PostgresConfluenceStore(connection),
                shadow_recorder=_shadow_recorder(settings, connection),
            )
            result = coordinator.run(
                cycle_id=cycle_id,
                frame=frame,
                bindings=load_scanner_catalog(scanners_path),
                evaluation_time=evaluation_time,
            )
        except Exception:
            runtime.finish_cycle(
                cycle_id=cycle_id,
                successful=0,
                stale=0,
                failed=1,
                finished_at=datetime.now(settings.runtime.timezone),
            )
            raise
        else:
            runtime.finish_cycle(
                cycle_id=cycle_id,
                successful=1,
                stale=0,
                failed=0,
                finished_at=datetime.now(settings.runtime.timezone),
            )
    statuses = ", ".join(
        f"{run.evaluation.scanner_id}={run.evaluation.status.value}" for run in result.runs
    )
    print(
        f"Tarama tamamlandı: {instrument.symbol} {timeframe.value} "
        f"bar={frame.through_bar_time.isoformat()} · {statuses} · "
        f"events={result.event_count}, transitions={result.transition_count}, "
        f"confluence={result.confluence_count}, outbox={result.outbox_count}"
    )
    return 0


def _scheduled_components(settings: ApplicationSettings, connection, *, notify: bool):
    if notify and settings.telegram.delivery_mode is not DeliveryMode.LIVE:
        raise ValueError("--notify için DELIVERY_MODE=live olmalıdır")
    telegram = (
        settings.telegram
        if notify
        else replace(settings.telegram, delivery_mode=DeliveryMode.DISABLED)
    )
    runtime = PostgresRuntimeRepository(connection)
    ingestion = IngestionService(
        provider=_market_data_provider(settings),
        store=PostgresSnapshotStore(connection),
    )
    coordinator = ScanFrameCoordinator(
        feature_engine=_feature_engine(connection),
        event_store=PostgresScanStore(connection),
        state_store=PostgresStateStore(connection),
        telegram_settings=telegram,
        confluence_store=PostgresConfluenceStore(connection),
        shadow_recorder=_shadow_recorder(settings, connection),
    )
    return runtime, ingestion, coordinator


def _scan_due(
    settings: ApplicationSettings,
    *,
    timeframe_raw: str,
    universe: str,
    bars: int,
    lookback_days: int,
    scanners_path: Path,
    notify: bool,
) -> int:
    if bars < 40 or bars > 5000:
        raise ValueError("--bars 40 ile 5000 arasında olmalıdır")
    if lookback_days < 1 or lookback_days > 60:
        raise ValueError("--lookback-days 1 ile 60 arasında olmalıdır")
    timeframe = parse_timeframe(timeframe_raw)
    evaluation_time = datetime.now(settings.runtime.timezone)
    calendar = ExchangeCalendarsXist()
    with _connect(settings.runtime.database_url) as connection:
        runtime, ingestion, coordinator = _scheduled_components(
            settings,
            connection,
            notify=notify,
        )
        result = ScheduledScanService(
            repository=runtime,
            ingestion=ingestion,
            coordinator=coordinator,
            planner=ScheduledBarPlanner(
                calendar,
                maximum_lookback_days=lookback_days,
            ),
        ).run(
            ScheduledScanRequest(
                market="BIST",
                universe_id=universe,
                timeframe=timeframe,
                bars=bars,
                evaluation_time=evaluation_time,
            ),
            load_scanner_catalog(
                scanners_path,
                calendar_version=calendar.version,
            ),
        )
    print(
        f"Scheduled scan: timeframe={timeframe.value}, due={len(result.due_bars)}, "
        f"completed={result.completed_bars}, success={result.successful_instruments}, "
        f"failed={result.failed_instruments}"
    )
    return 0 if result.failed_instruments == 0 else 1


def _scan_worker(
    settings: ApplicationSettings,
    *,
    timeframes_raw: str,
    universe: str,
    bars: int,
    lookback_days: int,
    poll_seconds: float,
    scanners_path: Path,
    notify: bool,
) -> int:
    if poll_seconds < 5:
        raise ValueError("--poll-seconds en az 5 saniye olmalıdır")
    timeframes = tuple(part.strip() for part in timeframes_raw.split(",") if part.strip())
    if not timeframes:
        raise ValueError("--timeframes en az bir değer içermelidir")
    for value in timeframes:
        parse_timeframe(value)
    stopped = False

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    while not stopped:
        for timeframe in timeframes:
            try:
                _scan_due(
                    settings,
                    timeframe_raw=timeframe,
                    universe=universe,
                    bars=bars,
                    lookback_days=lookback_days,
                    scanners_path=scanners_path,
                    notify=notify,
                )
            except Exception as exc:
                print(
                    f"Scheduled scan hatası ({timeframe}): {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        if not stopped:
            time.sleep(poll_seconds)
    return 0


def _command_job_executor(
    settings: ApplicationSettings,
    *,
    timeframe: str,
    bars: int,
    scanners_path: Path,
):
    parse_timeframe(timeframe)

    def financial_chain() -> FinancialProviderChain:
        return FinancialProviderChain(
            (
                BorsapyKapFinancialProvider(),
                YFinanceFinancialProvider(),
            )
        )

    def research_frame(connection, job: CommandJob, generated_at: datetime):
        runtime = PostgresRuntimeRepository(connection)
        instrument = runtime.resolve_instrument(job.symbol, as_of=generated_at.date())
        if instrument is None:
            raise ValueError(f"Aktif enstrüman bulunamadı: {job.symbol}")
        frame = IngestionService(
            provider=_market_data_provider(settings),
            store=PostgresSnapshotStore(connection),
        ).ingest(
            IngestionRequest(
                instrument_id=instrument.instrument_id,
                symbol=instrument.symbol,
                provider_symbol=instrument.provider_symbol,
                market=instrument.market,
                timeframe=Timeframe.D1,
                bars=max(500, bars),
                as_of=generated_at,
                series_revision=1,
            )
        )
        stored = PostgresSymbolReadStore(connection).load_symbol(job.symbol)
        if stored is None:
            raise ValueError(f"Araştırma snapshot'ı bulunamadı: {job.symbol}")
        service = EquityReportService(
            feature_engine=_feature_engine(connection),
            financials=financial_chain(),
        )
        return frame, stored, service

    def execute(job: CommandJob) -> CommandJobOutput | None:
        if job.command in {CommandName.SCAN, CommandName.SCANS}:
            _ma_research_symbol(
                settings,
                symbol=job.symbol,
                timeframe_raw=timeframe,
                bars=max(1000, bars),
            )
            _scan_symbol(
                settings,
                symbol=job.symbol,
                timeframe_raw=timeframe,
                bars=bars,
                scanners_path=scanners_path,
                notify=False,
            )
            return
        target = settings.runtime.artifact_root / job.job_id / job.command.value
        if job.command is CommandName.ANALYSIS:
            generated_at = datetime.now(settings.runtime.timezone)
            with _connect(settings.runtime.database_url) as connection:
                frame, stored, service = research_frame(connection, job, generated_at)
                report = service.assemble(
                    frame=frame,
                    stored=stored,
                    generated_at=generated_at,
                )
            envelope = TopicRouter(settings.telegram).route(
                publication_kind=PublicationKind.ANALYSIS,
                semantic_identity={"report_id": report.report_id, "view": "summary"},
                payload={"text": analysis_message(report)},
            )
            return CommandJobOutput(envelopes=(envelope,))
        if job.command is CommandName.REPORT:
            generated_at = datetime.now(settings.runtime.timezone)
            with _connect(settings.runtime.database_url) as connection:
                frame, stored, service = research_frame(connection, job, generated_at)
                output_path = target / (
                    f"{job.symbol}_{frame.through_bar_time:%Y%m%d}_arastirma_raporu.pdf"
                )
                generated = service.generate(
                    frame=frame,
                    stored=stored,
                    generated_at=generated_at,
                    target=output_path,
                )
            report_envelope = TopicRouter(settings.telegram).route(
                publication_kind=PublicationKind.REPORT,
                semantic_identity={"report_id": generated.report_id},
                payload={
                    "_method": "sendDocument",
                    "document_path": str(generated.rendered.path),
                    "document_base64": base64.b64encode(
                        generated.rendered.path.read_bytes()
                    ).decode("ascii"),
                    "filename": generated.rendered.path.name,
                    "caption": (
                        f"{job.symbol} · 24 bölümlü araştırma raporu\n"
                        f"Kapalı bar: {generated.bar_time:%d.%m.%Y}\n"
                        "Eksik veriler UNKNOWN bırakılmıştır. Yatırım tavsiyesi değildir."
                    ),
                },
            )
            return CommandJobOutput(
                envelopes=(report_envelope,),
                artifact=CommandArtifact(
                    report_id=generated.report_id,
                    instrument_id=generated.instrument_id,
                    artifact_kind="equity_report_pdf",
                    timeframe=generated.timeframe,
                    bar_time=generated.bar_time,
                    summary=generated.summary,
                    storage_uri=str(generated.rendered.path),
                    content_hash=generated.rendered.content_hash,
                ),
            )
        if job.command is CommandName.FUNDAMENTAL:
            as_of = datetime.now(settings.runtime.timezone)
            financial = financial_chain().fetch(job.symbol, as_of=as_of)
            envelope = TopicRouter(settings.telegram).route(
                publication_kind=PublicationKind.ANALYSIS,
                semantic_identity={
                    "job_id": job.job_id,
                    "view": "fundamental",
                    "as_of": as_of,
                },
                payload={"text": fundamental_message(job.symbol, financial)},
            )
            return CommandJobOutput(envelopes=(envelope,))
        if job.command is CommandName.CHART:
            generate_and_send_chart(
                symbol=job.symbol,
                topic_id=settings.telegram.topic_id(TopicKind.CHARTS),
                target=target,
            )
            return
        raise ValueError(f"Desteklenmeyen uzun iş komutu: {job.command.value}")

    return execute


def _command_worker_once(
    settings: ApplicationSettings,
    *,
    timeframe: str,
    bars: int,
    scanners_path: Path,
) -> int:
    with _connect(settings.runtime.database_url) as connection:
        result = CommandJobRunner(
            settings=settings.telegram,
            repository=PostgresCommandJobRepository(connection),
            executor=_command_job_executor(
                settings,
                timeframe=timeframe,
                bars=bars,
                scanners_path=scanners_path,
            ),
        ).run_once(now=datetime.now(settings.runtime.timezone))
    print(
        f"Command worker: claimed={result.claimed}, "
        f"completed={result.completed}, failed={result.failed}"
    )
    return 0 if result.failed == 0 else 1


def _command_worker_loop(
    settings: ApplicationSettings,
    *,
    timeframe: str,
    bars: int,
    scanners_path: Path,
    interval: float,
) -> int:
    if interval < 0.2:
        raise ValueError("--interval en az 0.2 saniye olmalıdır")
    stopped = False

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    with _connect(settings.runtime.database_url) as connection:
        runner = CommandJobRunner(
            settings=settings.telegram,
            repository=PostgresCommandJobRepository(connection),
            executor=_command_job_executor(
                settings,
                timeframe=timeframe,
                bars=bars,
                scanners_path=scanners_path,
            ),
        )
        while not stopped:
            result = runner.run_once(now=datetime.now(settings.runtime.timezone))
            if result.failed:
                print("Command worker işi başarısız oldu", file=sys.stderr)
            if not result.claimed:
                time.sleep(interval)
    return 0


def _command_jobs_status(settings: ApplicationSettings, *, limit: int) -> int:
    if limit < 1 or limit > 100:
        raise ValueError("--limit 1 ile 100 arasında olmalıdır")
    query = """
    SELECT command_name, symbol_at_request, status, attempt_count,
           requested_at, finished_at, error_detail
    FROM command_jobs
    ORDER BY requested_at DESC
    LIMIT %s
    """
    with _connect(settings.runtime.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
    print(f"Son command job kayıtları: {len(rows)}")
    for row in rows:
        error = str(row[6] or "-")
        for secret in (
            settings.telegram.bot_token,
            settings.runtime.database_url,
        ):
            if secret:
                error = error.replace(secret, "[REDACTED]")
        print(
            f"{row[0]} {row[1]} status={row[2]} attempt={row[3]} "
            f"requested={row[4]} finished={row[5]} error={error[:500]}"
        )
    return 0


def _news_kap_sync(
    settings: ApplicationSettings,
    *,
    lookback_days: int,
    notify: bool,
) -> int:
    if lookback_days < 0 or lookback_days > 30:
        raise ValueError("--lookback-days 0 ile 30 arasında olmalıdır")
    observed_at = datetime.now(settings.runtime.timezone)
    with _connect(settings.runtime.database_url) as connection:
        result = NewsIngestionService(
            provider=KapDisclosureProvider(timezone=settings.runtime.timezone),
            store=PostgresNewsStore(connection),
            telegram_settings=settings.telegram,
        ).run(
            from_date=observed_at.date() - timedelta(days=lookback_days),
            to_date=observed_at.date(),
            observed_at=observed_at,
            notify=notify,
        )
    print(
        "KAP haber eşitleme: "
        f"bulunan={result.fetched}, yeni={result.inserted}, "
        f"BIST_bağlantılı={result.linked_items}, outbox={result.outbox_count}, "
        f"ilk_referans={'evet' if result.bootstrapped else 'hayır'}"
    )
    return 0


def _news_kap_backfill(
    settings: ApplicationSettings,
    *,
    days: int,
    chunk_days: int,
) -> int:
    if days < 1 or days > 365:
        raise ValueError("--days 1 ile 365 arasında olmalıdır")
    if chunk_days < 1 or chunk_days > 7:
        raise ValueError("--chunk-days 1 ile 7 arasında olmalıdır")
    observed_at = datetime.now(settings.runtime.timezone)
    first_date = observed_at.date() - timedelta(days=days)
    period_end = observed_at.date()
    totals = [0, 0, 0]
    with _connect(settings.runtime.database_url) as connection:
        service = NewsIngestionService(
            provider=KapDisclosureProvider(timezone=settings.runtime.timezone),
            store=PostgresNewsStore(connection),
            telegram_settings=settings.telegram,
        )
        while period_end >= first_date:
            period_start = max(
                first_date,
                period_end - timedelta(days=chunk_days - 1),
            )
            result = service.run(
                from_date=period_start,
                to_date=period_end,
                observed_at=observed_at,
                notify=False,
            )
            totals[0] += result.fetched
            totals[1] += result.inserted
            totals[2] += result.linked_items
            period_end = period_start - timedelta(days=1)
    print(
        "KAP geçmişi dolduruldu: "
        f"days={days}, bulunan={totals[0]}, yeni={totals[1]}, "
        f"BIST_bağlantılı={totals[2]}, outbox=0"
    )
    return 0


def _news_general_sync(
    settings: ApplicationSettings,
    *,
    lookback_days: int,
    sources_raw: str,
    notify: bool,
) -> int:
    if lookback_days < 0 or lookback_days > 7:
        raise ValueError("--lookback-days 0 ile 7 arasında olmalıdır")
    sources = tuple(
        dict.fromkeys(value.strip().casefold() for value in sources_raw.split(",") if value.strip())
    )
    unknown = sorted(set(sources) - set(SUPPORTED_SOURCES))
    if unknown:
        raise ValueError("Desteklenmeyen genel haber kaynağı: " + ", ".join(unknown))
    observed_at = datetime.now(settings.runtime.timezone)
    failed = 0
    totals = [0, 0, 0]
    with _connect(settings.runtime.database_url) as connection:
        store = PostgresNewsStore(connection)
        for source in sources:
            try:
                result = NewsIngestionService(
                    provider=LegacyGeneralNewsProvider(
                        source,
                        timezone=settings.runtime.timezone,
                    ),
                    store=store,
                    telegram_settings=settings.telegram,
                ).run(
                    from_date=observed_at.date() - timedelta(days=lookback_days),
                    to_date=observed_at.date(),
                    observed_at=observed_at,
                    notify=notify,
                )
            except Exception as exc:
                failed += 1
                print(
                    f"Genel haber kaynağı hatası ({source}): {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue
            totals[0] += result.fetched
            totals[1] += result.inserted
            totals[2] += result.outbox_count
            print(
                f"Genel haber eşitleme: source={source}, bulunan={result.fetched}, "
                f"yeni={result.inserted}, outbox={result.outbox_count}, "
                f"ilk_referans={'evet' if result.bootstrapped else 'hayır'}"
            )
    print(
        f"Genel haber toplamı: bulunan={totals[0]}, yeni={totals[1]}, "
        f"outbox={totals[2]}, hatalı_kaynak={failed}"
    )
    return 0 if failed == 0 else 1


def _telegram_smoke_symbol(
    settings: ApplicationSettings,
    *,
    symbol: str,
    confirm_live: bool,
) -> int:
    if settings.telegram.delivery_mode is not DeliveryMode.LIVE or not confirm_live:
        raise ValueError(
            "Canlı deneme için DELIVERY_MODE=live ve --confirm-live birlikte gereklidir"
        )
    canonical = symbol.strip().upper()
    if not canonical:
        raise ValueError("Sembol boş olamaz")
    run_id = str(uuid.uuid4())
    topic_id = settings.telegram.topic_id(TopicKind.COMMAND)
    user_id = min(settings.telegram.allowed_user_ids)
    specifications = (
        (CommandName.HELP, ()),
        (CommandName.STATUS, ()),
        (CommandName.SCAN, (canonical,)),
        (CommandName.SCANS, (canonical,)),
        (CommandName.NEWS, (canonical,)),
        (CommandName.ANALYSIS, (canonical,)),
        (CommandName.REPORT, (canonical,)),
        (CommandName.FUNDAMENTAL, (canonical,)),
        (CommandName.CHART, (canonical,)),
        (CommandName.CHART_HELP, ()),
        (CommandName.LIST, ()),
        (CommandName.HISTORY, ()),
        (CommandName.SCAN, (canonical, "--FORCE")),
    )
    with _connect(settings.runtime.database_url) as connection:
        service = SymbolCommandService(
            PostgresSymbolReadStore(connection),
            PostgresLongJobQueue(connection),
            clock=lambda: datetime.now(settings.runtime.timezone),
        )
        router = TopicRouter(settings.telegram)
        envelopes = []
        for command_index, (name, arguments) in enumerate(specifications, 1):
            command = IncomingCommand(
                update_id=-command_index,
                message_id=-command_index,
                user_id=user_id,
                chat_id=settings.telegram.chat_id,
                topic_id=topic_id,
                name=name,
                args=arguments,
            )
            reply = service.handle(command)
            rendered_command = f"/{name.value}" + (f" {' '.join(arguments)}" if arguments else "")
            for part, text in enumerate(reply.messages, 1):
                reply_topic_kind = {
                    CommandName.SCAN: TopicKind.SCANS,
                    CommandName.SCANS: TopicKind.SCANS,
                    CommandName.NEWS: TopicKind.NEWS,
                }.get(name, TopicKind.COMMAND)
                envelopes.append(
                    router.route(
                        publication_kind=PublicationKind.COMMAND_REPLY,
                        semantic_identity={
                            "smoke_run_id": run_id,
                            "command": rendered_command,
                            "part": part,
                        },
                        payload={"text": f"🧪 {rendered_command}\n\n{text}"},
                        reply_topic_kind=reply_topic_kind,
                    )
                )
        inserted = PostgresOutboxRepository(connection).enqueue(tuple(envelopes))
    print(
        f"Telegram ASELS komut denemesi kuyruğa yazıldı: "
        f"symbol={canonical}, messages={inserted}, run_id={run_id}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        values = merged_environment(os.environ, args.env_file)
        settings = ApplicationSettings.from_mapping(values)
        if args.command == "config-check":
            return _config_check(settings)
        if args.command == "doctor":
            return _doctor(
                settings,
                args.directory,
                maximum_cycle_age_hours=args.max_cycle_age_hours,
                strict_runtime=args.strict_runtime,
            )
        if args.command == "db-init":
            return _db_migrate(settings, args.directory)
        if args.command == "db-migrate":
            return _db_migrate(
                settings,
                args.directory,
                dry_run=args.dry_run,
                baseline=args.baseline,
            )
        if args.command == "db-version":
            return _db_version(settings, args.directory)
        if args.command == "shadow-report":
            return _shadow_report(
                settings,
                days=args.days,
                scanner_id=args.scanner,
                timeframe=args.timeframe,
            )
        if args.command == "shadow-gate":
            return _shadow_gate(
                settings,
                scanner_id=args.scanner,
                timeframe=args.timeframe,
                days=args.days,
                minimum_samples=args.min_samples,
                minimum_agreement=args.min_agreement,
            )
        if args.command == "outcomes-backfill":
            return _outcomes_backfill(
                settings,
                horizon_raw=args.horizon,
                days=args.days,
                scanner_id=args.scanner,
            )
        if args.command == "outcomes-report":
            return _outcomes_report(
                settings,
                days=args.days,
                minimum_samples=args.min_samples,
            )
        if args.command == "publisher-once":
            return _publisher_once(settings, limit=args.limit)
        if args.command == "publisher-loop":
            return _publisher_loop(
                settings,
                limit=args.limit,
                interval=args.interval,
            )
        if args.command == "listener-once":
            return _listener_once(settings, timeout=args.timeout)
        if args.command == "listener-loop":
            return _listener_loop(settings, timeout=args.timeout)
        if args.command == "instrument-register":
            return _register_instrument(
                settings,
                symbol=args.symbol,
                provider_symbol=args.provider_symbol,
                universe=args.universe,
            )
        if args.command == "universe-sync":
            return _sync_universe(
                settings,
                universe=args.universe,
                apply=args.apply,
                allow_large_removal=args.allow_large_removal,
            )
        if args.command == "ma-research-symbol":
            return _ma_research_symbol(
                settings,
                symbol=args.symbol,
                timeframe_raw=args.timeframe,
                bars=args.bars,
            )
        if args.command == "ma-research-universe":
            return _ma_research_universe(
                settings,
                universe=args.universe,
                timeframe_raw=args.timeframe,
                bars=args.bars,
            )
        if args.command == "scan-symbol":
            return _scan_symbol(
                settings,
                symbol=args.symbol,
                timeframe_raw=args.timeframe,
                bars=args.bars,
                scanners_path=args.scanners,
                notify=args.notify,
            )
        if args.command == "scan-due":
            return _scan_due(
                settings,
                timeframe_raw=args.timeframe,
                universe=args.universe,
                bars=args.bars,
                lookback_days=args.lookback_days,
                scanners_path=args.scanners,
                notify=args.notify,
            )
        if args.command == "scan-worker":
            return _scan_worker(
                settings,
                timeframes_raw=args.timeframes,
                universe=args.universe,
                bars=args.bars,
                lookback_days=args.lookback_days,
                poll_seconds=args.poll_seconds,
                scanners_path=args.scanners,
                notify=args.notify,
            )
        if args.command == "command-worker-once":
            return _command_worker_once(
                settings,
                timeframe=args.timeframe,
                bars=args.bars,
                scanners_path=args.scanners,
            )
        if args.command == "command-worker-loop":
            return _command_worker_loop(
                settings,
                timeframe=args.timeframe,
                bars=args.bars,
                scanners_path=args.scanners,
                interval=args.interval,
            )
        if args.command == "command-jobs-status":
            return _command_jobs_status(settings, limit=args.limit)
        if args.command == "news-kap-sync":
            return _news_kap_sync(
                settings,
                lookback_days=args.lookback_days,
                notify=args.notify,
            )
        if args.command == "news-kap-backfill":
            return _news_kap_backfill(
                settings,
                days=args.days,
                chunk_days=args.chunk_days,
            )
        if args.command == "news-general-sync":
            return _news_general_sync(
                settings,
                lookback_days=args.lookback_days,
                sources_raw=args.sources,
                notify=args.notify,
            )
        if args.command == "telegram-smoke-symbol":
            return _telegram_smoke_symbol(
                settings,
                symbol=args.symbol,
                confirm_live=args.confirm_live,
            )
    except (RuntimeError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2
    parser.error("Bilinmeyen komut")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
