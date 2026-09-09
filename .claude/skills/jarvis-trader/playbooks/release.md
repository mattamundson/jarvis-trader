# Playbook: Release / Pre-Push Checklist

Use for: before any `git push`, PR creation, or tagging a version.

---

## Non-Negotiable Pre-Push Gates

All applicable gates must execute successfully. No shortcuts. A gate that did not execute is not a pass.

```bash
# Gate 1: Engine tests
cd engine && .venv/Scripts/python -m pytest tests/ -v
# Expected: 0 failures, 0 errors

# Gate 2: Dashboard build
cd dashboard && pnpm run build
# Expected: production build succeeds with no TypeScript/build errors

# Gate 3: Secrets check
bash scripts/hooks/check-secrets.sh
# Expected: no new secrets detected

# Gate 4: Safety layer (subset of Gate 1, but verify explicitly)
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v
# Expected: all tests pass
```

If hosted CI creates a job but no runner executes any step, record `CI-INFRA / NO VALIDATION EXECUTED`; do not treat the red badge as a code failure or the existence of the job as a pass.

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

## Step 2 — Verify Safety / Authorization Boundaries

If any of these files were modified, double-check:

| File | What to verify |
|---|---|
| `engine/risk/safety_layer.py` | Kill-switch/risk behavior is unchanged unless the exact policy change has required safety review |
| `engine/config.py` | repository LIVE default remains disabled unless the exact bounded LIVE change is explicitly authorized |
| `engine/config.py` / runtime evidence | `REQUIRE_HUMAN_APPROVAL` is compared with the current governing decision and observed runtime when relevant — **do not assume a historical True/False literal** |
| `engine/backtest/signals.py` | strategy parameters unchanged unless the change carries required research/validation evidence |
| IB broker/adapter code | live-capital routing remains unavailable unless explicitly authorized and reviewed |

```bash
# Quick source checks (source state only — not proof of loaded runtime values)
grep -n "LIVE_TRADING_ENABLED" engine/config.py
grep -n "REQUIRE_HUMAN_APPROVAL" engine/config.py
grep -R -n "4001" engine | head
```

Repository defaults and documentation are not substitutes for loaded runtime truth. If the release depends on actual mode, approval state, broker port/account, or active risk limits, require the A-01/runtime receipt and report contradictions rather than choosing a value by assumption.

A phase number, date, readiness score, test result, PAPER result, merged PR, or agent/LLM recommendation never grants LIVE capital authority.

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

After push, record the exact head SHA and the actual evidence state. A workflow that never receives a runner remains `CI-INFRA`, not verified.

---

## Branch Strategy

| Branch | Purpose |
|---|---|
| `master` | Current working branch |
| `main` | Production-ready; always deployable |
| `feat/name` | Non-trivial features |
| `fix/name` | Bug fixes |

Non-trivial work should use a feature branch. Never force-push a protected/canonical branch without explicit authorization.

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

A tag/version is a software identity, not trading-environment or capital authorization.

---

## Pre-Release Checklist Summary

```
[ ] pytest: 0 failures
[ ] pnpm build: production build succeeds
[ ] check-secrets.sh: no new secrets
[ ] test_safety_layer.py: all pass
[ ] repository LIVE default inspected; runtime LIVE state observed if the release depends on it
[ ] approval/risk values not inferred from stale docs when runtime truth is required
[ ] exact-head CI state recorded: PASS / FAIL / BLOCKED / CI-INFRA
[ ] No .env files staged
[ ] No hardcoded localhost:8010 in dashboard
[ ] Commit message follows conventional format
[ ] No protected/canonical branch force-push without explicit authorization
```

---

## Deliverable

```
gates:          executed result per gate
commit:         <hash> <message>
branch:         <branch name>
pushed:         yes / no
hosted CI:      PASS / FAIL / BLOCKED / CI-INFRA
safety check:   invariant/authority review result
runtime truth:  observed receipt ID / UNVERIFIED-NOT-REQUIRED / BLOCKED
```
