# Market data waterfall (audit reference)

**Code:** [engine/data/market_data.py](../../engine/data/market_data.py) — `MarketDataManager`.

## OHLCV bars (`get_bars`)

| Tier | Condition | Source |
|------|-----------|--------|
| 1 | `ibkr` exists and `ibkr.is_connected` | IBKR historical bars |
| 2 | `polygon` configured | Polygon aggs (micro symbols mapped via `POLYGON_FUTURES_MAP`) |
| 3 | CSV cache file present | `_load_csv_cache` — **rejected if last bar &gt; 2 days old** (staleness guard) |

## Current price (`get_current_price`)

| Tier | Condition | Notes |
|------|-----------|--------|
| **0** | **`tos_rtd` connected (thinkorswim desktop RTD)** | **`rtd_tos` — broker-direct push feed. See [below](#tier-0--thinkorswim-desktop-rtd-rtd_tos). Skipped entirely when TOS isn't running.** |
| 1 | IB connected | `get_snapshot_price` — if `last_price` truthy, return |
| 2 | Schwab connected | Real-time quote |
| 2.5 | TradingView feed available | Optional CDP bridge |
| 3 | Polygon | Mapped symbol for micros |
| 4 | CSV | Last daily close — **no 2-day staleness check** (unlike `get_bars`); treat as last-resort |

`get_tick_price` (position/portfolio reads) and `get_vix` carry the same Tier 0
TOS RTD check ahead of their other tiers.

## Tier 0 — thinkorswim desktop RTD (`rtd_tos`)

Adapter: [engine/data/tos_rtd_adapter.py](../../engine/data/tos_rtd_adapter.py)
(`TOSRTDConnector`). Wired from `engine/main.py`’s `lifespan` via
`MarketDataManager.inject_tos_rtd()`.

- **What it is.** thinkorswim.exe registers a COM RTD server (`Tos.RTD`,
  `{1B415BA9-E543-41BD-8EB1-CB12A5B7678F}`, `RTDService.dll`) that proxies to
  TOS’s own listener on `127.0.0.1:12001` — the same feed Excel’s
  `=RTD("TOS.RTD",,"LAST","SPY")` uses. While TOS is open this is the
  lowest-latency broker-direct source available, hence Tier 0.
- **Read-only.** Only RTD read calls (`ServerStart`/`ConnectData`/
  `RefreshData`/`Heartbeat`/`DisconnectData`/`ServerTerminate`). No order path,
  no account access, never consulted by risk / kill-switch / execution code.
- **Scope:** MES, ES, MNQ, NQ, SPY, QQQ, VIX. Symbol mapping lives in
  `TOS_RTD_SYMBOLS` — TOS needs `/MES:XCME` (bare `MES` returns `0.0`, `/MES`
  returns `N/A`) and `VIX` (not `$VIX.X`).
- **Failure is invisible by design.** TOS closed, pywin32 missing, COM fault,
  unknown symbol → the tier returns `None`/`[]` and the waterfall falls through
  to IBKR/Schwab/Polygon unchanged. No exception escapes the tier.
- **Freshness.** RTD pushes *changes only*, so a quiet symbol’s cached value is
  not proof of liveness. `is_connected` is driven by a live `Heartbeat`, and
  every quote carries `as_of` so `build_envelope()` can re-derive liveness.
  `rtd_tos` is registered in `LIVE_SOURCES`
  ([engine/data/provenance.py](../../engine/data/provenance.py)).

### Verify it’s working

```bash
cd engine
.venv/Scripts/python.exe scripts/tos_rtd_probe.py     # read-only diagnostic
```

The probe reports transport, dependency, session, per-symbol quotes and the
option chain. Expected when TOS is running: `[PASS]` on all steps with live
prices; `ticks priced: 4/4`. Exit 0 = healthy, 2 = TOS absent (tier inactive,
harmless), 1 = a real fault.

To confirm which tier served a price, check `source` in the returned dict — it
is `rtd_tos` when Tier 0 answered.

### Disable it

Set `enabled=False` on the connector, or simply don’t inject it: `inject_tos_rtd`
is opt-in and `MarketDataManager.tos_rtd` defaults to `None`, in which case the
tier does not exist and the waterfall behaves exactly as it did before.

### Two constraints worth knowing before changing anything here

1. **No COM worker thread — ever.** `RTDService.dll` registers no
   `ThreadingModel`, so COM treats it as `ThreadingModel=Apartment`: the object
   is always created inside the process’s *first* apartment, and calls from any
   other apartment are marshalled there. A non-pumping STA (an asyncio/uvicorn
   loop thread) never services those calls, so they hang. Measured: if anything
   touched COM first (`import win32com.client`, `CoInitialize()` on the main
   thread), a worker thread’s `ServerStart` blocked forever **with no
   exception**; with COM untouched it worked. The session is therefore created
   and used on the calling (event-loop) thread. Per-call cost is
   sub-millisecond; anything that must *wait* (first fill) is an
   `await asyncio.sleep` loop, never a blocking sleep. `connect()` must stay on
   the loop thread — it is scheduled with `asyncio.create_task` in `lifespan`,
   never `to_thread`.
2. **The 12001 TCP protocol is NOT documented, and its subscription framing is
   unknown.** Only the `HELLO 1.1` → `RTD SERVER` handshake is verified; that is
   what `probe_tcp_handshake` uses as a cheap pre-flight. Every newline-framed
   subscription line format tried after the banner was rejected (~95 formats).
   Do not "simplify" the adapter down to hand-rolled TCP — go through the COM
   server, which is the vendor’s supported path and is verified end-to-end.

Also: pywin32 is driven with explicit `InvokeTypes` dispid descriptors (no
`gencache`/makepy, no writes to `%TEMP%\gen_py`). The raw `IRtdServer` vtable
path works for every method *except* `ConnectData` (oVft 64), which faults inside
the DLL — do not convert it.

## Operations guidance

- For **paper validation** with fresh futures prices, prefer **IB Gateway on `IBKR_PORT` (4002 paper)** so Tier 1 succeeds; see [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md) and [IB_RECONNECT_AND_HEALTH.md](IB_RECONNECT_AND_HEALTH.md).
- **CSV** is appropriate for **offline backtest / fixture** work, not as a substitute for live IBKR+Polygon when validating intraday signals.

## Tests

- Regression: [engine/tests/test_market_data_waterfall.py](../../engine/tests/test_market_data_waterfall.py) — IBKR/Schwab/Polygon/CSV tiers and the Redis-fabric freshness gate.
- Tier 0 TOS RTD: [engine/tests/test_tos_rtd_adapter.py](../../engine/tests/test_tos_rtd_adapter.py) — offline (no TOS/COM/network). Covers symbol mapping, the never-emit-a-silent-zero coercion, disconnected/disabled behaviour, waterfall precedence and fall-through, provenance, and two COM-apartment regression guards.
- Live connectivity: [engine/scripts/tos_rtd_probe.py](../../engine/scripts/tos_rtd_probe.py) — requires TOS running.
