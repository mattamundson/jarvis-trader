# JARVIS TRADER — Strategy Development Roadmap

> Last verified: 2026-05-23 (manual triage; prior auto-gen dated 2026-05-23 05:11 UTC)
> Source: `~/.claude/handoffs/REMAINING_WORK_REPORT_2026-05-07.md`
>
> Columns: **DONE** (git-verified or file-verified) | **AGENT** (autonomous) | **AMO** (needs Amo)

## ✅ Done

- **P1-15** — Centralize cache-selector to `_find_latest_cache()` in `_gate_v2_helpers.py`
- **P1-4** — mypy 3 real bugs: alert_manager.py annotation, main.py None-guard, inference_router missing return
- **P1-6** — 10 ruff I001 violations cleanup from peer commits
- **P2-2** — Move duplicated runner constants to `engine/backtest/_constants.py`
- **P2-3** — Extract `verdict_lifecycle.py` (archive→WFO→compare→commit workflow)
- **P2-6** — End-to-end verdict refresh test on synthetic data (500 bars, 3 windows, 5 grid combos)
- **P2-8** — Track MGC wfo + p_edge journal CSV (detect regime shifts)
- **P3-1** — Document gate v2 framework (7 criteria, math, bootstrap CI, deflated Sharpe, failure modes)
- **P3-10** — Pre-commit gate-policy snapshot test (threshold baseline; require intentional updates)
- **P3-11** — MES short-only mean-rev rank2 (final mean-rev hypothesis test; LOW expected value)
- **P3-12** — HTF-conditioned mean-rev (daily RSI confirmation)
- **P3-13** — MNQ trend rank3 with shorter periods OR macro filter
- **P3-15** — Regime detector alert (MES daily RSI <30 for 5 days OR VIX >25 sustained)
- **P3-16** — Optional hands-off monitor mode (low-cadence loop running live_readiness)
- **P3-2** — Document cache filename contract (regex + docstring + assertion + test)
- **P3-3** — Document verdict lifecycle (archive→WFO→compare→commit sequence)
- **P3-32** — Bump `restart_engine.ps1` timeout 360s → 480s
- **P3-35** — Standardize runner docstring "Usage:" line (fix CWD confusion)
- **P3-37** — Add `--alert-on-rating-drop` mode to verdict comparison
- **P3-38** — Property-based test for cache filename contract
- **P3-39** — Strategy retirement criteria (PASS→FAIL thresholds for degradation, rolling loss, large-loss streaks)
- **P3-4** — Document Hermes/OpenClaw architecture (where each lives, env wiring, failure modes, recovery)
- **P3-40** — Roadmap visualization (Kanban-style "in flight / blocked / next / done")
- **P3-43** — Tiered kill-switch escalation (soft halt → hard halt → emergency flatten)
- **P3-45** — Live-readiness gauge writes machine-readable go/no-go state file
- **P3-6** — Canonical strategy-portfolio scoreboard (auto-gen from JSONs; engine/data/_README.md)
- **P3-7** — Diversification audit on equity curves (correlation MES rank11 + MGC rank4 daily PnL)
- **P3-9** — Tighten ALT mc_dd ceiling (both PASS-alt at 0.8-1.2%; ceiling 7% generous; tighten to 4%)
- **P1-5** — TV CDP watchdog script (`Jarvis-TVCDP-Watch-30min` task verified Ready)
- **P1-7** — Tests for 3 unawaited coroutine fixes (`test_unawaited_coroutine_fixes.py` — 10 tests)
- **P1-8** — `test_calibration_full_warmup_sets_ready_flag` verified passing (62s, 1 passed)
- **P1-10** — `Jarvis-LiveReadiness-Daily` task verified Ready (first run successful)
- **P1-14** — Cache filename contract test (`tests/test_cache_filename_contract.py` — 41 tests)
- **P2-1** — Cache-selector centralized: 35/37 runners use `_find_latest_cache`; 2 legitimate exceptions
- **P2-4** — Dashboard `/health` widget (`EngineHealthWidget.tsx` — TV MCP, LLM, IBKR dots, 15s poll)
- **P2-5** — Property-based verdict drift tests (`89bbc6a` — 16 Hypothesis tests)
- **P2-7** — Live readiness 7-criteria smoke tests (`test_live_readiness.py` — 36 tests)
- **P2-19** — Parallel agent deployment pattern (`~/.claude/rules/agent-deployment.md` complete)
- **P2-20** — Handoff INDEX.md exists at `~/.claude/handoffs/INDEX.md`
- **P2-21** — `.gitattributes` CRLF normalization (`* text=auto eol=lf`, `*.ps1 text eol=crlf`)
- **P2-22** — Pre-commit mypy hook scoped to `engine/backtest/` (`6cfc42d`)
- **P2-23** — pytest invocation wrapper (`~/scripts/jarvis-test.ps1` — smoke/full/coverage/keyword modes)
- **P2-25** — AskUserQuestion + hook interaction documented in `~/.claude/CLAUDE.md`
- **P2-29** — HERMES_RUNBOOK.md reference in CLAUDE.md hooks section
- **P3-5** — 1P naming convention documented in `~/.claude/rules/secret-1p-naming.md`
- **P3-27** — Memory file weekly trim (`~/scripts/memory-trim.ps1` verified exists)
- **P3-30** — HEREDOC pattern standardized in `~/.claude/rules/git-hygiene.md`
- **P3-31** — pyarrow ImportError resolved (pyarrow imports cleanly in engine venv)
- **P3-34** — Typed VerdictSchema Pydantic model (`2679db5` — 19 tests against real verdict files)
- **P3-36** — `ThresholdConfig` YAML-loadable per-symbol in `compare_verdicts.py`
- **P3-44** — Database backups committed (`2afef84`)
- **P3-46** — `is_strategy_authorized()` unifies VALIDATION_ONLY + paper_config + gate v2 verdict
- **P3-47** — Agent prompt forbidden-commands list in `rules/agent-deployment.md` template
- **P3-49** — `~/.coldstore` naming in place; `~/.archive` removed
- **P2-12** — Credential-guard hook tightened for `python -c` args (obfuscated-path + code-loading checks; 9/9 smoke tests; `895029b`)
- **P2-14** — Cred-rotation audit trail script (`~/scripts/cred-rotation-audit.ps1`; CSV at `~/.claude/audit/cred-rotation-audit.csv`; `ec4c812`)
- **P2-30** — `hermes-safe-restart.sh` verified at `/root/.hermes/bin/` (stream detection + systemctl; pre-existed)

## 🤖 Agent-Doable (open, sorted by estimate)

| ID | Task | Estimate |
|----|------|---------|
| P0-5 | Verify `/health` post-restart (status=ok, ibkr_execution, tv_mcp, llm_path) | 5 min |
| P2-9 | Engine alert wiring smoke test (trigger failure, wait for notification, confirm) | 30 min |
| P3-23 | dp600-stark-v2 pre-commit hook (husky + lint-staged) | 30 min |
| P3-28 | Auto-generated cross-linking between handoffs (INDEX.md auto-populated) | 1 hr |
| P3-29 | Session-coordination lockfile for shared files | 1-2 hr |
| P3-48 | Pre-flight permission gates (destructive ops require "PROPOSING_DESTRUCTIVE_OP" line) | harness-level |
| P0-3 | `ibkr_execution_connected=false` regression diagnostic | 30-60 min |
| P2-13 | Pre-stage Wave 2 1P items (B2-B6 closure) — YAML inventory + pre-flight validation | 1.5 hr |
| P2-18 | CV pipeline cv.md → DOCX automated build (eliminate drift) | 1 hr |
| P3-19 | Lighthouse Perf 63 → 90 on dp600-stark-v2 | 2-4 hr |
| P3-20 | dp600-stark-v2 README + CONTRIBUTING + ARCHITECTURE docs | 2-3 hr |
| P3-21 | dp600-stark-v2 80% coverage threshold gate | 1 hr |
| P3-22 | dp600-stark-v2 E2E suite (Playwright dashboard → quiz → grade flow) | 4-6 hr |
| P3-8 | Re-validate gate v2 thresholds (realized FDR from trial multiplicity) | 3-4 hr |
| P3-14 | Pivot symbol expansion: VIX-conditional MES OR MES options income | 4-6 hr each |
| P3-26 | restart_engine.ps1 false-positive WARN behavior verification (3-5 more cycles) | passive |

## 👤 / ⚠️ Amo-Gated (open)

| ID | Class | Task | Estimate |
|----|-------|------|---------|
| P0-1 | ⚠️ | Engine restart (load late-session commits) | 5 min |
| P0-2 | 👤 | Polygon key rotation + delete `.env.LIVE-TRADING-DANGER-...` | 10 min |
| P0-4 | 👤 | Anthropic credit top-up (unblocks LLM, Hermes, social_analyst) | 5 min |
| P1-1 | 👤 | DP-600 baseline `/simulation-v2` (65 Q / 100 min, dp600-realism mode) | 100 min |
| P1-11 | 👤 | Restart TradingView Desktop (TV CDP socket hung at app layer) | 5 min |
| P1-13 | 👤 | Wave 2 ambiguity resolution (B2-B6: webhooks, Telegram naming, Jarvis-Internal, Cursor/Supermemory/Firecrawl) | 30 min |
| P1-2 | 👤 | Send Anna Kisting email (Draft 1 ready) | 5 min |
| P1-3 | 👤 | Phase 0 Wave 1 credential rotation (T1 re-verify, T2, T5, T3, GitHub PAT) | 2h 45m |
| P1-9 | ⚠️ | Add `Jarvis-EngineHealth-Hourly` task (optional auto-restart, cap 3/hr) | 30 min |
| P2-10 | ⚠️ | PM2 restart count alert (`Jarvis-PM2RestartWatch-15min`, alert on >5/hr) | 30 min |
| P2-11 | 👤 | Migrate `engine/.env` to 1P-CLI-load (removes plaintext creds; requires `op signin` at boot) | 2-4 hr |
| P2-15 | ⚠️ | Periodic key-rotation reminder (`Jarvis-RotationReminder-Weekly`) | 1 hr |
| P2-16 | ⚠️ | master-jarvis archive execution (gated on .secrets/keys.env rotation) | 30-60 min |
| P2-17 | ⚠️ | jarvis-trader-Copy/ scrub (gated on Phase 0 cred rotation) | 15 min |
| P2-24 | ? | C1 paper validation natural pass (12/30 closed; ~2026-06-15) | time-only |
| P2-26 | 👤 | Pre-add `.claude/settings.local.json` push-allow rule (remove future friction) | 5 min |
| P2-27 | 👤 | Hermes systemd unit (`hermes gateway install`) — survives wsl --shutdown | 15 min |
| P2-28 | 👤 | Hermes `gateway setup` for Telegram/Discord/WhatsApp messaging platforms | 30 min |
| P2-31 | 👤 | Update Hermes git (`/home/mattm/.hermes/hermes-agent/` is 379 commits behind origin/main) | 20 min |
| P3-17 | 👤 | Audit-log review for Wave 1 keys (anytime within 30 days) | 45 min |
| P3-18 | 👤 | Phase 0 Wave 2 (after B2-B6 ambiguities resolved) | 30-45 min browser |
| P3-24 | 👤 | OpenClaw vs Twilio decision for messaging-platform second leg | 30-60 min |
| P3-25 | 👤 | TWS-support push scope (just `0cf2f26` or full branch?) | decision |
| P3-33 | 👤 | Validate `jarvis-quant-venv` kernel via tutorial → retire conda `jarvis` | 15 min |
| P3-41 | 👤 | Define "live trading" explicitly (initial capital, symbols, risk caps, review cadence, expansion/pause) | 1 hr (Amo decisions) |
| P3-42 | 👤 | Document $250/day → $1M scaling roadmap (tier transitions $250 → $500 → $1K → $5K → $1M) | 1-2 hr (Amo) |
| P3-50 | 👤 | dp600-stark-v2 post-exam phases (per long-term roadmap §3.5 of dp600 doc) | months |

## Summary

| Stat | Count |
|------|-------|
| Total tasks | 103 |
| Done (verified) | 60 |
| Open agent-doable | 16 |
| Open Amo-gated | 27 |
| Remaining | 43 |

Run `backtest/gen_scoreboard.py` to refresh the strategy verdict table.
