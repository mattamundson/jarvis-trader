# JARVIS Dashboard + Recommendation Audit

Generated: `2026-09-12T04:43:23.113597+00:00`

> Scope: read-only evidence capture. No engine/risk/kill-switch/.env/symbol-routing changes.

## Verdict

- Operator-analysis-ready: **True**
- Monitoring-ready: **False**
- Execution-ready: **False**
- Dashboard OK: **True**
- Engine OK: **True**

### Blockers / warnings

- kill_switch_active=true
- live_trading=false
- master-api :8030 closed; master/trade-record widgets may be degraded
- MES_1h active/auth mismatch: status=ACTIVE verdict=FAIL


## Current recommendations

- Actionable shown: `0`
- Actionable raw count: `25`
- Pending approvals: `0`

## Historical paper-performance summary

- Pipeline runs: `18249`
- Closed paper trades: `91`
- Closed paper P&L: `$3181.32`
- Profit factor: `1.4211`
- Win rate: `0.3077`
- Regular-trading-hours paper entries: `62`
- Last paper entry: `2026-08-18T13:49:41.803391+00:00`

### Edge caveats

- closed ledger PF=1.4211, win_rate=0.3077, pnl=3181.32
- approved queue order_ids did not join to paper_trades; recommendation attribution is not proven
- current recommendation board is empty: actionable=0, pending=0

## Port checks

| surface | port | open |
| --- | --- | --- |
| dashboard_3010 | 3010 | True |
| engine_8010 | 8010 | True |
| ibkr_paper_4002 | 4002 | False |
| tradingview_cdp_9222 | 9222 | False |
| master_api_8030 | 8030 | False |

## Endpoint checks

| endpoint | status | ok | latency_ms | error |
| --- | --- | --- | --- | --- |
| dashboard_root | 200 | True | 1268.7 |  |
| dashboard_mission_control | 200 | True | 12.8 |  |
| engine_health_proxy | 200 | True | 2274.6 |  |
| runtime_snapshot | 200 | True | 38.5 |  |
| paper_status | 200 | True | 145.6 |  |
| pnl_truth | 200 | True | 91.5 |  |
| safety_status | 200 | True | 374.7 |  |
| portfolio | 200 | True | 31.9 |  |
| pending_approvals | 200 | True | 47.0 |  |
| actionable | 200 | True | 10945.7 |  |
| drawdown_stats | 200 | True | 98.7 |  |
| broker_status | 200 | True | 32.3 |  |
| engine_health_direct | 200 | True | 1284.0 |  |

## Paper trades by symbol

| symbol | rows | closed | open | closed_pnl | wins | losses | first_entry | last_entry |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MGC | 47 | 38 | 0 | 3905.93 | 12 | 26 | 2026-05-08T10:18:18.029656+00:00 | 2026-08-12T14:17:06.367855+00:00 |
| MCL | 1 | 1 | 0 | 100.0 | 1 | 0 | 2026-04-03T22:12:19.135111+00:00 | 2026-04-03T22:12:19.135111+00:00 |
| SPY | 4 | 4 | 0 | 6.54 | 2 | 2 | 2026-06-26T19:13:41.245316+00:00 | 2026-08-03T19:57:29.141431+00:00 |
| AAPL | 11 | 11 | 0 | -16.99 | 2 | 9 | 2026-06-15T20:24:05.530098+00:00 | 2026-08-03T16:08:17.579271+00:00 |
| QQQ | 7 | 7 | 0 | -22.9 | 2 | 5 | 2026-06-18T15:22:40.247408+00:00 | 2026-08-03T18:05:41.454232+00:00 |
| TSLA | 7 | 7 | 0 | -38.73 | 0 | 7 | 2026-06-15T23:04:29.737464+00:00 | 2026-08-03T16:08:18.768118+00:00 |
| MES | 43 | 23 | 0 | -752.53 | 9 | 13 | 2026-05-08T17:26:03.870851+00:00 | 2026-08-18T13:49:41.803391+00:00 |

## Paper trade distribution

```json
{
  "closed": 91,
  "wins": 28,
  "losses": 62,
  "breakeven": 1,
  "win_rate": 0.3077,
  "gross_profit": 10736.5,
  "gross_loss": -7555.18,
  "profit_factor": 1.4211,
  "avg_win": 383.45,
  "avg_loss": -121.86,
  "best": 3173.0,
  "worst": -1284.0
}
```

## Intraday paper-test evidence

```json
{
  "rth_entries": 62,
  "non_rth_entries": 58,
  "first_rth": {
    "trade_id": "2537898b-6748-45c2-9daa-0d09d993495e",
    "symbol": "MES",
    "entry_time": "2026-05-08T17:26:03.870851+00:00",
    "exit_time": "2026-05-08T17:39:25.600887+00:00",
    "pnl": 0.0,
    "status": "closed",
    "strategy_id": null,
    "quote_source": "legacy_unbackfilled",
    "entry_ct": "2026-05-08T12:26:03.870851-05:00"
  },
  "last_rth": {
    "trade_id": "2057bc5e-8142-4109-99e4-8502221cd78e",
    "symbol": "MES",
    "entry_time": "2026-08-18T13:49:41.803391+00:00",
    "exit_time": "2026-08-18T20:45:02.901158+00:00",
    "pnl": -1245.25,
    "status": "closed",
    "strategy_id": "config:c3ef16ed",
    "quote_source": "legacy_unbackfilled",
    "entry_ct": "2026-08-18T08:49:41.803391-05:00"
  },
  "by_symbol": {
    "MES": {
      "rows": 22,
      "closed": 13,
      "closed_pnl": -802.71,
      "first": "2026-05-08T12:26:03.870851-05:00",
      "last": "2026-08-18T08:49:41.803391-05:00"
    },
    "MGC": {
      "rows": 14,
      "closed": 13,
      "closed_pnl": -109.21,
      "first": "2026-06-11T09:06:36.163189-05:00",
      "last": "2026-08-12T09:17:06.367855-05:00"
    },
    "TSLA": {
      "rows": 6,
      "closed": 6,
      "closed_pnl": -33.73,
      "first": "2026-06-18T09:08:30.220647-05:00",
      "last": "2026-08-03T11:08:18.768118-05:00"
    },
    "QQQ": {
      "rows": 7,
      "closed": 7,
      "closed_pnl": -22.9,
      "first": "2026-06-18T10:22:40.247408-05:00",
      "last": "2026-08-03T13:05:41.454232-05:00"
    },
    "AAPL": {
      "rows": 9,
      "closed": 9,
      "closed_pnl": -15.92,
      "first": "2026-06-18T10:23:37.227520-05:00",
      "last": "2026-08-03T11:08:17.579271-05:00"
    },
    "SPY": {
      "rows": 4,
      "closed": 4,
      "closed_pnl": 6.54,
      "first": "2026-06-26T14:13:41.245316-05:00",
      "last": "2026-08-03T14:57:29.141431-05:00"
    }
  },
  "recent_examples": [
    {
      "trade_id": "73665367-1552-439c-9d7c-85533282e940",
      "symbol": "MGC",
      "entry_time": "2026-07-31T14:52:21.119624+00:00",
      "exit_time": "2026-07-31T20:45:00.367351+00:00",
      "pnl": 77.50000000000091,
      "status": "closed",
      "strategy_id": "LONG_GAP_FILL",
      "quote_source": "paper_simulator",
      "entry_ct": "2026-07-31T09:52:21.119624-05:00"
    },
    {
      "trade_id": "3e143a8a-c977-4acb-8e5b-51033afa388c",
      "symbol": "MES",
      "entry_time": "2026-08-03T16:07:48.461717+00:00",
      "exit_time": "2026-08-03T20:45:02.459669+00:00",
      "pnl": 209.5,
      "status": "closed",
      "strategy_id": "LONG_MOMENTUM",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-03T11:07:48.461717-05:00"
    },
    {
      "trade_id": "9060f589-aaac-45b1-8fd1-5651ca9bbe53",
      "symbol": "AAPL",
      "entry_time": "2026-08-03T16:08:17.579271+00:00",
      "exit_time": "2026-08-18T20:45:03.151069+00:00",
      "pnl": 2.439992675781241,
      "status": "closed",
      "strategy_id": "LONG_MOMENTUM",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-03T11:08:17.579271-05:00"
    },
    {
      "trade_id": "437d5360-515e-4597-b75b-c0dfd1b1e5d4",
      "symbol": "TSLA",
      "entry_time": "2026-08-03T16:08:18.768118+00:00",
      "exit_time": "2026-08-17T05:05:41.314040+00:00",
      "pnl": -7.737799999999993,
      "status": "closed",
      "strategy_id": "LONG_MOMENTUM",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-03T11:08:18.768118-05:00"
    },
    {
      "trade_id": "120cb2f8-2d9e-47d8-b56d-279e356bdfdb",
      "symbol": "QQQ",
      "entry_time": "2026-08-03T18:05:41.454232+00:00",
      "exit_time": "2026-08-17T05:05:40.962905+00:00",
      "pnl": -8.489399999999932,
      "status": "closed",
      "strategy_id": "LONG_MOMENTUM",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-03T13:05:41.454232-05:00"
    },
    {
      "trade_id": "da9ba79a-eadc-48c6-b468-f60c8a7dab4d",
      "symbol": "MGC",
      "entry_time": "2026-08-03T19:57:18.665068+00:00",
      "exit_time": "2026-08-03T20:45:02.433987+00:00",
      "pnl": -16.5,
      "status": "closed",
      "strategy_id": "LONG_GAP_FILL",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-03T14:57:18.665068-05:00"
    },
    {
      "trade_id": "7a51f8a4-4763-4207-97b5-ce05c5416d49",
      "symbol": "SPY",
      "entry_time": "2026-08-03T19:57:29.141431+00:00",
      "exit_time": "2026-08-18T20:45:03.116453+00:00",
      "pnl": 13.16998291015625,
      "status": "closed",
      "strategy_id": "LONG_MOMENTUM",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-03T14:57:29.141431-05:00"
    },
    {
      "trade_id": "3083f899-a8a2-42db-ac35-8155e43617c7",
      "symbol": "MES",
      "entry_time": "2026-08-05T15:56:49.009789+00:00",
      "exit_time": "2026-08-05T16:18:39.389185+00:00",
      "pnl": -80.82650000000194,
      "status": "closed",
      "strategy_id": "LONG_MOMENTUM",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-05T10:56:49.009789-05:00"
    },
    {
      "trade_id": "9d8db8fa-18a2-4dda-b0fe-d60b81ff49a9",
      "symbol": "MES",
      "entry_time": "2026-08-05T16:57:59.410811+00:00",
      "exit_time": "2026-08-05T20:13:11.707315+00:00",
      "pnl": -80.82650000000194,
      "status": "closed",
      "strategy_id": "LONG_MOMENTUM",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-05T11:57:59.410811-05:00"
    },
    {
      "trade_id": "27777ed0-e48d-4b41-96df-0e603c89f5c7",
      "symbol": "MES",
      "entry_time": "2026-08-11T16:55:53.526735+00:00",
      "exit_time": "2026-08-11T18:31:10.754821+00:00",
      "pnl": -59.0565000000006,
      "status": "closed",
      "strategy_id": "LONG_MOMENTUM",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-11T11:55:53.526735-05:00"
    },
    {
      "trade_id": "31717f9a-3ff3-4673-b7b5-9ca8e389230f",
      "symbol": "MGC",
      "entry_time": "2026-08-12T14:17:06.367855+00:00",
      "exit_time": "2026-08-12T20:45:04.669832+00:00",
      "pnl": -4.0,
      "status": "closed",
      "strategy_id": "MGC_trend_rv_filter_rank1",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-12T09:17:06.367855-05:00"
    },
    {
      "trade_id": "2057bc5e-8142-4109-99e4-8502221cd78e",
      "symbol": "MES",
      "entry_time": "2026-08-18T13:49:41.803391+00:00",
      "exit_time": "2026-08-18T20:45:02.901158+00:00",
      "pnl": -1245.25,
      "status": "closed",
      "strategy_id": "config:c3ef16ed",
      "quote_source": "legacy_unbackfilled",
      "entry_ct": "2026-08-18T08:49:41.803391-05:00"
    }
  ]
}
```

## Pipeline actions

| final_action | rows | first_run | last_run |
| --- | --- | --- | --- |
| hold | 16252 | 2026-04-05T00:52:19 | 2026-09-11T20:03:11 |
| sell | 1197 | 2026-04-10T16:26:24 | 2026-08-18T18:31:51 |
| buy | 800 | 2026-04-07T09:24:25 | 2026-08-18T16:10:42 |

## Approved queue attribution join

| symbol | approved_rows | queue_order_ids | matched_paper_trade_ids | matched_closed_pnl |
| --- | --- | --- | --- | --- |
| MES | 356 | 356 | 0 | 0.0 |
| MGC | 31 | 31 | 0 | 0.0 |

## Recommended enhancement queue

1. Dashboard readiness card: split monitoring-ready vs execution-ready, backed by this audit payload.
2. Recommendation attribution fix/report: durable join from decision/pipeline/approval to paper trade.
3. Confidence calibration: hit rate and expectancy by confidence bucket, symbol, regime, and strategy_id.
4. Master API dependency badge: visible degraded state on journal/performance pages when :8030 is closed.
5. Intraday paper scoreboard: RTH vs non-RTH P&L, independent of all-time ledger headline.
6. [safety-review] only: unify drawdown metric source and durable alert dedup.
