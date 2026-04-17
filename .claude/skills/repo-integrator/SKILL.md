---
name: repo-integrator
description: Systematically evaluate a GitHub repo (or Discord-bookmark link) against all nine jarvis-trader integration surfaces — engine code, rules, skills, commands, subagents, docs, dev tooling, dashboard, ops — and produce a structured integration proposal. Use when the user says "analyze this repo", "integrate [URL]", "what can we use from [repo]", "re-scan this link", or when batch-processing items from `docs/research-backlog-from-discord.md` or `docs/digest/`. Replaces the binary novel/dedup/noise classifier with multi-dimensional evaluation so a repo that's useless on one axis (e.g., not a trading strategy) can still surface value on another (e.g., rules, dev tooling, skills).
---

# When to use

- User provides a GitHub URL or repo slug
- Re-analyzing items from `docs/research-backlog-from-discord.md`
- Re-analyzing items previously classified `noise` or `dedup` in `docs/digest/*-synthesis.md`
- Processing a new Discord bookmark link
- User says "does this have anything useful for us"

**Do not use** this skill for pure strategy comparison ("which of these 3 is best") — that's a strategy-synthesis task. This skill finds value *wherever it lives*, not just in one category.

# Why this skill exists

The prior Discord digest classified each link as `novel` (8 shipped), `dedup` (16 corroboration), or `noise` (48 discarded). That's a trading-only lens. A repo like `forrestchang/andrej-karpathy-skills` scores 0/5 as a trading strategy — noise by the old classifier — but 5/5 as an LLM-discipline rules contribution (shipped 2026-04-17 as `.claude/rules/meta-discipline.md`).

**Rule:** every repo gets evaluated against **all nine surfaces**, not just the trading-adjacent ones.

# The nine surfaces

| # | Surface | Where it lives | Example fits |
|---|---|---|---|
| 1 | Engine code | `engine/agents/`, `engine/backtest/`, `engine/strategies/`, `engine/risk/`, `engine/analytics/`, `engine/data/`, `engine/analysis/` | New signal, agent, backtest harness, indicator, risk check |
| 2 | Project rules | `.claude/rules/*.md` | Coding discipline, safety invariant, testing pattern |
| 3 | Project skills | `.claude/skills/*/SKILL.md` | Reusable workflow pattern |
| 4 | Slash commands | `.claude/commands/*.md` | `/pretrade-check`-style quick action |
| 5 | Subagents | `.claude/agents/*.md` | Specialized reviewer or analyzer |
| 6 | Docs | `docs/runbooks/`, `docs/strategy/`, `docs/digest/`, `CLAUDE.md` | Operational runbook, architecture note |
| 7 | Dev tooling | `ecosystem.config.js`, `.github/workflows/`, `.claude/hooks/`, pre-commit, `engine/scripts/` | CI check, PM2 pattern, hook automation |
| 8 | Dashboard | `dashboard/components/`, `dashboard/lib/`, Tailwind theme | UI component, chart, monitoring widget |
| 9 | Ops / messaging | `engine/notifications/`, `engine/schedulers/`, WhatsApp/OpenClaw/Discord integrations | Alert pattern, cron job, message route |

# Workflow

## 1. Fetch the content

Prefer local cache to avoid network:

```bash
ls C:/Users/mattm/discord-export/digest-raw/github/<owner>__<repo>.md
```

If not cached:
```bash
gh api "repos/<owner>/<repo>/readme" --jq .content | base64 -d > /tmp/readme.md
gh api "repos/<owner>/<repo>" > /tmp/meta.json  # stars, license, archived, topics, pushed_at
```

For X/Twitter links: read text from `C:/Users/mattm/discord-export/digest-raw/x-posts.jsonl` (grep by status_id).

## 2. Read it end-to-end

No skimming. Integration value lives in the specific hooks, not the summary.

## 3. Cross-reference all nine surfaces

Run these greps against the project before proposing anything:

```bash
cd /c/Users/mattm/ThinkorSwim/jarvis-trader

# For each keyword/concept from the README:
grep -r "<concept>" engine/ --include="*.py" | head -5     # surface 1
grep -r "<concept>" .claude/rules/ --include="*.md"        # surface 2
ls .claude/skills/ | grep -i "<concept>"                   # surface 3
ls .claude/commands/ | grep -i "<concept>"                 # surface 4
ls .claude/agents/ | grep -i "<concept>"                   # surface 5
grep -r "<concept>" docs/ --include="*.md" | head -5       # surface 6
grep -l "<concept>" ecosystem.config.js .github/workflows/*.yml 2>/dev/null  # surface 7
grep -r "<concept>" dashboard/components dashboard/lib --include="*.tsx"     # surface 8
grep -r "<concept>" engine/notifications engine/schedulers --include="*.py"  # surface 9
```

**Duplication is worse than omission.** If a surface already covers the concept, classify as `dedup-<surface>` and mention the existing file — don't re-ship it.

## 4. License check

| License | Action |
|---|---|
| MIT / Apache 2.0 / BSD / ISC / Unlicense | Integrate freely; attribute in file header |
| GPL / AGPL / LGPL | Flag — integration requires legal review first |
| Proprietary / no license | Can reference ideas but copy no code; mention only |
| Missing LICENSE file | Treat as proprietary |

## 5. Classify each surface

For every one of the nine surfaces, produce exactly one of:

- **`integrate-now`** — concrete file path + 1-2 sentence plan. User can green-light same turn.
- **`partial-integrate`** — some pieces fit but require follow-up (e.g., missing infra, needs refactor to match existing patterns)
- **`defer`** — genuine fit but blocked on a dependency, decision, or prerequisite
- **`dedup-<surface>`** — already covered by `<specific file path>`
- **`no-fit`** — not applicable to this surface

## 6. Write the analysis

Output to `docs/repo-integrations/<owner>__<repo>.md` using this exact structure:

```markdown
---
repo: <owner>/<repo>
url: https://github.com/<owner>/<repo>
stars: <n>
language: <primary>
license: <license>
archived: <true|false>
pushed_at: <iso-date>
analyzed_at: 2026-04-17
recommendation: integrate-now | partial-integrate | defer | dedup | noise
surfaces_with_value: [<surface-names-only>]
---

# <owner>/<repo>

## Core value proposition
<2-3 sentence synthesis of what the repo actually does. No marketing speak.>

## Surface analysis

### 1. Engine code
<classification> — <specific finding + file path if any>

### 2. Project rules
<classification> — <finding>

### 3. Project skills
<classification> — <finding>

### 4. Slash commands
<classification> — <finding>

### 5. Subagents
<classification> — <finding>

### 6. Docs
<classification> — <finding>

### 7. Dev tooling
<classification> — <finding>

### 8. Dashboard
<classification> — <finding>

### 9. Ops / messaging
<classification> — <finding>

## Integration plan
<For every `integrate-now` or `partial-integrate` surface above: concrete file paths + steps. If none, write "No integrations; recommend classify as <dedup|noise>.">

## License & attribution
<license + where attribution goes (file header / commit message / CLAUDE.md)>

## Effort estimate
<S = <2hr, M = 2-8hr, L = 1-3 days, XL = >3 days>

## Red flags
<any reasons NOT to integrate: archived, abandoned, security concerns, license conflict, architectural mismatch>
```

## 7. Surface to user

Return a one-paragraph verdict in chat:

> `<owner>/<repo>` — **<recommendation>**. Value on surface(s): <list>. No value on: <list>. Integration effort: <S/M/L/XL>. Proposal doc: `docs/repo-integrations/<slug>.md`. Want to proceed with any of them?

**Never** commit integrations without explicit user go/no-go. The skill produces proposals, not merged code.

# Anti-patterns

- **Don't copy README wholesale** — synthesize. If you can't rewrite it in your own words, you don't understand it yet.
- **Don't force an integration** — "no-fit" across all nine surfaces is a valid result. Write the analysis doc anyway so the repo is marked analyzed and won't be re-scanned.
- **Don't skip the cross-reference step** — duplication wastes the user's review time more than omission.
- **Don't touch safety-critical code** without `[safety-review]` tag. If a repo suggests a change to `engine/config.py`, `engine/risk/`, `engine/execution/`, or kill-switch logic, flag it as `defer` and surface the safety-review requirement.
- **Don't auto-commit** — always surface proposals for user green-light first.

# Batch mode

When re-scanning `docs/research-backlog-from-discord.md` or a list of URLs:

1. Emit one analysis doc per repo to `docs/repo-integrations/`.
2. Aggregate into a single summary at `docs/repo-integrations/_batch-<date>.md` with columns: repo | recommendation | surfaces | effort.
3. Sort by `effort ascending` within `integrate-now` — user picks quick wins first.
4. Use parallel agents (haiku model per `.claude/rules/workflow.md`) — 10 agents max, one repo each per batch.

# Self-test

When this skill was first run against `forrestchang/andrej-karpathy-skills`, the expected output was:
- `recommendation: integrate-now`
- `surfaces_with_value: [rules]`
- Engine code: `no-fit` (not a trading strategy)
- Project rules: `integrate-now` → `.claude/rules/meta-discipline.md` (shipped in commit `966a2d3`)
- All other surfaces: `no-fit` or `dedup`

If you run the skill on that repo and get a different answer, the skill is broken.

# Attribution

Skill concept proposed by user 2026-04-17 09:31 after observing that the binary novel/dedup/noise classifier in `docs/digest/README.md` missed non-trading value in repos like `forrestchang/andrej-karpathy-skills`.
