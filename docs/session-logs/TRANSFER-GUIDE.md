# n-autoresearch -> Claude Code transfer guide

This package is a practical Claude Code conversion of the public repository `iii-hq/n-autoresearch`.

## What is included

- `SKILL.md` — the main Claude Code skill definition
- `references/repo-map.md` — architectural map of the repository
- `references/api-contract.md` — exact working contract for the iii REST endpoints used by the loop
- `references/install-in-claude-code.md` — installation and placement instructions
- `examples/kickoff-prompts.md` — prompts that reliably trigger the skill
- `templates/*.json` — reusable payload skeletons

## Why this shape was chosen

The repository is already organized around an agent loop:
- human edits `program.md`
- agent edits `train.py`
- iii tracks experiments
- GPU workers execute training

Because of that, the best Claude Code conversion is **not** one giant markdown dump of the whole repo.

Instead, the best conversion is:

1. one main skill file that tells Claude when and how to operate
2. a small set of references that Claude can load only when needed
3. payload templates for exact API interactions

## What I would not do

I would **not**:
- paste the full repository into one prompt file
- include the raw worker source code inside `SKILL.md`
- make the skill overly generic
- hide the repo's important constraint that `train.py` is the normal edit surface

## Alternate packaging options

### Option A — Minimal skill
Only:
- `SKILL.md`

Good for:
- quick experiments
- personal use

### Option B — Recommended
Included in this package.

Good for:
- repeated use
- team sharing
- lower-context loading

### Option C — Expanded project kit
Add:
- a shell script to initialize tags
- a parser script for `run.log`
- a summary formatter
- environment validation checks

Good for:
- heavy operational use
- repeatability across contributors

## Rename before import if desired

If you want strict name-folder matching for upload/import workflows, rename the folder from:

```text
n-autoresearch-skill
```

to:

```text
n-autoresearch
```

and keep:

```yaml
name: n-autoresearch
```

inside `SKILL.md`.
