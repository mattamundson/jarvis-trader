# File targets and ripgrep patterns

Use this to move quickly from a request to likely files.

## First-stop files

- `AGENTS.md`
- `README.md`
- `doc/GOAL.md`
- `doc/PRODUCT.md`
- `doc/SPEC-implementation.md`
- `doc/DEVELOPING.md`
- `doc/DATABASE.md`
- `doc/DEPLOYMENT-MODES.md`
- `package.json`
- `pnpm-workspace.yaml`

## High-value directories

| Directory | Use for |
|-----------|---------|
| `server/` | API routes, orchestration, auth, packaging |
| `ui/` | React/Vite board UI, API consumers |
| `packages/db/` | Schema, migrations, DB utilities |
| `packages/shared/` | Shared types, constants, validators, API paths |
| `packages/adapters/` | Runtime integrations |
| `packages/adapter-utils/` | Shared adapter helpers |
| `packages/plugins/` | Optional extensions |
| `cli/` | Control-plane CLI |
| `doc/plans/` | Dated plan documents |

## Search recipes by concern

### Company scope and tenant boundaries
```bash
rg -n "companyId|company_id|/api/companies|company-scoped|company scope" server ui packages doc
```

### Budgets and cost control
```bash
rg -n "budgetMonthlyCents|costCents|cost-events|costs/summary|costs/by-agent|auto-paused|hard.stop" server ui packages doc
```

### Approvals and governed actions
```bash
rg -n "approval|approve|approved|governed|board|override|activity.log|activity" server ui packages doc
```

### Issues, tasks, checkout, assignment
```bash
rg -n "issue|task|checkout|assignee|single-assignee|atomic" server ui packages doc
```

### Adapters and runtime execution
```bash
rg -n "adapterType|adapterConfig|execute\(|parse\(|heartbeat|wake|agent.run" packages server ui doc
```

### Auth and actor types
```bash
rg -n "agent_api_keys|Bearer|Authorization|auth|board.access|agent.key|hashed.at.rest" server packages doc
```

### Worktrees and isolated dev instances
```bash
rg -n "worktree|PAPERCLIP_IN_WORKTREE|PAPERCLIP_WORKTREE|seed-mode|repo-local" cli scripts doc server
```

### Embedded DB, storage, secrets
```bash
rg -n "DATABASE_URL|pglite|PGlite|embedded|storage|SECRET_KEY|secrets.migrate" cli server doc
```

### Shared API path constants
```bash
rg -n "API_PATH|apiPath|/api/" packages/shared server ui
```

### Heartbeat scheduling
```bash
rg -n "heartbeat|scheduler|cron|next.run|last.heartbeat|trigger" server packages doc
```

### Plugin host integration
```bash
rg -n "plugin|PluginHost|sdk|workspace.path|extension" packages/plugins server doc
```

## Finding adapter packages

```bash
ls packages/adapters/
rg -n "export" packages/adapters/*/src/index.ts
```

## Finding migration files

```bash
ls packages/db/
rg -rn "migrate|migration" packages/db/
```
