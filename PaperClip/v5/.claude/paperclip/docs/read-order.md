# Read order

The repo declares its own preferred read order in `AGENTS.md`. Use it.

## Mandatory read order for non-trivial work

1. `AGENTS.md`
2. `doc/GOAL.md`
3. `doc/PRODUCT.md`
4. `doc/SPEC-implementation.md`
5. `doc/DEVELOPING.md`
6. `doc/DATABASE.md`

## Why this order matters

- `AGENTS.md` — contributor rules, concrete V1 expectations
- `doc/GOAL.md` — what the product is trying to become
- `doc/PRODUCT.md` — what Paperclip is and is not (guards against scope creep)
- `doc/SPEC-implementation.md` — concrete build contract; controls V1 behavior over SPEC.md
- `doc/DEVELOPING.md` — how the repo is actually run
- `doc/DATABASE.md` — DB modes, storage, secrets, embedded vs. hosted implications

## Minimum read sets by task

### Orientation only
- `AGENTS.md`
- `doc/PRODUCT.md`
- `.claude/paperclip/docs/repo-map.md`

### DB or schema change
- `AGENTS.md`
- `doc/SPEC-implementation.md`
- `doc/DATABASE.md`
- `.claude/paperclip/docs/repo-map.md`
- `.claude/paperclip/docs/file-targets-and-rg.md`

### API / server change
- `AGENTS.md`
- `doc/SPEC-implementation.md`
- `doc/DEVELOPING.md`
- `.claude/paperclip/docs/repo-map.md`
- `.claude/paperclip/docs/file-targets-and-rg.md`

### UI change
- `AGENTS.md`
- `doc/PRODUCT.md`
- `doc/SPEC-implementation.md`
- `.claude/paperclip/docs/repo-map.md`
- `.claude/paperclip/docs/file-targets-and-rg.md`

### Adapter change
- `AGENTS.md`
- `doc/PRODUCT.md`
- `doc/DEVELOPING.md`
- `.claude/paperclip/docs/repo-map.md`
- `.claude/paperclip/docs/file-targets-and-rg.md`

### Plugin change
- `AGENTS.md`
- `doc/plugins/PLUGIN_SPEC.md`
- `doc/plugins/PLUGIN_AUTHORING_GUIDE.md`
- `.claude/paperclip/docs/repo-map.md`

### Release / dev-env issue
- `AGENTS.md`
- `doc/DEVELOPING.md`
- `doc/DATABASE.md`
- `.claude/paperclip/docs/dev-commands.md`
- `.claude/paperclip/docs/review-checklists.md`
