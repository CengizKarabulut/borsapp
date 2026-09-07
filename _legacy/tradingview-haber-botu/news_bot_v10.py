"""v10: Araştırma PDF'ini koruyarak aynı Telegram mesajında kısa içerik özeti verir.

v9'un kaynak sağlığı + v8'in tarih/tekrar filtresi aynen korunur. Public PDF varsa:
1) PDF indirilir/oluşturulur,
2) pypdf ile metin çıkarılır,
3) rapor türüne özel extractive özet hazırlanır,
4) PDF, bu özet caption'ı ile Telegram'a gönderilir.

Model portföylerde önceki başarılı rapordan kalan ticker listesi saklanır; mümkünse
"yeni görünen / artık görünmeyen" farkı bir sonraki raporda gösterilir.
"""

import html
import os
import tempfile
import time
from datetime import datetime

import requests

import news_bot as base
import news_bot_v4 as v4
import news_bot_v6 as v6
import news_bot_v9 as v9
from research_summary import extract_pdf_text, summarize_report_text


ISTANBUL = v9.ISTANBUL
SUMMARY_STATE_KEY = "research_summary_v10"
SUMMARY_MAX_PAGES = max(1, int(os.getenv("RESEARCH_SUMMARY_MAX_PAGES", "12")))
SUMMARY_MAX_CHARS = max(5000, int(os.getenv("RESEARCH_SUMMARY_MAX_CHARS", "60000")))
SUMMARY_CAPTION_LIMIT = min(1000, max(700, int(os.getenv("RESEARCH_SUMMARY_CAPTION_LIMIT", "980"))))

ORIGINAL_SEND_RESEARCH_ITEM = v6.send_research_item
_SENT_SUMMARY_META = []


def clean(value):
    return base.clean(value)


def _previous_tickers(source):
    try:
        state = base.load_state()
        values = (
            state.get(SUMMARY_STATE_KEY, {})
            .get(source, {})
            .get("model_portfoy", {})
            .get("tickers", [])
        )
        return [clean(value).upper() for value in values if clean(value)]
    except Exception:
        return []


def _record_summary_meta(item, summary):
    meta = dict(summary.get("meta") or {})
    if not meta:
        return
    _SENT_SUMMARY_META.append({
        "source": item.get("source"),
        "report_type": item.get("report_type"),
        "published_date": item.get("published_date"),
        "meta": meta,
    })


def persist_summary_meta():
    if not _SENT_SUMMARY_META:
        return
    state = base.load_state()
    summary_state = state.setdefault(SUMMARY_STATE_KEY, {})
    for entry in _SENT_SUMMARY_META:
        source = entry.get("source")
        report_type = entry.get("report_type")
        if not source or not report_type:
            continue
        type_state = summary_state.setdefault(source, {}).setdefault(report_type, {})
        meta = entry.get("meta") or {}
        if meta.get("tickers"):
            type_state["tickers"] = list(dict.fromkeys(meta["tickers"]))[:50]
        type_state["published_date"] = entry.get("published_date") or ""
        type_state["updated_at"] = datetime.now(ISTANBUL).isoformat()
    base.save_state(state)
    _SENT_SUMMARY_META.clear()


def _fit_caption(lines, link_line, limit=SUMMARY_CAPTION_LIMIT):
    """HTML satırlarını tag kesmeden Telegram caption sınırına sığdır."""
    kept = []
    reserve = len(link_line) + 1
    for line in lines:
        candidate = "\n".join(kept + [line])
        if len(candidate) + reserve <= limit:
            kept.append(line)
    if not kept:
        kept = ["📚 <b>ARAŞTIRMA RAPORU</b>"]
    return "\n".join(kept + [link_line])[:limit]


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
        lines.append(f"📝 {html.escape(title[:180])}")

    bullets = list(summary.get("bullets") or [])
    if bullets:
        lines.append("🧾 <b>Kısa özet (PDF'den):</b>")
        for bullet in bullets:
            lines.append("• " + html.escape(clean(bullet)[:240]))
    elif extraction_error:
        lines.append("🧾 PDF ektedir; metin katmanı otomatik okunamadığı için içerik özeti üretilmedi.")
    else:
        lines.append("🧾 PDF ektedir; güvenilir bir kısa özet çıkaracak yeterli metin bulunamadı.")

    link_line = f'<a href="{html.escape(page_url, quote=True)}">Resmî araştırma kaynağını aç</a>'
    return _fit_caption(lines, link_line)


def _send_document(token, payload, pdf_path, filename, label):
    for attempt in range(1, base.MAX_ATTEMPTS + 1):
        try:
            with open(pdf_path, "rb") as document:
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data=payload,
                    files={"document": (filename, document, "application/pdf")},
                    timeout=60,
                )
            if response.status_code == 429:
                retry = response.json().get("parameters", {}).get("retry_after", 15)
                time.sleep(int(retry) + 1)
                continue
            if response.status_code >= 500:
                time.sleep(min(60, attempt * 5))
                continue
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            print(f"Özetli araştırma PDF Telegram deneme {attempt} başarısız [{label}]: {exc}")
            time.sleep(min(60, attempt * 5))
    return False


def send_research_item(item, session=requests):
    """Public PDF'leri özet caption ile, link-only kayıtları mevcut v9/v6 biçiminde gönder."""
    delivery = item.get("delivery")
    if delivery != "pdf" and not item.get("render_html"):
        return ORIGINAL_SEND_RESEARCH_ITEM(item, session=session)

    source = item.get("source", "")
    label = (
        v6.RESEARCH_PAGE_CONFIGS.get(source, {}).get("label")
        or v4.BULLETIN_LABELS.get(source, source)
    )
    report_type = item.get("report_type", "arastirma")

    if base.DRY_RUN:
        print(
            f"DRY_RUN SUMMARY PDF [{label}] [{report_type}] "
            f"{item.get('document_url') or item.get('page_url')}"
        )
        return True

    token, payload = v4._telegram_base_payload()
    safe_date = (
        item.get("published_date") or datetime.now(ISTANBUL).date().isoformat()
    ).replace("-", "")
    filename = f"{source}_{report_type}_{safe_date}.pdf"

    with tempfile.TemporaryDirectory(prefix="research-summary-") as directory:
        pdf_path = os.path.join(directory, filename)
        if item.get("render_html"):
            v4._render_html_pdf(item["document_url"], pdf_path)
        else:
            v4._download_pdf(item["document_url"], pdf_path, session=session)

        extraction_error = ""
        pdf_text = ""
        try:
            pdf_text = extract_pdf_text(
                pdf_path,
                max_pages=SUMMARY_MAX_PAGES,
                max_chars=SUMMARY_MAX_CHARS,
            )
        except Exception as exc:
            extraction_error = clean(exc)
            print(f"PDF metni çıkarılamadı [{label}/{report_type}]: {exc}")

        previous = _previous_tickers(source) if report_type == "model_portfoy" else []
        summary = summarize_report_text(
            pdf_text,
            report_type,
            previous_tickers=previous,
            max_bullets=5,
        )
        payload["caption"] = _summary_caption(item, summary, extraction_error=extraction_error)

        sent = _send_document(token, payload, pdf_path, filename, label)
        if sent:
            _record_summary_meta(item, summary)
            print(
                f"Özetli araştırma PDF gönderildi [{source}/{report_type}]: "
                f"{len(summary.get('bullets') or [])} özet maddesi"
            )
        return sent


def install_summary_sender():
    v6.send_research_item = send_research_item


def main():
    install_summary_sender()
    try:
        v9.main()
    finally:
        # v9 kendi research/cache state'ini yazdıktan sonra model-portföy snapshot'ını ekle.
        persist_summary_meta()


if __name__ == "__main__":
    main()
