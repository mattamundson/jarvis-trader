# FRED API Key Setup

## Why This Matters

`GET /macro/snapshot` requires a valid FRED API key. Without it, the endpoint returns HTTP 422 and VIX / macro data is unavailable. This affects:

- Command Center dashboard macro panel
- VIX regime classification (6-tier canonical)
- Pre-market macro brief
- WhatsApp alerts with macro context

**Current status:** `FRED_API_KEY` not configured — this is the [P1] priority item.

---

## Get Your Free Key (2 minutes)

1. Go to **https://fred.stlouisfed.org/docs/api/api_key.html**
2. Click **Request API Key**
3. Log in or create a free St. Louis Fed account
4. Fill in application name: `JARVIS TRADER` / use case: `personal trading research`
5. Key is emailed immediately (or shown on screen)

---

## Configure the Key

### In `.env` (development)

```bash
# In c:\Users\mattm\ThinkorSwim\jarvis-trader\.env
FRED_API_KEY=your_actual_key_here
```

### Verify it works

```bash
cd engine
.venv/Scripts/python -c "
import os; os.environ['FRED_API_KEY'] = 'your_key_here'
from data.fred_data import FredDataClient
client = FredDataClient()
vix = client.get_vix_history(days=5)
print('VIX data OK:', len(vix), 'rows')
"
```

### Test via the API

```bash
curl http://localhost:8010/macro/snapshot
# Should return: {"vix": <value>, "regime": "NORMAL", ...}
# Without key: {"detail": "FRED_API_KEY not configured"}
```

---

## Key FRED Series Used

| Series ID | Data | Used For |
|-----------|------|----------|
| `VIXCLS`  | CBOE VIX (daily close) | VIX regime classification |
| `DFF`     | Fed Funds Rate | Macro rate context |
| `T10Y2Y`  | 10Y-2Y yield spread | Yield curve signal |
| `UNRATE`  | Unemployment rate | Macro health |
| `CPIAUCSL`| CPI (monthly) | Inflation context |

---

## VIX 6-Tier Regime (what this unlocks)

| VIX Level | Regime | Position Sizing | Iron Condors |
|-----------|--------|-----------------|--------------|
| < 12      | VERY_LOW  | 1.5× normal  | Yes |
| 12–16     | LOW       | 1.25× normal | Yes |
| 16–20     | NORMAL    | 1.0× normal  | Yes |
| 20–25     | ELEVATED  | 0.75× normal | Yes (caution) |
| 25–30     | HIGH      | 0.50× normal | NO |
| > 30      | EXTREME   | HALT (kill switch auto-arms) | NO |

---

## Rate Limits

- **Free tier**: 120 requests/minute — more than sufficient
- **Caching**: `engine/data/fred_data.py` caches VIX for 1 hour to avoid hitting limits
- **No paid tier needed** for JARVIS Trader's current use case

---

## Without FRED (Fallback Mode)

The engine gracefully falls back to **VIX from price** (using the `^VIX` ticker via yfinance) when FRED is unavailable. This provides approximately the same data but with a slight delay. Set this in `.env`:

```bash
FRED_API_KEY=
VIX_FALLBACK_SOURCE=yfinance
```

The command center dashboard will show `[FALLBACK]` badge next to the VIX display.

---

*Reference: `engine/data/fred_data.py` · JARVIS_TRADER_MASTER.md §1.14*
