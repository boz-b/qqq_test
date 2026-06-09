-- qqq_test initial PostgreSQL schema.
-- This migration is intentionally plain PostgreSQL. The price_bars table can
-- later be converted to a TimescaleDB hypertable without changing callers.

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    asset_class TEXT NOT NULL DEFAULT 'equity',
    exchange TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    timezone TEXT NOT NULL DEFAULT 'America/New_York',
    provider_identifiers JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    ingest_run_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    job_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS price_bars (
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    bar_seconds INTEGER NOT NULL CHECK (bar_seconds > 0),
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume NUMERIC(22, 6) NOT NULL DEFAULT 0,
    provider TEXT NOT NULL,
    adjusted BOOLEAN NOT NULL DEFAULT TRUE,
    source_hash TEXT,
    ingest_run_id BIGINT REFERENCES ingest_runs(ingest_run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, bar_seconds, ts, provider),
    CHECK (high >= low),
    CHECK (open >= 0 AND high >= 0 AND low >= 0 AND close >= 0),
    CHECK (volume >= 0)
);

CREATE INDEX IF NOT EXISTS price_bars_lookup_idx
    ON price_bars (instrument_id, bar_seconds, ts DESC);

CREATE INDEX IF NOT EXISTS price_bars_provider_ts_idx
    ON price_bars (provider, ts DESC);

-- Future TimescaleDB upgrade path, once the extension is installed:
-- SELECT create_hypertable('price_bars', 'ts', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
-- ALTER TABLE price_bars SET (
--     timescaledb.compress,
--     timescaledb.compress_segmentby = 'instrument_id,bar_seconds,provider',
--     timescaledb.compress_orderby = 'ts DESC'
-- );

CREATE TABLE IF NOT EXISTS market_events (
    market_event_id BIGSERIAL PRIMARY KEY,
    event_time TIMESTAMPTZ NOT NULL,
    market_date DATE NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('macro', 'news_summary')),
    source TEXT NOT NULL,
    source_id TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    impact TEXT,
    title TEXT NOT NULL,
    actual TEXT,
    forecast TEXT,
    previous TEXT,
    priority SMALLINT NOT NULL DEFAULT 0 CHECK (priority BETWEEN 0 AND 10),
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingest_run_id BIGINT REFERENCES ingest_runs(ingest_run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_time, kind, source, title)
);

CREATE INDEX IF NOT EXISTS market_events_date_kind_idx
    ON market_events (market_date, kind, priority DESC, event_time);

CREATE TABLE IF NOT EXISTS news_summaries (
    news_summary_id BIGSERIAL PRIMARY KEY,
    market_event_id BIGINT NOT NULL UNIQUE REFERENCES market_events(market_event_id) ON DELETE CASCADE,
    instrument_id BIGINT REFERENCES instruments(instrument_id) ON DELETE SET NULL,
    summary_text TEXT NOT NULL,
    source_attribution TEXT,
    model_provider TEXT NOT NULL DEFAULT 'gemini',
    model_name TEXT,
    candidate_count INTEGER CHECK (candidate_count IS NULL OR candidate_count >= 0),
    prompt_hash TEXT,
    response_hash TEXT,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingest_run_id BIGINT REFERENCES ingest_runs(ingest_run_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS news_summaries_generated_at_idx
    ON news_summaries (generated_at DESC);

CREATE TABLE IF NOT EXISTS features (
    feature_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    bar_seconds INTEGER NOT NULL CHECK (bar_seconds > 0),
    feature_set TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    parameters_hash TEXT,
    code_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS features_lookup_idx
    ON features (instrument_id, feature_set, feature_name, ts DESC);

CREATE UNIQUE INDEX IF NOT EXISTS features_unique_idx
    ON features (instrument_id, ts, bar_seconds, feature_set, feature_name, COALESCE(parameters_hash, ''));

CREATE TABLE IF NOT EXISTS strategy_signals (
    signal_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    signal_time TIMESTAMPTZ NOT NULL,
    strategy_name TEXT NOT NULL,
    direction SMALLINT NOT NULL CHECK (direction IN (-1, 0, 1)),
    strength DOUBLE PRECISION,
    parameters_hash TEXT,
    code_version TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS strategy_signals_lookup_idx
    ON strategy_signals (instrument_id, strategy_name, signal_time DESC);

CREATE UNIQUE INDEX IF NOT EXISTS strategy_signals_unique_idx
    ON strategy_signals (instrument_id, signal_time, strategy_name, COALESCE(parameters_hash, ''));

CREATE TABLE IF NOT EXISTS backtest_runs (
    backtest_run_id BIGSERIAL PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    instrument_id BIGINT REFERENCES instruments(instrument_id) ON DELETE SET NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    bar_seconds INTEGER CHECK (bar_seconds IS NULL OR bar_seconds > 0),
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    code_version TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS backtest_runs_strategy_created_idx
    ON backtest_runs (strategy_name, created_at DESC);

COMMENT ON TABLE price_bars IS 'Durable OHLCV bars for 1m/daily and future shorter intervals; TimescaleDB-ready via bar_seconds and ts.';
COMMENT ON TABLE market_events IS 'Macro calendar rows and AI-summarized news rows only. Do not store raw news candidates here.';
COMMENT ON TABLE news_summaries IS 'Post-AI summary records linked to market_events; raw source news is intentionally excluded.';
COMMENT ON COLUMN price_bars.bar_seconds IS 'Bar duration in seconds, e.g. 60 for 1m, 300 for 5m, 86400 for daily.';
COMMENT ON COLUMN market_events.event_payload IS 'Structured macro metadata or summary metadata; not raw provider news payloads.';
