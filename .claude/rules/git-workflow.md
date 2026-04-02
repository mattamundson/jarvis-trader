# Git Workflow — JARVIS TRADER

## Commit Message Format

Conventional commits are required:
- `feat:` — New feature
- `fix:` — Bug fix
- `refactor:` — Code restructure (no behavior change)
- `docs:` — Documentation changes
- `test:` — Adding or fixing tests
- `chore:` — Build, tooling, CI changes

Examples:
- `feat: add options chain endpoint to API`
- `fix: VIX regime tier naming 5→6 tiers`
- `docs: restructure root docs into organized subdirectories`

## Security Rules

- **NEVER commit**: `.env`, `engine/.env`, credentials, API keys, bearer tokens
- **NEVER commit**: `client_secret*.json`, `token.json`, `credentials.json`
- **Before pushing**: Run `bash scripts/hooks/check-secrets.sh`
- The `.secrets.baseline` file is the approved baseline — update it after adding new non-secret patterns

## Pre-Push Checklist

1. `cd dashboard && pnpm run build` — must pass
2. `cd engine && pytest tests/ -v` — must pass
3. `bash scripts/hooks/check-secrets.sh` — must show no new secrets
4. Review `git diff --stat` — no large generated files, no .env files

## Branch Strategy

- `main` — production-ready, always deployable
- `master` — current working branch (per git status)
- Feature branches for non-trivial work: `feat/options-api`, `fix/vix-tiers`, etc.
- Never force-push `main` without explicit authorization
