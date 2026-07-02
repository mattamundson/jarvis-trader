# HANDOFF — 2026-07-02 — IBKR Real-Time Data Entitlement (MES/ES price feed)

- **Session:** `322b0b9a-e7e4-4dad-a5b7-4eaa686ffc8b` (via `/jarvis-trader`)
- **Branch:** `fix/corey-standalone-vertex-routing`
- **Companion:** `CONVERSATION_2026-07-02_es-plan-price-feed-ibkr-data.md` (full narrative)

---

## 1. Current state

- **Engine: HEALTHY.** `/health` at 07:00Z = `status:ok`, `ibkr_connected:true`
  (exec + data), `ibgateway_alive:true` port 4002, `paper_mode:true`,
  `kill_switch_active:true` (expected in paper), `llm` anthropic primary healthy,
  uptime ~75 min. Earlier transient empty-`/health` concern did NOT recur — not wedged.
- **IB Gateway: UP**, logged into paper account **DUR162217**, port 4002 listening.
- **Price feed: DELAYED ONLY (~11 min).** Real-time CME futures blocked by **IBKR Error 354**
  ("market data is not subscribed"). `usfuture` data farm is CONNECTED → this is a pure
  **entitlement** problem, not connectivity. `reqMktData` realtime = NaN; delayed returns
  price (~7535/7543/7545 through the session).
- **STC watch loop (`Loopify-es-stc-trigger`): ARMED**, GREEN, every-3-min, self-expires
  15:00 CT. Fires correctly on the cross but up to a bar late on delayed data. On the day,
  STC stayed pinned at floor (~0.01) with ES ~7,535 above the 7,475 pivot — setup loaded,
  never confirmed.
- **Open paper positions:** 2× MES LONG (entry 5300.125 @ 2026-07-01T13:37Z;
  5300.625 @ 2026-06-30T20:09Z). IB-side broker positions empty (paper).

## 2. Key decisions made

- **Root cause of stale feed = missing real-time CME entitlement**, PROVEN by direct
  `ib_async` probe (Error 354 + realtime NaN + delayed-only). NOT a competing login
  (Amo confirmed), NOT code-fixable.
- **The fix is a subscription, not code:** "US Securities Snapshot and Futures Value Bundle
  (NP)" ~$10/mo, on the **funded** account, **shared to paper**, agreement signed.
- **Delayed data is adequate for the MES 1h STC paper strategy** — the cross confirms at bar
  close; 10-min delay only costs entry-fill precision, not signal detection. Do NOT treat the
  entitlement as a blocker to trading the plan.
- **`.env` account mismatch is latent, not urgent** — `/brokers/positions` shows
  `ibkr_queryable:true`; the engine queries IBKR fine despite `.env` pointing at DUP662235.
- **Did NOT restart the engine** — `restart_engine.ps1` is Tier-3 / excluded from a generic
  "proceed" per standing rule. The `IB_ACCOUNT_ID` fix should ride the next natural restart.
- **Raw JSONL transcript NOT committed** — it embeds the private global CLAUDE.md, 1Password
  item names, secret-path names, and account IDs. Distilled markdown committed instead.

## 3. In-progress work

- **Real-time entitlement propagation.** Amo subscribed + signed agreement + relogged the
  Gateway, but Error 354 persists. Either (a) sub is on the wrong account / sharing off, or
  (b) IBKR propagation lag (often not live until next session/day). Awaiting propagation or a
  Subscription-Manager confirmation.

## 4. Blockers discovered

- **Paper accounts can't own a market-data subscription** — they inherit from the funded
  account with "Share market data with paper trading account" enabled. Likely the crux of the
  persistent 354 on DUR162217.
- IBKR entitlement activation is **not same-session** — commonly flips on the next trading
  session even when configured correctly.
- Claude-in-Chrome MCP browser tab is a **separate session** from Amo's authenticated
  browser — cannot drive his logged-in IBKR portal.
- No free real-time futures source in the stack (TV needs its own CME plan; Polygon free
  blocks futures).

## 5. Files created or modified (this session)

Repo (`jarvis-trader`), committed here:
- `docs/session-logs/CONVERSATION_2026-07-02_es-plan-price-feed-ibkr-data.md` — full narrative.
- `docs/session-logs/HANDOFF_2026-07-02_ibkr-realtime-data-entitlement.md` — this file.

Outside the repo (machine state, for reference — NOT committed):
- `~/.claude/loops/es-stc-trigger/run.ps1` — the armed watch-loop runner (+ `state.json`).
- `~/.claude/staged-patches/tradingview_feed.py` — apply-ready TV feed drop-in (Redis quote
  VERIFIED; QuestDB bar resample fail-closed + UNVERIFIED). Shelved — needs a TV CME sub too.
- `~/.claude/projects/.../memory/project_price_feed_three_faults_2026_07_01.md` — root cause +
  dated `STATUS UPDATE 2026-07-02`.
- `~/.claude/projects/.../memory/project_es_stc_trigger_loop_2026_07_01.md` — the watch loop.
- `~/.claude/projects/.../memory/MEMORY.md` — index lines updated.
- `scratchpad/ib_probe.py` — reusable read-only IB market-data probe (clientId 99).

## 6. TODO items

- [ ] **Amo:** IB Gateway → Account → Management → **Market Data Subscription Manager** —
      confirm the CME bundle shows for DUR162217. Empty → fix funded-account sub + sharing.
      Present → just wait for propagation.
- [ ] **Amo (next restart, not urgent):** `engine/.env` line 74
      `IB_ACCOUNT_ID=DUP662235` → `DUR162217`, then `.\restart_engine.ps1`
      (credential-guarded + Tier-3; Amo applies).
- [ ] After entitlement is live: re-run `scratchpad/ib_probe.py` — expect `[realtime]` a real
      price and no Error 354.
- [ ] (Optional, deferred) Apply the staged `tradingview_feed.py` only if feed redundancy is
      wanted AND the TV account gets a CME sub. Don't open a second vendor problem otherwise.

## 7. Git state (at handoff)

- **Branch:** `fix/corey-standalone-vertex-routing`, **2 commits ahead** of origin
  (`b25f9e0`, `93e1bb5` — pre-existing gemini-2.5-pro decision-routing work, tests green per
  memory). These push along with this docs commit.
- **Recent log:** `93e1bb5` route advisor_debate→gemini-2.5-pro · `b25f9e0` route
  trade-decision agents→gemini-2.5-pro · `b61be07` docs gate v2 ALT DD 4% · `1e47acc` discord
  digest · `f396d1a` failover start_time reset.
- **Working tree (NOT touched by this commit):** 5 tracked mods (`.gitignore`,
  `dashboard.code-workspace`, `METRICS_SNAPSHOT.json`, `family_fdr_report.md`,
  `forecast_reports/2026-06-25.md`) + many untracked (forecast reports, tearsheets, research
  docs, prior session logs). Staged **per-file** (never `git add -A`) — only the two docs above.

## 8. Suggested next action

**Confirm the subscription's home in the Gateway's Market Data Subscription Manager** — that
single check disambiguates *wait for propagation* (bundle present) vs *fix sharing* (bundle on
the funded account, "share with paper" on). Everything else can ride: trade the 1h plan on
delayed data (fully adequate), fold the `IB_ACCOUNT_ID` fix into the next restart, leave the TV
patch shelved.
