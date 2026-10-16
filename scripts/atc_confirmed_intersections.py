"""ATC Kesişim: Telegram topic 28330, database-confirmed multi-timeframe only.

At least two different same-direction scanner rules must agree INSIDE each
timeframe; a symbol must meet that condition in at least two fresh timeframes.
Neither provisional candles nor fictitious prices are used here.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.application.scan_intersections import (
    cross_timeframe_intersections,
    render_intersections,
)
from market_intelligence.core.identity import stable_hash
from market_intelligence.delivery.telegram.config import TelegramSettings, TopicKind
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.delivery.telegram.publisher import TelegramPublisher
from market_intelligence.delivery.telegram.routing import OutboxEnvelope, PublicationKind
from market_intelligence.delivery.telegram.timeframe_topics import (
    existing_intersection_topic_id,
)
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository
from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scanning.display_codes import scanner_code_from_id
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_export_dashboard import LATEST_SQL, SCANNER_ORDER
from scripts.atc_publish_targeted import AtcOnlyOutbox
from scripts.atc_timeframe_visuals import select_verified_matches

ISTANBUL = ZoneInfo("Europe/Istanbul")
_ALLOWED = frozenset(("POZITIF", "NEGATIF"))


def build_confirmed_intersections(members, evaluations, bindings, timeframes, *, now):
    """Return ranked fully confirmed intersections; skip incomplete frame lanes.

    Direction labels are derived solely from persisted scan evaluations with
    current scanner versions/hashes; mixed/neutral/unknown are excluded.
    """
    all_details, closings, coverage, issues = {}, {}, {}, {}
    for timeframe in tuple(dict.fromkeys(timeframes)):
        try:
            close, covered, matches = select_verified_matches(
                members, evaluations, bindings, timeframe, now=now,
            )
        except ValueError as exc:
            issues[timeframe] = str(exc)[:180]
            continue
        details = []
        for symbol, number, state in matches:
            if state not in _ALLOWED:
                continue
            details.append({
                "symbol": symbol,
                "scanner": SCANNER_ORDER[number - 1],
                "direction": "bullish" if state == "POZITIF" else "bearish",
                "plan": {"scenarios": [], "price_basis": "unknown"},
            })
        all_details[timeframe] = details
        closings[timeframe] = close
        coverage[timeframe] = covered
    if len(all_details) < 2:
        raise ValueError(
            f"At least two sufficiently covered, fresh, verified timeframes are "
            f"required; got {list(all_details)}; excluded={issues}"
        )
    # limit=None guarantees full set; image renderer can show top-20 while
    # the accompanying CSV captures every eligible intersection.
    ranked = cross_timeframe_intersections(all_details, limit=None)
    return ranked, closings, coverage, issues


def export_intersections_csv(ranked, closings, *, generated):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow((
        "Hisse", "Yon", "ZamanDilimiSayisi", "TaramaSayisi", "ZamanDilimleri",
        "TaramaKodlari", "ZitYonZamanDilimleri", "KapanislarTSI", "RaporSaatiTSI",
    ))
    close_labels = {
        tf: value.astimezone(ISTANBUL).isoformat()
        for tf, value in closings.items()
    }
    for item in ranked:
        frames = sorted(item["timeframes"])
        writer.writerow((
            item["symbol"], "LONG" if item["direction"] == "bullish" else "SHORT",
            item["timeframe_count"], item["count"], ",".join(frames),
            ",".join(scanner_code_from_id(name) for name in item["scanners"]),
            ",".join(item["opposing_timeframes"]),
            "; ".join(f"{tf}={close_labels[tf]}" for tf in frames),
            generated.astimezone(ISTANBUL).isoformat(),
        ))
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def make_envelopes(settings, topic_id, *, ranked, closings, coverage, now):
    if not ranked:
        # A genuinely empty result is still a useful and truthful summary.
        print("Confirmed intersection: no two-timeframe qualifying symbols", flush=True)
    targets = {
        tf: f"{close.astimezone(ISTANBUL):%d.%m.%Y %H:%M} TSİ"
        for tf, close in closings.items()
    }
    scoped = ", ".join(f"{tf} {coverage[tf]}/630" for tf in sorted(coverage))
    pngs, _pdf = render_intersections(
        "GENEL KESİŞİM", ranked[:20], now,
        targets=targets, coverage=scoped, global_view=True,
    )
    csv_bytes = export_intersections_csv(ranked, closings, generated=now)
    identity = {
        "source": "atc-confirmed-intersections-v1",
        "bars": {tf: value.isoformat() for tf, value in sorted(closings.items())},
    }
    common = (
        f"ATC KESİŞİM · {len(ranked)} uygun hisse · {scoped}. "
        "En az 2 farklı aynı yönlü tarama ve en az 2 zaman dilimi. "
        "Kesişim sayısı başarı olasılığı değildir; YTD."
    )
    media = []
    for index, png in enumerate(pngs, 1):
        media.append(("photo", index, {
            "_method": "sendPhoto",
            "photo_base64": base64.b64encode(png).decode("ascii"),
            "filename": f"ATC_KESISIM_{index}.png",
            "caption": common + f" · Sayfa {index}/{len(pngs)}; tam liste CSV'de.",
        }))
    media.append(("csv", 0, {
        "_method": "sendDocument",
        "document_base64": base64.b64encode(csv_bytes).decode("ascii"),
        "filename": f"ATC_KESISIM_{now:%Y%m%d}.csv",
        "caption": common + " · Tüm uygun hisseler, kapanış zamanları ve zıt yönler.",
    }))
    envelopes = []
    for kind, page, payload in media:
        key = stable_hash({
            "channel": "telegram",
            "publication_kind": PublicationKind.CONFLUENCE.value,
            "chat_id": settings.chat_id, "message_thread_id": topic_id,
            "semantic_identity": {**identity, "media": kind, "page": page},
        })
        envelopes.append(OutboxEnvelope(
            semantic_key=key, publication_kind=PublicationKind.CONFLUENCE,
            topic_kind=TopicKind.SCANS, chat_id=settings.chat_id,
            message_thread_id=topic_id, payload=payload,
        ))
    return tuple(envelopes)


def publish_confirmed_intersections(timeframes=("1h", "1d"), *, now=None):
    import psycopg

    now = now or datetime.now(ISTANBUL)
    values = {**os.environ, "DELIVERY_MODE": "live"}
    settings = TelegramSettings.from_mapping(values)
    topic_id = existing_intersection_topic_id(values)
    if topic_id is None:
        raise ValueError("Only the verified original Kesişim topic can receive this report")
    if len(set(timeframes)) < 2:
        raise ValueError("Cross-timeframe report requires at least two timeframes")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    with psycopg.connect(database_url, autocommit=True) as db:
        members = PostgresRuntimeRepository(db).list_universe("ATC_630", as_of=now.date())
        if len(members) != 630:
            raise ValueError(f"ATC_630 requires exactly 630 current members; got {len(members)}")
        bindings = load_scanner_catalog(
            Path("config/scanners.toml"), calendar_version=ExchangeCalendarsXist().version,
        )
        if len(bindings) != 18:
            raise ValueError("18 original scanner rules required")
        with db.cursor() as cursor:
            cursor.execute(LATEST_SQL, ("ATC_630", [m.instrument_id for m in members]))
            evaluations = cursor.fetchall()
        ranked, closings, coverage, issues = build_confirmed_intersections(
            members, evaluations, bindings, timeframes, now=now,
        )
        print(f"Confirmed intersections: {len(ranked)} symbols; coverage={coverage}, "
              f"excluded_timeframes={issues}", flush=True)
        envelopes = make_envelopes(
            settings, topic_id, ranked=ranked,
            closings=closings, coverage=coverage, now=now,
        )
        queued = PostgresOutboxRepository(db).enqueue(envelopes, ordered=True)
        publisher = TelegramPublisher(
            settings=settings,
            repository=AtcOnlyOutbox(db, [e.semantic_key for e in envelopes]),
            transport=HttpxTelegramTransport(settings.bot_token),
        )
        outcome = publisher.publish_batch(now=datetime.now(ISTANBUL), limit=len(envelopes))
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT semantic_key, status, telegram_message_id FROM telegram_outbox "
                "WHERE semantic_key=ANY(%s::text[])", ([e.semantic_key for e in envelopes],),
            )
            statuses = {key: (state, msgid) for key, state, msgid in cursor.fetchall()}
        if any(statuses.get(e.semantic_key, (None,))[0] != "sent" for e in envelopes):
            raise RuntimeError(
                f"Some real Kesişim messages not delivered: {outcome.sent} sent, "
                f"{outcome.failed} failed; errors={outcome.error_samples[:3]}"
            )
        for e in envelopes:
            message_id = statuses[e.semantic_key][1]
            print(f"Kesişim delivered: https://t.me/c/4439315048/{topic_id}/{message_id}", flush=True)
        return {"count": len(ranked), "coverage": coverage, "queued": queued,
                "sent": outcome.sent}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframes", default="1h,1d")
    args = parser.parse_args()
    publish_confirmed_intersections(
        tuple(x.strip() for x in args.timeframes.split(",") if x.strip()),
    )


if __name__ == "__main__":
    main()
