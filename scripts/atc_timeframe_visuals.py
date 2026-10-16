"""ATC visual results: one confirmation-only PNG summary per existing timeframe topic.

Render from persisted scan_evaluations, never from synthetic/unverified matches.
The Telegram thread ID must be supplied by the EXISTING GitHub topic settings.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import os
from datetime import datetime, timedelta
from pathlib import Path
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
from market_intelligence.scanning.display_codes import direction_display, scanner_code
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
                    matched_count: int, total_symbols: int, page: int, pages: int,
                    provisional: bool = False, visible_count: int | None = None) -> bytes:
    """Use saved, consistent typography; no artificial/generated market prices."""
    width = 1080
    height = 310 + max(1, len(rows)) * 46 + 72
    img = Image.new("RGB", (width, height), "#EDF2F7")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((20, 20, width - 20, height - 20), radius=20, fill="#FFFFFF")
    draw.rectangle((20, 20, width - 20, 105), fill="#102C46")
    kind = "CANLI / TEYİTSİZ" if provisional else "TEYİTLİ"
    title = f"ALPHA TREND CIPHER · {timeframe.upper()} TARAMA"
    draw.text((52, 38), title, font=_font(27, bold=True), fill="#FFFFFF")
    draw.text((52, 136), f"{kind} · {bar_time.astimezone(ISTANBUL):%d.%m.%Y %H:%M} TSİ",
              font=_font(21), fill="#26374C")
    draw.text((52, 181), f"Değerlendirilen: {total_symbols}/630 hisse  ·  Eşleşme: {matched_count}",
              font=_font(21, bold=True), fill="#26374C")
    draw.text((52, 229), "HISSE", font=_font(19, bold=True), fill="#51687D")
    draw.text((340, 229), "KOD", font=_font(19, bold=True), fill="#51687D")
    draw.text((805, 229), "YÖN", font=_font(19, bold=True), fill="#51687D")
    draw.line((52, 260, 1025, 260), fill="#D5DFE8", width=2)
    if not rows and matched_count == 0:
        draw.text((53, 290), "Teyitli kapanışta eşleşen koşul yok.",
                  font=_font(23, bold=True), fill="#52697F")
    for index, (symbol, number, state) in enumerate(rows):
        top = 267 + index * 46
        if index % 2 == 0:
            draw.rounded_rectangle((43, top, 1036, top + 44),
                                   radius=6, fill="#F5F8FB")
        draw.text((54, top + 10), "#" + symbol, font=_font(19, bold=True),
                  fill="#17304C")
        # Pine labels original 1-9 as A-I; rules 10-18 retain numbers.
        # The chart never reveals indicator names, thresholds or formulae.
        draw.text((340, top + 10), scanner_code(number),
                  font=_font(21, bold=True), fill="#33485B")
        draw.text((805, top + 10), direction_display(state),
                  font=_font(19, bold=True), fill=COLORS[state])
    shown = visible_count if visible_count is not None else matched_count
    footer = (f"Sayfa {page}/{pages} · {shown}/{matched_count} eşleşme görselde"
              if shown != matched_count else f"Sayfa {page}/{pages} · {kind} tarama")
    draw.text((52, height - 76), footer,
              font=_font(19), fill="#60748A")
    disclaimer = ("Geçici senaryodur; mum kapanınca değişebilir. YTD."
                  if provisional else "Bilgilendirme amaçlıdır, yatırım tavsiyesi değildir.")
    draw.text((52, height - 45), disclaimer,
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


def preview_visual_identity(slot: datetime, media: str) -> dict:
    """Stable slot-scoped identities for targeted-only intraday publishing."""
    if media not in {"photo", "csv"}:
        raise ValueError("Unexpected ATC visual format")
    return {
        "source": "atc-intraday-visual-v1",
        "timeframe": Timeframe.D1.value,
        "slot": slot.isoformat(),
        "format": media,
    }


def preview_visual_envelopes(settings, topic_ids, *, now, slot, finished, expected=630):
    """Show evaluated provisional matches; attach ALL results without truncation.

    Never persist provisional signals to confirmed scan_evaluations.
    """
    rows = []
    for symbol, scans in finished:
        for number, directions in scans:
            if not 1 <= number <= len(SCANNER_ORDER):
                raise ValueError(f"Unknown provisional scanner number: {number}")
            rows.append((symbol, number, status_label("match", directions)))
    rows = sorted(set(rows), key=lambda row: (row[1], row[0], row[2]))
    visible = [row for row in rows if row[2] in MATCH_STATES][:MAX_ROWS_PER_CARD]
    png = render_card_png(
        timeframe="1d", bar_time=now, rows=visible,
        matched_count=len(rows), total_symbols=len(finished),
        page=1, pages=1, provisional=True, visible_count=len(visible),
    )
    table = io.StringIO()
    writer = csv.writer(table)
    writer.writerow(("Hisse", "TaramaKodu", "Yon", "KontrolSaatiTSI", "MumDurumu"))
    for symbol, number, state in rows:
        writer.writerow((
            symbol, scanner_code(number), direction_display(state),
            now.astimezone(ISTANBUL).isoformat(), "CANLI_TEYITSIZ",
        ))
    csv_bytes = ("\ufeff" + table.getvalue()).encode("utf-8")
    common = (f"ATC GÜNLÜK CANLI / TEYİTSİZ · {now:%d.%m.%Y %H:%M} TSİ · "
              f"{len(finished)}/{expected} hisse · {len(rows)} eşleşme. "
              "Kapanışta değişebilir; yatırım tavsiyesi değildir.")
    return (
        route_timeframe_image(
            settings, topic_ids, Timeframe.D1,
            identity=preview_visual_identity(slot, "photo"),
            payload={
                "_method": "sendPhoto", "photo_base64": base64.b64encode(png).decode("ascii"),
                "filename": "ATC_1D_CANLI_TEYITSIZ.png",
                "caption": common + f" Görselde ilk {len(visible)} eşleşme; tamamı CSV'de.",
            },
        ),
        route_timeframe_image(
            settings, topic_ids, Timeframe.D1,
            identity=preview_visual_identity(slot, "csv"),
            payload={
                "_method": "sendDocument",
                "document_base64": base64.b64encode(csv_bytes).decode("ascii"),
                "filename": f"ATC_1D_CANLI_TEYITSIZ_{slot:%Y%m%d_%H%M}.csv",
                "caption": common + " Tam eşleşme listesi (yön belirsizliği korunur).",
            },
        ),
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
    # Outbox state must survive delivery failures for safe retries and diagnostics.
    with psycopg.connect(uri, autocommit=True) as db:
        members = PostgresRuntimeRepository(db).list_universe("ATC_630", as_of=now.date())
        if len(members) != 630:
            raise ValueError(f"Expected 630 watched symbols, got {len(members)}")
        bindings = load_scanner_catalog(
            Path("config/scanners.toml"), calendar_version=ExchangeCalendarsXist().version
        )
        with db.cursor() as cur:
            cur.execute(LATEST_SQL, ("ATC_630", [m.instrument_id for m in members]))
            ev = cur.fetchall()
        bar_time, covered, matches = select_verified_matches(
            members, ev, bindings, tf.value, now=now
        )
        if not matches:
            print(f"Visual scanner {tf.value}: confirmed 0 matches; publishing verified empty result card", flush=True)
        rows = matches[:MAX_ROWS_PER_CARD * MAX_CARDS]
        pages = max(1, (len(rows) + MAX_ROWS_PER_CARD - 1) // MAX_ROWS_PER_CARD)
        envelopes = []
        for i in range(pages):
            page_rows = rows[i * MAX_ROWS_PER_CARD:(i + 1) * MAX_ROWS_PER_CARD]
            pic = render_card_png(
                timeframe=tf.value, bar_time=bar_time, rows=page_rows,
                matched_count=len(matches), total_symbols=covered,
                page=i + 1, pages=pages, visible_count=len(rows),
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
                        f"Sayfa {i + 1}/{pages} · "
                        f"görselde {len(rows)}/{len(matches)} · tam liste CSV'de · YTD"
                    ),
                },
            ))
        # Maximum images limits Telegram flood, not data completeness.
        # Every verified match goes in a complete CSV in the same topic.
        complete_table = io.StringIO()
        writer = csv.writer(complete_table)
        writer.writerow(("Hisse", "TaramaKodu", "Yon", "TeyitliMumTSI"))
        for symbol, number, state in matches:
            writer.writerow((
                symbol, scanner_code(number), direction_display(state),
                bar_time.astimezone(ISTANBUL).isoformat(),
            ))
        complete_bytes = ("\ufeff" + complete_table.getvalue()).encode("utf-8")
        envelopes.append(route_timeframe_image(
            settings, topic_ids, tf,
            identity={
                "source": "atc-timeframe-visual-v1",
                "timeframe": tf.value,
                "bar_close": bar_time.isoformat(), "format": "csv",
            },
            payload={
                "_method": "sendDocument",
                "document_base64": base64.b64encode(complete_bytes).decode("ascii"),
                "filename": f"ATC_{tf.value}_TEYITLI_{bar_time:%Y%m%d_%H%M}.csv",
                "caption": (
                    f"ATC {tf.value.upper()} | TEYİTLİ | {len(matches)} eşleşmenin "
                    "eksiksiz listesi · yatırım tavsiyesi değildir."
                ),
            },
        ))
        inserted = PostgresOutboxRepository(db).enqueue(tuple(envelopes), ordered=True)
        # Reuse the targeted-only queue implementation; never flush old news.
        outbox = AtcOnlyOutbox(db, [e.semantic_key for e in envelopes])
        result = TelegramPublisher(
            settings=settings, repository=outbox,
            transport=HttpxTelegramTransport(settings.bot_token),
        ).publish_batch(now=datetime.now(ISTANBUL), limit=len(envelopes))
        with db.cursor() as cur:
            cur.execute(
                "SELECT semantic_key, status FROM telegram_outbox "
                "WHERE semantic_key=ANY(%s::text[])",
                ([e.semantic_key for e in envelopes],),
            )
            states = dict(cur.fetchall())
        for error in result.error_samples:
            print(f"ATC Telegram visual delivery error: {error[:350]}", flush=True)
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
    parser.add_argument("--skip-if-unmapped", action="store_true",
                        help="Skip missing existing topic rather than misroute to SCANS")
    args = parser.parse_args()
    if args.skip_if_unmapped:
        tf = parse_timeframe(args.timeframe)
        topics = timeframe_topic_ids(os.environ)
        if tf not in topics:
            print(f"ATC {tf.value}: no verified existing topic; visual delivery skipped", flush=True)
            return
    publish_timeframe(args.timeframe)


if __name__ == "__main__":
    main()
