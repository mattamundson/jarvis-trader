# JARVIS Recommendation Baseline Comparison

Generated: `2026-09-12T08:49:50.403936+00:00`

> Scope: read-only comparison from attribution report JSON. No engine/risk/kill-switch/broker/.env/symbol-gate changes.

## Verdict

- `linked_outperformed_unlinked_pnl`: **True**
- `linked_outperformed_all_paper_avg_trade`: **True**
- `queue_order_lineage_proven`: **False**
- `edge_certified`: **False**

## Cohorts

| Cohort | Closed | P&L | Avg/trade | Win rate | PF | Wilson 95% win-rate |
|---|---:|---:|---:|---:|---:|---|
| all_paper | 91 | $3181.32 | $34.96 | 0.3077 | 1.4211 | 0.2223–0.4087 |
| all_unique_linked | 42 | $4758.66 | $113.30 | 0.3333 | 2.3703 | 0.2101–0.4845 |
| unlinked | 49 | $-1577.34 | $-32.19 | 0.2857 | 0.6136 | 0.1785–0.4241 |
| rth_linked | 18 | $1885.33 | $104.74 | 0.4444 | 5.9318 | 0.2456–0.6628 |
| queue_order_id_matched | 0 | $0 | $None | None | None | None–None |

## Comparisons

### linked_vs_all_paper
- `pnl_delta`: 1577.34
- `avg_trade_delta`: 78.34
- `win_rate_delta`: 0.0256
- `profit_factor_delta`: 0.9492

### linked_vs_unlinked
- `pnl_delta`: 6336.00
- `avg_trade_delta`: 145.49
- `win_rate_delta`: 0.0476
- `profit_factor_delta`: 1.7567

### rth_linked_vs_all_paper
- `pnl_delta`: -1295.99
- `avg_trade_delta`: 69.78
- `win_rate_delta`: 0.1367
- `profit_factor_delta`: 4.5107

### queue_order_matched_vs_all_paper
- `pnl_delta`: -3181.32
- `avg_trade_delta`: -34.96
- `win_rate_delta`: -0.3077
- `profit_factor_delta`: -1.4211

## Interpretation

Linked trades outperformed the unlinked cohort in this historical ledger, but queue-order lineage remains unproven and `edge_certified=false`. Treat this as prioritization evidence, not a production trading edge certificate.
