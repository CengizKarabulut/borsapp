"""v11: PDF + kısa özet akışına kontrollü 'yatırımcı için anlamı' katmanı ekler.

v10'un PDF gönderimini, tarih/tekrar filtrelerini ve extractive özetini korur.
Yeni katman yalnız PDF içinde bulunan somut öneri, hedef, destek/direnç, kırılım/stop
ve model-portföy değişimlerinden kısa bir anlam çıkarır; serbest yatırım tavsiyesi üretmez.
"""

import html

import news_bot as base
import news_bot_v4 as v4
import news_bot_v6 as v6
import news_bot_v10 as v10
from investor_takeaway import summarize_report_text


SUMMARY_CAPTION_LIMIT = v10.SUMMARY_CAPTION_LIMIT


def clean(value):
    return base.clean(value)


def _summary_caption(item, summary, extraction_error=""):
    source = item.get("source", "")
    label = (
        v6.RESEARCH_PAGE_CONFIGS.get(source, {}).get("label")
        or v4.BULLETIN_LABELS.get(source, source)
    )
    icon, report_label = v6.report_type_meta(item)
    date_text = item.get("date_text") or item.get("published_date") or ""
    title = clean(item.get("title"))
    page_url = item.get("page_url") or item.get("document_url")

    lines = [
        f"📚 <b>ARAŞTIRMA | {html.escape(label)}</b>",
        f"{icon} <b>{html.escape(report_label)}</b>",
    ]
    if date_text:
        lines.append(f"🗓 {html.escape(date_text)}")
    if title and report_label.lower() not in title.lower():
        lines.append(f"📝 {html.escape(title[:150])}")

    takeaways = list(summary.get("takeaways") or [])
    if takeaways:
        lines.append("👀 <b>Yatırımcı için anlamı:</b>")
        for takeaway in takeaways[:2]:
            lines.append("• " + html.escape(clean(takeaway)[:240]))

    bullets = list(summary.get("bullets") or [])
    if bullets:
        lines.append("🧾 <b>Rapordan öne çıkanlar:</b>")
        for bullet in bullets[:4]:
            lines.append("• " + html.escape(clean(bullet)[:220]))
    elif extraction_error:
        lines.append("🧾 PDF ektedir; metin katmanı otomatik okunamadığı için içerik özeti üretilmedi.")
    else:
        lines.append("🧾 PDF ektedir; güvenilir bir kısa özet çıkaracak yeterli metin bulunamadı.")

    link_line = f'<a href="{html.escape(page_url, quote=True)}">Resmî araştırma kaynağını aç</a>'
    return v10._fit_caption(lines, link_line, limit=SUMMARY_CAPTION_LIMIT)


def install_takeaway_layer():
    # v10.send_research_item bu iki ismi kendi modül globalinden runtime'da okur.
    v10.summarize_report_text = summarize_report_text
    v10._summary_caption = _summary_caption


def main():
    install_takeaway_layer()
    v10.main()


if __name__ == "__main__":
    main()
