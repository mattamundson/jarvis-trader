# Contributing to JARVIS TRADER

This guide explains how to work with the JARVIS TRADER codebase and CI/CD pipeline.

## Quick Start for Development

### 1. Setup

```bash
# Clone and enter project
cd jarvis-trader

# Create Python virtual environment
python3.12 -m venv venv
source venv/bin/activate  # Linux/Mac
# OR: venv\Scripts\activate  # Windows

# Install dependencies
cd engine
pip install -r requirements-core.txt
pip install -e ".[dev]"  # Install with dev tools
cd ..

# Setup Node
cd dashboard
npm ci
cd ..
```

### 2. Before Pushing Code

Run these checks locally to catch issues before CI:

```bash
# From engine/ directory
cd engine

# Format code
ruff format .

# Lint code
ruff check . --fix

# Type check
mypy . --ignore-missing-imports

# Run tests
pytest tests/ -v

# Check coverage
pytest tests/ --cov=engine --cov-report=term-missing
```

### 3. Dashboard Development

```bash
cd dashboard

# Dev server
npm run dev
# Opens on http://localhost:3010

# Build for production
npm run build

# Check for linting issues
npm run lint
```

## Code Standards

### Python

- **Line length**: 120 characters
- **Python version**: 3.12+
- **Import order**: handled by ruff (groups: future, stdlib, third-party, first-party, local)
- **Naming**: PEP 8 conventions enforced
- **Type hints**: Use for all public functions

Example:
```python
async def fetch_market_data(
    symbol: str,
    interval: str = "1h",
) -> dict[str, Any]:
    """Fetch OHLCV data for a symbol."""
    # Implementation
    return data
```

### TypeScript/React

- **ESLint**: Run `npm run lint` in dashboard/
- **Components**: Function components with hooks
- **Props**: Typed interfaces for all component props
- **File structure**: `components/`, `app/`, `lib/`

Example:
```typescript
interface ButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

export function Button({ label, onClick, disabled }: ButtonProps) {
  return (
    <button onClick={onClick} disabled={disabled}>
      {label}
    </button>
  );
}
```

## Git Workflow

### Branch naming
- Feature: `feature/add-ema-indicator`
- Bug fix: `fix/websocket-timeout`
- Refactor: `refactor/consolidate-auth`
- Docs: `docs/api-reference`

### Commit messages
- Start with verb: "Add", "Fix", "Update", "Remove", "Refactor"
- Be specific: "Fix rate limit bug in WebSocket handler" (not "fix bug")
- Reference issues: "Fixes #42" (if applicable)

Example:
```
Add consecutive loss tracking to risk manager

- Implement loss counter that resets on profitable trade
- Add validation in safety layer
- Update tests for loss tracking scenarios

Fixes #127
```

### Pull Request checklist

Before opening a PR:
- [ ] Linting passes: `ruff check .`
- [ ] Formatting correct: `ruff format --check .`
- [ ] Type checking passes: `mypy . --ignore-missing-imports`
- [ ] Tests pass: `pytest tests/ -v`
- [ ] No new warnings in mypy output
- [ ] Coverage maintained or improved
- [ ] Branch is up to date with `main`

## Testing

### Unit Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_safety_layer.py -v

# Run specific test
pytest tests/test_safety_layer.py::test_something -v

# Run with coverage
pytest tests/ --cov=engine --cov-report=html
```

### Test markers

```python
@pytest.mark.unit
def test_my_function():
    pass

@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_call():
    pass

@pytest.mark.slow
def test_backtest():
    pass
```

Run specific markers:
```bash
pytest -m unit  # Only unit tests
pytest -m "not slow"  # Skip slow tests
```

### Async tests

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await my_async_func()
    assert result == expected
```

## Common Issues

### Import sorting conflicts
If ruff and mypy disagree on imports:
```bash
# Let ruff fix it (it's the source of truth in CI)
ruff check . --fix
```

### Type checking too strict
If you can't fix a type error:
```python
# Narrow scope of suppression
result = dangerous_call()  # type: ignore[call-arg]

# Don't use bare: # type: ignore
```

### Tests hang
Check for:
- Infinite loops in async code
- Missing `await` statements
- Database connections not closed

Increase timeout if legitimate:
```toml
# In pyproject.toml
[tool.pytest.ini_options]
timeout = 60  # seconds
```

### Coverage too low
Add tests for uncovered code:
```bash
# Generate HTML report
pytest tests/ --cov=engine --cov-report=html
# Open htmlcov/index.html
```

## Security

- Never commit `.env` files (use `.env.example`)
- Never commit API keys or tokens
- Use GitHub Secrets for CI environment variables
- Scan code before pushing: grep for "API_KEY", "SECRET", "PASSWORD"

```bash
# Check for secrets (manually)
grep -r "API_KEY\|PASSWORD\|SECRET" engine/ dashboard/
```

## Performance Tips

### Development
- Use `pytest tests/ -k "test_name"` to run only relevant tests
- Use `ruff format` instead of rerunning linter
- Cache pip packages: `pip cache purge` if needed

### CI
- Keep commits focused on single feature
- Large changes slow down CI (parallel still helps)
- Avoid adding heavy dependencies

## Getting Help

1. Check existing tests for examples
2. Read docstrings and comments in code
3. Review CI logs in GitHub Actions (Settings → Actions)
4. Ask in code review comments

## CI/CD Documentation

See [`.github/CI_CD_GUIDE.md`](CI_CD_GUIDE.md) for:
- Full workflow documentation
- How to interpret CI failures
- Pre-deploy verification steps
- Performance details

## Release Process

When ready to release:

1. Ensure all tests pass on `main`
2. Update `CHANGELOG.md` with changes
3. Tag release: `git tag v0.1.0`
4. Push: `git push origin main --tags`
5. GitHub Actions will run pre-deploy check
6. Deployment proceeds if all checks pass
