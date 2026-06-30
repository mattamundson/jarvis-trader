---
source: 0xMoysei — "The 10-Step Second Brain"
url: https://x.com/0xmoysei/status/2069494292695932964
author: "@0xMoysei (relaying Andrej Karpathy's LLM Wiki pattern)"
kind: article
analyzed_at: 2026-06-27
recommendation: adopt (mostly already built)
surfaces_with_value: [engine-code, skills, commands, docs, ops]
---

# 0xMoysei — The 10-Step Second Brain

Point Claude at an Obsidian vault; it files, links, and reconciles while you curate
sources and ask questions. `raw` belongs to you and is never edited; `wiki` belongs to
Claude. Sources compile once into linked pages and compound from there.

## Core finding

jarvis-trader **already implements the substance of this article**, adapted from
DamiDefi's "9 Things My Obsidian Vault Does While I Sleep" rather than copied from the
tweet. The original gaps were operational, not architectural: the overnight jobs existed
but were undocumented and un-triggerable, and the structural "lint pass that catches
broken links" was missing. This PR closes those. The design choice to keep the vault
*outside* the repo was deliberate and is preserved — see `docs/memory-patterns.md`:
*"Matt already has a separate Obsidian second-brain vault … no need to double it up
inside jarvis-trader."*

Legend: ✅ already done · ◐ existed but dormant/undocumented · ✚ added by this PR · ✗ intentionally not adopted

## The 10 steps mapped to the repo

| # | Article step | Status | Where |
|---|--------------|--------|-------|
| 1 | Two tools, two jobs (Obsidian stores, Claude curates) | ✅ | `engine/vault/`, Obsidian vault at `JARVIS_VAULT_ROOT` |
| 2 | Install Claude Code | ✅ | this environment |
| 3 | Make your vault | ✅ | 5-folder taxonomy, `engine/vault/paths.py` |
| 4 | Open a door into the vault (Local REST API) | ✗ | Not via Obsidian's REST plugin — the engine reads/writes the vault filesystem directly (deep-analyzer, bookmark render). Personal MCP-to-vault wiring declined in `docs/memory-patterns.md`. |
| 5 | Wire Claude in with MCP (`mcp-obsidian`) | ✗ | Same as #4 — direct FS access, not a personal Obsidian MCP server |
| 6 | Load yourself into the brain (`CLAUDE.md`) | ✅ | Root `CLAUDE.md` + `.claude/rules/`, `.claude/skills/` |
| 7 | Karpathy `raw/` + `wiki/` structure | ◐→✚ | Repo uses DamiDefi's numbered `00`–`04` taxonomy (a superset). `raw/wiki` semantics preserved: `01-Sources` is immutable capture, `00-Inbox` is Claude-compiled output. Recorded here as a deliberate variant. |
| 8 | Teach Claude the Obsidian dialect (`[[wikilinks]]`) | ✅→✚ | Writers already emit wikilinks; this PR adds a **lint pass** (`engine/vault/lint.py`) that validates them |
| 9 | Add live data, then walk away (scheduled jobs) | ◐→✚ | 4 PM2 cron jobs (synthesis 06:00, **lint 06:30 ✚**, contradiction 07:00, backup 00:00) + 03:00 bookmark render. All now documented + armable + API-triggerable. |
| 10 | Skip the wiring with community repos | ✅ | `AgriciDaniel/claude-obsidian` already analyzed at `docs/repo-integrations/AgriciDaniel__claude-obsidian.md` |

## The 9 rules mapped

| Rule (paraphrased) | Status | Note |
|--------------------|--------|------|
| Start with 10 sources, not 10,000 | ✅ | Vault grows from Discord/X captures, not bulk import |
| `raw` is yours and never edited | ✅ | `01-Sources` capture is immutable; automation only writes `00-Inbox` |
| `wiki` belongs to Claude | ✅ | Synthesis/lint/contradiction output → `00-Inbox` |
| It isn't RAG — compile once, compound | ✅ | Notes are compiled markdown pages, not embedded chunks (gbrain sink is a separate optional path) |
| Lint pass catches broken links + contradictions | ✚ + ✅ | **Broken-link lint added** (`lint.py`); contradiction scan already existed (`synthesis.py`) |
| Files itself at 7 a.m. | ✅ | Contradiction check is the 07:00 CT job |
| Control access with keys, not prompts | ✅ | API behind `X-API-Key`; backup uses a scoped git remote, not an agent with delete rights |
| You keep judgment; it keeps the books | ✅ | Jobs read/write notes only; never touch the order path or safety layer |
| A vault that maintains itself | ✚ | Lint + status now make drift visible instead of silent |

## What this PR added (✚)

- `engine/vault/lint.py` + `engine/scripts/vault_lint.py` + `jarvis-vault-lint` PM2 job — broken-`[[wikilink]]` and orphan detection (pure FS, no LLM).
- `engine/routers/vault_router.py` (`/vault/status`, `/vault/{kind}/latest`, `/vault/{kind}/run`) — read + trigger on demand, gated by the same `ENABLE_VAULT_*` flags as cron (409 if disabled).
- `.claude/commands/vault.md` + `.claude/skills/jarvis-vault/SKILL.md` — session-level access; cross-linked from `jarvis-search-discipline`.
- `.env.example` vault block + `docs/runbooks/VAULT_AUTOMATION.md` — the dormant jobs are now documented and armable.

## Not adopted (✗) and why

- **Obsidian Local REST API + `mcp-obsidian`** (steps 4–5): the engine already reaches the
  vault via direct filesystem writes; adding a personal Obsidian MCP server duplicates that
  surface and was previously declined in `docs/memory-patterns.md`. Revisit only if a
  human-in-the-loop Obsidian editing flow is wanted from a session.
- **Literal `raw/` + `wiki/` rename** (step 7): the DamiDefi `00`–`04` taxonomy is already
  in production with writers, tests, and renders pointing at it. Renaming would be churn for
  no behavioural gain; the raw-vs-compiled distinction is preserved by folder convention.
