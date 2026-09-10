from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from market_intelligence.core.identity import stable_hash
from market_intelligence.news.contracts import NewsItem
from market_intelligence.news.text import (
    normalize_news_text,
    polish_news_copy,
    sentence_excerpt,
)

SUPPORTED_SOURCES = (
    "bloomberght",
    "forexfactory",
    "investing",
    "ntvpara",
    "trthaber",
    "tradingview",
)

_TV_BASE = "https://tr.tradingview.com"
_TV_API = "https://news-mediator.tradingview.com/public/news-flow/v2/news"
_BHT_BASE = "https://www.bloomberght.com"
_BHT_LIST = f"{_BHT_BASE}/tumhaberler"
_FOREX_CALENDAR = "https://www.forexfactory.com/calendar"
_FOREX_API = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_FOREX_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "TRY", "CHF", "CAD", "AUD", "NZD"}
_RSS_FEEDS = {
    "investing": (
        "https://tr.investing.com/rss/news.rss",
        "https://tr.investing.com/rss/forex.rss",
        "https://tr.investing.com/rss/stock.rss",
    ),
    "ntvpara": ("https://www.ntv.com.tr/ntvpara.rss",),
    "trthaber": ("https://www.trthaber.com/ekonomi_articles.rss",),
}
_SOURCE_LABELS = {
    "bloomberght": "Bloomberg HT",
    "forexfactory": "Forex Factory Takvimi",
    "investing": "Investing.com Türkiye",
    "ntvpara": "NTV Para",
    "trthaber": "TRT Haber Ekonomi",
    "tradingview": "TradingView",
}
_BIST_TOKEN = re.compile(r"(?<![A-Z0-9])[A-Z]{3,6}(?![A-Z0-9])")
RowFetcher = Callable[[str, datetime], Iterable[Mapping[str, Any]]]


def _headers(referer: str | None = None, *, json_response: bool = False) -> dict[str, str]:
    result = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/126 Safari/537.36"
        ),
        "Accept": "application/json" if json_response else "text/html,application/xhtml+xml",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
    }
    if referer:
        result["Referer"] = referer
    return result


def _published_at(raw: Any, timezone: ZoneInfo, fallback: datetime) -> datetime:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            return datetime.fromtimestamp(raw, tz=timezone)
        except (OSError, OverflowError, ValueError):
            return fallback
    value = normalize_news_text(raw)
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _xml_text(node: ElementTree.Element, *names: str) -> str:
    wanted = {name.casefold() for name in names}
    for child in node:
        if child.tag.rsplit("}", 1)[-1].casefold() in wanted:
            return normalize_news_text("".join(child.itertext()))
    return ""


def _xml_link(node: ElementTree.Element) -> str:
    for child in node:
        if child.tag.rsplit("}", 1)[-1].casefold() != "link":
            continue
        value = normalize_news_text(child.get("href") or "".join(child.itertext()))
        if value and child.get("rel", "alternate") in {"", "alternate"}:
            return value
    return ""


def _symbols(row: Mapping[str, Any]) -> tuple[str, ...]:
    text = f"{row.get('title', '')} {row.get('summary', '')} {row.get('detail', '')}"
    return tuple(dict.fromkeys(_BIST_TOKEN.findall(normalize_news_text(text).upper())))


class GeneralNewsProvider:
    """Native canonical provider for non-KAP news and calendar sources."""

    def __init__(
        self,
        source: str,
        *,
        timezone: ZoneInfo | None = None,
        session: Any = requests,
        limit: int = 100,
        detail_limit: int = 5,
        row_fetcher: RowFetcher | None = None,
    ) -> None:
        normalized = source.strip().casefold()
        if normalized not in SUPPORTED_SOURCES:
            raise ValueError(f"Desteklenmeyen genel haber kaynağı: {source}")
        if limit < 1 or detail_limit < 0:
            raise ValueError("haber limitleri geçersiz")
        self.source = normalized
        self.timezone = timezone or ZoneInfo("Europe/Istanbul")
        self.session = session
        self.limit = limit
        self.detail_limit = detail_limit
        self.row_fetcher = row_fetcher

    def fetch(self, *, from_date: date, to_date: date) -> tuple[NewsItem, ...]:
        if from_date > to_date:
            raise ValueError("haber başlangıç tarihi bitiş tarihinden sonra olamaz")
        observed_at = datetime.now(self.timezone)
        rows = (
            self.row_fetcher(self.source, observed_at)
            if self.row_fetcher is not None
            else self._fetch_rows(observed_at)
        )
        items: dict[str, NewsItem] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            headline = normalize_news_text(row.get("title"))
            if not headline:
                continue
            published_at = _published_at(row.get("published"), self.timezone, observed_at)
            if row.get("published") and not from_date <= published_at.date() <= to_date:
                continue
            url = normalize_news_text(row.get("link")) or None
            provider_id = normalize_news_text(row.get("id") or url)
            news_id = f"{self.source}:" + (
                provider_id
                if provider_id
                else stable_hash({"headline": headline, "published": published_at.isoformat()})
            )
            summary = sentence_excerpt(
                row.get("detail") or row.get("summary") or "",
                max_chars=6_000,
            )
            headline, summary = polish_news_copy(headline, summary)
            payload = dict(row)
            payload.pop("detail", None)
            if self.source in {"forexfactory", "tradingview"}:
                payload["enriched"] = True
            candidate = NewsItem(
                news_id=news_id,
                source=self.source,
                headline=headline,
                published_at=published_at,
                url=url,
                symbols=_symbols(row),
                summary=summary,
                provider=normalize_news_text(
                    row.get("provider") or _SOURCE_LABELS[self.source]
                ),
                category=normalize_news_text(row.get("category") or "Piyasa Haberi"),
                payload=payload,
            )
            current = items.get(news_id)
            if current is None or len(candidate.summary) > len(current.summary):
                items[news_id] = candidate
            if len(items) >= self.limit:
                break
        return tuple(sorted(items.values(), key=lambda item: item.published_at, reverse=True))

    def enrich(self, items: tuple[NewsItem, ...]) -> tuple[NewsItem, ...]:
        enriched: list[NewsItem] = []
        remaining = self.detail_limit
        for item in items:
            if item.payload.get("enriched") is True or not item.url or remaining == 0:
                enriched.append(item)
                continue
            remaining -= 1
            try:
                response = self.session.get(
                    item.url,
                    headers=_headers(item.url),
                    timeout=12,
                )
                response.raise_for_status()
                response.encoding = response.encoding or "utf-8"
                soup = BeautifulSoup(response.text, "html.parser")
                candidates = [
                    node.get("content", "")
                    for selector in (
                        'meta[property="og:description"]',
                        'meta[name="description"]',
                    )
                    for node in soup.select(selector)[:1]
                ]
                candidates.extend(
                    node.get_text(" ", strip=True)
                    for node in soup.select("article p, main article p")
                    if len(normalize_news_text(node.get_text(" ", strip=True))) >= 40
                )
                parts = list(
                    dict.fromkeys(
                        value
                        for value in (normalize_news_text(value) for value in candidates)
                        if value and value.casefold() not in item.summary.casefold()
                    )
                )
                combined = " ".join(part for part in (item.summary, *parts) if part)
                headline, summary = polish_news_copy(
                    item.headline,
                    sentence_excerpt(combined, max_chars=6_000),
                )
                payload = dict(item.payload)
                payload["enriched"] = True
                enriched.append(
                    replace(
                        item,
                        headline=headline,
                        summary=summary,
                        payload=payload,
                    )
                )
            except (requests.RequestException, ValueError):
                enriched.append(item)
        return tuple(enriched)

    def _fetch_rows(self, observed_at: datetime) -> tuple[Mapping[str, Any], ...]:
        if self.source == "forexfactory":
            return self._fetch_forex_factory(observed_at)
        if self.source == "bloomberght":
            return self._fetch_bloomberght()
        if self.source == "tradingview":
            return self._fetch_tradingview()
        return self._fetch_rss()

    def _fetch_forex_factory(self, observed_at: datetime) -> tuple[Mapping[str, Any], ...]:
        rows: Any = ()
        for attempt in range(2):
            response = self.session.get(
                _FOREX_API,
                headers=_headers(_FOREX_CALENDAR, json_response=True),
                timeout=25,
            )
            if getattr(response, "status_code", 200) == 429 and attempt == 0:
                retry_after = normalize_news_text(
                    getattr(response, "headers", {}).get("Retry-After")
                )
                time.sleep(min(int(retry_after), 5) if retry_after.isdigit() else 2)
                continue
            response.raise_for_status()
            rows = response.json()
            break
        found: list[Mapping[str, Any]] = []
        for row in rows if isinstance(rows, list) else ():
            currency = normalize_news_text(row.get("country")).upper()
            title = normalize_news_text(row.get("title"))
            event_time = _published_at(row.get("date"), self.timezone, observed_at)
            impact = normalize_news_text(row.get("impact")).casefold()
            if currency not in _FOREX_CURRENCIES or not title or impact != "high":
                continue
            minutes = (event_time - observed_at).total_seconds() / 60
            actual = normalize_news_text(row.get("actual"))
            if 0 <= minutes <= 75:
                phase, timing = "upcoming", f"Yaklaşık {max(1, round(minutes))} dakika sonra"
            elif -30 <= minutes < 0 and actual:
                phase, timing = "released", "Yeni açıklandı"
            else:
                continue
            values = [timing, "Etki: Yüksek"]
            for label, value in (
                ("Açıklanan", actual),
                ("Beklenti", normalize_news_text(row.get("forecast"))),
                ("Önceki", normalize_news_text(row.get("previous"))),
            ):
                if value:
                    values.append(f"{label}: {value}")
            found.append(
                {
                    "id": f"{phase}:{currency}:{event_time.isoformat()}:{title.casefold()}",
                    "title": f"{currency} — {title}",
                    "link": _FOREX_CALENDAR,
                    "published": event_time.isoformat(),
                    "summary": " · ".join(values),
                    "provider": "Forex Factory",
                    "category": "Ekonomik Takvim",
                }
            )
        return tuple(found)

    def _fetch_bloomberght(self) -> tuple[Mapping[str, Any], ...]:
        response = self.session.get(
            _BHT_LIST,
            headers=_headers(_BHT_BASE),
            timeout=25,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        found: list[Mapping[str, Any]] = []
        for card in soup.select('main [data-type^="news-card"]'):
            anchor = card.select_one("a[href][title]") or card.select_one("a[href]")
            if anchor is None:
                continue
            path = normalize_news_text(anchor.get("href"))
            title = normalize_news_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            if not path or not title or path.startswith("/sondakika"):
                continue
            paragraph = card.select_one("p")
            found.append(
                {
                    "id": urljoin(_BHT_BASE, path),
                    "title": title,
                    "link": urljoin(_BHT_BASE, path),
                    "summary": normalize_news_text(
                        paragraph.get_text(" ", strip=True) if paragraph else ""
                    ),
                    "provider": _SOURCE_LABELS[self.source],
                }
            )
            if len(found) >= self.limit:
                break
        return tuple(found)

    def _fetch_tradingview(self) -> tuple[Mapping[str, Any], ...]:
        headers = _headers(f"{_TV_BASE}/news-flow/", json_response=True)
        headers["Origin"] = _TV_BASE
        response = self.session.get(
            _TV_API,
            params={"filter": "lang:tr", "client": "screener", "user_prostatus": "free"},
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        found: list[Mapping[str, Any]] = []
        for row in payload.get("items", ()) if isinstance(payload, dict) else ():
            title = normalize_news_text(row.get("title"))
            path = normalize_news_text(
                row.get("storyPath") or row.get("story_path") or row.get("url")
            )
            if not title or not path:
                continue
            provider = row.get("provider") or {}
            provider_name = (
                normalize_news_text(provider.get("name") or provider.get("id"))
                if isinstance(provider, dict)
                else normalize_news_text(provider)
            )
            found.append(
                {
                    "id": normalize_news_text(row.get("id")),
                    "title": title,
                    "link": path if path.startswith("http") else urljoin(_TV_BASE, path),
                    "published": row.get("published"),
                    "summary": normalize_news_text(
                        row.get("description") or row.get("summary")
                    ),
                    "provider": provider_name or "TradingView",
                }
            )
            if len(found) >= self.limit:
                break
        return tuple(found)

    def _fetch_rss(self) -> tuple[Mapping[str, Any], ...]:
        found: list[Mapping[str, Any]] = []
        for feed_url in _RSS_FEEDS[self.source]:
            try:
                response = self.session.get(
                    feed_url,
                    headers=_headers(feed_url)
                    | {"Accept": "application/rss+xml,application/xml,text/xml"},
                    timeout=25,
                )
                response.raise_for_status()
                root = ElementTree.fromstring(response.content)
            except (requests.RequestException, ElementTree.ParseError):
                continue
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1].casefold() not in {"item", "entry"}:
                    continue
                title = _xml_text(node, "title")
                link = _xml_link(node)
                if not title or not link:
                    continue
                raw_summary = _xml_text(
                    node,
                    "description",
                    "summary",
                    "content",
                    "subtitle",
                )
                found.append(
                    {
                        "id": _xml_text(node, "guid", "id") or link,
                        "title": title,
                        "link": link,
                        "published": _xml_text(node, "pubDate", "published", "updated"),
                        "summary": normalize_news_text(
                            BeautifulSoup(raw_summary, "html.parser").get_text(
                                " ",
                                strip=True,
                            )
                        ),
                        "provider": _SOURCE_LABELS[self.source],
                    }
                )
                if len(found) >= self.limit:
                    return tuple(found)
        return tuple(found)


# Import compatibility for callers that have not yet changed the old class name.
LegacyGeneralNewsProvider = GeneralNewsProvider
