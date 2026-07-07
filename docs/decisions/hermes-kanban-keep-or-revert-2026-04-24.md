# Decision Brief: hermes-kanban — Keep, Revert, or Defer?

**Date**: Friday 2026-04-24 09:58 CT
**Author**: Claude (system32 session)
**For**: Matt
**Deadline**: Before next overnight window (tonight ~02:00 CT)

## TL;DR

A peer Claude session at 02:42 CT this morning cloned `GumbyEnder/hermes-kanban`, patched two upstream bugs, and deployed the plugin + 3 skills. My subsequent audit surfaced 3 rejection-gate failures + one partial-fix risk. **Plugin is deployed but NOT yet enabled in Obsidian** — which means nothing is running. You have a clean opt-in moment before anything touches your vault.

Three options, ranked by effort:

| Option | Effort | Upside | Downside |
|---|---|---|---|
| **A. Keep** (enable + monitor) | ~1h | Hermes gets Kanban project-executor capability | No license; single-author 2-day-old repo; partial bind-fix risk |
| **B. Revert** (delete files, use bare `mgmeyers/obsidian-kanban`) | ~30min | Clean slate; keep community Kanban plugin | Lose auto-executor bridge |
| **C. Defer** (leave as-is, disabled) | 0 | No action needed | Debt carries forward, clutters vault |

**My recommendation**: **B. Revert**, unless you have a specific use case you want the auto-executor for in the next 30 days. The risk profile of a 2-day-old un-licensed single-author repo doesn't justify the capability on a trading-infra machine. Stars are 80 but repo age is 2 days → looks brigaded.

## What Peer Session Did (02:42 CT)

From `~/.claude/projects/C--windows-system32/memory/MEMORY.md` line 7:

- Cloned `GumbyEnder/hermes-kanban`
- Patched 2 upstream bugs:
  1. Added missing `startNotifier(intervalMinutes)` / `stopNotifier()` methods to `plugin/src/server.ts` (main.ts called them; they didn't exist)
  2. Changed server bind from `0.0.0.0` to `127.0.0.1` to prevent LAN exposure of the un-authenticated REST API
- Built (tsc + esbuild) → deployed `main.js` (47KB) + `manifest.json` to `master-jarvis\second-brain\.obsidian\plugins\hermes-kanban-bridge\`
- Deployed 3 skills (kanban-orchestrator, kanban-rituals, project-breakdown-to-kanban) to `/root/.hermes/skills/productivity/`
- Did NOT auto-download `mgmeyers/obsidian-kanban` visual renderer (permission policy)

## My Audit Findings (09:58 CT)

### ✅ Deployment State Confirmed

- `C:\Users\mattm\master-jarvis\second-brain\.obsidian\plugins\hermes-kanban-bridge\main.js` exists (47KB, Apr 24 03:02)
- `C:\Users\mattm\master-jarvis\second-brain\.obsidian\plugins\hermes-kanban-bridge\manifest.json` exists — version 1.3.0, author GumbyEnder
- `/root/.hermes/skills/productivity/{kanban-orchestrator,kanban-rituals,project-breakdown-to-kanban}.md` all deployed

### 🟢 Important: Plugin is NOT enabled

`.obsidian/community-plugins.json` does NOT exist in your vault. That file is Obsidian's registry of enabled community plugins. Its absence means **the Hermes Kanban Bridge plugin has not been activated** — no REST server is listening, no vault files being mutated, no risk surface active.

You have a clean decision point right now.

### ⚠️ Partial bind-fix risk

Peer's bind fix (0.0.0.0 → 127.0.0.1) only covers ONE of the two `listen()` call sites in the compiled main.js:

- Line 652: `this.server.listen(this.settings.port, "127.0.0.1", ...)` ← peer's patch
- Line 819: `this.server.listen(this.port, "0.0.0.0", ...)` ← still present

Depending on which code path the plugin activates (different classes / different trigger conditions), the 0.0.0.0 bind could still fire and expose the REST API to your LAN. Peer's MEMORY note didn't mention this second site.

### ❌ Upstream repo fails 3/5 security gates

Per the audit gates from `~/.claude/plans/why-are-all-of-synthetic-pond.md`:

| Gate | Threshold | Observed | Result |
|---|---|---|---|
| License | MIT/Apache | `license: null` on GitHub | ❌ |
| Last commit | ≤6 months | 2h ago (2026-04-24T04:10Z) | ✅ |
| Contributors | >1 unique | GumbyEnder only, 3 contributions | ❌ |
| Install script | sandboxed | `hermes-kanban-install.sh` hardcodes author NAS paths, leaks `gh auth token` via curl Authorization header | ❌ |
| Network exfil | none | REST server on localhost, config flag can auto-trust arbitrary vault writes | ⚠️ |

**Creation date**: 2026-04-22 (just 2 days ago). 80 stargazers in 2 days looks brigaded.

### Companion plugin note

`mgmeyers/obsidian-kanban` (the reputable, MIT-licensed visual renderer that the Hermes plugin bridges to) is NOT installed. You'd need to install it manually from the Obsidian community browser for the Kanban boards to render.

## Option A — Keep (enable + monitor)

**Steps**:
1. Install `mgmeyers/obsidian-kanban` from Obsidian community browser
2. Open `~/.obsidian/community-plugins.json` or toggle the plugin in Obsidian Settings → Community plugins
3. Set `boardFolder=Kanban` in plugin settings
4. Verify auto-trust is OFF (not yet checked since plugin isn't loaded)
5. Audit the second `listen(0.0.0.0)` site in main.js; either patch source + rebuild OR confirm it's dead code
6. Add a scheduled task to `git fetch` upstream daily and alert you on unexpected changes (supply-chain monitor)

**Upside**: Hermes can break goals into Kanban boards, move cards, run planning rituals — all local.
**Downside**: You're running un-licensed code from a 2-day-old single-author repo on a machine with trading infra. Any upstream malicious commit would propagate on next rebuild.

## Option B — Revert (delete files, keep bare Kanban) [RECOMMENDED]

**Steps**:
1. Delete `C:\Users\mattm\master-jarvis\second-brain\.obsidian\plugins\hermes-kanban-bridge\` (the whole folder — 2 files)
2. Delete `/root/.hermes/skills/productivity/kanban-orchestrator.md`, `kanban-rituals.md`, `project-breakdown-to-kanban.md` via `wsl -u root rm ...`
3. (Optional) Install `mgmeyers/obsidian-kanban` directly from Obsidian community browser — gives you Kanban boards without the Hermes bridge
4. Update `MEMORY.md` to reflect the decision

**Upside**: Clean slate, no un-licensed code, no supply-chain exposure. Still get Kanban boards if wanted.
**Downside**: Lose the Hermes "autonomous project executor" capability. Can always revisit in 3 months when upstream matures.

## Option C — Defer (leave as-is, disabled)

**Steps**: None.

**Upside**: Zero action needed.
**Downside**: Dead code accumulates in your vault + Hermes skills dir; you'll forget it's there; next audit will re-encounter it.

## Files You'd Touch (Option B)

- Delete: `C:\Users\mattm\master-jarvis\second-brain\.obsidian\plugins\hermes-kanban-bridge\` (folder)
- Delete: `/root/.hermes/skills/productivity/kanban-orchestrator.md`
- Delete: `/root/.hermes/skills/productivity/kanban-rituals.md`
- Delete: `/root/.hermes/skills/productivity/project-breakdown-to-kanban.md`
- Update: `~/.claude/projects/C--windows-system32/memory/MEMORY.md` top entry (mark as reverted)
- Update: `~/.claude/projects/C--windows-system32/memory/project_hermes_kanban_shipped_2026_04_24.md` (peer's file — ask peer session or note "reverted per decision brief")

## Re-evaluation Trigger

Re-check `GumbyEnder/hermes-kanban` in 3 months (2026-07-24) if:
- A LICENSE file has been added (MIT or Apache)
- ≥3 independent contributors
- Install script parameterized (no hardcoded `/mnt/nas` paths)
- Both `listen()` sites bound to 127.0.0.1
- No reports of supply-chain incidents in the meantime

Until those conditions, do not re-deploy.
