# Corey Initial Balance (IB) v1 — ThinkScript Study

**File**: `thinkorswim-scripts/AA_CoreyIBv1STUDY.ts`  
**Author**: Corey Surles (@coreysurles)  
**JARVIS Layer**: Layer 2 (Structure) + Layer 4 (Entry Trigger)  
**Status**: Ported (Phase 2, commit pending) — `engine/backtest/ib_signals.py::compute_initial_balance`  
**Panel**: Upper (main price chart)

## Purpose

Identifies the Initial Balance (IB) range during the first 60 minutes of RTH (Regular Trading Hours) and projects that range as a structural framework for the trading day. IB breakouts above/below define bias, volatility regimes, and entry opportunities.

**Core concept**: The first 60 minutes of trading set the day's tone. Price action relative to IB High/Low predicts intraday momentum.

## JARVIS Mapping

**Signals generated**:
- `ib_high` — Initial Balance high (RTH first 60 min)
- `ib_low` — Initial Balance low (RTH first 60 min)
- `above_ib_high` — Close broke above IB High (Layer 4 entry trigger)
- `below_ib_low` — Close broke below IB Low (Layer 4 entry trigger)

**Layer 4 integration**: `layer4_entry()` in `engine/backtest/signals.py:529-534` fires `ENTRY_NOW` **unconditionally** when IB High breakout (`above_ib_high=True` AND `prev_above_ib_high=False` transition in BULL bias). This is the **highest-confidence entry signal in JARVIS** — no additional filters. MES backtest shows this signal is currently over-optimized and unprofitable; porting to live code is Phase 2 priority.

**Extension levels** (Layer 2 confluence):
- 25%, 50%, 75% quadrants within IB range
- 50%, 100%, 3x extensions above/below IB High/Low
- Confluence with other Layer 2 levels (VAH/VAL, Hidden Pivots)

## TOS Inputs

| Input | Default | Range | Purpose |
|-------|---------|-------|---------|
| `OpenRangeMinutes` | 60 | 15–120 min | Minutes after market open to capture IB |
| `MarketOpenTime` | 0930 | 0900–1000 | RTH start time (CT) |
| `showArrows` | yes | bool | Show/hide IB breakout arrows |
| `ShowQuads` | yes | bool | Show/hide 25/50/75% quadrant lines |
| `ShowExtensions` | yes | bool | Show/hide +50%, +100%, +3x extension lines |
| `ShowCloudsIB` | yes | bool | Colored clouds for IB price regions |
| `ShowCloudExt` | yes | bool | Colored clouds for extension levels |
| `ShowLabels` | yes | bool | IB High/Low labels on chart |
| `showTodayOnly` | no | bool | Hide IB from prior days |
| `useEMACross` | yes | bool | Overlay EMA 8/13 cross (momentum filter) |
| `ema1_len` | 8 | 1–50 | Fast EMA length |
| `ema2_len` | 13 | 1–50 | Slow EMA length |

## Visual Elements

**IB High (red, 3-pt weight)**: Horizontal line at the highest price during first 60 min RTH. Extends to next day open.

**IB Low (green, 1-pt weight)**: Horizontal line at the lowest price during first 60 min RTH. Extends to next day open.

**Quadrant lines (white dashes)**: Divide IB range into 4 equal zones. Help identify pullback targets and breakout magnitudes.

**Extensions (white dashes)**:
- Up 50%: IB High + 0.5 × (IB High − IB Low)
- Up 100%: IB High + 1.0 × (IB High − IB Low) [= 2x IB High − IB Low]
- Up 3x: IB High + 3.0 × (IB High − IB Low)
- Down 50%, 100%, 3x: Symmetric below IB Low

**Colored clouds**:
- Lower half IB (IB Low → 25%): Red/green gradient (seller/buyer region)
- Upper half IB (75% → IB High): Green/red gradient (buyer/seller region)
- Extensions: Magenta (approaching target), pink (target reached)

**EMA 8/13 overlay**: Momentum filter; golden cross = bullish, death cross = bearish.

## Install (TOS Steps)

1. Open ThinkOrSwim → Charts → Highest timeframe where you trade (e.g., 1-min or 5-min)
2. Right-click → Edit Studies
3. Create new custom study → paste code from `AA_CoreyIBv1STUDY.ts`
4. Name: `AA_CoreyIBv1STUDY`
5. Input defaults: Use table above; keep `OpenRangeMinutes=60`, `MarketOpenTime=0930` for US futures
6. Aggregation: Set to 1-min (script captures IB during first 60 bars)
7. **Critical**: Must be applied to **daily chart or intraday (1/5/15-min)** — not 1-hour. IB is calculated within that aggregation's first 60 minutes
8. Add to chart; toggle clouds/extensions/labels as preferred

## Alerts

| Signal | Condition | Action | Trade Impact |
|--------|-----------|--------|--------------|
| **IB High Breakout** | Close > IB High AND prior close ≤ IB High | Buy alert | `above_ib_high=true` → Layer 4 ENTRY_NOW (bulls only) |
| **IB Low Breakdown** | Close < IB Low AND prior close ≥ IB Low | Sell alert | `below_ib_low=true` → Layer 4 ENTRY_NOW (bears only) |
| **IB Squeeze** | (IB High − IB Low) < 10% daily range | Volatility compression | Expect breakout within +/−3x extension |
| **Extension Target** | Price touches 100% or 3x extension | Momentum extreme | Pullback likely; Layer 2 confluence check recommended |
| **EMA Cross** | EMA 8 crosses above/below EMA 13 | Momentum shift | Reinforces breakout bias; use with IB level |

**Recommended alert settings**:
- `showArrows=yes` — TOS native arrow when `above_ib_high` or `below_ib_low`
- Label shows live IB High, IB Low, extensions (updates at bar close)

## Known Limits / Gotchas

1. **Multi-day IB ranges on single chart**: If `showTodayOnly=no`, all historical IB lines appear. Cluttered visually; use `showTodayOnly=yes` to isolate current session only.

2. **Aggregation sensitivity**: Script calculates IB within first 60 bars of the chart aggregation. On a 5-min chart, IB = first 300 minutes; on 1-min, IB = first 60 minutes. Always use intraday aggregation (1/5/15-min for scalps, daily for swing). Never apply to weekly/monthly.

3. **Post-IB period**: After first 60 minutes, IB High/Low freeze and extend to next day open. Extensions continue to update with each new high/low but based on that frozen IB range. If you want a rolling 60-min range, disable this study and use a different framework.

4. **Overnight gaps**: IB calculated on regular hours only (MarketOpenTime=0930). Overnight gaps below IB Low are NOT considered breakdowns by this study (no prior bar in IB period). Layer 4 entry rules require prior bar transition, so gap-downs will NOT trigger `above_ib_high`; watch manually.

5. **EMA lag**: EMA 8/13 default is momentum-only, not entry confirmation. Use as bias-check; don't rely on it alone.

6. **Futures vs stocks**: Works identically on ES, NQ, CL, GC, etc. Each has its own IB range calculated independently. No cross-instrument correlation baked in.

7. **Python orphan status**: No equivalent calculation in `engine/backtest/signals.py`. IB High/Low are approximated as `prev_high`/`prev_low` (shift-1), which is close but not exact. Full Python port requires capturing the first 60 bars of each session and computing their range separately — planned as Phase 2 refactor.

## References

- **JARVIS Backtest**: `engine/backtest/signals.py:281–291` (simplified IB approximation)
- **Composite Signals**: `engine/agents/composite_signals.py:285–320` (Layer 4 entry checks)
- **COHEN_MES_README.md** — Framework philosophy and Layer stacking

## Author Note

"IB is the market's reset. First hour sets the tone for the entire day. Breakouts above IB High with momentum (EMA cross) are the highest-conviction setups in liquid futures." — Corey Surles

---
*Last updated: 2026-04-20*
