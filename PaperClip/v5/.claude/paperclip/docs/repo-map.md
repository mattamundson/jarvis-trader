# Repository map

## Monorepo shape

Paperclip uses a PNPM workspace monorepo.

Top-level workspace members:
- `server/`
- `ui/`
- `cli/`
- `packages/*`
- `packages/adapters/*`
- `packages/plugins/*`
- `packages/plugins/examples/*`

## Primary folders

### `server/`
Express-based API and orchestration services.
- REST routes
- control-plane orchestration logic
- auth (board operator sessions, agent API keys, run tokens)
- service coordination
- local dev server entrypoints

### `ui/`
React + Vite board UI.
- company-facing control-plane screens
- API client integration
- navigation / routes
- task, org, budget, approval, and agent-management interfaces

### `packages/db/`
Drizzle schema, migrations, DB clients, persistence contracts.
- schema evolution
- migrations
- DB utilities
- persistence boundaries

### `packages/shared/`
Shared types, constants, validators, and API path constants.
Change this when behavior changes affect contracts shared by server and UI.

### `packages/adapters/`
Adapter implementations for different agent runtimes/providers.
Each adapter covers:
- execution model
- config shape
- heartbeat / wakeup integration
- provider-specific behavior

Built-in adapters: `process`, `http`. Others: Claude Code, Codex, Cursor, OpenClaw.

### `packages/adapter-utils/`
Shared helper logic across adapters.

### `packages/plugins/`
Plugin system packages — optional or environment-specific capabilities.

### `cli/`
Control-plane CLI.
- onboarding
- worktree management
- doctor / health checks
- company import/export

### `doc/`
Operational and product docs. Treat as implementation context, not decoration.

Key doc files:
- `doc/GOAL.md`
- `doc/PRODUCT.md`
- `doc/SPEC-implementation.md`
- `doc/SPEC.md`
- `doc/DEVELOPING.md`
- `doc/DATABASE.md`
- `doc/DEPLOYMENT-MODES.md`
- `doc/CLI.md`
- `doc/plans/` — all dated plan documents

## Mental model

Paperclip is the control plane, not the execution plane.
- Agents run externally and phone home
- Core job: orchestration, governance, tracking, visibility
- Features should trace back to company/goal/agent/task/budget/approval lifecycle

## Existing repo skill directories

The repo already has its own:
- `.claude/skills/` — design-guide, company-creator, paperclip
- `.agents/skills/` — company-creator, create-agent-adapter, doc-maintenance, pr-report, release, release-changelog

Do not overwrite these. The V5 pack uses `.claude/paperclip/docs/` as its namespace.
