# Frozen /tape fixture snapshots

These payloads are FROZEN source snapshots for the /tape truthfulness tests. Tests must never
read live state files (`C:\Users\mattm\tape\state\flow-latest.json`, JarvisBox exports); if a
fixture needs replacing, freeze a new copy here and note the provenance below.

Provenance:

- `tape-idle-market-closed-20261107.json` — captured 2026-11-07 ~01:11 CT (Saturday, Globex
  closed since Fri 16:00 CT). Body base: `reports/dashboard/api_flow_tape_20261107.json`
  (audit lane `jarvis-audit-20261107`, read-only GET of `/api/flow/tape` on the serving build),
  with the NEW response contract fields (`recorder`, `marketState`, `todayCt`,
  `globexTradingDate`) filled from the recorder's own raw state file at the same time
  (`state: "idle (outside window)"`, `heartbeat_age_s: 5.5`, `last_tick_age_s: null`,
  `session.trading_day: "2026-11-07"`, `levels_source: "tape-config (tape-plan dated
  2026-11-06, not today 2026-11-07 CT)"`). Not synthetic: prices genuinely null (market closed).
- `tape-live-plan-current-ok.json` — SYNTHETIC (constructed for tests, clearly not a capture):
  a Monday 2026-11-09 12:00 CT live snapshot with a same-date plan and recorder levels source
  agreeing, so the usable-plan path can be exercised without waiting for RTH.
- `tape-live-plan-conflict-20261109.json` — SYNTHETIC: same live shape but the recorder's
  `levels_source` names a plan dated 2026-11-10 while the dashboard plan is dated 2026-11-09,
  exercising the explicit-conflict (never auto-resolve) path.

Market-state labels in fixtures derive from the CME ES Globex weekly schedule (Sun 17:00 CT -
Fri 16:00 CT, daily break 16:00-17:00 CT); holiday calendars are not accounted.
