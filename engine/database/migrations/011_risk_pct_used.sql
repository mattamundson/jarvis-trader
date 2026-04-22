-- Migration 011: Layer 5 conviction-aware position sizing
-- Adds 'risk_pct_used' column to paper_trades table to track the actual
-- risk percentage used for each trade, computed from signal conviction
-- (bias, regime, structure_position alignment).
-- Nullable for backward compatibility with existing trades.

ALTER TABLE paper_trades ADD COLUMN risk_pct_used REAL;
