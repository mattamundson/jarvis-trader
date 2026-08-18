-- JARVIS TRADER — PostgreSQL Schema
-- Auto-executed on first docker compose up
-- Tables: orders, trades, agent_decisions, portfolio_snapshots, alerts

-- ── Orders ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          VARCHAR(20) NOT NULL,
    quantity        INTEGER NOT NULL,          -- positive=buy, negative=sell
    order_type      VARCHAR(20) NOT NULL,      -- market, limit, stop, stop_limit
    limit_price     DECIMAL(15, 4),
    stop_price      DECIMAL(15, 4),
    is_futures      BOOLEAN DEFAULT FALSE,
    is_options      BOOLEAN DEFAULT FALSE,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, submitted, filled, cancelled, rejected
    broker          VARCHAR(20),               -- ibkr, schwab
    broker_order_id VARCHAR(50),
    fill_price      DECIMAL(15, 4),
    fill_quantity   INTEGER,
    commission      DECIMAL(10, 4),
    pnl             DECIMAL(15, 4),
    -- Decision provenance
    triggered_by    VARCHAR(50),               -- which agent triggered this
    signal_score    DECIMAL(5, 4),             -- the signal that triggered it (-1 to 1)
    approved_by     VARCHAR(50),               -- 'human', 'fund_manager_auto', etc.
    notes           TEXT
);

CREATE INDEX idx_orders_symbol ON orders(symbol);
CREATE INDEX idx_orders_created_at ON orders(created_at);
CREATE INDEX idx_orders_status ON orders(status);

-- ── Agent Decisions (full provenance log) ────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_decisions (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_name      VARCHAR(50) NOT NULL,      -- technical_analyst, trader, risk_manager, etc.
    symbol          VARCHAR(20),
    timeframe       VARCHAR(10),
    signal          DECIMAL(5, 4),             -- -1.0 to 1.0
    confidence      DECIMAL(5, 4),             -- 0.0 to 1.0
    reasoning       TEXT,                      -- full LLM reasoning
    indicators      JSONB,                     -- raw indicator values
    model_used      VARCHAR(50),
    tokens_used     INTEGER,
    latency_ms      INTEGER,
    order_id        BIGINT REFERENCES orders(id)
);

CREATE INDEX idx_agent_decisions_agent ON agent_decisions(agent_name);
CREATE INDEX idx_agent_decisions_symbol ON agent_decisions(symbol);
CREATE INDEX idx_agent_decisions_created_at ON agent_decisions(created_at);

-- ── Portfolio Snapshots (from broker API, not agents) ────────────────────
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source          VARCHAR(20) NOT NULL,      -- ibkr, schwab
    total_equity    DECIMAL(15, 4),
    cash_balance    DECIMAL(15, 4),
    unrealized_pnl  DECIMAL(15, 4),
    realized_pnl    DECIMAL(15, 4),
    daily_pnl       DECIMAL(15, 4),
    margin_used     DECIMAL(15, 4),
    margin_available DECIMAL(15, 4),
    positions       JSONB                      -- [{symbol, qty, avg_cost, mkt_value, pnl}]
);

CREATE INDEX idx_portfolio_snapshots_at ON portfolio_snapshots(captured_at);

-- ── Safety Events ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS safety_events (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type      VARCHAR(50) NOT NULL,      -- kill_switch_activate, kill_switch_deactivate, order_rejected, etc.
    reason          VARCHAR(100),
    details         JSONB,
    resolved        BOOLEAN DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    resolved_by     VARCHAR(50)
);

-- ── Alerts ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level           VARCHAR(10) NOT NULL,      -- info, warning, critical
    title           VARCHAR(200) NOT NULL,
    body            TEXT,
    source          VARCHAR(50),               -- which agent/system
    acknowledged    BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ
);

-- ── Performance Summary (materialized, updated daily) ────────────────────
CREATE TABLE IF NOT EXISTS performance_daily (
    trade_date      DATE PRIMARY KEY,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    losing_trades   INTEGER DEFAULT 0,
    gross_pnl       DECIMAL(15, 4) DEFAULT 0,
    net_pnl         DECIMAL(15, 4) DEFAULT 0,
    commissions     DECIMAL(10, 4) DEFAULT 0,
    max_drawdown    DECIMAL(5, 4) DEFAULT 0,
    sharpe_ratio    DECIMAL(8, 4),
    equity_eod      DECIMAL(15, 4)
);

-- Seed: Mark system as initialized
INSERT INTO alerts (level, title, body, source)
VALUES ('info', 'JARVIS TRADER initialized', 'Database schema created successfully', 'system');
