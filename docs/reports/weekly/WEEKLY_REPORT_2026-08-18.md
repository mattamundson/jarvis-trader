📊 JARVIS WEEKLY PRODUCTION REPORT
window: 2026-08-16 → 2026-08-18 · generated 2026-08-18 14:22

1) BACKTEST (weekly QC)
   source: deep gate_v2 verdict → PASS (core PASS / alt FAIL)
   champion params: fast=60, slow=200, atr_trail_mult=2.0, min_rv_annualized=0.0
   p(edge) 0.9968 · DSR(honest) 27 · 95th DD 4.3881% · WFO MODERATE · fixed-param PF 0.9306056898858063 · OOS trades 69 · cost catastrophic

2) FORWARD EVIDENCE (paper ledger, closed, 7d)
   LONG_MOMENTUM                      n=2   pnl=$   -16.23  win%=0.0
   unattributed                       n=1   pnl=$  -406.00  win%=0.0
   TOTAL                              n=3   pnl=$  -422.23

3) ATTRIBUTION (analyst, 7d)
   news             $    -6.80  (mean -3.4011, max_loss -6.8022)
   other            $    -3.38  (mean -1.6916, max_loss -3.3831)
   technical        $    -2.92  (mean -1.4621, max_loss -2.9242)
   fundamental      $    -2.34  (mean -1.1719, max_loss -2.3439)
   social           $    -0.77  (mean -0.3869, max_loss -0.7738)
   top |contributor|: news · 3 trades · $-422.23 window PnL

4) RISK
   max drawdown limit: 20.0% (engine MAX_DRAWDOWN_PCT)
   backtest maxDD: 4.3881% → OK
   realized-PnL DD proxy: peak $5714.51 → trough $-1881.7 (−$1981.7) [ASSUMPTION — no capital base in ledger]
   week PnL: $-422.23 · trades 3
   worst day: 2026-08-16 $-406.0
   risk_pct_used: avg 0.0% / max 0.0%
   open positions (3): AAPL(buy), SPY(buy), MES(buy)

5) LIVE MONITORING
   engine: DOWN ⚠
   week: 18 snapshots · engine-down 7 (38.9%)
   alerts: DATA LEG DOWN (ibkr_data_connected=false)×8, ENGINE DOWN (no /health response)×7
