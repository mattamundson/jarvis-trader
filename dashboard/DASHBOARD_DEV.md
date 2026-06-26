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

4. **Check before promoting**
   ```powershell
   pnpm typecheck      # tsc --noEmit, must be clean
   pnpm build          # full build, ~40 routes, 0 TS errors
   ```

5. **Promote to the live dashboard (3010)**
   ```powershell
   pnpm build
   pm2 restart jarvis-dashboard
   ```

## Notes
- **`pnpm`, never `npm`** (npm is broken on this machine).
- Don't run `pnpm dev` (it's pinned to 3010 and collides with prod). Use `pnpm dev:cursor` / `dev-cursor.ps1`.
- The dashboard is **display/control only** — never put trade-safety logic in the client. Safety lives in the engine.
