CREATE INDEX IF NOT EXISTS ix_shadow_comparisons_scanner_time
    ON shadow_comparisons (scanner_id, timeframe, bar_time DESC);

CREATE INDEX IF NOT EXISTS ix_shadow_comparisons_category
    ON shadow_comparisons (scanner_id, category)
    WHERE category IN ('legacy_only', 'new_only', 'finding_diff');
