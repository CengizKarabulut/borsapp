"""Complete scan appendix, independent of the top-20 display limit."""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape


def render_full_scan_pdf(sections, slot):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        LongTable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        TableStyle,
    )

    from market_intelligence.application.live_scans import LABELS

    font = next(
        p
        for p in (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
        )
        if p.exists()
    )
    pdfmetrics.registerFont(TTFont("ScanFull", str(font)))
    body = ParagraphStyle("scan", fontName="ScanFull", fontSize=8, leading=11)
    title = ParagraphStyle("title", parent=body, fontSize=19, leading=25, spaceAfter=12)

    def para(value):
        return Paragraph(escape(str(value)), body)

    def table(rows, widths):
        result = LongTable(
            [[para(v) for v in row] for row in rows], colWidths=widths, repeatRows=1, hAlign="LEFT"
        )
        result.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE8F2")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F2F5F9")],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return result

    story = []
    for index, section in enumerate(sections):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(f"BORSAPP / {escape(section['timeframe'])} / Tam tarama eki", title))
        story.append(
            para(
                f"Sinyal kapanışı: {section['target']} | Üretim: {slot.isoformat()} | Evren: {section['expected']}"
            )
        )
        story.append(
            para(
                "İlk 20 sınırı uygulanmaz. Tüm eşleşmeler aşağıdadır. İşlenmeyen ve hesaplanamayan veriler eşleşme yok anlamına gelmez."
            )
        )
        story.append(Spacer(1, 12))
        coverage = [["Tarama", "İşlenen", "Eşleşme", "Hesaplanamayan"]]
        summary = {r[0]: r for r in section["summary"]}
        for scanner in section["scanners"]:
            r = summary.get(scanner, (scanner, 0, 0, 0))
            coverage.append(
                [LABELS.get(scanner, scanner), f"{r[1]}/{section['expected']}", r[2], r[3]]
            )
        story.append(table(coverage, [500, 140, 140, 140]))
        story.append(Spacer(1, 16))
        rows = [
            [
                "Hisse / Tarama",
                "Senaryo / Fiyat bazı",
                "Giriş*",
                "Stop",
                "TP1",
                "TP2",
                "TP3",
                "Risk %",
            ]
        ]

        def number(value):
            return "-" if value is None else f"{value:.2f}"

        for item in section["details"]:
            plan = item["plan"]
            for scenario in plan.get("scenarios", []) or [None]:
                label = f"{item['symbol']} / {LABELS.get(item['scanner'], item['scanner'])}"
                if scenario is None:
                    rows.append(
                        [label, f"Hesaplanamadı: {plan.get('reason', 'veri yok')}", *["-"] * 6]
                    )
                    continue
                basis = {"raw": "Ham fiyat", "split_adjusted": "Bölünmeye düzeltilmiş"}.get(
                    plan.get("price_basis"), str(plan.get("price_basis", "Belirsiz"))
                )
                side = "Yukarı" if scenario["side"] == "long" else "Aşağı"
                state = "Koşullu" if plan.get("status") == "conditional" else "Referans"
                note = f"{side} / {state} / {basis}" + (
                    " / Geniş stop" if scenario.get("wide_stop") else ""
                )
                rows.append(
                    [
                        label,
                        note,
                        *[
                            number(scenario.get(k))
                            for k in ("entry", "stop", "tp1", "tp2", "tp3", "risk_pct")
                        ],
                    ]
                )
        if len(rows) == 1:
            rows.append(["Eşleşme bulunamadı", "Kapsam tablosunu kontrol edin", *["-"] * 6])
        story.append(table(rows, [255, 185, 80, 80, 80, 80, 80, 80]))
        story.append(Spacer(1, 12))
        story.append(
            para(
                "* Giriş sinyal kapanış referansıdır; gerçekleşmiş emir değildir. ATR14 Wilder, swing7 + 0.2 ATR; minimum 0.75 ATR risk; TP 1R/2R/3R. Maliyetler hariç, performans doğrulanmadı. Aşağı senaryo otomatik açığa satış talimatı değildir."
            )
        )
    class ScanDocument(SimpleDocTemplate):
        current_section = ""
        def afterPage(self):
            footer(self.canv, self)
        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph) and flowable.style is title:
                self.current_section = flowable.getPlainText()

    output = io.BytesIO()

    def footer(c, doc):
        c.setFont("ScanFull", 8)
        c.drawString(35, 20, f"{doc.current_section} / Sayfa {doc.page}")

    ScanDocument(
        output, pagesize=(1010, 714), leftMargin=35, rightMargin=35, topMargin=30, bottomMargin=40
    ).build(story, onFirstPage=lambda c,d: None, onLaterPages=lambda c,d: None)
    return output.getvalue()


def enqueue_full_scan_pdf(connection, *, universe, slot, sections, hashes, predecessors, topic_id):
    from market_intelligence.core.identity import canonical_json, stable_hash

    key = stable_hash({"kind": "full_scan_job_v1", "universe": universe, "slot": slot.isoformat()})
    if connection.execute("SELECT 1 FROM command_jobs WHERE request_key=%s", (key,)).fetchone():
        return
    # Keep the running report and only the newest waiting snapshot.
    connection.execute(
        "UPDATE command_jobs SET status='superseded',finished_at=now() WHERE command_name='scan_pdf' AND status='pending' AND context->>'universe'=%s",
        (universe,),
    )
    context = {
        "automatic": True,
        "universe": universe,
        "slot": slot.isoformat(),
        "sections": sections,
        "hashes": hashes,
        "predecessors": predecessors,
    }
    connection.execute(
        "INSERT INTO command_jobs(command_name,symbol_at_request,requested_by,requested_topic,context,request_key) VALUES ('scan_pdf',%s,0,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
        (universe, topic_id, canonical_json(context), key),
    )


def execute_full_scan_pdf(connection, context):
    from datetime import datetime

    from market_intelligence.application.live_scans import SUMMARY_SQL
    from market_intelligence.application.trade_dashboard import load_trade_rows

    sections = []
    for seed in context["sections"]:
        target = datetime.fromisoformat(seed["target"])
        section = dict(seed)
        section["summary"] = connection.execute(
            SUMMARY_SQL, (context["universe"], seed["timeframe"], target, context["hashes"])
        ).fetchall()
        section["details"] = load_trade_rows(
            connection, context["universe"], seed["timeframe"], target, context["hashes"]
        )
        sections.append(section)
        print(f"Full PDF {seed['timeframe']}: {len(section['details'])} findings", flush=True)
    return render_full_scan_pdf(
        sections, datetime.now(datetime.fromisoformat(context["slot"]).tzinfo)
    )
