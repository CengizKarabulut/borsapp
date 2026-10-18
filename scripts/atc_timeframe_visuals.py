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
from scripts.atc_full_universe_status import universe_status_csv
from scripts.atc_publish_targeted import AtcOnlyOutbox
from scripts.atc_saved_scan_plans import (
    complete_reference_levels,
    fmt_level,
    load_saved_trade_plans,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")
COLORS = {"POZITIF": "#177A4F", "NEGATIF": "#B83636",
          "NOTR": "#A56C21", "KARMA": "#6366A3",
          "ESLESME_YON_BELIRSIZ": "#52697F"}
MATCH_STATES = frozenset(COLORS)
MAX_ROWS_PER_CARD = 20


def pine_plan_required(match) -> bool:
    """Only owner-Pine supported directions own a standalone Stop/TP plan."""
    _symbol, number, state = match
    # 17 Oct native Pine defines both directions for A-I and 10-16.
    # Rules 17/18 have no standalone source risk family.
    return state in {"POZITIF", "NEGATIF"} and 1 <= number <= 16


def require_complete_publication(
    *, timeframe: str, covered: int, matches, plans, model_failures=None,
) -> dict:
    """Demand real data; distinguish impossible original Pine R/R from missing data."""
    if covered != 630:
        raise ValueError(
            f"{timeframe}: strict completed-candle coverage {covered}/630; "
            "withholding PNG/CSV and waiting for genuine source data"
        )
    required = [match for match in matches if pine_plan_required(match)]
    failures = model_failures or {}
    accepted_constraints = {"nonpositive_level", "invalid_stop_or_target"}
    nonactionable = [
        match for match in required
        if failures.get(match) in accepted_constraints
    ]
    missing = [
        match for match in required
        if match not in nonactionable and not complete_reference_levels(
            plans.get(match), "bullish" if match[2] == "POZITIF" else "bearish",
        )
    ]
    print(
        f"ATC complete-report audit {timeframe}: coverage={covered}/630, "
        f"Pine plans={len(required) - len(missing) - len(nonactionable)}/{len(required)}, "
        f"non-actionable math={len(nonactionable)}, data missing={len(missing)}, "
        f"full-image-rows={len(matches)}",
        flush=True,
    )
    if missing:
        names = ", ".join(
            f"{symbol}:{scanner_code(number)}:{direction_display(state)}"
            for symbol, number, state in missing[:80]
        )
        raise ValueError(
            f"{timeframe}: {len(missing)} Pine-required Stop/TP plans missing; "
            f"Telegram report WITHHELD until exact-source levels validated. "
            f"Unresolved: {names}"
        )
    return {
        "verified_plans": len(required) - len(nonactionable),
        "model_rejected": len(nonactionable),
        "nonplan_matches": len(matches) - len(required),
    }


def full_card_pages(match_count: int) -> int:
    """Never silently discard valid matches from 20-row PNG pages."""
    return max(1, (match_count + MAX_ROWS_PER_CARD - 1) // MAX_ROWS_PER_CARD)


def _font(size, *, bold=False):
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    names = (
        windows_fonts / ("segoeuib.ttf" if bold else "segoeui.ttf"),
        windows_fonts / ("arialbd.ttf" if bold else "arial.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
         if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
         if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size=size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow 10.0 has no size argument on its fallback font.
        return ImageFont.load_default()


def render_card_png(*, timeframe: str, bar_time: datetime, rows,
                    matched_count: int, total_symbols: int, page: int, pages: int,
                    provisional: bool = False, visible_count: int | None = None) -> bytes:
    """Show real code/direction and same-evaluation reference stop/TP only.

    Legacy 3-tuple callers intentionally render dashes for unavailable plans.
    """
    width = 1840
    height = 310 + max(1, len(rows)) * 46 + 76
    img = Image.new("RGB", (width, height), "#EDF2F7")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((20, 20, width - 20, height - 20), radius=20, fill="#FFFFFF")
    draw.rectangle((20, 20, width - 20, 105), fill="#102C46")
    kind = "CANLI / TEYİTSİZ" if provisional else "TEYİTLİ"
    title = f"ALPHA TREND CIPHER · {timeframe.upper()} TARAMA"
    draw.text((52, 38), title, font=_font(28, bold=True), fill="#FFFFFF")
    draw.text((52, 136), f"{kind} · {bar_time.astimezone(ISTANBUL):%d.%m.%Y %H:%M} TSİ",
              font=_font(21), fill="#26374C")
    draw.text((52, 181), f"Değerlendirilen: {total_symbols}/630 hisse · Eşleşme: {matched_count}",
              font=_font(21, bold=True), fill="#26374C")
    columns = ((55, "HİSSE"), (250, "KOD"), (355, "YÖN"), (555, "GİRİŞ"),
               (770, "STOP"), (995, "TP1"), (1210, "TP2"), (1435, "TP3"),
               (1640, "PLAN"))
    for x, name in columns:
        draw.text((x, 229), name, font=_font(19, bold=True), fill="#51687D")
    draw.line((52, 260, width - 52, 260), fill="#D5DFE8", width=2)
    if not rows and matched_count == 0:
        draw.text((53, 290), "Teyitli kapanışta eşleşen koşul yok.",
                  font=_font(23, bold=True), fill="#52697F")
    for index, row in enumerate(rows):
        model_failure = None
        if len(row) == 3:
            symbol, number, state = row
            plan = None
        elif len(row) == 4:
            symbol, number, state, plan = row
        elif len(row) == 5:
            symbol, number, state, plan, model_failure = row
        else:
            raise ValueError("Scanner display row must have 3, 4 or 5 fields")
        top = 267 + index * 46
        if index % 2 == 0:
            draw.rounded_rectangle((43, top, width - 43, top + 44),
                                   radius=6, fill="#F5F8FB")
        draw.text((55, top + 10), "#" + symbol, font=_font(19, bold=True), fill="#17304C")
        draw.text((250, top + 10), scanner_code(number), font=_font(21, bold=True),
                  fill="#33485B")
        draw.text((355, top + 10), direction_display(state),
                  font=_font(19, bold=True), fill=COLORS[state])
        if state not in ("POZITIF", "NEGATIF"):
            plan = None
        numbers = (
            (plan.entry, plan.stop, plan.tp1, plan.tp2, plan.tp3)
            if plan is not None else (None,) * 5
        )
        for x, value in zip((555, 770, 995, 1210, 1435), numbers, strict=True):
            # A negative theoretical TP is NOT a real price. Flag original
            # formula incompatibility; never conceal it as a valid level.
            display = fmt_level(value)
            draw.text((x, top + 10), display,
                      font=_font(18, bold=x == 770),
                      fill="#B83636" if model_failure and display == "-" else "#33485B")
        complete = complete_reference_levels(
            plan, "bullish" if state == "POZITIF" else "bearish",
        ) if state in ("POZITIF", "NEGATIF") else False
        draw.text(
            (1640, top + 12),
            "UYGULANAMAZ" if model_failure else "REFERANS" if complete else "YOK",
            font=_font(14, bold=True), fill="#B83636" if model_failure else "#60748A",
        )
    shown = visible_count if visible_count is not None else matched_count
    footer = (f"Sayfa {page}/{pages} · {shown}/{matched_count} eşleşme görselde"
              if shown != matched_count else f"Sayfa {page}/{pages} · {kind} tarama")
    draw.text((52, height - 76), footer, font=_font(19), fill="#60748A")
    disclaimer = (
        "Giriş/Stop/TP referanstır, emir değildir; geçici mumda değişebilir. YTD."
        if provisional else
        "-: geçersiz/ayrı planı olmayan fiyat · UYGULANAMAZ: tam Stop/TP planı yok; pozitif alanlar yalnız referans · YTD."
    )
    draw.text((52, height - 45), disclaimer, font=_font(16), fill="#60748A")
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
    if len(covered) < int(len(members) * .9) or (
        len(members) == 630 and len(covered) != 630
    ):
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
    writer.writerow(("Hisse", "TaramaKodu", "Yon", "Giris", "Stop", "TP1", "TP2", "TP3", "KontrolSaatiTSI", "MumDurumu"))
    for symbol, number, state in rows:
        writer.writerow((
            symbol, scanner_code(number), direction_display(state),
            "", "", "", "", "",
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
        universe_csv, universe_audit = universe_status_csv(
            members, ev, bindings, tf.value, bar_time,
        )
        if universe_audit["members"] != 630 or universe_audit.get("match", 0) != len(matches):
            raise RuntimeError(
                f"{tf.value}: mismatched actual scanner matches: "
                f"images={len(matches)} universe_csv={universe_audit.get('match', 0)}"
            )
        print(f"ATC complete universe evidence {tf.value}: {universe_audit}", flush=True)
        plans, model_failures = load_saved_trade_plans(
            db, members=members, evaluations=ev, matches=matches,
            timeframe=tf.value, bar_time=bar_time, include_model_failures=True,
        )
        audit = require_complete_publication(
            timeframe=tf.value, covered=covered, matches=matches, plans=plans,
            model_failures=model_failures,
        )
        rows = [(*key, plans.get(key), model_failures.get(key)) for key in matches]
        pages = full_card_pages(len(rows))
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
                    "source": "atc-timeframe-visual-risk-audited-v5",
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
                        f"Hisse veri {covered}/630 | "
                        f"Koşul hesabı {universe_audit['confirmed_evaluations']}/"
                        f"{universe_audit['expected_evaluations']} | "
                        f"Hesaplanamayan {universe_audit['unresolved_evaluations']} | "
                        f"{len(matches)} koşul / {universe_audit['matched_members']} hisse | "
                        f"Sayfa {i + 1}/{pages} · "
                        f"630 hisse durumları ayrı CSV'de · YTD"
                    ),
                },
            ))
        # One 20-row PNG per page, without truncating any confirmed matches.
        # Every verified match is also kept in the full CSV in the same topic.
        complete_table = io.StringIO()
        writer = csv.writer(complete_table)
        writer.writerow(("Hisse", "TaramaKodu", "Yon", "Giris", "Stop", "TP1", "TP2", "TP3", "FiyatBazi", "TeyitliMumTSI", "PlanDurumu", "PlanNedeni"))
        for symbol, number, state in matches:
            plan = plans.get((symbol, number, state))
            levels = (plan.entry, plan.stop, plan.tp1, plan.tp2, plan.tp3) if plan else (None,) * 5
            writer.writerow((
                symbol, scanner_code(number), direction_display(state),
                *(fmt_level(v, csv=True) for v in levels),
                plan.price_basis if plan else "",
                bar_time.astimezone(ISTANBUL).isoformat(),
                (
                    "RISK_MODELI_UYGULANAMAZ"
                    if (symbol, number, state) in model_failures
                    else "TEYITLI" if pine_plan_required((symbol, number, state))
                    else "YON_BELIRSIZ" if state == "ESLESME_YON_BELIRSIZ"
                    else "NOTR_PLAN_YOK" if state == "NOTR"
                    else "AYRI_PLAN_YOK"
                ),
                model_failures.get((symbol, number, state), ""),
            ))
        complete_bytes = ("\ufeff" + complete_table.getvalue()).encode("utf-8")
        envelopes.append(route_timeframe_image(
            settings, topic_ids, tf,
            identity={
                "source": "atc-timeframe-visual-risk-audited-v5",
                "timeframe": tf.value,
                "bar_close": bar_time.isoformat(), "format": "csv",
            },
            payload={
                "_method": "sendDocument",
                "document_base64": base64.b64encode(complete_bytes).decode("ascii"),
                "filename": f"ATC_{tf.value}_TEYITLI_{bar_time:%Y%m%d_%H%M}.csv",
                "caption": (
                    f"ATC {tf.value.upper()} | {len(matches)} doğrulanmış KOŞUL eşleşmesi "
                    f"/ {universe_audit['matched_members']} farklı hisse. "
                    f"Toplam değerlendirmede {universe_audit['unresolved_evaluations']} "
                    "hesaplanamayan kayıt var; 630 hissenin tek tek durumu ayrı CSV'de. YTD."
                ),
            },
        ))
        envelopes.append(route_timeframe_image(
            settings, topic_ids, tf,
            identity={
                "source": "atc-630-universe-evaluation-v1",
                "timeframe": tf.value,
                "bar_close": bar_time.isoformat(), "format": "universe-csv",
            },
            payload={
                "_method": "sendDocument",
                "document_base64": base64.b64encode(universe_csv).decode("ascii"),
                "filename": f"ATC_{tf.value}_630_HISSE_TUM_DURUMLAR_{bar_time:%Y%m%d_%H%M}.csv",
                "caption": (
                    f"ATC {tf.value.upper()} · 630 HISSE TAM DENETIM · "
                    f"{len(matches)} koşul eşleşmesi / "
                    f"{universe_audit['matched_members']} farklı hisse · "
                    f"{universe_audit['unresolved_evaluations']} hesaplanamayan/eksik "
                    "tarama · A-I ve 10-18 durumları tek tek CSV'de · YTD"
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
               "full_universe_rows": universe_audit["members"],
               "unique_matched_symbols": universe_audit["matched_members"],
               "matched_symbols_with_other_unknown_rules": universe_audit["matched_with_unresolved"],
               "unresolved_scanner_evaluations": universe_audit["unresolved_evaluations"],
               "valid_plans": audit["verified_plans"],
               "model_rejected": audit["model_rejected"],
               "nonplan_matches": audit["nonplan_matches"],
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
