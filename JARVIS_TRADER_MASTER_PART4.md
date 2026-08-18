# JARVIS TRADER -- Master Document (Part 4)
# Sections 1.15 through 1.20
# Version 3.0 | 2026-03-30

---

## 1.15 Options Trading System (FULL SPEC + BUILD PLAN)

> **STATUS: PLANNED -- NOT YET BUILT**
>
> This section is a complete specification for the options trading subsystem.
> No code exists yet. All files listed in "Infrastructure to Build" must be
> created before any options strategies can execute.

The options layer sits on top of the existing futures engine and adds five
distinct strategy types, each with precise entry/exit/management rules. Options
are used for income generation (covered calls, credit spreads), portfolio
hedging (protective puts), range-bound capture (iron condors), and event-driven
volatility (straddles/strangles).

---

### A. Covered Calls on Futures (MES / MNQ)

**Concept:** Own 1 micro futures contract in a current long position and sell
1 OTM call against it. The premium collected provides income and a small
downside buffer. The trade-off is capped upside above the strike price.

**Entry Conditions:**
- Already hold 1 micro futures contract (MES or MNQ) as a long position
- Sell 1 OTM call at **0.30 delta** (approximately 1 standard deviation OTM)
- Strike selection: current underlying price + (1.0 to 1.5 x ATR)
- Expiration: **7-14 DTE** (weeklies strongly preferred for faster theta decay)
- Regime requirement: RegimeClassifier must report **TRENDING** or **RANGING**
  - Do NOT sell calls in VOLATILE regime (gap risk too high, premium not worth it)
- IV Rank must be **> 30%** (only sell premium when it is expensive relative to history)

**Greeks Targets at Entry:**
| Greek   | Target              | Rationale                                    |
|---------|---------------------|----------------------------------------------|
| Delta   | -0.30 at entry      | ~70% probability of expiring OTM             |
| Theta   | > $0.50/day/contract | Minimum daily income to justify the position  |
| IV Rank | > 30%               | Sell expensive premium only                   |

**Delta Drift Management:**
- Allow call delta to drift from -0.30 toward -0.10 as time passes
- When delta reaches -0.10 (or premium hits 50% of max profit): **roll**
  - Close the current short call
  - Sell a new call further OTM (back to -0.30 delta)
  - Same or next expiration cycle

**Exit Rules (Priority Order):**
1. **Let expire worthless** -- primary goal. Keep 100% of premium collected.
2. **Roll at 0.10 delta** -- when 50% of max profit is captured, roll to next cycle
   further OTM to collect additional premium.
3. **Close if underlying hits T1 target** -- lock in the futures profit. Release
   the call obligation by buying back the short call. This is an active management
   decision: the futures gain exceeds the forfeited premium.
4. **Assignment risk** -- if the call goes ITM near expiration, accept assignment.
   The futures position is called away at the strike. Net P&L = (strike - futures entry)
   + premium collected. This is a profitable outcome by design.

**Stop-Loss:**
- There is no stop-loss on the call itself. Covered calls have defined risk:
  the maximum loss is forgone upside above the strike price.
- The underlying futures position retains its own stop-loss (from the STC strategy).
- Premium collected partially offsets potential futures losses if the underlying
  drops. The call expires worthless and the premium is retained.

**Risk Profile:**
- Maximum profit: premium received + (strike - futures entry) if called away
- Maximum loss: full downside on the futures position minus premium received
  (same directional risk as holding the futures contract unhedged)
- Breakeven: futures entry price minus premium received per point

**Example Trade (MES):**
```
MES long at 5,450.00
Sell 1 MES 5,480 Call (0.30 delta), 10 DTE
Premium received: 8.50 points = $42.50 ($5/point x 8.50)
Theta: $0.85/day

Scenario 1 -- Expire OTM: Keep $42.50. Continue holding MES long.
Scenario 2 -- Roll at 0.10 delta (day 6): Buy back for $2.00 ($10),
              sell new 5,500 Call for $6.00 ($30). Net new credit: $20.
Scenario 3 -- MES hits T1 (5,465): Close call for $3.00 ($15).
              Futures gain: 15 pts x $5 = $75. Net: $75 + $42.50 - $15 = $102.50.
```

---

### B. Credit Spreads (Vertical Put/Call Spreads)

**Concept:** Sell premium with defined risk using vertical spreads. Two flavors:

#### B1. Bull Put Spread (Bullish / Neutral Outlook)

**Structure:**
- Sell 1 put at **0.30 delta** (short strike)
- Buy 1 put **2-3 strikes lower** (long strike, protection wing)
- Net credit = premium received - premium paid for wing

**Example:**
```
MES at 5,450
Sell 5,430 Put (0.30 delta) for 12.00 points
Buy 5,420 Put (wing) for 8.00 points
Net credit: 4.00 points = $20.00
Spread width: 10 points = $50.00
Max risk: $50 - $20 = $30.00
Max profit: $20.00 (if both expire OTM)
Probability of profit: ~70% (short strike at 0.30 delta)
```

#### B2. Bear Call Spread (Bearish / Neutral Outlook)

**Structure:**
- Sell 1 call at **0.30 delta** (short strike)
- Buy 1 call **2-3 strikes higher** (long strike, protection wing)
- Same net credit structure, opposite directional bias

**Parameters for Both Spread Types:**
| Parameter         | MES Options    | MNQ Options     |
|-------------------|----------------|-----------------|
| Spread width      | $5-10 per side | $10-25 per side |
| DTE at entry      | 30-45 days     | 30-45 days      |
| Delta (short leg) | 0.30           | 0.30            |
| IV Rank minimum   | > 30%          | > 30%           |

**Management Rules:**
- **Profit target:** Close at **50% of max credit received**. Do not hold to
  expiration hoping for the last 50% -- risk/reward deteriorates.
- **Time-based close:** At **21 DTE**, close the spread regardless of P&L.
  Gamma risk accelerates after 21 DTE and small moves can wipe out gains.
- **Stop-loss:** If unrealized loss reaches **2x the premium received**, close
  the spread immediately. Discipline > hope.
- **Never roll losing spreads** -- close, assess, re-enter with fresh analysis.

**When to Use Which:**
- Bull put spread: regime = TRENDING UP or RANGING, signal = LEAN_BULL or HOLD
- Bear call spread: regime = TRENDING DOWN or RANGING, signal = LEAN_BEAR or HOLD
- Never enter either spread when regime = VOLATILE

---

### C. Iron Condors (Range-Bound Markets)

**Concept:** Combine a bull put spread and a bear call spread into a single
position. Profit from time decay while the underlying stays within a range.

**Structure:**
| Leg       | Delta  | Description                    |
|-----------|--------|--------------------------------|
| Long put  | -0.05  | Far OTM protection (wing)      |
| Short put | -0.16  | ~1 standard deviation OTM      |
| Short call| +0.16  | ~1 standard deviation OTM      |
| Long call | +0.05  | Far OTM protection (wing)      |

**Regime and Volatility Requirements (ALL must be true):**
1. RegimeClassifier reports **RANGING** -- TRENDING or VOLATILE regimes disqualify
2. VIX level must be **NORMAL (16-20) or ELEVATED (20-25)**
   - VIX < 16 (CALM): premium too thin, not worth the trade
   - VIX > 25 (HIGH/EXTREME): gap risk too high, spreads too wide
3. IV Rank > **30%** -- only sell premium when it is rich relative to recent history
4. No earnings announcements, FOMC, CPI, NFP, or GDP releases within the
   expiration window (check EconomicCalendar from `news_blackout.py`)

**Wing Width:** $5-10 per side (MES) or $10-25 per side (MNQ)

**DTE:** 30-45 days at entry

**P&L Profile:**
```
Max profit: total credit received (both spreads expire OTM)
Max loss: wider spread width - total credit received
          (capped by wings on both sides)
Breakeven: short put strike - total credit AND short call strike + total credit
```

**Management Rules:**
1. **Profit target:** Close entire condor at **50% of max credit**.
2. **Tested side adjustment:** If the short strike delta on either side reaches
   **0.30** (the underlying is moving toward it), roll that side out in time
   and further OTM. Roll means: close the threatened spread, re-sell at a new
   strike with the same or better credit.
3. **Hard stop (per side):** If max loss on either the put spread or call spread
   reaches **2x the credit received for that side**, close that side immediately.
   The untested side can remain if still within parameters.
4. **Time-based close:** At 21 DTE, close the entire condor regardless.

**Never Enter Iron Condors When:**
- VIX > 25 (HIGH or EXTREME) -- gap risk exceeds premium income
- Regime = VOLATILE -- the underlying will blow through one side
- Major economic events fall within the expiration window
- Less than 30 DTE (insufficient theta runway)

**Example Trade (MES):**
```
MES at 5,450, VIX at 18 (NORMAL), Regime = RANGING

Sell 5,380 Put (0.16 delta) / Buy 5,370 Put (0.05 delta)  -- Bull put wing
Sell 5,520 Call (0.16 delta) / Buy 5,530 Call (0.05 delta) -- Bear call wing

Put spread credit: 3.50 points = $17.50
Call spread credit: 3.00 points = $15.00
Total credit: 6.50 points = $32.50
Max loss per side: 10 points - 3.50 = 6.50 points = $32.50 (put side)
                   10 points - 3.00 = 7.00 points = $35.00 (call side)

Target: close at $16.25 (50% of $32.50)
Hard stop: close put side if loss exceeds $35.00 (2x $17.50)
           close call side if loss exceeds $30.00 (2x $15.00)
```

---

### D. Protective Puts (Portfolio Hedge)

**Concept:** Buy OTM puts as insurance against a sharp market decline. This is
a cost center, not a profit center. The goal is to cap portfolio drawdown during
elevated risk periods.

**Entry Triggers (BOTH must be true simultaneously):**
1. VIX enters **ELEVATED** regime (VIX > 20)
2. RegimeClassifier reports **VOLATILE**

When both conditions are met, buy protection. When either condition clears,
evaluate whether to close the hedge.

**Structure:**
- Buy 1 OTM put at **0.20 delta** on MES or MNQ (whichever has the larger
  position in the portfolio)
- Duration: **30-60 DTE** (long enough for protection, short enough to limit
  premium bleed)

**Cost Budget:**
- Maximum **0.5% of total portfolio value per month** on protective puts
- If the cost of a 0.20 delta put exceeds 0.5% of portfolio, either:
  - Move to a lower delta (cheaper, less protection)
  - Skip the hedge (accept the drawdown risk)
- Track cumulative hedging cost in `paper_tracker.py` as a separate line item

**Exit Rules:**
1. **VIX drops below 16 (CALM):** Close the put. The fear event has passed.
   Holding longer wastes premium via theta decay.
2. **Premium loss hits 80%:** Close and accept the cost. Re-evaluate conditions
   before buying new protection.
3. **Event materializes (underlying drops significantly):** The put gains value.
   Close when the put is ITM and the portfolio has been defended. Book the gain
   as an offset to portfolio losses.
4. **Expiration approaches (< 7 DTE):** Close or roll. Do not let puts expire
   worthless if conditions still warrant protection -- roll to next cycle.

**When NOT to Hedge:**
- VIX < 16 (CALM) -- hedging is cheap but unnecessary
- Regime = TRENDING UP -- buying puts during a strong uptrend is expensive and
  rarely pays off
- After a major decline has already occurred (buying puts at peak VIX is buying
  at the worst price)

---

### E. Straddles / Strangles (Pre-Event Volatility Plays)

**Concept:** Buy both a call and a put to profit from a large move in either
direction. Used exclusively around major scheduled economic events where the
move is expected to exceed the cost of both options.

#### E1. Straddle (Symmetric, Maximum Sensitivity)

**Structure:**
- Buy 1 ATM call + Buy 1 ATM put
- Same strike price (ATM), same expiration
- Entry: **1-2 trading days before the scheduled event**
- Higher cost, lower breakeven distance (small moves profit)

#### E2. Strangle (Wider, Cheaper, Requires Larger Move)

**Structure:**
- Buy 1 OTM call (0.25 delta) + Buy 1 OTM put (0.25 delta)
- Different strike prices (both OTM), same expiration
- Entry: **1-2 trading days before the scheduled event**
- Lower cost, wider breakeven (requires significant move to profit)

**Event Calendar (from `news_blackout.py`):**
| Event          | Frequency       | Time (ET)  | Impact Level | Typical Move |
|----------------|-----------------|------------|--------------|--------------|
| FOMC Decision  | 8x per year     | 14:00      | EXTREME (3)  | 30-80 MES pts|
| CPI Release    | Monthly (~12th) | 08:30      | HIGH (2)     | 20-50 MES pts|
| NFP Jobs       | 1st Friday/mo   | 08:30      | HIGH (2)     | 15-40 MES pts|
| GDP Advance    | Quarterly       | 08:30      | HIGH (2)     | 10-30 MES pts|
| PCE Deflator   | Monthly         | 08:30      | HIGH (2)     | 15-35 MES pts|

**Exit Rules (CRITICAL -- timing matters more than price):**
- Exit within the **first 30 minutes after the data release**
- The move happens fast; IV crush begins immediately after the number is known
- Holding past 30 minutes means IV collapse eats into intrinsic value
- Target: **1.5x total premium paid** (both legs combined)
- Maximum risk: **total premium paid** (both legs expire worthless -- worst case)

**Never Hold Through Full IV Crush:**
- The entire edge is in the initial move before IV reprices
- After 30 minutes, the options are repriced to post-event volatility
- A straddle that is breakeven on intrinsic value may still lose money due to
  the IV drop across both legs

**Position Sizing:**
- Maximum **1% of portfolio** on any single straddle/strangle
- Only trade EXTREME impact events (FOMC primarily) with straddles
- Use strangles for HIGH impact events (CPI, NFP) -- cheaper, similar payoff
  if the move is large enough

**Example (FOMC Straddle on MES):**
```
MES at 5,450, FOMC in 2 days
Buy 5,450 Call for 18.00 points = $90.00
Buy 5,450 Put for 17.00 points = $85.00
Total premium: 35.00 points = $175.00

Breakeven: 5,415 (down 35) or 5,485 (up 35)
Target: 52.50 points ($262.50 -- 1.5x premium)
Max loss: $175.00 (both expire worthless)

FOMC day: MES gaps to 5,510 (+60 pts)
Call value: ~62.00 points = $310.00
Put value: ~2.00 points = $10.00
Total: $320.00. Profit: $320 - $175 = $145.00 (83% return)
Exit immediately -- do not wait for more.
```

---

### Options Infrastructure to Build

All options modules will reside in `engine/options/`. No files exist yet.

#### Files to Create

| File                          | Purpose                                                    | Priority |
|-------------------------------|------------------------------------------------------------|----------|
| `engine/options/__init__.py`  | Package init, exports                                      | P0       |
| `engine/options/greeks_monitor.py` | Black-Scholes Greeks calculation, IV surface modeling  | P0       |
| `engine/options/chain_fetcher.py`  | IB Gateway options chain data via `ib_async`           | P0       |
| `engine/options/premium_calculator.py` | Premium pricing, probability of profit, expected value | P1  |
| `engine/options/strategy_executor.py` | Options order construction (spreads, condors, straddles) | P1 |
| `engine/options/position_manager.py` | Track positions, monitor Greeks drift, expiration alerts | P1 |
| `engine/options/iv_rank.py`   | IV Rank calculation (current IV vs. 52-week range)         | P1       |
| `engine/options/roll_manager.py` | Roll logic for covered calls and spreads               | P2       |
| `engine/options/event_scanner.py` | Scan upcoming events, suggest straddle/strangle trades | P2       |

#### API Endpoints to Add (in `engine/main.py` or new `engine/routers/options_router.py`)

| Method | Endpoint                      | Description                                       |
|--------|-------------------------------|---------------------------------------------------|
| GET    | `/options/chain/{symbol}`     | Fetch options chain with Greeks for a symbol       |
| GET    | `/options/positions`          | Current options positions with P&L and Greeks      |
| POST   | `/options/trade`              | Paper trade an options strategy (spread, condor)   |
| GET    | `/options/greeks`             | Portfolio-level Greeks summary (delta, gamma, theta, vega) |
| POST   | `/options/scan`               | Scan for opportunities (high IV rank, spread candidates) |
| GET    | `/options/iv-rank/{symbol}`   | Current IV Rank for a symbol                       |
| POST   | `/options/roll`               | Execute a roll (close current, open new position)  |
| GET    | `/options/events/upcoming`    | Upcoming economic events with straddle candidates  |

#### Dashboard Pages to Add

| Page                              | Components                                           |
|-----------------------------------|------------------------------------------------------|
| `dashboard/app/options/page.tsx`  | Options positions table, Greeks summary, P&L chart   |
| `dashboard/app/options/chain/page.tsx` | Options chain viewer with strike/expiry grid    |
| `dashboard/components/GreeksSummaryCard.tsx` | Portfolio delta, gamma, theta, vega display |
| `dashboard/components/IVRankGauge.tsx` | Visual gauge for IV Rank with threshold markers |
| `dashboard/components/OptionsPositionTable.tsx` | Active options positions with management buttons |

#### Dependencies Required

- `ib_async >= 0.9.86` -- already in `requirements.txt` (IB Gateway connection)
- `py_vollib` or `mibian` -- Black-Scholes pricing (to be added)
- No additional dashboard dependencies needed (existing Recharts + Tailwind sufficient)

---

## 1.16 Futures Strategies (Detailed Per-Instrument)

Each instrument has unique characteristics that determine strategy configuration,
risk parameters, and trading eligibility. This section is the canonical reference
for all instrument-specific decisions.

---

### MES (Micro E-mini S&P 500)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Exchange          | CME Globex                                      |
| Multiplier        | $5 per point                                    |
| Tick size         | 0.25 points ($1.25 per tick)                    |
| Typical margin    | ~$1,200 (varies with volatility)                |
| Session           | Near 24h; RTH 9:30-4:00 ET                     |
| Commission        | $2.50 per contract (round-trip estimate)        |
| ATR (daily)       | 15-30 points typical                            |

**Strategy Configuration:**
- STC_OS=15, STC_OB=83, Stop=0.50 ATR, T1=2.00 ATR, T2=3.236 ATR, T3=4.00 ATR
- `regime_filter=OFF` -- structure-based entries in EXHAUSTED and COMPRESSION regimes
  improve MES PF from 0.96 to 1.69 (v2.5 re-optimization)
- `adaptive_regime=OFF`

**Walk-Forward Results:**
- WFE = **0.09** (OVERFIT)
- OOS profitable: 1/6 windows (17%)
- Only 23 trades in test period -- insufficient for statistical significance
- **Verdict: DO NOT TRADE until signal redesign and extended data**

**Why MES Fails:**
- S&P 500 is highly efficient -- STC crossover signals lack edge
- Low trade count (23) provides no statistical confidence
- ATR targets (2.00 ATR) rarely hit intraday -- 36/51 daily trades exit at EOD
- Regime filter OFF somewhat helps but WFE remains deeply overfit

---

### MNQ (Micro E-mini Nasdaq 100)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Exchange          | CME Globex                                      |
| Multiplier        | $2 per point                                    |
| Tick size         | 0.25 points ($0.50 per tick)                    |
| Typical margin    | ~$2,500 (varies with volatility)                |
| Session           | Near 24h; RTH 9:30-4:00 ET                     |
| Commission        | $2.50 per contract                              |
| ATR (daily)       | 50-150 points typical                           |

**Volatility Profile:** HIGH -- Nasdaq moves 2-5x MES in percentage terms.
This higher volatility is precisely what gives STC more to work with.

**Strategy Configuration (APPROVED for paper trading):**
- STC_OS=15, STC_OB=92, Stop=0.70 ATR, T1=1.00 ATR, T2=1.80 ATR, T3=2.618 ATR
- `regime_filter=ON` (required for adaptive_regime to function)
- `adaptive_regime=ON` -- **CRITICAL**: lifts WFE from 0.24 to 0.57
- `volume_filter=OFF` -- **NEVER ENABLE**: degrades WFE from 0.57 to -0.23
- `mtf_filter=OFF` -- **NEVER ENABLE**: degrades WFE from 0.57 to 0.17

**Walk-Forward Results:**
- WFE = **0.57** (GOOD -- clears 0.50 threshold)
- OOS profitable: 4/6 windows (67%)
- Config: adaptive regime only -- no MTF, no volume filter
- Corrected from 0.48 on 2026-03-29T23:46 run

**Why Adaptive Regime Is Critical:**
- Nasdaq has distinct trending/ranging phases
- Trending regimes use tighter STC thresholds (enter earlier)
- Ranging regimes use wider thresholds (wait for stronger signals)
- The adaptive switching captures 138% more OOS performance vs static params

**OOS Stable Parameter Zone (Agent AC Finding):**
- OS=23, OB=88, stop=0.70 ATR, T1=2.00 ATR
- Identified as the most parameter-stable region across walk-forward windows
- Alternative to the primary OS=15/OB=92 if the primary set degrades during paper trading

**Paper Trading Config:**
- Capital: $25,000
- Risk/trade: 0.25% ($62.50 max risk per trade)
- Kill switch: -3% monthly OR 3 consecutive losses
- Max concurrent: 1 contract

---

### MCL (Micro Crude Oil)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Exchange          | CME Globex (NYMEX)                              |
| Multiplier        | $100 per point (1,000 barrels x $0.10 tick)     |
| Tick size         | $0.01/barrel ($10 per contract per tick)         |
| Typical margin    | ~$800 (varies with oil volatility)              |
| Session           | Near 24h (CME Globex extended hours)            |
| Commission        | $2.50 per contract                              |
| ATR (daily)       | $0.50-$2.00 typical                             |

**Mean-Reversion Tendency:** Crude oil oscillates within regimes far more than
equities. This mean-reverting behavior is well suited to STC crossover signals
that catch reversals within established ranges.

**Strategy Configuration (APPROVED for paper trading):**
- STC_OS=15, STC_OB=83, Stop=0.90 ATR, T1=1.50 ATR, T2=2.618 ATR, T3=4.00 ATR
- `regime_filter=ON` (oil is regime-sensitive)
- `adaptive_regime=OFF` -- **NEVER ENABLE**: adaptive WFE = -0.31, FAR WORSE
  than static 0.82
- `volume_filter=OFF`
- `mtf_filter=OFF`

**Walk-Forward Results:**
- WFE = **0.82** (EXCELLENT -- highest of all instruments)
- OOS profitable: 5/6 windows (83%)
- Config: static params only
- Confirmed on 2026-03-29T23:41 run

**Why Static Beats Adaptive for MCL:**
- Crude oil regime transitions are too abrupt for the EMA-spread-based RegimeClassifier
- The classifier flips TRENDING/RANGING mid-move in oil, causing false signal regime tags
- Static params with regime_filter=ON (which uses a simpler regime gate) works far better

**Paper Trading Config:**
- Capital: $25,000
- Risk/trade: 0.25% ($62.50 max risk per trade)
- Kill switch: -3% monthly OR 3 consecutive losses
- Max concurrent: 1 contract

---

### MGC (Micro Gold)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Exchange          | CME Globex (COMEX)                              |
| Multiplier        | $10 per point (10 troy ounces)                  |
| Tick size         | $0.10/oz ($1 per contract per tick)             |
| Typical margin    | ~$1,500 (varies)                                |
| Session           | Near 24h; RTH 8:20-1:30 CT                     |
| Commission        | $2.50 per contract                              |
| ATR (daily)       | $3-$15 typical                                  |

**Trend-Following Characteristics:** Gold makes extended trending moves (bull
runs, safe-haven flights) that can persist for months. This characteristic
initially made MGC appear to be the best STC candidate.

**Strategy Configuration (HALTED):**
- STC_OS=17, STC_OB=88, Stop=0.30 ATR, T1=1.50 ATR, T2=2.618 ATR, T3=4.00 ATR
- `regime_filter=OFF` -- regime_filter is **anti-predictive** for gold daily
  (regime=ON windows avg OOS -1.7%, regime=OFF avg OOS +5.9%)
- `adaptive_regime=OFF` -- identical WFE to static (0.27 both ways)
- Only viable on daily timeframe; hourly gold (MGC 1h PF=0.77) loses money

**Walk-Forward Results:**
- WFE = **0.14** (OVERFIT -- below 0.30 threshold)
- Extended history (2022-2026, 15 windows): only 6/15 (40%) OOS windows profitable
- Bear market data (2022-2023) exposes underlying parameter instability

**The Small-Sample Bias Story:**
- v2.2: MGC adaptive WFE = 0.88 (EXCELLENT) -- appeared ready for paper trading
- Only 3 walk-forward windows were used, all during the 2025 gold bull run
- Extended to 15 windows (2022-2026): WFE collapsed to 0.14
- This is a textbook case of small-sample overfitting -- the 2025 gold rally
  was an outlier regime that made the optimizer look like a genius
- **Lesson:** Always validate with 10+ walk-forward windows. 3 windows is
  insufficient for any statistical claim.

**Status:** HALTED. Requires fundamental signal redesign + extended 2022 history
before reconsideration. At minimum 24 months of new data before re-evaluation.

---

### M2K (Micro Russell 2000)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Multiplier        | $5 per point                                    |
| Commission        | $2.50 per contract                              |

**Status: PERMANENTLY REMOVED FROM TRADING UNIVERSE**

- 1h PF = 0.64 (consistently losing)
- 1d PF = 0.60 (consistently losing)
- Russell 2000 is unsuitable for STC strategy: high beta, mean-reverting at
  the index level, regime structure does not match STC's trend-following nature
- No walk-forward was even run -- in-sample results are negative
- **Do not reconsider M2K for the STC strategy. Period.**

---

### SPY (SPDR S&P 500 ETF)

**Status: BACKTESTING REFERENCE ONLY (Not a futures contract)**

- Used as a benchmark proxy in reporting
- WFE = -1.11 (DEEPLY OVERFIT, worst of all instruments)
- Re-optimized in v2.5: PF 3.00 to 3.79, but near-zero returns
- Negative Sharpe (-1.43) despite high PF -- a statistical warning sign
  (a few large wins mask many small losses)
- **Do not trade. Do not paper trade. Reference only.**

---

### Instrument Trading Status Summary

| Symbol | TF  | WFE    | Config                   | Status                        |
|--------|-----|--------|--------------------------|-------------------------------|
| MCL    | 1h  | 0.82   | Static, regime ON        | **APPROVED -- Paper trading** |
| MNQ    | 1h  | 0.57   | Adaptive regime only     | **APPROVED -- Paper trading** |
| MGC    | 1d  | 0.14   | Static, regime OFF       | HALTED -- Overfit             |
| MES    | 1h  | 0.09   | Static, regime OFF       | DO NOT TRADE                  |
| SPY    | 1h  | -1.11  | N/A                      | Reference only                |
| M2K    | any | N/A    | N/A                      | Permanently removed           |

---

## 1.17 Go-Live Validation Checklist (CANONICAL)

> **This is the ONE authoritative checklist.** All previous conflicting
> thresholds (WR 28%, WR 50%, WR 55%, MaxDD 8%, MaxDD 10%, MaxDD 15%,
> min trades 40 vs 60) are RESOLVED below. Do not reference older documents
> for threshold values.

---

### Tier 1: Paper Trading Qualification

**All items must be checked before paper trading can be declared successful.**
**Minimum period: 60 calendar days with 60+ trades.**

| #  | Criterion                                      | Threshold          | Status |
|----|-------------------------------------------------|--------------------|--------|
| 1  | Minimum trades executed                         | >= 60 trades       | [ ]    |
| 2  | Minimum calendar days                           | >= 60 days         | [ ]    |
| 3  | Forward walk-forward WFE (rolling, last 30 days)| >= 0.50            | [ ]    |
| 4  | Rolling win rate (paper, not backtested)         | >= 45%             | [ ]    |
| 5  | Profit factor (paper, not backtested)            | >= 1.5             | [ ]    |
| 6  | Maximum drawdown during paper period             | < 10%              | [ ]    |
| 7  | Zero EP-3 events (data feed failures) in last 2 weeks | 0 events    | [ ]    |
| 8  | WhatsApp alerts verified working                 | 5+ SIDs confirmed  | [ ]    |
| 9  | Kill switch tested                               | Activate + deactivate OK | [ ] |
| 10 | Engine uptime during paper period                | > 95%              | [ ]    |
| 11 | No -3% monthly draws during paper period         | 0 months at -3%    | [ ]    |
| 12 | IB paper port 4002 tested and connected          | Connected           | [ ]    |
| 13 | All endpoints returning valid responses           | ~95 endpoints OK   | [ ]    |

**Threshold Resolution Notes:**
- Win rate: 28% was an old estimate from early research, 55% was an aggressive
  target from the skill docs. **Resolved: 45% for paper qualification** (realistic
  for a trend-following strategy).
- Max drawdown: 8% was live gate, 15% was an old estimate. **Resolved: 10% for
  paper qualification** (strict enough to prove consistency, loose enough to allow
  learning).
- Min trades: 40 was from an early draft, 60 is current. **Resolved: 60 trades
  over 60 days** (approximately 1 trade/day average -- realistic for 2 instruments).

---

### Tier 2: Live Trading Gate

**Requires Tier 3 autonomy -- Matt must manually confirm EVERY item.**

| #  | Criterion                                      | Threshold          | Status |
|----|-------------------------------------------------|--------------------|--------|
| 1  | Paper qualification checklist (Tier 1)          | ALL items checked  | [ ]    |
| 2  | Forward WFE maintained                          | >= 0.50 for 3+ months | [ ] |
| 3  | Win rate in paper period                        | >= 50%             | [ ]    |
| 4  | Profit factor in paper period                   | >= 2.0             | [ ]    |
| 5  | Maximum paper drawdown                          | < 8%               | [ ]    |
| 6  | Sharpe ratio in paper period                    | >= 1.0             | [ ]    |
| 7  | SCHWAB_READY flag set manually by Matt          | True               | [ ]    |
| 8  | IB live account funded                          | >= $10,000         | [ ]    |
| 9  | Live port 4001 manually enabled                 | Enabled (blocked by default) | [ ] |
| 10 | Starting position size                          | 1 MES contract, 0.25% risk | [ ] |
| 11 | 30-day live trial before scaling                | Completed          | [ ]    |

**Live gate is stricter than paper gate on purpose.** Paper qualification proves
the system works mechanically. Live qualification proves it works financially.
The higher PF (2.0 vs 1.5), WR (50% vs 45%), and lower MaxDD (8% vs 10%)
thresholds reflect the reality that live trading introduces slippage variance,
emotional interference, and execution delays not present in paper.

---

### Tier 3: Scaling Authorization

**After 30-day live trial:**
| #  | Criterion                                      | Threshold          |
|----|-------------------------------------------------|--------------------|
| 1  | Live trial PF                                  | >= 1.5             |
| 2  | Live trial Sharpe                               | >= 0.8             |
| 3  | Live trial max drawdown                         | < 5%               |
| 4  | Matt's subjective comfort level                 | Explicit approval  |
| 5  | Scale step                                      | +1 contract per instrument per quarter |

---

### Circuit Breakers (Active at ALL Tiers)

| Breaker                | Trigger            | Action                          |
|------------------------|--------------------|---------------------------------|
| Daily loss limit       | -2% in one day     | Pause until next session        |
| Monthly kill switch    | -3% in one month   | Halt instrument, review required|
| Consecutive losses     | 3 in a row         | Manual review before next trade |
| Max portfolio drawdown | -10% from peak     | Kill switch ALL instruments     |
| WFE degradation        | Rolling WFE < 0.30 | Halt instrument, re-optimize    |

---

## 1.18 Session History & Decision Log

This section records the complete version timeline and every significant
strategic decision made during the project. It serves as an audit trail and
prevents re-litigating settled questions.

---

### Version Timeline

| Version | Date       | Key Change                                                    |
|---------|------------|---------------------------------------------------------------|
| v1.0    | Early 2026 | Initial strategy. In-sample results only. CONDITIONAL GO based on MGC. Numbers massively inflated by look-ahead bias + partial stop bugs. |
| v2.0    | 2026-03    | Full walk-forward validation for all 5 instruments. ALL 5 FAIL static WFE. Verdict: NO-GO. Signal redesign required. |
| v2.1    | 2026-03    | RegimeClassifier built (`regime.py`). MNQ WFE improved 0.24 to 0.34. Target > 0.40. |
| v2.2    | 2026-03    | MGC adaptive WFE = 0.88 (EXCELLENT). Later revealed as small-sample bias (3 windows). |
| v2.3    | 2026-03    | Combined filter testing. Volume filter destroys MNQ edge (0.34 to -0.23). SPY adaptive WFE improved -1.11 to -0.71 but still overfit. |
| v2.4    | 2026-03    | Extended MGC history (2022-2026, 15 windows). WFE = 0.27. Small-sample bias confirmed. CONDITIONAL-CAUTION. |
| v2.5    | 2026-03-29 | SPY/MES re-optimized. Per-instrument regime_filter flags added to INSTRUMENT_PARAMS (7-element tuples). MES PF 0.96 to 1.69 (regime OFF). |
| v2.6    | 2026-03-29 | **CRITICAL bug fix** -- optimizer kwarg bug discovered. Extra kwargs silently caused all walk-forward optimization calls to return None. ALL previous WFEs invalid. Corrected: MGC 0.27 to 0.14 (HALTED), MNQ static 0.34 to 0.24. |
| v2.7    | 2026-03-30 | Final corrections. MNQ adaptive WFE confirmed 0.57. MCL static WFE confirmed 0.82. MTF filter tested and REJECTED (0.57 to 0.17). Volume filter REJECTED (0.57 to -0.23). **Paper trading APPROVED for MCL 1h and MNQ 1h.** |

---

### Key Decisions Log

Each decision below is FINAL unless new walk-forward evidence contradicts it.

| # | Decision                                   | Verdict      | Evidence                                    | Date       |
|---|-------------------------------------------|--------------|---------------------------------------------|------------|
| 1 | Static STC params for all instruments      | REJECTED     | All 5 instruments OVERFIT (WFE < 0.30)      | 2026-03    |
| 2 | Adaptive regime for MNQ                    | **APPROVED** | WFE lifts 0.24 to 0.57 (+138%)              | 2026-03-30 |
| 3 | Adaptive regime for MCL                    | REJECTED     | WFE drops 0.82 to -0.31 -- adaptive HURTS   | 2026-03-30 |
| 4 | Adaptive regime for MGC                    | REJECTED     | WFE identical to static (0.14 both ways)     | 2026-03-29 |
| 5 | MTF filter for MNQ                         | REJECTED     | WFE drops 0.57 to 0.17 (-70%)               | 2026-03-30 |
| 6 | Volume filter for MNQ                      | REJECTED     | WFE drops 0.57 to -0.23 -- over-constrains  | 2026-03-30 |
| 7 | Volume filter for MCL                      | NOT TESTED   | MCL already at WFE 0.82 -- do not fix what works | 2026-03-30 |
| 8 | Trailing ATR stop                          | REJECTED     | Grid search confirms no improvement for any instrument | 2026-03-29 |
| 9 | MGC daily paper trading                    | **HALTED**   | WFE 0.14 post-bugfix (was 0.27, was 0.88 at 3 windows) | 2026-03-30 |
| 10| Paper risk: 0.25% (not 1.0%)              | **APPROVED** | Conservative for validation phase            | 2026-03-30 |
| 11| News/event blackout filter                 | KEEP (live)  | 81 events in calendar, ~1% signals blocked   | 2026-03-29 |
| 12| MCL static paper trading                   | **APPROVED** | WFE 0.82 EXCELLENT, 5/6 OOS profitable       | 2026-03-30 |
| 13| MNQ adaptive paper trading                 | **APPROVED** | WFE 0.57 GOOD, 4/6 OOS profitable            | 2026-03-30 |
| 14| M2K removed from universe                  | PERMANENT    | PF < 0.65 both timeframes, unsuitable for STC | 2026-03    |

---

### Bugs Found and Fixed (Chronological)

| # | Bug                                        | Impact                                         | Fix         |
|---|--------------------------------------------|-------------------------------------------------|-------------|
| 1 | Look-ahead bias in signal generation       | Signals used future candle data for entry decisions | backtester.py |
| 2 | Partial stop exits                         | Stop-loss exits credited partial bar P&L instead of exact stop price | backtester.py |
| 3 | T1 target unreachable at 1.50 ATR          | Almost never hit intraday -- changed to 1.00 ATR | signals.py |
| 4 | Duplicate trade counting                   | Same signal could fire on consecutive bars       | backtester.py |
| 5 | Equity curve calculation errors            | Compounding applied incorrectly                  | backtester.py |
| 6 | Win rate inflation                         | Partial exits counted as wins                    | backtester.py |
| 7 | Sharpe calculation wrong annualization     | Used incorrect factor for hourly bars            | backtester.py |
| 8 | Position sizing fractional shares          | Not properly rounded for futures contracts       | backtester.py |
| 9 | **Optimizer kwarg bug** (v2.6 CRITICAL)   | Extra kwargs (adaptive_regime, volume_filter, mtf_filter) silently caused TypeError in `_compute_signals()`, caught by bare except, returned None for ALL optimization calls. Every walk-forward run after these kwargs were added was invalid. | walk_forward.py `_run_with_params()` |

The optimizer kwarg bug (Bug #9) is the most consequential bug found. It
invalidated every walk-forward run between v2.1 and v2.5. The fix was to filter
kwargs to `signal_keys` in `_run_with_params()` before calling `_compute_signals()`.
This single change corrected MGC WFE from 0.27 to 0.14 (revealing overfit) and
MNQ from 0.34 to 0.24 (static) or 0.57 (adaptive, corrected).

---

### Phase Timeline

| Phase | Description                                       | Dates              | Status    |
|-------|---------------------------------------------------|--------------------|-----------|
| A     | Fix 8 critical backtesting bugs                   | Early Mar 2026     | COMPLETE  |
| B     | Corrected backtests: 12-matrix (6 symbols x 2 TF) | Mar 2026          | COMPLETE  |
| C     | Walk-forward validation: 5 instruments             | Mar 2026          | COMPLETE  |
| D     | Monte Carlo (10k sims) + sensitivity analysis      | Mar 2026          | COMPLETE  |
| E     | Research report: 1,245 lines                       | Mar 2026          | COMPLETE  |
| F     | Regime-adaptive STC: RegimeClassifier              | Mar 2026          | COMPLETE  |
| G     | Signal filter testing (volume, MTF, trailing stop) | Mar 2026          | COMPLETE  |
| H     | Paper trading approval: MCL + MNQ                  | 2026-03-30        | COMPLETE  |
| I     | Paper trading execution                            | Apr-May 2026      | ACTIVE    |
| J     | Live trading evaluation                            | Jun 2026+         | PENDING   |

---

## 1.19 Known Issues & Pending Work

---

### P0 -- Critical (Do Immediately)

**Security: API Keys in Git History**
- Anthropic API key (sk-ant-api03-...), Polygon.io key, Twilio SID/Auth Token,
  and Google OAuth client secrets are exposed in git history
- Full remediation guide: `SECURITY_REMEDIATION.md`
- Steps: Revoke all keys, run BFG Repo-Cleaner, force-push cleaned history,
  regenerate keys, populate `.env`
- Install pre-commit hook: `scripts/check-secrets.sh` linked to `.git/hooks/pre-commit`
- **This is the single highest-priority item in the entire project.**

---

### P1 -- High Priority (Before Paper Trading Ends)

**Infrastructure:**
- [ ] IB paper port 4002 integration tested end-to-end with live TWS/IB Gateway
  running. Currently only connection test exists (`/ib/connection-test`).
- [ ] SQLite persistence for paper trades verified under multi-day operation
  (current testing is single-session only).
- [ ] FRED API key configuration -- macro data currently falls back to cached
  values. Need live FRED data for regime classifier accuracy.
- [ ] Yahoo Finance rate limiting mitigation -- occasional 429 errors. Yahoo v8
  API bypass in `data_loader.py` exists as third fallback but needs monitoring.
- [ ] `EmailIntelligenceAgent.analyze_recent_emails` method may be missing in
  some code paths. Verify or remove references.

**Testing:**
- [ ] Zero integration tests for live IB Gateway connection (paper or live).
  Tests exist for HTTP endpoints but not the actual `ib_async` connection flow.
- [ ] Signal warmup tests require 300+ bars of data. 100-bar fixtures caused
  failures and were fixed, but edge cases may remain.
- [ ] No CI/CD pipeline -- all tests run manually via `pytest`. Consider GitHub
  Actions for automated testing.

**Dashboard:**
- [ ] Settings page (`dashboard/app/settings/page.tsx`) -- risk params and kill
  switch UI in progress but not finalized.
- [ ] Backtest comparison page (`dashboard/app/backtest/page.tsx`) -- paper vs
  backtest comparison partially built.
- [ ] Command center page (`dashboard/app/command-center/page.tsx`) -- Iron Man
  HUD concept. Not started.

---

### P2 -- Medium Priority (During Paper Trading)

**Data Limitations:**
- Historical data limited to Yahoo Finance free tier (max ~2 years hourly).
  This constrains walk-forward window count and prevents multi-cycle validation.
- No tick data available. All backtesting uses 1h bars, which masks intrabar
  price action (stop-outs that would have occurred on tick data are invisible).
- Weekend gaps in yfinance data require forward-fill handling. Currently handled
  but not robustly tested across DST transitions.

**Optimization Schedule:**
- Walk-forward re-optimization: scheduled quarterly. First re-optimization should
  run at the end of paper trading period (late May 2026).
- SPY 1h corrected walk-forward: not yet run. May clear 0.50 threshold but
  unverified. Low priority since SPY is not a futures instrument.
- Rolling WFE recalculation every 4 weeks with new data appended.

**Engine:**
- [ ] `engine/health_monitor.py` -- WhatsApp alert if engine goes down. Verify
  it correctly detects process crashes (not just API errors).
- [ ] EOD scheduler (`engine/schedulers/eod_scheduler.py`) -- verify daily
  snapshots execute correctly Mon-Fri at 3:05 PM CT.
- [ ] API authentication: no auth on any endpoint. Acceptable for `localhost`
  only deployment. If engine is ever exposed to a network, add JWT or API key auth.

---

### P3 -- Low Priority (Post Paper Trading)

**Options System:**
- [ ] Build all files in `engine/options/` per Section 1.15 specification.
- [ ] Add options API endpoints to engine.
- [ ] Add options dashboard pages.
- [ ] Integrate with IB Gateway for options chain data.

**Strategy Improvements:**
- [ ] MGC signal redesign with extended 2022 history (bear market data).
- [ ] MES signal redesign (new entry trigger beyond STC crossover).
- [ ] Multi-factor entry confirmation (beyond current regime + STC).
- [ ] Earnings calendar integration for equities proxy instruments.
- [ ] VIX regime overlay on all signals (currently only used for options spec).

**Infrastructure Upgrades:**
- [ ] Trade journal integration with OneNote via MCP.
- [ ] Real options flow data (Unusual Whales or similar).
- [ ] Cloud deployment consideration (currently local-only on Windows).
- [ ] PM2 ecosystem management for all services.

---

### Known Technical Debt

| Item                                  | Location                    | Severity |
|---------------------------------------|-----------------------------|---------:|
| Bare `except` in optimizer            | `walk_forward.py`           | Fixed v2.6 |
| No type hints in backtester core      | `backtester.py`             | Low      |
| Hardcoded event dates in blackout     | `news_blackout.py`          | Low (through 2026) |
| `conftest.py` asyncpg issue           | `engine/tests/conftest.py`  | Low (use `--noconftest`) |
| Dashboard uses `any` types in places  | Various `.tsx` files         | Low      |
| Paper config has `sic_params` typo    | `paper_config.py`           | Low (should be `stc_params`) |

---

## 1.20 File Reference

---

### Authoritative Files (Use These -- Not Older Versions)

These are the canonical, up-to-date files for each concern. When information
conflicts between files, the file listed here takes precedence.

| Concern                    | File                                          | Version / Status      |
|----------------------------|-----------------------------------------------|-----------------------|
| Strategy config (paper)    | `engine/backtest/paper_config.py`             | v2.7 AUTHORITATIVE    |
| Signal parameters          | `engine/backtest/signals.py` (INSTRUMENT_PARAMS) | AUTHORITATIVE      |
| Walk-forward results       | `engine/backtest/results/WF_*.json` (12 files)| FINAL                 |
| Executive briefing         | `engine/backtest/results/EXECUTIVE_BRIEFING.md`| v2.7 FINAL           |
| Paper trading approval     | `PAPER_TRADING_APPROVAL.md`                   | APPROVED 2026-03-30   |
| Strategy summary           | `SUMMARY.md`                                  | v2.7 FINAL            |
| Master document            | `JARVIS_TRADER_MASTER.md` (+ PART2, PART3, PART4) | v3.0 PRIMARY     |
| MCL paper setup            | `engine/paper/MCL_paper_setup.md`             | FINAL                 |
| MNQ paper setup            | `engine/paper/MNQ_paper_setup.md`             | FINAL                 |
| Research report            | `engine/docs/BACKTEST_RESEARCH_REPORT.md`     | 1,245 lines, FINAL   |
| Security remediation       | `SECURITY_REMEDIATION.md`                     | P0 ACTION REQUIRED    |
| Project log                | `jarvis-trader-skill-project-log.md`          | Session 5 current     |

---

### Engine Source Files

| Component                  | Path                                          | Description           |
|----------------------------|-----------------------------------------------|-----------------------|
| Signal generation          | `engine/backtest/signals.py`                  | STC signals + INSTRUMENT_PARAMS |
| Backtester core            | `engine/backtest/backtester.py`               | Trade simulation engine |
| Walk-forward validation    | `engine/backtest/walk_forward.py`             | Rolling 6m/3m WF      |
| Regime classifier          | `engine/backtest/regime.py`                   | EMA spread + BBWidth + ATR voting |
| MTF filter                 | `engine/backtest/mtf_filter.py`               | 4h/daily STC alignment gate |
| Indicators                 | `engine/backtest/indicators.py`               | Technical indicators (STC, ATR, volume_ratio) |
| Optimizer                  | `engine/backtest/optimizer.py`                | Parameter grid search |
| Monte Carlo                | `engine/backtest/monte_carlo.py`              | 10,000 sim Monte Carlo |
| Sensitivity analysis       | `engine/backtest/sensitivity.py`              | Parameter sensitivity |
| News blackout              | `engine/backtest/news_blackout.py`            | EconomicCalendar (81 events, 2024-2026) |
| Paper config               | `engine/backtest/paper_config.py`             | MCL/MNQ/MGC configs   |
| Paper tracker              | `engine/backtest/paper_tracker.py`            | Paper trade tracking  |
| Run backtest CLI           | `engine/backtest/run_backtest.py`             | CLI for single backtests |
| Run all backtests          | `engine/backtest/run_all_backtests.py`        | Full 12-matrix runner |
| Backtest unit tests        | `engine/backtest/test_backtester.py`          | 5/5 passing           |

---

### Engine Infrastructure Files

| Component                  | Path                                          | Description           |
|----------------------------|-----------------------------------------------|-----------------------|
| FastAPI main               | `engine/main.py`                              | ~95 endpoints, port 8010 |
| Database schema            | `engine/database/schema.py`                   | DatabaseManager, 6 tables |
| Database migrations        | `engine/database/migrations.py`               | Version-tracked migrations (001-005) |
| DB init script             | `engine/init_db.py`                           | CLI: `python init_db.py [--reset]` |
| IB Gateway manager         | `engine/execution/ib_gateway.py`              | Paper port 4002, live port 4001 blocked |
| IB Order manager           | `engine/execution/ib_order_manager.py`        | Order reconciliation  |
| Safety layer               | `engine/risk/safety_layer.py`                 | Circuit breakers, kill switch |
| P&L monitor                | `engine/risk/pnl_monitor.py`                  | 3-tier source (IB/SQLite/memory) |
| Position sizing            | `engine/utils/position_sizing.py`             | Fixed-fractional formula |
| Performance calculator     | `engine/analytics/performance.py`             | PF, Sharpe, win rate  |
| EOD scheduler              | `engine/schedulers/eod_scheduler.py`          | Mon-Fri 3:05 PM CT snapshots |
| WhatsApp notifications     | `engine/notifications/whatsapp.py`            | 4 formatters          |
| Journal router             | `engine/routers/journal_router.py`            | Trade journal CRUD    |
| Health monitor             | `engine/health_monitor.py`                    | WhatsApp alert if engine down |
| Trading pipeline           | `engine/agents/pipeline.py`                   | TradingPipeline.run_on_signal() |
| Trader agent               | `engine/agents/trader.py`                     | Position sizing integration |
| Portfolio tracker          | `engine/portfolio/tracker.py`                 | SQLite-backed PortfolioTracker |
| Config                     | `engine/config.py`                            | Env var validation at startup |

---

### Dashboard Files

| Component                  | Path                                          | Description           |
|----------------------------|-----------------------------------------------|-----------------------|
| Main dashboard             | `dashboard/app/page.tsx`                      | Landing page with summary widgets |
| Paper trading page         | `dashboard/app/paper/page.tsx`                | Paper trade monitoring |
| Performance page           | `dashboard/app/performance/page.tsx`          | Performance analytics  |
| Journal page               | `dashboard/app/journal/page.tsx`              | Trade journal view     |
| Watchlist page             | `dashboard/app/watchlist/page.tsx`            | Symbol scanning        |
| Scorecard page             | `dashboard/app/scorecard/page.tsx`            | Validation scorecard   |
| Health page                | `dashboard/app/health/page.tsx`               | 6-subsystem health grid |
| Validation page            | `dashboard/app/validation/page.tsx`           | Pre-live readiness     |
| Settings page              | `dashboard/app/settings/page.tsx`             | Risk params + kill switch |
| Backtest page              | `dashboard/app/backtest/page.tsx`             | Backtest vs live comparison |
| Stats page                 | `dashboard/app/stats/page.tsx`                | Rolling performance    |

**Dashboard component count:** 33+ components across 11 pages (Session 5 total).
All TypeScript: 0 errors.

---

### Scripts

| Script                         | Path                                       | Purpose                      |
|--------------------------------|--------------------------------------------|------------------------------|
| Smoke test                     | `engine/scripts/smoke_test.py`             | 48-endpoint smoke test       |
| Signal tester                  | `engine/scripts/test_signal.py`            | CLI signal tester            |
| Seed paper trades              | `engine/scripts/seed_paper_trades.py`      | 95 synthetic trades, 30 days |
| Pine Script generator          | `engine/scripts/pine_script_generator.py`  | TradingView Pine Script      |
| Generated Pine Script          | `engine/scripts/jarvis_trader_strategy.pine`| Pine Script v5 strategy     |
| TradingView setup guide        | `engine/scripts/TRADINGVIEW_SETUP.md`      | Webhook setup instructions   |
| Daily report                   | `engine/scripts/daily_report.py`           | EOD report generator         |
| Windows startup                | `start_jarvis.bat`                         | Double-click startup         |
| Phase 1-2 verification         | `engine/verify_phase1_2.py`                | Post-build verification      |
| Secret checker (pre-commit)    | `engine/scripts/check-secrets.sh`          | Git hook for secret detection|

---

### Walk-Forward Result Files (12 Completed Runs)

All files in `engine/backtest/results/`:

| File                                          | Description                                      | WFE    | Verdict         |
|-----------------------------------------------|--------------------------------------------------|--------|-----------------|
| `WF_MCL_1h_walk_forward.json`                 | MCL hourly, static params                        | 0.82   | **APPROVED**    |
| `WF_MNQ_1h_adaptive_walk_forward.json`        | MNQ hourly, adaptive regime                      | 0.57   | **APPROVED**    |
| `WF_MNQ_1h_adaptive_mtf_walk_forward.json`    | MNQ hourly, adaptive + MTF                       | 0.17   | REJECTED        |
| `WF_MNQ_1h_adaptive_volume_walk_forward.json` | MNQ hourly, adaptive + volume                    | -0.23  | REJECTED        |
| `WF_MCL_1h_adaptive_walk_forward.json`        | MCL hourly, adaptive regime                      | -0.31  | REJECTED        |
| `WF_MGC_1d_walk_forward.json`                 | MGC daily, static (15 windows)                   | 0.14   | HALTED          |
| `WF_MNQ_1h_walk_forward.json`                 | MNQ hourly, static params                        | 0.24   | OVERFIT         |
| `WF_MES_1h_walk_forward.json`                 | MES hourly, static params                        | 0.09   | OVERFIT         |
| `WF_MGC_1d_adaptive_walk_forward.json`        | MGC daily, adaptive regime                       | 0.14   | OVERFIT         |
| `WF_MGC_1d_adaptive_volume_walk_forward.json` | MGC daily, adaptive + volume                     | --     | OVERFIT         |
| `WF_SPY_1h_walk_forward.json`                 | SPY hourly, static params                        | -1.11  | DEEPLY OVERFIT  |
| `WF_SPY_1h_adaptive_walk_forward.json`        | SPY hourly, adaptive regime                      | -0.71  | OVERFIT         |

---

### Historical / Reference Files (Do Not Modify -- Audit Trail)

These files are kept for audit purposes. They document the research process
and should not be edited.

- `engine/backtest/results/WF_*.json` -- all 12 walk-forward run results
- `engine/backtest/results/optimizer_*.json` -- all optimization result files
- `engine/backtest/results/EXECUTIVE_BRIEFING.md` -- version history in document
- `jarvis-trader-skill-project-log.md` -- session-by-session development log
- `engine/CHANGELOG.md` -- version history (v1.0.0 through v1.5.0)
- `engine/docs/BACKTEST_RESEARCH_REPORT.md` -- 1,245-line research report

---

### Files to Be Created (Pending)

| File                                  | Section Reference | Priority |
|---------------------------------------|-------------------|----------|
| `engine/options/__init__.py`          | 1.15              | P3       |
| `engine/options/greeks_monitor.py`    | 1.15              | P3       |
| `engine/options/strategy_executor.py` | 1.15              | P3       |
| `engine/options/chain_fetcher.py`     | 1.15              | P3       |
| `engine/options/premium_calculator.py`| 1.15              | P3       |
| `engine/options/position_manager.py`  | 1.15              | P3       |
| `engine/options/iv_rank.py`           | 1.15              | P3       |
| `engine/options/roll_manager.py`      | 1.15              | P3       |
| `engine/options/event_scanner.py`     | 1.15              | P3       |
| `dashboard/app/command-center/page.tsx` | 1.19            | P2       |
| `dashboard/app/options/page.tsx`      | 1.15              | P3       |
| `dashboard/app/options/chain/page.tsx`| 1.15              | P3       |

---

### Quick Command Reference

```bash
# ── Engine ──────────────────────────────────────────────────────────────
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine

# Start engine
.venv/Scripts/python -m uvicorn main:app --reload --port 8010

# Run single backtest
.venv/Scripts/python -m backtest.run_backtest --symbol MNQ --interval 1h

# Run optimizer
.venv/Scripts/python -m backtest.optimizer --symbol MNQ --interval 1h

# Run walk-forward
.venv/Scripts/python -m backtest.walk_forward --symbol MNQ --interval 1h

# Run walk-forward with adaptive regime
.venv/Scripts/python -m backtest.walk_forward --symbol MNQ --interval 1h --adaptive-regime

# Run Monte Carlo on a result file
.venv/Scripts/python -m backtest.monte_carlo --result backtest/results/some_result.json

# Run full 12-matrix
.venv/Scripts/python -m backtest.run_all_backtests

# Init database
.venv/Scripts/python init_db.py
.venv/Scripts/python init_db.py --reset  # destructive

# Run tests
.venv/Scripts/python -m pytest tests/ --noconftest -v

# Smoke test (48 endpoints)
.venv/Scripts/python scripts/smoke_test.py

# ── Dashboard ───────────────────────────────────────────────────────────
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard
npm run dev          # port 3010
npm run build        # TypeScript check + production build

# ── Windows Startup ─────────────────────────────────────────────────────
# Double-click:
start_jarvis.bat     # Starts engine + dashboard + DB init
```

---

### Port Reference

| Service          | Port | Protocol | Notes                              |
|------------------|------|----------|------------------------------------|
| JARVIS Engine    | 8010 | HTTP     | FastAPI, ~95 endpoints             |
| Dashboard        | 3010 | HTTP     | Next.js 15, dev server             |
| IB Gateway Paper | 4002 | TCP      | TWS paper trading (when running)   |
| IB Gateway Live  | 4001 | TCP      | BLOCKED by default -- Tier 3 only  |

---

### Environment Variables Required

Defined in `engine/.env` (never committed). Template at `engine/.env.example`.

| Variable               | Required | Description                          |
|------------------------|----------|--------------------------------------|
| `ANTHROPIC_API_KEY`    | Yes      | Claude API for debate agents         |
| `TWILIO_ACCOUNT_SID`   | Yes      | WhatsApp alerts                      |
| `TWILIO_AUTH_TOKEN`     | Yes      | WhatsApp alerts                      |
| `TWILIO_WHATSAPP_FROM`  | Yes      | WhatsApp sender number              |
| `WHATSAPP_TO`          | Yes      | Matt's WhatsApp number               |
| `POLYGON_API_KEY`      | Optional | Market data (fallback to yfinance)   |
| `FRED_API_KEY`         | Optional | Macro data (fallback to cached)      |
| `FINNHUB_API_KEY`      | Optional | News data (free tier)                |

---

*End of JARVIS_TRADER_MASTER_PART4.md -- Sections 1.15 through 1.20*
*Version 3.0 | 2026-03-30 | Part 4 of 4*
