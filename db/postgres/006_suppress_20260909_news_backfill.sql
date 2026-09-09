-- One-time safety valve for the 2026-09-09 manual NEWS backfill.
-- Records remain queryable and auditable; only queued Telegram delivery is suppressed.
UPDATE telegram_outbox
SET status = 'suppressed_backfill',
    last_error = 'manual_backfill_20260909_not_for_bulk_delivery',
    locked_at = NULL,
    lease_until = NULL
WHERE publication_kind IN ('news', 'calendar')
  AND status IN ('pending', 'failed')
  AND created_at <= TIMESTAMPTZ '2026-09-09 10:00:00+00';
