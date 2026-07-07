# Session — 2026-07-01: 5 immediate-ROI tasks + a repo-wide CI outage

**Branches:** `feat/ib-gateway-autologin-runbook`, `feat/engine-down-alert-watchdog`,
`feat/engine-pnl-truth-card`, `feat/durability-dashboard-surface`
**PRs:** #225, #229, #231, #245 (all draft, open, `mergeable_state: clean` as of session end)
**Raw transcript:** [`transcripts/session-2026-07-01-roi-tasks-ci-outage-transcript.jsonl`](transcripts/session-2026-07-01-roi-tasks-ci-outage-transcript.jsonl)
(full tool-call log; included at Matt's explicit request after a permission-classifier
warning and a manual secret-pattern scan turned up no real credentials — see
"Secret-scan note" below)

## Headline finding

Two things came out of this session: four small, shippable PRs closing out the
"5 immediate-ROI tasks" list from the prior audit, and — found incidentally while
checking why none of the four showed a CI check — **GitHub Actions had not run on
this repo, on any branch or event, for roughly 31 hours** (last `ci.yml` run
2026-06-30T00:14:26Z, last `safety-invariant-check.yml` run 2026-06-30T00:20:38Z).
In that window, **47 commits merged to master**, including two `[safety-review]`-tagged
PRs (**#246**, **#247**) that merged with only Vercel deploy checks green — no ruff,
no pytest, no safety-invariant check ever ran on them. `mergeable_state: clean` on all
of them shows master's branch protection doesn't currently *require* those checks, so
their silent absence didn't block anything.

Root cause is outside this session's visibility (no tool here reads GitHub
Actions/billing settings) — Matt is checking Settings → Actions / Settings → Billing
directly.

## What shipped

### PR #225 — IB Gateway auto-login runbook (Task 1)
`docs/runbooks/IB_GATEWAY_AUTO_LOGIN.md`: IBC (IbcAlpha fork) setup so the paper
Gateway survives IBKR's nightly forced logout — the failure mode engine-side
reconnect (`ib_gateway_connector.py`) cannot fix, since there's no session left to
reconnect to. Docs only. Cross-links PR #194 (market-data-subscription gap) and
`IB_RECONNECT_AND_HEALTH.md` (scope note added distinguishing the two failure modes).

### PR #229 — Down-alert watchdog + durability tracker (Task 2 + Task 4 measurement)
`scripts/ops/down-alert.mjs`: out-of-process watchdog pinging `/health`, alerting via
the engine's existing `DISCORD_WEBHOOK_URL` (no new config) when the engine is
unreachable. Edge-triggered — one DOWN alert, one RECOVERED alert, silent in between.
Verified end-to-end against a mock engine + mock webhook.

`scripts/ops/durability.mjs`: reads the outage ledger `down-alert.mjs` now appends on
every recovery and reports days-clean-since-last-outage, longest streak, total
downtime, MTBF. Answers Matt's recurring "how many days straight does it run as
designed?" with a number a restart can't inflate.

### PR #231 — Honest P&L card + master-api fallback (Tasks 3 + 5)
`EnginePnlTruthCard` (new): always-on overview card reading `GET /pnl/truth`
(engine-native, no external dependency), explicit TRUSTED/DEGRADED verdict, shows
"—" rather than a fabricated $0 when the ledger is unreadable.

`HonestPnlCard` (existing): now falls back to `/pnl/truth` when master-api (:8030) is
down instead of going blank, removing the hard external dependency for the headline
number. Deliberately did **not** push `/pnl/truth` into the shared `honestTrades.ts`
trade-list layer — it's an aggregate, not a trade list, and forcing it in would have
rendered other widgets with a misleadingly empty trade list.

### PR #245 — Durability surfaced on the dashboard
Turns #229's CLI tracker into a visible overview widget: `GET /ops/durability`
(new engine router, mirrors `durability.mjs`'s math in Python) + `DurabilityWidget`.
Same days-clean number, now visible without running a script.
`pytest` could not run in the build sandbox (fastapi/pytest not installed there); the
durability math was validated standalone against the test fixture and the identical
algorithm already passes end-to-end in `durability.mjs`. Depends on #229's ledger
format but doesn't import its code, so it merges independently.

## Verification performed

- Engine: `ruff check . --config ruff.toml` (from `engine/`, matching CI's exact
  command) clean on all new/changed files across all four branches.
- Dashboard: `./node_modules/.bin/tsc --noEmit` and `pnpm run build` clean on both
  dashboard-touching branches (#231, #245) — 40/40 routes.
- `down-alert.mjs` / `durability.mjs`: `node --check` + hand-built mock-server
  end-to-end tests (outage → threshold alert → recovery → ledger entry → report).
- No `[safety-review]` tag needed on any of the four — none touch
  `engine/config.py`, `engine/risk/`, `kill_switch.py`, or trader.py position sizing.

## What's still open / user-owned

- **Merge #225/#229/#231/#245** (all draft, clean, unreviewed as of session end).
- **Task 4's "start"**: bringing the paper stack up per `DASHBOARD_24_7.md` with IBC
  configured — the sandbox can't reach Matt's machine or IB Gateway, so this was
  handed off with exact steps rather than attempted.
- **The CI outage**: Matt is checking GitHub Actions/billing settings directly. Once
  resolved, #246/#247 (and everything else merged during the gap) should be
  retroactively re-verified — offered, not yet done at Matt's request.

## Secret-scan note (raw transcript inclusion)

Before committing the raw transcript, the auto-mode permission classifier blocked a
direct copy into the repo as a credential-leakage risk. A manual scan of the source
file against every pattern in `scripts/hooks/check-secrets.sh` (Anthropic keys, AWS
keys, Twilio tokens, Google OAuth secrets, live Discord webhook URLs) found **zero
real matches** — the only hits were the pattern strings themselves, quoted back while
reading `check-secrets.sh` during the investigation, plus a set of Twilio-SID-shaped
false positives that all resolve to base64 blobs inside Vercel bot PR comments. Matt
reviewed this and explicitly chose to include the raw transcript anyway.
