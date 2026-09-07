import html
import json
import os
import re
import time
from urllib.parse import urljoin, urlparse, urlunparse

import requests


TV_BASE_URL = "https://tr.tradingview.com"
TV_NEWS_URL = "https://tr.tradingview.com/news-flow/"
NEWS_API_URL = "https://news-mediator.tradingview.com/public/news-flow/v2/news"
NEWS_API_PARAMS = {
    "filter": "lang:tr",
    "client": "screener",
    "user_prostatus": "free",
}
SOURCE_VERSION = "tradingview-news-mediator-v2"

CACHE_FILE = os.environ.get("CACHE_FILE", "tv_news_cache.json")
NEWS_LIMIT = int(os.environ.get("NEWS_LIMIT", "200"))
CACHE_LIMIT = int(os.environ.get("CACHE_LIMIT", "500"))
PER_RUN_SEND_LIMIT = int(os.environ.get("PER_RUN_SEND_LIMIT", "100"))
TELEGRAM_SEND_DELAY = float(os.environ.get("TELEGRAM_SEND_DELAY", "4"))
MAX_TELEGRAM_ATTEMPTS = int(os.environ.get("MAX_TELEGRAM_ATTEMPTS", "5"))
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}

token = os.environ.get("TELEGRAM_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")
message_thread_id = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID")

if not DRY_RUN and (not token or not chat_id):
    raise SystemExit("TELEGRAM_TOKEN veya TELEGRAM_CHAT_ID eksik.")
if message_thread_id:
    try:
        message_thread_id = int(message_thread_id)
    except ValueError:
        raise SystemExit("TELEGRAM_MESSAGE_THREAD_ID sayisal olmalidir.")


def normalize_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalized_link(value):
    if not value:
        return ""
    parsed = urlparse(value)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def news_key(news):
    return normalized_link(news.get("link")) or normalize_space(news.get("title")).lower()


def unique_keys(keys):
    seen = set()
    result = []
    for key in keys:
        key = normalize_space(key)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
        if len(result) >= CACHE_LIMIT:
            break
    return result


def dedupe_news(news_items):
    seen = set()
    result = []
    for news in news_items:
        key = news_key(news)
        title_key = normalize_space(news.get("title")).lower()
        if not key or key in seen or title_key in seen:
            continue
        seen.add(key)
        if title_key:
            seen.add(title_key)
        result.append(news)
    return result


def load_state(path):
    state = {"source_version": "", "last_seen_key": "", "seen_keys": []}
    if not os.path.exists(path):
        return state
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"Cache okunamadi, guvenli baslangic yapilacak: {exc}")
        return state

    if isinstance(data, dict):
        source_version = data.get("source_version")
        if isinstance(source_version, str):
            state["source_version"] = source_version.strip()
        seen_keys = data.get("seen_keys", [])
        if isinstance(seen_keys, list):
            state["seen_keys"] = [
                item.strip()
                for item in seen_keys
                if isinstance(item, str) and item.strip()
            ]
        last_seen_key = data.get("last_seen_key")
        if isinstance(last_seen_key, str):
            state["last_seen_key"] = last_seen_key.strip()
        if not state["last_seen_key"] and state["seen_keys"]:
            state["last_seen_key"] = state["seen_keys"][0]
        return state

    if isinstance(data, list):
        loaded = []
        for item in data:
            if isinstance(item, str) and item.strip():
                loaded.append(item.strip())
            elif isinstance(item, dict):
                value = item.get("id") or item.get("link") or item.get("title")
                if isinstance(value, str) and value.strip():
                    loaded.append(value.strip())
        state["source_version"] = SOURCE_VERSION
        state["seen_keys"] = loaded
        if loaded:
            state["last_seen_key"] = loaded[0]

    return state


def save_state(last_seen_key, keys):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source_version": SOURCE_VERSION,
                "last_seen_key": last_seen_key,
                "seen_keys": unique_keys(keys),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def fetch_news_flow():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Origin": TV_BASE_URL,
        "Referer": TV_NEWS_URL,
    }
    response = requests.get(
        NEWS_API_URL,
        params=NEWS_API_PARAMS,
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()

    data = response.json()
    items = data.get("items", [])
    if not isinstance(items, list):
        return []

    found = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = normalize_space(item.get("title"))
        story_path = normalize_space(
            item.get("storyPath")
            or item.get("story_path")
            or item.get("url")
        )
        if not title or not story_path:
            continue

        link = story_path if story_path.startswith("http") else urljoin(TV_BASE_URL, story_path)
        provider = item.get("provider") or {}
        provider_name = ""
        if isinstance(provider, dict):
            provider_name = normalize_space(provider.get("name") or provider.get("id"))
        elif isinstance(provider, str):
            provider_name = normalize_space(provider)

        found.append(
            {
                "title": title,
                "link": link,
                "provider": provider_name,
                "published": item.get("published"),
                "id": normalize_space(item.get("id")),
            }
        )
        if len(found) >= NEWS_LIMIT:
            break

    return dedupe_news(found)


def telegram_retry_after(response):
    try:
        payload = response.json()
    except Exception:
        return 15
    parameters = payload.get("parameters") if isinstance(payload, dict) else {}
    retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
    try:
        return max(1, int(retry_after))
    except (TypeError, ValueError):
        return 15


def send_telegram(text):
    if DRY_RUN:
        print(f"DRY_RUN: Telegram'a gonderilmeyecek ({len(text)} karakter).")
        return True

    tg_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id

    for attempt in range(1, MAX_TELEGRAM_ATTEMPTS + 1):
        try:
            response = requests.post(tg_url, json=payload, timeout=20)
        except requests.RequestException as exc:
            wait_seconds = min(60, 5 * attempt)
            print(f"Telegram istegi basarisiz (deneme {attempt}): {exc}; {wait_seconds}s beklenecek.")
            time.sleep(wait_seconds)
            continue

        if response.status_code == 429:
            wait_seconds = telegram_retry_after(response) + 1
            print(f"Telegram hiz limiti verdi; {wait_seconds}s beklenip tekrar denenecek.")
            time.sleep(wait_seconds)
            continue

        if 500 <= response.status_code < 600:
            wait_seconds = min(60, 5 * attempt)
            print(f"Telegram gecici hata verdi: {response.status_code}; {wait_seconds}s beklenecek.")
            time.sleep(wait_seconds)
            continue

        if response.status_code >= 400:
            print(f"Telegram kalici hata verdi, mesaj sonraki tura birakildi: {response.status_code} {response.text[:300]}")
            return False

        return True

    print("Telegram mesaji tekrar denemelerden sonra gonderilemedi; sonraki tura birakildi.")
    return False


def select_news_to_process(found_news, state):
    current_keys = [news_key(news) for news in found_news]
    latest_key = current_keys[0]
    old_news = state["seen_keys"]
    old_news_set = set(old_news)
    last_seen_key = state["last_seen_key"]

    if state["source_version"] != SOURCE_VERSION:
        print("Cache veri kaynagi eski veya farkli; eski haberleri gondermemek icin sadece yeni referans alinacak.")
        return [], 0, latest_key, current_keys, [], "bootstrap"

    if not last_seen_key:
        print("Ilk calistirma: en ustteki haber referans alindi; eski haberler gonderilmeyecek.")
        return [], 0, latest_key, current_keys, old_news, "bootstrap"

    if last_seen_key in current_keys:
        cutoff_index = current_keys.index(last_seen_key)
        print(f"Son gorulen haber bulundu. Yeni haber sayisi: {cutoff_index}")
    else:
        seen_indexes = [
            index
            for index, key in enumerate(current_keys)
            if key in old_news_set
        ]
        if seen_indexes:
            cutoff_index = min(seen_indexes)
            print(f"Son gorulen haber listede yok, ama daha once gorulmus bir haber bulundu. Yeni haber sayisi: {cutoff_index}")
        else:
            print("Son gorulen haber akista bulunamadi; tekrar atmamak icin sadece yeni referans alinacak.")
            return [], 0, latest_key, current_keys, old_news, "bootstrap"

    candidates = [
        news
        for news in reversed(found_news[:cutoff_index])
        if news_key(news) not in old_news_set
    ]
    return candidates[:PER_RUN_SEND_LIMIT], len(candidates), latest_key, current_keys, old_news, "normal"


def build_message(news):
    safe_title = html.escape(news["title"])
    safe_news_link = html.escape(news["link"], quote=True)
    return (
        f"<b>{safe_title}</b>\n\n"
        f"<a href=\"{safe_news_link}\">TradingView'de oku</a>"
    )


def main():
    cache_state = load_state(CACHE_FILE)

    print(f"TradingView haber API aciliyor: {NEWS_API_URL}")
    try:
        found_news_links = fetch_news_flow()
    except Exception as exc:
        print(f"Haber akisi okunamadi; cache degistirilmeyecek: {exc}")
        return

    print(f"TradingView akistan bulunan haber sayisi: {len(found_news_links)}")
    for item in found_news_links[:10]:
        provider = f" [{item['provider']}]" if item.get("provider") else ""
        print(f"- {item['title']}{provider} | {item['link']}")

    if not found_news_links:
        print("Haber bulunamadi; cache degistirilmeyecek.")
        return

    (
        news_to_process,
        candidate_count,
        latest_key,
        current_keys,
        old_news,
        mode,
    ) = select_news_to_process(found_news_links, cache_state)

    sent_keys = []
    for news in news_to_process:
        print(f"Gonderiliyor: {news['title'][:90]}")
        if not send_telegram(build_message(news)):
            print("Gonderim durduruldu; kalan haberler sonraki calismada denenecek.")
            break
        sent_keys.append(news_key(news))
        time.sleep(TELEGRAM_SEND_DELAY)

    if mode == "bootstrap":
        save_state(latest_key, current_keys + old_news)
        print("TradingView haber cache'i referans noktasina guncellendi.")
        return

    if not news_to_process:
        save_state(latest_key, current_keys + old_news)
        print("Yeni haber yok; cache tazelendi.")
        return

    if sent_keys and len(sent_keys) == candidate_count:
        save_state(latest_key, current_keys + old_news)
        print("Tum yeni haberler gonderildi; cache en yeni habere ilerletildi.")
        return

    if sent_keys:
        save_state(sent_keys[-1], list(reversed(sent_keys)) + old_news)
        print(f"{len(sent_keys)} haber gonderildi; cache son basarili mesaja kadar ilerletildi.")
        return

    save_state(cache_state["last_seen_key"], old_news)
    print("Hic haber gonderilemedi; cache ilerletilmedi.")


if __name__ == "__main__":
    main()
