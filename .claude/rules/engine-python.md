---
paths:
  - "engine/**/*.py"
---

# Engine Python Rules

## Runtime
- Always use `engine/.venv/Scripts/python` — never system Python 3.14 or Store Python
- Never run with `--reload` flag — it creates duplicate IB Gateway connections
- Restart via `.\restart_engine.ps1` after config changes

## Code Style
- Async with graceful sync fallback (`try: async; except: sync`)
- Pydantic v2 for all models (`model_config = ConfigDict(...)`, not `class Config`)
- ruff-clean — zero lint errors before commit
- File size: 400 lines typical, 800 absolute max
- Type hints on all public functions

## Testing
- `cd engine && .venv/Scripts/python -m pytest tests/ -v`
- New behavior requires new test
- `tests/test_safety_layer.py` is SACRED — never modify to make a failing test pass
- asyncio_mode = auto (set in pyproject.toml)

## Imports
- Relative imports within engine packages
- `from engine.config import settings` for config access
- `from engine.risk.safety_layer import SafetyLayer` for safety

## API Patterns
- All routes return Pydantic models
- Use `HTTPException` for 4xx errors, not raw dicts
- All background tasks use `BackgroundTasks` or `asyncio.create_task`

## Safety — Mandatory
- Never modify `SafetyLayer` logic without Tier 3 confirmation
- Never add `except Exception: pass` near safety checks
- Never use LLM output to drive safety decisions
