-- Live summaries and resuming the current bar must not scan historical evaluations.
CREATE INDEX IF NOT EXISTS ix_scan_evaluations_live_bar
    ON scan_evaluations(timeframe, bar_time, instrument_id, scanner_id, evaluated_at DESC);
