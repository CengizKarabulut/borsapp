from __future__ import annotations

import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from market_intelligence.news.contracts import NewsItem
from market_intelligence.news.text import normalize_news_text, sentence_excerpt

KAP_BASE_URL = "https://www.kap.org.tr"
KAP_DISCLOSURES_URL = f"{KAP_BASE_URL}/tr/api/disclosure/members/byCriteria"
KAP_DETAIL_URL = f"{KAP_BASE_URL}/tr/api/notification/attachment-detail"
_SPACE = re.compile(r"\s+")
_SYMBOL = re.compile(r"[A-Z0-9]{2,12}")
_ENGLISH_BLOCK = re.compile(
    r"<(?P<tag>[a-z0-9]+)[^>]*class=['\"][^'\"]*\bcontent-en\b[^'\"]*['\"][^>]*>.*?</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)


class HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> HttpResponse: ...

    def get(self, url: str, **kwargs: Any) -> HttpResponse: ...


def _clean(value: Any) -> str:
    return normalize_news_text(value)


def _body_text(value: Any) -> str:
    fragments = value if isinstance(value, list) else [value]
    collected: list[str] = []
    for fragment in fragments:
        raw = str(fragment or "")
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(raw, "html.parser")
            for node in soup.select("script, style, .content-en"):
                node.decompose()
            text = " · ".join(soup.stripped_strings)
        except ImportError:
            text = _ENGLISH_BLOCK.sub(" ", raw)
        text = normalize_news_text(text)
        if text and not text.startswith("["):
            collected.append(text)
    return " · ".join(dict.fromkeys(collected))


def _published_at(value: Any, timezone: ZoneInfo) -> datetime:
    raw = _clean(value)
    if not raw:
        raise ValueError("KAP publishDate eksik")
    for pattern in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=timezone)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"KAP publishDate biçimi tanınmadı: {raw}") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone)


def _symbols(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        raw = " ".join(_clean(item) for item in value)
    else:
        raw = _clean(value)
    return tuple(dict.fromkeys(_SYMBOL.findall(raw.upper())))


class KapDisclosureProvider:
    source = "kap"

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        timezone: ZoneInfo | None = None,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
    ) -> None:
        if detail_workers < 1:
            raise ValueError("KAP detail_workers en az 1 olmalıdır")
        self.client = client
        self.timezone = timezone or ZoneInfo("Europe/Istanbul")
        self.timeout_seconds = timeout_seconds
        self.detail_workers = detail_workers

    def fetch(self, *, from_date: date, to_date: date) -> tuple[NewsItem, ...]:
        if from_date > to_date:
            raise ValueError("KAP başlangıç tarihi bitiş tarihinden sonra olamaz")
        client = self.client or self._default_client()
        response = client.post(
            KAP_DISCLOSURES_URL,
            json={
                "fromDate": from_date.isoformat(),
                "toDate": to_date.isoformat(),
                "disclosureClass": "",
                "subjectList": [],
                "mkkMemberOidList": [],
                "inactiveMkkMemberOidList": [],
                "bdkMemberOidList": [],
                "fromSrc": False,
                "disclosureIndexList": [],
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": KAP_BASE_URL,
                "Referer": f"{KAP_BASE_URL}/tr/bildirim-sorgu",
                "User-Agent": "borsapp/0.1 (+https://github.com/CengizKarabulut/borsapp)",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, list):
            raise RuntimeError("KAP bildirim sorgusu liste döndürmedi")
        items: dict[str, NewsItem] = {}
        for raw_row in body:
            if not isinstance(raw_row, Mapping):
                continue
            item = self._parse_row(raw_row)
            if item is not None:
                items[item.news_id] = item
        return tuple(sorted(items.values(), key=lambda item: item.published_at, reverse=True))

    def _parse_row(self, row: Mapping[str, Any]) -> NewsItem | None:
        disclosure_id = _clean(row.get("disclosureIndex"))
        if not disclosure_id:
            return None
        symbols = _symbols(row.get("stockCodes") or row.get("relatedStocks") or row.get("fundCode"))
        subject = _clean(row.get("subject") or row.get("summary") or "KAP Bildirimi")
        headline = f"{', '.join(symbols)} — {subject}" if symbols else subject
        company = _clean(row.get("kapTitle"))
        summary = _clean(row.get("summary"))
        if company:
            summary = " · ".join(part for part in (summary, f"Şirket: {company}") if part)
        return NewsItem(
            news_id=f"kap:{disclosure_id}",
            source=self.source,
            headline=headline,
            published_at=_published_at(row.get("publishDate"), self.timezone),
            url=f"{KAP_BASE_URL}/tr/Bildirim/{disclosure_id}",
            symbols=symbols,
            summary=summary,
            provider=company or "KAP",
            category=_clean(row.get("disclosureClass")),
            attachment_count=int(row.get("attachmentCount") or 0),
            payload=dict(row),
        )

    def enrich(self, items: tuple[NewsItem, ...]) -> tuple[NewsItem, ...]:
        """Fetch full KAP bodies for new disclosures; each failure uses list data."""

        if not items:
            return ()
        client = self.client or self._default_client()
        workers = min(self.detail_workers, len(items))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kap-detail") as pool:
            return tuple(pool.map(lambda item: self._enrich_one(client, item), items))

    def _enrich_one(self, client: HttpClient, item: NewsItem) -> NewsItem:
        disclosure_id = item.news_id.removeprefix("kap:")
        try:
            response = client.get(
                f"{KAP_DETAIL_URL}/{disclosure_id}",
                headers={
                    "Accept": "application/json",
                    "Referer": item.url or f"{KAP_BASE_URL}/tr/Bildirim/{disclosure_id}",
                    "User-Agent": "borsapp/0.1 (+https://github.com/CengizKarabulut/borsapp)",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            rows = body if isinstance(body, list) else []
            detail = rows[0] if rows and isinstance(rows[0], Mapping) else {}
            disclosure = detail.get("disclosure") if isinstance(detail, Mapping) else {}
            basic = disclosure.get("disclosureBasic") if isinstance(disclosure, Mapping) else {}
            basic_summary = _clean(basic.get("summary")) if isinstance(basic, Mapping) else ""
            detail_text = _body_text(detail.get("disclosureBody"))
            parts = list(dict.fromkeys(part for part in (basic_summary, detail_text) if part))
            summary = sentence_excerpt("\n\n".join(parts), max_chars=6_000)
            return replace(
                item,
                summary=summary or item.summary,
                payload={**dict(item.payload), "detail": detail},
            )
        except Exception:
            return item

    @staticmethod
    def _default_client() -> HttpClient:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx kurulu değil; runtime bağımlılıklarını yükleyin") from exc
        return httpx
