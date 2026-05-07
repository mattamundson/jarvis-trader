# .git-hooks — Opt-in Git Hooks for jarvis-trader

This directory contains git hooks that are **not installed automatically**. They run the same toolchain as CI but are opt-in so you can commit work-in-progress with intentional lint violations without being blocked.

---

## pre-commit

Runs `ruff` lint + `mypy` type-check on staged `.py` files before each commit. Only checks files staged for commit (not the full tree), so it stays fast.

### Install

**Option A — hooksPath (recommended; applies to this repo only):**

```bash
git config core.hooksPath .git-hooks
```

This is reversible. To unset:

```bash
git config --unset core.hooksPath
```

**Option B — copy into .git/hooks:**

```bash
cp .git-hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Note: `.git/` is not tracked, so this survives only on your machine.

### What it checks

| Tool | Config | Scope |
|------|--------|-------|
| `ruff check` | `engine/ruff.toml` | Staged `.py` files only |
| `mypy` | `engine/pyproject.toml` | Staged `.py` files only |

Ruff auto-fix is **not** enabled — the hook shows errors and aborts so you see exactly what needs fixing.

### Emergency bypass (one-time)

```bash
git commit --no-verify -m "wip: ..."
```

Per `~/.claude/rules/git-hygiene.md`: don't make `--no-verify` a habit.

### Relationship to .pre-commit-config.yaml

`.pre-commit-config.yaml` (repo root) handles ruff + ruff-format via the `pre-commit` framework and also runs secret detection. If you have `pre-commit install` configured, both will run.

The hook in this directory is a lightweight alternative: no `pip install pre-commit` required, adds mypy coverage (not in `.pre-commit-config.yaml`), and is easier to audit.

### Venv requirement

The hook uses `engine/.venv/Scripts/python.exe`. The venv must be set up:

```powershell
cd engine
python -m venv .venv
.venv\Scripts\pip install -r ..\requirements-core.txt
```

If the venv is missing, the hook exits with an error pointing at the missing binary.
