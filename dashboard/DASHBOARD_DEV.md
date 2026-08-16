# Editing the dashboard in Cursor

The dashboard is a Next.js 15 / React 19 app. It runs **two ways**:

| | Port | How | Hot-reload? |
|---|---|---|---|
| **Production** (live) | 3010 | pm2 `jarvis-dashboard` -> `next start` (static build) | No — needs rebuild |
| **Dev** (editing) | 3011 | `pnpm dev:cursor` -> `next dev` | Yes — instant |

The dev server runs **alongside** prod, so the live dashboard stays up on 3010 while you edit on 3011.

## Workflow

1. **Open in Cursor**
   ```powershell
   cursor C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard
   ```

2. **Start the hot-reload dev server** (from `dashboard/`)
   ```powershell
   ./dev-cursor.ps1            # or: pnpm dev:cursor
   ./dev-cursor.ps1 -Open      # also opens the browser
   ```
   Preview at **http://127.0.0.1:3011**. Save a file -> the page updates instantly.
   API calls proxy to the engine (`127.0.0.1:8010`) automatically; auth is read from
   `.env.local`.

3. **Edit.** Cursor's AI follows the guardrails in `.cursor/rules/dashboard-conventions.mdc`
   (pnpm only, `fetchEngine`/`postEngine` only, strict `<Badge>` variants, App Router,
   Tailwind tokens). New nav links go in `components/Sidebar.tsx`.

4. **Promote to the live dashboard (3010)** — one sanctioned command
   ```powershell
   pwsh -File scripts/deploy-local.ps1
   ```
   This is the **only** supported local deploy path. It runs install ->
   typecheck -> unit tests -> build *before* touching pm2, aborts without
   restarting if any of those fail, then restarts pm2 and verifies the result
   by fetching the served page and checking that **every** `/_next/static`
   chunk it references actually returns 200.

   That last check is the point. `dashboard/` is simultaneously the source tree
   and pm2's serving directory, so a bare `pnpm build` here *is* a production
   deploy — and if nobody restarts pm2 afterwards, the running server can serve
   HTML referencing chunks that no longer exist. A 200 on the page alone does
   not catch that; an exit code catches even less.

## Notes
- **`pnpm`, never `npm`** (npm is broken on this machine).
- Don't run `pnpm dev` (it's pinned to 3010 and collides with prod). Use `pnpm dev:cursor` / `dev-cursor.ps1`.
- **Never run a bare `pnpm build` to deploy.** It publishes to the live serving
  directory with no typecheck, no tests, and no restart. Use `deploy-local.ps1`.
- The dashboard is **display/control only** — never put trade-safety logic in the client. Safety lives in the engine.
