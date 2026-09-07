"""v6: Katmanlı finans akışı, akıllı KAP özeti ve çok tür aracı kurum araştırma merkezi."""

import html
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import news_bot as base
import news_bot_v4 as v4
import news_bot_v5 as v5


ISTANBUL = ZoneInfo("Europe/Istanbul")

BIST_URL = "https://www.borsaistanbul.com/duyurular"
TCMB_PRESS_RSS = (
    "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB%2BTR/Bottom%2BMenu/Diger/RSS/"
    "Basin%2BDuyurulari"
)
TUIK_URL = "https://veriportali.tuik.gov.tr/tr/"
SPK_URL = f"https://spk.gov.tr/spk-bultenleri/{datetime.now(ISTANBUL).year}-yili-spk-bultenleri"

OFFICIAL_LABELS = {
    "bist": "Borsa İstanbul",
    "tcmb": "TCMB",
    "tuik": "TÜİK",
    "spk": "SPK",
}

LAYER_INFO = {
    "kap": ("🏛", "RESMÎ", "KAP"),
    "bist": ("🏛", "RESMÎ", "Borsa İstanbul"),
    "tcmb": ("🏛", "RESMÎ", "TCMB"),
    "tuik": ("🏛", "RESMÎ", "TÜİK"),
    "spk": ("🏛", "RESMÎ", "SPK"),
    "bloomberght": ("⚡", "HIZLI PİYASA", "Bloomberg HT"),
    "investing": ("⚡", "HIZLI PİYASA", "Investing.com Türkiye"),
    "ntvpara": ("⚡", "HIZLI PİYASA", "NTV Para"),
    "trthaber": ("⚡", "HIZLI PİYASA", "TRT Haber Ekonomi"),
    "tradingview": ("⚡", "HIZLI PİYASA", "TradingView"),
    "forexfactory": ("🗓", "EKONOMİK TAKVİM", "Forex Factory"),
}

REPORT_TYPES = (
    (
        "model_portfoy", "🎯", "MODEL PORTFÖY",
        ("model portföy", "model portfoy", "öneri listesi", "oneri listesi", "hisse önerileri", "hisse onerileri"),
    ),
    (
        "teknik_bulten", "📈", "TEKNİK BÜLTEN",
        ("teknik bülten", "teknik bulten", "teknik analiz", "teknik görünüm", "teknik gorunum"),
    ),
    (
        "sirket_raporu", "🏢", "ŞİRKET RAPORU",
        (
            "şirket raporu", "sirket raporu", "şirket analizi", "sirket analizi",
            "şirket güncelleme", "sirket guncelleme", "hedef fiyat", "bilanço analizi", "bilanco analizi",
        ),
    ),
    (
        "strateji_raporu", "🧭", "STRATEJİ RAPORU",
        (
            "strateji raporu", "yatırım stratejisi", "yatirim stratejisi", "sabah stratejisi",
            "piyasa stratejisi", "strateji bülteni", "strateji bulteni", "haftalık strateji",
            "aylık strateji", "aylik strateji",
        ),
    ),
    (
        "gunluk_bulten", "📄", "GÜNLÜK BÜLTEN",
        (
            "günlük bülten", "gunluk bulten", "günlük piyasa", "gunluk piyasa",
            "güne başlarken", "gune baslarken", "piyasa açılmadan önce", "piyasa acilmadan once",
            "sabah bülteni", "sabah bulteni", "bist günlük", "bist gunluk",
        ),
    ),
)

KAP_KIND_RULES = (
    (
        "sermaye", "💰", "SERMAYE İŞLEMİ",
        ("sermaye artır", "sermaye artir", "bedelli", "bedelsiz", "kayıtlı sermaye", "kayitli sermaye"),
    ),
    (
        "pay_islem", "👤", "PAY ALIM/SATIM",
        ("pay alım satım", "pay alim satim", "pay alımı", "pay alimi", "pay satımı", "pay satimi"),
    ),
    (
        "geri_alim", "🔄", "PAY GERİ ALIMI",
        ("geri alım", "geri alim", "geri alınan pay", "geri alinan pay"),
    ),
    (
        "yeni_is", "🤝", "YENİ İŞ / SÖZLEŞME",
        ("yeni iş ilişkisi", "yeni is iliskisi", "sözleşme imzalan", "sozlesme imzalan", "ihale", "sipariş", "siparis"),
    ),
    (
        "finansal", "📊", "FİNANSAL RAPOR",
        ("finansal rapor", "finansal tablo", "faaliyet raporu", "bilanço", "bilanco", "kar veya zarar"),
    ),
    (
        "temettu", "💸", "KÂR PAYI / TEMETTÜ",
        ("kar payı", "kâr payı", "temettü", "temettu"),
    ),
    (
        "yonetim", "🏢", "KURUMSAL / YÖNETİM",
        ("kurumsal yönetim", "kurumsal yonetim", "yönetim kurulu", "yonetim kurulu", "derecelendirme"),
    ),
)

RESEARCH_PAGE_CONFIGS = {
    "tera": {"label": "TERA Yatırım", "url": v4.TERA_DAILY, "delivery": "auto"},
    "info": {"label": "İnfo Yatırım", "url": v4.INFO_DAILY, "delivery": "auto"},
    "a1capital": {"label": "A1 Capital", "url": v4.A1_DAILY, "delivery": "auto"},
    "bulls": {"label": "Bulls Yatırım", "url": v4.BULLS_DAILY, "delivery": "auto"},
}
for _source, _config in v5.BROKER_CONFIGS.items():
    RESEARCH_PAGE_CONFIGS[_source] = {
        "label": _config["label"],
        "url": _config["url"],
        "delivery": _config["delivery"],
    }


TR_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[./]\d{1,2}[./]20\d{2}|"
    r"\d{1,2}\s+(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|Haziran|Temmuz|"
    r"Ağustos|Agustos|Eylül|Eylul|Ekim|Kasım|Kasim|Aralık|Aralik)\s+20\d{2})\b",
    re.IGNORECASE,
)


def clean(value):
    return base.clean(value)


def _get_soup(url, session=requests):
    response = session.get(url, headers=base.headers(url), timeout=35)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def extract_tr_date(text):
    match = TR_DATE_RE.search(clean(text))
    return match.group(0) if match else ""


def fetch_bist(session=requests):
    soup = _get_soup(BIST_URL, session)
    found, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(BIST_URL, clean(anchor.get("href")))
        title = clean(anchor.get_text(" ", strip=True))
        context = clean(anchor.parent.get_text(" ", strip=True) if anchor.parent else title)
        date_text = extract_tr_date(context)
        if not title or not date_text or href in seen:
            continue
        lowered = title.lower()
        if any(token in lowered for token in ("iletişim", "hakkında", "ana sayfa", "kariyer")):
            continue
        if "borsaistanbul.com" not in href:
            continue
        seen.add(href)
        found.append(base.blank_item(
            "bist", title, href, id=href, provider="Borsa İstanbul",
            published=date_text, summary="Borsa İstanbul resmî duyurusu",
            category="Resmî Duyuru",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break
    return base.dedupe(found)


def fetch_tcmb(session=requests):
    response = session.get(TCMB_PRESS_RSS, headers=base.headers(TCMB_PRESS_RSS), timeout=35)
    response.raise_for_status()
    content = response.content
    soup = BeautifulSoup(content, "xml")
    items = soup.find_all("item")
    found = []
    if items:
        for node in items:
            title = clean(node.title.get_text(" ", strip=True) if node.title else "")
            link = clean(node.link.get_text(" ", strip=True) if node.link else "")
            published = clean(node.pubDate.get_text(" ", strip=True) if node.pubDate else "")
            if not title or not link:
                continue
            found.append(base.blank_item(
                "tcmb", title, urljoin("https://www.tcmb.gov.tr", link),
                id=link, provider="TCMB", published=published,
                summary="Türkiye Cumhuriyet Merkez Bankası resmî duyurusu",
                category="Basın Duyurusu",
            ))
            if len(found) >= base.NEWS_LIMIT:
                break
        return base.dedupe(found)

    # TCMB'nin RSS çıktısı bazı istemcilere düz metin dönebilir; link-title çiftlerini yedek olarak yakala.
    text = response.text
    pattern = re.compile(
        r"<!\[CDATA\[(?P<title>.*?)\]\]>\s*(?P<link>/wps/wcm/connect/TR/TCMB\+TR/[^\s<]+)\s*"
        r"(?P<date>\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+20\d{2}\s+\d{2}:\d{2}:\d{2})",
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        link = urljoin("https://www.tcmb.gov.tr", match.group("link"))
        found.append(base.blank_item(
            "tcmb", clean(match.group("title")), link,
            id=link, provider="TCMB", published=clean(match.group("date")),
            summary="Türkiye Cumhuriyet Merkez Bankası resmî duyurusu",
            category="Basın Duyurusu",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break
    return base.dedupe(found)


def fetch_tuik(session=requests):
    soup = _get_soup(TUIK_URL, session)
    found, seen = [], set()
    # Yeni Veri Portalı en son verileri tablo/satır yapısında yayımlıyor.
    for row in soup.find_all("tr"):
        text = clean(row.get_text(" ", strip=True))
        if "Haber Bülteni" not in text:
            continue
        date_text = extract_tr_date(text)
        anchor = row.find("a", href=True)
        if not anchor:
            continue
        href = urljoin(TUIK_URL, clean(anchor.get("href")))
        title = clean(anchor.get_text(" ", strip=True))
        if not title or not date_text or href in seen:
            continue
        seen.add(href)
        found.append(base.blank_item(
            "tuik", title, href, id=href, provider="TÜİK",
            published=date_text, summary=text[:700], category="Haber Bülteni",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break

    # Tema/SPA değişiminde ana sayfadaki haber bülteni bağlantılarını yedek olarak tara.
    if not found:
        for anchor in soup.find_all("a", href=True):
            href = urljoin(TUIK_URL, clean(anchor.get("href")))
            context = clean(anchor.parent.get_text(" ", strip=True) if anchor.parent else "")
            title = clean(anchor.get_text(" ", strip=True))
            date_text = extract_tr_date(context)
            if not title or not date_text or "Haber Bülteni" not in context or href in seen:
                continue
            seen.add(href)
            found.append(base.blank_item(
                "tuik", title, href, id=href, provider="TÜİK",
                published=date_text, summary=context[:700], category="Haber Bülteni",
            ))
            if len(found) >= base.NEWS_LIMIT:
                break
    return base.dedupe(found)


def fetch_spk(session=requests):
    soup = _get_soup(SPK_URL, session)
    found, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(SPK_URL, clean(anchor.get("href")))
        context = clean(anchor.parent.get_text(" ", strip=True) if anchor.parent else "")
        text = clean(anchor.get_text(" ", strip=True))
        combined = clean(f"{text} {context}")
        number = re.search(r"Bülten\s*No\s*:?\s*(20\d{2}[/ -]\d+)", combined, re.IGNORECASE)
        date_text = extract_tr_date(combined)
        if not number or not date_text or href in seen:
            continue
        seen.add(href)
        bulletin_no = number.group(1).replace(" ", "")
        found.append(base.blank_item(
            "spk", f"SPK Bülteni {bulletin_no}", href,
            id=bulletin_no, provider="SPK", published=date_text,
            summary=f"Sermaye Piyasası Kurulu resmî bülteni · {date_text}",
            category="SPK Bülteni",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break

    # Bazı SPK tema sürümlerinde bülten numarası link dışında düz metin olabilir.
    if not found:
        page_text = clean(soup.get_text("\n", strip=True))
        pattern = re.compile(
            r"Bülten\s*No\s*:?\s*(20\d{2}[/ -]\d+).*?Yayımlanma\s*:?\s*"
            r"(\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+20\d{2})",
            re.IGNORECASE,
        )
        for match in pattern.finditer(page_text):
            bulletin_no = match.group(1).replace(" ", "")
            found.append(base.blank_item(
                "spk", f"SPK Bülteni {bulletin_no}", SPK_URL,
                id=bulletin_no, provider="SPK", published=match.group(2),
                summary="Sermaye Piyasası Kurulu resmî bülteni",
                category="SPK Bülteni",
            ))
            if len(found) >= base.NEWS_LIMIT:
                break
    return base.dedupe(found)


def classify_report_type(text):
    lowered = clean(text).lower()
    for key, icon, label, keywords in REPORT_TYPES:
        if any(keyword in lowered for keyword in keywords):
            return key, icon, label
    return "arastirma", "📚", "ARAŞTIRMA RAPORU"


def classify_kap(item):
    text = clean(f"{item.get('title', '')} {item.get('summary', '')} {item.get('detail', '')}").lower()
    for key, icon, label, keywords in KAP_KIND_RULES:
        if any(keyword in text for keyword in keywords):
            return key, icon, label
    return "diger", "📣", "KAP BİLDİRİMİ"


def _first_match(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean(match.group(1))
    return ""


def smart_kap_facts(item):
    kind, _, _ = classify_kap(item)
    text = clean(f"{item.get('summary', '')} {item.get('detail', '')}")
    facts = []

    if kind == "sermaye":
        current = _first_match((
            r"(?:mevcut|çıkarılmış|ödenmiş)\s+sermaye[^0-9]{0,35}([0-9.]+(?:,[0-9]+)?\s*(?:TL|TRY))",
            r"sermaye[^0-9]{0,20}([0-9.]+(?:,[0-9]+)?\s*(?:TL|TRY))",
        ), text)
        target = _first_match((
            r"(?:ulaşılacak|yeni|artırılmış)\s+sermaye[^0-9]{0,35}([0-9.]+(?:,[0-9]+)?\s*(?:TL|TRY))",
        ), text)
        ratio = _first_match((
            r"(?:artırım|artış|oran)[^%0-9]{0,25}%?\s*([0-9]+(?:[.,][0-9]+)?\s*%)",
            r"%\s*([0-9]+(?:[.,][0-9]+)?)",
        ), text)
        if current:
            facts.append(f"Mevcut sermaye: {current}")
        if target and target != current:
            facts.append(f"Yeni sermaye: {target}")
        if ratio:
            facts.append(f"Oran: {ratio if '%' in ratio else '%' + ratio}")

    elif kind in {"pay_islem", "geri_alim"}:
        quantity = _first_match((
            r"([0-9.]+(?:,[0-9]+)?)\s*(?:adet|lot)\b",
            r"([0-9.]+(?:,[0-9]+)?)\s*TL\s*nominal",
        ), text)
        price = _first_match((
            r"(?:ortalama\s+fiyat|işlem\s+fiyatı|islem\s+fiyati|fiyat)[^0-9]{0,20}([0-9]+(?:[.,][0-9]+)?\s*TL)",
        ), text)
        share = _first_match((
            r"(?:sermayedeki\s+pay|pay\s+oran)[^%0-9]{0,20}%?\s*([0-9]+(?:[.,][0-9]+)?)",
        ), text)
        if quantity:
            facts.append(f"Miktar: {quantity} adet/lot")
        if price:
            facts.append(f"Fiyat: {price}")
        if share:
            facts.append(f"Sermaye payı: %{share}")

    elif kind == "yeni_is":
        amount = _first_match((
            r"(?:sözleşme|sozlesme|ihale|sipariş|siparis)[^.]{0,100}?(?:bedeli|tutarı|tutari)[^0-9]{0,20}"
            r"([0-9.]+(?:,[0-9]+)?\s*(?:TL|TRY|USD|EUR|GBP|₺|\$|€))",
            r"(?:bedeli|tutarı|tutari)[^0-9]{0,20}([0-9.]+(?:,[0-9]+)?\s*(?:TL|TRY|USD|EUR|GBP|₺|\$|€))",
        ), text)
        duration = _first_match((
            r"(?:süre|sure|teslim)[^0-9]{0,20}([0-9]+\s*(?:gün|gun|ay|yıl|yil))",
        ), text)
        if amount:
            facts.append(f"Sözleşme/iş tutarı: {amount}")
        if duration:
            facts.append(f"Süre: {duration}")

    elif kind == "finansal":
        period = _first_match((
            r"((?:20\d{2})\s*[/.-]\s*(?:03|06|09|12|3|6|9))",
            r"((?:1|2|3|4)\.?\s*çeyrek\s*20\d{2})",
            r"((?:Ocak|Nisan|Temmuz|Ekim)[-–](?:Mart|Haziran|Eylül|Aralık)\s*20\d{2})",
        ), text)
        if period:
            facts.append(f"Rapor dönemi: {period}")

    elif kind == "temettu":
        gross = _first_match((
            r"(?:brüt|brut)[^0-9]{0,20}([0-9]+(?:[.,][0-9]+)?\s*(?:TL|%))",
        ), text)
        date_value = _first_match((
            r"(?:ödeme|odeme|dağıtım|dagitim)\s+tarihi[^0-9]{0,20}(\d{1,2}[./]\d{1,2}[./]20\d{2})",
        ), text)
        if gross:
            facts.append(f"Brüt kâr payı: {gross}")
        if date_value:
            facts.append(f"Ödeme tarihi: {date_value}")

    return facts[:4]


def layered_build_message(item):
    source = item.get("source")
    if source == "kap":
        title = clean(item.get("title")) or "KAP Bildirimi"
        ticker, subject = "", title
        if " — " in title:
            ticker, subject = [part.strip() for part in title.split(" — ", 1)]
        company = clean(item.get("provider"))
        published = base.format_date(item.get("published"))
        summary = v4._strip_company_from_summary(item.get("summary"), company)
        detail = clean(item.get("detail"))
        _, kind_icon, kind_label = classify_kap(item)
        facts = smart_kap_facts(item)

        parts = [f"🏛 <b>RESMÎ | KAP{f' | {html.escape(ticker)}' if ticker else ''}</b>"]
        parts.append(f"{kind_icon} <b>{html.escape(kind_label)}</b>")
        parts.append(f"<b>{html.escape(subject)}</b>")
        if company and company.lower() != "kap":
            parts.append(f"🏢 {html.escape(company)}")
        if published:
            parts.append(f"🕒 {html.escape(published)}")
        if facts:
            parts.append("🔎 <b>Öne çıkan:</b> " + " · ".join(html.escape(value) for value in facts))
        if summary:
            parts.append(f"📝 <b>Özet:</b> {html.escape(summary)}")
        if detail and detail.lower() != summary.lower():
            parts.append(f"ℹ️ <b>Detay:</b> {html.escape(detail[:1100])}")
        if item.get("attachment_count"):
            parts.append(f"📎 {int(item['attachment_count'])} ek")
        parts.append(
            f'<a href="{html.escape(item["link"], quote=True)}">KAP bildiriminin tamamını aç</a>'
        )
        message = "\n".join(parts)
        if len(message) <= 3900:
            return message
        return message[:3700].rstrip() + "…\n" + parts[-1]

    if source in OFFICIAL_LABELS:
        _, layer, label = LAYER_INFO[source]
        published = base.format_date(item.get("published")) or clean(item.get("published"))
        parts = [f"🏛 <b>{layer} | {html.escape(label)}</b>", f"<b>{html.escape(item['title'])}</b>"]
        if published:
            parts.append(f"🕒 {html.escape(published)}")
        summary = clean(item.get("summary"))
        if summary:
            parts.append(f"📝 {html.escape(summary[:1000])}")
        parts.append(f'<a href="{html.escape(item["link"], quote=True)}">Resmî kaynağı aç</a>')
        return "\n".join(parts)

    # Mevcut haber formatını koru, üstüne katman etiketi ekle.
    message = v4.ORIGINAL_BUILD_MESSAGE(item)
    layer = LAYER_INFO.get(source)
    if not layer:
        return message
    icon, layer_name, label = layer
    return f"{icon} <b>{layer_name} | {html.escape(label)}</b>\n\n{message}"


def layered_enrich(item, session=requests):
    # Resmî liste kaynaklarında liste özeti yeterlidir; her 15 dakikada detay sayfasını ayrıca kazımayız.
    if item.get("source") in OFFICIAL_LABELS:
        return item
    return v4.ORIGINAL_ENRICH(item, session) if item.get("source") != "kap" else v4.enhanced_enrich(item, session)


def research_context(anchor, levels=3):
    chunks = [clean(anchor.get_text(" ", strip=True))]
    node = anchor
    for _ in range(levels):
        node = getattr(node, "parent", None)
        if not node:
            break
        chunks.append(clean(node.get_text(" ", strip=True))[:1000])
    return clean(" ".join(chunks))


def scan_research_page(source, config, session=requests):
    try:
        soup = _get_soup(config["url"], session)
    except Exception as exc:
        print(f"{config['label']} araştırma sayfası okunamadı: {exc}")
        return []

    found, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(config["url"], clean(anchor.get("href")))
        if not href or href in seen or href.startswith(("javascript:", "mailto:")):
            continue
        context = research_context(anchor)
        report_key, _, report_label = classify_report_type(context)
        if report_key == "arastirma":
            continue
        title = clean(anchor.get_text(" ", strip=True))
        if not title or len(title) < 4:
            title = report_label.title()
        date_text = extract_tr_date(context)
        published = v4.parse_bulletin_date(date_text)
        delivery = "link"
        document_url = ""
        if config.get("delivery") != "link" and href.lower().split("?", 1)[0].endswith(".pdf"):
            if v5.same_public_site(config["url"], href):
                delivery = "pdf"
                document_url = href
        item = {
            "source": source,
            "title": title,
            "page_url": href if delivery == "link" else config["url"],
            "document_url": document_url,
            "date_text": date_text,
            "published_date": published.isoformat() if published else "",
            "render_html": False,
            "delivery": delivery,
            "report_type": report_key,
            "report_label": report_label,
            "key": f"{source}:{report_key}:{base.canonical_url(href)}",
        }
        seen.add(href)
        found.append(item)
        if len(found) >= 20:
            break
    return found


def specialized_daily_items():
    items = []
    # v5 install_extensions sonrasında hem ilk dört hem genişletilmiş broker fetcher'ları v4'te bulunur.
    for source in RESEARCH_PAGE_CONFIGS:
        fetcher = v4.BULLETIN_FETCHERS.get(source)
        if not fetcher:
            continue
        try:
            item = fetcher()
        except Exception as exc:
            print(f"{RESEARCH_PAGE_CONFIGS[source]['label']} güncel bülteni okunamadı: {exc}")
            continue
        if not item:
            continue
        key, _, label = classify_report_type(f"{item.get('title', '')} {item.get('date_text', '')}")
        if key == "arastirma":
            key, label = "gunluk_bulten", "GÜNLÜK BÜLTEN"
        item["report_type"] = key
        item["report_label"] = label
        item["delivery"] = item.get("delivery") or ("pdf" if item.get("document_url") else "link")
        item["key"] = f"{source}:{key}:{item.get('key') or base.canonical_url(item.get('document_url') or item.get('page_url'))}"
        items.append(item)
    return items


def report_type_meta(item):
    key = item.get("report_type") or classify_report_type(item.get("title", ""))[0]
    for report_key, icon, label, _ in REPORT_TYPES:
        if report_key == key:
            return icon, label
    return "📚", "ARAŞTIRMA RAPORU"


def send_research_item(item, session=requests):
    label = RESEARCH_PAGE_CONFIGS.get(item["source"], {}).get("label") or v4.BULLETIN_LABELS.get(item["source"], item["source"])
    icon, report_label = report_type_meta(item)
    date_text = item.get("date_text") or item.get("published_date") or ""
    page_url = item.get("page_url") or item.get("document_url")
    header = f"📚 <b>ARAŞTIRMA | {html.escape(label)}</b>\n{icon} <b>{html.escape(report_label)} | {html.escape(label)}</b>"
    caption_parts = [header]
    if date_text:
        caption_parts.append(f"🗓 {html.escape(date_text)}")
    title = clean(item.get("title"))
    if title and report_label.lower() not in title.lower():
        caption_parts.append(f"📝 {html.escape(title[:500])}")
    caption_parts.append(f'<a href="{html.escape(page_url, quote=True)}">Resmî araştırma kaynağını aç</a>')
    caption = "\n".join(caption_parts)

    if base.DRY_RUN:
        print(f"DRY_RUN RESEARCH [{label}] [{report_label}] {page_url}")
        return True

    delivery = item.get("delivery")
    if delivery == "pdf" or item.get("render_html"):
        token, payload = v4._telegram_base_payload()
        payload["caption"] = caption[:1000]
        safe_date = (item.get("published_date") or datetime.now(ISTANBUL).date().isoformat()).replace("-", "")
        filename = f"{item['source']}_{item.get('report_type', 'arastirma')}_{safe_date}.pdf"
        with tempfile.TemporaryDirectory(prefix="research-") as directory:
            pdf_path = os.path.join(directory, filename)
            if item.get("render_html"):
                v4._render_html_pdf(item["document_url"], pdf_path)
            else:
                v4._download_pdf(item["document_url"], pdf_path, session=session)
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
                    print(f"Araştırma PDF Telegram deneme {attempt} başarısız [{label}]: {exc}")
                    time.sleep(min(60, attempt * 5))
        return False

    return base.send_message(caption)


def send_research_reports():
    state = base.load_state()
    research_state = state.setdefault("research_reports", {})
    old_bulletins = state.get("bulletins", {})
    today = datetime.now(ISTANBUL).date()

    candidates = specialized_daily_items()
    for source, config in RESEARCH_PAGE_CONFIGS.items():
        candidates.extend(scan_research_page(source, config))

    unique = []
    seen = set()
    for item in candidates:
        key = item.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)

    for item in unique:
        source = item["source"]
        report_type = item.get("report_type", "arastirma")
        source_state = research_state.setdefault(source, {})
        type_state = source_state.setdefault(report_type, {"seen_keys": []})
        seen_keys = set(type_state.get("seen_keys", []))
        if item["key"] in seen_keys:
            continue

        published = v4.parse_bulletin_date(item.get("date_text") or item.get("published_date") or "")
        first_for_type = not type_state.get("seen_keys")

        # v4/v5 daha önce bugünkü günlük bülteni gönderdiyse v6 geçişinde tekrar yollama.
        if report_type == "gunluk_bulten" and old_bulletins.get(source, {}).get("last_key"):
            type_state["seen_keys"] = list(dict.fromkeys([item["key"]] + type_state.get("seen_keys", [])))[:100]
            continue

        # Yeni tür ilk kez açılırken geçmiş arşivi Telegram'a dökme; yalnız bugünün raporu gönderilebilir.
        if first_for_type and published and published != today:
            type_state["seen_keys"] = list(dict.fromkeys([item["key"]] + type_state.get("seen_keys", [])))[:100]
            print(f"{source}/{report_type}: geçmiş araştırma referansı alındı")
            continue
        if first_for_type and not published:
            type_state["seen_keys"] = list(dict.fromkeys([item["key"]] + type_state.get("seen_keys", [])))[:100]
            print(f"{source}/{report_type}: tarihsiz başlangıç referansı alındı")
            continue

        try:
            sent = send_research_item(item)
        except Exception as exc:
            print(f"Araştırma gönderimi başarısız [{source}/{report_type}]: {exc}")
            sent = False
        if sent:
            type_state["seen_keys"] = list(dict.fromkeys([item["key"]] + type_state.get("seen_keys", [])))[:100]
            type_state["sent_at"] = datetime.now(ISTANBUL).isoformat()
            time.sleep(base.SEND_DELAY)

    base.save_state(state)


def install_official_sources():
    base.SOURCE_LABELS.update(OFFICIAL_LABELS)
    base.FETCHERS.update({
        "bist": fetch_bist,
        "tcmb": fetch_tcmb,
        "tuik": fetch_tuik,
        "spk": fetch_spk,
    })
    base.SOURCE_PRIORITY = [
        "kap", "bist", "tcmb", "tuik", "spk",
        "bloomberght", "forexfactory", "investing", "ntvpara", "trthaber", "tradingview",
    ]
    base.ENABLED_SOURCES = list(base.SOURCE_PRIORITY)


def main():
    # Önce v5 broker kaynaklarını kur; v4'ün tek bülten gönderimini devre dışı bırakıp v6 çok-tür araştırma merkezini kullan.
    v5.install_extensions()
    install_official_sources()

    original_v4_enrich = v4.enhanced_enrich

    def enrich_wrapper(item, session=requests):
        if item.get("source") in OFFICIAL_LABELS:
            return item
        return original_v4_enrich(item, session)

    v4.enhanced_enrich = enrich_wrapper
    v4.build_message = layered_build_message
    v4.BULLETIN_SOURCES = []

    # v4.main temiz KAP enrich mantığını ve temel haber akışını korur; bülten listesi boş olduğu için eski tek-tip gönderim çalışmaz.
    v4.main()
    send_research_reports()


if __name__ == "__main__":
    main()
