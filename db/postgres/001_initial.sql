CREATE TABLE IF NOT EXISTS instruments (
    instrument_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_class TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT,
    valid_from DATE NOT NULL,
    valid_to DATE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE TABLE IF NOT EXISTS instrument_symbols (
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    provider TEXT NOT NULL,
    symbol TEXT NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE,
    PRIMARY KEY (instrument_id, provider, symbol, valid_from),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX IF NOT EXISTS ix_instrument_symbols_lookup
    ON instrument_symbols(provider, symbol, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS universe_memberships (
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    universe_id TEXT NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE,
    PRIMARY KEY (instrument_id, universe_id, valid_from)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    action_type TEXT NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    source TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS data_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    timeframe TEXT NOT NULL,
    through_bar_time TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    price_basis TEXT NOT NULL,
    series_revision BIGINT NOT NULL,
    payload_hash TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    quality TEXT NOT NULL,
    is_provisional BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonical_bars (
    snapshot_id TEXT NOT NULL REFERENCES data_snapshots(snapshot_id) ON DELETE CASCADE,
    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (snapshot_id, close_time),
    CHECK (close_time > open_time),
    CHECK (volume >= 0)
);

CREATE TABLE IF NOT EXISTS scan_cycles (
    cycle_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    expected_instruments INTEGER NOT NULL,
    successful_instruments INTEGER NOT NULL DEFAULT 0,
    stale_instruments INTEGER NOT NULL DEFAULT 0,
    failed_instruments INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    UNIQUE (market, universe_id, timeframe, bar_time)
);

CREATE TABLE IF NOT EXISTS scan_watermarks (
    market TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    scanner_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    last_completed_bar_time TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (market, universe_id, scanner_id, timeframe)
);

CREATE TABLE IF NOT EXISTS scan_evaluations (
    evaluation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cycle_id UUID NOT NULL REFERENCES scan_cycles(cycle_id),
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    symbol_at_evaluation TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    scanner_id TEXT NOT NULL,
    scanner_version TEXT NOT NULL,
    ruleset_hash TEXT NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES data_snapshots(snapshot_id),
    status TEXT NOT NULL CHECK (status IN ('match', 'no_match', 'unknown')),
    finding_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_detail TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (
        instrument_id, scanner_id, scanner_version, ruleset_hash,
        snapshot_id
    )
);

CREATE TABLE IF NOT EXISTS scan_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_id UUID NOT NULL REFERENCES scan_evaluations(evaluation_id),
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    symbol_at_event TEXT NOT NULL,
    scanner_id TEXT NOT NULL,
    finding_key TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    direction TEXT NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (instrument_id, scanner_id, finding_key, timeframe, bar_time)
);

CREATE TABLE IF NOT EXISTS active_states (
    state_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    scanner_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    state_key TEXT NOT NULL,
    status TEXT NOT NULL,
    producer_version TEXT NOT NULL,
    ruleset_hash TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL,
    unknown_bars INTEGER NOT NULL DEFAULT 0,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (instrument_id, scanner_id, timeframe, state_key)
);

CREATE TABLE IF NOT EXISTS state_transitions (
    transition_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transition_key TEXT NOT NULL UNIQUE,
    state_id UUID REFERENCES active_states(state_id),
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    scanner_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    previous_state_key TEXT,
    next_state_key TEXT,
    transition_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    timing_uncertain BOOLEAN NOT NULL DEFAULT FALSE,
    bar_time TIMESTAMPTZ NOT NULL,
    producer_version TEXT NOT NULL,
    ruleset_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS telegram_outbox (
    outbox_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    semantic_key TEXT NOT NULL UNIQUE,
    publication_kind TEXT NOT NULL,
    topic_kind TEXT NOT NULL,
    chat_id BIGINT NOT NULL,
    message_thread_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    lease_until TIMESTAMPTZ,
    telegram_message_id BIGINT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_telegram_outbox_pending
    ON telegram_outbox(status, available_at);

CREATE TABLE IF NOT EXISTS telegram_consumers (
    consumer_key TEXT PRIMARY KEY,
    last_update_id BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shadow_comparisons (
    comparison_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id TEXT NOT NULL REFERENCES data_snapshots(snapshot_id),
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    scanner_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    legacy_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    category TEXT NOT NULL,
    legacy_finding_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    new_finding_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    diagnostics JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snapshot_id, scanner_id)
);

CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    artifact_kind TEXT NOT NULL,
    timeframe TEXT,
    bar_time TIMESTAMPTZ,
    summary TEXT NOT NULL,
    storage_uri TEXT,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, artifact_kind, timeframe, bar_time, content_hash)
);

CREATE TABLE IF NOT EXISTS ma_research_levels (
    research_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID NOT NULL REFERENCES instruments(instrument_id),
    timeframe TEXT NOT NULL,
    ma_type TEXT NOT NULL,
    period INTEGER NOT NULL CHECK (period >= 2),
    level_class TEXT NOT NULL,
    touches INTEGER NOT NULL CHECK (touches >= 0),
    quality_score DOUBLE PRECISION NOT NULL,
    research_version TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (valid_until IS NULL OR valid_until > valid_from),
    UNIQUE (
        instrument_id, timeframe, ma_type, period,
        research_version, valid_from
    )
);
CREATE INDEX IF NOT EXISTS ix_ma_research_levels_active
    ON ma_research_levels(instrument_id, timeframe, valid_from, valid_until);

CREATE TABLE IF NOT EXISTS news_items (
    news_id TEXT PRIMARY KEY,
    instrument_id UUID REFERENCES instruments(instrument_id),
    headline TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_news_items_instrument_published
    ON news_items(instrument_id, published_at DESC);

CREATE TABLE IF NOT EXISTS command_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    command_name TEXT NOT NULL,
    instrument_id UUID REFERENCES instruments(instrument_id),
    symbol_at_request TEXT NOT NULL,
    requested_by BIGINT NOT NULL,
    requested_topic BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_detail TEXT
);

CREATE TABLE IF NOT EXISTS finding_outcomes (
    event_id UUID NOT NULL REFERENCES scan_events(event_id),
    horizon_bars INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    raw_return DOUBLE PRECISION,
    benchmark_return DOUBLE PRECISION,
    excess_return DOUBLE PRECISION,
    max_favorable_excursion DOUBLE PRECISION,
    max_adverse_excursion DOUBLE PRECISION,
    price_basis TEXT NOT NULL,
    methodology_version TEXT NOT NULL,
    PRIMARY KEY (event_id, horizon_bars, methodology_version)
);
