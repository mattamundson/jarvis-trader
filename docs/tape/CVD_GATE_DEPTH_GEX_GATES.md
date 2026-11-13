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

## 5. Claude read (`claude-read-latest.json`)

The `/tape` page polls `GET /api/tape/claude-read` and shows a read-only Claude read panel.
The route reads one file, `claude-read-latest.json`, from the tape state folder:

- `TAPE_STATE_DIR` when that environment variable is set
- otherwise `~/tape/state`
- on the trading PC that folder is `C:\Users\mattm\tape\state`

A missing file or malformed JSON is reported on the panel. The route does not throw, and it does not write.

The parser is an allow-list. Only the fields below are kept. Any other key is dropped, including `r`, `R`, `pnl`, `pl`, `fill`, `position`, and `account`. A string that contains `$`, `P&L`, `pnl`, `unrealized`, `realized`, `buying power`, or `net liq` is dropped. Prices in the file are index levels, not dollar amounts, and the panel does not render a dollar sign. Every trigger on the panel, and every `/tape` plan trigger, is labeled `signal, not a fill`.

`kind`, `direction`, `status`, and `gamma.regime` are lowercase enums.

```json
{
  "version": 1,
  "written_at": "2026-11-12T08:05:00-06:00",
  "source": "claude",
  "kind": "plan",
  "context": {
    "prior_sessions": [
      {"date": "2026-11-11", "close": 7640.5, "low": 7600.0, "close_note": "IB close stand-in, not CME settle"}
    ],
    "vix_regime": "string",
    "event_implied_move": "string",
    "gamma": {"regime": "short", "flip": 7660.75, "pin": 7676, "as_of": "2026-11-12T07:50:00-06:00"},
    "stale": ["string"]
  },
  "bias": "string",
  "plan": "string",
  "levels": [{"price": 7629, "label": "string"}],
  "triggers": [
    {"name": "string", "level": 7635.5, "direction": "above", "closes_needed": 2, "closes_seen": 0, "status": "armed"}
  ],
  "note": "string",
  "live_legal": "NO, size 0"
}
```

- `version` must be `1`.
- `written_at` is an ISO-8601 timestamp with an offset. The panel prints it in America/Chicago.
- `kind` is `plan`, `read`, or `close`.
- `direction` is `above` or `below`.
- `status` is `armed`, `signal`, or `invalidated`.
- `gamma.regime` is `long`, `short`, or `neutral`.
- A copy-paste example lives at `docs/tape/claude-read-latest.example.json`.

Stale badge:

- During RTH, Monday–Friday 08:30–15:00 America/Chicago inclusive, the read is stale when `written_at` is more than 60 minutes before the server clock, or when it is in the future.
- Outside that window, including the weekday overnight session and the weekend, the read is stale when its Globex trading day is not the current Globex trading day. That day is the Chicago calendar date, rolled forward at 17:00 CT (Sunday 17:00 already belongs to Monday). Age alone does not stale the file outside RTH.
- Gamma `as_of` is shown with its age and flagged when that age is more than 60 minutes, the timestamp is missing, or it is unparseable. That flag is independent of the written_at badge.
- The panel recomputes both ages from the timestamps on each poll, including a failed poll. A failed poll never leaves the badge on CURRENT: the read is STALE when the rule above says so, and otherwise the badge is REFRESH FAILED until a poll succeeds.

The plan trigger on the same page (long and short in `config/tape-plan.json`) confirms only after two consecutive completed 5-minute closes beyond the level. One close leaves the side ARMED. That status is a signal, not a fill.
