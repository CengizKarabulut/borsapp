"""KAP, ekonomi haberleri ve forex takvim olaylarını Telegram'a gönderir."""

import html
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup


TV_BASE = "https://tr.tradingview.com"
TV_API = "https://news-mediator.tradingview.com/public/news-flow/v2/news"
BHT_BASE = "https://www.bloomberght.com"
BHT_LIST = f"{BHT_BASE}/tumhaberler"
KAP_BASE = "https://www.kap.org.tr"
KAP_API = f"{KAP_BASE}/tr/api/disclosure/members/byCriteria"
FOREX_FACTORY_CALENDAR = "https://www.forexfactory.com/calendar"
FOREX_FACTORY_API = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FOREX_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "TRY", "CHF", "CAD", "AUD", "NZD"}
FOREX_ALERT_MINUTES = int(os.getenv("FOREX_ALERT_MINUTES", "75"))
SOURCE_LABELS = {
    "kap": "KAP",
    "bloomberght": "Bloomberg HT",
    "forexfactory": "Forex Factory Takvimi",
    "investing": "Investing.com Türkiye",
    "ntvpara": "NTV Para",
    "trthaber": "TRT Haber Ekonomi",
    "tradingview": "TradingView",
}
SOURCE_PRIORITY = [
    "kap", "bloomberght", "forexfactory", "investing", "ntvpara", "trthaber", "tradingview"
]
RSS_FEEDS = {
    "investing": [
        "https://tr.investing.com/rss/news.rss",
        "https://tr.investing.com/rss/forex.rss",
        "https://tr.investing.com/rss/stock.rss",
    ],
    "ntvpara": ["https://www.ntv.com.tr/ntvpara.rss"],
    "trthaber": ["https://www.trthaber.com/ekonomi_articles.rss"],
}
SOURCE_VERSION = "multi-source-v3"

CACHE_FILE = os.getenv("CACHE_FILE", "news_cache.json")
NEWS_LIMIT = int(os.getenv("NEWS_LIMIT", "100"))
PER_RUN_SEND_LIMIT = int(os.getenv("PER_RUN_SEND_LIMIT", "30"))
DETAIL_MAX_CHARS = int(os.getenv("DETAIL_MAX_CHARS", "1800"))
SEND_DELAY = float(os.getenv("TELEGRAM_SEND_DELAY", "4"))
MAX_ATTEMPTS = int(os.getenv("MAX_TELEGRAM_ATTEMPTS", "5"))
DRY_RUN = os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"}
_requested_sources = {
    value.strip().lower()
    for value in os.getenv(
        "NEWS_SOURCES", "kap,bloomberght,forexfactory,investing,ntvpara,trthaber,tradingview"
    ).split(",")
}
# Ortam değişkenindeki sıra ne olursa olsun güvenilir kaynak önceliğini koru.
ENABLED_SOURCES = [source for source in SOURCE_PRIORITY if source in _requested_sources]


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_url(value):
    parsed = urlparse(value or "")
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", ""))


def item_key(item):
    identity = clean(item.get("id")) or canonical_url(item.get("link")) or clean(item.get("title")).lower()
    return f"{item['source']}:{identity}"


def dedupe(items):
    result, seen = [], set()
    for item in items:
        key = item_key(item)
        title_key = f"{item['source']}:title:{clean(item.get('title')).lower()}"
        if not key or key in seen or title_key in seen:
            continue
        seen.update((key, title_key))
        result.append(item)
    return result


def normalized_story_text(item):
    value = f"{clean(item.get('title'))} {clean(item.get('summary'))[:240]}".lower()
    value = "".join(
        character for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    stopwords = {"ve", "ile", "icin", "bir", "bu", "da", "de", "mi", "ne", "son", "dakika"}
    return " ".join(word for word in value.split() if word not in stopwords)


def is_cross_source_duplicate(item, fingerprints):
    candidate = normalized_story_text(item)
    if not candidate:
        return False
    candidate_tokens = set(candidate.split())
    for previous in fingerprints:
        if isinstance(previous, dict) and previous.get("source") == item.get("source"):
            continue
        previous_text = previous.get("text", "") if isinstance(previous, dict) else clean(previous)
        if not previous_text:
            continue
        if candidate == previous_text or SequenceMatcher(None, candidate, previous_text).ratio() >= 0.84:
            return True
        previous_tokens = set(previous_text.split())
        union = candidate_tokens | previous_tokens
        if len(candidate_tokens) >= 4 and len(previous_tokens) >= 4 and union:
            if len(candidate_tokens & previous_tokens) / len(union) >= 0.68:
                return True
    return False


def remember_story(item, fingerprints):
    fingerprints.insert(0, {
        "source": item["source"],
        "text": normalized_story_text(item),
        "link": canonical_url(item.get("link")),
    })
    del fingerprints[1500:]


def headers(referer=None, json_response=False):
    result = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept": "application/json" if json_response else "text/html,application/xhtml+xml",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
    }
    if referer:
        result["Referer"] = referer
    return result


def blank_item(source, title, link, **values):
    item = {
        "source": source, "id": "", "title": clean(title), "link": link,
        "provider": SOURCE_LABELS[source], "published": "", "summary": "",
        "detail": "", "image": "",
    }
    item.update(values)
    return item


def fetch_kap(session=requests):
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    payload = {
        "fromDate": (now - timedelta(days=1)).date().isoformat(),
        "toDate": now.date().isoformat(),
        "disclosureClass": "", "subjectList": [], "mkkMemberOidList": [],
        "inactiveMkkMemberOidList": [], "bdkMemberOidList": [],
        "fromSrc": False, "disclosureIndexList": [],
    }
    request_headers = headers(f"{KAP_BASE}/tr/bildirim-sorgu", True)
    request_headers.update({"Content-Type": "application/json", "Origin": KAP_BASE})
    response = session.post(KAP_API, json=payload, headers=request_headers, timeout=30)
    response.raise_for_status()
    rows = response.json()
    found = []
    for row in rows if isinstance(rows, list) else []:
        disclosure_id = clean(row.get("disclosureIndex"))
        if not disclosure_id:
            continue
        company = clean(row.get("kapTitle"))
        ticker = clean(row.get("stockCodes") or row.get("relatedStocks") or row.get("fundCode"))
        subject = clean(row.get("subject") or row.get("summary") or "KAP Bildirimi")
        title = f"{ticker} — {subject}" if ticker else subject
        summary_parts = [clean(row.get("summary"))]
        if company:
            summary_parts.append(f"Şirket: {company}")
        found.append(blank_item(
            "kap", title, f"{KAP_BASE}/tr/Bildirim/{disclosure_id}",
            id=disclosure_id, provider=company or "KAP", published=row.get("publishDate"),
            summary=" · ".join(part for part in summary_parts if part),
            category=clean(row.get("disclosureClass")), attachment_count=row.get("attachmentCount", 0),
        ))
        if len(found) >= NEWS_LIMIT:
            break
    return dedupe(found)


def parse_iso_datetime(value):
    try:
        parsed = datetime.fromisoformat(clean(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("UTC"))
    except (TypeError, ValueError):
        return None


def fetch_forex_factory(session=requests, now=None):
    now = now or datetime.now(ZoneInfo("Europe/Istanbul"))
    rows = None
    for attempt in range(3):
        response = session.get(
            FOREX_FACTORY_API,
            headers=headers(FOREX_FACTORY_CALENDAR, True),
            timeout=25,
        )
        if getattr(response, "status_code", 200) == 429 and attempt < 2:
            retry_after = clean(getattr(response, "headers", {}).get("Retry-After"))
            delay = min(int(retry_after), 20) if retry_after.isdigit() else 5 * (attempt + 1)
            print(f"Forex Factory hız sınırı; {delay} saniye sonra yeniden denenecek")
            time.sleep(delay)
            continue
        response.raise_for_status()
        rows = response.json()
        break
    if rows is None:
        return []
    found = []
    for row in rows if isinstance(rows, list) else []:
        currency = clean(row.get("country")).upper()
        event_name = clean(row.get("title"))
        event_time = parse_iso_datetime(row.get("date"))
        impact = clean(row.get("impact")).lower()
        if currency not in FOREX_CURRENCIES or not event_name or not event_time or impact != "high":
            continue
        minutes = (event_time.astimezone(ZoneInfo("UTC")) - now.astimezone(ZoneInfo("UTC"))).total_seconds() / 60
        actual = clean(row.get("actual"))
        if 0 <= minutes <= FOREX_ALERT_MINUTES:
            phase = "upcoming"
            provider = "Yaklaşan yüksek etkili olay"
            timing = f"Yaklaşık {max(1, round(minutes))} dakika sonra"
        elif -30 <= minutes < 0 and actual:
            phase = "released"
            provider = "Yüksek etkili veri açıklandı"
            timing = "Yeni açıklandı"
        else:
            continue
        values = [timing, "Etki: Yüksek"]
        for label, value in (
            ("Açıklanan", actual),
            ("Beklenti", clean(row.get("forecast"))),
            ("Önceki", clean(row.get("previous"))),
        ):
            if value:
                values.append(f"{label}: {value}")
        event_id = f"{phase}:{currency}:{event_time.isoformat()}:{event_name.lower()}"
        found.append(blank_item(
            "forexfactory",
            f"{currency} — {event_name}",
            FOREX_FACTORY_CALENDAR,
            id=event_id,
            provider=provider,
            published=event_time.isoformat(),
            summary=" · ".join(values),
            category="Ekonomik Takvim",
        ))
    return dedupe(sorted(found, key=lambda item: item["published"]))


def fetch_bloomberght(session=requests):
    response = session.get(BHT_LIST, headers=headers(BHT_BASE), timeout=25)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup, found = BeautifulSoup(response.text, "html.parser"), []
    for card in soup.select('main [data-type^="news-card"]'):
        anchor = card.select_one("a[href][title]") or card.select_one("a[href]")
        if not anchor:
            continue
        path, title = clean(anchor.get("href")), clean(anchor.get("title"))
        if not path or not title or path.startswith("/sondakika"):
            continue
        paragraph = card.select_one("p")
        image = next((clean(node.get("data-src") or node.get("src")) for node in card.select("img")
                      if "transparent.gif" not in clean(node.get("data-src") or node.get("src"))), "")
        found.append(blank_item(
            "bloomberght", title, urljoin(BHT_BASE, path),
            summary=clean(paragraph.get_text(" ", strip=True) if paragraph else ""),
            image=urljoin(BHT_BASE, image) if image else "",
        ))
        if len(found) >= NEWS_LIMIT:
            break
    return dedupe(found)


def fetch_tradingview(session=requests):
    request_headers = headers(f"{TV_BASE}/news-flow/", True)
    request_headers["Origin"] = TV_BASE
    response = session.get(
        TV_API,
        params={"filter": "lang:tr", "client": "screener", "user_prostatus": "free"},
        headers=request_headers,
        timeout=20,
    )
    response.raise_for_status()
    found = []
    for row in response.json().get("items", []):
        title = clean(row.get("title"))
        path = clean(row.get("storyPath") or row.get("story_path") or row.get("url"))
        if not title or not path:
            continue
        provider = row.get("provider") or {}
        provider = clean(provider.get("name") or provider.get("id")) if isinstance(provider, dict) else clean(provider)
        found.append(blank_item(
            "tradingview", title, path if path.startswith("http") else urljoin(TV_BASE, path),
            id=clean(row.get("id")), provider=provider or "TradingView", published=row.get("published"),
            summary=clean(row.get("description") or row.get("summary")),
        ))
        if len(found) >= NEWS_LIMIT:
            break
    return dedupe(found)


def xml_child_text(node, *names):
    wanted = {name.lower() for name in names}
    for child in node:
        if child.tag.rsplit("}", 1)[-1].lower() in wanted:
            return clean("".join(child.itertext()))
    return ""


def xml_child_link(node):
    for child in node:
        if child.tag.rsplit("}", 1)[-1].lower() == "link":
            link = clean(child.get("href") or "".join(child.itertext()))
            if link and child.get("rel", "alternate") in {"alternate", ""}:
                return link
    return ""


def fetch_rss_source(source, session=requests):
    found = []
    for feed_url in RSS_FEEDS[source]:
        root = None
        for attempt in range(2):
            try:
                response = session.get(
                    feed_url,
                    headers=headers(feed_url) | {"Accept": "application/rss+xml,application/xml,text/xml"},
                    timeout=25,
                )
                response.raise_for_status()
                root = ElementTree.fromstring(response.content)
                break
            except (requests.RequestException, ElementTree.ParseError) as exc:
                if attempt == 1:
                    print(f"RSS alt akışı atlandı [{SOURCE_LABELS[source]}]: {feed_url} ({exc})")
        if root is None:
            continue
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1].lower() not in {"item", "entry"}:
                continue
            title = xml_child_text(node, "title")
            link = xml_child_link(node)
            if not title or not link:
                continue
            raw_summary = xml_child_text(node, "description", "summary", "content", "subtitle")
            summary = clean(BeautifulSoup(raw_summary, "html.parser").get_text(" ", strip=True))
            image = ""
            for child in node:
                local_name = child.tag.rsplit("}", 1)[-1].lower()
                image_url = child.get("url") or (
                    child.get("href") if child.get("rel") == "enclosure" else ""
                )
                if local_name in {"enclosure", "content", "thumbnail", "link"} and image_url:
                    image = clean(image_url)
                    break
            found.append(blank_item(
                source, title, link,
                id=xml_child_text(node, "guid", "id") or link,
                published=xml_child_text(node, "pubDate", "published", "updated"),
                summary=summary,
                image=image,
            ))
            if len(found) >= NEWS_LIMIT:
                break
        if len(found) >= NEWS_LIMIT:
            break
    return dedupe(found)


def meta(soup, *selectors):
    for selector in selectors:
        node = soup.select_one(selector)
        if node and clean(node.get("content")):
            return clean(node.get("content"))
    return ""


def enrich(item, session=requests):
    if item["source"] in {"tradingview", "forexfactory"}:
        return item
    response = session.get(item["link"], headers=headers(), timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    if item["source"] == "bloomberght":
        item["summary"] = meta(soup, 'meta[property="og:description"]', 'meta[name="description"]') or item["summary"]
        item["image"] = meta(soup, 'meta[property="og:image"]', 'meta[name="twitter:image"]') or item["image"]
        paragraphs = [clean(node.get_text(" ", strip=True)) for node in soup.select("article.news-content .article-wrapper p")]
        item["detail"] = "\n\n".join(dict.fromkeys(value for value in paragraphs if value))[:DETAIL_MAX_CHARS]
        article = soup.select_one("article.news-content")
        match = re.search(r"\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+\d{4},\s+\d{2}:\d{2}", clean(article.get_text(" ", strip=True)) if article else "")
        if match:
            item["published"] = match.group(0)
    elif item["source"] == "kap":
        content = soup.select_one(".disclosureScrollableArea")
        if content:
            item["detail"] = clean(content.get_text(" ", strip=True))[:DETAIL_MAX_CHARS]
    else:
        item["summary"] = meta(
            soup, 'meta[property="og:description"]', 'meta[name="description"]'
        ) or item["summary"]
        item["image"] = meta(
            soup, 'meta[property="og:image"]', 'meta[name="twitter:image"]'
        ) or item["image"]
        paragraphs = [
            clean(node.get_text(" ", strip=True))
            for node in soup.select("article p, main article p")
        ]
        paragraphs = list(dict.fromkeys(value for value in paragraphs if len(value) >= 40))
        item["detail"] = "\n\n".join(paragraphs)[:DETAIL_MAX_CHARS]
    return item


FETCHERS = {
    "kap": fetch_kap,
    "bloomberght": fetch_bloomberght,
    "forexfactory": fetch_forex_factory,
    "investing": lambda session=requests: fetch_rss_source("investing", session),
    "ntvpara": lambda session=requests: fetch_rss_source("ntvpara", session),
    "trthaber": lambda session=requests: fetch_rss_source("trthaber", session),
    "tradingview": fetch_tradingview,
}


def load_state():
    empty = {"source_version": SOURCE_VERSION, "sources": {}, "fingerprints": []}
    try:
        with open(CACHE_FILE, encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) and isinstance(data.get("sources"), dict) else empty
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return empty


def save_state(state):
    state["source_version"] = SOURCE_VERSION
    with open(CACHE_FILE, "w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)


def select_new(items, source_state):
    keys = [item_key(item) for item in items]
    previous = source_state.get("last_seen_key", "")
    seen = set(source_state.get("seen_keys", []))
    if not previous:
        return [], keys
    if previous in keys:
        cutoff = keys.index(previous)
    else:
        matches = [index for index, key in enumerate(keys) if key in seen]
        if not matches:
            return [], keys
        cutoff = min(matches)
    return [item for item in reversed(items[:cutoff]) if item_key(item) not in seen], keys


def format_date(value):
    if isinstance(value, (int, float)):
        value = value / 1000 if value > 10_000_000_000 else value
        return time.strftime("%d.%m.%Y %H:%M", time.localtime(value))
    parsed = parse_iso_datetime(value)
    if parsed:
        return parsed.astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")
    return clean(value).replace("T", " ").replace("Z", " UTC")


def build_message(item):
    label = SOURCE_LABELS[item["source"]]
    provider = clean(item.get("provider"))
    source_line = label if not provider or provider.lower() == label.lower() else f"{label} · {provider}"
    if format_date(item.get("published")):
        source_line += f" · {format_date(item['published'])}"
    detail, summary = clean(item.get("detail")), clean(item.get("summary"))
    if detail and summary and detail.lower().startswith(summary.lower()):
        detail = detail[len(summary):].strip(" .")
    parts = [f"<b>{html.escape(item['title'])}</b>", f"<i>{html.escape(source_line)}</i>"]
    parts += [html.escape(value) for value in (summary, detail) if value]
    if item.get("attachment_count"):
        parts.append(f"📎 {int(item['attachment_count'])} ek")
    parts.append(f'<a href="{html.escape(item["link"], quote=True)}">Kaynakta ayrıntıyı aç</a>')
    message = "\n\n".join(parts)
    if len(message) <= 3900:
        return message
    fixed = "\n\n".join(parts[:2] + [parts[-1]])
    body = "\n\n".join(parts[2:-1])
    return "\n\n".join(parts[:2] + [body[:3900 - len(fixed) - 6].rstrip() + "…", parts[-1]])


def send_message(text):
    if DRY_RUN:
        print(f"DRY_RUN ({len(text)} karakter):\n{text}\n")
        return True
    token, chat_id = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_TOKEN veya TELEGRAM_CHAT_ID eksik")
    payload = {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": False, "prefer_large_media": True},
    }
    if os.getenv("TELEGRAM_MESSAGE_THREAD_ID"):
        payload["message_thread_id"] = int(os.environ["TELEGRAM_MESSAGE_THREAD_ID"])
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=20)
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
            print(f"Telegram deneme {attempt} başarısız: {exc}")
            time.sleep(min(60, attempt * 5))
    return False


def main():
    state, remaining = load_state(), PER_RUN_SEND_LIMIT
    fingerprints = state.setdefault("fingerprints", [])
    for source in ENABLED_SOURCES:
        try:
            items = FETCHERS[source]()
            print(f"{SOURCE_LABELS[source]}: {len(items)} haber bulundu")
        except Exception as exc:
            print(f"{SOURCE_LABELS[source]} okunamadı; cache korunuyor: {exc}")
            continue
        if not items:
            continue
        source_state = state["sources"].setdefault(source, {"last_seen_key": "", "seen_keys": []})
        if source == "forexfactory":
            current_keys = [item_key(item) for item in items]
            seen = set(source_state.get("seen_keys", []))
            candidates = [item for item in items if item_key(item) not in seen]
        else:
            candidates, current_keys = select_new(items, source_state)
        if source != "forexfactory" and (
            not source_state["last_seen_key"]
            or (not candidates and source_state["last_seen_key"] not in current_keys)
        ):
            source_state.update({"last_seen_key": current_keys[0], "seen_keys": current_keys[:500]})
            print(f"{SOURCE_LABELS[source]} başlangıç referansı alındı; eski haberler gönderilmedi")
            continue
        processed = []
        for item in candidates:
            if is_cross_source_duplicate(item, fingerprints):
                print(f"Tekrar haber atlandı [{SOURCE_LABELS[source]}]: {item['title'][:90]}")
                processed.append(item_key(item))
                continue
            if remaining <= 0:
                break
            try:
                enrich(item)
            except Exception as exc:
                print(f"Detay alınamadı; liste özeti kullanılacak: {exc}")
            if not send_message(build_message(item)):
                break
            processed.append(item_key(item))
            remember_story(item, fingerprints)
            remaining -= 1
            time.sleep(SEND_DELAY)
        if len(processed) == len(candidates):
            source_state.update({"last_seen_key": current_keys[0], "seen_keys": list(dict.fromkeys(current_keys + source_state["seen_keys"]))[:500]})
        elif processed:
            source_state.update({"last_seen_key": processed[-1], "seen_keys": list(dict.fromkeys(list(reversed(processed)) + source_state["seen_keys"]))[:500]})
        if remaining <= 0:
            break
    save_state(state)


if __name__ == "__main__":
    main()
