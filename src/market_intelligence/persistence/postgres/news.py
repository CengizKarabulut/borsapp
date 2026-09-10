from __future__ import annotations

from datetime import datetime
from typing import Any

from market_intelligence.application.news_ingestion import PersistedNewsBatch
from market_intelligence.core.identity import canonical_json
from market_intelligence.delivery.telegram.routing import OutboxEnvelope
from market_intelligence.news.contracts import NewsItem
from market_intelligence.news.text import news_dedup_key
from market_intelligence.persistence.postgres.scan_store import (
    OUTBOX_SQL,
    PostgresConnection,
)

SOURCE_EXISTS_SQL = "SELECT EXISTS(SELECT 1 FROM news_items WHERE source = %s)"
EXISTING_IDS_SQL = "SELECT news_id FROM news_items WHERE news_id = ANY(%s)"
ENRICHED_IDS_SQL = """
SELECT news_id
FROM news_items
WHERE news_id = ANY(%s)
  AND (
    (source = 'kap' AND jsonb_typeof(payload -> 'raw' -> 'detail') = 'object')
    OR
    (source <> 'kap' AND COALESCE(payload -> 'raw' ->> 'enriched', 'false') = 'true')
  )
"""
RESOLVE_SYMBOLS_SQL = """
SELECT DISTINCT ON (upper(s.symbol)) upper(s.symbol), i.instrument_id
FROM instrument_symbols s
JOIN instruments i ON i.instrument_id = s.instrument_id
WHERE s.provider = 'canonical' AND upper(s.symbol) = ANY(%s)
  AND s.valid_from <= %s
  AND (s.valid_to IS NULL OR s.valid_to >= %s)
  AND i.valid_from <= %s
  AND (i.valid_to IS NULL OR i.valid_to >= %s)
ORDER BY upper(s.symbol), s.valid_from DESC
"""
UPSERT_NEWS_SQL = """
INSERT INTO news_items (
    news_id, instrument_id, headline, published_at, source, url, payload, observed_at
)
SELECT news_id, instrument_id, headline, published_at, source, url, payload, observed_at
FROM jsonb_to_recordset(%s::jsonb) AS value(
    news_id TEXT, instrument_id UUID, headline TEXT, published_at TIMESTAMPTZ,
    source TEXT, url TEXT, payload JSONB, observed_at TIMESTAMPTZ
)
ON CONFLICT (news_id) DO UPDATE SET
    instrument_id = COALESCE(EXCLUDED.instrument_id, news_items.instrument_id),
    headline = EXCLUDED.headline,
    published_at = EXCLUDED.published_at,
    url = EXCLUDED.url,
    payload = CASE
        WHEN length(COALESCE(news_items.payload ->> 'summary', ''))
           > length(COALESCE(EXCLUDED.payload ->> 'summary', ''))
        THEN news_items.payload
        ELSE EXCLUDED.payload
    END,
    observed_at = EXCLUDED.observed_at
"""
LINK_NEWS_SQL = """
INSERT INTO news_item_instruments (news_id, instrument_id, symbol_at_link, linked_at)
SELECT news_id, instrument_id, symbol_at_link, linked_at
FROM jsonb_to_recordset(%s::jsonb) AS value(
    news_id TEXT, instrument_id UUID, symbol_at_link TEXT, linked_at TIMESTAMPTZ
)
ON CONFLICT (news_id, instrument_id) DO NOTHING
"""


class PostgresNewsStore:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def existing_ids(self, news_ids: tuple[str, ...]) -> set[str]:
        if not news_ids:
            return set()
        with self.connection.cursor() as cursor:
            cursor.execute(EXISTING_IDS_SQL, (list(news_ids),))
            return {str(row[0]) for row in cursor.fetchall()}

    def enriched_ids(self, news_ids: tuple[str, ...]) -> set[str]:
        """Return rows that already contain their source-specific detail payload.

        Existing list-only rows are deliberately omitted so a later sync can
        backfill their complete Turkish summary without creating a new outbox
        notification; persist still recognises them as existing rows.
        """

        if not news_ids:
            return set()
        with self.connection.cursor() as cursor:
            cursor.execute(ENRICHED_IDS_SQL, (list(news_ids),))
            return {str(row[0]) for row in cursor.fetchall()}

    def persist(
        self,
        *,
        source: str,
        items: tuple[NewsItem, ...],
        observed_at: datetime,
        envelopes: dict[str, OutboxEnvelope],
    ) -> PersistedNewsBatch:
        if any(item.source != source for item in items):
            raise ValueError("haber batch'i tek kaynak içermelidir")
        if not items:
            return PersistedNewsBatch(0, 0, 0, False)
        unknown_envelopes = set(envelopes) - {item.news_id for item in items}
        if unknown_envelopes:
            raise ValueError("batch dışında haber için outbox zarfı verildi")

        news_ids = [item.news_id for item in items]
        symbols = sorted({symbol for item in items for symbol in item.symbols})
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(SOURCE_EXISTS_SQL, (source,))
                source_exists = bool(cursor.fetchone()[0])
                cursor.execute(EXISTING_IDS_SQL, (news_ids,))
                existing_ids = {str(row[0]) for row in cursor.fetchall()}
                instrument_by_symbol: dict[str, str] = {}
                if symbols:
                    day = observed_at.date()
                    cursor.execute(
                        RESOLVE_SYMBOLS_SQL,
                        (symbols, day, day, day, day),
                    )
                    instrument_by_symbol = {
                        str(row[0]).upper(): str(row[1]) for row in cursor.fetchall()
                    }
                news_rows, link_rows = self._rows(
                    items,
                    observed_at=observed_at,
                    instrument_by_symbol=instrument_by_symbol,
                )
                cursor.execute(UPSERT_NEWS_SQL, (canonical_json(news_rows),))
                if link_rows:
                    cursor.execute(LINK_NEWS_SQL, (canonical_json(link_rows),))

                new_ids = set(news_ids) - existing_ids
                outbox_count = 0
                if source_exists:
                    for item in items:
                        if (
                            item.news_id in new_ids
                            and item.news_id in envelopes
                            and (
                                item.source != "kap"
                                or any(symbol in instrument_by_symbol for symbol in item.symbols)
                            )
                        ):
                            outbox_count += self._persist_outbox(
                                cursor, envelopes[item.news_id]
                            )
        linked_items = sum(
            any(symbol in instrument_by_symbol for symbol in item.symbols)
            for item in items
        )
        return PersistedNewsBatch(
            inserted=len(new_ids),
            linked_items=linked_items,
            outbox_count=outbox_count,
            bootstrapped=not source_exists,
        )

    @staticmethod
    def _rows(
        items: tuple[NewsItem, ...],
        *,
        observed_at: datetime,
        instrument_by_symbol: dict[str, str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        news_rows: list[dict[str, Any]] = []
        link_rows: list[dict[str, Any]] = []
        for item in items:
            linked = [
                (symbol, instrument_by_symbol[symbol])
                for symbol in item.symbols
                if symbol in instrument_by_symbol
            ]
            details = {
                "symbols": list(item.symbols),
                "summary": item.summary,
                "provider": item.provider,
                "category": item.category,
                "attachment_count": item.attachment_count,
                "raw": dict(item.payload),
                "dedup_key": news_dedup_key(
                    source=item.source,
                    news_id=item.news_id,
                    headline=item.headline,
                    url=item.url,
                    published_at=item.published_at,
                ),
            }
            news_rows.append(
                {
                    "news_id": item.news_id,
                    "instrument_id": linked[0][1] if linked else None,
                    "headline": item.headline,
                    "published_at": item.published_at.isoformat(),
                    "source": item.source,
                    "url": item.url,
                    "payload": details,
                    "observed_at": observed_at.isoformat(),
                }
            )
            link_rows.extend(
                {
                    "news_id": item.news_id,
                    "instrument_id": instrument_id,
                    "symbol_at_link": symbol,
                    "linked_at": observed_at.isoformat(),
                }
                for symbol, instrument_id in linked
            )
        return news_rows, link_rows

    @staticmethod
    def _persist_outbox(cursor: Any, envelope: OutboxEnvelope) -> int:
        payload = {
            "publication_kind": envelope.publication_kind.value,
            "chat_id": envelope.chat_id,
            "message_thread_id": envelope.message_thread_id,
            "message": envelope.payload,
        }
        cursor.execute(
            OUTBOX_SQL,
            (
                envelope.semantic_key,
                envelope.publication_kind.value,
                envelope.topic_kind.value,
                envelope.chat_id,
                envelope.message_thread_id,
                canonical_json(payload),
            ),
        )
        return int(cursor.fetchone() is not None)
