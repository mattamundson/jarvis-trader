# JARVIS Trader Dashboard — Remote Access (US-008)

Verified 2026-06-12.

## Already works now (no setup)

- **Tailscale is up** on this machine: node `amoszn` = **`100.68.247.106`** (online).
- The dashboard binds **`0.0.0.0:3010`** (verified via `netstat` — listening on all interfaces, not just localhost).

➡️ **From Amo's phone on the tailnet, the live dashboard is reachable right now at:**

```
http://100.68.247.106:3010
```

(Phone must have Tailscale installed and logged into the same tailnet.)

## Optional upgrade — HTTPS + clean hostname (AMO-GATED)

`tailscale serve` puts the dashboard behind the tailnet's HTTPS cert with the machine's MagicDNS name (`amoszn.<tailnet>.ts.net`) instead of a raw IP:port. Amo runs:

```powershell
# prereq: tailscale up (already satisfied)
tailscale serve --bg 3010
# then from the phone: https://amoszn.<tailnet>.ts.net
tailscale serve status   # confirm the mapping
```

To stop sharing: `tailscale serve --https=443 off`.

> Note: `tailscale serve` was previously blocked when the daemon wedged into `NoState` (2026-06-11). It is healthy now. If it wedges again: `tailscale up --force-reauth` (see session_coordination Tier-2.5 — claim the `tailscale` resource lock first if peers are live).

## Fallback — Cloudflare Tunnel (if tailnet unavailable)

For public access without the tailnet (e.g. sharing with someone not on Tailscale):

```powershell
# one-time: winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:3010
```

Prints a temporary `https://<random>.trycloudflare.com` URL proxying to the local dashboard. For a stable named tunnel, set up a Cloudflare account + `cloudflared tunnel create`. Use sparingly — this exposes the dashboard publicly (no auth in front of it).

## Binding confirmation

`pm2 describe jarvis-dashboard` → `next start --port 3010`, listening `0.0.0.0:3010` + `[::]:3010`. No bind change needed for either tailnet direct-IP access or `tailscale serve` proxying.
