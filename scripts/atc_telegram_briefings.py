#!/usr/bin/env python3
"""Morning 630-share pivot report, intraday what-if preview, and confirmed EOD.

The what-if pipeline NEVER writes provisional bars, scan evaluations or alerts
into the confirmed scanner stores. It reuses original scanner math on a
momentary bar snapshot and labels it TEYITSIZ on every Telegram message.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.cli import _feature_engine, _market_data_provider
from market_intelligence.settings import ApplicationSettings
from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.core.identity import stable_hash
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.delivery.telegram.config import TelegramSettings
from market_intelligence.delivery.telegram.routing import PublicationKind, TopicRouter
from market_intelligence.market_data.canonicalizer import Canonicalizer
from market_intelligence.market_data.providers import FetchRequest
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository
from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.persistence.postgres.snapshots import PostgresSnapshotStore
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scanning.contracts import ScanContext
from market_intelligence.scanning.pipeline import ScanPipeline
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_cloud_summary import prepare_daily_report
from scripts.atc_export_dashboard import export_matrix

ISTANBUL = ZoneInfo("Europe/Istanbul")
SCANNER_LABELS = (
    "MACD pozitif", "SMI/MACD", "SMI/MACD hacim", "EMA trend",
    "RSI/MACD hacim", "SMA/MACD hacim", "SMI tam", "SMI erken",
    "RSI momentum", "Hacim patlaması", "Sıkışma hacim", "Uç RSI",
    "Başarısız kırılım", "Karar bölgesi", "Trend devamı", "Tükenme",
    "Karar paneli", "MA yakınlığı",
)


def pivot_levels(high: float, low: float, close: float) -> tuple[float, ...]:
    """Classic floor pivots based on the previous CONFIRMED daily candle."""
    if not (0 < low <= close <= high):
        raise ValueError("Previous-day OHLC is inconsistent")
    pivot = (high + low + close) / 3
    return (
        2 * pivot - high,
        pivot - (high - low),
        pivot,
        2 * pivot - low,
        pivot + (high - low),
    )  # S1, S2, Pivot, R1, R2


def last_closed_session(calendar, today):
    dates = calendar.sessions(today - timedelta(days=14), today - timedelta(days=1))
    if not dates:
        raise ValueError("No previous BIST session in calendar")
    return dates[-1]


def build_morning_rows(connection, *, now):
    calendar = ExchangeCalendarsXist()
    last_session = last_closed_session(calendar, now.date())
    members = PostgresRuntimeRepository(connection).list_universe("ATC_630", as_of=now.date())
    if len(members) != 630:
        raise ValueError(f"ATC_630 membership incomplete: {len(members)}/630")
    storage = PostgresSnapshotStore(connection)
    result = []
    for member in members:
        item = storage.load_recent_bars(
            instrument_id=member.instrument_id, as_of=now, timeframe="1d", limit=1
        )
        bar = item.bars[-1] if item else None
        if bar is None or bar.close_time.astimezone(ISTANBUL).date() != last_session:
            result.append((member.symbol, None, None, "VERI_YOK"))
            continue
        try:
            levels = pivot_levels(bar.high, bar.low, bar.close)
        except ValueError:
            result.append((member.symbol, None, None, "VERI_HATASI"))
            continue
        result.append((member.symbol, levels, bar.close * bar.volume, "TEYITLI"))
    return last_session, result


def morning_messages(last_session, rows):
    valid = [(symbol, levels, turnover) for symbol, levels, turnover, status in rows if status == "TEYITLI"]
    if len(valid) < 0.90 * len(rows):
        raise ValueError(f"Previous confirmed close coverage insufficient: {len(valid)}/{len(rows)}")
    ranking = sorted(valid, key=lambda r: r[2] or 0, reverse=True)[:20]
    title = f"ATC | Sabah destek–direnç | {last_session:%d.%m.%Y} kapanışı"
    lines = [
        title, f"630 hisse · teyitli {len(valid)} · veri eksik {len(rows)-len(valid)}",
        "Klasik pivot yöntemi: D1 önceki seans H/L/C; tahmini al-sat seviyesi değildir.",
        "Hacim ağırlığı değil, önceki gün kapanış × pay hacmine göre ilk 20:",
    ]
    for symbol, (s1, s2, p, r1, r2), _ in ranking:
        lines.append(f"#{symbol}  S2 {s2:.2f} | S1 {s1:.2f} | P {p:.2f} | R1 {r1:.2f} | R2 {r2:.2f}")
    lines.append("Tüm 630 sembolün değerleri ekteki CSV dosyasında. Bilgilendirme amaçlıdır.")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(("Hisse", "KapanisTarihi", "S2", "S1", "Pivot", "R1", "R2", "Durum"))
    for symbol, levels, _, status in sorted(rows):
        prices = ("", "", "", "", "") if levels is None else (
            f"{levels[1]:.4f}", f"{levels[0]:.4f}", f"{levels[2]:.4f}",
            f"{levels[3]:.4f}", f"{levels[4]:.4f}",
        )
        writer.writerow((symbol, last_session.isoformat(), *prices, status))
    return "\n".join(lines), ("\ufeff" + output.getvalue()).encode("utf-8")


def make_daily_preview_frame(connection, member, settings, *, now):
    """Use today's ACTUAL live provider snapshot as a temporary hypothetical close.

    We deliberately ask the vendor for a candle at a theoretical session-end
    cutoff only to include its current mutable daily candle in its usual filter.
    The returned bar must start TODAY. No synthetic future prices are made.
    """
    from market_intelligence.market_data.bars import CanonicalFrame

    schedule = Canonicalizer().schedule
    session_open, session_close = schedule.session_bounds(now.date())
    if not session_open <= now < session_close:
        raise ValueError("Outside live BIST session")
    store = PostgresSnapshotStore(connection)
    cache = store.load_recent_bars(
        instrument_id=member.instrument_id, as_of=now,
        timeframe="1d", limit=600,
    )
    if cache is None or len(cache.bars) < 30:
        raise ValueError("Not enough persisted historical daily candles")
    provider = _market_data_provider(settings)
    raw = provider.fetch_from_source(
        cache.source,
        FetchRequest(
            provider_symbol=member.provider_symbol,
            timeframe=Timeframe.D1,
            bars=2,
            as_of=session_close + timedelta(minutes=1),
        ),
    )
    if raw.price_basis != cache.price_basis or raw.provider != cache.source:
        raise ValueError("Live provider series differs from confirmed archive")
    recent = Canonicalizer().build(
        instrument_id=member.instrument_id,
        symbol_at_snapshot=member.symbol,
        market=member.market,
        provider_frame=raw,
        target_timeframe=Timeframe.D1,
        series_revision=cache.series_revision,
    )
    today = [bar for bar in recent.bars if bar.open_time.date() == now.date()]
    if len(today) != 1 or today[0].close_time != session_close:
        raise ValueError("Provider did not return today's mutable daily candle")
    old_bars = tuple(b for b in cache.bars if b.close_time <= session_open)
    bars = (old_bars[-599:] + (today[0],))[-600:]
    identity = stable_hash({
        "kind": "atc-intraday-only-what-if",
        "symbol": member.symbol, "now": now.isoformat(),
        "source": cache.source, "bars": bars,
    })
    # Scanner math intentionally runs on the temporary "what if this closed now"
    # frame. is_partial=False is scoped ONLY to this in-memory preview pipeline.
    # Never hand this frame to PostgresSnapshotStore or ScanFrameCoordinator.
    return CanonicalFrame(
        instrument_id=member.instrument_id,
        symbol_at_snapshot=member.symbol,
        market=member.market,
        timeframe=Timeframe.D1,
        snapshot_id=identity,
        series_revision=cache.series_revision,
        price_basis=cache.price_basis,
        source=cache.source,
        bars=bars,
        is_partial=False,
        quality="PROVISIONAL_WHAT_IF_NOT_PERSISTED",
    )


def preview_for_member(member, *, settings, now, bindings, calendar_version):
    import psycopg

    with psycopg.connect(settings.runtime.database_url, autocommit=True) as db:
        frame = make_daily_preview_frame(db, member, settings, now=now)
        pipeline = ScanPipeline(_feature_engine(db))
        results = []
        for number, binding in enumerate(bindings, 1):
            if Timeframe.D1 not in binding.shadow_timeframes:
                continue
            context = ScanContext(
                evaluation_time=now, bar_close_time=frame.through_bar_time,
                market_session_id=f"BIST:{now.date()}",
                calendar_version=calendar_version,
                ruleset_hash=binding.ruleset_hash,
            )
            scan = pipeline.run(
                cycle_id="UNPERSISTED_INTRADAY_PREVIEW",
                frame=frame, scanner=binding.scanner, context=context,
            ).scan
            if scan.evaluation.status is EvaluationStatus.MATCH:
                results.append((number, tuple(f.direction.value for f in scan.findings)))
        return member.symbol, results


def summarize_preview(finished, *, now, expected=630):
    matches = Counter()
    symbols = {}
    for symbol, scans in finished:
        for number, directions in scans:
            matches[number] += 1
            symbols.setdefault(number, []).append(symbol)
    lines = [
        f"ATC | CANLI / TEYİTSİZ | {now:%d.%m.%Y %H:%M} TSİ",
        f"Günlük mum şu anda kapansaydı: {len(finished)}/{expected} hisse değerlendirildi.",
        "Bu sonuçlar mum oluşurken değişebilir. Kesin kapanış sinyali değildir.",
    ]
    for number in range(1, 19):
        if matches[number]:
            symbols_now = sorted(set(symbols[number]))
            preview_symbols = ", ".join("#" + s for s in symbols_now[:7])
            lines.append(f"{number:02d} {SCANNER_LABELS[number-1]}: {matches[number]} ({preview_symbols})")
    if not any(matches.values()):
        lines.append("Bu saatte koşula uyan tarama bulunmadı.")
    lines.append("Kesin sonuçlar kapanış sonrası yeniden hesaplanacak. Yatırım tavsiyesi değildir.")
    return "\n".join(lines), sum(matches.values())


def enqueue(connection, *, now, identity, publications):
    settings = TelegramSettings.from_mapping({**os.environ, "DELIVERY_MODE": "live"})
    router = TopicRouter(settings)
    envelopes = tuple(
        router.route(
            publication_kind=kind,
            semantic_identity={"source": "atc-bulletins-v1", "slot": identity, "part": index},
            payload=payload,
        )
        for index, (kind, payload) in enumerate(publications)
    )
    return PostgresOutboxRepository(connection).enqueue(envelopes, ordered=True)


def run_morning(connection, now):
    session_date, rows = build_morning_rows(connection, now=now)
    text, csv_bytes = morning_messages(session_date, rows)
    count = enqueue(connection, now=now, identity=f"morning:{session_date}",
        publications=[
            (PublicationKind.REPORT, {"text": text}),
            (PublicationKind.REPORT, {
                "_method": "sendDocument",
                "document_base64": base64.b64encode(csv_bytes).decode("ascii"),
                "filename": f"ATC_630_destek_direnc_{session_date}.csv",
                "caption": f"ATC 630 · {session_date} kapanışı · klasik pivot S2/S1/P/R1/R2",
            }),
        ])
    print(f"Morning pivot report: {len(rows)} watched, queued={count}", flush=True)


def run_preview(connection, settings, now, *, workers):
    calendar = ExchangeCalendarsXist()
    if now.date() not in calendar.sessions(now.date(), now.date()):
        print("No trading session today; no provisional market message", flush=True)
        return
    members = PostgresRuntimeRepository(connection).list_universe("ATC_630", as_of=now.date())
    if len(members) != 630:
        raise ValueError(f"Pinned market universe incomplete: {len(members)}/630")
    bindings = load_scanner_catalog(Path("config/scanners.toml"),
                                    calendar_version=calendar.version)
    finished, failures = [], Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(
                preview_for_member, member, settings=settings, now=now,
                bindings=bindings, calendar_version=calendar.version,
            ): member.symbol for member in members
        }
        for future in as_completed(future_map):
            try:
                finished.append(future.result())
            except Exception as exc:
                failures[type(exc).__name__] += 1
    if len(finished) < 0.80 * len(members):
        raise ValueError(
            f"Live partial OHLCV coverage too low: {len(finished)}/{len(members)} "
            f"(errors: {dict(failures)}); nothing sent"
        )
    text, hits = summarize_preview(finished, now=now, expected=len(members))
    # Slot IDs are stable for duplicate GitHub schedule retries.
    slot = now.replace(minute=0, second=0, microsecond=0)
    queued = enqueue(connection, now=now, identity=f"preview:{slot.isoformat()}",
                     publications=[(PublicationKind.SCAN_EVENT, {"text": text})])
    print(f"Intraday preview: {len(finished)}/630, {hits} matches, queued={queued}, "
          f"errors={dict(failures)}", flush=True)


def run_eod(connection, now):
    if now.hour < 19:
        raise ValueError("EOD report cannot run before confirmed market close")
    destination = Path("runtime_artifacts/ATC_Tarama_Matris.csv")
    export_matrix(connection, "ATC_630", "config/scanners.toml",
                  destination, as_of=now.date(), require_members=630)
    with destination.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    text, coverage = prepare_daily_report(
        rows, as_of=now.date(), min_fresh_ratio=0.95
    )
    queued = enqueue(
        connection, now=now, identity=f"eod:{now.date()}",
        publications=[(PublicationKind.REPORT, {"text": text})],
    )
    print(f"EOD confirmed coverage={coverage['fresh_symbols']}/630; queued={queued}",
          flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("morning", "preview", "eod"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("--workers must be 1–12")
    if not os.environ.get("DATABASE_URL"):
        parser.error("DATABASE_URL secret missing")
    import psycopg

    now = datetime.now(ISTANBUL)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
        if args.mode == "morning":
            run_morning(connection, now)
        elif args.mode == "preview":
            settings = ApplicationSettings.from_mapping({
                **os.environ, "DELIVERY_MODE": "disabled"
            })
            run_preview(connection, settings, now, workers=args.workers)
        else:
            run_eod(connection, now)


if __name__ == "__main__":
    main()
