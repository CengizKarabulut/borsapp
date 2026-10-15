"""ATC visual results: one confirmation-only PNG summary per existing timeframe topic.

Render from persisted scan_evaluations, never from synthetic/unverified matches.
The Telegram thread ID must be supplied by the EXISTING GitHub topic settings.
"""
from __future__ import annotations

import argparse
import base64
import io
import os
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from market_intelligence.core.timeframes import Timeframe, parse_timeframe
from market_intelligence.delivery.telegram.config import TelegramSettings
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.delivery.telegram.publisher import TelegramPublisher
from market_intelligence.delivery.telegram.timeframe_topics import (
    route_timeframe_image,
    timeframe_topic_ids,
)
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository
from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_export_dashboard import LATEST_SQL, SCANNER_ORDER, status_label
from scripts.atc_publish_targeted import AtcOnlyOutbox

ISTANBUL = ZoneInfo("Europe/Istanbul")
COLORS = {"POZITIF": "#177A4F", "NEGATIF": "#B83636",
          "NOTR": "#A56C21", "KARMA": "#6366A3"}
MATCH_STATES = frozenset(COLORS)
MAX_ROWS_PER_CARD = 20
MAX_CARDS = 10


def _font(size, *, bold=False):
    from pathlib import Path

    names = (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
         if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
         if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def render_card_png(*, timeframe: str, bar_time: datetime, rows: list[tuple[str, int, str]],
                    matched_count: int, total_symbols: int, page: int, pages: int) -> bytes:
    """Use saved, consistent typography; no artificial/generated market prices."""
    width = 1080
    height = 310 + max(1, len(rows)) * 46 + 72
    img = Image.new("RGB", (width, height), "#EDF2F7")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((20, 20, width - 20, height - 20), radius=20, fill="#FFFFFF")
    draw.rectangle((20, 20, width - 20, 105), fill="#102C46")
    title = f"ALPHA TREND CIPHER · {timeframe.upper()} TARAMA"
    draw.text((52, 38), title, font=_font(27, bold=True), fill="#FFFFFF")
    draw.text((52, 136), f"Teyitli mum: {bar_time.astimezone(ISTANBUL):%d.%m.%Y %H:%M} TSİ",
              font=_font(21), fill="#26374C")
    draw.text((52, 181), f"Değerlendirilen: {total_symbols}/630 hisse  ·  Eşleşme: {matched_count}",
              font=_font(21, bold=True), fill="#26374C")
    draw.text((52, 229), "HISSE", font=_font(19, bold=True), fill="#51687D")
    draw.text((340, 229), "KOSUL", font=_font(19, bold=True), fill="#51687D")
    draw.text((805, 229), "YON", font=_font(19, bold=True), fill="#51687D")
    draw.line((52, 260, 1025, 260), fill="#D5DFE8", width=2)
    for index, (symbol, number, state) in enumerate(rows):
        top = 267 + index * 46
        if index % 2 == 0:
            draw.rounded_rectangle((43, top, 1036, top + 44),
                                   radius=6, fill="#F5F8FB")
        draw.text((54, top + 10), "#" + symbol, font=_font(19, bold=True),
                  fill="#17304C")
        label = SCANNER_ORDER[number - 1].split(".")[-1].replace("_", " ")
        draw.text((340, top + 10), f"{number:02d}  {label[:32]}",
                  font=_font(19), fill="#33485B")
        draw.text((805, top + 10), state,
                  font=_font(19, bold=True), fill=COLORS[state])
    draw.text((52, height - 76), f"Sayfa {page}/{pages} · ATC teyitli tarama",
              font=_font(19), fill="#60748A")
    draw.text((52, height - 45), "Bilgilendirme amaçlıdır, yatırım tavsiyesi değildir.",
              font=_font(16), fill="#60748A")
    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


def select_verified_matches(members, evaluations, bindings, timeframe, *, now):
    tf = parse_timeframe(timeframe)
    permitted = {b.scanner.id: b for b in bindings if tf in b.shadow_timeframes}
    member_ids = {str(m.instrument_id): m.symbol for m in members}
    latest = [ev for ev in evaluations if ev[1] == tf.value
              and str(ev[0]) in member_ids and ev[2] in permitted]
    if not latest:
        raise ValueError(f"{tf.value}: no completed scanner evaluations")
    close = max(ev[5] for ev in latest)
    if close > now:
        raise ValueError("Future bar timestamp in scan records")
    max_age = timedelta(days=11 if tf is Timeframe.W1 else 5 if tf is Timeframe.D1
                        else 2)
    if now - close > max_age:
        raise ValueError(f"{tf.value}: latest completed bar is stale")
    todays = [ev for ev in latest if ev[5] == close]
    covered = {str(ev[0]) for ev in todays}
    if len(covered) < int(len(members) * .9):
        raise ValueError(
            f"{tf.value}: confirmed bar coverage too low: {len(covered)}/{len(members)}"
        )
    matches = []
    for ev in todays:
        instrument_id, _, scanner_id, version, ruleset, _bar, status, _err, _eid, directions = ev
        bind = permitted[scanner_id]
        if bind.scanner.version != version or bind.ruleset_hash != ruleset:
            continue
        label = status_label(status, directions or ())
        if label in MATCH_STATES:
            matches.append((member_ids[str(instrument_id)],
                            SCANNER_ORDER.index(scanner_id) + 1, label))
    return close, len(covered), sorted(
        set(matches), key=lambda x: (x[1], x[0], x[2])
    )


def publish_timeframe(timeframe: str, *, now=None) -> dict:
    import psycopg

    now = now or datetime.now(ISTANBUL)
    settings = TelegramSettings.from_mapping({**os.environ, "DELIVERY_MODE": "live"})
    topic_ids = timeframe_topic_ids(os.environ)
    tf = parse_timeframe(timeframe)
    if tf not in topic_ids:
        raise ValueError(
            f"{tf.value} icin eski Telegram topic ID GitHub ortaminda bulunamadi. "
            "Yeni topic acilmadi, genel topic'e gonderilmedi."
        )
    uri = os.environ.get("DATABASE_URL", "")
    if not uri:
        raise ValueError("DATABASE_URL missing")
    with psycopg.connect(uri) as db:
        members = PostgresRuntimeRepository(db).list_universe("ATC_630", as_of=now.date())
        if len(members) != 630:
            raise ValueError(f"Expected 630 watched symbols, got {len(members)}")
        bindings = load_scanner_catalog(
            "config/scanners.toml", calendar_version=ExchangeCalendarsXist().version
        )
        with db.cursor() as cur:
            cur.execute(LATEST_SQL, ("ATC_630", [m.instrument_id for m in members]))
            ev = cur.fetchall()
        bar_time, covered, matches = select_verified_matches(
            members, ev, bindings, tf.value, now=now
        )
        if not matches:
            print(f"Visual scanner {tf.value}: 0 matches; no empty/fabricated image", flush=True)
            return {"bar_time": bar_time.isoformat(), "covered": covered, "matches": 0,
                    "sent": 0}
        rows = matches[:MAX_ROWS_PER_CARD * MAX_CARDS]
        pages = (len(rows) + MAX_ROWS_PER_CARD - 1) // MAX_ROWS_PER_CARD
        envelopes = []
        for i in range(pages):
            page_rows = rows[i * MAX_ROWS_PER_CARD:(i + 1) * MAX_ROWS_PER_CARD]
            pic = render_card_png(
                timeframe=tf.value, bar_time=bar_time, rows=page_rows,
                matched_count=len(matches), total_symbols=covered,
                page=i + 1, pages=pages,
            )
            envelopes.append(route_timeframe_image(
                settings, topic_ids, tf,
                identity={
                    "source": "atc-timeframe-visual-v1",
                    "timeframe": tf.value,
                    "bar_close": bar_time.isoformat(), "page": i + 1,
                },
                payload={
                    "_method": "sendPhoto",
                    "photo_base64": base64.b64encode(pic).decode("ascii"),
                    "filename": f"ATC_{tf.value}_{i + 1}.png",
                    "caption": (
                        f"ATC {tf.value.upper()} | "
                        f"{bar_time.astimezone(ISTANBUL):%d.%m.%Y %H:%M} TSİ | "
                        f"Teyitli {covered}/630 | {len(matches)} koşul eşleşmesi | "
                        f"Sayfa {i + 1}/{pages} · YTD"
                    ),
                },
            ))
        inserted = PostgresOutboxRepository(db).enqueue(tuple(envelopes), ordered=True)
        # Reuse the targeted-only queue implementation; never flush old news.
        outbox = AtcOnlyOutbox(db, [e.semantic_key for e in envelopes])
        result = TelegramPublisher(
            settings=settings, repository=outbox,
            transport=HttpxTelegramTransport(settings.bot_token),
        ).publish_batch(now=now, limit=len(envelopes))
        with db.cursor() as cur:
            cur.execute(
                "SELECT semantic_key, status FROM telegram_outbox "
                "WHERE semantic_key=ANY(%s::text[])",
                ([e.semantic_key for e in envelopes],),
            )
            states = dict(cur.fetchall())
        if (len(states) != len(envelopes)
                or any(states.get(e.semantic_key) != "sent" for e in envelopes)):
            raise RuntimeError(
                f"ATC {tf.value} image was not delivered to its existing topic: "
                f"sent={result.sent}, failed={result.failed}, states={list(states.values())}"
            )
    summary = {"timeframe": tf.value, "covered": covered, "matches": len(matches),
               "new_queued": inserted, "pages": pages, "sent_new": result.sent}
    print(f"ATC visual result: {summary}", flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", required=True)
    args = parser.parse_args()
    publish_timeframe(args.timeframe)


if __name__ == "__main__":
    main()
