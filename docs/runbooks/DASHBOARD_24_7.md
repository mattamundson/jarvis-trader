# Dashboard 24/7 + "Is it actually live?" Runbook

Answers three questions honestly: **is the dashboard up 24/7, is it showing live data, and how do I make it so.**

## What is already done vs. what actually gates 24/7

- **PM2 config exists.** `engine/ecosystem.config.js` already has a `jarvis-dashboard` app
  (`pnpm run start`, `autorestart: true`, port 3010). So the dashboard *can* be process-managed
  24/7 exactly like the engine — this is **not** a code gap.
- **The real gaps are operational**, and any one of them makes the dashboard "not live":

| Requirement | Why | How |
|---|---|---|
| PM2 actually running the app | If you start it by hand (`pnpm dev`) it dies on terminal close | `cd engine && pm2 start ecosystem.config.js` (starts engine + dashboard + crons) |
| PM2 survives reboot | Otherwise a restart = everything down | `pm2 save` then `pm2 startup` (follow the printed command) |
| The machine never sleeps | A laptop that sleeps is a dashboard that's down | Windows: power plan → sleep = *Never*; keep it plugged in / a dedicated box or VPS |
| **IB Gateway logged in** | IBKR logs the Gateway out **daily** → `data_connected: false` → prices/positions go blank even with the engine up | Auto-relogin with **IBC/IBController**, or a daily manual re-auth. This is the #1 cause of "the dashboard went dark." |
| Engine up on :8010 | The dashboard proxy targets `ENGINE_INTERNAL_URL` (default `http://localhost:8010`) | `pm2 status` → `jarvis-engine` = `online` |
| `master-api` up on :8030 | The "honest trade record" widgets (`/stats`, `/journal`, `/performance`) call a **separate service not in this repo** | Start that service; if it's down those widgets show "unavailable" (expected, not an engine bug) |

**Bottom line:** "24/7 live" is a state that the machine + PM2 + engine + IB Gateway + master-api must
*all* hold simultaneously. The dashboard rendering is now crash-proof (#207), but it can only be as
live as the feed behind it.

## Bring the whole stack up (once)

```bash
cd dashboard && pnpm install && pnpm run build   # dashboard needs a production build for `pnpm start`
cd ../engine  && pm2 start ecosystem.config.js    # engine + dashboard + scheduled jobs
pm2 save                                          # remember this process list
pm2 startup                                       # print the boot auto-start command; run it
pm2 status                                        # jarvis-engine + jarvis-dashboard should be "online"
```

Then disable machine sleep and make sure IB Gateway is logged in (paper, port 4002).

## Is it *actually* live right now? — one command

```bash
cd dashboard && pnpm run check:live
# or: node scripts/check-live-data.mjs
# env: ENGINE_URL (default http://localhost:8010), ENGINE_API_KEY, MASTER_API_URL
```

It hits every core data source the overview depends on and prints a per-feature verdict:

- 🟢 **LIVE** — real data flowing
- 🟡 **EMPTY** — 200 but empty/all-null (feed degraded: market closed, IB Gateway down, no data)
- 🟠 **AUTH/HTTP** — 4xx (bad/missing `ENGINE_API_KEY`, wrong path)
- 🔴 **UNREACHABLE** — service down (start the engine / master-api)

Exit code is non-zero only if the **engine itself** is unreachable. Run it during market hours with
IB Gateway logged in to confirm true live data; a wall of 🟡 off-hours is expected.

## What this does NOT claim

This makes the dashboard *stay up* and lets you *see* what's live. It does **not** assert every
widget's numbers are correct — for that, spot-check specific widgets against the engine API. And it
cannot make a laptop that sleeps, or an IB Gateway that logged itself out, stay online — those are
physical/operational, not code.
