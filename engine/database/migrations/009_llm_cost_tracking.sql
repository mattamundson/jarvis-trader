-- Migration 009: LLM Cost Tracking per Pipeline Run
-- Creates pipeline_llm_costs table to track token usage and estimated costs
-- for each LLM call within a pipeline run.

CREATE TABLE IF NOT EXISTS pipeline_llm_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

CREATE INDEX IF NOT EXISTS idx_llm_costs_run_id ON pipeline_llm_costs(run_id);
CREATE INDEX IF NOT EXISTS idx_llm_costs_created_at ON pipeline_llm_costs(created_at);
