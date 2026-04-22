# gstack v0.15.1.0 — Install Guide for JARVIS Trader

gstack is vendored at `.claude/skills/gstack/` in this repo.
It gives Claude Code 33 specialized engineering skills: `/review`, `/qa`, `/ship`,
`/office-hours`, `/browse`, `/investigate`, and more.

## Quick Start (macOS/Linux)

```bash
cd .claude/skills/gstack
./setup
```

The `./setup` script:
1. Detects your platform (macOS arm64/x86, Linux, Windows via WSL)
2. Builds the `browse` binary (requires Bun v1.0+) — headless Chromium controller
3. Builds the `design` binary (requires Bun v1.0+) — GPT Image generation
4. Symlinks each skill directory into `~/.claude/skills/`
5. Sets up `~/.gstack/config.yaml` with default settings

After setup, all 33 skills are available in Claude Code as `/office-hours`,
`/review`, `/qa`, etc.

## Prerequisites

| Tool | Required | Install |
|------|----------|---------|
| Claude Code | Yes | https://claude.ai/claude-code |
| Git | Yes | system package |
| Bun v1.0+ | Yes | `curl -fsSL https://bun.sh/install \| bash` |
| Node.js | Windows only | https://nodejs.org |

## Windows (WSL2)

The browse binary is compiled for native Linux inside WSL2. Run `./setup` from
a WSL2 terminal — do not run from PowerShell or CMD.

```bash
# In WSL2:
cd /mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/.claude/skills/gstack
./setup
```

## What Each Skill Does

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `/office-hours` | Starting a new feature | Reframes your idea before writing code |
| `/plan-ceo-review` | After planning | CEO-level product review |
| `/plan-eng-review` | After planning | Lock architecture, data flow, edge cases |
| `/plan-design-review` | After planning | Rate design dimensions 0–10 |
| `/autoplan` | After planning | Run all three plan reviews auto |
| `/review` | Before merging | Pre-landing PR review — finds prod bugs |
| `/qa` | Feature ready | Open real browser, find bugs, fix, verify |
| `/qa-only` | Feature ready | QA report only, no code changes |
| `/ship` | Ready to ship | Run tests → review → push → PR |
| `/investigate` | Bug reported | Systematic root-cause debugging |
| `/design-consultation` | New UI needed | Build complete design system from scratch |
| `/design-review` | UI ready | Design audit + fix loop |
| `/design-shotgun` | Exploring UI | Visual design exploration (variants) |
| `/design-html` | HTML design | CSS/HTML visual polish |
| `/browse` | Browser testing | Real Chromium, ~100ms/command |
| `/connect-chrome` | Auth testing | Connect to headed Chrome with sidebar |
| `/setup-browser-cookies` | First login | Import real browser cookies |
| `/codex` | Second opinion | OpenAI Codex cross-model code review |
| `/cso` | Security audit | OWASP Top 10 + STRIDE threat model |
| `/benchmark` | Performance | Regression detection before/after |
| `/canary` | Post-deploy | Monitor deployment health loop |
| `/land-and-deploy` | Ship cycle | Merge → deploy → canary verify |
| `/checkpoint` | Mid-work | Save progress snapshot |
| `/learn` | After session | Capture session learnings |
| `/retro` | Weekly | Retrospective with shipping streaks |
| `/document-release` | Post-ship | Update all docs to match what shipped |
| `/health` | Anytime | Project health dashboard |
| `/careful` | Safety | Warn before destructive commands |
| `/freeze` | Safety | Lock edits to one directory |
| `/guard` | Safety | Activate careful + freeze together |
| `/unfreeze` | Safety | Remove directory edit restrictions |
| `/gstack-upgrade` | Maintenance | Update gstack to latest version |
| `/setup-deploy` | First deploy | One-time deploy configuration |

## Directory Layout

```
.claude/skills/gstack/
├── bin/                    # CLI utilities (gstack-config, gstack-slug, etc.)
├── browse/                 # Browser binary source (TypeScript/Bun)
│   ├── src/                # Commands, server, snapshot
│   ├── dist/               # Compiled binary (built by ./setup)
│   └── SKILL.md            # /browse skill prompt
├── design/                 # Design binary source (TypeScript/Bun)
├── [skill-name]/           # One dir per skill
│   ├── SKILL.md            # The prompt Claude reads
│   └── SKILL.md.tmpl       # Source template (edit this, not SKILL.md)
├── review/checklist.md     # Review specialist checklists
├── review/specialists/     # SQL, security, performance, testing reviewers
├── qa/references/          # Issue taxonomy
├── AGENTS.md               # All available skills (table view)
├── CLAUDE.md               # Dev-mode config for gstack contributors
├── ETHOS.md                # Builder philosophy (Boil the Lake)
├── setup                   # One-time install script
└── VERSION                 # 0.15.1.0
```

## Keeping gstack Updated

```bash
# Option A: Pull latest from GitHub
cd .claude/skills/gstack
git remote add gstack-upstream https://github.com/garrytan/gstack.git 2>/dev/null || true
git fetch gstack-upstream
git merge gstack-upstream/main --allow-unrelated-histories

# Option B: Re-clone fresh
rm -rf .claude/skills/gstack
git clone --depth 1 https://github.com/garrytan/gstack.git .claude/skills/gstack
cd .claude/skills/gstack && ./setup
```

Or just use `/gstack-upgrade` inside Claude Code — it handles this automatically.

## JARVIS Trader + gstack Integration Notes

- Use `/review` before any PR that touches `engine/risk/safety_layer.py`
- Use `/investigate` for debugging agent pipeline failures
- Use `/qa` + `/browse` for testing the Next.js dashboard (port 3010)
- Use `/cso` for periodic security audits of the FastAPI engine
- Use `/ship` in place of your manual git → PR workflow
- `/office-hours` is great before designing new trading agents or features
- `/benchmark` is ideal for measuring pipeline latency before/after changes

## Telemetry

Off by default. First run will ask. No code, file paths, or repo names are sent.
To configure: `~/.claude/skills/gstack/bin/gstack-config set telemetry off`
