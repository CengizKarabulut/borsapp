"""v9: kaynak sağlığı, daha kısa çalışma süresi ve sessiz/hızlı araştırma taraması.

v8'in tarih + semantik tekrar filtresini korur ve şu operasyonel sorunları düzeltir:
- TCMB RSS için BeautifulSoup XML parser bağımlılığını kaldırır (stdlib ElementTree).
- GitHub runner'da 401 döndüren Reuters'ı varsayılan akıştan çıkarır; istenirse env ile açılır.
- Şeker Yatırım ve İş Yatırım'ın güncel araştırma URL'lerini kullanır.
- BULLETIN_SOURCES listesini araştırma taramasında gerçekten bağlayıcı yapar.
- Eski arşiv adaylarını tek tek loglamak yerine özetler ve taranacak anchor sayısını sınırlar.
"""

import os
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import news_bot as base
import news_bot_v4 as v4
import news_bot_v5 as v5
import news_bot_v6 as v6
import news_bot_v7 as v7
import news_bot_v8 as v8


ISTANBUL = ZoneInfo("Europe/Istanbul")
RESEARCH_SCAN_MAX_ANCHORS = max(50, int(os.getenv("RESEARCH_SCAN_MAX_ANCHORS", "500")))
RESEARCH_HTTP_TIMEOUT = max(5, int(os.getenv("RESEARCH_HTTP_TIMEOUT", "18")))
ENABLE_REUTERS = os.getenv("ENABLE_REUTERS", "").lower() in {"1", "true", "yes"}

# Canlı GitHub runner gözleminde 403/404/SSL/timeout veren kaynaklar varsayılan listeden çıkarıldı.
# Kullanıcı BULLETIN_SOURCES ile açıkça eklerse yine denenebilirler.
DEFAULT_HEALTHY_RESEARCH_SOURCES = (
    "tera,a1capital,bulls,yapikredi,akyatirim,ziraat,qnb,garanti,midas,"
    "phillipcapital,gedik,oyak,seker,isyatirim,vakif,deniz"
)

# Güncel resmî sayfalar (Eylül 2026 kontrolü).
KNOWN_RESEARCH_URLS = {
    "seker": "https://www.sekeryatirim.com.tr/Arastirma/Raporlar",
    "isyatirim": "https://www.isyatirim.com.tr/tr-tr/analiz/arastirma-raporlari/Sayfalar/default.aspx",
}


def clean(value):
    return base.clean(value)


def configured_research_sources(raw=None):
    raw = raw if raw is not None else os.getenv("BULLETIN_SOURCES", DEFAULT_HEALTHY_RESEARCH_SOURCES)
    requested = []
    for value in str(raw or "").split(","):
        source = value.strip().lower()
        if source and source in v6.RESEARCH_PAGE_CONFIGS and source not in requested:
            requested.append(source)
    return requested


def filter_news_sources(sources, enable_reuters=None):
    enabled = ENABLE_REUTERS if enable_reuters is None else bool(enable_reuters)
    return [source for source in sources if enabled or source != "reuters"]


def apply_known_url_fixes():
    for source, url in KNOWN_RESEARCH_URLS.items():
        if source in v5.BROKER_CONFIGS:
            v5.BROKER_CONFIGS[source]["url"] = url
        if source in v6.RESEARCH_PAGE_CONFIGS:
            v6.RESEARCH_PAGE_CONFIGS[source]["url"] = url


def fetch_tcmb(session=requests):
    """TCMB RSS'i haricî XML parser gerektirmeden oku."""
    response = session.get(
        v6.TCMB_PRESS_RSS,
        headers=base.headers(v6.TCMB_PRESS_RSS) | {"Accept": "application/rss+xml,application/xml,text/xml"},
        timeout=30,
    )
    response.raise_for_status()
    found = []

    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError:
        root = None

    if root is not None:
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1].lower() not in {"item", "entry"}:
                continue
            title = base.xml_child_text(node, "title")
            link = base.xml_child_link(node)
            published = base.xml_child_text(node, "pubDate", "published", "updated")
            if not title or not link:
                continue
            found.append(base.blank_item(
                "tcmb",
                title,
                urljoin("https://www.tcmb.gov.tr", link),
                id=link,
                provider="TCMB",
                published=published,
                summary="Türkiye Cumhuriyet Merkez Bankası resmî duyurusu",
                category="Basın Duyurusu",
            ))
            if len(found) >= base.NEWS_LIMIT:
                break
        if found:
            return base.dedupe(found)

    # TCMB bazı istemcilere RSS benzeri düz metin döndürdüğünde son yedek.
    text = getattr(response, "text", "") or response.content.decode("utf-8", errors="ignore")
    pattern = re.compile(
        r"<!\[CDATA\[(?P<title>.*?)\]\]>\s*(?P<link>/wps/wcm/connect/TR/TCMB\+TR/[^\s<]+)\s*"
        r"(?P<date>\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+20\d{2}\s+\d{2}:\d{2}:\d{2})",
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        link = urljoin("https://www.tcmb.gov.tr", match.group("link"))
        found.append(base.blank_item(
            "tcmb",
            clean(match.group("title")),
            link,
            id=link,
            provider="TCMB",
            published=clean(match.group("date")),
            summary="Türkiye Cumhuriyet Merkez Bankası resmî duyurusu",
            category="Basın Duyurusu",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break
    return base.dedupe(found)


def _research_soup(url, session=requests):
    response = session.get(url, headers=base.headers(url), timeout=RESEARCH_HTTP_TIMEOUT)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def scan_research_page(source, config, session=requests):
    """v8 kurallarını koruyup eski adayları sessizce eleyen sınırlı tarama."""
    try:
        soup = _research_soup(config["url"], session)
    except Exception as exc:
        print(f"{config['label']} araştırma sayfası erişilemedi; bu tur atlandı: {exc}")
        return []

    found = []
    seen_urls = set()
    rejected = {}
    scanned = 0

    for anchor in soup.find_all("a", href=True):
        scanned += 1
        if scanned > RESEARCH_SCAN_MAX_ANCHORS:
            break

        raw_href = clean(anchor.get("href"))
        if not raw_href:
            continue
        href = urljoin(config["url"], raw_href)
        if href in seen_urls or v8._is_blocked_url(href) or v8._inside_navigation(anchor):
            continue
        if not v5.same_public_site(config["url"], href):
            continue

        context = v8._local_anchor_context(anchor)
        report_type, report_label = v8._report_type_from_evidence(context, href)
        if not report_type:
            continue

        direct_text = clean(
            f"{anchor.get_text(' ', strip=True)} {anchor.get('title')} "
            f"{anchor.get('aria-label')} {urlparse(href).path}"
        )
        direct_type, _ = v8._report_type_from_evidence(direct_text, href)
        is_pdf = urlparse(href).path.lower().endswith(".pdf")
        if not direct_type and not (is_pdf and len(context) <= 350):
            continue

        date_candidates = v8.extract_dates(direct_text) or v8.extract_dates(context)
        if not date_candidates:
            rejected["missing_date"] = rejected.get("missing_date", 0) + 1
            continue

        title = clean(anchor.get_text(" ", strip=True))
        if v8._ascii(title) in v8.GENERIC_TITLES:
            title = report_label.title()

        delivery = "pdf" if is_pdf and config.get("delivery") != "link" else "link"
        item = {
            "source": source,
            "title": title or report_label.title(),
            "page_url": config["url"] if delivery == "pdf" else href,
            "document_url": href if delivery == "pdf" else "",
            "date_text": date_candidates[0].strftime("%d.%m.%Y"),
            "published_date": date_candidates[0].isoformat(),
            "render_html": False,
            "delivery": delivery,
            "report_type": report_type,
            "report_label": report_label,
        }
        normalized, reason = v8.normalize_candidate(item)
        if normalized:
            seen_urls.add(href)
            found.append(normalized)
        else:
            rejected[reason] = rejected.get(reason, 0) + 1

        if len(found) >= 20:
            break

    if rejected:
        summary = ", ".join(f"{key}={value}" for key, value in sorted(rejected.items()))
        print(f"{source}: {scanned} bağlantı tarandı; gönderilmeyen araştırmalar: {summary}")
    return found


def specialized_daily_items(sources):
    """Yalnız seçili kurumların özel fetcher'larını çağır."""
    items = []
    for source in sources:
        fetcher = v4.BULLETIN_FETCHERS.get(source)
        config = v6.RESEARCH_PAGE_CONFIGS.get(source)
        if not fetcher or not config:
            continue
        try:
            item = fetcher()
        except Exception as exc:
            print(f"{config['label']} güncel bülteni erişilemedi; bu tur atlandı: {exc}")
            continue
        if not item:
            continue
        key, _, label = v6.classify_report_type(f"{item.get('title', '')} {item.get('date_text', '')}")
        if key == "arastirma":
            key, label = "gunluk_bulten", "GÜNLÜK BÜLTEN"
        item["report_type"] = key
        item["report_label"] = label
        item["delivery"] = item.get("delivery") or ("pdf" if item.get("document_url") else "link")
        items.append(item)
    return items


def send_research_reports():
    state = base.load_state()
    research_state = state.setdefault(v8.RESEARCH_STATE_KEY, {})
    today = datetime.now(ISTANBUL).date()
    sources = configured_research_sources()
    raw_candidates = []

    print(f"Araştırma kaynakları ({len(sources)}): {', '.join(sources)}")

    for item in specialized_daily_items(sources):
        normalized, reason = v8.normalize_candidate(item, today=today)
        if normalized:
            raw_candidates.append(normalized)
        elif reason not in {"stale_date", "missing_date"}:
            print(f"{item.get('source', '?')}/{item.get('report_type', '?')}: özel aday atlandı ({reason})")

    for source in sources:
        config = v6.RESEARCH_PAGE_CONFIGS[source]
        raw_candidates.extend(scan_research_page(source, config))

    candidates = v8._dedupe_candidates(raw_candidates)
    sent_count = 0

    for item in candidates:
        source = item["source"]
        report_type = item["report_type"]
        source_state = research_state.setdefault(source, {})
        type_state = source_state.setdefault(
            report_type,
            {"seen_keys": [], "seen_semantic_keys": [], "rejected_keys": []},
        )
        seen_keys = set(type_state.get("seen_keys", []))
        seen_semantic = set(type_state.get("seen_semantic_keys", []))

        if item["key"] in seen_keys or item["semantic_key"] in seen_semantic:
            continue

        if v8._legacy_seen_for_today(state, item):
            type_state["seen_keys"] = list(dict.fromkeys([item["key"]] + type_state.get("seen_keys", [])))[:300]
            type_state["seen_semantic_keys"] = list(
                dict.fromkeys([item["semantic_key"]] + type_state.get("seen_semantic_keys", []))
            )[:300]
            continue

        try:
            sent = v6.send_research_item(item)
        except Exception as exc:
            print(f"Araştırma gönderimi başarısız [{source}/{report_type}]: {exc}")
            sent = False
        if not sent:
            continue

        type_state["seen_keys"] = list(dict.fromkeys([item["key"]] + type_state.get("seen_keys", [])))[:300]
        type_state["seen_semantic_keys"] = list(
            dict.fromkeys([item["semantic_key"]] + type_state.get("seen_semantic_keys", []))
        )[:300]
        type_state["last_published_date"] = item["published_date"]
        type_state["sent_at"] = datetime.now(ISTANBUL).isoformat()
        sent_count += 1
        if base.SEND_DELAY:
            import time
            time.sleep(base.SEND_DELAY)

    print(f"Araştırma taraması tamamlandı: {len(candidates)} güncel benzersiz aday, {sent_count} yeni gönderim")
    base.save_state(state)


def _install_news_sources_reliable():
    v7.ORIGINAL_INSTALL_NEWS_SOURCES()
    base.ENABLED_SOURCES = filter_news_sources(base.ENABLED_SOURCES)
    if not ENABLE_REUTERS:
        print("Reuters: GitHub runner erişimi 401 verdiği için varsayılan akışta devre dışı")


def install_runtime_fixes():
    apply_known_url_fixes()

    # v7.main çağrıldığında v6.install_official_sources güncel fonksiyonu base.FETCHERS'a yazar.
    v6.fetch_tcmb = fetch_tcmb

    if not hasattr(v7, "ORIGINAL_INSTALL_NEWS_SOURCES"):
        v7.ORIGINAL_INSTALL_NEWS_SOURCES = v7.install_news_sources
    v7.install_news_sources = _install_news_sources_reliable

    # v8.main, bu fonksiyonu v6.send_research_reports'a bağlayacak.
    v8.send_research_reports = send_research_reports


def main():
    install_runtime_fixes()
    v8.main()


if __name__ == "__main__":
    main()
