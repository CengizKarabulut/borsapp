"""Geliştirilmiş haber botu: temiz KAP mesajları ve aracı kurum PDF bültenleri."""

import html
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import news_bot as base


ISTANBUL = ZoneInfo("Europe/Istanbul")
ORIGINAL_ENRICH = base.enrich
ORIGINAL_BUILD_MESSAGE = base.build_message

BULLETIN_SOURCES = [
    value.strip().lower()
    for value in os.getenv("BULLETIN_SOURCES", "tera,info,a1capital,bulls").split(",")
    if value.strip()
]
BULLETIN_MAX_MB = int(os.getenv("BULLETIN_MAX_MB", "15"))
BULLETIN_TIMEOUT = int(os.getenv("BULLETIN_TIMEOUT", "35"))

BULLETIN_LABELS = {
    "tera": "TERA Yatırım",
    "info": "İnfo Yatırım",
    "a1capital": "A1 Capital",
    "bulls": "Bulls Yatırım",
}

TERA_DAILY = "https://www.terayatirim.com/arastirma/gunluk-bulten"
INFO_DAILY = "https://infoyatirim.com/arastirma/gunluk-bulten"
A1_DAILY = "https://a1capital.com.tr/gunluk-bulten/"
BULLS_DAILY = "https://bullsyatirim.com/gunluk-bulten"

TR_MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4,
    "mayıs": 5, "mayis": 5, "haziran": 6, "temmuz": 7,
    "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}

KAP_SYSTEM_TOKEN = re.compile(
    r"(?:\[[A-Z0-9_]+\])|(?:\boda_[A-Za-z0-9_().\[\]-]+\b)",
    re.IGNORECASE,
)
KAP_SKIP_EXACT = {
    "ilgili şirketler", "related companies", "ilgili fonlar", "related funds",
    "türkçe", "turkish", "ingilizce", "english",
    "bildirim içeriği", "announcement content", "explanations",
}
KAP_BOILERPLATE_STARTS = (
    "yukarıdaki açıklamalarımızın",
    "we proclaim that our above disclosure",
    "burada yer alan yatırım bilgi",
    "işbu açıklamanın ingilizce tercümesi",
)


def _clean(value):
    return base.clean(value)


def _response_soup(response):
    response.raise_for_status()
    if getattr(response, "encoding", None) is None:
        response.encoding = "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def _first_anchor(soup, predicate):
    for anchor in soup.find_all("a", href=True):
        text = _clean(anchor.get_text(" ", strip=True))
        href = _clean(anchor.get("href"))
        if predicate(text, href):
            return anchor
    return None


def parse_bulletin_date(value):
    text = _clean(value).lower()
    dotted = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", text)
    if dotted:
        try:
            return datetime(
                int(dotted.group(3)), int(dotted.group(2)), int(dotted.group(1)),
                tzinfo=ISTANBUL,
            ).date()
        except ValueError:
            return None

    worded = re.search(
        r"\b(\d{1,2})\s+([a-zçğıöşü]+)\s+(20\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    if worded:
        month = TR_MONTHS.get(worded.group(2).lower())
        if month:
            try:
                return datetime(
                    int(worded.group(3)), month, int(worded.group(1)),
                    tzinfo=ISTANBUL,
                ).date()
            except ValueError:
                return None
    return None


def _bulletin(source, title, page_url, document_url, date_text, render_html=False):
    published_date = parse_bulletin_date(date_text or title)
    return {
        "source": source,
        "title": _clean(title) or f"{BULLETIN_LABELS[source]} Günlük Bülten",
        "page_url": page_url,
        "document_url": document_url,
        "date_text": _clean(date_text),
        "published_date": published_date.isoformat() if published_date else "",
        "render_html": bool(render_html),
        "key": base.canonical_url(document_url or page_url),
    }


def fetch_tera_bulletin(session=requests):
    response = session.get(TERA_DAILY, headers=base.headers(TERA_DAILY), timeout=BULLETIN_TIMEOUT)
    soup = _response_soup(response)
    latest = _first_anchor(
        soup,
        lambda text, href: bool(
            re.search(r"günlük\s+bülten\s+\d{1,2}\.\d{1,2}\.20\d{2}", text, re.IGNORECASE)
        ),
    )
    if not latest:
        return None
    title = _clean(latest.get_text(" ", strip=True))
    page_url = urljoin(TERA_DAILY, latest["href"])
    detail = session.get(page_url, headers=base.headers(TERA_DAILY), timeout=BULLETIN_TIMEOUT)
    detail_soup = _response_soup(detail)
    pdf = _first_anchor(
        detail_soup,
        lambda text, href: href.lower().split("?", 1)[0].endswith(".pdf")
        or "raporun tamamına" in text.lower()
        or text.lower().strip() == "pdf dosyası",
    )
    if not pdf:
        return None
    document_url = urljoin(page_url, pdf["href"])
    return _bulletin("tera", title, page_url, document_url, title)


def fetch_info_bulletin(session=requests):
    response = session.get(INFO_DAILY, headers=base.headers(INFO_DAILY), timeout=BULLETIN_TIMEOUT)
    soup = _response_soup(response)
    pdf_like = _first_anchor(
        soup,
        lambda text, href: "pdf indir" in text.lower() and "türkçe" in text.lower(),
    )
    if not pdf_like:
        return None
    page_text = _clean(soup.get_text(" ", strip=True))
    date_match = re.search(
        r"Günlük Bülten\s*,?\s*(\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+20\d{2})",
        page_text,
        flags=re.IGNORECASE,
    )
    date_text = date_match.group(1) if date_match else ""
    document_url = urljoin(INFO_DAILY, pdf_like["href"])
    # İnfo'nun güncel "PDF İNDİR" bağlantısı HTML bülten döndürüyor.
    # GitHub runner'daki Chrome bu sayfayı PDF'e yazdırır.
    return _bulletin(
        "info",
        f"Günlük Bülten {date_text}".strip(),
        INFO_DAILY,
        document_url,
        date_text,
        render_html=True,
    )


def fetch_a1_bulletin(session=requests):
    response = session.get(A1_DAILY, headers=base.headers(A1_DAILY), timeout=BULLETIN_TIMEOUT)
    soup = _response_soup(response)
    latest = _first_anchor(
        soup,
        lambda text, href: bool(
            re.search(
                r"günlük\s+bülten\s*[–-]\s*\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+20\d{2}",
                text,
                flags=re.IGNORECASE,
            )
        ),
    )
    if not latest:
        return None
    title = _clean(latest.get_text(" ", strip=True))
    document_url = urljoin(A1_DAILY, latest["href"])
    return _bulletin("a1capital", title, A1_DAILY, document_url, title)


def fetch_bulls_bulletin(session=requests):
    response = session.get(BULLS_DAILY, headers=base.headers(BULLS_DAILY), timeout=BULLETIN_TIMEOUT)
    soup = _response_soup(response)
    latest = _first_anchor(
        soup,
        lambda text, href: "devamını okuyun" in text.lower()
        and bool(re.search(r"/gunluk-bulten--\d+", href)),
    )
    if not latest:
        return None
    page_url = urljoin(BULLS_DAILY, latest["href"])
    detail = session.get(page_url, headers=base.headers(BULLS_DAILY), timeout=BULLETIN_TIMEOUT)
    detail_soup = _response_soup(detail)
    heading = detail_soup.find(["h1", "h2"], string=re.compile(r"Günlük Bülten", re.IGNORECASE))
    page_text = _clean(detail_soup.get_text(" ", strip=True))
    date_match = re.search(r"\b\d{1,2}\.\d{1,2}\.20\d{2}\b", page_text)
    date_text = date_match.group(0) if date_match else ""
    pdf = _first_anchor(
        detail_soup,
        lambda text, href: href.lower().split("?", 1)[0].endswith(".pdf")
        or "detaylı pdf raporu" in text.lower(),
    )
    if not pdf:
        return None
    document_url = urljoin(page_url, pdf["href"])
    title = _clean(heading.get_text(" ", strip=True) if heading else "Günlük Bülten")
    if date_text:
        title = f"{title} {date_text}"
    return _bulletin("bulls", title, page_url, document_url, date_text)


BULLETIN_FETCHERS = {
    "tera": fetch_tera_bulletin,
    "info": fetch_info_bulletin,
    "a1capital": fetch_a1_bulletin,
    "bulls": fetch_bulls_bulletin,
}


def _normalize_kap_line(line):
    line = KAP_SYSTEM_TOKEN.sub(" ", _clean(line))
    line = re.sub(r"\s+", " ", line).strip(" ·-|")
    line = re.sub(r"\bHayır\s*\(No\)\s*Hayır\s*\(No\)\b", "Hayır", line, flags=re.IGNORECASE)
    line = re.sub(r"\bEvet\s*\(Yes\)\s*Evet\s*\(Yes\)\b", "Evet", line, flags=re.IGNORECASE)
    line = re.sub(r"\bHayır\s*\(No\)\b", "Hayır", line, flags=re.IGNORECASE)
    line = re.sub(r"\bEvet\s*\(Yes\)\b", "Evet", line, flags=re.IGNORECASE)
    return line


def compact_kap_detail(soup):
    content = soup.select_one(".disclosureScrollableArea")
    if not content:
        return ""

    for node in content.select("script, style, input, button, svg, noscript"):
        node.decompose()

    raw_lines = content.get_text("\n", strip=True).splitlines()
    lines = []
    seen = set()
    for raw in raw_lines:
        line = _normalize_kap_line(raw)
        if not line:
            continue
        lowered = line.lower()
        if lowered in KAP_SKIP_EXACT:
            continue
        if any(lowered.startswith(prefix) for prefix in KAP_BOILERPLATE_STARTS):
            continue
        if re.fullmatch(r"[\[\]A-Z0-9_(). -]{6,}", line) and "_" in line:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        lines.append(line)

    if not lines:
        return ""

    explanation_index = next(
        (index for index, line in enumerate(lines) if line.lower().startswith("açıklamalar")),
        None,
    )
    useful = lines[explanation_index + 1:] if explanation_index is not None else lines

    sentence_like = [
        line for line in useful
        if len(line) >= 28
        and not any(
            line.lower().startswith(prefix)
            for prefix in (
                "ilgili şirketler", "related companies", "ilgili fonlar", "related funds",
                "türkçe", "turkish", "ingilizce", "english", "bildirim içeriği",
                "announcement content",
            )
        )
    ]
    useful = sentence_like[-8:] if sentence_like else useful[-8:]

    detail = " ".join(useful)
    detail = KAP_SYSTEM_TOKEN.sub(" ", detail)
    detail = re.sub(r"\s+", " ", detail).strip()
    return detail[:1200]


def enhanced_enrich(item, session=requests):
    if item["source"] != "kap":
        return ORIGINAL_ENRICH(item, session)

    response = session.get(item["link"], headers=base.headers(), timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    detail = compact_kap_detail(soup)
    if detail:
        item["detail"] = detail
    return item


def _strip_company_from_summary(summary, company):
    value = _clean(summary)
    company = _clean(company)
    if company:
        value = re.sub(
            rf"(?:^|[·|]\s*)Şirket:\s*{re.escape(company)}(?:\s*[·|]|$)",
            " ",
            value,
            flags=re.IGNORECASE,
        )
    return re.sub(r"\s*[·|]\s*$", "", re.sub(r"\s+", " ", value)).strip(" ·|")


def build_message(item):
    if item.get("source") != "kap":
        return ORIGINAL_BUILD_MESSAGE(item)

    title = _clean(item.get("title")) or "KAP Bildirimi"
    ticker = ""
    subject = title
    if " — " in title:
        ticker, subject = [part.strip() for part in title.split(" — ", 1)]

    company = _clean(item.get("provider"))
    published = base.format_date(item.get("published"))
    summary = _strip_company_from_summary(item.get("summary"), company)
    detail = _clean(item.get("detail"))

    if detail and summary:
        normalized_detail = _clean(detail).lower()
        normalized_summary = _clean(summary).lower()
        if normalized_detail == normalized_summary or normalized_detail.startswith(normalized_summary):
            detail = detail[len(summary):].strip(" .·")

    header = f"📣 <b>KAP{f' · {html.escape(ticker)}' if ticker else ''}</b>"
    parts = [header, f"<b>{html.escape(subject)}</b>"]
    if company and company.lower() != "kap":
        parts.append(f"🏢 {html.escape(company)}")
    if published:
        parts.append(f"🕒 {html.escape(published)}")
    if summary:
        parts.append(f"📝 <b>Özet:</b> {html.escape(summary)}")
    if detail:
        parts.append(f"ℹ️ <b>Detay:</b> {html.escape(detail)}")
    if item.get("attachment_count"):
        parts.append(f"📎 {int(item['attachment_count'])} ek")
    parts.append(
        f'<a href="{html.escape(item["link"], quote=True)}">KAP bildiriminin tamamını aç</a>'
    )

    message = "\n".join(parts)
    if len(message) <= 3900:
        return message

    link = parts[-1]
    fixed = "\n".join(parts[:4] + [link])
    body = "\n".join(parts[4:-1])
    allowed = max(200, 3900 - len(fixed) - 8)
    return "\n".join(parts[:4] + [body[:allowed].rstrip() + "…", link])


def _telegram_base_payload():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_TOKEN veya TELEGRAM_CHAT_ID eksik")
    payload = {"chat_id": chat_id, "parse_mode": "HTML"}
    if os.getenv("TELEGRAM_MESSAGE_THREAD_ID"):
        payload["message_thread_id"] = int(os.environ["TELEGRAM_MESSAGE_THREAD_ID"])
    return token, payload


def _find_chrome():
    for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(candidate)
        if path:
            return path
    return ""


def _download_pdf(url, destination, session=requests):
    response = session.get(url, headers=base.headers(url), timeout=60, stream=True)
    response.raise_for_status()
    limit = BULLETIN_MAX_MB * 1024 * 1024
    total = 0
    with open(destination, "wb") as stream:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise RuntimeError(f"Bülten {BULLETIN_MAX_MB} MB sınırını aştı")
            stream.write(chunk)
    with open(destination, "rb") as stream:
        signature = stream.read(5)
    if signature != b"%PDF-":
        raise RuntimeError(f"PDF beklenirken farklı içerik geldi: {url}")


def _render_html_pdf(url, destination):
    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError("İnfo bültenini PDF'e çevirmek için Chrome bulunamadı")
    command = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-pdf-header-footer",
        f"--print-to-pdf={destination}",
        url,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not Path(destination).exists():
        raise RuntimeError(
            f"Chrome PDF üretimi başarısız: {(result.stderr or result.stdout)[-500:]}"
        )
    if Path(destination).stat().st_size > BULLETIN_MAX_MB * 1024 * 1024:
        raise RuntimeError(f"Oluşan PDF {BULLETIN_MAX_MB} MB sınırını aştı")


def send_bulletin_document(item, session=requests):
    label = BULLETIN_LABELS[item["source"]]
    date_text = item.get("date_text") or item.get("published_date") or ""
    caption_parts = [f"📄 <b>{html.escape(label)} · Günlük Bülten</b>"]
    if date_text:
        caption_parts.append(html.escape(date_text))
    caption_parts.append(
        f'<a href="{html.escape(item["page_url"], quote=True)}">Kurumun araştırma sayfasını aç</a>'
    )
    caption = "\n".join(caption_parts)

    if base.DRY_RUN:
        print(
            f"DRY_RUN PDF [{label}] {date_text}: {item['document_url']} "
            f"(HTML->PDF={item.get('render_html')})"
        )
        return True

    token, payload = _telegram_base_payload()
    payload["caption"] = caption
    safe_date = (
        item.get("published_date") or datetime.now(ISTANBUL).date().isoformat()
    ).replace("-", "")
    filename = f"{item['source']}_gunluk_bulten_{safe_date}.pdf"

    with tempfile.TemporaryDirectory(prefix="bulletin-") as directory:
        pdf_path = os.path.join(directory, filename)
        if item.get("render_html"):
            _render_html_pdf(item["document_url"], pdf_path)
        else:
            _download_pdf(item["document_url"], pdf_path, session=session)

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
                print(f"Telegram PDF deneme {attempt} başarısız [{label}]: {exc}")
                time.sleep(min(60, attempt * 5))
    return False


def send_latest_bulletins():
    if not BULLETIN_SOURCES:
        return

    state = base.load_state()
    bulletin_state = state.setdefault("bulletins", {})
    today = datetime.now(ISTANBUL).date()

    for source in BULLETIN_SOURCES:
        fetcher = BULLETIN_FETCHERS.get(source)
        if not fetcher:
            print(f"Bilinmeyen bülten kaynağı atlandı: {source}")
            continue
        try:
            item = fetcher()
        except Exception as exc:
            print(f"{BULLETIN_LABELS.get(source, source)} bülteni okunamadı: {exc}")
            continue
        if not item or not item.get("key"):
            print(f"{BULLETIN_LABELS[source]}: güncel bülten bulunamadı")
            continue

        source_state = bulletin_state.setdefault(source, {"last_key": ""})
        if source_state.get("last_key") == item["key"]:
            print(f"{BULLETIN_LABELS[source]}: bülten zaten gönderildi")
            continue

        published = parse_bulletin_date(
            item.get("date_text") or item.get("published_date") or item.get("title")
        )
        if not source_state.get("last_key") and published and published != today:
            source_state["last_key"] = item["key"]
            print(
                f"{BULLETIN_LABELS[source]} başlangıç referansı alındı "
                f"({published.isoformat()}); eski PDF gönderilmedi"
            )
            continue

        if send_bulletin_document(item):
            source_state["last_key"] = item["key"]
            source_state["sent_at"] = datetime.now(ISTANBUL).isoformat()
            print(f"{BULLETIN_LABELS[source]} günlük bülteni PDF olarak gönderildi")
            time.sleep(base.SEND_DELAY)

    base.save_state(state)


def main():
    # Mevcut kaynakları ve tekrar filtresini koru; yalnız KAP görünümünü iyileştir.
    base.enrich = enhanced_enrich
    base.build_message = build_message
    base.main()

    # PDF bültenleri haber tekrar filtresinden ve haber gönderim limitinden bağımsızdır.
    send_latest_bulletins()


if __name__ == "__main__":
    main()
