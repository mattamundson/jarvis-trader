# Live operator readiness audit — 2026-09-22

Scope: read-only database + HTTP probes; no live trading/risk/kill-switch mutation.

## Ledger recency
- pipeline_runs_count: `19148`
- latest_pipeline_run_created_at: `2026-09-24T13:33:36`
- approval_queue_count: `905`
- latest_approval_queue_created_at: `2026-09-18T19:13:54.244491+00:00`
- pending_trade_approvals_count: `373`
- latest_pending_trade_approval_created_at: `2026-08-11T16:03:24`
- paper_trades_count: `120`
- latest_paper_trade_entry_time: `2026-08-18T13:49:41.803391+00:00`
- latest_paper_trade_exit_time: `2026-08-18T20:45:03.151069+00:00`
- ibkr_fills_count: `6`
- latest_ibkr_fill_time: `2026-06-01 09:06:14+00:00`

## Latest pipeline decisions
- id=19148 run=707f8cc2 2026-09-24T13:33:36 MES decision=hold confidence=None status=completed
- id=19147 run=5b36117d 2026-09-23T13:32:04 MES decision=hold confidence=None status=completed
- id=19146 run=13062e15 2026-09-22T13:33:54 MES decision=buy confidence=None status=completed
- id=19145 run=39b74b70 2026-09-22T11:23:57 MES decision=buy confidence=None status=completed
- id=19144 run=645bc7c9 2026-09-22T11:23:57 SPY decision=sell confidence=None status=completed
- id=19143 run=48c54fe3 2026-09-22T11:23:55 MNQ decision=sell confidence=None status=completed
- id=19142 run=faa7f425 2026-09-22T11:21:19 QQQ decision=hold confidence=None status=completed
- id=19141 run=9a59826b 2026-09-22T11:21:16 MCL decision=hold confidence=None status=completed

## Latest approval queue rows
- id=905 2026-09-18T19:13:54.244491+00:00 MES direction=LONG confidence=0.75 status=expired expires=2026-09-18T19:43:54.244491+00:00
- id=904 2026-09-18T18:43:54.182186+00:00 MES direction=LONG confidence=0.75 status=expired expires=2026-09-18T19:13:54.182186+00:00
- id=903 2026-09-18T18:13:54.084884+00:00 MES direction=LONG confidence=0.75 status=expired expires=2026-09-18T18:43:54.084884+00:00
- id=902 2026-09-18T17:35:43.907841+00:00 MES direction=LONG confidence=0.7 status=expired expires=2026-09-18T18:05:43.907841+00:00
- id=901 2026-09-18T17:05:43.827862+00:00 MES direction=LONG confidence=0.7 status=expired expires=2026-09-18T17:35:43.827862+00:00
- id=900 2026-09-18T15:22:23.778397+00:00 MES direction=LONG confidence=0.7 status=expired expires=2026-09-18T15:52:23.778397+00:00
- id=899 2026-09-18T14:52:23.702558+00:00 MES direction=LONG confidence=0.7 status=expired expires=2026-09-18T15:22:23.702558+00:00
- id=898 2026-09-18T14:22:23.564310+00:00 MES direction=LONG confidence=0.7 status=expired expires=2026-09-18T14:52:23.564310+00:00

## Current operator conclusion
- Engine and dashboard HTTP paths are live after repair.
- Actionable board now returns quickly through the dashboard proxy.
- Recent pipeline runs exist, but no fresh approval/paper-trade/fill evidence exists in the recent period; next recovery tranche is pipeline-to-approval-to-paper execution attribution.
