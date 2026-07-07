# Runbook — /regime Dashboard Manual Test (live engine)

Purpose: verify the Intraday Regime page (`/regime`) end-to-end against a
**running engine**. The headless QA in the sandbox can only exercise the
sample-data fallback (engine is offline there), so the live path below must be
confirmed locally before trusting real `/regime/intraday` values.

Page: `dashboard/app/regime/page.tsx`
Data layer: `dashboard/lib/regime.ts` (`fetchIntradayRegime` → GET `/regime/intraday`)
Chart: `dashboard/components/regime/RegimeScoreHistoryChart.tsx`

## 0. Start both services

```bash
# Engine (http://localhost:8010)
cd engine && .venv/Scripts/activate && python main.py

# Dashboard (http://localhost:3010)
cd dashboard && pnpm install && pnpm dev
```

Open http://localhost:3010/regime.

## 1. Live vs sample provenance (the key gap)

- [ ] Top-right badge reads **"Live Engine Data"** with a green pulsing dot
      (not "Sample Data"). This is the whole point of the live test — if it
      still says "Sample Data", the engine call failed; check the next item.
- [ ] DevTools → Network: `GET /regime/intraday?symbol=SPY&futures=false`
      returns **200** (proxied through the dashboard, not a 502).
- [ ] No console errors. (With the engine down you get `502` on `/api/engine`
      and a `ws://.../ws/events` handshake failure — both are expected ONLY in
      the offline/fallback case and must be absent when the engine is up.)

## 2. Real values render (not the hardcoded sample)

The sample fallback always shows SPY @ `$750.75`, score `-54.30`, BEARISH.
Live data should differ from those exact constants.

- [ ] Symbol header, price, and the big score number reflect real engine output
      (price ≠ `$750.75` unless SPY genuinely sits there).
- [ ] Verdict card direction (BULLISH / BEARISH / NEUTRAL) matches the score
      sign and the `directionPct`.
- [ ] Timeframe Scores (5-MIN / 15-MIN / 1-HOUR) show live numbers + bias.
- [ ] Indicator Breakdown cards (VWAP, DONCHIAN, EMA STACK, etc.) populate with
      live values and the thin tone bars fill proportionally.

## 3. Symbol selector

- [ ] Change the dropdown SPY → NVDA → QQQ. Each change re-fetches
      `/regime/intraday?symbol=...` and the header symbol + all numbers update.
- [ ] Rapid switching does not leave a stale symbol's data on screen.

## 4. Score history chart + EMA toggle (regression-checked 2026-06-18)

- [ ] Chart renders the white score line with the bullish/bearish gradient fill.
- [ ] **EMA: ON** draws three overlaid lines — teal (short), blue (long),
      purple (extra). This regressed once: the lines were dropped by recharts
      when wrapped in a Fragment (fixed in `RegimeScoreHistoryChart.tsx`). If
      only the white line shows while the label says ON, the regression is back.
- [ ] Toggling **EMA: OFF** removes the three EMA lines; **ON** restores them.
- [ ] `{snapshotCount}` snapshots label matches the engine's history length.
- [ ] Hover shows the tooltip with the score at that timestamp.

## 5. Options Flow

- [ ] If the engine has a GEX/options source wired: Flow Signal, Net GEX
      (formatted `+$X.XM`), and GEX Flip Level (`$NNN`) render with correct
      tone colors.
- [ ] If not wired: the three cards show a dashed border and **"Not wired"**
      (null state) — this is correct, not a bug.

## 6. Refresh behavior

- [ ] Leave the page open ~30s (the `REFRESH_MS` SWR interval). Data re-polls
      without a full reload and without flashing the sample fallback.
- [ ] Kill the engine while the page is open → next poll should fall back to the
      sample snapshot and flip the badge to "Sample Data" (graceful, no crash).

## Notes

- The sandbox/headless path can only confirm: build, types, render, the
  snake→camel mapper by inspection, control interactivity, and the
  sample-fallback badge. Items in sections 1–2 and the live half of 5 require a
  real engine and can only be checked here.
