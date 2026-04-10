# JARVIS Pre-Market Briefing — 2026-04-08

> Generated: 08:44 ET | Session: Pre-Market | Engine: ONLINE (uptime 28h, paper mode)

---

## DATE AND SESSION

- **Date**: Wednesday, April 8, 2026
- **Current time**: ~08:44 ET — approximately **46 minutes to CME equity open** (9:30 AM ET)
- **MCL (crude)**: Active now — 24h contract, expect heavy early-session volume from overnight gap
- **Scheduled releases today**:
  - **EIA Crude Oil Inventories** — Wednesday release (10:30 AM ET). High impact for MCL.
  - No FOMC blackout in effect (next meeting TBD). Fed speaker risk: low.

---

## MACRO ENVIRONMENT — BULL

| Indicator | Value | Read |
|-----------|-------|------|
| VIX | 20.0 | Moderate — elevated but not panic |
| Fed Funds | 4.33% | Neutral, no change expected near-term |
| 10Y Yield | 4.30% | Slightly below fed funds — flat curve |
| Unemployment | 4.1% | Healthy labor market |

**Macro read: BULLISH RISK-ON** driven by geopolitical relief, not fundamentals.
The ceasefire trade is in full force. Yields edging lower signals bonds are catching a bid alongside equities — classic risk-on but with safe-haven hedging still present. VIX at 20 means vol is coming in but not collapsed — the market is not pricing a durable peace.

---

## TOP HEADLINES

- **US-Iran 2-Week Ceasefire**: Trump suspended attacks against Iran for two weeks, sparking the largest single-day risk rally in months. Dow futures +1,300 pts, S&P +2.7%, Nasdaq +3.4% pre-market. *(CNBC, Al Jazeera)*
- **Crude Oil -15%**: WTI tumbled to ~$95.75/bbl, Brent to ~$94.40 — one of the sharpest single-day crude drops in years. Strait of Hormuz closure risk repriced sharply lower. *(CNN Business)*
- **EIA Inventory Report Due Today**: Weekly crude inventory data (10:30 AM ET). Expectations uncertain — a large build could amplify the sell-off in MCL; a draw would be counterintuitive given the ceasefire narrative.
- **Delta Air Lines Q1 Beat**: Airlines (UAL, LUV, DAL) surging double digits. Cruise lines (CCL, RCL) also rallying on falling fuel costs. *(Bloomberg)*
- **European DAX +4.8%**: Global risk rally broad-based. All sectors green except energy. *(CNBC)*

---

## MCL POSTURE — HIGH CAUTION / NO TRADE

**Instrument**: Micro Crude Oil (MCL) | 1h | WFE=0.82 | APPROVED

- **Overnight move**: WTI -15% (~$17/barrel). MCL point value = $100/pt → this is a $1,700+ move on a single contract. Extreme.
- **Regime**: Unknown — technical analysis endpoint returning 500 error (data feed likely overwhelmed by gap). Cannot confirm regime classification.
- **STC status**: Not available (endpoint failure). At -15% gap, STC is almost certainly in deep oversold territory or has reset. Entry signal reliability is low in immediate aftermath of a gap of this magnitude.
- **Signal direction**: No valid signal — pipeline last ran 2026-04-07 15:30 on a different symbol. No MCL signal generated.
- **Posture: OBSERVE ONLY.** Wait for STC to stabilize (minimum 2-3 bars post-gap). Do not enter on the first hour of the gap down. Watch for EIA print at 10:30 ET — if bullish for oil (draw), a partial reversal could form. If bearish (build), the leg lower continues.

---

## MNQ POSTURE — WATCH FOR PULLBACK ENTRY

**Instrument**: Micro Nasdaq-100 (MNQ) | 1h | WFE=0.57 | APPROVED

- **Overnight move**: NQ futures +3.2–3.4% pre-market. Gap-up open likely.
- **Regime**: Unknown — same endpoint failure as MCL. Macro context strongly bull.
- **STC status**: Not available. At +3.4% gap-up, STC is likely approaching or at overbought (OS=83 threshold). Chasing the open is against the strategy rules.
- **Signal direction**: No current signal. Last pipeline action = HOLD (AAPL, yesterday). Confidence 25%. Regime tagged as unknown.
- **Posture: WATCH.** Let the gap fill or consolidate. If MNQ pulls back after open and STC resets from overbought toward mid-range (50-65), a long setup per strategy rules may form. Do not buy the open of a 3%+ gap — gap-fade risk is real.

---

## WATCH LIST

1. **EIA at 10:30 ET** — Primary MCL catalyst today. Large build = more downside, could give a shorting setup post-report if STC confirms. Draw = potential reversal long if ceasefire narrative holds.
2. **MNQ first 30 minutes** — Watch for the gap-fill or continuation. If NQ opens +3% and immediately continues higher with no pullback, regime is strongly bullish and MNQ may set up on a 1h pullback. If it reverses immediately, wait for new structure.
3. **Technical endpoint recovery** — `/analyze/technical` returning HTTP 500 (request_id: b6f02044, 2a1898b4). Likely a market data timeout on the massive crude gap. Monitor for recovery — JARVIS is partially blind without live STC values.

---

## RISK NOTE

**Elevated risk session. Recommend observation-only.**

- **Gap volatility**: Both MCL (-15%) and MNQ (+3.4%) have gapped to extremes. Opening range will be volatile. Strategy STC signals require settled price action to be reliable.
- **Ceasefire is temporary**: 2-week deal, not permanent. Reversion risk is high if negotiations collapse. Do not hold overnight positions in MCL expecting the move to extend.
- **Engine blind spot**: `/analyze/technical` endpoint is down. No live STC or ATR stop data available from JARVIS. Do not enter without manual confirmation of signal.
- **Daily P&L**: +$130 (26% of $500 target). System not halted. Kill switch inactive.

---

*JARVIS TRADER | Paper Mode | LIVE_TRADING_ENABLED=False | No positions open*
*Sources: CNBC, CNN Business, Al Jazeera, Bloomberg, Washington Times, engine API*
