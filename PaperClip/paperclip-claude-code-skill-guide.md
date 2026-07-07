# Paperclip Claude Code transfer pack guide v4

This version pivots the pack toward Claude Code surfaces that are directly documented by Anthropic:

- project memory at `./CLAUDE.md`
- project slash commands at `.claude/commands/`
- project subagents at `.claude/agents/`

The earlier `skills` directories are still included, but they should be treated as support docs and compatibility content rather than the primary install surface.

## Install

```bash
./scripts/install-into-repo.sh /path/to/paperclip-clone
```

## What the installer does

1. Backs up any existing `CLAUDE.md` and `.claude/` into a timestamped folder.
2. Copies this pack's `.claude/` tree into the target repo.
3. Creates `CLAUDE.md` if it does not exist.
4. If `CLAUDE.md` already exists, appends a managed import block that references `@.claude/paperclip/imports/root-memory.md`.

## Main project subagents

- `paperclip-repo`
- `paperclip-core`
- `paperclip-db`
- `paperclip-api`
- `paperclip-ui`
- `paperclip-adapters`
- `paperclip-plugins`
- `paperclip-release`

## Main project commands

- `paperclip-orient`
- `paperclip-impact`
- `paperclip-core`
- `paperclip-db`
- `paperclip-api`
- `paperclip-ui`
- `paperclip-adapter`
- `paperclip-plugin`
- `paperclip-release`
- `paperclip-trace`
- `paperclip-validate`

## Notes

- `CLAUDE.md` is the official project memory location.
- `.claude/agents/` is the official project subagent location.
- `.claude/commands/` is the official project slash-command location.
- `.claude/skills/` is retained here only as support material because it is useful for packaging Paperclip-specific repo knowledge into focused markdown docs.
