from __future__ import annotations

import importlib.util
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

from market_intelligence.core.identity import stable_hash
from market_intelligence.news.contracts import NewsItem

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LEGACY_NEWS_FILE = REPOSITORY_ROOT / "_legacy" / "tradingview-haber-botu" / "news_bot.py"
SUPPORTED_SOURCES = (
    "bloomberght",
    "forexfactory",
    "investing",
    "ntvpara",
    "trthaber",
    "tradingview",
)
_BIST_TOKEN = re.compile(r"(?<![A-Z0-9])[A-Z]{3,6}(?![A-Z0-9])")


def _legacy_module() -> ModuleType:
    if not LEGACY_NEWS_FILE.is_file():
        raise RuntimeError(f"Legacy haber sağlayıcısı bulunamadı: {LEGACY_NEWS_FILE}")
    spec = importlib.util.spec_from_file_location("borsapp_legacy_general_news", LEGACY_NEWS_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Legacy haber sağlayıcısı yüklenemedi")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _published_at(raw: Any, timezone: ZoneInfo, fallback: datetime) -> datetime:
    value = str(raw or "").strip()
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


def _symbols(item: dict[str, Any]) -> tuple[str, ...]:
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    return tuple(dict.fromkeys(_BIST_TOKEN.findall(text.upper())))


class LegacyGeneralNewsProvider:
    """Strangler adapter for the six non-KAP providers in the source repository."""

    def __init__(self, source: str, *, timezone: ZoneInfo | None = None) -> None:
        normalized = source.strip().casefold()
        if normalized not in SUPPORTED_SOURCES:
            raise ValueError(f"Desteklenmeyen genel haber kaynağı: {source}")
        self.source = normalized
        self.timezone = timezone or ZoneInfo("Europe/Istanbul")

    def fetch(self, *, from_date: date, to_date: date) -> tuple[NewsItem, ...]:
        if from_date > to_date:
            raise ValueError("haber başlangıç tarihi bitiş tarihinden sonra olamaz")
        legacy = _legacy_module()
        observed_at = datetime.now(self.timezone)
        if self.source == "forexfactory":
            rows = legacy.fetch_forex_factory(now=observed_at)
        elif self.source in {"investing", "ntvpara", "trthaber"}:
            rows = legacy.fetch_rss_source(self.source)
        else:
            rows = getattr(legacy, f"fetch_{self.source}")()
        items: dict[str, NewsItem] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            headline = str(row.get("title") or "").strip()
            if not headline:
                continue
            published_at = _published_at(row.get("published"), self.timezone, observed_at)
            # Undated listing items are current snapshots. Dated feeds are bounded
            # so an old RSS page cannot be replayed as fresh news.
            if row.get("published") and not from_date <= published_at.date() <= to_date:
                continue
            url = str(row.get("link") or "").strip() or None
            provider_id = str(row.get("id") or url or "").strip()
            news_id = f"{self.source}:" + (
                provider_id
                if provider_id
                else stable_hash({"headline": headline, "published": published_at.isoformat()})
            )
            items[news_id] = NewsItem(
                news_id=news_id,
                source=self.source,
                headline=headline,
                published_at=published_at,
                url=url,
                symbols=_symbols(row),
                summary=str(row.get("summary") or row.get("detail") or "").strip()[:1800],
                provider=str(row.get("provider") or self.source).strip(),
                category=str(row.get("category") or "Piyasa Haberi").strip(),
                payload={key: value for key, value in row.items() if key != "detail"},
            )
        return tuple(sorted(items.values(), key=lambda item: item.published_at, reverse=True))
