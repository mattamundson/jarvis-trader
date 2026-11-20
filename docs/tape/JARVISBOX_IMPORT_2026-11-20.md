# JarvisBox import — 2026-11-20

`C:\Users\mattm\JarvisBox` is the local mirror of the cloud "box" agent workspace
(`/workspace`, `/home/box`), synced 2026-11-06 → 2026-11-19. 4,357 files / 17.6 GB, of which
17.2 GB is a personal pictures backup. This doc records what was pulled into the repo, and why
the rest was not.

## Imported (this PR)

| Box path | Repo path | Notes |
|---|---|---|
| `workspace/tape/system/**` | `scripts/tape/system/` | ES read system: call log + grader, 15m-close bias gate, pre-read checklist, overnight analogs, event (NFP/CPI/FOMC) move stats. Paper/read-only, never places orders. |
| `workspace/tape/system/regime/**` | `scripts/tape/system/regime/` | Balance-vs-trend day classifier: labels, features, walk-forward backtest, 0–10 pre-open score. 992 RTH sessions. See `regime/findings.md`. |
| `workspace/tape/context/build_context.py` | `scripts/tape/context/build_context.py` | Builds `es-context-latest.md` (IB read-only historical on 4001 + GEX + calendar). Its output is consumed by `checklist.py` and `regime_score.py`. |
| `workspace/tape/context/es-context-20261106-0007.md` | `scripts/tape/system/regime/tests/fixtures/` | Frozen pre-NFP context that `findings.md` scores (display 5). |
| `workspace/tape/lessons.md` | `docs/tape/ES_TAPE_LESSONS.md` | Per-session tape lessons (2026-10-27 → 2026-11-12). |

### Changes made during the port (behaviour otherwise unchanged)

1. Hardcoded `/workspace/tape/...` paths are now resolved through `TAPE_ROOT`, which defaults to
   `scripts/tape` in the repo. On the box, set `TAPE_ROOT=/workspace/tape`.
2. All `read_text()`/`write_text()` calls take an explicit `encoding="utf-8"`. Without it,
   `grade_calls.py` crashed on Windows (cp1252 could not encode `→`).
3. `regime/tests/test_regime_score.py` reads a frozen fixture instead of the mutable
   `context/es-context-latest.md`. Its assertions are pinned to 2026-11-06.

Verification: `pytest tests regime/tests` → 27 passed (engine venv, Windows). Smoke-ran
`checklist.py`, `bias_gate.py --demo`, `grade_calls.py`, `analogs.py`, `event_stats.py`,
`regime/regime_score.py` against a scratch `TAPE_ROOT` copy: all exit 0. Committed data and report
files are byte-identical to the box snapshot.

Not CI-gated: `ci.yml` only lints and tests `engine/`.

## Already on GitHub (no action)

- `workspace/pr-fixes/files/*`: byte-identical to what is on the PR branches
  `cursor/es-chart-with-overlays-b181` (#1008) and `cursor/footprint-freshness-badges-980d` (#1009).
  Both PRs are OPEN and all their checks are green as of 2026-11-20.

## Open, deliberately not applied

- `workspace/tape/sync/push_flow_bidask.patch` (`push_flow.py` 188 → 325 lines): adds bid/ask-at-price
  from the local tick recorder for the #1009 footprint page. It was not applied for three reasons:
  (a) it hardcodes the `ESZ6_*.csv` contract, which goes stale at the December roll;
  (b) there are already six `push_flow.py` copies on the PC in two divergent lineages (188 and 372 lines);
  (c) no pusher process was running at import time, so its runtime behaviour could not be checked.
  It needs a dedicated PR with a live check of the pusher.

## Not imported (by design)

| Box content | Reason |
|---|---|
| `paper-journal.md`, `strike-log.md`, `study-grades.csv`, `scored-setups.csv` | Personal trading/discipline records. This repo is **public**. |
| `x-bookmarks-scout/` | Dated third-party levels, mostly non-trading. `docs/research/bookmark-edge-scan-*` already covers this. |
| `zscore/` | Outputs only (QQQ z-score paper tracker log). The generating code is not in the mirror. |
| `tape/state`, `ovn`, `databento`, `site`, `flow`, `addons/cache` | Live, regenerated market-data mirrors. |
| `hp-pictures-backup-*`, `erpr21xx`, `runtime-automation`, `confluence-*`, `hp-erp`, `interview-lab` | Not JARVIS TRADER. |
| `chat-archive`, `grokbot-history`, `alfred`, `home/box/agent-data` | Agent transcripts and blobs. |
| `.incoming`, `.tapesync`, `transfer_*` | Transfer plumbing. |
