# Paperclip Claude Code Pack — V5

A Claude Code transfer pack for the `paperclipai/paperclip` repository.

## What's different in V5 vs. V4

V5 removes the legacy `.claude/skills/` directory entirely. The live repo already uses `.claude/skills/` for its own content (`design-guide`, `company-creator`, `paperclip`). V4 would collide with that. V5 re-homes all support docs to `.claude/paperclip/docs/` — a clean namespace that installs alongside the repo's own content without conflict.

## What's included

```
v5/
├── CLAUDE.md                         ← project memory (drop at repo root)
├── paperclip-value-analysis.md       ← standalone benefits doc
├── scripts/
│   ├── install-into-repo.sh          ← one-command installer
│   └── merge-claude-md.py            ← safe CLAUDE.md merge helper
└── .claude/
    ├── paperclip/
    │   └── docs/                     ← 9 reference files (new namespace)
    │       ├── root-memory.md
    │       ├── repo-map.md
    │       ├── read-order.md
    │       ├── architecture-invariants.md
    │       ├── dev-commands.md
    │       ├── file-targets-and-rg.md
    │       ├── change-playbooks.md
    │       ├── review-checklists.md
    │       └── value-analysis.md
    ├── agents/                        ← 8 project subagents
    │   ├── paperclip-repo.md
    │   ├── paperclip-core.md
    │   ├── paperclip-db.md
    │   ├── paperclip-api.md
    │   ├── paperclip-ui.md
    │   ├── paperclip-adapters.md
    │   ├── paperclip-plugins.md
    │   └── paperclip-release.md
    └── commands/                      ← 11 slash commands
        ├── paperclip-orient.md
        ├── paperclip-impact.md
        ├── paperclip-core.md
        ├── paperclip-db.md
        ├── paperclip-api.md
        ├── paperclip-ui.md
        ├── paperclip-adapter.md
        ├── paperclip-plugin.md
        ├── paperclip-release.md
        ├── paperclip-trace.md
        └── paperclip-validate.md
```

## Install into a local repo clone

```bash
git clone https://github.com/paperclipai/paperclip
./scripts/install-into-repo.sh /path/to/paperclip
```

The installer:
1. Backs up existing `.claude/` and `CLAUDE.md` to a timestamped folder
2. Copies `.claude/paperclip/docs/` into the repo
3. Copies `paperclip-*.md` agent and command files (namespaced, won't overwrite existing)
4. Creates or safely merges `CLAUDE.md`

Does **not** touch `.claude/skills/` — no collision with the repo's own skills.

## Manual install

```bash
# Copy docs namespace
mkdir -p /path/to/paperclip/.claude/paperclip/docs
cp .claude/paperclip/docs/* /path/to/paperclip/.claude/paperclip/docs/

# Copy agents (namespaced)
mkdir -p /path/to/paperclip/.claude/agents
cp .claude/agents/paperclip-*.md /path/to/paperclip/.claude/agents/

# Copy commands (namespaced)
mkdir -p /path/to/paperclip/.claude/commands
cp .claude/commands/paperclip-*.md /path/to/paperclip/.claude/commands/

# Drop CLAUDE.md if none exists, or merge
cp CLAUDE.md /path/to/paperclip/CLAUDE.md  # only if no CLAUDE.md exists
# or:
python scripts/merge-claude-md.py /path/to/paperclip/CLAUDE.md
```

## Verify installation

```bash
# Check docs copied
ls /path/to/paperclip/.claude/paperclip/docs/

# Confirm NO legacy skills references
grep -r "skills/" /path/to/paperclip/.claude/paperclip/  # should be empty

# Check agents
ls /path/to/paperclip/.claude/agents/ | grep paperclip

# Check commands
ls /path/to/paperclip/.claude/commands/ | grep paperclip
```

## Using the pack

Open Claude Code in the repo:
```bash
cd /path/to/paperclip
claude
```

Then use slash commands:
- `/paperclip-orient` — get oriented on the monorepo
- `/paperclip-impact <describe your change>` — trace cross-package impact
- `/paperclip-validate` — run completion checklists
- `/paperclip-trace <entity or request>` — trace data/request path
- `/paperclip-db`, `/paperclip-api`, `/paperclip-ui`, `/paperclip-adapter`, `/paperclip-plugin`, `/paperclip-release`

Or invoke subagents by name in your prompt: "Use the paperclip-repo agent to..."

## Key design decisions

| Decision | Reason |
|----------|--------|
| No `.claude/skills/` | Repo already has own skills there |
| Docs under `.claude/paperclip/docs/` | Non-colliding namespace |
| Agents namespaced `paperclip-*.md` | Won't overwrite repo's own agents |
| CLAUDE.md uses `@` imports | Modular, mergeable, keeps root file short |
| Installer is additive | Backs up first, appends not overwrites |
