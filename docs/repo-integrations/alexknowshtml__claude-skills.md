---
repo: alexknowshtml/claude-skills
url: https://github.com/alexknowshtml/claude-skills
stars: 23
language: HTML
license: null (no LICENSE file)
archived: false
pushed_at: 2026-04-17T01:08:42Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [project-skills, docs]
---

# alexknowshtml/claude-skills

## Core value proposition

A curated collection of five reusable Claude Code skills focused on session workflow and content publishing: `/reflect` (session retrospectives with Opus delegation), `/pause` (session state save with return prompts), `/upskill` (automated skill maintenance), `/create-skill` (turning sessions into reusable skills), and `/pretty-page` (markdown to styled HTML with S3 upload). Each is battle-tested from production use.

## Surface analysis

### 1. Engine code
**no-fit** — The repo contains no Python trading logic, signals, backtesting harnesses, risk checks, or analytics. All skills are Claude Code workflow utilities, not engine components.

### 2. Project rules
**no-fit** — The skills do not propose or document coding discipline, safety invariants, or testing patterns specific to trading or risk management. They are agnostic workflow rules.

### 3. Project skills
**partial-integrate** — Four of the five skills have direct trading workflow value: (a) `/reflect` automates session learning loops and could be adapted to analyze trading debugging sessions; (b) `/upskill` can maintain jarvis-trader-specific skills (e.g., detecting stale `/backtest-report` or outdated `/jarvis-trader` docs); (c) `/create-skill` is a meta-skill for operationalizing new trading patterns discovered in sessions; (d) `/pretty-page` can generate shareable HTML reports of trading analysis (e.g., WFE snapshots, backtest results). `/pause` is context-agnostic session saving — low trading-specific value but useful for any multi-day trading session work.

**Duplication check:** `/reflect` partially overlaps with the session logging already wired in `.claude/projects/<slug>/` and the `/vault-wrap-up` in obsidian-mind skill, but those are automated end-of-session commits, not retrospective analysis. `/upskill` does not conflict with any existing skill maintenance workflow. `/create-skill` is a meta-skill with no duplication. `/pretty-page` has no equivalent in jarvis-trader yet (dashboard generates JSON APIs, not shareable HTML reports).

### 4. Slash commands
**no-fit** — The repo provides only `.claude/skills/` format, not `.claude/commands/` format. Commands would require conversion (trivial but not done in the repo).

### 5. Subagents
**no-fit** — No subagent definitions. `/reflect` internally delegates to an Opus subagent, but that is local logic within the skill, not a shareable subagent specification.

### 6. Docs
**integrate-now** — The repo's `README.md` and inline SKILL.md documentation are well-written, but jarvis-trader lacks a general skill-writing guide. `/create-skill` includes best-practice research on skill design (placeholder in the repo, but the pattern is sound). Recommend integrating its structure into `docs/skill-design-patterns.md` — currently no such runbook exists in jarvis-trader.

### 7. Dev tooling
**no-fit** — The skills contain no CI checks, PM2 patterns, Git hooks, or pre-commit automation. They are pure workflow utilities.

### 8. Dashboard
**no-fit** — No UI components, charts, or widgets. All skills are Claude Code terminal/editor workflows.

### 9. Ops / messaging
**no-fit** — The skills do not integrate with OpenClaw, WhatsApp, Telegram, or any messaging layer. `/pause` and `/reflect` are entirely local.

## Integration plan

### Skill 3: `/upskill` (Priority: HIGH)
**Plan:** Copy `upskill/SKILL.md` to `.claude/skills/upskill/SKILL.md` (does not conflict with `last30days` or other existing skills). Customize the `SESSION_DIR` placeholder to point to jarvis-trader's `.claude/projects/jarvis-trader/` and add a post-processing step to check for stale references in trading-specific skills (`backtest-report`, `jarvis-trader`, `pm2-doctor`, `repo-integrator`). No code changes required; skill is pure workflow.

### Skill 3B: `/reflect` (Priority: MEDIUM)
**Plan:** Copy `reflect/SKILL.md` to `.claude/skills/reflect/SKILL.md`. Customize the Opus subagent delegation to include a check for "trading session friction" — e.g., repeated backtesting loops, signal validation issues, portfolio reconciliation bugs. The skill's Opus analysis phase can surface these patterns without code changes. Requires user approval on first run.

### Skill 5: `/pretty-page` (Priority: LOW)
**Plan:** Copy `pretty-page/SKILL.md` to `.claude/skills/pretty-page/SKILL.md`. Requires `boto3` (already available in `engine/.venv` if AWS or S3-compatible storage is available). No changes to skill logic; user must configure `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` environment variables before use. Use case: publish WFE analysis snapshots, backtest report HTML, or trading learnings to a shareable URL.

### Skill 1: `/pause` (Priority: LOW)
**Plan:** Copy `pause/SKILL.md` to `.claude/skills/pause/SKILL.md`. No trading-specific customization needed; useful as-is for multi-day trading sessions. Auto-generates return prompts with minimal overhead.

### Skill 4: `/create-skill` (Priority: DEFER)
**Plan:** Integrate after first `/upskill` or `/reflect` session surfaces a new skill candidate from trading work. This is a meta-skill for operationalizing discoveries; it depends on the user having a candidate workflow first.

### Skill 6: `/pretty-page` Setup (One-time)
If S3 integration is desired, configure in `.claude/settings.json` or user env:
```bash
export S3_BUCKET="jarvis-trader-reports"
export AWS_ACCESS_KEY_ID="<your-key>"
export AWS_SECRET_ACCESS_KEY="<your-secret>"
export S3_ENDPOINT_URL="<optional>"  # for non-AWS
```

## License & attribution

**License:** null (no LICENSE file) — Treat as proprietary. Code can be referenced/adapted but must not be copied wholesale without explicit permission from [@alexknowshtml](https://github.com/alexknowshtml). Recommend reaching out to the author if close integration is planned.

**Attribution strategy:** If skills are integrated without modification, add a comment block in each `.claude/skills/<name>/SKILL.md` header:
```markdown
<!-- Adapted from https://github.com/alexknowshtml/claude-skills -->
```

If modifications are made (e.g., trading-specific Opus subagent logic), note in the file and optionally in `docs/ATTRIBUTIONS.md` if that exists.

## Effort estimate

- **`/upskill` + `/reflect` + `/pause` (copy + placeholder customization):** S (< 2hr)
- **`/pretty-page` setup (copy + S3 env config):** S (< 2hr)
- **`/create-skill` (defer until needed):** deferred
- **Total for integrate-now + partial-integrate:** **S + M = M (2–4hr)**

If S3 integration is skipped, effort is **S (< 2hr)** for all four skills.

## Red flags

1. **No LICENSE file** — alexknowshtml/claude-skills has no explicit license. Verify with the author ([@alexknowshtml](https://github.com/alexknowshtml)) before committing to production use.
2. **Repo age** — Created 2026-04-12 (5 days old at time of analysis). Early-stage but active (pushed 2026-04-17). Monitor for API changes if Claude Code releases breaking changes to skill format.
3. **Opus delegation in `/reflect`** — Requires Opus availability and API quota. Trading sessions should gate this behind a feature flag or user approval if Opus budget is constrained.
4. **S3 dependency in `/pretty-page`** — Requires `boto3` and valid cloud credentials. Not critical for other skills; can be skipped if cloud storage is not available.
5. **Placeholder hardcoding** — All five skills contain `<angle-bracket>` placeholders (e.g., `<your-project-slug>`, `<your-bucket-name>`) that MUST be customized before use. Recommend a pre-integration audit checklist.

## Notes

- No existing skill in jarvis-trader conflicts with these five.
- `/reflect` and `/upskill` are the highest-value additions (learning loop automation + skill maintenance).
- `/pretty-page` is optional but valuable for sharing analysis reports with stakeholders.
- `/create-skill` is a dependency for future skill-writing workflows; integrate after first candidate emerges.
- Author is actively maintaining the repo (pushed 5 days ago); low risk of abandonment.
