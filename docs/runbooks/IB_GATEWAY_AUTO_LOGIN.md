# IB Gateway auto-login (IBC) — surviving the nightly forced logout

**The #1 cause of "the dashboard went dark overnight."** IBKR logs the IB Gateway
**process** out every day (paper resets ~daily; live has a weekly hard restart). When
that happens the Gateway has *no session at all* — so the engine's own reconnect logic
(exponential backoff in [`ib_gateway_connector.py`](../../engine/execution/ib_gateway_connector.py),
documented in [IB_RECONNECT_AND_HEALTH.md](IB_RECONNECT_AND_HEALTH.md)) cannot help: there
is nothing on `:4002` to reconnect *to*. `data_connected` goes false, prices/positions go
blank, and every widget behind the feed degrades until a human re-types the password.

This runbook removes the human. It sets up **IBC (IB Controller)** to auto-launch the
Gateway, auto-enter credentials, and auto-dismiss the daily logout/restart dialogs — so the
paper stack survives unattended overnight.

> Scope: **paper only, port 4002, account DUP662235.** Port 4001 (live) is permanently
> blocked in code — do not point IBC at it. This is an operational/ops-config runbook; it
> touches **no** engine, risk, or safety code.

---

## Why engine-side reconnect is not enough

| Failure | Who fixes it | Covered by |
|---|---|---|
| Network blip; Gateway still logged in | Engine reconnect (backoff 2s/4s/8s) | [IB_RECONNECT_AND_HEALTH.md](IB_RECONNECT_AND_HEALTH.md) |
| Engine process died | PM2 `autorestart` | [DASHBOARD_24_7.md](DASHBOARD_24_7.md) |
| **Gateway logged itself out (daily)** | **IBC auto-login (this doc)** | — |
| Machine slept / rebooted | Power plan + `pm2 startup` | [DASHBOARD_24_7.md](DASHBOARD_24_7.md) |

All four must hold simultaneously for "24/7 live." IBC closes the third row — the one that
silently eats overnight paper runs and makes durability measurement (Task 4) impossible.

---

## Market-data caveat (read before blaming IBC)

Auto-login keeps the Gateway **session** alive. It does **not** grant market-data
**subscriptions**. If prices are still blank *after* login is confirmed, the cause is a
missing/limited IBKR market-data subscription or off-hours silence, not IBC. See the
delayed-data / freshness handling being tracked in **PR #194** and
[MARKET_DATA_WATERFALL.md](MARKET_DATA_WATERFALL.md) before concluding auto-login failed.
The live-data verdict tool (`pnpm check:live`, see [DASHBOARD_24_7.md](DASHBOARD_24_7.md))
distinguishes 🟡 EMPTY (session up, feed degraded) from 🔴 UNREACHABLE (session/Gateway down).

---

## Install (one time)

1. **Download IBC** — https://github.com/IbcAlpha/IBC/releases (the actively-maintained
   fork; the original `ib-controller` is abandoned). Match the archive to the OS.
   - Windows: `IBCWinx64-*.zip` → extract to `C:\IBC`.
2. **Confirm IB Gateway is installed** (not TWS) and note its version folder, e.g.
   `C:\Jts\ibgateway\<build>\`.
3. IBC ships templates: `config.ini` and a start script (`StartGateway.bat` on Windows,
   `gatewaystart.sh` on Linux/Mac). Copy them out of the install dir so upgrades don't clobber them.

---

## Configure `config.ini` (the only file that matters)

Set exactly these keys. **Credentials go in this file** — so it is a secret: it must be
gitignored and never committed (same rule as `engine/.env`).

```ini
# --- login ---
IbLoginId=<paper username>
IbPassword=<paper password>
TradingMode=paper

# --- headless, unattended survival ---
IbDir=C:\Jts
FIX=no
ExistingSessionDetectedAction=primary   ; reclaim the session on relaunch, don't bail
AcceptNonBrokerageAccountWarning=yes

# --- the daily logout dialogs (the whole point) ---
AutoRestartOption=RestartTodayAt          ; let Gateway self-restart on its schedule
ClosedownAt=                              ; leave blank — we do NOT want a daily shutdown
DismissPasswordExpiryWarning=yes
DismissNSEComplianceNotice=yes
ReloginAfterSecondFactorAuthenticationTimeout=yes
AcceptIncomingConnectionAction=accept

# --- API wiring: must match the engine (paper 4002) ---
OverrideTwsApiPort=4002
```

Key notes:
- **`ExistingSessionDetectedAction=primary`** — when IBKR's daily reset creates a phantom
  "existing session," IBC reclaims it instead of exiting. This is the single most important
  key for overnight survival.
- **Second-factor (IBKR Mobile) auth**: fully unattended login is only possible if the
  paper account has 2FA that does **not** require a live phone approval each time. Paper
  accounts typically allow this; if yours forces IBKR-Mobile approval, IBC will pause for it
  and true 24/7 is not achievable without disabling that on the paper login. `ReloginAfter…=yes`
  handles the *timeout* case gracefully.
- **Port must be 4002.** Never 4001 — the engine and safety layer treat 4001 as blocked.

---

## Start it under process management

Do **not** launch by double-clicking — a hand-started process dies with the terminal/RDP
session, which reintroduces the exact overnight-death problem. Run IBC under the same PM2
that already supervises the engine + dashboard ([`engine/ecosystem.config.js`](../../engine/ecosystem.config.js)).

Add an app to the PM2 ecosystem (paper only):

```js
// engine/ecosystem.config.js  — add alongside jarvis-engine / jarvis-dashboard
{
  name: "ib-gateway",
  script: "C:\\IBC\\StartGateway.bat",   // or gatewaystart.sh on Linux
  autorestart: true,
  // IBC restarts the Gateway in-place on the daily reset; PM2 is the outer
  // safety net if IBC itself ever exits.
}
```

Then, exactly as in [DASHBOARD_24_7.md](DASHBOARD_24_7.md):

```bash
cd engine && pm2 start ecosystem.config.js   # engine + dashboard + ib-gateway
pm2 save                                      # remember the process list
pm2 startup                                   # print boot auto-start cmd; run it
pm2 status                                    # ib-gateway should be "online"
```

---

## Verify it actually survives the night

1. **Immediately after start:** `curl -s localhost:8010/health` → `ibkr_connected: true`
   (or run `cd dashboard && pnpm run check:live` — expect 🟢 on the price sources during
   market hours).
2. **Across a daily reset:** leave it overnight. Next morning, without touching anything:
   - `pm2 status` → `ib-gateway` still `online`, low restart count.
   - `GET /health` → `ibkr_connected: true`.
   - `pnpm run check:live` → prices 🟢 (market hours) or 🟡 (off-hours), **not** 🔴.
3. **If it went 🔴 overnight:** open the IBC log (path printed by the start script) and grep
   for the dialog it got stuck on — usually a 2FA prompt or an unhandled notice. Add the
   corresponding `Dismiss…=yes` / action key to `config.ini` and repeat.

A clean pass here is the prerequisite for **Task 4** (uninterrupted paper-run durability):
you cannot measure "how many days straight the strategy runs as designed" until the Gateway
stops falling over every night.

---

## What this does NOT do

- It does **not** enable live trading, change any risk parameter, or touch `:4001`.
- It does **not** create market-data subscriptions (see the caveat above / PR #194).
- It does **not** keep a **sleeping laptop** awake — disable sleep separately
  ([DASHBOARD_24_7.md](DASHBOARD_24_7.md)). A dedicated always-on box or VPS is the real fix.

## Cross-references

- [DASHBOARD_24_7.md](DASHBOARD_24_7.md) — the full 24/7 stack (PM2, sleep, master-api).
- [IB_RECONNECT_AND_HEALTH.md](IB_RECONNECT_AND_HEALTH.md) — engine-side reconnect (the row
  above this one).
- [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md) — one-time paper connection proof.
- PR #194 — delayed-data / market-data freshness gate (the "prices still blank after login" case).
