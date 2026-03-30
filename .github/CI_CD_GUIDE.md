# JARVIS TRADER CI/CD Pipeline

This document describes the automated CI/CD pipeline for JARVIS TRADER.

## Overview

The CI/CD pipeline runs on every push to `main` or `develop` branches, and on every pull request to `main`. It ensures code quality, security, and correctness before deployment.

**Total runtime: ~5-10 minutes**

## Workflows

### 1. Continuous Integration (`.github/workflows/ci.yml`)

Runs on:
- Push to `main` or `develop`
- Pull requests to `main`

#### Jobs:

**Job 1: engine-lint** (2-3 min)
- Lints Python code in `engine/` using ruff
- Runs: `ruff check engine/` (code quality)
- Runs: `ruff format --check engine/` (code style)
- Fails if style violations found

**Job 2: engine-typecheck** (2-3 min)
- Type checks Python code using mypy
- Runs: `mypy engine/ --ignore-missing-imports`
- Catches type errors before runtime
- Config: `engine/pyproject.toml`

**Job 3: engine-test** (3-5 min)
- Runs all unit and integration tests
- Runs: `pytest engine/tests/ -v --tb=short`
- Generates coverage report (artifact)
- Continues on failure to show all errors

**Job 4: dashboard-build** (3-5 min)
- Builds Next.js dashboard
- Runs: `npm ci` + `npm run build`
- Catches TypeScript errors
- Verifies production build succeeds

**Job 5: security-scan** (1-2 min)
- Checks for committed `.env` files
- Scans for hardcoded secrets (API keys, tokens)
- Fails if any secrets detected
- Prevents accidental credential leaks

**Job 6: ci-summary**
- Final status check
- Fails if any job failed
- Shows green checkmark if all pass

### 2. Pre-Deploy Verification (`.github/workflows/deploy-check.yml`)

Runs on:
- Push to `main` branch only

This is a stricter gate before production deployment.

#### Checks:
1. **All CI checks** (linting, type-checking, tests, build)
2. **Environment safety**:
   - Ensures `.env` does not exist in repo
   - Ensures `.env.example` exists
3. **Secret verification**: Double-check no secrets in code
4. Requires all checks to pass with `-x` (fail fast)

## Configuration Files

### `engine/ruff.toml`
Linting and formatting rules:
- Line length: 120 chars
- Target: Python 3.12
- Rules: E, W, F, I, N, UP, B, SIM
- Per-file overrides for tests

### `engine/pyproject.toml`
Updated with:
- **pytest config**: test discovery, markers, async mode, logging
- **mypy config**: Python 3.12, strict optional, ignore-missing-imports
- **coverage config**: source exclusions

## How to Use

### Running CI locally

```bash
# Install dev dependencies
cd engine
pip install -e ".[dev]"

# Lint
ruff check . --config ruff.toml
ruff format . --config ruff.toml

# Type check
mypy . --ignore-missing-imports

# Test
pytest tests/ -v --cov=engine --cov-report=term-missing

# Dashboard
cd ../dashboard
npm ci
npm run build
```

### Fixing common CI failures

**Linting errors:**
```bash
cd engine
ruff format .  # Auto-fix style
ruff check . --fix  # Auto-fix code issues
```

**Type errors:**
- Add type hints to function arguments/returns
- Use `Optional[T]` for nullable values
- Check mypy output for specific errors

**Test failures:**
- Review error message in GitHub Actions
- Run locally: `pytest tests/ -v`
- Check logs: `pytest.log`

**Secret detection:**
- Remove hardcoded credentials
- Use `.env.example` for documentation
- Read from environment variables or `.env` at runtime

## Security Best Practices

1. **Never commit `.env` files**
   - Use `.env.example` with dummy values
   - GitHub Actions will reject any `.env` files

2. **No hardcoded secrets**
   - Use environment variables
   - Use GitHub Secrets for sensitive data
   - Scan code before pushing

3. **All checks must pass before merge**
   - Fix linting/types locally first
   - Don't skip CI checks
   - Review coverage reports

## Adding New Tests

1. Create test file: `engine/tests/test_your_feature.py`
2. Use pytest markers:
   ```python
   @pytest.mark.unit
   @pytest.mark.asyncio
   async def test_something():
       pass
   ```
3. Tests run automatically in CI

## Dashboard Build Process

- Next.js build catches TypeScript errors
- ESLint runs via `npm run lint`
- Build output goes to `.next/`
- Fails if any type or lint errors

## Troubleshooting

### "Ruff not found"
```bash
pip install ruff==0.8.0
```

### "Tests timeout"
- Increase timeout in `pyproject.toml`: `timeout = 60`
- Check for hanging async operations

### "Type checking too strict"
- Update mypy config in `pyproject.toml`
- Use `# type: ignore` for exceptional cases
- Add `py.typed` to mark package as typed

### "Coverage too low"
- Add tests for uncovered code
- Check coverage report: `coverage.xml`
- Artifact uploaded to GitHub Actions

## Deployment

Once main branch is green (all CI passed):
1. Pre-deploy check runs on main push
2. All checks must pass
3. Deployment pipeline can proceed
4. Use GitHub Secrets for sensitive deploy vars

## Architecture

```
┌─ Push to main/develop
│
└─► CI Pipeline (ci.yml)
    ├─ engine-lint (ruff)
    ├─ engine-typecheck (mypy)
    ├─ engine-test (pytest)
    ├─ dashboard-build (next build)
    ├─ security-scan
    └─ ci-summary
         │
         └─ All must pass
              │
              └─► Pre-Deploy Check (deploy-check.yml)
                   ├─ All CI + environment safety + secrets scan
                   └─ Ready for deployment
```

## Performance

Each job runs in parallel for speed:
- Python jobs: Ubuntu 22.04 with Python 3.12
- Node jobs: Ubuntu 22.04 with Node 20
- Caching: pip cache, npm cache enabled
- Artifacts: Coverage reports kept for 30 days

Total time: **5-10 minutes** (down from 15+ without parallelization)

## Next Steps

1. Update GitHub branch protection rules:
   - Require CI checks to pass before merge
   - Require code review
2. Set up Slack/email notifications for failures
3. Monitor test coverage trend over time
4. Add performance benchmarks if needed
