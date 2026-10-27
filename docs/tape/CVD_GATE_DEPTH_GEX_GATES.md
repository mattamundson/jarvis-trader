# /tape: CVD gate, L2 depth, GEX producer, Hermes gates

Paper only. Live legal? NO, size 0. The public page and API show levels and gates only, never dollars, R, P&L, positions or account data.

## 1. CVD gate (`cvd_gate.mode = "z30"`)

The tick recorder resets CVD to 0 in each CT trading-day file, so a fixed CVD level (the old 540) has no stable meaning.
The z30 rule does not use the origin at all.

- `d30` = trailing 30-minute change in session CVD (calendar minutes, gaps forward-filled).
- `scale` = zero-centred RMS of the rolling `d30` samples over the last `lookback_min` (240) minutes of the session.
- `z = d30 / scale`.
- Side: `above` if `z >= z_thr` (1.0), `below` if `z <= -z_thr`, else `at`. Lean (the bias vote) is the sign of `d30`.
- `state = "warming"` until `min_samples` (60) rolling samples exist (about 90 minutes into a session) or while `scale` is 0.
  A warming gate casts no bias vote and the page says so.
- `level` is the CVD 30 minutes ago and `dist` is `d30`, so existing consumers keep working.
- `mode: "fixed"` keeps the old rule (`level`) for back-compat. Config in `~/tape/state/tape-config.json` deep-merges over defaults.

Tests: origin-shift invariance, mirror symmetry, warming and flat series, gap fill, bias vote (`scripts/tape/test_flow_snapshot.py`).

## 2. L2 / DOM depth

- `es_tick_recorder/depth_recorder.py` lives next to `tick_recorder.py` (outside the repo, in `C:\Users\mattm\es_tick_recorder`). Own IB clientId 99, own lock port 47099, read-only (`reqMktDepth`, 10 rows, no orders). The live tick recorder is not touched.
- Writes about 1 row per second to `<data>/ESZ6_depth_YYYYMMDD.csv` (`ts_utc, nb, na, bp1..10, bs1..10, ap1..10, as1..10`) and `depth-status.json`.
- If IB refuses depth (codes 309, 310, 317, 354, 10089, 10090, 10186, 10187, 10190, 10285) or no rows arrive, status becomes `no_permission` and it retries every 10 minutes. The panel shows that state.
- `flow_snapshot.py` reads the tail of the CSV: `imb_top`, `imb_5`, `imb_10` = (bid lots - ask lots) / (bid + ask), `imb_avg` = mean `imb_5` over the last 60 snapshots, plus `big` = levels at least `max(100, 3 x median)` lots (top 6, with how many seconds they have been resting). Lots only.
- Repeated price rows are merged into one rung per price. Resting size can be pulled, so treat it as context, not a trigger.

## 3. GEX producer (`scripts/tape/gex_producer.py`)

Reads the public ZeroGEX ES page (delayed about 15 minutes) and writes `gex-latest.json`. As-of is the vendor snapshot time. Flip, call wall, put wall, max pain, net GEX, flip velocity (pts/hr over up to 120 minutes). `pin` is not published, so it is null. Stale after 35 minutes. On a failed fetch the last good levels are kept with `fetch_ok: false`.
Scheduled task "Tape GEX Producer (ZeroGEX, delayed)": Mon-Fri every 10 minutes from 07:00 CT for 10 hours.

## 4. Hermes gates (`scripts/tape/hermes_gates_bridge.py`)

Hermes writes no `gates.md`. The bridge reads Hermes's pre-market readiness report and approved safety record (read-only) and writes a sanitised `<tape state>/gates.md` with allow-listed names and a pass / warn / fail word only. A report that is not from today shows as WARN with its age, and no lockout line is written. `readHermesGates` now also looks in the tape state dir.
Scheduled task "Tape Hermes Gates Bridge": Mon-Fri every 30 minutes from 06:30 CT.
