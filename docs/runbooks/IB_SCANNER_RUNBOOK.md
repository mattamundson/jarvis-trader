# IB Market Scanner — Runbook

**Status:** Default OFF (`ENABLE_IB_SCANNER=0`). Read-only. No order paths.

---

## What It Does

The IB market scanner queries Interactive Brokers Gateway for ranked opportunity lists
beyond the engine's current MCL/MNQ watchlist. Use it to discover:

- **Breakout candidates** — stocks with the largest percent gain or gap-up at open
- **Intraday volume spikes** — securities trading far above average volume
- **Futures movers** — most active futures contracts for cross-instrument context

Results are **ranked snapshots**, not live tick streams. The scanner opens a
separate read-only connection to IB Gateway (client ID 10), runs one or more
`reqScannerData` requests, and disconnects. No positions, orders, or subscriptions
are created.

---

## How to Enable

1. Set the flag in `engine/.env`:
   ```
   ENABLE_IB_SCANNER=1
   ```
2. Confirm IB Gateway is running on paper port 4002.
3. Restart the engine:
   ```powershell
   .\restart_engine.ps1
   ```
4. Verify the routes respond:
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8010/ib-scanner/top-movers -H "X-API-Key: <key>"
   ```

When the flag is `0` (or absent), all `/ib-scanner/*` routes return HTTP 501
with instructions to enable. No IB connection is attempted.

---

## Available Routes

| Route | Scan codes | Use case |
|---|---|---|
| `GET /ib-scanner/top-movers` | TOP_PERC_GAIN + TOP_PERC_LOSE + HOT_BY_VOLUME (parallel) | Morning overview of broad market leaders |
| `GET /ib-scanner/futures-movers` | FUT_HOT_BY_VOLUME on FUT.GLOBEX | Futures volume context, cross-instrument awareness |
| `GET /ib-scanner/raw?scan_code=X&instrument=Y&n=50` | Any supported code | Advanced one-off queries |

All routes require the `X-API-Key` header (same key as all other engine routes).

---

## Available Scan Codes

### Equity scans (instrument=STK, location=STK.US.MAJOR)

| Code | What it finds |
|---|---|
| `TOP_PERC_GAIN` | Largest percent gainers today |
| `TOP_PERC_LOSE` | Largest percent losers today |
| `HOT_BY_VOLUME` | Highest volume-to-average ratio |
| `TOP_OPEN_PERC_GAIN` | Largest percent gain from yesterday's close to today's open |
| `HIGH_OPEN_GAP` | Stocks that gapped up at open |
| `LOW_OPEN_GAP` | Stocks that gapped down at open |
| `MOST_ACTIVE` | Highest raw volume |
| `TOP_TRADE_RATE` | Highest trades-per-minute rate |

### Futures scans (instrument=FUT, location=FUT.GLOBEX)

| Code | What it finds |
|---|---|
| `FUT_HOT_BY_VOLUME` | Most active futures contracts by volume |
| `FUT_TOP_PERC_GAIN` | Largest percent-gaining futures contracts |
| `FUT_TOP_PERC_LOSE` | Largest percent-losing futures contracts |

Futures scan codes require the paper account to have futures market data subscriptions.
If the account is not subscribed, results return empty — no error is thrown.

---

## IB Scanner Limitations

1. **Snapshots, not streams.** Results are a ranked list at the moment of the query.
   IB caches scanner results server-side for **up to 30 seconds**. Calling the same
   endpoint more frequently returns the same cached snapshot. Re-call every 60 seconds
   or more for fresh data.

2. **~50 results per query.** IB's API caps `numberOfRows` at approximately 50.
   The `n` query parameter on `/raw` is bounded to 50 max.

3. **Account permissions.** Some scan codes require specific market data subscriptions
   (e.g., Level 2, futures data). If the paper account lacks a subscription, IB
   returns an empty result set rather than an error.

4. **Client ID 10.** The scanner uses a dedicated read-only client ID (10) to avoid
   conflicting with the engine's trading connections (IDs 1-3). If another process
   uses client ID 10 on the same Gateway, the scanner connection will fail gracefully
   and return empty results.

5. **Not for order discovery.** Scanner results identify candidates; they do not
   feed into the trading pipeline, approval queue, or any order-routing path.
   The scanner module has no import path to `execution/` or `risk/`.

---

## Use Cases

### Morning pre-market setup (manual)

```powershell
$key = (Get-Content engine\.env | Select-String "^API_KEY=").ToString().Split("=")[1].Trim()
Invoke-RestMethod http://127.0.0.1:8010/ib-scanner/top-movers `
    -Headers @{"X-API-Key" = $key} | ConvertTo-Json -Depth 4
```

Surfaces the day's early leaders before the first pipeline scan at 09:31 ET.

### Intraday volume spike check

```powershell
Invoke-RestMethod "http://127.0.0.1:8010/ib-scanner/raw?scan_code=HOT_BY_VOLUME&n=10" `
    -Headers @{"X-API-Key" = $key}
```

### Hermes / Telegram — "what's moving"

The `jarvis-scanner` Hermes skill calls `/ib-scanner/top-movers` and formats the
top 5 gainers, losers, and unusual-volume entries as a Telegram-friendly summary.
Skill path: `/home/mattm/.hermes/skills/jarvis-scanner/`

Trigger phrases: "what's moving", "top movers", "show gainers", "unusual volume"

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| All routes return HTTP 501 | `ENABLE_IB_SCANNER=0` | Set `=1` and restart engine |
| Empty lists returned | IB Gateway not running on 4002 | Start IB Gateway; verify port 4002 is listening |
| Empty futures results | Account lacks futures data subscription | Subscribe to CME/GLOBEX data in IB account settings |
| Connection timeout in logs | Gateway is running but busy | Retry; Gateway may be processing other requests |
| Client ID 10 already in use | Another process grabbed client 10 | Kill the other process or change `_SCANNER_CLIENT_ID` in `brokers/ib_scanner.py` |

---

## Cross-References

- Engine safety rules: `engine/CLAUDE.md` — scanner never touches order routing
- IB Gateway connection model: `engine/execution/ib_gateway.py` — established patterns
- Scanner module: `engine/brokers/ib_scanner.py`
- HTTP routes: `engine/routers/ib_scanner_router.py`
- Hermes skill: `/home/mattm/.hermes/skills/jarvis-scanner/`
- Philosophy: [[STARK_MODE_OPERATING_PHILOSOPHY]] — use scanner for opportunity awareness,
  not as a signal source; pipeline gate v2 remains the sole trade-entry authority
