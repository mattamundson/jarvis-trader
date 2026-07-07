# Handoff — TradingView MCP + Gamma Levels + Kraken Integration

**Session date:** 2026-04-16 (Thursday)
**Session window:** ~17:52 CT → 19:35 CT (approx 1h45m)
**Model:** claude-opus-4-7 (1M context)
**Working directory:** `C:\windows\system32` (launched from system32; all repo work done via absolute paths)
**Target repo:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\`
**Remote:** `https://github.com/mattamundson/jarvis-trader.git`
**Output branch:** `feat/tradingview-mcp-gamma-kraken`
**Open PR:** <https://github.com/mattamundson/jarvis-trader/pull/2>

---

## 1. Session summary — what was accomplished, in what order

The user requested integration of four external resources into jarvis-trader:

1. `https://github.com/tradesdontlie/tradingview-mcp` (TradingView MCP server)
2. `https://x.com/milesdeutscher/status/2044536031991763414` (tweet content unknown at start)
3. `https://www.tradingview.com/script/Wtxy5arU-MY-FREE-GAMMA-LEVELS/` (closed-source Pine Script overlay by TheRealDrip2Rip)
4. `https://github.com/krakenfx/kraken-cli` (Rust CLI for Kraken spot/futures)

### Phase 1 — Planning (plan mode)
- Read plan-mode system reminder, created plan file at `C:\Users\mattm\.claude\plans\https-github-com-tradesdontlie-tradingvi-hazy-willow.md`.
- Launched 2 parallel Explore agents (haiku, per token-efficiency rule) to map the jarvis-trader TradingView + crypto integration surfaces.
- Launched 4 parallel WebFetch calls for the external URLs. Three succeeded (tradingview-mcp, kraken-cli, Gamma Levels script description). X.com returned 402 (auth wall); retried via `firecrawl-scrape` skill (out of credits) and then Playwright MCP `browser_navigate` + `browser_evaluate` which successfully extracted the tweet body.
- **Key discovery from exploration:** `tradingview-mcp` is already cloned at `jarvis-trader/tradingview-mcp/`, already registered in `.mcp.json`, and a 626-line `engine/data/tv_indicator_bridge.py` already reads it with a manifest + 14-indicator fallback pattern. So Track 1 is extension-only, not new-install.
- **Key discovery on the tweet:** It's a walkthrough guide for `tradesdontlie/tradingview-mcp`. Collapses into Track 1 as documentation — not a separate feature. Captured two artifacts: canonical install prompt and `tv_health_check` validation tool.
- **Key discovery on Gamma Levels:** Source is closed. Chose "Path A" (chart-overlay passthrough via MCP `get-pine-labels`) over "Path B" (build own GEX calculator on Polygon options). User confirmed this decision.
- **Key discovery on Kraken:** Ships a built-in MCP server and a paper-trading engine. `MarketModule` ABC already exists for broker-agnostic trading. User confirmed: paper-first + live-flagged path, MCP + Python adapter both wired.

Plan file was iteratively refined across multiple edits, then `ExitPlanMode` requested approval.

### Phase 2 — Implementation (auto mode)
User approved plan + auto mode. Executed 14 tasks in this order:

**Track 1: TradingView MCP setup (T1)**
- Wrote `docs/tradingview-mcp-setup.md` with Miles's install prompt, Chrome `--remote-debugging-port=9222` requirement, `tv_health_check` validation, load instructions for the gamma indicator.

**Track 2: Gamma Levels (T2a–T2e)**
- T2a/T2b: Extended `TVIndicatorSnapshot` with 7 new fields (gex_flip, call_wall, put_wall, hvl, vol_trigger_up, vol_trigger_down, max_pain). Added `_parse_gamma_levels` static method with alias matching (`_GAMMA_ALIASES` table) and 2-tier value resolution (prefer `label.price`, fallback to regex on text). Added `_enrich_with_gamma` helper invoked from `get_snapshot` for both manifest + individual fallback paths.
- T2c: Flattened the 7 fields into `tradingview_feed.get_all_indicators` as `tv_gex_flip`, `tv_call_wall`, etc.
- T2d: Added `_compute_gamma_regime_hints()` module-level helper to `technical_analyst.py`. Derives gex_regime (positive/negative), suggested_stop_policy (tight/wide), nearest_wall (+ side + distance_pct), above_hvl. Called in pipeline-entry block of the agent.
- T2e: Wrote 14 unit tests in `engine/tests/test_gamma_levels_parser.py`. All pass.

**Track 3: Kraken CLI (T3a–T3g)**
- T3a: Created `engine/markets/crypto/kraken_adapter.py` (265 lines). Async subprocess wrapper around `kraken` binary, 429-backoff with retries, paper/live gating. Returns None on any failure; never raises.
- T3b: Refactored `engine/markets/crypto/module.py` to backend-aware: `CRYPTO_BACKEND=freqtrade|kraken` env var selects path. Freqtrade behavior preserved as default. Back-compat `_bridge` property + setter preserved existing test mocks.
- T3c: Added `calculate_crypto_position_size()` + `CRYPTO_SPOT_SYMBOLS` + `CryptoPositionSizeResult` dataclass to `engine/utils/position_sizing.py`. Price-based sizing with 25% notional cap.
- T3d: Added `CRYPTO_SPOT_SYMBOLS` set + `attach_crypto()` + `is_crypto_spot()` to `engine/execution/order_router.py`. Spot crypto routes to `CryptoMarketModule.execute_signal()` instead of IBKR.
- T3e: Added `CRYPTO_BACKEND`, `KRAKEN_LIVE_ENABLED`, and 4 Kraken API key fields to `engine/config.py`. Registered `kraken` MCP server in `.mcp.json`. Added corresponding block to `.env.example`.
- T3f: Wrote 18 unit tests in `engine/tests/test_kraken_adapter.py`. All pass.
- T3g: Wrote `docs/kraken-setup.md` with install, key creation, paper workflow, live-gating, MCP registration, rate limits, troubleshooting.

**Track 4: Final regression (T4)**
- Ran full pytest suite twice. First run: 10 failures (8 pre-existing + 2 legitimately stale cache-count assertions in `test_tv_bridge_integration.py` that expected 1 `_read_labels` call per cache miss, but my gamma-overlay read adds a 2nd).
- Fixed the 2 cache-count assertions to reflect the new manifest+gamma pair.
- Second run: 1676 passing, 8 failing (all pre-existing). Zero new regressions.

### Phase 3 — Post-implementation review
- User asked "Do I need to download TradingView Desktop?" → verified (no TV Desktop install present; `tv` CLI not on PATH). Gave concrete install steps.
- User said "proceed" → ran import sanity check (all clean), flagged the 105-file pre-existing dirty state from prior sessions, proposed surgical commit plan, saved a project memory entry.
- User said "commit" → executed 3 conventional-commit commits (docs / feat tv / feat crypto).
- User said "proceed" → discovered latent bug: `settings.CRYPTO_ENABLED` and `settings.get_enabled_markets()` are referenced but never defined in `TradingConfig`. AttributeError silently swallowed by try/except in module `is_enabled()`. Fixed by adding `CRYPTO_ENABLED`, `ENABLED_MARKETS`, and `get_enabled_markets()` method to `TradingConfig`. 4th commit.
- User said "proceed" again → discovered another gap: `CryptoMarketModule` is never instantiated in `engine/main.py`. Started to add registration block, realized main.py already has 175 lines of uncommitted prior-session changes. Reverted my edit, saved the 25-line block as a standalone patch file at `docs/patches/main-py-crypto-orchestrator-wiring.patch`. 5th commit.
- User said "push" → blocked by permission policy ("Push to master bypasses pull request review").
- User said "Proceed option 1" → created feature branch `feat/tradingview-mcp-gamma-kraken`, pushed to origin, opened PR #2 with comprehensive body.

### Phase 4 — Unexpected state (end of session)
- Between PR open and handoff-write, an **external commit appeared** on the branch: `126501f test(data): update waterfall test for Polygon futures blocklist`. Authored as "Claude <claude@anthropic.com>" with co-author "Claude Opus 4.6 (1M context)". Timestamp 19:30:01 CT. I did NOT author this commit. See §5 Blockers.

---

## 2. Files created or modified

### Created (12 new files across the repo + plan + memory)

| Path | Purpose |
|---|---|
| `docs/tradingview-mcp-setup.md` | Setup walkthrough: install prompt, Chrome debug port, `tv_health_check`, gamma-indicator load steps. 108 lines. |
| `docs/kraken-setup.md` | Kraken install, API keys, paper workflow, live-gating, MCP registration, rate limits, troubleshooting. 123 lines. |
| `docs/patches/main-py-crypto-orchestrator-wiring.patch` | 61-line git-apply patch for the `engine/main.py` block that conditionally registers `CryptoMarketModule` with the orchestrator. Deliberately not applied in this session because `main.py` already carried ~175 lines of uncommitted prior-session work. |
| `engine/markets/crypto/kraken_adapter.py` | Async subprocess wrapper around `kraken` CLI. Paper/live gating via `live_enabled` constructor flag. 429 backoff with `_MAX_RETRIES=3`. 265 lines. |
| `engine/tests/test_gamma_levels_parser.py` | 14 tests for `_parse_gamma_levels` + `_compute_gamma_regime_hints`. All pass. |
| `engine/tests/test_kraken_adapter.py` | 18 tests using `unittest.mock.patch` on `shutil.which` and `asyncio.create_subprocess_exec`. All pass. |
| `C:\Users\mattm\.claude\plans\https-github-com-tradesdontlie-tradingvi-hazy-willow.md` | Plan file per plan-mode workflow. Contains the approved 4-track plan. |
| `C:\Users\mattm\.claude\projects\C--windows-system32\memory\tradingview-kraken-integration-2026-04-16.md` | Project memory — state of the integration, activation checklist, prerequisites. |
| `C:\windows\system32\.playwright-mcp\page-2026-04-16T22-59-42-548Z.yml` | Playwright snapshot artifact from tweet fetch. Can be deleted. |
| `C:\Users\mattm\.claude\plans\miles-tweet.md` | Empty placeholder file created when firecrawl-scrape attempt failed. Can be deleted. |

### Modified (10 files in the repo)

| Path | Change | Why |
|---|---|---|
| `.mcp.json` | Added `kraken` MCP server entry alongside existing `tradingview` entry. | Parity with tradingview-mcp — Claude Code sessions can invoke `kraken` tools directly. |
| `.env.example` | Added 7 lines: `ENABLED_MARKETS`, `CRYPTO_ENABLED`, `CRYPTO_BACKEND`, 4 Kraken API key fields, `KRAKEN_LIVE_ENABLED`. | Document new Kraken config surface + crypto activation gating. |
| `engine/config.py` | Added `ENABLED_MARKETS: str`, `CRYPTO_ENABLED: bool`, `CRYPTO_BACKEND: str`, 4 Kraken API key fields, `KRAKEN_LIVE_ENABLED: bool`, and a `get_enabled_markets()` instance method. | Unblocks the silently-dormant multi-market activation path. Kraken surface. |
| `engine/data/tv_indicator_bridge.py` | Added `re` import. Added `_GAMMA_ALIASES` dict + `_GAMMA_FILTER` + `_NUM_RE` constants. Added 7 gamma fields to `TVIndicatorSnapshot`. Refactored `get_snapshot` to consolidate manifest/individual paths and invoke a new `_enrich_with_gamma` method. Added `_parse_gamma_levels` + `_coerce_label_value` static methods. | Parse the closed-source "MY FREE GAMMA LEVELS" overlay via label passthrough without touching its math. |
| `engine/data/tradingview_feed.py` | Added 7 `tv_gex_*` / `tv_call_wall` / `tv_put_wall` / `tv_hvl` / `tv_vol_trigger_up_down` / `tv_max_pain` keys to `get_all_indicators()` dict. | Flatten gamma fields into the flat dict consumed by the pipeline. |
| `engine/agents/technical_analyst.py` | Added invocation of `_compute_gamma_regime_hints(indicators)` right after the TV injection block. Added `_compute_gamma_regime_hints` as a module-level function at end of file. | Make gamma context actionable for the LLM synthesis stage: regime classification, stop-policy suggestion, nearest-wall proximity. |
| `engine/markets/crypto/kraken_adapter.py` | New file (listed in Created). | — |
| `engine/markets/crypto/module.py` | Added `_resolve_backend` + `_live_enabled` helpers. Added `backend` kwarg to `CryptoMarketModule.__init__`. Split `__init__` to instantiate either `FreqtradeBridge` OR `KrakenAdapter` based on `CRYPTO_BACKEND`. Added backend property + back-compat `_bridge` property with setter. Branched `connect()`, `get_positions()`, `get_daily_pnl()`, `execute_signal()`, `shutdown()`, `health_check()` on backend. | Backend selector; Kraken becomes a first-class alternative to Freqtrade without breaking orchestrator contract. |
| `engine/execution/order_router.py` | Added `CRYPTO_SPOT_SYMBOLS` set. Added `crypto_module` param to `__init__`. Added `attach_crypto()` + `is_crypto_spot()` methods. Added crypto branch to `route_order()` that dispatches to `CryptoMarketModule.execute_signal()` and translates the `TradeResult` back into the order-dict contract. | Spot crypto symbols (BTCUSD, ETHUSD, SOLUSD, XBTUSD) route to the crypto module instead of being misrouted to IBKR futures. |
| `engine/utils/position_sizing.py` | Added `CRYPTO_SPOT_SYMBOLS` set. Added `CryptoPositionSizeResult` dataclass. Added `calculate_crypto_position_size()` function. | Price-based fractional-quantity sizing for crypto (distinct from the per-point contract sizing for futures). |
| `engine/tests/test_tv_bridge_integration.py` | Two cache-count assertions updated from 1→2 and 2→4. | Reflects the new manifest + gamma read pair per cache miss. |

### Modified by an unknown actor after the PR opened (1 file)
| Path | Change | Provenance |
|---|---|---|
| `engine/tests/test_market_data_waterfall.py` | 13 insertions, 3 deletions. Updates the `test_get_current_price_falls_back_to_polygon` test to assert Polygon is NOT called for futures symbols (matching the 2026-04-16 Polygon blocklist incident). | Authored by "Claude <claude@anthropic.com>" with co-author "Claude Opus 4.6 (1M context)" at 19:30:01 CT. Commit `126501f`. Present on local `feat/tradingview-mcp-gamma-kraken` branch but NOT yet pushed to origin — PR #2 still shows only my 5 commits. See §5 Blockers. |

---

## 3. Current state — what's running, what's stopped, what's broken

### Running
- Nothing started by this session. No engine, no dashboard, no scheduler, no daemon was launched.

### Stopped / idle
- jarvis-trader engine (port 8010): presumed stopped. Session did not interact with it.
- Dashboard (port 3010): presumed stopped. Not touched.
- IB Gateway: presumed stopped. Not touched.

### Broken / degraded
- **Pre-existing failing tests (8):** all confirmed pre-existing, none caused by this session:
  - `tests/test_approval_to_order_e2e.py::TestApprovalToOrderE2E::test_approve_endpoint_resolves_approval` — HTTP 500 from `/approve`
  - `tests/test_approval_to_order_e2e.py::TestApprovalToOrderE2E::test_approve_routes_order_to_ib` — HTTP 500
  - `tests/test_approval_to_order_e2e.py::TestApprovalToOrderE2E::test_double_approve_returns_409` — HTTP 500
  - `tests/test_approval_to_order_e2e.py::TestApprovalToOrderE2E::test_approve_with_price_override` — HTTP 500
  - `tests/test_market_data_waterfall.py::test_get_current_price_falls_back_to_polygon_when_ibkr_no_price` — expected "polygon" got "csv_cache" (Polygon blocklist incident 2026-04-16). **May have been fixed by commit `126501f` — verify on next run.**
  - `tests/test_new_features.py::TestManagedAgentBridge::test_raises_if_managed_called_without_managed_mode` — pre-existing per memory; intermittent (passed in one run, failed in another).
  - `tests/test_pending_approvals.py::test_approval_router_approve_flow` — "Live trading is disabled (LIVE_TRADING_ENABLED=False)"
  - `tests/test_scanner_pause_responsiveness.py::test_pause_method_does_not_cancel_task` — pre-existing; intermittent.

### Intentionally dormant (waiting on user action)
- `CryptoMarketModule` code exists but is **not registered in the orchestrator**. Patch file at `docs/patches/main-py-crypto-orchestrator-wiring.patch` must be applied to `engine/main.py`.
- Runtime activation of Kraken backend requires:
  - kraken-cli binary on PATH (not installed)
  - `ENABLED_MARKETS=futures,crypto` in `.env`
  - `CRYPTO_ENABLED=True` in `.env`
  - `CRYPTO_BACKEND=kraken` in `.env`
- Runtime activation of TradingView MCP + gamma levels requires:
  - TradingView Desktop app installed (not installed; verified absent from `AppData\Local\Programs\TradingView`, `Program Files\TradingView`, `AppData\Roaming\TradingView`)
  - `tv` CLI globally linked: `cd tradingview-mcp && npm link` (not done)
  - Chrome launched with `--remote-debugging-port=9222` (not verified present in startup)
  - "MY FREE GAMMA LEVELS" by TheRealDrip2Rip manually loaded on each chart (SPX, QQQ, ES1!, NQ1!)
  - Chart layout saved

### Test suite baseline (on this branch, pre-`126501f`)
- **1676 passing** | **8 failing** (all pre-existing) | **69 skipped** | **1 xfailed** | **1030 warnings**
- Zero new regressions introduced by this session's commits.

---

## 4. In-progress work — anything started but not finished

### Nothing mid-edit on disk.
Every code-touching task from the plan was either completed or deliberately deferred. No dangling edits; no half-written files.

### Explicitly deferred (captured, not lost)
1. **`engine/main.py` wiring** — 25-line block that registers `CryptoMarketModule` with `MultiMarketOrchestrator` and attaches it to `OrderRouter`. Saved at `docs/patches/main-py-crypto-orchestrator-wiring.patch`. Apply after reviewing the ~175 lines of prior-session uncommitted changes to `main.py`.
2. **Path B: own-math GEX Pine Script** — write `scripts/tradingview/pine/JARVIS_Gamma_Exposure.pine` from Polygon options chain data. Scheduled as a follow-up sprint after Path A (overlay passthrough) is validated live. Documented in the plan file.
3. **Kraken symbol universe expansion** — after BTC/ETH spot are validated, add SOL spot, Kraken perpetuals (`PF_XBTUSD`), and xStocks tokenized equities. Documented in the plan file.
4. **Kraken → AgentFeedbackTracker wiring** — so crypto PnL contributes to the IC-weighted ensemble alongside futures. Documented in the plan file.
5. **PRAW raw-Reddit swap for SocialAnalyst** — not mine; noted in memory as "~4-6hr follow-up task" since PRAW 7.8.1 is already in requirements.txt but unused by the module.

---

## 5. Blockers discovered — issues found that need resolution

### B1 — Unauthored commit `126501f` on my branch (most urgent to triage)

**What:** A commit appeared on local `feat/tradingview-mcp-gamma-kraken` at 19:30:01 CT, after PR #2 was opened. Author metadata:
- `Author: Claude <claude@anthropic.com>` (not this session's identity)
- Co-author: `Claude Opus 4.6 (1M context) <noreply@anthropic.com>` (different model than this session, which is Opus 4.7)
- Title: `test(data): update waterfall test for Polygon futures blocklist`
- Diff: `engine/tests/test_market_data_waterfall.py | 16 +++++++++++++---`

**Likely cause:** a second Claude Code session or a hook/automation ran in parallel. The commit looks correct and fixes one of the 8 pre-existing test failures. The concern is process, not content.

**Risk:**
- The commit is **on local `feat/tradingview-mcp-gamma-kraken` but NOT pushed.** `git status` says "Your branch is ahead of 'origin/feat/tradingview-mcp-gamma-kraken' by 1 commit."
- PR #2's diff still only shows my 5 commits. If you `git push`, PR #2 will auto-update to include `126501f`.
- Since this session did NOT write that commit, its author history and co-author line look correct for whoever did.

**Recommended action for next session:**
1. `git log -1 --show-signature 126501f` to inspect (unlikely to be signed).
2. Decide: accept (push) or reject (`git reset --hard 568bf47` to drop the commit, or cherry-pick onto master separately).
3. If accepted, `git push` updates PR #2. Verify the PR's diff now shows 6 commits.
4. Never proactively push from another session until the provenance is clear.

### B2 — `engine/main.py` carries ~175 lines of uncommitted prior-session work

**What:** Before this session started, `engine/main.py` was already dirty. Changes include:
- New router imports (`jarvis_router`, `messaging_router`)
- `Optional, Tuple` type imports
- `SDKTradingPipeline` guarded import (try/except on `claude_agent_sdk` ModuleNotFoundError)
- Sdk pipeline string-annotated forward reference
- More changes below line 1240 not inspected in detail

**Impact on this session:** I wrote a `CryptoMarketModule` registration block (~25 lines), realized it would bundle with the prior work on commit, reverted, and saved as `docs/patches/main-py-crypto-orchestrator-wiring.patch` instead.

**Recommended action:**
1. Review the 175 lines of prior-session changes to `main.py`. These were likely from the 2026-04-10 sprint or later.
2. Decide commit strategy (one logical commit, multiple?)
3. After that lands, apply the crypto-wiring patch: `git apply docs/patches/main-py-crypto-orchestrator-wiring.patch`.

### B3 — 105 other pre-existing uncommitted files from prior sessions

Full list: `git status --short`. High-value files needing review include `engine/agents/advisor_client.py`, `engine/agents/pipeline.py`, `engine/agents/risk_manager.py`, `engine/llm/client.py`, `engine/llm/context_manager.py`, `engine/llm/cost_tracker.py`, `engine/main.py`, `engine/notifications/openclaw_notifier.py`, `engine/notifications/whatsapp.py`, `engine/requirements*.txt`. Triage as a separate workstream.

### B4 — Permission policy blocks `git push` to master

Claude Code settings on this machine reject Bash calls that would push to the default branch. The block fires even on read-only chained commands that mention push-adjacent state. Workaround this session: created a feature branch and pushed that — which succeeded (no block).

**If the user wants direct-to-master workflow:** add to `.claude/settings.local.json`:
```json
{ "permissions": { "allow": ["Bash(git push:*)"] } }
```

### B5 — `.mcp.json` `kraken` entry will log an error until binary is installed

The new `kraken` MCP server entry in `.mcp.json` runs `kraken mcp serve`. Without the binary, Claude Code will log a non-fatal MCP startup error. Other MCPs (tradingview) still load. Remove the entry temporarily if the noise bothers the user; re-add after install. Documented in `docs/kraken-setup.md`.

### B6 — `kraken mcp serve` subcommand existence is unverified

README says kraken-cli has a "built-in MCP server," but I was unable to verify the exact subcommand (`mcp serve` vs `mcp-server` vs `mcp run`) without the binary installed. If `mcp serve` doesn't exist in the installed release, remove the `kraken` entry from `.mcp.json`; the Python adapter path does not need the MCP entry to function.

---

## 6. Key decisions made

| # | Decision | Why | Tradeoff |
|---|---|---|---|
| D1 | Collapse the Miles Deutscher tweet into Track 1 as documentation, not a separate feature. | Tweet content is a walkthrough of `tradesdontlie/tradingview-mcp`. Zero new code needed. | None — this was correct. |
| D2 | Gamma Levels: Path A (overlay passthrough via MCP labels) now, Path B (own GEX from Polygon options) as a follow-up. | Source script is closed; reverse-engineering would be license-grey. Path A ships today and respects the author's license. | Vendor could change label text and break our parser. Mitigated by substring + multi-alias matching and tolerance of None. |
| D3 | Kraken scope: paper + live-flagged path, both wired. | Matches IBKR paper-first policy; live path stays gated behind `KRAKEN_LIVE_ENABLED=True` env flag. | Slightly more code than paper-only, but enables future promotion without a refactor. |
| D4 | Register kraken-cli as an MCP server (`.mcp.json`) AND build a Python adapter. | Parity with `tradingview-mcp`. Claude sessions can use kraken tools directly; pipeline uses the Python adapter for autonomous runs. | `.mcp.json` entry will log a non-fatal error until the binary is installed (B5). |
| D5 | `KrakenAdapter` is a helper class, not a `MarketModule` subclass. | Matches `FreqtradeBridge`'s shape. `CryptoMarketModule` stays as the sole `MarketModule` surface, internally selecting the bridge based on `CRYPTO_BACKEND`. | Slightly more branching logic inside `CryptoMarketModule` — justified by preserving the orchestrator contract. |
| D6 | Crypto sizing as a separate `calculate_crypto_position_size()` function, not a case in `calculate_position_size()`. | Futures use integer contracts + per-point multipliers; crypto uses fractional quantity + spot price. Shoehorning would complicate the existing futures path. | Minor duplication of edge-case handling — acceptable. |
| D7 | `CRYPTO_SPOT_SYMBOLS = {"BTCUSD","ETHUSD","SOLUSD","XBTUSD"}` duplicated in both `position_sizing.py` and `order_router.py`. | Avoids a circular import between execution/utils modules. | Future symbol additions require editing two places — acceptable at 4 entries. |
| D8 | Keep `BTC` and `ETH` in `FUTURES_SYMBOLS` (they are CME micro-futures tickers for MBT/MET), add the USD-suffixed `BTCUSD`/`ETHUSD` as the spot tickers. | The plan originally said "remove BTC/ETH from futures"; on re-reading `order_router.py` those entries ARE correct for CME futures. | None — the original plan had a misread. |
| D9 | Revert my `main.py` edit and save as a patch file instead of bundling with prior-session work. | User's review-before-commit convention requires the 175 lines of prior work to be reviewed separately. | Requires an explicit `git apply` step by the user later. Documented. |
| D10 | Fix missing `CRYPTO_ENABLED` + `get_enabled_markets()` in config but DO NOT fix the similarly-missing `POLYMARKET_ENABLED` / `OPTIONS_ENABLED`. | Scope discipline — those were not on this session's plan. Filling the crypto gap unblocks this PR; filling the others would change runtime behavior for modules outside scope. | Polymarket and options modules continue silently dormant. Acceptable for now. |
| D11 | Feature branch + PR workflow over direct push to master. | Permission policy blocks push-to-master; spirit matches PR-review discipline. | One extra step (merge PR) before commits land on master. |
| D12 | Gamma regime hints are additive keys prefixed `gamma_*` rather than replacing existing indicator keys. | The LLM synthesis layer already sees the full `indicators` dict. Adding new keys is safe; rewriting existing ones could regress the prompt. | LLM must learn to notice the new keys; explained via field names and docstring. |
| D13 | Label-parser uses substring matching (case-insensitive) not regex, with multi-alias support per level. | Vendor labels may vary in wording. Substring is robust to trailing values, prefixes, etc. | Weak against collisions like "Call" in unrelated labels — none observed in practice. |
| D14 | Kraken adapter's `_run` retries only on 429/rate-limit indicators in stderr, max 3 attempts. | Prevents retry-hammering on legitimate failures like auth errors. | Misclassified stderr (e.g. an auth error that happens to contain "rate" in its message) would cause spurious retries — low risk. |

---

## 7. TODO items — what was planned but not started

All 14 tasks from the approved plan are complete. The following items were **captured as follow-up** during the session and deliberately scoped out of this PR:

- [ ] Apply `docs/patches/main-py-crypto-orchestrator-wiring.patch` to register `CryptoMarketModule` with `MultiMarketOrchestrator`. Blocked on B2 (review prior-session `main.py` changes first).
- [ ] Install kraken-cli binary (`github.com/krakenfx/kraken-cli/releases/latest`) to `C:\Users\mattm\bin\kraken.exe` or via `cargo install --git`.
- [ ] Install TradingView Desktop app (`tradingview.com/desktop`).
- [ ] Run `cd tradingview-mcp && npm link` to expose the `tv` CLI globally.
- [ ] Launch Chrome with `--remote-debugging-port=9222` (pin shortcut to Startup).
- [ ] Manually add "MY FREE GAMMA LEVELS" by TheRealDrip2Rip to SPX, QQQ, ES1!, NQ1! charts in TradingView Desktop. Save layout.
- [ ] Verify `tv_health_check` returns "Connection confirmed" in Claude Code.
- [ ] Verify `kraken mcp --help` lists the actual MCP subcommand shape; correct `.mcp.json` if needed.
- [ ] Run `kraken paper init --balance 10000` to initialize paper account.
- [ ] Set the three `.env` lines: `ENABLED_MARKETS=futures,crypto`, `CRYPTO_ENABLED=True`, `CRYPTO_BACKEND=kraken`. Keep `KRAKEN_LIVE_ENABLED=False`.
- [ ] Run `./restart_engine.ps1` and confirm `✅ CryptoMarketModule registered (backend=kraken)` appears in engine logs (only after patch from `docs/patches/` is applied).
- [ ] Smoke test: curl `/tv/snapshot?symbol=SPX` with X-API-Key; expect `tv_gex_flip`, `tv_call_wall`, etc. populated (not None).
- [ ] Follow-up sprint — Path B: build `scripts/tradingview/pine/JARVIS_Gamma_Exposure.pine` from Polygon options chain.
- [ ] Follow-up sprint — Kraken symbol universe expansion (SOL, PF_XBTUSD perpetuals, xStocks).
- [ ] Follow-up sprint — wire Kraken PnL into `AgentFeedbackTracker` / IC-weighted ensemble.

---

## 8. Full to-do list currently in memory

The TaskCreate/TaskList system returned **"No tasks found"** — the 14 session tasks were all marked `completed` and have since been cleared from the active task list. No pending or in-progress tasks remain in the harness.

Previous task IDs (for archival):
- #1 T1: Create tradingview-mcp setup doc — completed
- #2 T2a: Extend TVIndicatorSnapshot with gamma fields — completed
- #3 T2b: Wire gamma levels into get_snapshot flow — completed
- #4 T2c: Inject tv_gex_* keys into pipeline — completed
- #5 T2d: Add gamma-aware regime hints to TechnicalAnalyst — completed
- #6 T2e: Write gamma levels parser tests — completed
- #7 T3a: Build KrakenAdapter MarketModule impl — completed
- #8 T3b: Wire CRYPTO_BACKEND selector in CryptoMarketModule — completed
- #9 T3c: Add crypto position sizing — completed
- #10 T3d: Fix order_router Kraken spot routing — completed
- #11 T3e: Add Kraken config + .mcp.json entry — completed
- #12 T3f: KrakenAdapter tests — completed
- #13 T3g: Write Kraken setup doc — completed
- #14 T4: Final regression test suite — completed

---

## 9. Git state

### `git branch --show-current`
```
feat/tradingview-mcp-gamma-kraken
```

### `git remote get-url origin`
```
https://github.com/mattamundson/jarvis-trader.git
```

### `git status` (head + first 30 modified entries)
```
On branch feat/tradingview-mcp-gamma-kraken
Your branch is ahead of 'origin/feat/tradingview-mcp-gamma-kraken' by 1 commit.
  (use "git push" to publish your local commits)

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
        modified:   .claude/task-manifest.json
        modified:   dashboard/tsconfig.tsbuildinfo
        modified:   data/jarvis_trader.db
        modified:   engine/.env.example
        modified:   engine/LLM_CLIENT_INTEGRATION.md
        modified:   engine/agents/advisor_client.py
        modified:   engine/agents/pipeline.py
        modified:   engine/agents/risk_manager.py
        modified:   engine/api/__init__.py
        modified:   engine/api/models.py
        modified:   engine/data/paper_trades.json
        modified:   engine/database/_mixins_alerts.py
        modified:   engine/database/migrations.py
        modified:   engine/dependencies.py
        modified:   engine/docs/jarvis-trader-analysis-and-next-steps.md
        modified:   engine/docs/jarvis-trader-codebase-reference.md
        modified:   engine/learning/data/session_memory.json
        modified:   engine/llm/README.md
        modified:   engine/llm/client.py
        modified:   engine/llm/context_manager.py
        modified:   engine/llm/cost_tracker.py
        modified:   engine/main.py
        modified:   engine/notifications/openclaw_notifier.py
        modified:   engine/notifications/telegram.py
        modified:   engine/notifications/whatsapp.py
        modified:   engine/requirements-core.txt
        modified:   engine/requirements.txt
        modified:   engine/routers/observability_router.py
        modified:   engine/routers/openclaw_router.py
        modified:   engine/routers/portfolio_router.py
        ... (75 more modified files, plus untracked entries — run `git status --short | wc -l` = 105)
```

### `git log --oneline -20`
```
126501f test(data): update waterfall test for Polygon futures blocklist       ← NOT AUTHORED BY THIS SESSION (see §5 B1)
568bf47 docs(patches): stage CryptoMarketModule startup-wiring patch for later
4d83b47 fix(config): add missing CRYPTO_ENABLED + ENABLED_MARKETS + get_enabled_markets
115a0b6 feat(crypto): add KrakenAdapter + CRYPTO_BACKEND selector (paper-first)
030bd6f feat(tv): parse MY FREE GAMMA LEVELS overlay + gamma regime hints
21e0b86 docs(tradingview): add MCP setup guide + register kraken MCP server
fd02ccc fix(wfe): correct BacktestDataLoader constructor call in rolling scheduler
01e9345 feat(trader): wire ToolInspectionManager + Advisor gating
94c4793 fix(data): disable Polygon for futures + add port-conflict guardrail
05b939d chore(gitignore): ignore aider workspace files
7f1f0e0 refactor(approval): extract shared approval flow and enforce paper gate
1928322 docs(ops): add paper IB verification and market-data runbooks
1597130 fix(dashboard): prefer internal engine routing for local proxy health
3f94558 fix(health): report IB connectivity from execution connector path
30dee80 fix(dashboard): update pending approvals offline hint for proxy routing
7eb3db1 feat(dashboard): add quick Jarvis analysis and align proxy guidance
e4cfb16 fix(dashboard): proxy engine requests server-side and restore ws proxy fallback
787d3b0 fix(dashboard): use fetchEngine for token-proxy metrics and clarify offline banner (D4)
4d8aa13 feat(social): raw PRAW Reddit integration for futures-specific sentiment
1309d67 docs: 2026-04-10 EOD operational hardening handoff
```

### `git diff --stat master..HEAD` (the 6 branch-only commits)
```
 engine/tests/test_market_data_waterfall.py | 16 +++++++++++++---
 1 file changed, 13 insertions(+), 3 deletions(-)
```

Note: this stat only reflects `126501f` because my 5 prior commits were fast-forwarded from `master` (same ancestor as master). `master` HEAD is at `568bf47` since I branched AFTER my own commits landed locally on master. The PR diff on GitHub (PR #2) reflects all 6 commits visible against `origin/master` at the time of push — but `126501f` is not yet pushed, so the remote PR currently shows only the 5 commits authored by this session.

### Session commits (in order)
```
21e0b86  docs(tradingview): add MCP setup guide + register kraken MCP server
030bd6f  feat(tv): parse MY FREE GAMMA LEVELS overlay + gamma regime hints
115a0b6  feat(crypto): add KrakenAdapter + CRYPTO_BACKEND selector (paper-first)
4d83b47  fix(config): add missing CRYPTO_ENABLED + ENABLED_MARKETS + get_enabled_markets
568bf47  docs(patches): stage CryptoMarketModule startup-wiring patch for later
```

### Session commit signed-off-by
All 5 session commits carry:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Open PR
```
PR #2: TradingView MCP + gamma levels + Kraken integration
       https://github.com/mattamundson/jarvis-trader/pull/2
       base: master
       head: feat/tradingview-mcp-gamma-kraken
       commits at push time: 5 (21e0b86 → 568bf47)
       state after push: +1 unpushed commit (126501f) on local branch only
```

### Plan file
```
C:\Users\mattm\.claude\plans\https-github-com-tradesdontlie-tradingvi-hazy-willow.md
```

### Memory entries created this session
```
C:\Users\mattm\.claude\projects\C--windows-system32\memory\tradingview-kraken-integration-2026-04-16.md
C:\Users\mattm\.claude\projects\C--windows-system32\memory\MEMORY.md (index updated with one line)
```

### Tests added this session
```
engine/tests/test_gamma_levels_parser.py  (14 tests, all passing)
engine/tests/test_kraken_adapter.py       (18 tests, all passing)
```

### Final test run baseline on this branch (pre-126501f)
```
1676 passed, 8 failed, 69 skipped, 1 xfailed, 1030 warnings in 295.00s
```

---

## Quick-start for the next AI session

1. `cd C:\Users\mattm\ThinkorSwim\jarvis-trader`
2. `git status` — confirm you're on `feat/tradingview-mcp-gamma-kraken`
3. `git log --oneline -7` — verify you see the 5 session commits + `126501f` (the unauthored one)
4. **Triage `126501f`** — see §5 B1. Decide: push it, reject it, or wait for user input.
5. Read the plan at `C:\Users\mattm\.claude\plans\https-github-com-tradesdontlie-tradingvi-hazy-willow.md` for full context.
6. Read the project memory at `C:\Users\mattm\.claude\projects\C--windows-system32\memory\tradingview-kraken-integration-2026-04-16.md`.
7. Do NOT `git add -A` or `git add .` — there are 105 pre-existing dirty files from prior sessions that must be reviewed separately.
8. Do NOT push to `master` — permission policy blocks it. Use feature branches.
9. When user is ready to activate: guide them through §4 / §7 TODO list.

End of handoff.
