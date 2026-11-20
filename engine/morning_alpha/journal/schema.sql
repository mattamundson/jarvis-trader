CREATE TABLE IF NOT EXISTS morning_alpha_strategy_versions (
    strategy_id TEXT NOT NULL,
    version TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (strategy_id, version)
);

CREATE TABLE IF NOT EXISTS morning_alpha_signal_candidates (
    candidate_id UUID PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    payload JSONB NOT NULL,
    provider_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (strategy_id, strategy_version)
        REFERENCES morning_alpha_strategy_versions(strategy_id, version)
);

CREATE TABLE IF NOT EXISTS morning_alpha_signal_events (
    event_id UUID PRIMARY KEY,
    candidate_id UUID NOT NULL REFERENCES morning_alpha_signal_candidates(candidate_id),
    event_type TEXT NOT NULL CHECK (event_type IN ('trade_plan','rejection','outcome')),
    recorded_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_morning_alpha_candidates_as_of
    ON morning_alpha_signal_candidates(as_of, symbol);
CREATE INDEX IF NOT EXISTS ix_morning_alpha_events_candidate
    ON morning_alpha_signal_events(candidate_id, recorded_at);
