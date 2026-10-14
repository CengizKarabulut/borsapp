#!/usr/bin/env python3
"""Prepare a closed-session ATC report from actual exported scanner evaluations.

Never send stale or incomplete data as a complete-market signal summary.
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings
from market_intelligence.delivery.telegram.routing import PublicationKind, TopicRouter
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository

ISTANBUL = ZoneInfo("Europe/Istanbul")
EXCLUDED = frozenset({
    "VERI_YOK", "DESTEKLENMIYOR", "HESAPLANAMADI",
    "SURUM_UYUSMAZLIGI", "ESLESME_YON_BELIRSIZ",
})
SIGNAL_STATES = frozenset({"POZITIF", "NEGATIF", "NOTR", "KARMA"})


def prepare_daily_report(rows, *, as_of, min_fresh_ratio=0.95):
    """Return (text, coverage) for a fresh 1d session, or raise for bad coverage."""
    if not 0 < min_fresh_ratio <= 1:
        raise ValueError("min_fresh_ratio 0 ile 1 arasında olmalıdır")
    daily = [r for r in rows if r["ZamanDilimi"] == "1d"]
    symbols = {r["Hisse"] for r in daily}
    if not symbols:
        raise ValueError("Günlük veri matrisi boş")
    fresh = []
    for row in daily:
        timestamp = row.get("MumKapanisiUTC") or ""
        if not timestamp:
            continue
        try:
            bar_time = datetime.fromisoformat(timestamp)
        except ValueError:
            continue
        if bar_time.tzinfo is None:
            continue
        if bar_time.astimezone(ISTANBUL).date() == as_of:
            if row["Durum"] not in EXCLUDED:
                fresh.append(row)
    fresh_symbols = {r["Hisse"] for r in fresh}
    ratio = len(fresh_symbols) / len(symbols)
    if ratio < min_fresh_ratio:
        raise ValueError(
            f"Güncel tarama kapsamı %{ratio * 100:.1f} ({len(fresh_symbols)}/{len(symbols)}); "
            f"asgari %{min_fresh_ratio * 100:.0f}. Eski/verisiz sonuç Telegram'a gönderilmez."
        )
    by_scanner = defaultdict(Counter)
    for r in fresh:
        by_scanner[int(r["TaramaNo"])][r["Durum"]] += 1
    lines = [
        f"ATC | BIST tarama özeti | {as_of:%d.%m.%Y}",
        f"Güncel değerlendirilen: {len(fresh_symbols)}/{len(symbols)} hisse",
        "Yalnız teyitli günlük mumlar | al-sat önerisi değildir",
    ]
    for number in range(1, 19):
        counts = by_scanner[number]
        lines.append(
            f"{number:02d}: +{counts['POZITIF']} "
            f"-{counts['NEGATIF']} nötr {counts['NOTR']} "
            f"karma {counts['KARMA']} / değerlendirilen {sum(counts.values())}"
        )
    lines.append("Koşul sayısı başarı olasılığı ya da getiri garantisi değildir.")
    return "\n".join(lines), {
        "expected_symbols": len(symbols),
        "fresh_symbols": len(fresh_symbols),
        "fresh_ratio": ratio,
        "matched_conditions": sum(
            counts[k] for counts in by_scanner.values() for k in SIGNAL_STATES
        ),
    }


def enqueue_report(db, env, *, as_of, text):
    settings = TelegramSettings.from_mapping(env)
    if settings.delivery_mode is not DeliveryMode.LIVE:
        raise ValueError("Telegram raporlaması için DELIVERY_MODE=live olmalıdır")
    envelope = TopicRouter(settings).route(
        publication_kind=PublicationKind.REPORT,
        semantic_identity={
            "source": "atc-cloud-eod",
            "session": as_of.isoformat(),
            "report_version": 1,
        },
        payload={"text": text},
    )
    return PostgresOutboxRepository(db).enqueue((envelope,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--as-of", type=str, default=None)
    parser.add_argument("--min-fresh-ratio", type=float, default=0.95)
    parser.add_argument("--queue-telegram", action="store_true")
    args = parser.parse_args()
    with args.csv.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    session_date = (
        datetime.fromisoformat(args.as_of).date()
        if args.as_of
        else datetime.now(ISTANBUL).date()
    )
    report, coverage = prepare_daily_report(
        rows, as_of=session_date, min_fresh_ratio=args.min_fresh_ratio
    )
    print(
        f"ATC kontrol: {coverage['fresh_symbols']}/{coverage['expected_symbols']} "
        f"hisse güncel; {coverage['matched_conditions']} tarama eşleşmesi"
    )
    if args.queue_telegram:
        database_url = os.getenv("DATABASE_URL", "")
        if not database_url:
            parser.error("DATABASE_URL secret eksik")
        import psycopg

        with psycopg.connect(database_url) as db:
            inserted = enqueue_report(db, os.environ, as_of=session_date, text=report)
        print(f"Telegram Raporlar konusuna outbox kuyruğu: {inserted} yeni ileti")


if __name__ == "__main__":
    main()
