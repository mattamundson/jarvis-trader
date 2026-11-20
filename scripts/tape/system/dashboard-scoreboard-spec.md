# Dashboard scoreboard page — draft spec (addition-only, no PR opened)

**Status:** draft for the nightly PR routine. Do not merge without Matt’s yes.  
**Scope:** add a new page/route only. Do not remove or rearrange existing pages/panels.

## Goal

One scoreboard that answers: “Are overnight/RTH reads earning their keep?” with three panels:

1. **Call accuracy** — from `/workspace/tape/system/reports/graded_calls.json` + `hit_rates.md`
2. **Proof record** — read-only summary from existing proof-record sources (link out; do not rewrite those files here)
3. **Data freshness** — gamma age, price source age, context-file mtime, checklist missing[]

## Route / nav

- Path suggestion: `/scoreboard` (or `/reads` if `/scoreboard` collides)
- Add a single nav item: **Scoreboard**
- Page title: **Read scoreboard**

## Panel A — Call accuracy

Inputs (read-only files on the box, mirrored or fetched as the app already does for tape state):

- `calls.jsonl` count + last call ts
- `reports/graded_calls.json` → overall hit rate at +30m / +60m / session-end
- Breakdown tables: by `hour_of_night`, by `setup_type`
- Edge vs baselines: % of graded windows that `beat_no_change_baseline`, % `beat_prior_range_baseline`

UI:

- Big numbers: 30m hit rate, 60m hit rate, n graded / n incomplete
- Spark/table of last 20 calls: ts, bias, lean, hit@30, MFE, MAE
- Flag row if `data_freshness.gamma_stale` on the call

Empty state: “No graded calls yet — run `grade_calls.py`.”

## Panel B — Proof record (read-only link-through)

- Show current proof-record count / progress toward 20 setups from existing dashboard data or a read-only JSON endpoint already used elsewhere
- **Do not** write `proof-record.json` / `scored-setups.csv` / `paper-journal.md` from this page
- Link: “Open proof record” → existing page

## Panel C — Data freshness

- Gamma: `asof_ct`, age minutes, STALE badge if >60
- Price: last Yahoo/engine bar ts + src label
- Context file: mtime of `/workspace/tape/context/es-context-latest.md` (or “missing”)
- Checklist missing[] chips (red)

## Acceptance tests (for the nightly PR)

1. Page renders with fixtures when graded_calls.json is present
2. Page renders empty states when files missing (no crash)
3. Nav includes Scoreboard; existing routes unchanged
4. No deletes/renames of existing components
5. Unit test: STALE badge appears when gamma_age_min > 60
6. Copy includes “Live legal? NO, size 0” in footer of this page

## Out of scope

- Live order buttons
- Editing proof-record
- Auto-merge of the PR

## Implementation notes for cloud agent

- Prefer server components reading static JSON copied into the Next app’s `public/tape-system/` or an existing state sync path
- If sync is required, add a read-only copy step in the existing mirror routine — do not open IB/engine ports
