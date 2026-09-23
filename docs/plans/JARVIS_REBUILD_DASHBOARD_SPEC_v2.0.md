# JARVIS Dashboard Rebuild — Operator Surface Specification (v2.0)

**Authored:** 2026-09-23 · **Status:** DESIGN ONLY — nothing implemented
**Companion to:** `JARVIS_REBUILD_BLUEPRINT_v2.0.md` (architecture), `JARVIS_REBUILD_WORK_BREAKDOWN_v2.0.md` (tasks)
**Current state:** 58 page routes, 191 components, 52 lib modules, Next 15.3 / React 19 / Tailwind 3.4 / SWR / Recharts / lightweight-charts

**Scope fence:** JARVIS is **futures + options + equities**. Commodities research is `amo-arbitrage`'s
mandate; this spec covers only JARVIS surfaces. Crypto (`/alt`) and prediction markets are rendered as
explicitly non-core research surfaces and never feed the trading authority.

**Single-operator mandate:** this is a **one-user console**. There are no roles, no permissions model, no user
management, no tenancy, and no multi-user affordances anywhere in the UI. One operator, one auth boundary,
one audit trail. Any design that implies "who else uses this?" is out of scope.

---

## 0. The diagnosis in one paragraph

The dashboard is not badly built — it is **un-governed**. It grew by accretion: 58 routes, 191 components,
52 lib helpers, each page independently deciding how to fetch, how to compute a metric, and how to render
missing data. That is why four different pages can show four different P&L numbers, why "is JARVIS healthy"
needs six tabs, and why `useHonestTrades` had to exist as a *correction layer* for the metric layer. The
rebuild is not "make it prettier." It is: **one information architecture, one data layer, one design
system, one provenance contract, and a hard rule that no number renders without proof of where it came
from and how old it is.**

---

## 1. The seven laws of this UI

Ordered. Earlier laws beat later ones when they conflict.

1. **No number without provenance.** Every displayed quantity is wrapped in a `Value<T>` carrying
   `source`, `asOf`, `quality`, and (where relevant) `verdictId`/`artifactId`. A component that receives
   a bare `number` for a load-bearing metric is a type error by design.
2. **Unavailable is a first-class state, rendered loudly.** `STALE`, `MISSING`, `REJECTED`, `UNVERIFIED`
   are *content*, not error fallbacks. A grey "—" is acceptable only when accompanied by a reason chip.
   Never render `0` for "unknown".
3. **One authority per question.** The UI never re-derives a verdict, a tradability decision, a P&L
   figure, or a health status. It renders what the authority returned, including the authority's reason
   code. Client-side "helpful" recomputation is banned.
4. **The 10-second test.** From a cold load of `/`, a competent operator can answer *"am I safe to trade
   right now, and if not, why?"* in under ten seconds without scrolling. This is the primary acceptance
   criterion for the entire rebuild.
5. **Realtime by subscription, not by polling.** One SSE/WS connection per client, multiplexed. No page
   polls `/health`. No widget owns an interval.
6. **Latency is a feature.** Interaction → feedback < 100 ms; first meaningful paint < 1.5 s on the
   operator box; the HUD never blocks on a slow leg — it renders what it has with freshness stamps and
   fills in.
7. **The UI cannot change safety state by accident.** Kill switch, symbol gates, risk params, and flags
   are read-only in the UI unless the operator passes an explicit, typed, confirmed action — and every
   such action writes an audit row. There are no ambient toggles.

---

## 2. Information architecture: 58 routes → 1 HUD + 13 surfaces

### 2.1 The target map

| # | Surface | Purpose (one sentence) | Absorbs (current routes) |
|---|---|---|---|
| **T0** | **`/` — HUD** | *Am I safe to trade right now, what does the system believe, and what is it about to do?* | `/`, `/dashboard`, `/mission-control`, `/command-center`, `/command-center-v2`, `/today`, `/trust-pane` |
| T1 | `/state` | Every leg of the system, its freshness, its last transition, and its owner | `/health`, `/data-integrity` |
| T2 | `/book` | Positions, exposure, realized/unrealized P&L, risk budget consumption | `/portfolio`, `/performance`, `/stats`, `/master/trading`, `/paper`, `/parallel-paper` |
| T3 | `/decisions` | The decision ledger: every decision, its evidence, its verdict id, its outcome | `/signals`, `/signal-outcomes`, `/pipeline-board`, `/trades/pending-approvals` |
| T4 | `/trades` | Trade journal, reviews, post-mortems, attribution | `/trades`, `/trades/journal`, `/trades/[id]/review`, `/journal`, `/journal-review` |
| T5 | `/evidence` | Verdicts, gate v2 table, forward evidence, DSR/trial accounting, scorecards | `/validation`, `/strategies`, `/strategy-ledger`, `/scorecard`, `/trading-eligibility`, `/backtest` |
| T6 | `/research` | Research queue, experiment registry, trial ledger, learning loop | `/strategy-research`, `/research-log`, `/learning` |
| T7 | `/options` | Volatility surface, chain, defined-risk candidates, options verdicts | `/options` |
| T8 | `/market` | Market context: brief, regime, levels, auction structure, watchlist, screener | `/market-brief-public`, `/regime`, `/hidden-pivots`, `/domflow`, `/atr-trail`, `/framing-brief`, `/analysis`, `/analysis/spx`, `/screener`, `/watchlist`, `/kairos` |
| T9 | `/ops` | Services, cron/loops, incidents, backups, deploy truth | (split out of `/health`, `/config`, `/settings`) |
| T10 | `/intel` | Discord/X/news/sentiment as *evidence*, with source integrity | `/discord`, `/sentiment` surfaces |
| T11 | `/alt` | Crypto + prediction markets (explicitly non-core, isolated) | `/crypto`, `/polymarket` |
| T12 | `/lab` | Experimental surfaces that are not production claims | `/thinkscript`, `/strategy-c`, `/strategy-c-command`, `/vault` |
| T13 | `/admin` | Flags, safety state, config truth, audit trail — read-mostly, gated writes | `/config`, `/settings` |

**Net: 58 → 14.** Every retired route gets a permanent 301 to its new home (see §11), so muscle memory and
bookmarks survive.

### 2.2 Navigation model

Three levels, never four:

```
┌─ HUD (/)                    ← always one click away, logo returns here
├─ NOW     /            /decisions   /book
├─ TRUST   /state       /evidence    /ops      /admin
├─ MARKET  /market      /options     /alt      /intel
└─ WORK    /research    /trades      /lab
```

A persistent **global status rail** sits above the nav on every surface: `TRUST · DATA · BROKER · KILL ·
PAPER/LIVE · LAST DECISION · BUILD`. It is never hidden, never scrolled away, and it is the same
component everywhere. If the operator is on `/research` and the broker dies, they see it.

---

## 3. The HUD (`/`) — exhaustive specification

The HUD is the product. Everything else is depth.

### 3.1 Layout (single full-bleed viewport, no page scroll on 1920×1080)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ GLOBAL STATUS RAIL                                                            │
│ TRUST: DEGRADED · DATA 12/12 fresh · BROKER: connected(verified) ·            │
│ KILL: clear · MODE: PAPER · LAST DECISION 09:41:12 (MES NO_TRADE) · BUILD abc123│
├───────────────┬──────────────────────────────────┬───────────────────────────┤
│ A. VITALS     │ B. CONVICTION                    │ D. PIPELINE TAPE          │
│  (vertical    │  per-symbol stance card          │  live stage-by-stage      │
│   leg list,   │  - symbol, direction, size       │  reasoning for the last   │
│   each with   │  - odds (touch/close/fail)       │  decision, streaming      │
│   green/amber/│  - verdict id + age              │  - stage, agent, tokens,  │
│   red + age)  │  - data freshness                │    cost, latency          │
│               │  - WHY (evidence chips)          │  - link to full trace     │
│               │  - tradability reason code       │                           │
├───────────────┴──────────────────────────────────┴───────────────────────────┤
│ C. BOOK                    │ E. NEXT ACTION + RISK                              │
│  open positions, unrealized│  what the engine will evaluate next + countdown    │
│  today P&L, exposure,      │  risk budget consumed (heat), remaining daily loss │
│  heat bar, DD governor tier│  allowance, next scheduled job, next session event │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Zone A — Vitals

Each leg is a row: **name · state chip · latency/age · last transition · owner**.

Legs (exactly these, no more):
`engine` · `database` · `broker_connection` · `broker_data` · `market_data:{symbol}` (one row per trading
symbol) · `llm_path` · `event_bus` · `scheduler` · `research_plane` · `backup`.

State vocabulary (fixed, typed, no ad-hoc strings): `OK` · `DEGRADED` · `DOWN` · `UNKNOWN` · `STALE`.
`UNKNOWN` is what a leg reports when the probe itself failed — never conflate with `DOWN`.

Each leg row expands (click) into a drawer: last 20 transitions, the probe that produced the state, the
threshold it crossed, and the runbook link.

### 3.3 Zone B — Conviction

One card per symbol in the trading universe. The card is the entire argument for or against a trade:

| Field | Source of truth | Render rule |
|---|---|---|
| Symbol + asset class | config | — |
| Tradability | `is_tradable(symbol, strategy_id, now)` | `ALLOW` (green) / `DENY` (red) + **reason code** in plain language |
| Direction | signals layer | `LONG` / `SHORT` / `NO_TRADE` — never a hedge word |
| Size | risk policy | contracts + `$` risk + % of budget; shows the policy hash |
| Odds | model | **touch / close / failure** as three separate probabilities with sample size |
| Verdict | verdict store | id, family, `as_of`, age vs 14-day expiry, PASS/FAIL/INSUFFICIENT_SAMPLE |
| Data quality | quality gate | `ACCEPTED` + bar age, or the failing check by name |
| Evidence chips | evidence objects | each chip cites an artifact (news item, journal note, backtest id) |
| Why-not | tradability reason | when `DENY`: the single blocking reason first, the full chain on expand |

**Banned on this card:** any number without a provenance tooltip; any probability without a sample size;
any direction that is not one of the three; the words "modest", "slight", "potential" applied to an edge.

### 3.4 Zone C — Book

Open positions (symbol, side, qty, entry, mark, unrealized, age, stop, target, R-multiple), today's
realized P&L, portfolio heat bar with tier thresholds, drawdown governor tier, and a one-line
reconciliation status. Every figure carries the same `Value<T>` provenance envelope.

### 3.5 Zone D — Pipeline tape

A live stream of the current/last decision: stage name, agent, model, tokens, cost, latency, and the
*typed evidence object* it produced (not the raw prose). Clicking a stage opens the full trace. The tape
is append-only and never re-renders history.

### 3.6 Zone E — Next action + risk

What the engine will evaluate next and when; scheduled jobs for the session; session calendar events
(open/close/halt windows); risk budget remaining (daily loss allowance, drawdown allowance); and the
**next human action** if one is required (with the reason).

### 3.7 HUD acceptance criteria

- **10-second test:** cold load → "safe to trade?" answered, with reason, without scrolling. Verified by
  a timed Playwright test with a real operator script.
- **Kill test:** pull the data feed mid-session; Zone A's `market_data:MES` row flips to `STALE`, the
  global rail flips to `DEGRADED`, Zone B's card flips to `DENY (data_stale)`, and the odds panel
  renders `unavailable` — all via the stream, with no manual refresh, within one event.
- **No bare numbers:** a static-analysis test walks the HUD's rendered DOM and asserts every numeric node
  carries a provenance attribute (`data-prov`) or is on an explicit allowlist (clock, countdowns).
- **Zero polling:** network log shows exactly one persistent stream connection and no interval-driven
  requests to `/health` or per-widget endpoints.

---

## 4. Design system

### 4.1 Tokens (single source: `dashboard/styles/tokens.css`)

```css
:root {
  /* surfaces */
  --bg-0:#07080b; --bg-1:#0d0f14; --bg-2:#141821; --bg-3:#1c2130;
  --border:#242a38; --border-strong:#333c4f;

  /* text */
  --fg-0:#e8ecf4; --fg-1:#a8b2c4; --fg-2:#6b7689;

  /* semantic state — the ONLY colors allowed to carry meaning */
  --ok:#31d07a; --warn:#f2b13c; --bad:#ff5c5c; --unknown:#6b7689;
  --info:#4aa8ff; --accent:#ff8a3d;      /* accent = JARVIS brand, never semantic */

  /* risk tiers (drawdown governor) */
  --tier-0:var(--ok); --tier-1:var(--warn); --tier-2:#ff8a3d; --tier-3:var(--bad);

  /* type */
  --font-display:'Orbitron',system-ui;   /* headings, numeric hero */
  --font-ui:system-ui,-apple-system,'Segoe UI';
  --font-mono:'JetBrains Mono',ui-monospace;
  --fs-hero:44px; --fs-h1:24px; --fs-h2:18px; --fs-body:14px; --fs-micro:11px;

  /* space (4px base) */
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s6:24px; --s8:32px; --s12:48px;

  /* radius / elevation */
  --r-sm:4px; --r-md:8px; --r-lg:12px;
  --e1:0 1px 2px rgb(0 0 0/.4); --e2:0 8px 24px rgb(0 0 0/.45);
}
```

**Color law:** semantic colors mean exactly one thing each. `--ok` never means "nice", `--bad` never
means "down day". Direction uses `--info`/`--accent`, not green/red — because in a trading UI, green/red
must be reserved for *state*, not for price direction, or the operator mis-reads the rail.

### 4.2 Density & typography rules

- Numeric hero values: `--font-display`, tabular-nums, `letter-spacing:.02em`.
- **Every metric shows its unit and its age**: `7,710.00 (2s)` not `7710`.
- Percentages always carry a basis: `+1.2% (today, RTH)`.
- Never abbreviate a symbol or a state; never use ellipsis on a state chip.
- Tabular alignment for all columns; no proportional digits in tables.

### 4.3 Motion

- State transitions animate (150 ms ease-out) — a leg going red should *catch the eye*.
- Data updates do not animate (no flashing numbers); they fade a 1px underline.
- `prefers-reduced-motion` disables all of it. No motion is ever the only signal.

### 4.4 Themes

Dark is primary (control-room). A light theme exists for daylight/print and must meet the same contrast
bar. No third theme. No per-page theme overrides — ever.

---

## 5. Data layer architecture

### 5.1 The provenance envelope (the core type)

```ts
export type Quality = 'ACCEPTED' | 'STALE' | 'MISSING' | 'REJECTED' | 'UNVERIFIED';

export interface Provenance {
  source: string;            // 'ibkr' | 'databento' | 'polygon' | 'db' | 'judge' | 'llm' | 'config'
  asOf: string;              // ISO-8601, when the fact was true in the world
  ingestTs: string;          // ISO-8601, when we learned it
  quality: Quality;
  reasonCode?: string;       // machine-readable: 'data_stale' | 'no_fresh_verdict' | ...
  artifactId?: string;       // content-addressed evidence id
  verdictId?: string;        // authorizing verdict, when applicable
  policyHash?: string;       // risk policy version that produced a sized number
  authority?: string;        // which component is the source of truth for this fact
}

export type Value<T> = { value: T | null; prov: Provenance };
```

Every engine response that carries a load-bearing fact returns `Value<T>`. There is no "raw" variant.
`null` + `quality:'MISSING'` is how the API says "I don't know" — and the UI renders that as a loud,
explained state.

### 5.2 Contract example (engine → dashboard)

```ts
GET /api/v1/hud/summary
{
  trust: { value: 'DEGRADED', prov: {...authority:'trust_aggregator'} },
  legs: [
    { id:'broker_data', state:{value:'STALE',prov:{...}}, ageS:{value:412,prov:{...}} },
    ...
  ],
  conviction: [
    {
      symbol:'MES',
      tradable:{ value:false, prov:{ source:'gate_v2_policy', reasonCode:'data_stale',
                                     verdictId:'MES_trend_rank11@2026-09-20', authority:'is_tradable' } },
      direction:{ value:'NO_TRADE', prov:{...} },
      odds:{ touch:{value:null,prov:{quality:'MISSING',reasonCode:'insufficient_sample'}}, ... },
      size:{ value:null, prov:{ reasonCode:'denied_before_sizing' } }
    }
  ],
  book: { /* same envelope discipline */ },
  next: { /* ... */ }
}
```

The dashboard's only job is to render this. It performs no aggregation that could disagree with the engine.

### 5.3 Transport

| Need | Mechanism |
|---|---|
| Initial paint | `fetch` of one aggregated endpoint per surface (server components where possible) |
| Live updates | **one** SSE connection per client (`/api/v1/stream`), multiplexed by topic: `legs`, `conviction`, `book`, `tape`, `ops` |
| Mutations | POST with idempotency key; response returns the new `Value<T>` so the UI never guesses |
| Fallback | If SSE fails, degrade to SWR polling **with a visible `DEGRADED_TRANSPORT` banner** — silence is not acceptable |
| Offline/stale | If the last event is older than the topic's SLA, the affected zone shows `STALE` and the rail degrades |

### 5.4 Client state rules

- Server state lives in SWR (or a thin store) — never duplicated into component state.
- No component computes a derived financial metric. Derived *presentation* (e.g. formatting) is fine;
  derived *values* (totals, ratios, P&L) must come from the engine.
- Formatters are pure, unit-tested, and centralized in `lib/format/*` (replacing the current sprawl of
  `honestMetrics.ts`, `honestAnnualized.ts`, `parallelPaperFormat.ts`, `watchlistFormatters.ts`,
  `watchlistBarFormatters.ts`, `signalFlowFormatters.ts`, …).
- Error boundaries per zone: one zone failing never blanks the HUD.

---

## 6. Component library

Three tiers, strictly layered. A page may compose tier 1 and 2; it may never reach past them.

**Tier 1 — primitives** (`components/ui/`): `Card`, `Chip`, `StateDot`, `KeyValue`, `Table`, `Tabs`,
`Drawer`, `Modal`, `Toast`, `Skeleton`, `Sparkline`, `Gauge`, `HeatBar`, `Timeline`, `CodeBlock`,
`CopyButton`, `Tooltip`, `Segmented`, `EmptyState`, `ReasonChip`, `ProvenancePopover`.

**Tier 2 — composites** (`components/blocks/`): `StatValue` (renders `Value<T>` + provenance + age),
`MetricGrid`, `LegList`, `ConvictionCard`, `PositionTable`, `VerdictTable`, `EvidenceChipRow`,
`OddsTriplet`, `RiskBudgetBar`, `PipelineTape`, `SessionClock`, `JournalEntry`, `DiffView`.

**Tier 3 — page assemblies** (`app/<surface>/`): composition only, no business logic, no formatting
beyond layout.

**Hard rules:**
- `StatValue` is the *only* way a number reaches the screen. If you are rendering `{x}` inside a `<span>`,
  the lint rule `no-bare-numeric-render` fails the build.
- Every table has a defined empty state, a defined stale state, and a defined "authority unavailable"
  state — three separate components, not one generic fallback.
- No `any`. The data layer is typed end-to-end; the API client is generated or schema-validated (Zod)
  so a backend shape change is a build error, not a runtime `undefined`.

---

## 7. Page-by-page specifications

Each surface below states: purpose · zones · data contract · states · acceptance test. (T0 is §3.)

### T1 `/state` — system truth
- **Purpose:** the answer to "which leg is lying to me right now?"
- **Zones:** leg table (state, age, probe, threshold, owner, runbook) · transition timeline · data-quality
  matrix (symbol × interval × check) · dependency graph (engine→db→broker→data).
- **Contract:** `GET /api/v1/state/legs`, `/api/v1/state/transitions`, `/api/v1/state/quality-matrix`.
- **States:** every leg `UNKNOWN` when the probe fails; matrix shows the *failing check name*, not a color.
- **Acceptance:** with a feed pulled, the matrix names the check and the leg names the probe.

### T2 `/book` — the book
- **Purpose:** positions, exposure, and P&L that reconcile with the broker.
- **Zones:** positions · exposure by symbol/sleeve/correlation bucket · realized/unrealized/attribution ·
  risk-budget consumption · drawdown governor tier · reconciliation status.
- **Contract:** `GET /api/v1/book/{positions,exposure,pnl,risk,reconciliation}`.
- **States:** `UNVERIFIED` when broker reconciliation is unavailable — **the honest P&L from the deduped
  trade record is a dependency, not an optional extra** (today's `useHonestTrades` / master-api gap is a
  first-class missing-data state, not a "Failed to fetch").
- **Acceptance:** internal P&L equals broker-derived P&L within tolerance, or the page says exactly which
  leg is unavailable and why.

### T3 `/decisions` — the decision ledger
- **Purpose:** every decision the system made, with its evidence, its authorizing verdict, and its outcome.
- **Zones:** decision table (time, symbol, direction, size, verdict id, reason codes, latency, cost) ·
  decision detail (evidence objects, agent trace, policy hash, data provenance) · outcome column
  (realized vs expected, slippage) · pending-approval queue (if human approval is ever re-enabled).
- **Contract:** `GET /api/v1/decisions`, `GET /api/v1/decisions/{id}`.
- **States:** a decision with no verdict id renders as `UNVERIFIED_DECISION` — an auditable red flag.
- **Acceptance:** any decision row is reconstructable from stored artifacts alone.

### T4 `/trades` — journal, reviews, post-mortems
- **Purpose:** learning surface. What we did, what happened, what we concluded.
- **Zones:** closed trades · R-multiple distribution · post-mortem list + editor · attribution by
  strategy/sleeve/regime · calibration (predicted vs realized) · tagged patterns.
- **Contract:** `GET /api/v1/trades/journal`, `/post-mortems`, `/attribution`, `/calibration`.
- **Acceptance:** every closed trade has a post-mortem or an explicit `unreviewed` flag; calibration
  scatter is computed server-side with a stated sample size.

### T5 `/evidence` — verdicts and validation
- **Purpose:** the single place where "do we believe this edge?" is answered.
- **Zones:** verdict table (symbol × family × verdict × metrics × as_of × expiry) · gate-v2 threshold
  panel (showing the *actual* constants: `PF_CI≥1.10`, `p_edge≥0.95/0.60`, `MC_DD≤5%/4%`,
  `fixed_PF≥1.20`, `DSR≥0.10`, `≥min OOS trades`) · trial/campaign accounting (n trials → deflation) ·
  adversarial-pass results · forward evidence (paper fills, slippage vs expectation) · scorecards.
- **Contract:** `GET /api/v1/evidence/verdicts`, `/gate-policy`, `/trials`, `/forward`, `/adversarial`.
- **States:** **`UNVERIFIED` is the loud state** — QQQ/AAPL/TSLA showing "no verdict on file" must be
  impossible to miss; SPY showing "REJECTED verdict, trading continues" must render as a red anomaly row,
  not a footnote.
- **Acceptance:** the options gap is visible on this page without any drilling.

### T6 `/research` — queue, registry, trials
- **Purpose:** what we're investigating, what it costs, what it concluded.
- **Zones:** research queue (ranked, with ROI/effort) · experiment registry · trial ledger (per campaign,
  cumulative) · LLM cost per experiment · promoted/rejected ledger · "what would change my mind" fields.
- **Contract:** `GET /api/v1/research/{queue,experiments,trials,costs}`.
- **Acceptance:** every experiment row links to a replayable artifact.

### T7 `/options` — volatility surface
- **Purpose:** SPY/QQQ/SPX/VIX structure, candidates, and honest availability.
- **Zones:** chain table · IV surface (strike × expiry heat) · term structure · skew · defined-risk
  candidate list (defined max loss, POP, breakeven, R:R) · VIX regime panel · **entitlement banner** when
  the data path is entitlement-blocked (the 354/10168/10197 class) — the page must never imply live
  options data it does not have.
- **Contract:** `GET /api/v1/options/{chain,surface,term,skew,candidates,availability}`.
- **Acceptance:** with no options entitlement, the page renders an explicit `UNAVAILABLE (entitlement)`
  state and zero option prices — not stale or synthetic values.

### T8 `/market` — context
- **Purpose:** the market's structure, not a prediction.
- **Zones:** session clock + RTH/Globex state · regime (trend/range classification with method + lookback) ·
  levels (ONH/ONL, prior day H/L/C, VWAP bands, value area, gaps) · auction/breadth context · watchlist
  with data quality · morning brief (machine-generated, with its own honesty block) · screener output.
- **Contract:** `GET /api/v1/market/{regime,levels,watchlist,brief,screener}`.
- **Acceptance:** a directional claim anywhere on this page carries its base rate and sample size, or it
  is not rendered (per the market-brief measurement-integrity rule).

### T9 `/ops` — operations
- **Purpose:** what is running, on which commit, under which supervisor, and what broke.
- **Zones:** service table (name, plane, supervisor, pid, uptime, restarts, commit, image digest) ·
  cron/loops with last-run + last-success + next-run · incidents timeline with post-mortem links · backup
  status **and last verified restore** · deploy truth (`what is deployed` vs `what is in git`).
- **Contract:** `GET /api/v1/ops/{services,loops,incidents,backups,deploys}`.
- **Acceptance:** "what is deployed" is answerable in one glance and matches git reality or flags the drift.

### T10 `/intel` — external evidence
- **Purpose:** Discord/X/news/sentiment as *sourced evidence*, with integrity visible.
- **Zones:** source integrity board (per source: last ingest, item count, dedupe rate, known gaps) ·
  curated feed · analyst commentary (Corey) with freshness · entity/topic clustering · provenance links.
- **Contract:** `GET /api/v1/intel/{sources,feed,commentary}`.
- **Acceptance:** every feed item links to its origin; a source that stopped ingesting is red, not silent.

### T11 `/alt` — crypto + prediction markets
- **Purpose:** isolated, explicitly non-core surfaces.
- **Zones:** crypto (perps spot, funding, basis) · Polymarket (markets, prices, orderbook, model-vs-market
  divergence).
- **Acceptance:** the page states plainly that these do not feed the core trading authority.

### T12 `/lab` — experimental
- **Purpose:** honest sandbox. Nothing here is a production claim.
- **Zones:** ThinkScript workspace · Strategy-C tooling · DOM/orderflow experiments · vault/notes view.
- **Acceptance:** every widget carries a persistent `EXPERIMENTAL` banner that cannot be dismissed.

### T13 `/admin` — flags, safety, audit
- **Purpose:** the only place a human can change system state — deliberately inconvenient.
- **Zones:** flags table (env/DB-backed, current value, default, last change, changed-by) · safety state
  (kill switch, limits, policy hash) — **read-only display** · audit log (append-only, filterable) ·
  config truth diff (env vs code default).
- **Write actions** (each requires typed confirmation + reason + writes an audit row):
  unlatch kill switch · toggle a flag · promote/demote a symbol's paper enablement.
  **Never exposed here:** risk thresholds, blocklist membership, live-trading enable. Those are
  `[safety-review]` PR surfaces, not UI toggles.
- **Acceptance:** no ambient toggle exists; every write is audited; the page cannot enable live trading.

---

## 8. Realtime, performance, and budgets

| Budget | Target | Enforcement |
|---|---|---|
| HUD first meaningful paint | < 1.5 s | Lighthouse CI + Playwright timing assertion |
| Interaction feedback | < 100 ms | Interaction-to-next-paint in Playwright |
| JS shipped to HUD route | < 250 KB gzip | `check-bundle-budget.mjs` (exists — extend per-route) |
| Stream latency (engine event → render) | < 250 ms p95 | Instrumented counter in the client, reported to `/metrics` |
| Polling requests per minute per client | **0** (stream only) | Network assertion in Playwright |
| Widgets per HUD | fixed (5 zones) | Code review + a route-composition test |

**Rendering strategy:** server components for static shells and tables that change slowly; client
components only for streaming zones; charts lazy-loaded per surface (lightweight-charts for price,
recharts only for small analytics) so the HUD never pays for `/options`' chart bundle.

---

## 9. Accessibility

- Keyboard-complete: every action reachable, visible focus ring, no keyboard traps.
- Contrast ≥ 4.5:1 for text, ≥ 3:1 for state chips (state must be legible, not decorative).
- **Never color alone:** every state chip carries a glyph and a text label (`▲ OK`, `● STALE`).
- Screen-reader labels on all metric values including provenance ("MES price 7,710.00, source IBKR,
  2 seconds old").
- Live regions for rail state changes (`aria-live="polite"`), assertive only for kill-switch transitions.
- Automated a11y gate (axe) in Playwright on all 14 surfaces; a11y regressions fail CI.

---

## 10. Testing strategy

| Layer | Tool | What it proves |
|---|---|---|
| Format/derive purity | node:test | Formatters and provenance rendering are deterministic |
| Component | vitest + Testing Library | `StatValue` renders every quality state correctly; no bare numbers |
| Contract | zod schema tests + a fixture generator | API shape changes break the build, not the page |
| E2E | Playwright | The 10-second test, the kill test, zero-polling, a11y, route coverage |
| Visual | Playwright screenshots per surface × {ok, stale, degraded, unavailable} | State rendering is stable and reviewed |
| Static | ESLint custom rules: `no-bare-numeric-render`, `no-client-metric-derivation`, `no-page-level-fetch-interval` | The laws in §1 are enforced by the build, not by discipline |
| Perf | bundle budget + Lighthouse budget | §8 holds |

**The kill test is the flagship test.** It programmatically degrades a leg in the engine and asserts the
entire chain — rail, zone, card, odds panel, reason code — updates within one event, with no refresh.

---

## 11. Migration plan (no big bang, no broken links)

**Order (each step ships independently and is reversible):**

1. **Foundations first** — tokens, `ui/` primitives, `StatValue`, provenance types, formatter consolidation.
   No route changes yet. Nothing user-visible breaks.
2. **Data layer** — add `/api/v1/hud/*` aggregate endpoints + the stream; keep every existing endpoint
   alive. The new layer runs *beside* the old one.
3. **HUD** — build `/` on the new layer. Old `/dashboard`, `/mission-control`, `/command-center*` remain
   functional (they are the rollback path).
4. **Surface-by-surface** — build T1…T13 one at a time. Each ships with: the new surface, a 301 from the
   absorbed routes, a Playwright spec, and a visual baseline.
5. **Retire** — after a surface has been live for two weeks with no rollback, delete its absorbed routes
   and their components. Archive, never delete, the component code (branch tag).
6. **Enforce** — turn on the ESLint laws, the no-polling assertion, the bundle budget per route, and the
   a11y gate as *required* checks.

**Redirect table (excerpt; full table in the work breakdown):**
`/dashboard → /` · `/mission-control → /` · `/command-center → /` · `/command-center-v2 → /` ·
`/trust-pane → /` · `/today → /` · `/health → /state` · `/data-integrity → /state` ·
`/portfolio → /book` · `/performance → /book` · `/stats → /book` · `/master/trading → /book` ·
`/signals → /decisions` · `/signal-outcomes → /decisions` · `/pipeline-board → /decisions` ·
`/validation → /evidence` · `/strategies → /evidence` · `/scorecard → /evidence` ·
`/trading-eligibility → /evidence` · `/regime → /market` · `/watchlist → /market` · `/config → /admin`.

**Component disposition:** of the 191 components, expect ~40 to survive largely intact, ~60 to be
rewritten as Tier-1/2 primitives, and ~90 to be deleted with their routes. The disposition table is part
of the work breakdown, produced by an automated route→component usage audit, not by hand.

---

## 12. UI anti-patterns this spec refuses

1. A number on screen with no source and no age.
2. `0` or `—` standing in for "unknown".
3. Client-side recomputation of a metric the engine already owns.
4. Two pages showing the same metric computed differently.
5. Per-widget polling intervals.
6. A generic error state instead of named, explained states.
7. Color as the only signal.
8. Hiding a missing verdict behind a green summary.
9. Any UI path that can change risk, blocklist, or live-trading state.
10. Adding a route instead of extending a surface.
11. Charts that imply precision the data cannot support (no interpolation across gaps, no unsampled
    smooth curves).
12. "Experimental" surfaces that don't say so.

---

## 13. Definition of done (UI)

1. 14 surfaces live; 44 routes retired with permanent redirects; every redirect tested.
2. The 10-second test passes with a real operator script, timed, on the operator box.
3. The kill test passes end-to-end via the stream with no refresh.
4. Zero polling requests; one stream connection per client.
5. Every numeric node carries provenance (static test) and every quality state has a rendered variant
   (visual baselines).
6. a11y: axe clean on all 14 surfaces; keyboard-complete; contrast verified.
7. Budgets from §8 enforced in CI.
8. The options-verdict gap and the SPY anomaly are visible on `/evidence` without drilling.
9. `pnpm run typecheck`, `test:unit`, `test:component`, `test:e2e`, `guards`, `budget` all green on a
   protected trunk.
10. A newcomer can answer "is JARVIS safe to trade right now?" in under ten seconds, unaided.

---

*Nothing in this document was implemented. No route was changed, no component deleted, no dependency
added. No credentials were read; no live-trading, risk, kill-switch, broker-routing, or symbol-gate change
was made or proposed for immediate execution.*
