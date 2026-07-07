# Schwab API OAuth Setup Guide

## Prerequisites

- Active Charles Schwab / ThinkorSwim account (migrated TOS accounts work)
- JARVIS TRADER engine installed with Python venv at `engine/.venv/`
- `schwab-py` installed: `pip install schwab-py` (already in requirements.txt)

---

## Step 1: Register a Developer App

1. Go to https://developer.schwab.com
2. Log in with your Schwab credentials
3. Click **Apps** → **Create App**
4. Fill in:
   - **App Name**: JARVIS TRADER (or any name you choose)
   - **Callback URL**: `https://127.0.0.1`
   - **Description**: Personal trading assistant
5. Submit and wait for approval (usually instant for paper trading access)
6. Copy your **App Key** (client ID) and **App Secret** (client secret) from the app detail page

---

## Step 2: Configure engine/.env

Add or update these lines in your `engine/.env` file:

```
SCHWAB_APP_KEY=your_app_key_here
SCHWAB_APP_SECRET=your_app_secret_here
SCHWAB_CALLBACK_URL=https://127.0.0.1
SCHWAB_READY=true
```

Do NOT set `SCHWAB_READY=true` until you have real credentials — the engine will attempt to initialize the client on startup.

---

## Step 3: Generate OAuth Token (One-Time Browser Flow)

The first time you connect, `schwab-py` requires a browser OAuth flow to obtain an access token.

```bash
cd engine
.venv/Scripts/python -c "
import schwab
import config

settings = config.get_settings()
client = schwab.auth.client_from_login_flow(
    api_key=settings.SCHWAB_APP_KEY,
    app_secret=settings.SCHWAB_APP_SECRET,
    callback_url=settings.SCHWAB_CALLBACK_URL,
    token_path='.schwab_token.json'
)
print('Token saved to .schwab_token.json')
"
```

A browser window will open. Log in with your Schwab credentials and approve access. The token is saved to `engine/.schwab_token.json`.

**Important**: `.schwab_token.json` is in `.gitignore` — never commit it.

---

## Step 4: Verify Connection

1. Start the engine:
   ```bash
   cd engine
   .venv/Scripts/python -m uvicorn main:app --port 8010
   ```

2. Check Schwab status endpoint:
   ```bash
   curl http://localhost:8010/schwab/status
   ```

3. Expected response:
   ```json
   {"connected": true, "state": "CONNECTED"}
   ```

---

## Token Management

| Event | Action |
|-------|--------|
| Normal operation | Auto-refresh every 30 minutes (heartbeat loop) |
| Token expired (7 days inactivity) | Delete `.schwab_token.json`, repeat Step 3 |
| 401 Unauthorized errors | Token likely expired — re-run Step 3 |
| App key changed | Update `.env`, delete token file, repeat Step 3 |

The engine's heartbeat loop in `routers/schwab.py` handles token refresh automatically during active sessions.

---

## Asset Coverage

| Asset Type | Via Schwab | Notes |
|-----------|-----------|-------|
| Equities (SPY, QQQ, AAPL) | YES | Full buy/sell/quote |
| Options | YES | Full chain, Greeks, order routing |
| Futures (MES, MNQ, MCL) | NO | Route via IBKR (port 4002) |
| Crypto | NO | Not supported by Schwab API |

---

## Order Routing in JARVIS

The JARVIS order router dispatches automatically based on instrument type:

- **Futures** (MES, MNQ, MCL) → IBKR (`ib_gateway_connector`)
- **Equities + Options** (SPY, QQQ) → Schwab (`schwab_connector`)

You do not specify the broker per trade — the orchestrator handles routing.

---

## Troubleshooting

**"Schwab not ready" on startup**
Check `SCHWAB_READY=true` in `engine/.env` and restart engine.

**"Token not found" or FileNotFoundError**
`.schwab_token.json` does not exist. Run the OAuth flow in Step 3.

**"401 Unauthorized"**
Token has expired (7-day inactivity limit). Delete `engine/.schwab_token.json` and repeat Step 3.

**"App not approved" on developer portal**
Schwab approval is usually instant. If it takes longer, check the developer portal email for a confirmation step.

**Browser opens but redirect fails**
Ensure your app's callback URL in the developer portal exactly matches `https://127.0.0.1` (no trailing slash, no port).

**`SCHWAB_READY=False` is the system default**
This is intentional — the engine stays in IBKR paper mode until Schwab is explicitly configured. Never flip to `true` without valid credentials.

---

## Security Notes

- `engine/.schwab_token.json` is listed in `.gitignore` at the project root — verify with `git check-ignore -v engine/.schwab_token.json`
- The token grants full account access — treat it like a password
- The `SCHWAB_APP_SECRET` in `.env` is also sensitive — never commit `.env`
- Rotate your App Secret on the developer portal if you suspect compromise
