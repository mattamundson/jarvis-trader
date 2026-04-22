# Install in Claude Code

This pack is structured as a Claude Code custom skill.

## Recommended folder placement

Project-local:

```bash
mkdir -p .claude/skills
cp -R n-autoresearch .claude/skills/
```

Personal/global:

```bash
mkdir -p ~/.claude/skills
cp -R n-autoresearch ~/.claude/skills/
```

The folder should contain `SKILL.md` at its root:

```text
n-autoresearch/
  SKILL.md
  references/
  examples/
  templates/
  scripts/
```

## Triggering the skill

Inside Claude Code, invoke it with prompts like:

- `Use the n-autoresearch skill and start a new run tag.`
- `Read program.md and kick off a baseline experiment.`
- `Use the n-autoresearch loop, but summarize each result before continuing.`

## Practical recommendation

Use the skill form when you want Claude Code to load the operating procedure on demand instead of carrying a huge monolithic prompt in every session.
