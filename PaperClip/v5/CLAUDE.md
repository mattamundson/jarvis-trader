# Paperclip — project memory

This is `paperclipai/paperclip`: an open-source control plane for autonomous AI companies.

Before any non-trivial work, read in this order:
1. `AGENTS.md` — contributor rules and V1 contract
2. `doc/GOAL.md` — product vision
3. `doc/PRODUCT.md` — what Paperclip is and is not
4. `doc/SPEC-implementation.md` — concrete V1 build contract
5. `doc/DEVELOPING.md` — dev setup and commands
6. `doc/DATABASE.md` — DB modes, storage, secrets

## Non-negotiable rules

- Company is the first-order boundary. All domain entities are company-scoped.
- Keep contracts synchronized: `packages/db`, `packages/shared`, `server`, `ui`.
- Preserve: single-assignee task model, atomic issue checkout, approval gates, budget hard-stops, activity logging for mutating actions.
- Do not replace strategic docs wholesale. Prefer additive updates.
- Plan docs belong in `doc/plans/YYYY-MM-DD-slug.md`.

## Dev quick-start

```sh
pnpm install
pnpm dev
# API + UI: http://localhost:3100
```

## Subagents available

Use `/paperclip-orient` or invoke by name:
- `paperclip-repo` — cross-package routing and orientation
- `paperclip-core` — domain model reasoning
- `paperclip-db` — schema and migrations
- `paperclip-api` — Express routes and auth
- `paperclip-ui` — React/Vite board UI
- `paperclip-adapters` — runtime integrations
- `paperclip-plugins` — plugin system
- `paperclip-release` — build, test, release

## Extended reference

@.claude/paperclip/docs/root-memory.md
