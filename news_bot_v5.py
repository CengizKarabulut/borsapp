"""v5: Aracı kurum bültenlerini genişletir; açık PDF'leri belge, kısıtlıları resmi link olarak yollar."""

import html
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import news_bot as base
import news_bot_v4 as v4


ISTANBUL = ZoneInfo("Europe/Istanbul")

# v4'teki dört kaynak korunur. Aşağıdakiler resmi araştırma/bülten sayfalarıdır.
BROKER_CONFIGS = {
    "yapikredi": {
        "label": "Yapı Kredi",
        "url": "https://www.yapikredi.com.tr/yapi-kredi-hakkinda/piyasa-bulteni/",
        "keywords": ("günlük", "bülten"),
        "delivery": "auto",
    },
    "akyatirim": {
        "label": "Ak Yatırım",
        "url": "https://www.akyatirim.com.tr/tr",
        "keywords": ("günlük bülten", "araştırma"),
        "delivery": "auto",
    },
    "ziraat": {
        "label": "Ziraat Yatırım",
        "url": "https://service.ziraatyatirim.com.tr/sabah-stratejisi",
        "keywords": ("sabah stratejisi", "raporumuz için", "günlük"),
        "delivery": "auto",
    },
    "qnb": {
        "label": "QNB Invest",
        "url": "https://www.qnbinvest.com.tr/",
        "keywords": ("bist 100", "günlük bülten", "qnb invest bugün"),
        # QNB sayfasındaki yeniden paylaşım kısıtı nedeniyle yalnız resmi bağlantı.
        "delivery": "link",
    },
    "garanti": {
        "label": "Garanti BBVA Yatırım",
        "url": "https://www.garantibbvayatirim.com.tr/arastirma-raporlari/gunluk-piyasa-ozeti",
        "keywords": ("günlük piyasa özeti", "günlük"),
        # Araştırma arşivi müşteri girişine bağlı.
        "delivery": "link",
    },
    "midas": {
        "label": "Midas",
        "url": "https://www.getmidas.com/midas-kulaklari/analist-notlari/",
        "keywords": (
            "piyasa açılmadan önce", "güne başlarken", "küresel piyasalar ve bist"
        ),
        "delivery": "link",
    },
    "phillipcapital": {
        "label": "PhillipCapital Türkiye",
        "url": "https://www.phillipcapital.com.tr/arastirma-urunleri",
        "keywords": ("yurt içi günlük bülten", "günlük bülten ve hisse önerileri"),
        "delivery": "auto",
    },
    "gedik": {
        "label": "Gedik Yatırım",
        "url": "https://gedik.com/yurt-ici-piyasa-bultenleri/gunluk-bulten",
        "keywords": ("günlük bülten",),
        # Sayfa bülten aboneliği istiyor; erişim atlatılmaz.
        "delivery": "link",
    },
    "global": {
        "label": "Global Menkul Değerler",
        "url": "https://www.global.com.tr/tr/sayfa/arastirma-raporlari",
        "keywords": ("günlük bülten",),
        "delivery": "auto",
    },
    "unlu": {
        "label": "ÜNLÜ Menkul",
        "url": "https://www.unlumenkul.com/borsa-analiz/",
        "keywords": ("günlük bülten", "bist"),
        "delivery": "link",
    },
    # Ek kurumlar: aynı altyapıda takip edilir.
    "oyak": {
        "label": "OYAK Yatırım",
        "url": "https://www.oyakyatirim.com.tr/arastirma-raporlari",
        "keywords": ("günlük bülten",),
        "delivery": "auto",
    },
    "seker": {
        "label": "Şeker Yatırım",
        "url": "https://www.sekeryatirim.com.tr/Arastirma/ArastirmaRaporlari",
        "keywords": ("günlük bülten", "şirket haberleri"),
        "delivery": "auto",
    },
    "integral": {
        "label": "İntegral Yatırım",
        "url": "https://integralyatirim.com.tr/arastirma-raporlari",
        "keywords": ("bist günlük bülten", "günlük bülten"),
        "delivery": "auto",
    },
    "isyatirim": {
        "label": "İş Yatırım",
        "url": "https://www.isyatirim.com.tr/tr-tr/analiz/arastirma-raporlari/Pages/default.aspx",
        "keywords": ("günlük", "piyasa"),
        "delivery": "auto",
    },
    "halk": {
        "label": "Halk Yatırım",
        "url": "https://www.halkyatirim.com.tr/arastirma/raporlar",
        "keywords": ("günlük bülten", "şirket haberleri"),
        "delivery": "auto",
    },
    "vakif": {
        "label": "Vakıf Yatırım",
        "url": "https://www.vkyanaliz.com/",
        "keywords": ("günlük strateji bülteni", "günlük bülten"),
        "delivery": "auto",
    },
    "deniz": {
        "label": "Deniz Yatırım",
        "url": "https://www.denizyatirim.com/piyasalar/",
        "keywords": ("günlük bülten",),
        # Güncel detaylar müşteri girişine bağlı.
        "delivery": "link",
    },
}

DEFAULT_BULLETIN_SOURCES = (
    "tera,info,a1capital,bulls,"
    "yapikredi,akyatirim,ziraat,qnb,garanti,midas,phillipcapital,gedik,global,unlu,"
    "oyak,seker,integral,isyatirim,halk,vakif,deniz"
)

DATE_PATTERNS = (
    re.compile(r"\b\d{1,2}[./]\d{1,2}[./]20\d{2}\b"),
    re.compile(
        r"\b\d{1,2}\s+(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|Haziran|Temmuz|"
        r"Ağustos|Agustos|Eylül|Eylul|Ekim|Kasım|Kasim|Aralık|Aralik)\s+20\d{2}\b",
        re.IGNORECASE,
    ),
)


def clean(value):
    return base.clean(value)


def extract_date(text):
    text = clean(text)
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return ""


def context_text(anchor, levels=3):
    chunks = [clean(anchor.get_text(" ", strip=True))]
    node = anchor
    for _ in range(levels):
        node = getattr(node, "parent", None)
        if not node:
            break
        chunks.append(clean(node.get_text(" ", strip=True))[:1200])
    return clean(" ".join(chunks))


def candidate_score(text, href, keywords):
    lowered = clean(text).lower()
    href_lower = clean(href).lower()
    score = 0
    for keyword in keywords:
        keyword = keyword.lower()
        if keyword in lowered:
            score += 12
        elif keyword in href_lower:
            score += 6
    if extract_date(lowered):
        score += 8
    if href_lower.split("?", 1)[0].endswith(".pdf"):
        score += 12
    if any(token in lowered for token in ("günlük", "sabah", "piyasa", "bist")):
        score += 4
    if any(token in lowered for token in ("yurt dışı", "forex", "viop", "varant")):
        score -= 3
    return score


def choose_best_anchor(soup, keywords):
    best = None
    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        text = context_text(anchor)
        score = candidate_score(text, href, keywords)
        if score <= 0:
            continue
        candidate = (score, anchor, text)
        if best is None or candidate[0] > best[0]:
            best = candidate
    return best


def find_public_pdf(soup, base_url, keywords):
    best = None
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, clean(anchor.get("href")))
        text = context_text(anchor)
        href_lower = href.lower().split("?", 1)[0]
        is_pdf = href_lower.endswith(".pdf") or "pdf" in clean(anchor.get_text(" ", strip=True)).lower()
        if not is_pdf:
            continue
        score = candidate_score(text, href, keywords) + 10
        candidate = (score, href, text)
        if best is None or candidate[0] > best[0]:
            best = candidate
    return best


def same_public_site(source_url, target_url):
    source_host = urlparse(source_url).netloc.lower().removeprefix("www.")
    target_host = urlparse(target_url).netloc.lower().removeprefix("www.")
    if not source_host or not target_host:
        return False
    # Kurumun kendi alan adı veya kendi CDN alt alanı.
    source_root = ".".join(source_host.split(".")[-2:])
    target_root = ".".join(target_host.split(".")[-2:])
    return source_root == target_root


def make_item(source, title, page_url, document_url, date_text, delivery):
    published = v4.parse_bulletin_date(date_text or title)
    final_url = document_url or page_url
    key_seed = f"{source}:{published.isoformat() if published else date_text}:{base.canonical_url(final_url)}"
    return {
        "source": source,
        "title": clean(title) or f"{BROKER_CONFIGS[source]['label']} Günlük Bülten",
        "page_url": page_url,
        "document_url": document_url,
        "date_text": clean(date_text),
        "published_date": published.isoformat() if published else "",
        "render_html": False,
        "delivery": delivery,
        "key": key_seed,
    }


def fetch_configured_bulletin(source, session=requests):
    config = BROKER_CONFIGS[source]
    page_url = config["url"]
    response = session.get(page_url, headers=base.headers(page_url), timeout=v4.BULLETIN_TIMEOUT)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")

    best = choose_best_anchor(soup, config["keywords"])
    page_text = clean(soup.get_text(" ", strip=True))
    if best:
        _, anchor, context = best
        target = urljoin(page_url, clean(anchor.get("href")))
        date_text = extract_date(context) or extract_date(page_text[:5000])
        title = clean(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {"tıklayınız", "detaylı oku", "raporu incele", "görüntüle", "indir"}:
            title = next(
                (clean(tag.get_text(" ", strip=True)) for tag in anchor.find_all_previous(["h1", "h2", "h3", "h4"], limit=3)
                 if clean(tag.get_text(" ", strip=True))),
                f"{config['label']} Günlük Bülten",
            )
    else:
        target = page_url
        date_text = extract_date(page_text[:8000])
        title = f"{config['label']} Günlük Bülten"

    # Erişimi kısıtlı veya yeniden dağıtıma açık olmayan kaynaklarda yalnız resmi link kullan.
    if config["delivery"] == "link":
        return make_item(source, title, target, "", date_text, "link") if date_text else None

    # Liste sayfasındaki doğrudan resmi PDF.
    direct_pdf = find_public_pdf(soup, page_url, config["keywords"])
    if direct_pdf and same_public_site(page_url, direct_pdf[1]):
        pdf_url = direct_pdf[1]
        pdf_date = extract_date(direct_pdf[2]) or date_text
        return make_item(source, title, page_url, pdf_url, pdf_date, "pdf")

    # Seçilen bağlantı zaten kurumun kendi PDF'i ise belge olarak gönder.
    if target.lower().split("?", 1)[0].endswith(".pdf") and same_public_site(page_url, target):
        return make_item(source, title, page_url, target, date_text, "pdf")

    # Resmi detay sayfasını aç; açık PDF varsa onu bul.
    if target.startswith("http") and same_public_site(page_url, target):
        try:
            detail_response = session.get(target, headers=base.headers(page_url), timeout=v4.BULLETIN_TIMEOUT)
            detail_response.raise_for_status()
            detail_response.encoding = detail_response.encoding or "utf-8"
            detail_soup = BeautifulSoup(detail_response.text, "html.parser")
            detail_pdf = find_public_pdf(detail_soup, target, config["keywords"])
            if detail_pdf and same_public_site(page_url, detail_pdf[1]):
                pdf_date = extract_date(detail_pdf[2]) or date_text
                return make_item(source, title, target, detail_pdf[1], pdf_date, "pdf")
        except requests.RequestException as exc:
            print(f"{config['label']} detay sayfası okunamadı: {exc}")

    # Açık PDF bulunamıyorsa resmi rapor sayfasını kaçırmamak için link olarak bildir.
    return make_item(source, title, target, "", date_text, "link") if date_text else None


def send_bulletin(item, session=requests):
    if item.get("delivery") != "link":
        return v4.ORIGINAL_SEND_BULLETIN_DOCUMENT(item, session=session)

    label = v4.BULLETIN_LABELS.get(item["source"], item["source"])
    date_text = item.get("date_text") or item.get("published_date") or ""
    link = item.get("page_url") or item.get("document_url")
    message = [f"📚 <b>{html.escape(label)} · Günlük Bülten</b>"]
    if date_text:
        message.append(f"🗓 {html.escape(date_text)}")
    message.append(
        "ℹ️ Bu kurumun raporu herkese açık doğrudan PDF olarak alınamadığı için resmi kaynak bağlantısı gönderildi."
    )
    message.append(f'<a href="{html.escape(link, quote=True)}">Resmî bülteni aç</a>')
    return base.send_message("\n".join(message))


def install_extensions():
    # v4'ün mevcut göndericisini sakla; sonra access-aware wrapper ile değiştir.
    if not hasattr(v4, "ORIGINAL_SEND_BULLETIN_DOCUMENT"):
        v4.ORIGINAL_SEND_BULLETIN_DOCUMENT = v4.send_bulletin_document

    for source, config in BROKER_CONFIGS.items():
        v4.BULLETIN_LABELS[source] = config["label"]
        v4.BULLETIN_FETCHERS[source] = (
            lambda session=requests, source=source: fetch_configured_bulletin(source, session)
        )

    requested = os.getenv("BULLETIN_SOURCES", DEFAULT_BULLETIN_SOURCES)
    v4.BULLETIN_SOURCES = [value.strip().lower() for value in requested.split(",") if value.strip()]
    v4.send_bulletin_document = send_bulletin


def main():
    install_extensions()
    v4.main()


if __name__ == "__main__":
    main()
