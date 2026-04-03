# JARVIS TRADER CI/CD - Quick Start

Get the CI/CD pipeline running in 5 minutes.

## Step 1: Verify Files Were Created (1 min)

All these files should exist:
```
.github/
├── workflows/
│   ├── ci.yml                    ✓ Main pipeline
│   └── deploy-check.yml          ✓ Deploy gate
├── CI_CD_GUIDE.md               ✓ Full docs
├── CONTRIBUTING.md              ✓ Dev guide
├── CI_CD_SETUP_SUMMARY.md       ✓ Overview
└── QUICK_START.md               ✓ This file

engine/
├── ruff.toml                    ✓ Linting rules
├── pyproject.toml               ✓ Tool config
└── tests/                       ✓ Test suite
```

Verify:
```bash
ls -la .github/workflows/ci.yml
ls -la engine/ruff.toml
```

## Step 2: Test Locally (2 min)

Before pushing, verify setup works:

```bash
# Python linting & type checking
cd engine
pip install ruff mypy
ruff check .
mypy . --ignore-missing-imports

# Run tests
pip install -r requirements-core.txt
pytest tests/ -v -k "not slow" --tb=short

# Dashboard
cd ../dashboard
npm ci
npm run build
```

If all pass, you're good to go!

## Step 3: Push to Main/Develop (1 min)

```bash
git add .
git commit -m "Setup: Add CI/CD pipeline"
git push origin main
```

## Step 4: Monitor CI (1 min)

1. Go to: **GitHub → Actions tab**
2. You should see "JARVIS TRADER CI" running
3. Wait for all jobs to complete (5-10 min)
4. All jobs should show ✓ green checkmarks

## Expected Results

### On Every Push to main/develop or PR to main:

**ci.yml runs:**
- `engine-lint` ✓ (2-3 min)
- `engine-typecheck` ✓ (2-3 min)
- `engine-test` ✓ (3-5 min)
- `dashboard-build` ✓ (3-5 min)
- `security-scan` ✓ (1-2 min)
- `ci-summary` ✓ aggregates results

**Total: 5-10 minutes**

### On Push to main ONLY:

**deploy-check.yml also runs:**
- Repeats all CI checks
- Verifies .env.example exists
- Verifies no .env committed
- Confirms no hardcoded secrets
- Fails fast on first error

## Fixing Common Issues

### "Linting failed"
```bash
cd engine
ruff check . --fix  # Auto-fix
ruff format .      # Auto-format
git add -A && git commit -m "fix: lint"
```

### "Type checking failed"
```bash
cd engine
mypy . --ignore-missing-imports  # Check output
# Add type hints where needed
```

### "Tests failed"
```bash
cd engine
pytest tests/ -v  # Run locally
pytest tests/test_file.py -v -s  # Debug specific test
```

### "Security scan detected secrets"
- Remove hardcoded API keys from code
- Use environment variables instead
- Use `.env.example` for documentation

### ".env file was committed"
```bash
git rm --cached engine/.env
echo ".env" >> .gitignore
git add .gitignore
git commit -m "fix: remove .env from repo"
```

## Configuration Customization

### Adjust Python version
Edit `.github/workflows/ci.yml`:
```yaml
- uses: actions/setup-python@v5
  with:
    python-version: '3.11'  # Change here
```

### Adjust line length
Edit `engine/ruff.toml`:
```toml
line-length = 100  # Change from 120
```

### Disable a linting rule
Edit `engine/ruff.toml`:
```toml
ignore = [
    "E501",
    "W503",
    "UP009",  # Add here
]
```

### Add test marker
Edit `engine/pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "my_marker: my marker",
]
```

### Increase test timeout
Edit `engine/pyproject.toml`:
```toml
[tool.pytest.ini_options]
timeout = 60  # Change from 30
```

## Enable Branch Protection (Recommended)

To prevent merging without CI passing:

1. Go to **GitHub → Settings → Branches**
2. Add rule for `main`:
   - Require CI checks: ✓
   - Require code review: ✓
   - Dismiss stale reviews: ✓

## Local Commands Reference

```bash
# Lint & format
cd engine
ruff format .
ruff check . --fix

# Type check
mypy . --ignore-missing-imports

# Run tests (all)
pytest tests/ -v

# Run specific test
pytest tests/test_file.py::test_function -v

# Run with coverage
pytest tests/ --cov=engine --cov-report=html

# Skip slow tests
pytest tests/ -v -m "not slow"

# Dashboard dev
cd dashboard
npm run dev  # http://localhost:3010
npm run build
npm run lint
```

## Next Steps

1. **Read** `.github/CI_CD_GUIDE.md` for full documentation
2. **Review** `.github/CONTRIBUTING.md` for development guidelines
3. **Enable** branch protection rules in GitHub
4. **Set up** GitHub Secrets for sensitive environment variables
5. **Monitor** Actions tab for CI trends

## Questions?

- Full guide: `.github/CI_CD_GUIDE.md`
- Development: `.github/CONTRIBUTING.md`
- Overview: `.github/CI_CD_SETUP_SUMMARY.md`
- Repo config: `engine/pyproject.toml`, `engine/ruff.toml`

---

**Status**: Ready to use
**Total setup time**: 5 minutes
**First CI run time**: 5-10 minutes
