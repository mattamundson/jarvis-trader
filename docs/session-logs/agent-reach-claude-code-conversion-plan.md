# Agent Reach → Claude Code Conversion Plan

## Bottom line

I would **not** rely on a single `SKILL.md` as the only Claude Code integration surface.

I would convert the repository into four layers:

1. `CLAUDE.md`
   - persistent project memory
   - architecture, rules, install/update boundaries, canonical commands

2. `.claude/agents/`
   - specialized Claude Code subagents
   - best for complex, reusable workflows like install/update/doctor/configure

3. `.claude/commands/`
   - explicit, repeatable user-invoked workflows
   - best for one-shot install/update/doctor tasks

4. `docs/agent-reach/`
   - dense reference material
   - repo map, platform matrix, troubleshooting, command cheatsheets

## Recommended file layout

```text
agent-reach-claude/
├── CLAUDE.md
├── .claude/
│   ├── agents/
│   │   └── agent-reach-operator.md
│   └── commands/
│       ├── install-agent-reach.md
│       ├── update-agent-reach.md
│       └── agent-reach-doctor.md
├── docs/
│   └── agent-reach/
│       ├── REPO_MAP.md
│       ├── PLATFORM_MATRIX.md
│       ├── UPSTREAM_CHEATSHEET.md
│       └── MIGRATION_NOTES.md
└── skills/
    └── agent-reach/
        └── SKILL.md
```

## Why this structure is correct

### `CLAUDE.md`
Use it for facts Claude should always know:
- Agent Reach is an installer/doctor/config layer, not the main runtime wrapper
- persistent state belongs in `~/.agent-reach/`
- temp output belongs in `/tmp/`
- after install, prefer upstream tools directly
- channel contract and development rules

### `.claude/agents/agent-reach-operator.md`
Use it for specialized behavior:
- classify task as install/update/doctor/configure/use/extend/port
- keep workspace clean
- run diagnostics before inventing fixes
- ask only for inputs the user must provide

### `.claude/commands/*.md`
Use them for explicit invocation:
- `/install-agent-reach`
- `/update-agent-reach`
- `/agent-reach-doctor`

### `docs/agent-reach/*.md`
Use them for large references that should not all live in memory at once.

### `skills/agent-reach/SKILL.md`
Keep this for portability and for systems that do consume `SKILL.md` directly.

## How I would map the upstream repo

### Upstream project memory → Claude memory
- upstream `CLAUDE.md` → root `CLAUDE.md`

### Upstream skill file → portability + reference
- upstream `agent_reach/skill/SKILL.md` → `skills/agent-reach/SKILL.md`
- additionally split its useful pieces into Claude-native files

### Upstream docs → Claude reference docs
- `docs/install.md` → command prompts + docs reference
- `docs/update.md` → update command + docs reference

### Upstream architecture → repo map
- `agent_reach/cli.py`, `core.py`, `doctor.py`, `config.py`, `channels/`, `integrations/` → `docs/agent-reach/REPO_MAP.md`

## What I would not do

- I would not dump the whole repo into one huge markdown file.
- I would not keep everything only in a `SKILL.md`.
- I would not put install/update scratch files in the active workspace.
- I would not rewrite Agent Reach into a different abstraction model unless you want a real fork.

## If you want the most useful next step

Use the transfer bundle and copy it into either:
- your project repo for project-local Claude Code behavior, or
- `~/.claude/` for user-level/global behavior
