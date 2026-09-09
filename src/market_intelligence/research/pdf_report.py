from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html import escape
from pathlib import Path

from market_intelligence.research.equity_report_v2 import EquityResearchReport, ReportTable


@dataclass(frozen=True)
class RenderedPdf:
    path: Path
    content_hash: str
    size_bytes: int


def _font_paths() -> tuple[Path | None, Path | None]:
    candidates = (
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        ),
    )
    return next(
        ((regular, bold) for regular, bold in candidates if regular.exists() and bold.exists()),
        (None, None),
    )


def render_equity_research_pdf(
    report: EquityResearchReport,
    target: Path,
) -> RenderedPdf:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        LongTable,
        PageBreak,
        Paragraph,
        Preformatted,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    regular_path, bold_path = _font_paths()
    regular_font = "Helvetica"
    bold_font = "Helvetica-Bold"
    if regular_path is not None and bold_path is not None:
        regular_font = "BorsappSans"
        bold_font = "BorsappSansBold"
        if regular_font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(regular_font, str(regular_path)))
            pdfmetrics.registerFont(TTFont(bold_font, str(bold_path)))

    class DeterministicCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            kwargs["invariant"] = 1
            super().__init__(*args, **kwargs)

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "BorsappTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=21,
        leading=25,
        textColor=colors.HexColor("#102A43"),
        alignment=TA_LEFT,
        spaceAfter=7 * mm,
    )
    subtitle = ParagraphStyle(
        "BorsappSubtitle",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#486581"),
        spaceAfter=4 * mm,
    )
    heading = ParagraphStyle(
        "BorsappHeading",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0B7285"),
        spaceBefore=3 * mm,
        spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "BorsappBody",
        parent=styles["BodyText"],
        fontName=regular_font,
        fontSize=9.2,
        leading=13.2,
        textColor=colors.HexColor("#243B53"),
        spaceAfter=1.7 * mm,
    )
    small = ParagraphStyle(
        "BorsappSmall",
        parent=body,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#627D98"),
    )
    json_style = ParagraphStyle(
        "BorsappJson",
        parent=small,
        fontName=regular_font,
        fontSize=5.2,
        leading=6.4,
        textColor=colors.HexColor("#334E68"),
        leftIndent=2 * mm,
        rightIndent=2 * mm,
    )
    callout = ParagraphStyle(
        "BorsappCallout",
        parent=body,
        fontName=bold_font,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#102A43"),
    )
    table_cell = ParagraphStyle(
        "BorsappTableCell",
        parent=small,
        fontSize=6.9,
        leading=9.2,
        textColor=colors.HexColor("#243B53"),
    )
    table_head = ParagraphStyle(
        "BorsappTableHead",
        parent=table_cell,
        fontName=bold_font,
        textColor=colors.white,
    )

    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=19 * mm,
        bottomMargin=19 * mm,
        title=f"{report.symbol} Hisse Analiz Raporu",
        author="Borsapp Market Intelligence",
        subject="Point-in-time, kaynak etiketli hisse araştırma raporu",
    )

    def footer(page_canvas, _document) -> None:
        page_canvas.saveState()
        page_canvas.setStrokeColor(colors.HexColor("#D9E2EC"))
        page_canvas.line(17 * mm, 14 * mm, 193 * mm, 14 * mm)
        page_canvas.setFont(regular_font, 6.8)
        page_canvas.setFillColor(colors.HexColor("#829AB1"))
        page_canvas.drawString(
            17 * mm,
            9.5 * mm,
            "Bu rapor yatırım tavsiyesi değildir. Veriler değişebilir; UNKNOWN alanlar tahmin edilmemiştir.",
        )
        page_canvas.drawRightString(193 * mm, 9.5 * mm, f"Sayfa {page_canvas.getPageNumber()}")
        page_canvas.restoreState()

    story = [
        Paragraph(f"{escape(report.symbol)} Hisse Analiz Raporu", title),
        Paragraph(
            f"Rapor kimliği: {report.report_id[:20]}…<br/>"
            f"Kapalı bar: {escape(report.as_of_bar.isoformat())}<br/>"
            f"Üretim: {escape(report.generated_at.isoformat())}<br/>"
            f"Şablon: {escape(report.template_version)} · Veri revizyonu: {report.series_revision}",
            subtitle,
        ),
        Table(
            [
                ["Analiz güveni", f"{report.confidence_score:.0f}/100"],
                ["Kanıt kapsamı", f"{report.evidence_available}/{report.evidence_total} bölüm"],
                [
                    "Finansal sağlık",
                    f"{report.financial_health_score:.0f}/100"
                    if report.financial_health_score is not None
                    else "Veri yok",
                ],
                [
                    "Teknik puan",
                    f"{report.technical_score:.0f}/100"
                    if report.technical_score is not None
                    else "Veri yok",
                ],
                ["Değerleme", report.valuation_status],
                ["Veri politikası", "Point-in-time · eksik alan UNKNOWN · otomatik AL/SAT yok"],
            ],
            colWidths=[42 * mm, 130 * mm],
        ),
        Spacer(1, 5 * mm),
        Paragraph("Öne çıkan 5 bulgu", heading),
        *[Paragraph(f"• {escape(item)}", body) for item in report.top_findings],
        Paragraph("Kritik 3 koşul", heading),
        *[Paragraph(f"• {escape(item)}", body) for item in report.critical_conditions],
        Paragraph("En önemli 3 risk", heading),
        *[Paragraph(f"• {escape(item)}", body) for item in report.key_risks],
        Paragraph(f"Geçersizleşme: {escape(report.invalidation)}", callout),
        Paragraph(f"Olumlu teyit: {escape(report.positive_confirmation)}", callout),
        Paragraph(f"Genel sonuç: {escape(report.conclusion)}", body),
        PageBreak(),
    ]
    story[2].setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), regular_font),
                ("FONTNAME", (0, 0), (0, -1), bold_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#243B53")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E6FFFA")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BCCCDC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    def table_widths(column_count: int) -> list[float]:
        usable = 172 * mm
        if column_count == 2:
            return [42 * mm, 130 * mm]
        if column_count == 4:
            return [27 * mm, 25 * mm, 32 * mm, 88 * mm]
        if column_count == 5:
            return [27 * mm, 25 * mm, 24 * mm, 48 * mm, 48 * mm]
        return [usable / max(column_count, 1)] * column_count

    def render_table(item: ReportTable):
        rows = [
            [Paragraph(escape(value), table_head) for value in item.columns],
            *[[Paragraph(escape(value), table_cell) for value in row] for row in item.rows],
        ]
        table = LongTable(
            rows,
            colWidths=table_widths(len(item.columns)),
            repeatRows=1,
            splitByRow=1,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), bold_font),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B7285")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F4F8FA")],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BCCCDC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return table

    for section in report.sections:
        status_color = {
            "AVAILABLE": "#2B8A3E",
            "PARTIAL": "#E67700",
            "UNKNOWN": "#C92A2A",
        }.get(section.status, "#486581")
        story.append(
            Paragraph(
                f"{section.number}. {escape(section.title)} "
                f"<font color='{status_color}' size='7'>[{escape(section.status)}]</font>",
                heading,
            )
        )
        story.extend(Paragraph(escape(paragraph), body) for paragraph in section.paragraphs)
        story.extend(Paragraph(f"• {escape(item)}", body) for item in section.bullets)
        for item in section.tables:
            if item.title:
                story.append(Paragraph(escape(item.title), callout))
            if item.rows:
                story.append(render_table(item))
                story.append(Spacer(1, 2 * mm))
        story.append(Spacer(1, 1.5 * mm))
    story.extend(
        [
            Spacer(1, 4 * mm),
            Paragraph("Metodoloji ve sınırlamalar", heading),
            Paragraph(
                "Rapor yalnız kapalı barlar, canonical scanner kayıtları, saklanmış KAP/haberler ve "
                "kaynağı belirtilen finansal alanlardan üretilir. Veri → bulgu → anlam → koşul → "
                "senaryo sırası korunur. Sonuçlar emir, hedef fiyat veya kişiye özel tavsiye değildir.",
                small,
            ),
            PageBreak(),
            Paragraph("Makine Okunabilir Özet (JSON)", heading),
            Paragraph(
                "Eksik kaynaklar null veya boş koleksiyon olarak korunur; bu blok raporla aynı "
                "snapshot kimliğinden üretilmiştir.",
                small,
            ),
            Preformatted(
                escape(report.machine_readable_json()),
                json_style,
                maxLineLength=92,
            ),
        ]
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=DeterministicCanvas)
    content = target.read_bytes()
    return RenderedPdf(
        path=target.resolve(),
        content_hash=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )
