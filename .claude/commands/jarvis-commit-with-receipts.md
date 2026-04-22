---
description: Draft a git commit message with attached "receipts" — grep/test output proving the change works. Stages nothing, writes nothing destructive, just prepares the commit body. Matt runs the actual git commit.
allowed-tools: Bash(git:*), Bash(./node_modules/.bin/tsc:*), Bash(.venv/Scripts/python:*), Read, Grep, Glob
argument-hint: "<short summary in imperative, e.g., 'fix MCL inverted stop invariant'>"
---

# Commit With Receipts

**Summary**: $ARGUMENTS

If no summary is given, refuse and ask Matt to provide one.

## Steps

1. Capture diff and changed files:
   ```bash
   cd "C:/Users/mattm/ThinkorSwim/jarvis-trader" && git -c color.ui=false diff --stat HEAD
   cd "C:/Users/mattm/ThinkorSwim/jarvis-trader" && git -c color.ui=false diff --name-only HEAD
   ```

2. For each changed Python file under `engine/`, run a targeted receipt:
   - If a new test was added in `engine/tests/`, run JUST that test file via `engine/.venv/Scripts/python -m pytest <path> -x --no-header -q`. Capture last 20 lines.
   - If a router or agent was modified, grep for 1-2 call sites to show the change is reachable.

3. For each changed TS/TSX file under `dashboard/`, run `./node_modules/.bin/tsc --noEmit` and capture pass/fail.

4. Scan for secrets before committing — refuse to proceed if diff contains any of: `api_key`, `API_KEY`, `-----BEGIN`, `xPRdYjkyUP`, `.env` paths without `.example`. Require Matt to explicitly acknowledge the override.

## Output

Print the proposed commit message — do NOT execute `git commit`:

```
<type>: $ARGUMENTS

<1-2 sentence context>

Receipts:
- <changed file>: <test name> passed / tsc clean / grep shows N call sites intact
- ...

Files touched:
- <list>
```

Where `<type>` is inferred from the summary verb: `fix:`, `feat:`, `refactor:`, `test:`, `docs:`, `chore:`.

Then print this one-liner for Matt to run himself:
```bash
cd "C:/Users/mattm/ThinkorSwim/jarvis-trader" && git add <files> && git commit -m "<message>"
```

## Constraints

- NEVER run `git commit` from this command — Matt runs it manually after reviewing.
- NEVER `git add -A` — the project has ~1,450+ uncommitted GMS-era changes that must not be bulk-staged (per user memory).
- If secret scan fails, STOP and refuse. Do not suggest a workaround.

## Why this exists

Pattern source: `shanraisshan/claude-code-best-practice` (Orchestration Workflow: Command → Agent gathers evidence → Human ships). Combined with the conventional-commits preference in Matt's workflow rules. Solves the "proof-before-push" gap — the user's own rules forbid blind `git add -A` and require receipts for trading-critical changes, but no single command collected them until now.
