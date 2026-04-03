# Playbook: Release / Pre-Push Checklist

Use for: before any `git push`, PR creation, or tagging a version.

---

## Non-Negotiable Pre-Push Gates

All 4 must pass. No exceptions. No shortcuts.

```bash
# Gate 1: Engine tests
cd engine && .venv/Scripts/python -m pytest tests/ -v
# Expected: 0 failures, 0 errors

# Gate 2: Dashboard build
cd dashboard && pnpm run build
# Expected: 16 routes compiled, 0 TypeScript errors

# Gate 3: Secrets check
bash scripts/hooks/check-secrets.sh
# Expected: no new secrets detected

# Gate 4: Safety layer (subset of Gate 1, but verify explicitly)
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v
# Expected: all tests pass
```

---

## Step 1 — Review Changes

```bash
# What changed?
git diff --stat

# What's staged?
git diff --cached --stat

# Full diff
git diff HEAD

# Recent history
git log --oneline -10
```

Check for:
- [ ] No `.env` files staged
- [ ] No `client_secret*.json` staged
- [ ] No `token.json` or `credentials.json` staged
- [ ] No large binary files accidentally included
- [ ] No hardcoded `localhost:8010` in dashboard TypeScript files
- [ ] No hardcoded API keys or secrets in Python files
- [ ] File sizes within limits (400 lines typical, 800 max)

---

## Step 2 — Verify Safety Invariants Unchanged

If any of these files were modified, double-check:

| File | What to verify |
|---|---|
| `engine/risk/safety_layer.py` | Kill switch thresholds unchanged unless Tier 3 approved |
| `engine/config.py` | `LIVE_TRADING_ENABLED = False` still set |
| `engine/config.py` | `REQUIRE_HUMAN_APPROVAL = True` still set |
| `engine/backtest/signals.py` | `INSTRUMENT_PARAMS` unchanged unless walk-forward validated |
| `engine/execution/ib_order_manager.py` | Port 4001 still blocked |

```bash
# Quick invariant check
grep -n "LIVE_TRADING_ENABLED" engine/config.py
grep -n "REQUIRE_HUMAN_APPROVAL" engine/config.py
grep -n "4001" engine/execution/ib_order_manager.py
```

---

## Step 3 — Write the Commit Message

Format (required):

```
<type>: <short imperative description>

<optional body — what changed and why>
<optional footer — breaking changes, closes issues>
```

Types: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`

Examples:
```
feat: add IV rank endpoint for options chain

fix: pipeline error when news analyst returns None report

refactor: split portfolio_router into router + service layer

test: add safety layer tests for cross-market risk

docs: update COMMANDS.md with new analytics endpoints
```

---

## Step 4 — Stage and Commit

```bash
# Stage specific files (never git add . or git add -A without reviewing)
git add engine/routers/new_router.py
git add engine/tests/test_new_router.py
git add dashboard/app/new-page/page.tsx

# Verify what's staged
git diff --cached --stat

# Commit
git commit -m "feat: add new feature description"
```

---

## Step 5 — Push

```bash
# Push to current branch
git push origin <branch-name>

# If on master/main and the user hasn't confirmed, confirm first
# Never force-push main without explicit authorization
```

---

## Step 6 — Verify Post-Push

```bash
# Confirm push succeeded
git log --oneline -3

# Confirm no secrets baseline drift
bash scripts/hooks/check-secrets.sh
```

---

## Branch Strategy

| Branch | Purpose |
|---|---|
| `master` | Current working branch |
| `main` | Production-ready; always deployable |
| `feat/name` | Non-trivial features |
| `fix/name` | Bug fixes |

Non-trivial work should use a feature branch. Ask the user before pushing directly to `main`.

---

## Versioning (if tagging a release)

```bash
# Tag with semantic version
git tag -a v1.2.0 -m "Release v1.2.0 — description"
git push origin v1.2.0
```

Use semantic versioning: `MAJOR.MINOR.PATCH`
- MAJOR: breaking API change or major milestone
- MINOR: new feature, backward-compatible
- PATCH: bug fix

---

## Pre-Release Checklist Summary

```
[ ] pytest: 0 failures
[ ] pnpm build: 0 TS errors, 16 routes
[ ] check-secrets.sh: no new secrets
[ ] test_safety_layer.py: all pass
[ ] LIVE_TRADING_ENABLED = False (verified in config.py)
[ ] No .env files staged
[ ] No hardcoded localhost:8010 in dashboard
[ ] Commit message follows conventional format
[ ] Not pushing to main directly without user confirmation
```

---

## Deliverable

```
gates:          all 4 pass
commit:         <hash> <message>
branch:         <branch name>
pushed:         yes / no
safety check:   invariants verified unchanged
```
