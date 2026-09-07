"""v7: Öncelikli haber kaynakları, provider-aware Matriks ve daha güçlü kaynak sıralaması."""

import re
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

import news_bot as base
import news_bot_v4 as v4
import news_bot_v5 as v5
import news_bot_v6 as v6


CNBCE_PAGES = (
    "https://www.cnbce.com/borsa",
    "https://www.cnbce.com/haberler",
)
AA_ECONOMY_RSS = "https://www.aa.com.tr/tr/teyithatti/rss/news?cat=ekonomi"
AA_ECONOMY_PAGE = "https://www.aa.com.tr/tr/ekonomi"
FORINVEST_NEWS = "https://www.foreks.com/haberler/"
REUTERS_MARKETS = "https://www.reuters.com/markets/"

NEW_LABELS = {
    "matriks": "Matriks (TradingView)",
    "forinvest": "ForInvest",
    "reuters": "Reuters",
    "cnbce": "CNBC-e",
    "aaekonomi": "Anadolu Ajansı Ekonomi",
}

NEW_LAYER_INFO = {
    "matriks": ("⚡", "BIST HIZLI", "Matriks"),
    "forinvest": ("⚡", "BIST HIZLI", "ForInvest"),
    "reuters": ("🌍", "GLOBAL PİYASA", "Reuters"),
    "cnbce": ("📰", "TÜRKİYE EKONOMİ", "CNBC-e"),
    "aaekonomi": ("📰", "TÜRKİYE EKONOMİ", "Anadolu Ajansı"),
}

FORINVEST_ARTICLE_RE = re.compile(r"/haber/detay/", re.IGNORECASE)
CNBCE_ARTICLE_RE = re.compile(r"-h\d+(?:$|[/?#])", re.IGNORECASE)
REUTERS_ARTICLE_RE = re.compile(
    r"/(?:markets|world|business|technology)/.+-20\d{2}-\d{2}-\d{2}/?$",
    re.IGNORECASE,
)
DATE_DOT_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.20\d{2}\b")
DATE_SHORT_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2}\s+\d{2}:\d{2}\b")
DATE_TR_RE = re.compile(
    r"\b\d{1,2}\s+(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|Haziran|Temmuz|"
    r"Ağustos|Agustos|Eylül|Eylul|Ekim|Kasım|Kasim|Aralık|Aralik)\s+20\d{2}(?:\s+\d{2}:\d{2})?\b",
    re.IGNORECASE,
)


def clean(value):
    return base.clean(value)


def _soup(url, session=requests):
    response = session.get(url, headers=base.headers(url), timeout=30)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def _context(anchor, max_chars=900):
    chunks = [clean(anchor.get_text(" ", strip=True))]
    node = getattr(anchor, "parent", None)
    for _ in range(3):
        if not node:
            break
        chunks.append(clean(node.get_text(" ", strip=True))[:max_chars])
        node = getattr(node, "parent", None)
    return clean(" ".join(chunks))


def _summary_from_anchor(anchor):
    node = getattr(anchor, "parent", None)
    for _ in range(3):
        if not node:
            break
        paragraph = node.find("p") if hasattr(node, "find") else None
        if paragraph:
            value = clean(paragraph.get_text(" ", strip=True))
            if len(value) >= 25:
                return value[:700]
        node = getattr(node, "parent", None)
    return ""


def _published_from_context(text):
    text = clean(text)
    for pattern in (DATE_TR_RE, DATE_DOT_RE, DATE_SHORT_RE):
        match = pattern.search(text)
        if match:
            return match.group(0)
    return ""


def fetch_matriks(session=requests):
    found = []
    for item in base.fetch_tradingview(session):
        provider = clean(item.get("provider"))
        if "matriks" not in provider.lower():
            continue
        cloned = dict(item)
        cloned["source"] = "matriks"
        cloned["provider"] = "Matriks · TradingView"
        found.append(cloned)
        if len(found) >= base.NEWS_LIMIT:
            break
    return base.dedupe(found)


def fetch_cnbce(session=requests):
    found, seen = [], set()
    for page_url in CNBCE_PAGES:
        soup = _soup(page_url, session)
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, clean(anchor.get("href")))
            parsed = urlparse(href)
            if "cnbce.com" not in parsed.netloc.lower() or not CNBCE_ARTICLE_RE.search(parsed.path):
                continue
            title = clean(anchor.get_text(" ", strip=True))
            if len(title) < 18 or href in seen:
                continue
            context = _context(anchor)
            seen.add(href)
            found.append(base.blank_item(
                "cnbce", title, href, id=href, provider="CNBC-e",
                published=_published_from_context(context),
                summary=_summary_from_anchor(anchor), category="Türkiye Ekonomi/Piyasa",
            ))
            if len(found) >= base.NEWS_LIMIT:
                return base.dedupe(found)
    return base.dedupe(found)


def _fetch_aa_rss(session=requests):
    response = session.get(
        AA_ECONOMY_RSS,
        headers=base.headers(AA_ECONOMY_PAGE) | {"Accept": "application/rss+xml,application/xml,text/xml"},
        timeout=30,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    found = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() not in {"item", "entry"}:
            continue
        title = base.xml_child_text(node, "title")
        link = base.xml_child_link(node)
        if not title or not link:
            continue
        raw_summary = base.xml_child_text(node, "description", "summary", "content")
        summary = clean(BeautifulSoup(raw_summary, "html.parser").get_text(" ", strip=True))
        found.append(base.blank_item(
            "aaekonomi", title, link,
            id=base.xml_child_text(node, "guid", "id") or link,
            provider="Anadolu Ajansı", published=base.xml_child_text(node, "pubDate", "published", "updated"),
            summary=summary, category="Ekonomi",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break
    return base.dedupe(found)


def _fetch_aa_html(session=requests):
    soup = _soup(AA_ECONOMY_PAGE, session)
    found, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(AA_ECONOMY_PAGE, clean(anchor.get("href")))
        parsed = urlparse(href)
        if "aa.com.tr" not in parsed.netloc.lower() or "/tr/ekonomi/" not in parsed.path:
            continue
        title = clean(anchor.get_text(" ", strip=True))
        if len(title) < 20 or href in seen:
            continue
        context = _context(anchor)
        seen.add(href)
        found.append(base.blank_item(
            "aaekonomi", title, href, id=href, provider="Anadolu Ajansı",
            published=_published_from_context(context), summary=_summary_from_anchor(anchor), category="Ekonomi",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break
    return base.dedupe(found)


def fetch_aaekonomi(session=requests):
    try:
        items = _fetch_aa_rss(session)
        if items:
            return items
    except Exception as exc:
        print(f"AA Ekonomi RSS okunamadı, HTML yedeğine geçiliyor: {exc}")
    return _fetch_aa_html(session)


def fetch_forinvest(session=requests):
    soup = _soup(FORINVEST_NEWS, session)
    found, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(FORINVEST_NEWS, clean(anchor.get("href")))
        if not FORINVEST_ARTICLE_RE.search(urlparse(href).path):
            continue
        title = clean(anchor.get_text(" ", strip=True))
        if len(title) < 18 or href in seen:
            continue
        context = _context(anchor)
        seen.add(href)
        found.append(base.blank_item(
            "forinvest", title, href, id=href, provider="ForInvest",
            published=_published_from_context(context), summary=_summary_from_anchor(anchor),
            category="Piyasa Haberleri",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break
    return base.dedupe(found)


def fetch_reuters(session=requests):
    soup = _soup(REUTERS_MARKETS, session)
    found, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(REUTERS_MARKETS, clean(anchor.get("href")))
        parsed = urlparse(href)
        if "reuters.com" not in parsed.netloc.lower() or not REUTERS_ARTICLE_RE.search(parsed.path):
            continue
        title = clean(anchor.get_text(" ", strip=True))
        if len(title) < 24 or href in seen:
            continue
        context = _context(anchor)
        time_node = anchor.find_parent().find("time") if anchor.find_parent() else None
        published = clean(time_node.get("datetime")) if time_node and time_node.get("datetime") else _published_from_context(context)
        summary = _summary_from_anchor(anchor)
        seen.add(href)
        found.append(base.blank_item(
            "reuters", title, href, id=href, provider="Reuters",
            published=published, summary=summary, category="Global Markets",
        ))
        if len(found) >= base.NEWS_LIMIT:
            break
    return base.dedupe(found)


def install_news_sources():
    base.SOURCE_LABELS.update(NEW_LABELS)
    base.FETCHERS.update({
        "matriks": fetch_matriks,
        "forinvest": fetch_forinvest,
        "reuters": fetch_reuters,
        "cnbce": fetch_cnbce,
        "aaekonomi": fetch_aaekonomi,
    })
    v6.LAYER_INFO.update(NEW_LAYER_INFO)

    # Kaynak önceliği: resmi > BIST hızlı > Reuters > güçlü yerli haber > genel haber > TradingView.
    base.SOURCE_PRIORITY = [
        "kap", "bist", "tcmb", "tuik", "spk",
        "matriks", "forinvest", "reuters",
        "bloomberght", "cnbce", "aaekonomi",
        "forexfactory", "investing", "ntvpara", "trthaber", "tradingview",
    ]
    base.ENABLED_SOURCES = list(base.SOURCE_PRIORITY)


def main():
    # v6'nın resmi kaynakları, KAP akıllı özeti ve araştırma merkezini koru.
    v5.install_extensions()
    v6.install_official_sources()
    install_news_sources()

    original_kap_enrich = v4.enhanced_enrich

    def enrich_wrapper(item, session=requests):
        # TradingView API'den gelen Matriks kaydı zaten kısa özet içerir; paywall sayfasını tekrar kazıma.
        if item.get("source") == "matriks":
            return item
        if item.get("source") in v6.OFFICIAL_LABELS:
            return item
        return original_kap_enrich(item, session)

    v4.enhanced_enrich = enrich_wrapper
    v4.build_message = v6.layered_build_message
    v4.BULLETIN_SOURCES = []

    v4.main()
    v6.send_research_reports()


if __name__ == "__main__":
    main()
