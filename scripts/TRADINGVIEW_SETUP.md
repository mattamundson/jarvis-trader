# TradingView Webhook Setup — JARVIS TRADER

## Overview
The STC strategy Pine Script sends webhook alerts to JARVIS TRADER
whenever a LONG, SHORT, or CLOSE signal fires on the configured
timeframe and symbol.

## Recommended Settings
- **Timeframe**: 1h (best backtest: PF 5.27, Sharpe 4.16)
- **Symbols**: MES1! (primary), MNQ1!, MCL1!

## Step 1: Expose the engine (local dev)
```bash
ngrok http 8010
# Note the URL: https://abc123.ngrok.io
```

## Step 2: Add Pine Script to TradingView
1. Open TradingView → Pine Editor (bottom toolbar)
2. Paste the contents of `jarvis_trader_strategy.pine`
3. Click **Add to chart**

## Step 3: Create Alerts (one per signal type)
For LONG, SHORT, and CLOSE signals:
1. Right-click chart → **Add Alert...**
2. **Condition**: JARVIS TRADER — STC + ATR Strategy → [signal name]
3. **Notifications** tab → enable **Webhook URL**
4. **URL**: `https://YOUR_NGROK_URL/webhook/tradingview`
5. **Message**: leave as-is (Pine Script generates the JSON payload)
6. Set **Expiration** to no expiration
7. Click **Create**

## Step 4: Verify
```bash
# Check recent webhooks received
curl http://localhost:8010/signals/recent

# Or manually send a test signal
python scripts/test_signal.py MES LONG 5000
```

## Webhook Secret (optional, recommended)
Set `TRADINGVIEW_WEBHOOK_SECRET=your_secret` in `engine/.env`.
Then add `X-Webhook-Secret: your_secret` as a custom header in the
TradingView alert settings.

## Supported Symbols
| TradingView | JARVIS |
|-------------|--------|
| MES1!       | MES    |
| MNQ1!       | MNQ    |
| MCL1!       | MCL    |
| SPY         | SPY    |
| QQQ         | QQQ    |
