CREATE INDEX IF NOT EXISTS ix_finding_outcomes_observed
    ON finding_outcomes(observed_at DESC, horizon_bars);

CREATE INDEX IF NOT EXISTS ix_scan_events_outcome_backfill
    ON scan_events(bar_time, scanner_id, timeframe);
