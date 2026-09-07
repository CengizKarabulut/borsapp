from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import FrameType

from market_intelligence.application.ingestion import IngestionRequest, IngestionService
from market_intelligence.application.scan_frame import ScanFrameCoordinator
from market_intelligence.application.scheduled_scan import (
    ScheduledScanRequest,
    ScheduledScanService,
)
from market_intelligence.application.symbol_commands import SymbolCommandService
from market_intelligence.application.telegram_listener import TelegramListener
from market_intelligence.core.timeframes import parse_timeframe
from market_intelligence.delivery.telegram.config import DeliveryMode
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.delivery.telegram.publisher import TelegramPublisher
from market_intelligence.delivery.telegram.updates import HttpxTelegramUpdateSource
from market_intelligence.features.ma import QualifiedMaResearchProvider
from market_intelligence.features.momentum import MacdProvider, RsiProvider
from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.features.volume import RelativeVolume20Provider
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.persistence.postgres.ma_research import (
    PostgresMaQualificationSource,
)
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository
from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.persistence.postgres.scan_store import PostgresScanStore
from market_intelligence.persistence.postgres.snapshots import PostgresSnapshotStore
from market_intelligence.persistence.postgres.state_store import PostgresStateStore
from market_intelligence.persistence.postgres.symbol_commands import (
    PostgresLongJobQueue,
    PostgresSymbolReadStore,
)
from market_intelligence.persistence.postgres.telegram_updates import (
    PostgresTelegramUpdateRepository,
)
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scheduling.xist import ExchangeCalendarsXist, ScheduledBarPlanner
from market_intelligence.settings import ApplicationSettings, merged_environment


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

    init = subparsers.add_parser("db-init", help="PostgreSQL şemasını idempotent kur")
    init.add_argument(
        "--schema",
        type=Path,
        default=Path("db/postgres/001_initial.sql"),
    )

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

    scan = subparsers.add_parser(
        "scan-symbol",
        help="Bir sembolü tüm uygun scanner aileleriyle çalıştır",
    )
    scan.add_argument("symbol")
    scan.add_argument("--timeframe", default="1h")
    scan.add_argument("--bars", type=int, default=250)
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
    due.add_argument("--bars", type=int, default=250)
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
    worker.add_argument("--bars", type=int, default=250)
    worker.add_argument("--lookback-days", type=int, default=7)
    worker.add_argument("--poll-seconds", type=float, default=60.0)
    worker.add_argument("--scanners", type=Path, default=Path("config/scanners.toml"))
    worker.add_argument("--notify", action="store_true")
    return parser


def _connect(database_url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg kurulu değil; python -m pip install -e \".[runtime]\" çalıştırın"
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


def _db_init(settings: ApplicationSettings, schema_path: Path) -> int:
    if not schema_path.is_file():
        raise ValueError(f"Şema dosyası bulunamadı: {schema_path}")
    sql = schema_path.read_text(encoding="utf-8")
    with _connect(settings.runtime.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
    print("PostgreSQL şeması hazır.")
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
    return TelegramListener(
        settings=settings.telegram,
        source=HttpxTelegramUpdateSource(settings.telegram.bot_token),
        repository=PostgresTelegramUpdateRepository(connection),
        command_service=SymbolCommandService(
            PostgresSymbolReadStore(connection),
            PostgresLongJobQueue(connection),
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
        f"accepted={result.accepted}, ignored={result.ignored}"
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


def _feature_engine(connection) -> FeatureEngine:
    registry = FeatureRegistry()
    for provider in (
        RelativeVolume20Provider(),
        MacdProvider(),
        RsiProvider(),
        QualifiedMaResearchProvider(PostgresMaQualificationSource(connection)),
    ):
        registry.register(provider)
    return FeatureEngine(registry)


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
            provider=BorsapyProvider(timestamp_timezone=settings.runtime.timezone.key),
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
        coordinator = ScanFrameCoordinator(
            feature_engine=_feature_engine(connection),
            event_store=PostgresScanStore(connection),
            state_store=PostgresStateStore(connection),
            telegram_settings=effective_telegram,
        )
        result = coordinator.run(
            cycle_id=cycle_id,
            frame=frame,
            bindings=load_scanner_catalog(scanners_path),
            evaluation_time=evaluation_time,
        )
        runtime.finish_cycle(
            cycle_id=cycle_id,
            successful=1,
            stale=0,
            failed=0,
            finished_at=datetime.now(settings.runtime.timezone),
        )
    statuses = ", ".join(
        f"{run.evaluation.scanner_id}={run.evaluation.status.value}"
        for run in result.runs
    )
    print(
        f"Tarama tamamlandı: {instrument.symbol} {timeframe.value} "
        f"bar={frame.through_bar_time.isoformat()} · {statuses} · "
        f"events={result.event_count}, transitions={result.transition_count}, "
        f"outbox={result.outbox_count}"
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
        provider=BorsapyProvider(timestamp_timezone=settings.runtime.timezone.key),
        store=PostgresSnapshotStore(connection),
    )
    coordinator = ScanFrameCoordinator(
        feature_engine=_feature_engine(connection),
        event_store=PostgresScanStore(connection),
        state_store=PostgresStateStore(connection),
        telegram_settings=telegram,
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
    timeframes = tuple(
        part.strip() for part in timeframes_raw.split(",") if part.strip()
    )
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        values = merged_environment(os.environ, args.env_file)
        settings = ApplicationSettings.from_mapping(values)
        if args.command == "config-check":
            return _config_check(settings)
        if args.command == "db-init":
            return _db_init(settings, args.schema)
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
    except (RuntimeError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2
    parser.error("Bilinmeyen komut")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
