# Deploying the dashboard to Vercel (public site, engine behind a tunnel)

Architecture:

```
Browser ── HTTPS ──► Vercel (login-gated)
                       │  app/api/engine/[...path]/route.ts  (server-side proxy)
                       │  injects X-API-Key from ENGINE_API_KEY
                       ▼
              Tailscale Funnel (public HTTPS)
                       ▼
              Your PC ── engine :8010  (X-API-Key auth on every non-/health route)
```

The browser never sees the engine key. The engine is only reachable with the key,
and the Vercel site is itself behind a login gate. Three gates, no open doors.

**The site only serves live data while your PC + engine + the funnel are all running.**
When the PC sleeps, pages render but data calls 502. That is expected.

---

## One-time setup

### 1. Start the engine tunnel (you run this — needs your tailnet auth)

```powershell
tailscale funnel 8010
```

Leave it running. It prints a public URL like:

```
https://<your-machine>.<tailnet>.ts.net
```

Copy that URL — it is `ENGINE_INTERNAL_URL` below. Verify it reaches the engine:

```powershell
curl https://<your-machine>.<tailnet>.ts.net/health   # -> {"status":"ok",...}
```

(No CORS change is needed — the Vercel proxy calls the engine server-to-server,
which is not subject to browser CORS.)

### 2. Link the project (you run — interactive login)

From `dashboard/`:

```powershell
vercel login
vercel link            # create/link a project; set ROOT DIRECTORY = . (you are already in dashboard/)
```

### 3. Set the two server-only env vars (you run — paste values when prompted)

```powershell
vercel env add ENGINE_INTERNAL_URL production
#   paste: https://<your-machine>.<tailnet>.ts.net   (no trailing slash)

vercel env add ENGINE_API_KEY production
#   paste the key from engine/.env  (X-API-Key value) — do NOT prefix with NEXT_PUBLIC_
```

Repeat both for `preview` if you want preview deploys to work too.

### 4. Turn on Deployment Protection (REQUIRED — the site is public)

Vercel dashboard → Project → Settings → Deployment Protection → enable
**Vercel Authentication** (or a password). This is the login gate; without it,
anyone with the URL can drive the proxy.

### 5. Deploy

```powershell
vercel --prod
```

Open the printed URL, log in through the gate, and load `/hidden-pivots`.

---

## Known limitation — WebSocket pages

Live-tick panels (anything using `lib/engine-websocket-context.tsx`,
`use-websocket.ts`, `useWebSocket.ts`) hardcode `ws://127.0.0.1:8010` and will not
connect from Vercel. REST pages — including Hidden Pivots — work fine. The WS
contexts need a refactor to a tunneled/proxied WS URL before live-streaming panels
work remotely. Tracked as a follow-up.

## Redeploying after dashboard changes

```powershell
git push                  # if using Git integration, this auto-deploys
# or, manual:
vercel --prod
```

The local prod dashboard on :3010 (pm2) is independent of Vercel and unaffected.
