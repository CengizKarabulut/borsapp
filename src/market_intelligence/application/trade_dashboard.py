"""Read-only trade desk projections of current, version-matched scan results."""

from __future__ import annotations

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import parse_timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.trade_plan import build_trade_plan

DETAIL_SQL = """
WITH latest AS (
 SELECT DISTINCT ON(e.instrument_id,e.scanner_id) e.*
 FROM scan_evaluations e JOIN scan_cycles c USING(cycle_id)
 WHERE c.universe_id=%s AND e.timeframe=%s AND e.bar_time=%s AND e.ruleset_hash=ANY(%s)
 ORDER BY e.instrument_id,e.scanner_id,e.evaluated_at DESC,e.evaluation_id DESC
)
SELECT e.instrument_id,e.symbol_at_evaluation,e.scanner_id,s.snapshot_id,
 s.source,s.price_basis,s.series_revision,s.frame_start_time,s.through_bar_time,
 f.direction,f.metrics
FROM latest e JOIN data_snapshots s USING(snapshot_id)
JOIN LATERAL (
 SELECT direction,metrics FROM scan_events v WHERE v.evaluation_id=e.evaluation_id
 UNION ALL
 SELECT 'neutral',a.metrics FROM active_states a
 WHERE a.instrument_id=e.instrument_id AND a.scanner_id=e.scanner_id
 AND a.timeframe=e.timeframe AND a.last_seen_at=e.bar_time AND a.ruleset_hash=e.ruleset_hash
 AND a.status='active'
) f ON TRUE
WHERE e.status='match'
ORDER BY e.symbol_at_evaluation,e.scanner_id
"""


def load_trade_rows(connection, universe, timeframe, target, hashes):
    rows = connection.execute(DETAIL_SQL, (universe, timeframe, target, hashes)).fetchall()
    cache = {}
    results = []
    for (
        instrument,
        symbol,
        scanner,
        snapshot,
        source,
        basis,
        revision,
        start,
        end,
        direction,
        metrics,
    ) in rows:
        plan = metrics.get("trade_plan")
        if plan and plan.get("snapshot_id") != snapshot:
            plan = None
        if not plan:
            if snapshot not in cache:
                raw = connection.execute(
                    "SELECT open_time,close_time,open,high,low,close,volume FROM canonical_market_bars "
                    "WHERE instrument_id=%s AND timeframe=%s AND source=%s AND price_basis=%s "
                    "AND series_revision=%s AND close_time>=%s AND close_time<=%s ORDER BY close_time",
                    (instrument, timeframe, source, basis, revision, start, end),
                ).fetchall()
                cache[snapshot] = (
                    CanonicalFrame(
                        str(instrument),
                        symbol,
                        "BIST",
                        parse_timeframe(timeframe),
                        snapshot,
                        revision,
                        PriceBasis(basis),
                        source,
                        tuple(CanonicalBar(*r) for r in raw),
                    )
                    if raw
                    else None
                )
            frame = cache[snapshot]
            plan = (
                build_trade_plan(frame, direction)
                if frame
                else {"status": "unavailable", "reason": "snapshot_missing", "scenarios": []}
            )
        results.append({"symbol": symbol, "scanner": scanner, "direction": direction, "plan": plan})
    return results


def render_dashboard(timeframe, target, slot, expected, summary, bindings, details):
    """One mobile-readable overview PNG and complete paginated vector PDF."""
    import io
    from pathlib import Path

    from PIL import Image, ImageDraw, ImageFont
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    from market_intelligence.application.live_scans import LABELS

    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    fontpath = next((p for p in candidates if p.exists()), None)
    if fontpath is None:
        raise RuntimeError("Dashboard requires a Unicode TrueType font")

    def font(size):
        return ImageFont.truetype(str(fontpath), size)

    bg, panel, ink, muted, green, red = (
        "#0B1220",
        "#121F32",
        "#EDF3FA",
        "#9AACBF",
        "#42D6B3",
        "#FF8B95",
    )
    applicable = [b for b in bindings if timeframe in b.shadow_timeframes]
    byid = {r[0]: r[1:] for r in summary}
    coverage = [byid.get(b.scanner.id, (0, 0, 0, []))[0] for b in applicable]
    flattened = []
    for item in details:
        plan = item["plan"]
        scenarios = plan.get("scenarios", [])
        if not scenarios:
            flattened.append((item, None))
        else:
            flattened.extend((item, v) for v in scenarios)

    def num(x):
        return f"{x:.2f}" if x is not None else "—"

    def values(item, v):
        label = LABELS.get(item["scanner"], item["scanner"])
        if v is None:
            return [item["symbol"], label, "BEKLE", "—", "—", "—", "—", "—", "—"]
        side = "YUKARI" if v["side"] == "long" else "AŞAĞI"
        return [
            item["symbol"],
            label,
            side,
            *[num(v.get(k)) for k in ("entry", "stop", "tp1", "tp2", "tp3")],
            num(v.get("risk_pct")) + "%",
        ]

    im = Image.new("RGB", (1440, 1680), bg)
    d = ImageDraw.Draw(im)

    def text(x, y, t, size=24, color=ink):
        d.text((x, y), str(t), font=font(size), fill=color)

    d.rectangle((0, 0, 1440, 8), fill=green)
    text(48, 34, "BORSAPP  /  TRADE DESK", 34)
    text(1160, 38, timeframe.value.upper(), 38, green)
    text(
        48,
        91,
        f"Kapanış {target.astimezone(slot.tzinfo):%d.%m.%Y %H:%M}  •  Üretim {slot:%d.%m %H:%M}",
        23,
        muted,
    )
    for x, title, value in [
        (48, "EVREN", str(expected)),
        (505, "TARAMA KAPSAMI", f"{min(coverage, default=0)}–{max(coverage, default=0)}"),
        (962, "EŞLEŞEN HİSSE", str(len({r["symbol"] for r in details}))),
    ]:
        d.rounded_rectangle((x, 145, x + 430, 260), radius=16, fill=panel)
        text(x + 22, 162, title, 20, muted)
        text(x + 22, 193, value, 36)
    text(48, 292, "TARAMA RADARI", 25)
    for i, b in enumerate(applicable):
        col, row = i % 2, i // 2
        x, y = 48 + col * 700, 342 + row * 42
        seen, matches, unknown, _ = byid.get(b.scanner.id, (0, 0, 0, []))
        text(x, y, LABELS.get(b.scanner.id, b.scanner.id), 19)
        text(x + 410, y, f"{matches} eşleşme", 19, green)
        text(x + 540, y, f"{seen}/{expected} · ?{unknown}", 18, muted)
    top = 765
    text(48, top, "İŞLEM SENARYOLARI", 25)
    text(
        48,
        top + 40,
        "Alfabetik ilk 10 satır • Tüm sonuçlar ekli PDF’de • Başarı sıralaması değildir",
        20,
        muted,
    )
    cols = [48, 215, 650, 770, 900, 1030, 1160, 1290]
    for x, t in zip(
        cols, ["HİSSE / YÖN", "TARAMA", "GİRİŞ*", "STOP", "TP1", "TP2", "TP3", "RİSK"], strict=False
    ):
        text(x, top + 96, t, 19, muted)
    for i, (item, v) in enumerate(flattened[:10]):
        y = top + 135 + i * 55
        d.rectangle((36, y - 4, 1404, y + 48), fill=panel if i % 2 == 0 else bg)
        vals = values(item, v)
        text(48, y, vals[0], 21)
        text(48, y + 25, vals[2], 14, green if vals[2] == "YUKARI" else red)
        label = vals[1]
        while d.textlength(label, font=font(18)) > 410:
            label = label[:-2] + "…"
        text(215, y, label, 18)
        text(
            215,
            y + 26,
            "Bölünmeye düzeltilmiş referans"
            if item["plan"].get("price_basis") == "split_adjusted"
            else "Ham fiyat referansı",
            13,
            muted,
        )
        for x, value in zip(cols[2:], vals[3:], strict=False):
            text(x, y + 10, value, 19, red if x == 770 else ink)
    if not flattened:
        text(48, top + 155, "Bu kapanış için eşleşme yok veya hesaplama bekleniyor.", 24, muted)
    text(
        48,
        1510,
        "* Giriş = sinyal mumunun kapanış referansı; gerçekleşmiş emir fiyatı değildir.",
        21,
        muted,
    )
    text(
        48,
        1550,
        "Stop: swing + ATR14 • TP: 1R / 2R / 3R • Yönsüz bulgular: koşullu iki senaryo",
        20,
        muted,
    )
    text(
        48,
        1590,
        "? = hesaplanamayan • Fiyat bazı satırda belirtilir • Maliyetler hariç; performans doğrulanmadı",
        19,
        muted,
    )
    out = io.BytesIO()
    im.save(out, format="PNG")
    png = out.getvalue()
    pdfmetrics.registerFont(TTFont("TradeDesk", str(fontpath)))
    pdf = io.BytesIO()
    c = canvas.Canvas(pdf, pagesize=(1120, 790))
    page_rows = flattened or [(None, None)]
    for offset in range(0, len(page_rows), 16):
        c.setFillColorRGB(0.04, 0.07, 0.12)
        c.rect(0, 0, 1120, 790, fill=1, stroke=0)
        c.setFillColorRGB(0.93, 0.96, 0.99)
        c.setFont("TradeDesk", 23)
        c.drawString(30, 750, f"BORSAPP / {timeframe.value} / İşlem senaryoları")
        c.setFont("TradeDesk", 10)
        c.drawString(
            30,
            726,
            f"Kapanış: {target.astimezone(slot.tzinfo):%d.%m.%Y %H:%M} | Evren {expected} | Kapsam {min(coverage, default=0)}–{max(coverage, default=0)} | Alfabetik sıralama",
        )
        xs = [30, 110, 415, 495, 590, 685, 780, 875, 985]
        for x, t in zip(
            xs,
            ["HİSSE", "TARAMA", "YÖN", "GİRİŞ*", "STOP", "TP1", "TP2", "TP3", "RİSK"],
            strict=False,
        ):
            c.drawString(x, 695, t)
        for i, (item, v) in enumerate(page_rows[offset : offset + 16]):
            if item is None:
                c.drawString(30, 660, "Eşleşme bulunamadı.")
                continue
            y = 663 - i * 34
            vals = values(item, v)
            for x, t in zip(xs, vals, strict=False):
                c.drawString(x, y, t)
            c.setFont("TradeDesk", 7)
            note = (
                item["plan"].get("reason", "")
                if v is None
                else (
                    "Koşullu senaryo | "
                    if item["plan"].get("status") == "conditional"
                    else "Referans senaryo | "
                )
                + ("Geniş stop | " if v.get("wide_stop") else "")
                + item["plan"].get("version", "kaynak planı")
            )
            c.drawString(
                110,
                y - 12,
                note
                + " | "
                + (
                    "Düzeltilmiş fiyat"
                    if item["plan"].get("price_basis") == "split_adjusted"
                    else "Ham fiyat"
                ),
            )
            c.setFont("TradeDesk", 10)
        c.setFont("TradeDesk", 9)
        c.drawString(
            30,
            65,
            "* Giriş sinyal kapanış referansıdır. Gerçekleşme, komisyon, kayma ve işlem yapılabilirlik değerlendirilmemiştir.",
        )
        c.drawString(
            30,
            47,
            "Ortak model: ATR14 Wilder, swing7 + 0.2 ATR tampon; en az 0.75 ATR risk. Hedefler 1R / 2R / 3R.",
        )
        c.drawString(
            30,
            29,
            f"Aşağı yönlü senaryo otomatik açığa satış talimatı değildir. Performans doğrulanmadı. Sayfa {offset // 16 + 1}",
        )
        c.showPage()
    c.save()
    return png, pdf.getvalue()
