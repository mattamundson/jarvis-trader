# Deploying the dashboard to Vercel (public site, engine behind a tunnel)

Architecture:

```
Browser ── HTTPS ──► Vercel (login-gated)
                       │  app/api/engine/[...path]/route.ts  (server-side proxy)
                       │  injects X-API-Key from ENGINE_API_KEY
                       ▼
              Cloudflare Tunnel (public HTTPS)
                       ▼
              Your PC ── engine :8010  (X-API-Key auth on every non-/health route)
```

The browser never sees the engine key. The engine is only reachable with the key,
and the Vercel site is itself behind a login gate (Deployment Protection).

**The site only serves live data while your PC + engine + the tunnel are all running.**
When the PC sleeps or the tunnel stops, pages render but data calls fail. Expected.

Live URLs (current project `matts-projects-fc4f64e1/jarvis-trader`):
- Site:  https://jarvis-trader-plum.vercel.app
- Env vars page: https://vercel.com/matts-projects-fc4f64e1/jarvis-trader/settings/environment-variables

---

## The engine tunnel (Cloudflare)

### Quick tunnel (ephemeral URL — fastest, changes on every restart)

```powershell
cloudflared tunnel --url http://localhost:8010
```

Prints `https://<random-words>.trycloudflare.com`. Leave the window open. That URL
is the engine's public address. **It changes every time you restart cloudflared**, so
after a restart you must update Vercel's `ENGINE_INTERNAL_URL` to the new URL and
redeploy (`vercel --prod --archive=tgz`).

### Named tunnel (stable URL — set up once, survives restarts)

See `## Stable tunnel` at the bottom. A named tunnel keeps the same URL forever and
can auto-start as a Windows service, so you never touch Vercel env vars again.

---

## One-time Vercel setup (already done, kept for reference)

1. From `dashboard/`: `vercel login` then `vercel link`
   (existing project `jarvis-trader`; root directory = `dashboard`).
2. Env vars (set in the web UI — the CLI's "Store as sensitive?" prompt fouls piping):
   open the env-vars page above and add, both for **Production**:
   - `ENGINE_INTERNAL_URL` = the tunnel URL (no trailing slash)
   - `ENGINE_API_KEY`     = the value of `API_KEY=` from `engine/.env`
3. Settings → General/Build → **Root Directory = `dashboard`**.
4. Settings → **Deployment Protection → Vercel Authentication = On**.

To copy the engine key to your clipboard without printing it:
```powershell
((Select-String -Path C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env -Pattern '^API_KEY=' | Select-Object -First 1).Line -split '=',2)[1].Trim() | Set-Clipboard
```

---

## Deploying

From `dashboard/`:

```powershell
vercel --prod --archive=tgz
```

`--archive=tgz` is required: a plain `vercel --prod` tries to upload node_modules
(~40k files) and hits Vercel's 15000-file limit. `.vercelignore` excludes the bulk;
`--archive=tgz` bundles the rest. Build runs remotely (~1-3 min) and prints the
production URL.

The local prod dashboard on :3010 (pm2) is independent of Vercel and unaffected.

---

## After a Cloudflare quick-tunnel restart (ephemeral URL only)

1. Note the new `https://<...>.trycloudflare.com` URL.
2. Update Vercel env var `ENGINE_INTERNAL_URL` to it (web UI).
3. Redeploy: `vercel --prod --archive=tgz`.

(The named tunnel below removes this chore entirely.)

---

## Known limitation — WebSocket pages

Live-tick panels (anything using `lib/engine-websocket-context.tsx`,
`hooks/useWebSocket.ts`, `lib/pipeline_ws.ts`) connect **directly** to the engine
WS and can't go through the Vercel proxy (serverless doesn't proxy WebSockets).
They degrade gracefully (show "disconnected", retry quietly) and keep working on the
local :3010 dashboard. REST pages — including Hidden Pivots — work fully on Vercel.
Making live panels work remotely needs engine-side short-lived WS token auth
(deliberately deferred to avoid exposing the key in the browser).

---

## Stable tunnel (named Cloudflare tunnel)

A named tunnel gives a permanent URL and can run as a Windows service. Requires a
domain managed in Cloudflare (the tunnel is routed to e.g. `engine.yourdomain.com`).

```powershell
cloudflared tunnel login                              # browser auth, one time
cloudflared tunnel create jarvis-engine               # creates tunnel + credentials json
cloudflared tunnel route dns jarvis-engine engine.<yourdomain>   # stable hostname
# config.yml: tunnel: <id>; credentials-file: <path>; ingress: [ {hostname: engine.<yourdomain>, service: http://localhost:8010}, {service: http_status:404} ]
cloudflared tunnel run jarvis-engine                  # or install as a service:
cloudflared service install
```

Then set Vercel `ENGINE_INTERNAL_URL = https://engine.<yourdomain>` once and never
touch it again.
