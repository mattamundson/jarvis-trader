# Deploying the dashboard to Vercel (public site, engine behind an ngrok tunnel)

This is the **as-built** runbook for `jarvis-trader-plum.vercel.app`. It reflects the
live setup (ngrok service + 3-layer auth), not the earlier Cloudflare/Tailscale drafts
those were abandoned (Tailscale Funnel was never enabled on the tailnet; Cloudflare
quick-tunnels were ephemeral). ngrok-as-a-service is what's actually running.

## Architecture

```
Browser ── HTTPS ──► Vercel (login-gated: Deployment Protection)
                       │  app/api/engine/[...path]/route.ts  (server-side proxy, runtime=nodejs)
                       │  injects, server-side only:
                       │    X-API-Key:      from ENGINE_API_KEY
                       │    Authorization:  Basic base64(ENGINE_TUNNEL_BASIC_AUTH)
                       │    ngrok-skip-browser-warning: true
                       ▼
              ngrok tunnel (public HTTPS, static domain, basic-auth enforced)
                       ▼
              Your PC ── engine :8010  (X-API-Key auth on every non-/health route)
```

**Three independent auth layers** — the browser carries none of them:
1. **Vercel login gate** (Deployment Protection) — gates who can load the site at all.
2. **ngrok basic-auth** — gates who can reach the tunnel (cred stored in `ngrok.yml`).
3. **engine X-API-Key** — gates the engine itself.

The proxy adds (2) and (3) **server-side**, so the engine key and the basic-auth
credential never reach the browser bundle.

**The site only serves live data while your PC + engine + ngrok service are all up.**
PC asleep / engine down / tunnel stopped → pages render, data calls 502. Expected.
The `Jarvis-TunnelHealth` task (below) alerts to Telegram when the public path breaks.

Live URLs (project `matts-projects-fc4f64e1/jarvis-trader`):
- Site:          https://jarvis-trader-plum.vercel.app
- Env vars page: https://vercel.com/matts-projects-fc4f64e1/jarvis-trader/settings/environment-variables

---

## The engine tunnel (ngrok, static domain, runs as a Windows service)

The tunnel is an **always-on Windows service** — no window to keep open, survives logoff,
auto-starts at boot. Static domain, so the URL never changes and Vercel env vars stay put.

- Static domain: `https://perioecic-piper-postsigmoid.ngrok-free.dev` → `127.0.0.1:8010`
- Config: `%LOCALAPPDATA%\ngrok\ngrok.yml` (version "3"; tunnel name `jarvis-engine`;
  basic-auth enforced via a `traffic_policy` block)
- Service: `Get-Service ngrok` should be **Running / Automatic**
- Logon launcher (idempotent backstop): `~/scripts/launch-ngrok-jarvis.ps1`,
  run by the `Jarvis-Ngrok-AtLogon` task — only starts an agent if none is running.

Operate the service:
```powershell
Get-Service ngrok                 # status
ngrok service start               # if Stopped
Restart-Service ngrok             # after editing ngrok.yml
```

### ngrok free-tier caveats (why the proxy has the headers it does)
- **1 concurrent agent session.** A second `ngrok start` anywhere kills the first
  (`ERR_NGROK_3200`). The service IS that one session don't also run a manual `ngrok http`.
- **Browser-warning interstitial.** Free tier injects an HTML splash for browser-like
  requests; the proxy sends `ngrok-skip-browser-warning: true` to always get JSON.
- **Bandwidth/request caps** apply — fine for personal dashboard use, not public traffic.

---

## Vercel environment variables (Production)

Three vars, all **Production** scope. `ENGINE_API_KEY` and `ENGINE_TUNNEL_BASIC_AUTH`
must be **Sensitive**.

| Variable                   | Value                                                  | Sensitive |
|----------------------------|--------------------------------------------------------|-----------|
| `ENGINE_INTERNAL_URL`      | the ngrok static domain (no trailing slash)            | no        |
| `ENGINE_API_KEY`           | value of `API_KEY=` from `engine/.env`                 | **yes**   |
| `ENGINE_TUNNEL_BASIC_AUTH` | `user:pass` matching the basic-auth in `ngrok.yml`     | **yes**   |

Set via CLI (the `--sensitive` flag avoids the interactive "Store as sensitive?" prompt
that fouls piping):
```powershell
vercel env add ENGINE_API_KEY production --sensitive
vercel env add ENGINE_TUNNEL_BASIC_AUTH production --sensitive
vercel env add ENGINE_INTERNAL_URL production
```
…or add them on the env-vars page (link above). After any change, **redeploy** (env
vars bake in at build time).

Copy the engine key to clipboard without printing it:
```powershell
((Select-String -Path C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env -Pattern '^API_KEY=' | Select-Object -First 1).Line -split '=',2)[1].Trim() | Set-Clipboard
```
The basic-auth credential lives in the `traffic_policy` block of `ngrok.yml` read it
from there if you need to refresh `ENGINE_TUNNEL_BASIC_AUTH`.

> **If `ngrok.yml`'s basic-auth credential changes**, `ENGINE_TUNNEL_BASIC_AUTH` goes
> stale → the site 401s through the tunnel. Update the Vercel var to match and redeploy.
> (This is the multi-session footgun: only one session should own the ngrok cred.)

---

## One-time Vercel setup (already done, kept for reference)

1. From `dashboard/`: `vercel login`, then `vercel link` (project `jarvis-trader`).
2. Set the three env vars above (Production).
3. Settings → Build → **Root Directory = `dashboard`**.
4. Settings → **Deployment Protection → Vercel Authentication = On**.

---

## Deploying

From `dashboard/`:
```powershell
vercel --prod --archive=tgz
```

`--archive=tgz` is currently **required**: a plain `vercel --prod` tries to enumerate
node_modules (~43k files) and hits Vercel's 15000-file limit `.vercelignore` is not
being honored by the CLI from this layout, so the tarball path is the reliable one.
Build runs remotely (~1-3 min) and aliases to `jarvis-trader-plum.vercel.app`.

> **Known fragility:** because `.vercelignore` is ignored, the tarball is ~4.8GB and
> occasionally fails extraction (BUILD_ERROR, empty message) when a peer dev server is
> bloating `.next/cache` mid-tar. Retry usually clears it. **The real fix is to stop
> deploying from the CLI entirely** see "Preferred: Git auto-deploy" below.

The local prod dashboard on :3010 (pm2 `jarvis-dashboard`) is independent of Vercel
and unaffected by deploys.

### Preferred: Git auto-deploy (retires the CLI archive dance)
Connect the Vercel project to the GitHub repo and enable production deploys from the
default branch. Vercel then **builds from the repo, not a local archive** no upload,
no 15000-file limit, no 4.8GB tarball, no manual command. Push → deploy. Do this once
the dashboard commits land on the production branch; it makes everything above obsolete
except the env vars.

---

## Tunnel health monitor

`Jarvis-TunnelHealth` (Windows task, every 15 min) runs `~/scripts/check-tunnel-health.ps1`
through `notify-on-fail.ps1`. It hits the **public** ngrok `/health` with the skip-warning
+ basic-auth headers, and disambiguates tunnel-down vs engine-down (also checks local
`127.0.0.1:8010`). Alerts to Telegram on failure; never restarts anything. This catches a
dead tunnel that the local-only `Jarvis-EngineHealth-Hourly` watchdog can't see.

---

## Credential rotation

Rotate when: a credential leaks, on 90-day hygiene, or to re-sync after a peer session
changed the ngrok cred (which silently 401s the public site — see the footgun note above).
Generate new values locally; never echo existing ones. These steps are run by you,
not by an agent (credential-guard blocks `.env`/`ngrok.yml` writes).

### A. ngrok basic-auth credential (re-sync + clean ownership)

```powershell
# 1. Generate a new 32-char credential (printed once, for you to paste)
$newpass = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 32 | %{[char]$_})
"jarvis:$newpass"        # copy this whole string

# 2. Edit %LOCALAPPDATA%\ngrok\ngrok.yml -> replace the credentials line under
#    tunnels.jarvis-engine.traffic_policy ... basic-auth ... credentials:
#        - "jarvis:<newpass>"

# 3. Apply it
Restart-Service ngrok

# 4. Re-point Vercel + redeploy (from dashboard/)
vercel env rm  ENGINE_TUNNEL_BASIC_AUTH production
vercel env add ENGINE_TUNNEL_BASIC_AUTH production --sensitive   # paste jarvis:<newpass>
vercel --prod --archive=tgz
```

Brief 401 window between step 3 and the redeploy completing (~2-3 min). Expected.

### B. engine API key (X-API-Key)

More blast radius — **three** consumers must move together or one of them 401s:

```powershell
# 1. Generate a new 64-hex key
$newkey = -join (1..64 | %{ '{0:x}' -f (Get-Random -Max 16) })
$newkey | Set-Clipboard      # on clipboard, not echoed

# 2. Update all THREE consumers:
#    a) engine/.env            -> API_KEY=<newkey>
#    b) dashboard/.env.local   -> ENGINE_API_KEY=<newkey>   (local :3010 proxy)
#    c) Vercel (remote proxy):
vercel env rm  ENGINE_API_KEY production
vercel env add ENGINE_API_KEY production --sensitive          # paste <newkey>

# 3. Restart engine (~229s warm-up), then redeploy Vercel
.\restart_engine.ps1
vercel --prod --archive=tgz
```

`check-tunnel-health.ps1` keeps working throughout — it hits `/health` (auth-exempt).

### C. Ownership — stop the rotation thrash

Only **one** session should own `ngrok.yml`. A peer rotating the basic-auth is what
desyncs Vercel. The `ngrok` resource is now wired into the Tier-2.5 shared-resource
guard, so a peer that tries to restart/reconfigure ngrok while you have it claimed gets
blocked. Claim it before editing the config:

```powershell
~/scripts/claude-resource-lock.ps1 -Claim ngrok -Reason "rotating basic-auth cred"
# ... edit ngrok.yml, Restart-Service ngrok ...
~/scripts/claude-resource-lock.ps1 -Release ngrok
```

### Optional
The ngrok account `authtoken` in `ngrok.yml` is local-only and hasn't leaked — rotate it
(via the ngrok dashboard) only if that file is ever exposed.

---

## Known limitation — WebSocket pages

Live-tick panels (`lib/engine-websocket-context.tsx`, `hooks/useWebSocket.ts`,
`lib/pipeline_ws.ts`) connect **directly** to the engine WS and can't traverse the Vercel
serverless proxy. They degrade gracefully (show "disconnected", retry quietly) and work
fully on the local :3010 dashboard. REST pages including Hidden Pivots (with the live
Price column) work fully on Vercel. Making live panels work remotely needs engine-side
short-lived WS token auth (deferred to avoid exposing the key in the browser).
