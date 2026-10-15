-- Retry failed data vendors after a bounded cooldown instead of hammering
-- delisted/unsupported symbols on every time frame and every Actions run.
CREATE TABLE IF NOT EXISTS provider_retry_cooldowns (
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 1,
    next_retry_at TIMESTAMPTZ NOT NULL,
    last_error TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, provider_symbol, timeframe)
);
CREATE INDEX IF NOT EXISTS ix_provider_retry_cooldowns_expiry
    ON provider_retry_cooldowns(next_retry_at);
