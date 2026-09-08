-- Suppress only queued NEWS duplicates left by older runs. Sent history is preserved.
WITH ranked_news AS (
    SELECT
        outbox_id,
        row_number() OVER (
            PARTITION BY
                chat_id,
                message_thread_id,
                md5(COALESCE(payload->'message'->>'text', payload::text))
            ORDER BY created_at, outbox_id
        ) AS duplicate_rank
    FROM telegram_outbox
    WHERE publication_kind = 'news'
      AND status IN ('pending', 'failed')
)
UPDATE telegram_outbox AS target
SET status = 'deduplicated',
    last_error = 'suppressed_duplicate_news_payload',
    locked_at = NULL,
    lease_until = NULL
FROM ranked_news
WHERE target.outbox_id = ranked_news.outbox_id
  AND ranked_news.duplicate_rank > 1;

CREATE INDEX IF NOT EXISTS ix_news_items_dedup_key
    ON news_items ((payload->>'dedup_key'))
    WHERE payload ? 'dedup_key';
