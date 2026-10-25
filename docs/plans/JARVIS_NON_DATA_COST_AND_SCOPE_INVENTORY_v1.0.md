# JARVIS Non-Data Cost & Scope Inventory (v1.0)

**Authored:** 2026-09-23 · **Status:** INVENTORY ONLY — nothing purchased, provisioned, or changed.
**Scope question answered:** *"Make sure you are scoping out everything else."*
**Relationship to the other docs:** the **$100–200/mo data** budget is covered in
`JARVIS_DATA_BUDGET_ALLOCATION_100-200_v1.0.md` and `JARVIS_OPTIONS_FUTURES_DATA_MATRIX_v1.0.md`.
**This document is every non-data cost and every non-data scoping decision.** Prices are `[ASSUMPTION]` bands
unless sourced.

---

## §1. What I had NOT scoped (the honest gaps)

Writing this inventory against the actual repo/account surfaces turned up eight things the rebuild blueprint and
the tier analysis both missed:

| # | I had not scoped | Verified evidence | Why it matters |
|---|---|---|---|
| 1 | **Vercel** (dashboard deploy/preview) | `dashboard/vercel.json`, `dashboard/DEPLOY_VERCEL.md`; PR #913 showed Vercel deployments + preview comments | The architecture decision memo (2026-09-15) says JARVIS should stay **local-first**; a public Vercel deploy is a *different* posture and needs an explicit decision |
| 2 | **Supabase** (live project) | PR check: `supabase.com/dashboard/project/kkcwiocdncnxsphfcerw/branches` | A hosted DB project exists; the blueprint assumed SQLite → local Postgres with no hosted service |
| 3 | **Voyage AI** (gbrain embeddings + `rerank-2.5`) | `.claude/CLAUDE.md` + second-brain `AGENTS.md` (voyage-finance-2, 1024-dim) | Recurring paid API in the *knowledge* plane; the blueprint's L7 only listed LLM inference |
| 4 | **Twilio WhatsApp** (per-message) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` in `engine/.env` | The only notification channel with a marginal cost per alert — relevant to the blueprint's "alert by cause, no spam" rule |
| 5 | **1Password** (`Amo Personal` vault canonical) | `.claude/CLAUDE.md` non-negotiable #5; `scripts/load-secrets.ps1`, `manage-jarvis-secrets.ps1`, `dpapi-secret-store.ps1`, `credential-rotation-log.ps1` | The secrets layer the blueprint's L9 assumes already exists and is paid |
| 6 | **Dev-tooling subscriptions** (Cursor, Claude Code / Codex CLI) | `.claude/` skills, `~/.Codex/handoffs/`, session manifests | These are the *build capacity* — arguably the largest real line, and nowhere in any cost model |
| 7 | **Hermes agent token spend** | This loop itself; nightly/night-shift loops | The agent that executes the rebuild bills tokens while it works |
| 8 | **The ops surface: ~20+ scheduled tasks** | `schtasks`: `Jarvis-*` and `Hermes-*` tasks (BarReconcile, AlertSelfTest, BrainDaemon + Watchdog, SnapshotWeekly, NightlySync, PS-Estate-Watchdog, WSL-KeepAlive, …) | The rebuild's L11 self-healing loops must **inherit or replace** these, not ignore them |

**Consequence:** the blueprint's cost model was data-complete and **operations-incomplete**. This document closes
that.

---

## §2. Complete non-data inventory

| Cat | Item | Current → target | $/mo low | $/mo high | One-off |
|---|---|---|---:|---:|---:|
| **A** | Trading host (dedicated Linux mini-PC or small VM) | Win11 shared box → **dedicated** | 20 | 120 | $700–2,000 |
| **A** | Research-plane burst (spot CPU/GPU) | same box → **isolated** | 50 | 400 | — |
| **A** | Vercel (dashboard deploys/previews) | free tier → decide | 0 | 20 | — |
| **A** | Supabase (`kkcwiocdncnxsphfcerw`) | free tier → **decide keep/drop** | 0 | 25 | — |
| **A** | UPS + network hardware | none → with host | 0 | 0 | $150–400 |
| **B** | Object storage, immutable RAW (R2/S3) | none → **required (P2)** | 10 | 200 | — |
| **B** | Off-box backups / PITR target | local only → **required** | 10 | 100 | — |
| **B** | Local disk headroom (**9.6 GB free today**) | AT RISK → ≥15% free | 0 | 0 | $0–300 |
| **C** | Anthropic / OpenAI / Google / Moonshot APIs | 4 keys live → unchanged | 0 | 800 | — |
| **C** | Voyage AI (gbrain embed + rerank) | in use → unchanged | 0 | 150 | — |
| **C** | Local Ollama fallback | in use → unchanged | 0 | 0 | — |
| **C** | Cursor (UI lane) | in use → unchanged | 20 | 60 | — |
| **C** | Claude Code / Codex CLI (agent lanes) | in use → unchanged | 0 | 200 | — |
| **C** | Hermes agent token spend | in use → unchanged | 0 | 300 | — |
| **D** | Prometheus + Grafana (self-host vs cloud) | metrics only → **required (P8)** | 0 | 300 | — |
| **D** | Sentry-class error tracking | none → optional | 0 | 30 | — |
| **D** | Twilio WhatsApp (per message) | in use → unchanged | 1 | 15 | — |
| **D** | Discord / Telegram / Windows toast | in use → unchanged | 0 | 0 | — |
| **E** | 1Password (`Amo Personal`) | in use → unchanged | 3 | 8 | — |
| **E** | GitHub Actions (18 `ubuntu-latest` workflows) | **BILLING BLOCKED** → restored | 0 | 100 | — |
| **E** | GitHub repo (private) | in use → unchanged | 0 | 4 | — |
| **E** | Secret scanning / pre-commit hooks | local scripts → unchanged | 0 | 0 | — |
| **F** | OSS stack (Nautilus, vectorbt, Postgres, Timescale, Redis, Next, DuckDB) | in use → unchanged | 0 | 0 | — |
| **F** | Managed orchestration (Prefect/Dagster) *if adopted* | APScheduler → self-host | 0 | 500 | — |
| **G** | IBKR paper (commissions only when live) | free/paper → unchanged | 0 | 10 | — |
| **G** | Alpaca paper | free → unchanged | 0 | 0 | — |
| **H** | Tailscale + TLS | free tier → unchanged | 0 | 10 | — |
| **H** | Domain names | none → optional | 1 | 4 | — |
| | **TOTALS** | | **115** | **3,356** | **$850–2,700** |

**$1,380–$40,272/yr recurring, plus $850–$2,700 one-off.**

---

## §3. The number that actually matters

| Bucket | $/mo | Note |
|---|---:|---|
| **Bare minimum to make the rebuild safe** (object storage + backups + CI restored + secrets) | **$23–412** | storage/backup are the new lines; CI/secrets are already paid |
| **Already-paid lines** (LLM, Voyage, Cursor, agent lanes, messaging, 1Password, GitHub, broker) | **$24–1,977** | existing burn — the rebuild changes none of it |
| **Net NEW from the rebuild** (trading host + research burst + storage + observability) | **$91–1,379** | this is what the rebuild *adds* |

**Honest reading:** the largest non-data line is **not infrastructure — it is AI/dev tooling** (up to ~$1,360/mo at
the top of the band: LLM APIs $800 + Hermes tokens $300 + Cursor $60 + agent CLIs $200). Infrastructure is
$91–1,379/mo, and the *safe minimum* is ~$23–412/mo.

That means: **the rebuild's incremental infrastructure cost is smaller than the tooling you already run.** The
real scoping risk was never money — it was that eight live services and ~20 scheduled tasks were invisible in
the plan.

---

## §4. Conflict to resolve: Vercel + Supabase vs the local-first decision

The 2026-09-15 architecture memo (`AMO_ARBITRAGE_VS_JARVIS_ARCH_DECISION_2026-09-15.md`) concluded:

> *JARVIS dashboard should stay local-first / PM2-supervised / Tailscale-auth-gated as the primary operating
> pattern. It is a trading control surface connected to a local FastAPI engine… do not force JARVIS into the
> managed-cloud pattern.*

Yet the repo carries **`dashboard/vercel.json`** and live **Vercel** deployments with preview comments, plus a
live **Supabase** project, and PR #913 showed both running.

These are not necessarily in conflict — a *preview* deploy of the dashboard on a PR is harmless if it carries no
auth'd control-plane data — but the rebuild must answer three questions explicitly:

1. **Does the Vercel deployment carry any authenticated control-plane surface** (positions, kill-switch,
   approvals)? If yes, that is a security decision, not a hosting preference.
2. **Is Supabase in the data path for JARVIS**, or is it a leftover from an experiment? (The blueprint's target
   store is Postgres+TimescaleDB on the trading host.)
3. **Should PR previews keep deploying the dashboard at all** while the dashboard is being rebuilt surface-by-surface?

**Recommendation:** keep Vercel strictly for **public, non-authenticated** pages (e.g. a market-brief-public style
surface) and keep every control-plane surface local + Tailscale. Put the Supabase disposition in the P0 hygiene
list (retire or document, don't leave ambiguous).

---

## §5. What the rebuild adds that must be scoped (not optional)

| Rebuild item | Phase | Non-data cost | Note |
|---|---|---|---|
| Dedicated trading-plane host | P1 | $20–120/mo + $700–2,000 one-off | The single highest-value infra purchase |
| Object storage for immutable RAW | P2-2 | $10–200/mo | Required for replayability (invariant #4) |
| Postgres 16 + TimescaleDB | P2-1 | $0 self-hosted on the host | Managed = $200–2k/mo, not needed |
| Redis | L2 | $0 | already present |
| Observability (Prometheus already exported) | P8 | $0 self-hosted → $300/mo cloud | `prometheus-fastapi-instrumentator` is already installed |
| Off-box backup + restore drill | P8-5 | $10–100/mo | A backup never restored is a hope |
| CI restored | P0-8 | $0–100/mo | **currently blocking every PR** |
| Orchestration | P2/P8 | $0 (harden APScheduler) | Do **not** adopt Prefect/Dagster Cloud ($500/mo) for a single-operator system |
| Secrets vault injection + rotation | X-1 | already paid | 1Password is canonical; keep it |

---

## §6. Free, and stays free

| Service | Why it stays at $0 |
|---|---|
| Discord (bot, webhooks), Telegram, Windows toast | No per-message cost |
| Tailscale (single-user tier), TLS via Let's Encrypt | Sufficient for one operator |
| Alpaca paper, IBKR paper | No cost while paper-only |
| OSS stack — NautilusTrader, vectorbt, pandas/Polars, DuckDB, Postgres/Timescale, Redis, Next.js, Chromium/Playwright | All open source |
| Local Ollama | CPU fallback when a cloud provider is down |
| Local secret scanning + pre-commit hooks | Already built in `~/scripts/` |
| RAG layer (Chroma + ONNX MiniLM) | Local, no API |
| Grafana/Prometheus self-hosted | Runs on the host you're already buying |

**Do not pay for:** managed Postgres, managed orchestration, Kubernetes, a second observability SaaS, per-seat
anything, or hosted CI beyond Actions minutes.

---

## §7. Decisions needed (ranked)

| # | Decision | Cost impact | Owner |
|---|---|---|---|
| 1 | **Trading-plane host: buy dedicated hardware or rent a small VM?** | $700–2,000 one-off vs $20–120/mo | Amo |
| 2 | **Vercel/Supabase disposition** (§4) | $0–45/mo + a security call | Amo |
| 3 | **Restore GitHub Actions billing** | $0–100/mo — **currently blocks all CI** | Amo |
| 4 | **Object storage + backup target** (R2/S3 + off-box) | $20–300/mo | Amo |
| 5 | **Observability: self-host Grafana or stay metrics-only?** | $0 vs $300/mo | Agree: **self-host** |
| 6 | **Disk headroom**: clean up vs add storage | $0 vs $0–300 | Execute P0-1 |
| 7 | **Cap the AI/dev tooling band** | up to $1,360/mo | Amo (existing spend) |

---

## §8. Bottom line

- **Data:** $100–200/mo — separately budgeted, covered in its own document.
- **Bare-minimum non-data to make the rebuild safe: ~$23–412/mo.**
- **Net-new non-data from the rebuild: ~$91–1,379/mo**, dominated by the trading-plane host and observability.
- **Largest existing non-data line is AI/dev tooling** (up to ~$1,360/mo) — already being paid, unchanged by the
  rebuild.
- **The eight unscoped items in §1 are now scoped**, and the two live hosted services (Vercel, Supabase) need an
  explicit disposition rather than being left ambiguous.
- **Nothing here changes the data recommendation or the pilot sequencing.** The pilot stays the first move
  because it is $0 and it decides whether the rest is worth building.

---

*Nothing purchased or provisioned. Prices are `[ASSUMPTION]` bands unless a source is named. No credentials were
read or written. No live-trading, risk, kill-switch, broker-routing, or symbol-gate change was made or proposed.*
