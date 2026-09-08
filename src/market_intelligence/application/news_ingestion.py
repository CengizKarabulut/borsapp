from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings
from market_intelligence.delivery.telegram.routing import (
    OutboxEnvelope,
    PublicationKind,
    TopicRouter,
)
from market_intelligence.news.contracts import NewsItem


class NewsProvider(Protocol):
    source: str

    def fetch(self, *, from_date: date, to_date: date) -> tuple[NewsItem, ...]: ...


@dataclass(frozen=True)
class PersistedNewsBatch:
    inserted: int
    linked_items: int
    outbox_count: int
    bootstrapped: bool


class NewsStore(Protocol):
    def persist(
        self,
        *,
        source: str,
        items: tuple[NewsItem, ...],
        observed_at: datetime,
        envelopes: dict[str, OutboxEnvelope],
    ) -> PersistedNewsBatch: ...


@dataclass(frozen=True)
class NewsSyncResult:
    fetched: int
    inserted: int
    linked_items: int
    outbox_count: int
    bootstrapped: bool


class NewsIngestionService:
    def __init__(
        self,
        *,
        provider: NewsProvider,
        store: NewsStore,
        telegram_settings: TelegramSettings,
    ) -> None:
        self.provider = provider
        self.store = store
        self.telegram_settings = telegram_settings
        self.router = TopicRouter(telegram_settings)

    def run(
        self,
        *,
        from_date: date,
        to_date: date,
        observed_at: datetime,
        notify: bool = False,
    ) -> NewsSyncResult:
        if notify and self.telegram_settings.delivery_mode is not DeliveryMode.LIVE:
            raise ValueError("haber bildirimi için DELIVERY_MODE=live olmalıdır")
        items = self.provider.fetch(from_date=from_date, to_date=to_date)
        envelopes = (
            {item.news_id: self._envelope(item) for item in items}
            if notify
            else {}
        )
        persisted = self.store.persist(
            source=self.provider.source,
            items=items,
            observed_at=observed_at,
            envelopes=envelopes,
        )
        return NewsSyncResult(
            fetched=len(items),
            inserted=persisted.inserted,
            linked_items=persisted.linked_items,
            outbox_count=persisted.outbox_count,
            bootstrapped=persisted.bootstrapped,
        )

    def _envelope(self, item: NewsItem) -> OutboxEnvelope:
        symbols = ", ".join(item.symbols)
        source_label = {
            "kap": "KAP",
            "bloomberght": "Bloomberg HT",
            "forexfactory": "Ekonomik Takvim",
            "investing": "Investing.com Türkiye",
            "ntvpara": "NTV Para",
            "trthaber": "TRT Haber Ekonomi",
            "tradingview": "TradingView",
        }.get(item.source, item.provider or item.source)
        heading = f"{source_label} · {symbols}" if symbols else source_label
        lines = [f"<b>{html.escape(heading)}</b>", html.escape(item.headline)]
        if item.summary:
            lines.append(html.escape(item.summary[:800]))
        if item.attachment_count:
            lines.append(f"📎 {item.attachment_count} ek")
        if item.url:
            lines.append(
                f'<a href="{html.escape(item.url, quote=True)}">Kaynağı aç</a>'
            )
        return self.router.route(
            publication_kind=(
                PublicationKind.CALENDAR
                if item.source == "forexfactory"
                else PublicationKind.NEWS
            ),
            semantic_identity={"news_id": item.news_id},
            payload={
                "text": "\n\n".join(lines),
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": False},
            },
        )
