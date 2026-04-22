#!/usr/bin/env python3
"""
JARVIS TRADER — TradingView Pine Script Alert Generator

Generates Pine Script v5 code for the STC + ATR strategy.
The generated script sends webhook alerts to the JARVIS TRADER engine.

Usage:
    python scripts/pine_script_generator.py
    python scripts/pine_script_generator.py --webhook-url https://abc.ngrok.io/webhook/tradingview
    python scripts/pine_script_generator.py --output my_strategy.pine
    python scripts/pine_script_generator.py --instructions
"""
import argparse
from pathlib import Path

DEFAULT_PARAMS = {
    "stc_length": 10,
    "stc_fast": 23,
    "stc_slow": 50,
    "stc_os": 15,
    "stc_ob": 83,
    "atr_length": 14,
    "atr_stop_mult": 0.70,
    "atr_t1_mult": 1.50,
    "ema_fast": 9,
    "ema_slow": 21,
    "regime_ema": 200,
}

PINE_SCRIPT = '''//@version=5
strategy(
    title="JARVIS TRADER — STC + ATR Strategy",
    overlay=true,
    pyramiding=0,
    default_qty_type=strategy.fixed,
    default_qty_value=1,
    initial_capital=10000,
    commission_type=strategy.commission.cash_per_order,
    commission_value=0.85
)

// ── Inputs ──────────────────────────────────────────────────
i_stc_length   = input.int({stc_length},   "STC Length",        minval=1)
i_stc_fast     = input.int({stc_fast},     "STC Fast MA",       minval=1)
i_stc_slow     = input.int({stc_slow},     "STC Slow MA",       minval=1)
i_stc_os       = input.float({stc_os},     "STC Oversold",      step=1.0)
i_stc_ob       = input.float({stc_ob},     "STC Overbought",    step=1.0)
i_atr_len      = input.int({atr_length},   "ATR Length",        minval=1)
i_atr_stop     = input.float({atr_stop_mult}, "ATR Stop Mult",  step=0.05)
i_atr_t1       = input.float({atr_t1_mult},  "ATR Target Mult", step=0.05)
i_regime_ema   = input.int({regime_ema},   "Regime EMA",        minval=1)
i_use_regime   = input.bool(true,          "Use Regime Filter")

// ── STC Calculation ─────────────────────────────────────────
f_stc(src, length, fast, slow) =>
    ema1  = ta.ema(src, fast)
    ema2  = ta.ema(src, slow)
    macd  = ema1 - ema2
    st1   = ta.stoch(macd, macd, macd, length)
    d1    = ta.ema(st1, 3)
    st2   = ta.stoch(d1, d1, d1, length)
    ta.ema(st2, 3)

stc     = f_stc(close, i_stc_length, i_stc_fast, i_stc_slow)
atr     = ta.atr(i_atr_len)
ema200  = ta.ema(close, i_regime_ema)

bull_regime = not i_use_regime or close > ema200
bear_regime = not i_use_regime or close < ema200

// ── Signals ──────────────────────────────────────────────────
long_sig   = ta.crossover(stc, i_stc_os)  and bull_regime
short_sig  = ta.crossunder(stc, i_stc_ob) and bear_regime
close_long = ta.crossunder(stc, i_stc_ob) and strategy.position_size > 0
close_sht  = ta.crossover(stc, i_stc_os)  and strategy.position_size < 0

if long_sig
    strategy.entry("Long", strategy.long)
if short_sig
    strategy.entry("Short", strategy.short)
if close_long or close_sht
    strategy.close_all()

// ── Webhook Alert Payloads ───────────────────────────────────
long_msg  = '{{"symbol":"' + syminfo.ticker + '","action":"LONG","price":' + str.tostring(close, "#.##") + ',"stc":' + str.tostring(stc, "#.##") + ',"source":"tradingview"}}'
short_msg = '{{"symbol":"' + syminfo.ticker + '","action":"SHORT","price":' + str.tostring(close, "#.##") + ',"stc":' + str.tostring(stc, "#.##") + ',"source":"tradingview"}}'
close_msg = '{{"symbol":"' + syminfo.ticker + '","action":"CLOSE","price":' + str.tostring(close, "#.##") + ',"source":"tradingview"}}'

alertcondition(long_sig,            title="LONG Signal",  message=long_msg)
alertcondition(short_sig,           title="SHORT Signal", message=short_msg)
alertcondition(close_long or close_sht, title="CLOSE Signal", message=close_msg)

// ── Visuals ──────────────────────────────────────────────────
plotshape(long_sig,  location=location.belowbar, color=color.green, style=shape.triangleup,   size=size.small)
plotshape(short_sig, location=location.abovebar, color=color.red,   style=shape.triangledown, size=size.small)
plot(stc, "STC", color=color.new(color.blue, 0), linewidth=2, display=display.pane)
hline(i_stc_os, "Oversold",  color=color.new(color.green, 40), linestyle=hline.style_dashed)
hline(i_stc_ob, "Overbought",color=color.new(color.red,   40), linestyle=hline.style_dashed)
hline(50,        "Midline",  color=color.new(color.gray,  60), linestyle=hline.style_dotted)
bgcolor(long_sig  ? color.new(color.green, 92) : na)
bgcolor(short_sig ? color.new(color.red,   92) : na)
'''

SETUP_GUIDE = """# TradingView Webhook Setup — JARVIS TRADER

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
"""


def generate(webhook_url: str = "https://YOUR_NGROK_URL/webhook/tradingview",
             output: str | None = None) -> str:
    params = {**DEFAULT_PARAMS, "webhook_url": webhook_url}
    script = PINE_SCRIPT.format(**params)
    if output:
        Path(output).write_text(script, encoding="utf-8")
        print(f"Saved: {output}")
    return script


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webhook-url", default="https://YOUR_NGROK_URL/webhook/tradingview")
    ap.add_argument("--output", help="Write .pine file here (default: stdout)")
    ap.add_argument("--instructions", action="store_true", help="Print setup guide")
    args = ap.parse_args()

    if args.instructions:
        print(SETUP_GUIDE)
        return

    script = generate(args.webhook_url, args.output)
    if not args.output:
        print(script)


if __name__ == "__main__":
    main()
