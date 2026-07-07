# HANDOFF — 2026-06-29 — Vercel Dashboard Deploy, ngrok Tunnel, Two-Checkout Consolidation

**Author session:** `7f55c1dd` — Claude Opus 4.8 (1M context)
**Date:** 2026-06-29 (session spanned 2026-06-26 → 2026-06-29 wall-clock across continuations)
**Companion doc:** `CONVERSATION_2026-06-29_vercel-deploy-consolidation.md` (turn-by-turn history, secret-redacted)
**Primary memory:** `~/.claude/projects/C--Users-mattm/memory/project_vercel_dashboard_deploy_2026_06_29.md`
**Runbook (as-built):** `dashboard/DEPLOY_VERCEL.md` (rewritten this session)

**Checkouts in play (same repo, two clones of `github.com/mattamundson/jarvis-trader`):**
- **A — canonical / mine:** `C:\Users\mattm\ThinkorSwim\jarvis-trader`, branch `fix/corey-cache-stale-nodata`
- **B — peer / stale:** `C:\Users\mattm\master-jarvis\jarvis-trader`, branch `feat/tradingview-mcp-gamma-kraken`

> **Read-me-first orientation.** This document is exhaustive by request. If you only need the
> punchline: the public dashboard's `/hidden-pivots` route 404s because **two checkouts hand-deploy
> to one Vercel project and last-deploy-wins**; the peer's branch lacks the (uncommitted) page. The
> permanent fix is to stop hand-deploying and switch the Vercel project to **Git auto-deploy from a
> single production branch**. My branch (A) is pushed and ready; PR #160 is the path to `master`.
> Everything else below is depth.

---

## 0. Context — how this session arrived here

This was a multi-segment continuation session. The earlier (pre-compaction) arc had already:
- Deployed the jarvis-trader Next.js dashboard publicly to Vercel (`jarvis-trader-plum.vercel.app`).
- Stood up an ngrok tunnel so the Vercel-hosted frontend can reach the **local** engine on `:8010`.
- Refactored the engine call path to a **server-side proxy** so the engine API key never reaches the
  browser, and later added basic-auth injection when the tunnel started enforcing it.
- Added a live Price column to the Hidden Pivots page.
- Registered a `Jarvis-TunnelHealth` scheduled task to monitor the public path.

The continuation (this document's scope) began with the user asking for **recommendations**, then
worked through: executing the safe recommendations, diagnosing a `/hidden-pivots` 404, deciding how
to consolidate two competing checkouts, pushing the canonical branch, capturing memory, re-indexing
gbrain, and finally producing these handoff artifacts.

---

## 1. Session summary — what was accomplished, in order (expanded)

### Phase 1 — Recommendations triage
The user asked for next-step recommendations on the live dashboard. I produced a ranked list:
1. **Switch to Git auto-deploy** (highest leverage — eliminates the fragile manual `--archive=tgz`
   CLI path and, as later proven, the deploy race).
2. **Make the runbook match reality** (it still described an abandoned Cloudflare/Tailscale path).
3. **Lock down tunnel ownership + rotate two creds** (basic-auth + engine key) + confirm rate-limiting.
4. **Clean up the abandoned Tailscale serve/funnel config.**
5. **WebSocket live panels remote** (deferred mini-project).

The user approved executing **#2 and #4** immediately (the two I could do without their hands).

### Phase 2 — #4 Tailscale cleanup (turned out to be a no-op)
- Tried `tailscale serve status` — the **shared-resource-guard** PreToolUse hook BLOCKED it because
  the command text matches the `tailscale` resource and **peer sessions were live** and I had not
  claimed the resource. (The guard matches command *text*, so even a read is gated.)
- Claimed the lock: `claude-resource-lock.ps1 -Claim tailscale -Reason "..."`.
- Inspected: `tailscale serve status` and `tailscale funnel status` both returned **"No serve
  config."** The leftover port-8644 serve config from the earlier abandoned Tailscale attempt was
  already gone (cleared or expired). Nothing to reset.
- Released the lock. Net: **verified-clean, no action needed.**

### Phase 3 — #2 Runbook rewrite (`dashboard/DEPLOY_VERCEL.md`)
- The file still documented the Cloudflare quick-tunnel + named-tunnel and Tailscale paths that were
  **abandoned** (Tailscale Funnel was never enabled on the tailnet; Cloudflare quick-tunnels were
  ephemeral). The live reality is **ngrok-as-a-Windows-service** with a static domain.
- Rewrote the entire document to the as-built architecture (see §6 architecture deep-dive). Added:
  the 3-layer auth model, the three Vercel env vars, the proxy header injection, free-tier caveats
  (why the proxy sends `ngrok-skip-browser-warning`), the `Jarvis-TunnelHealth` monitor, the
  deploy-fragility notes, and a **"Preferred: Git auto-deploy"** section pointing at the durable fix.
- **Committed `d701868`** `docs(deploy): rewrite Vercel runbook to as-built ngrok + 3-layer auth`.

### Phase 4 — #3 Credential-rotation procedure (drafted + documented)
- Grounded the steps by **reading `%LOCALAPPDATA%\ngrok\ngrok.yml`** (to learn the `traffic_policy`
  basic-auth structure) and **grepping the dashboard** for every `ENGINE_API_KEY` / `X-API-Key`
  consumer. Found the engine key is consumed in **three** places that must rotate together:
  `engine/.env` (`API_KEY=`), `dashboard/.env.local` (`ENGINE_API_KEY`, local :3010 proxy), and the
  Vercel `ENGINE_API_KEY` env var (remote proxy).
- **Discovered the live ngrok basic-auth cred had already been rotated by a peer** (different from the
  earlier leaked value), which means the Vercel `ENGINE_TUNNEL_BASIC_AUTH` may already be out of sync
  → the public path could 401 until re-synced. This is the "rotation thrash" footgun.
- Wrote a "Credential rotation" section (A: ngrok basic-auth re-sync, B: engine key across 3
  consumers, C: single-owner convention via the resource lock), with **generate-locally / never-echo**
  discipline and no secret values.
- **Committed `c590ef1`** `docs(deploy): add credential-rotation section to Vercel runbook`.

### Phase 5 — ngrok shared-resource guard wiring (BLOCKED by classifier)
- Attempted to add an `ngrok` branch to `~/.claude/hooks/shared-resource-guard.sh` (so a peer
  restarting ngrok / editing `ngrok.yml` while another session holds the lock gets blocked — the same
  Tier-2.5 enforcement that gated my Tailscale command).
- The **auto-mode self-modification classifier denied the edit** ("Editing a hook script controlling
  the agent's own guard behavior … without an explicit user request naming this change"). Per policy
  I did **not** route around it via Bash/sed (that would defeat the guard's intent).
- Handed the **exact diff** to the user to paste manually (reproduced verbatim in §7).

### Phase 6 — The `/hidden-pivots` 404 diagnosis (the core investigation)
User reported `https://jarvis-trader-plum.vercel.app/hidden-pivots` returns **404**. Diagnostic chain:
1. **Characterized the response:** `curl -D -` on the route → `HTTP/1.1 404 Not Found`,
   `X-Vercel-Cache: HIT`, `Server: Vercel`. Root `/` → `HTTP/1.1 200 OK`, `X-Vercel-Cache: PRERENDER`.
   → A **cached 404 from Vercel's edge** = the route is genuinely absent from the deployment's routing
   manifest. NOT a 401 login gate, NOT a 500 build error. (Also notable: root returned 200 to an
   **unauthenticated** request → Deployment Protection is OFF; logged as a separate finding.)
2. **Localized the failure:** tested 6 routes — `command-center`, `today`, `health`, `portfolio`,
   `watchlist` all **200**; only `hidden-pivots` **404**. → The deployment is full and healthy; one
   single route is missing. A missing route segment (404 not 500) means the **page file was not present
   at build time** in whatever tree was packed.
3. **Confirmed the source is fine:** in checkout A, `dashboard/app/hidden-pivots/page.tsx` exists and
   is git-tracked; commit `5960aca` ("live Price column on Hidden Pivots page") is in history. So the
   source has it — the **deployed build** doesn't.
4. **Identified the live deployment:** `vercel inspect jarvis-trader-plum.vercel.app` →
   deployment **`a68h0kk8n`**, created ~12 min earlier, **by the peer** (`amoszn` account, but from
   checkout B's session). `vercel ls --prod` showed a long string of recent Ready deployments from
   both sessions.
5. **Proved the branch mismatch:** in checkout B (`feat/tradingview-mcp-gamma-kraken`),
   `git ls-files dashboard/app/hidden-pivots/` → **empty** (untracked), `git status --short` →
   `?? dashboard/app/hidden-pivots/`, and `git merge-base --is-ancestor 5960aca HEAD` → **NO**. So on
   the peer's branch the page is uncommitted and the Price-column commit isn't in history.
6. **Root cause:** both checkouts are clones of the same repo, **both linked to the one Vercel
   project**, and `vercel --prod --archive=tgz` is **last-deploy-wins on the shared alias**. The peer's
   deploy from B (no committed page) clobbered my earlier deploy from A (which had it) → 404.
7. **Scoped the branch divergence** to choose a consolidation: default branch is `master`; A is
   **152 behind / 70 ahead** of master; A and B share an old merge-base `4d99ef3` (A is 1169 ahead of
   it, B only 14). B's 14 unique commits: **13 are backend** (system2 / strategy-c / IBKR executor /
   backtest) that never enter the Vercel build; only `next.config.ts` is dashboard-relevant.
8. **Compared `next.config.ts`** between A and B: they took **opposite** approaches — A pins
   `outputFileTracingRoot` (Windows EINVAL fix) and does **not** suppress TS/ESLint; B suppresses
   TS/ESLint and **removed** `outputFileTracingRoot` (their commit claimed it caused `path0/path0` on
   Vercel). **Both deploy cleanly on Vercel in practice.** → A is the correct single source: it has
   the feature and builds honestly.

### Phase 7 — Consolidation decision + push
- Presented the user a 3-way choice (redeploy-now / consolidate-to-one-branch / leave-it). The user
  chose **"Consolidate to one branch."**
- Recommended **A as the single production source** with **Git auto-deploy** to structurally end the
  race. Got the green light to push.
- **Pushed A to origin:** `git push -u origin fix/corey-cache-stale-nodata` →
  `c820bbe..36c2b7c` (fast-forward; the local tip had advanced to `36c2b7c` via peer/automation
  commits on this shared branch since my doc commits). Branch now tracks origin and is **in sync**.
- **Verified the pushed tip:** `git ls-tree -r --name-only HEAD -- dashboard/app/hidden-pivots/` →
  `dashboard/app/hidden-pivots/page.tsx`; `git merge-base --is-ancestor 5960aca HEAD` → **YES**.
- **Confirmed PR #160 already exists** (`fix/corey-cache-stale-nodata → master`, "feat: HiddenPivots
  scan, self-improving morning brief, forecast journal, DSR fixes (clean #134 extraction)") via a
  backgrounded `gh pr list` (gh was hanging foreground). → No new PR needed; #160 is the master path.
- **Delivered the Vercel UI click-path** (re-enable Protection → connect Git → set Production Branch →
  confirm Root Directory → trigger first auto-deploy).

### Phase 8 — Memory + gbrain re-index
- Wrote `project_vercel_dashboard_deploy_2026_06_29.md` (full topology) + a one-line MEMORY.md index
  pointer under `## Recent (2026-06-29)` (cross-linked to `project_ngrok_jarvis_engine_tunnel_2026_06_26`).
- Re-indexed gbrain: the raw `:8077/ingest` POST failed (daemon busy mid-ingest → connection refused),
  but the on-demand retry tool `~/tools/gbrain-memory-ingest.ps1` succeeded — `[OK]` and link graph
  rebuilt **`link_count 2184 → 2188`** (+4, matching the new memory's 4 wikilinks). New memory is now
  searchable via `recall.ps1` / `/vault`.

### Phase 9 — Handoff artifacts (this request)
- Expanded this handoff; produced the secret-redacted conversation history; committed both into the
  repo under `docs/session-logs/` and pushed.

---

## 2. Files created or modified — full paths, what changed, why (expanded)

### Committed to git (checkout A, branch `fix/corey-cache-stale-nodata`, on origin)
| File | Commit | What & why |
|---|---|---|
| `dashboard/DEPLOY_VERCEL.md` | `d701868` | Full rewrite: abandoned Cloudflare/Tailscale → as-built ngrok service + 3-layer auth + env vars + proxy injection + monitor + fragility notes + Git-auto-deploy section. |
| `dashboard/DEPLOY_VERCEL.md` | `c590ef1` | Appended "Credential rotation" section (A/B/C). No secret values. |
| `docs/session-logs/HANDOFF_2026-06-29_vercel-deploy-consolidation.md` | (this commit) | This document. |
| `docs/session-logs/CONVERSATION_2026-06-29_vercel-deploy-consolidation.md` | (this commit) | Secret-redacted turn-by-turn conversation history. |

### Created outside git (under `~/.claude`, intentionally not in the repo)
| File | Purpose |
|---|---|
| `~/.claude/projects/C--Users-mattm/memory/project_vercel_dashboard_deploy_2026_06_29.md` | Project memory: deploy topology, the race, consolidation, watch-items. |
| `~/.claude/projects/C--Users-mattm/memory/MEMORY.md` | +1 index pointer under `## Recent (2026-06-29)`. |
| `~/.claude/handoffs/HANDOFF_2026-06-29_vercel-deploy-consolidation.md` | The first (shorter) handoff; this repo copy supersedes it in depth. |

### Modified earlier in the broader session (pre-continuation; context — verify via `git log`)
| File | Commit(s) | Change |
|---|---|---|
| `dashboard/app/api/engine/[...path]/route.ts` | `7ef9538`, `97b53a6`, `a91670a` | 60s proxy timeout; `ngrok-skip-browser-warning` header; server-side basic-auth injection from `ENGINE_TUNNEL_BASIC_AUTH`. |
| `dashboard/lib/api.ts` | `7ef9538`, `5960aca` | Stripped client-side engine key (no `NEXT_PUBLIC` leak); added `fetchPriceSnapshot`. |
| `dashboard/app/hidden-pivots/page.tsx` | `5960aca` | `PriceCell` component + live Price column (second SWR, 15s poll). |
| `dashboard/vercel.json` | `767c7b7` | `maxDuration: 60` for the proxy route. |
| `dashboard/.vercelignore` | `1f14843` | Excludes node_modules/.next/etc. **NOTE: not honored by Vercel CLI** → 4.8GB uploads. |
| `C:\Users\mattm\scripts\check-tunnel-health.ps1` | (not git-tracked) | Tunnel monitor worker for `Jarvis-TunnelHealth`. |

### Attempted but BLOCKED (not applied)
| File | Why blocked | Resolution |
|---|---|---|
| `~/.claude/hooks/shared-resource-guard.sh` | Auto-mode self-modification classifier | User pastes the diff in §7 manually. |

---

## 3. Current state — running / stopped / broken (expanded)

| Component | State | Detail |
|---|---|---|
| Vercel site (`jarvis-trader-plum.vercel.app`) | **UP, partly wrong** | Root + all tested routes 200; `/hidden-pivots` **404** because the alias targets the peer's deploy `a68h0kk8n` (built from branch B without the page). Not broken code — wrong branch on the air. |
| Vercel Deployment Protection | **OFF (security regression)** | Root returned 200 to an unauthenticated curl → the dashboard UI + prerendered/cached data are publicly readable. Data calls still require tunnel+key. |
| ngrok tunnel | **UP** | Windows service `ngrok` (Running/Automatic). Static domain `https://perioecic-piper-postsigmoid.ngrok-free.dev` → `127.0.0.1:8010`. Basic-auth in `ngrok.yml` `traffic_policy` (peer-rotated value; see §5). |
| Engine `:8010` | **Assumed UP** | Not re-verified this session (`/health` is the check per `rules/verification.md`). `Jarvis-TunnelHealth` (15-min) covers the public path. |
| `Jarvis-TunnelHealth` task | **Registered/Ready** | Runs `check-tunnel-health.ps1` via `notify-on-fail.ps1`; Telegram on failure; alert-only (no restarts). |
| gbrain ingest daemon `:8077` | **Up but intermittent** | Refused a one-shot POST while busy mid-ingest; the retry-tool completed. Use `~/tools/gbrain-memory-ingest.ps1`, not raw curl. |
| git / gh (this machine) | **Slow/hanging** | Repeated 2-min timeouts on `git status`, `git rev-list`, `gh pr list`, `gh auth status`. Background runs eventually complete. Latency, not corruption (likely peer git activity + large repo + GitHub API). |
| Bash tool shell | **Auto-backgrounding** | Even trivial commands background due to the slowness above. |

---

## 4. In-progress work — started but not finished (expanded)

1. **ngrok shared-resource guard wiring** — diff prepared and verified-by-design; BLOCKED by the
   self-modification classifier. The *only* code change from the consolidation plan not yet landed.
   Awaiting user paste (§7). Low risk; additive; verified by an echo test included.
2. **Consolidation to a single production branch** — branch pushed (`36c2b7c`), PR #160 open, but the
   **Vercel-side wiring** (Git connect + Production Branch + auto-deploy + Root Directory confirm) is
   NOT done — it requires the Vercel dashboard UI, which the agent cannot reach. Until then the alias
   race persists and `/hidden-pivots` remains 404 on the current alias.
3. **Handoff artifacts** — being committed/pushed in this final phase.

---

## 5. Blockers discovered — need resolution (expanded, with severity)

1. **[HIGH] `/hidden-pivots` 404 via alias race.** Resolved only when production becomes a single
   Git-auto-deployed branch. Until the Vercel UI step is done, any peer `vercel --prod` from B
   reclobbers the alias.
2. **[HIGH] Deployment Protection OFF.** Public exposure of the dashboard UI + prerendered/cached
   data. Fix: Settings → Deployment Protection → Vercel Authentication = On.
3. **[MED] Self-modification classifier blocks the agent** from editing `shared-resource-guard.sh`
   even with explicit user authorization. Workaround: user pastes the block (§7). (Consider adding a
   Bash permission rule in settings if this recurs.)
4. **[HIGH-sec] Leaked + thrashing ngrok basic-auth.** The leaked `jarvis:Ckd432…` (truncated) is
   stale; a peer rotated the live cred afterward. Because the peer rotated **after** the last Vercel
   deploy, `ENGINE_TUNNEL_BASIC_AUTH` on Vercel may already be out of sync → the public path can 401
   through the tunnel until re-synced. Rotate per runbook step A and re-sync Vercel.
5. **[HIGH-sec] Engine API key now public-facing** and handled in plaintext repeatedly this session.
   Rotate per runbook step B (3 consumers in lockstep) + `.\restart_engine.ps1`.
6. **[MED] `.vercelignore` not honored by Vercel CLI** → 4.8GB `--archive=tgz` uploads that
   occasionally fail extraction (BUILD_ERROR, empty message — typically when a peer dev server is
   bloating `.next/cache` mid-tar). Retired by Git auto-deploy.
7. **[LOW] git/gh latency** — slowed every VCS step; worked around via backgrounding. Watch for a
   stuck `.git/index.lock` from a crashed peer git process if it persists.
8. **[INFO] Multi-session contention is the meta-theme.** The same two-session dynamic produced both
   the ngrok cred thrash and the deploy race. Single-owner conventions (resource lock for ngrok;
   single production branch for deploys) are the structural fixes.

---

## 6. Architecture deep-dive (so the next session needs no external context)

### 6.1 Request path & 3-layer auth
```
Browser ── HTTPS ──► Vercel (Deployment Protection login gate)   [LAYER 1]
                       │  app/api/engine/[...path]/route.ts  (runtime "nodejs", server-side)
                       │  injects, server-side only:
                       │    X-API-Key:      ENGINE_API_KEY                 [LAYER 3 cred]
                       │    Authorization:  Basic base64(ENGINE_TUNNEL_BASIC_AUTH)  [LAYER 2 cred]
                       │    ngrok-skip-browser-warning: true
                       ▼
              ngrok tunnel (public HTTPS, static domain, basic-auth enforced)   [LAYER 2]
                       ▼
              Local PC ── engine :8010  (X-API-Key on every non-/health route)  [LAYER 3]
```
- **Layer 1 — Vercel login gate** (Deployment Protection): gates who loads the site. Currently OFF.
- **Layer 2 — ngrok basic-auth**: gates who reaches the tunnel. Cred in `ngrok.yml` `traffic_policy`.
- **Layer 3 — engine X-API-Key**: gates the engine itself; `/health` is auth-exempt.
- The **browser carries none of these** — the proxy adds Layers 2 & 3 server-side. `dashboard/lib/api.ts`
  was deliberately stripped of any client-side key so nothing leaks into the browser bundle.

### 6.2 The proxy (`dashboard/app/api/engine/[...path]/route.ts`)
- `runtime = "nodejs"`, `dynamic = "force-dynamic"`. Catch-all that forwards GET/POST/PUT/PATCH/
  DELETE/OPTIONS to `ENGINE_INTERNAL_URL` (falls back to `ENGINE_URL_INTERNAL`, then localhost).
- Strips hop-by-hop headers, injects `X-API-Key` (from `ENGINE_API_KEY` || `NEXT_PUBLIC_ENGINE_API_KEY`),
  `ngrok-skip-browser-warning: true`, and (if set) `Authorization: Basic …` from `ENGINE_TUNNEL_BASIC_AUTH`.
- **60s AbortController timeout** — cold engine endpoints (TV/yfinance prices, mtf, discord intel) and
  the ~33-symbol Hidden Pivots scan exceed the prior 25s and were 502ing right after engine restarts.

### 6.3 The tunnel (ngrok)
- **Static domain** `https://perioecic-piper-postsigmoid.ngrok-free.dev` → `127.0.0.1:8010`.
- Config `%LOCALAPPDATA%\ngrok\ngrok.yml`: version "3", agent authtoken (`<REDACTED>`), tunnel
  `jarvis-engine` (`proto: http`, `addr: 8010`, the static `url`, and a `traffic_policy` →
  `on_http_request` → `basic-auth` with `realm "JARVIS Engine"` and `credentials: ["jarvis:<REDACTED>"]`).
- **Windows service** (`Get-Service ngrok` = Running/Automatic) + idempotent logon launcher
  `~/scripts/launch-ngrok-jarvis.ps1` via `Jarvis-Ngrok-AtLogon`.
- **Free-tier caveats**: 1 concurrent agent session (a second `ngrok start` kills the first,
  `ERR_NGROK_3200`); browser-warning interstitial (bypassed by the proxy header); bandwidth/request
  caps. CLI `ngrok http` ignores the config's `traffic_policy` — auth only via `ngrok start jarvis-engine`.

### 6.4 Vercel project
- Project `matts-projects-fc4f64e1/jarvis-trader`; alias `jarvis-trader-plum.vercel.app`;
  both checkouts' `dashboard/.vercel/project.json` point at `prj_U1ZIRR4wPJo0BMfBrSqfgpbpbXIS`.
- Production env vars: `ENGINE_INTERNAL_URL` (ngrok URL), `ENGINE_API_KEY` (Sensitive),
  `ENGINE_TUNNEL_BASIC_AUTH` (Sensitive, `user:pass`). Set via `vercel env add NAME production --sensitive`
  (the `--sensitive` flag avoids the interactive "Store as sensitive?" prompt that fouls piping).
- Deploy today: `vercel --prod --archive=tgz` (the `--archive=tgz` is required because `.vercelignore`
  is not honored and a plain deploy hits the 15000-file limit; the archive is ~4.8GB). **This is what
  Git auto-deploy retires.**

### 6.5 WebSocket limitation (deferred feature)
- `lib/engine-websocket-context.tsx`, `hooks/useWebSocket.ts`, `lib/pipeline_ws.ts` connect directly
  to the engine WS and cannot traverse the Vercel serverless proxy. They degrade gracefully and work on
  the local :3010 dashboard. Remote support needs **engine-side short-lived WS token auth** (deferred
  to avoid putting a long-lived key in the browser).

---

## 7. Key decisions made — architecture / values / tradeoffs (expanded)

1. **A (`fix/corey-cache-stale-nodata`) is the canonical dashboard production source.** It has the
   HiddenPivots page committed (incl. Price column `5960aca`), builds honestly (does not suppress
   TS/ESLint), and pins `outputFileTracingRoot`. B's unique value is backend, not dashboard.
2. **Fix the race structurally via Git auto-deploy — not another hand-deploy.** The user explicitly
   chose "Consolidate to one branch" over "Redeploy my branch now," precisely to stop the ping-pong.
   With Git auto-deploy, the peer's `vercel --prod` from B lands as a **preview** (not production),
   so it cannot clobber the alias.
3. **Two valid production-branch options, decision deferred to user:**
   - **Fast:** Production Branch = `fix/corey-cache-stale-nodata`. Fixes the 404 as soon as auto-deploy
     is wired. Reversible later.
   - **Proper:** merge PR #160 → `master`, then Production Branch = `master`. Cleaner long-term; the
     peer's backend work consolidates onto master via its own PR track.
4. **Did NOT force-merge the two divergent branches.** Per `rules/git-hygiene.md` (surface, don't
   reflexively merge) and because a peer was actively on B. The backend on B (13 commits) belongs on
   master through the peer's own PR; it never affected the dashboard build.
5. **Credential discipline: generate locally, never echo, rotate all consumers together.** The engine
   key has 3 consumers that must move in lockstep; partial rotation 401s one of them.
6. **ngrok treated as a guarded shared resource** (free tier = 1 session; peer rotation desyncs
   Vercel) → guard wiring + lock-before-mutate convention.
7. **Conversation-history upload is secret-redacted.** A verbatim transcript would commit live
   credentials to GitHub (forbidden by `rules/secret-hygiene.md`; the pre-commit scanner would block
   it). The redacted version preserves the narrative; the raw transcript stays local.
8. **Per-file, race-safe commits only.** This is a shared dirty checkout (7–8 peers historically);
   never `git add -A`; commit handoff files by explicit pathspec.

### The exact ngrok guard block to paste (Phase 5 blocker)
Open `~/.claude/hooks/shared-resource-guard.sh`; insert IMMEDIATELY ABOVE the generic-service branch
(the `elif … (Restart|Stop|Start)-Service\b … then` with the `# Generic service op` comment):
```bash
elif printf '%s' "$scan" | grep -qiE '\bngrok(\.exe)?\b[[:space:]]+(start|http|service|tcp|tunnel)\b' \
   || printf '%s' "$scan" | grep -qiE '(Restart|Stop|Start)-Service\b[^|]*ngrok' \
   || printf '%s' "$scan" | grep -qiE '\b(net|sc)(\.exe)?[[:space:]]+(stop|start)[[:space:]]+["'\'']?ngrok' \
   || printf '%s' "$scan" | grep -qiE 'ngrok\.yml'; then
  # ngrok tunnel that fronts the engine for the public Vercel dashboard. Free tier
  # allows ONE agent session; a peer (re)starting it or rotating ngrok.yml's basic-auth
  # is what desyncs ENGINE_TUNNEL_BASIC_AUTH and 401s the site. Claim before mutating.
  resource="ngrok"
```
Verify (solo session → exit 0; with a live peer and no claim → exit 2):
```powershell
echo '{"tool_name":"PowerShell","tool_input":{"command":"Restart-Service ngrok"},"session_id":"test"}' | bash ~/.claude/hooks/shared-resource-guard.sh; echo "exit=$LASTEXITCODE"
```

---

## 8. TODO — planned but not started (expanded; all user-side or user-gated)

**Vercel UI (user — agent cannot reach it). Project: matts-projects-fc4f64e1/jarvis-trader.**
1. **[urgent] Re-enable Deployment Protection** — Settings → Deployment Protection → Vercel
   Authentication = On (Standard) → Save → verify incognito shows the login gate.
2. **Connect Git + set Production Branch** — Settings → Git → connect `mattamundson/jarvis-trader`;
   Production Branch = `fix/corey-cache-stale-nodata` (fast) or `master` after #160 merges (proper);
   confirm Build → Root Directory = `dashboard`.
3. **Trigger first auto-deploy** — auto on connect, or Deployments → ⋯ → Redeploy, or push a commit;
   then verify `/hidden-pivots` loads behind the gate.

**Hook (user paste):** add the ngrok block to `shared-resource-guard.sh` (§7) and run the verify echo.

**Credential rotation (user; steps A/B/C in `dashboard/DEPLOY_VERCEL.md`):**
- A: rotate ngrok basic-auth in `ngrok.yml`; re-sync Vercel `ENGINE_TUNNEL_BASIC_AUTH`; `Restart-Service ngrok`.
- B: rotate engine API key across `engine/.env`, `dashboard/.env.local`, Vercel; `.\restart_engine.ps1`.
- C: designate ONE ngrok owner; claim the `ngrok` resource lock before editing config.

**Decision:** production branch = the fix branch (now) vs `master` (after merging PR #160).

**Deferred features:** remote WebSocket live-tick panels (engine-side short-lived WS token auth);
engine API key 90-day rotation cadence; (optional) ngrok account authtoken rotation if `ngrok.yml` is
ever exposed; engine-side rate-limiting confirmation on the public path (`slowapi`).

---

## 9. Full current to-do list

No formal TaskCreate list was used. Working to-do (all user-side / user-gated; nothing left the agent
can execute unblocked):

- [ ] (user, urgent) Re-enable Vercel Deployment Protection
- [ ] (user) Connect Git + set Production Branch + confirm Root Directory = dashboard (kills race + 404)
- [ ] (user) Trigger first auto-deploy; verify `/hidden-pivots` loads
- [ ] (user) Paste the ngrok block into `shared-resource-guard.sh` (+ run the verify echo)
- [ ] (user) Decide production branch: `fix/corey-cache-stale-nodata` vs `master` (via PR #160)
- [ ] (user) Rotate ngrok basic-auth (re-sync Vercel) — runbook step A
- [ ] (user) Rotate engine API key across 3 consumers — runbook step B
- [ ] (user) Designate single ngrok owner — runbook step C
- [ ] (later) Merge PR #160 → master for the proper-master production path
- [ ] (deferred) Remote WebSocket panels; engine key 90-day rotation; ngrok authtoken rotation; rate-limit check

**Done this session:** runbook rewrite (`d701868`) · rotation section (`c590ef1`) · branch pushed
(`36c2b7c`) · Tailscale leftover verified clean · 404 diagnosed (alias race, full evidence trail) ·
Vercel click-path delivered · memory written + gbrain re-indexed (link_count 2184→2188) · these
handoff + conversation artifacts committed and pushed.

---

## 10. Git state

> `git status --short`, `git log --oneline -20`, `git diff --stat` for checkout A
> (`C:\Users\mattm\ThinkorSwim\jarvis-trader`, branch `fix/corey-cache-stale-nodata`).
> Captured via background run (foreground git hit the 2-min cap). Verbatim:

```
=== BRANCH ===
fix/corey-cache-stale-nodata

=== git status --short ===
 M .gitignore
 M dashboard/dashboard.code-workspace
 M docs/reports/METRICS_SNAPSHOT.json
 M engine/data/forecast_reports/2026-06-25.md
?? dashboard/AGENTS.md
?? docs/architecture/DASHBOARD_PAGE_ROUTER_MAP.md
?? docs/reports/tearsheets/2026-06-27_07-00_paper_paper.html
?? engine/backtest/run_mes_vwap_rank1.py
?? engine/backtest/vwap_paper_track.py
?? engine/data/forecast_reports/2026-06-26.md
?? engine/data/forecast_reports/2026-06-27.md
?? engine/data/forecast_reports/2026-06-28.md
?? engine/data/forecast_reports/calibration_2026-06-28.md
?? engine/data/morning_forecasts/2026-06-26.json
?? engine/data/morning_forecasts/2026-06-27.json
?? engine/data/morning_forecasts/2026-06-28.json
?? engine/data/morning_forecasts/2026-06-29.json
?? engine/data/vec_index.db.tmp
?? engine/systematic/
(+ this commit adds docs/session-logs/HANDOFF_2026-06-29_*.md and CONVERSATION_2026-06-29_*.md)

=== git log --oneline -20 ===
36c2b7c data(discord): 2026-06-27 digest
8bd65d3 data(discord): 2026-06-26 digest
c590ef1 docs(deploy): add credential-rotation section to Vercel runbook
d701868 docs(deploy): rewrite Vercel runbook to as-built ngrok + 3-layer auth
54ada57 feat(autonomous): opt-in paper-only auto-approve (default OFF) (#173)
e82fe8e data(discord): 2026-06-25 digest
c820bbe fix(market_data): map MHG (COMEX) and MYM (CBOT) futures exchanges
a91670a feat(dashboard): proxy injects tunnel basic-auth server-side
40e9f96 fix(market_data): map ZB/ZN (CBOT) futures exchange — unfreeze bond bars
f359240 test(corey,harmonic): cover guardrail branches + prove harmonic detector fires
5960aca feat(dashboard): live Price column on Hidden Pivots page
1386713 feat(corey): signal-propagation guardrail for trade_outcomes
2898aa1 feat(corey): on-demand session-bias extract viewer
aa3f9bb feat(backtest): H1/H2 chronological stationarity gate (library + wrapper)
97b53a6 fix(dashboard): bypass ngrok browser-warning interstitial in proxy
1f14843 chore(dashboard): .vercelignore + Cloudflare deploy runbook
a438098 fix(paper-config): disable MGC — enabled on a now-FAIL rank4 verdict
1905852 docs(env): point DISCORD_TOKEN at 1Password canonical store
d0f7d91 fix(corey): re-extract stale no-data bias cache on backfilled commentary
767c7b7 chore(dashboard): Vercel deploy config + runbook

=== git diff --stat (unstaged) ===
 .gitignore                                 |  3 +++
 dashboard/dashboard.code-workspace         | 16 +++++++++++-
 docs/reports/METRICS_SNAPSHOT.json         | 40 +++++++++++++++---------------
 engine/data/forecast_reports/2026-06-25.md |  6 ++---
 4 files changed, 41 insertions(+), 24 deletions(-)

=== git diff --stat --cached (staged) ===
(empty — nothing staged at capture time)

=== origin sync (origin/fix/corey-cache-stale-nodata...HEAD, behind/ahead) ===
0	0   (in sync with origin at capture time)
```

**IMPORTANT — the dirty working tree is NOT this session's work.** This is a shared checkout; the
` M`/`??` entries (forecast_reports, morning_forecasts, `run_mes_vwap_rank1.py`, `vwap_paper_track.py`,
`engine/systematic/`, `.gitignore`, code-workspace, METRICS_SNAPSHOT) are peer-session and
scheduled-task artifacts (VWAP shadow, morning-brief/forecast journal, exec-bridge). **Do NOT
`git add -A`.** This session's commits are `d701868`, `c590ef1`, and the two handoff docs added now —
all staged by explicit pathspec. Leave the rest for their owning sessions.

---

## 11. Suggested next action

Do Vercel UI **#1 (re-enable Deployment Protection)** then **#2 (connect Git + set Production
Branch)** — that single pair both closes the public-exposure hole and fixes the `/hidden-pivots` 404
by ending the alias race. Then paste the ngrok guard block (§7) and schedule the credential rotation
(runbook A/B). Merging PR #160 → `master` (and switching Production Branch to `master`) is the
clean long-term finish.
