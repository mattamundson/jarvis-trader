# Stark Mode — JARVIS TRADER Operating Philosophy

**Purpose:** Single-document reference for how Matt runs JARVIS TRADER day-to-day.
Three control surfaces, one source of truth, five operating axioms. Read this
before onboarding a new session or extending any surface.

---

## 1. The Mental Model — Three Control Surfaces, One Source of Truth

JARVIS TRADER is operated across three distinct surfaces. Each has a role; none
duplicates another.

| Surface | Access point | Role | Codebase access |
|---|---|---|---|
| **Direct (Claude Code)** | Terminal — dev session | Deep work: multi-file edits, MCP tools, smoke tests, strategy validation | Yes — full |
| **Conversational (Hermes via Telegram / voice)** | Telegram message or voice note → Hermes → engine | On-the-go: natural language, `/jarvis/ask`, skill dispatch | No — HTTP to engine only |
| **Ambient (dashboard at `/jarvis`, `/performance`, `/`)** | Browser at `http://127.0.0.1:3010` | Passive monitoring: at-a-glance state, P&L, pipeline status | No — read-only API calls |

The **engineering surface** (Claude Code) is where code gets written, tests pass,
and system state changes. The **operations surface** (Hermes) is where Matt
interacts while away from the desk. The **awareness surface** (dashboard) is
always-on ambient context.

**The single source of truth** is:
- **Engine at port 8010** — pipeline state, gate verdicts, risk checks, trade log
- **SQLite DB** (`engine/data/jarvis_trader.db`) — Discord signals, bookmarks, sentiment, positions
- **gbrain-ingested vault** (`master-jarvis/second-brain/raw/`) — durable research, wiki, processed intel

Every surface above is a **view** on this. State is never duplicated or maintained
independently in the dashboard or Hermes. If the engine says it, that's the fact.

---

## 2. The Five Stark Axioms

### Axiom 1 — Voice-first when away from the desk

When Matt is not in a Claude Code session, Hermes skills are always preferred over
manual API calls from a phone. "pipeline mes" in Telegram beats opening a browser
and crafting a `curl`. Hermes is the remote control.

**Skill path (authoritative):** Hermes runs as WSL user `mattm` and reads skills
from `/home/mattm/.hermes/skills/`. The Windows path `C:\Users\mattm\.hermes\skills\`
is not read by Hermes — write new skills directly to the WSL path. Nine `jarvis-*`
skills are live as of 2026-05-20; see `CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP.md §6`.

### Axiom 2 — The safety layer is sacrosanct

No surface — not even Claude Code — can override `engine/risk/safety_layer.py`.
`/jarvis/ask` explicitly refuses safety-override questions. Kill switch thresholds
(-6% daily P&L, -20% drawdown) are hardcoded Python constants, not LLM-routable
parameters. Any change to safety files requires a `[safety-review]` PR tag and
does not happen from a Hermes session.

### Axiom 3 — The vault is the long-term memory

Every non-trivial decision, finding, or pattern lands as a `.md` file in
`master-jarvis/second-brain/raw/wiki/` so gbrain can recall it. `Jarvis-VaultGbrainSync`
runs every 30 minutes. If it's not in the vault, JARVIS doesn't know it tomorrow.

### Axiom 4 — The pipeline is paper-only until Phase 3

All three surfaces respect this unconditionally. `LIVE_TRADING_ENABLED = False` is
an invariant in `engine/config.py`. Live IB port 4001 is permanently blocked in
code. Hermes cannot flip this flag. Claude Code must not flip this flag without a
full Phase 3 sign-off and a `[safety-review]` commit.

### Axiom 5 — Self-improvement is daily

Each `/jarvis/ask` interaction produces a JSONL metadata log entry. Each morning
brief reflects patterns from the prior day's interactions. Non-obvious findings
become vault entries, which gbrain ingests, which makes the next brief smarter.
This loop is the system's compounding edge.

---

## 3. The Morning Routine

Matt's standard trading day:

| Time (CT) | Event |
|---|---|
| 5:30 am | `jarvis-morning-brief` cron fires → Telegram message |
| On wake | Scan the brief; if notable, send "jarvis brief mes" for deeper context |
| Pre-market | Open `/jarvis` dashboard page; check pipeline verdicts and session bias |
| During session | Significant pipeline runs via Claude Code or scheduled skill; ambient monitoring via dashboard |
| EOD | `/eod` slash command captures wrap-up; vault entry written if anything substantive happened |

The morning brief aggregates: session bias from Corey #market-updates, overnight
signal summary, gate v2 verdicts for live instruments (MES), portfolio P&L snapshot,
and any engine health alerts.

---

## 4. The 10 Questions JARVIS Can Answer

The `/jarvis/ask` intent taxonomy covers these ten categories. Each routes to a
distinct engine endpoint or skill.

| Intent | Example question |
|---|---|
| `health` | "Is the engine up?" |
| `bookmark_search` | "What did I save about order flow last week?" |
| `bookmark_recent` | "Show me the last 10 bookmarks" |
| `commentary` | "What did Corey say about ES this morning?" |
| `briefing` | "Give me the pre-market briefing" |
| `tearsheet` | "Show me the 90-day MES tearsheet" |
| `regime` | "What's the current market regime?" |
| `pipeline_run` | "Run the MES pipeline" |
| `position` | "What positions am I in?" |
| `unknown` | _(anything outside the above — JARVIS asks for clarification)_ |

Anything outside these categories is surfaced as `unknown` and Matt is asked to
rephrase. JARVIS does not guess intent for trading-consequential actions.

---

## 5. What JARVIS Will Not Do

The explicit refusal list. These are not features that are missing — they are
deliberate hard limits enforced at the skill and engine level.

- **Override the kill switch** — safety_layer.py is the only authority; no LLM route
- **Disable the safety layer** — non-negotiable; not configurable via any surface
- **Set `LIVE_TRADING_ENABLED = True`** — paper mode is enforced until Phase 3 sign-off
- **Bypass risk checks** — all six SafetyLayer checks are required for any order
- **Force a trade** — JARVIS assists decisions; it does not make them
- **Sell all positions** — no bulk order surface exists on any voice/chat path
- **Make tax or legal decisions** — JARVIS has no domain competence here; consult a professional
- **Move money between accounts** — outside JARVIS's scope entirely
- **Send messages to third parties on Matt's behalf** — Hermes posts to Matt's own Telegram only; no external-party comms

---

## 6. Analyst Inventory

Pipeline stage 1 runs these analysts in parallel before the bull/bear debate:

| Analyst | Flag | Status | Signal source |
|---|---|---|---|
| technical | always on | active | STC, ATR, regime |
| news | always on | active | Claude LLM + news feed |
| social | always on | active | Corey Discord #market-updates |
| fundamental | always on | active | macro / fundamentals |
| corey | always on | active | Corey auction-theory proximity |
| breakout | always on | active | breakout pattern scanner |
| harmonic | always on | active | harmonic pattern scanner |
| kronos | `ENABLE_KRONOS=1` | stub (default off) | Kronos foundation model |
| options (stage 6) | `ENABLE_OPTIONS_ANALYST=1` | capable (default off) | put/call skew, IV term structure, dealer gamma |
| research | `ENABLE_RESEARCH_AGENT=1` | stub (default off) | autonomous strategy hypothesis |

Options analyst (stage 6) — default off. Read-only signal contribution; never routes orders.
Activation: set `ENABLE_OPTIONS_ANALYST=1` in `engine/.env`. Source: `engine/agents/options_analyst.py`.

Sub-signal status (2026-05-20):
- **Skew (weight 0.4):** wired — `get_pc_skew` fetches 25-delta put/call IV from Polygon, returns percentage-point spread. Positive = puts richer = bearish. Normalization: `signal = -skew / 50.0`. 5-min TTL cache. Returns None on missing data; analyst abstains gracefully.
- **Term structure (weight 0.3):** wired — `get_term_structure` fetches ATM IV for front-week, front-month, second-month expiries. Slope = (front-week IV - front-month IV) × 100. Positive slope = backwardation (fear). Normalization: `signal = -slope / 20.0`. Returns None on missing data.
- **Dealer gamma (weight 0.3):** pending — gamma sub-signal still returns 0.0 (neutral) as a placeholder until a dealer-gamma feed is available. Weight still counts toward data-coverage so partial signal from skew + term is not penalized.

---

## 7. Cross-References

- `[[AUTONOMOUS_PIPELINE_RUNBOOK]]` — autonomous pipeline scheduler + human approval queue (default-OFF, all orders human-gated)
- `[[CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP]]` — surface-by-surface wiring, HTTP routes, MCP gaps, auth
- `[[KRONOS_AND_RESEARCH_AGENT_RUNBOOK]]` — Kronos classifier, ResearchAgent activation flags, test gate
- `[[DISCORD_INTEL_RUNBOOK]]` — Discord MCP servers, ingest task, HTTP route reference, smoke tests
- `[[SECOND_BRAIN_VAULT_OPERATIONS_RUNBOOK]]` — vault layout, gbrain ingest, session-stamped output dirs
- `[[QUANTSTATS_TEARSHEET_RUNBOOK]]` — tearsheet route params, output format, scheduled pattern
- `[[DISCORD_BRIEFING_RUNBOOK]]` — composed `/discord/briefing` facade, Corey bias + IB levels + sentiment
- `~/scripts/HERMES_RUNBOOK.md` — Hermes topology, LLM backends, systemd unit, safe-restart procedure

---

*Written 2026-05-20. Update when a surface changes scope, a new axiom is added,
or Phase 3 live-trading is authorized.*
