# Development commands

## Requirements

- Node `>=20`
- PNPM `9.15.4` (declared by repo)

## Fastest local start

```bash
pnpm install
pnpm dev
```

- API: `http://localhost:3100`
- UI: `http://localhost:3100` (served by API in dev middleware mode)
- DB: embedded PGlite auto-used when `DATABASE_URL` is unset

## Quick health checks

```bash
curl http://localhost:3100/api/health
curl http://localhost:3100/api/companies
```

## Reset local dev DB

```bash
rm -rf data/pglite
pnpm dev
```

## Common top-level commands

### Development
```bash
pnpm dev
pnpm dev:watch
pnpm dev:once
pnpm dev:list
pnpm dev:stop
pnpm dev:server
pnpm dev:ui
```

### Build / types / tests
```bash
pnpm build
pnpm typecheck
pnpm test
pnpm test:run
pnpm test:e2e
pnpm test:e2e:headed
pnpm test:release-smoke
pnpm test:release-smoke:headed
```

### Database
```bash
pnpm db:generate     # generate migration after schema change
pnpm db:migrate      # apply migrations
pnpm db:backup
```

### Release / packaging
```bash
pnpm build:npm
pnpm release
pnpm release:canary
pnpm release:stable
pnpm release:github
pnpm release:rollback
```

### CLI / utilities
```bash
pnpm paperclipai
pnpm secrets:migrate-inline-env --apply
pnpm check:tokens
```

## Server package commands (inside `server/`)

```bash
pnpm dev
pnpm dev:watch
pnpm build
pnpm start
pnpm typecheck
```

## UI package commands (inside `ui/`)

```bash
pnpm dev
pnpm build
pnpm preview
pnpm typecheck
pnpm clean
```

## CLI commands (inside `cli/`)

```bash
pnpm build
pnpm typecheck
pnpm test
pnpm test:run
```

## Database modes

| Mode | When to use | How |
|------|-------------|-----|
| Embedded PGlite | Default local dev, onboarding | Leave `DATABASE_URL` unset |
| Local Docker Postgres | Fuller local environment | Set `DATABASE_URL` to Docker instance |
| Hosted Postgres | Production / shared | Set `DATABASE_URL` to hosted instance |

## DB change workflow

1. Edit `packages/db/src/schema/*.ts`
2. Export new tables from `packages/db/src/schema/index.ts`
3. `pnpm db:generate`
4. `pnpm typecheck`
5. Update `packages/shared` types/validators
6. Update `server` routes/services
7. Update `ui` consumers
