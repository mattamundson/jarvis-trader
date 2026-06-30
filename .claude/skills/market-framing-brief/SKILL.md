---
name: market-framing-brief
description: Generate a Corey-style Auction Market Theory morning framing brief for ES + NQ (and the MES system overlay) for the next trading session, grounded in live web data. Use when the user says "framing for tomorrow", "morning brief for ES/NQ", "what's the setup for tomorrow", "create a market framing", "structural levels for next session", "do a Corey-style brief", "ES/NQ levels and scenarios", or "what should I watch at the open". Produces a fixed-structure brief: Overview, AMT cues, Game Theory, Structural Levels, Why-levels-matter, Scenario Map, Final Thoughts + System Overlay.
---

# When to use

The user wants a discretionary, levels-and-scenarios market read for the **next** trading session — the kind a subscription service ("Corey") posts as a morning update — but grounded in real data and reconciled with this system's actual MES strategy and safety discipline.

This skill does NOT trade, place orders, or modify code. It produces a written brief. The order-placing path is the engine pipeline + human approval, never this brief.

# Inputs

- **Instruments**: default ES + NQ (the two index futures Corey covers). MES is the tradeable micro the system overlay sizes.
- **Target session**: default = the next trading session after the most recently completed RTH close. The user may override ("for Thursday").
- **Optional**: a pasted third-party note (e.g. Corey's) to grade against — if supplied, add a "Verdict on the prior note" section.

# Workflow (do these in order — order matters)

## Step 0 — Fix the clock FIRST (non-negotiable)

The single biggest failure mode is planning "tomorrow" off stale data because of a timezone mismatch. The system clock is UTC; the trader is **CT**. Before pulling any data, establish:

- What is the current CT time and date? (UTC clock at/after 00:00 UTC = already "tomorrow" in UTC while still last-night in CT.)
- What is the **most recently completed RTH session**? (CME equity-index RTH closes 15:00 CT / 16:00 ET.)
- Is Globex currently open? (Reopens 17:00 CT Sun–Fri; the overnight tape feeds the target session.)
- Therefore: which calendar day is the **target session**, and what is the last *closed* session whose OHLC anchors the levels?

State this explicitly at the top of the brief. Do not skip it. Prior incident (this skill's origin): a brief was built treating Friday's close as current when Monday's session had already closed +1.2% — the entire bias was stale.

## Step 1 — Pull live data (WebSearch / WebFetch)

Fetch, and cite, each of these:

1. **Last completed session result** — % change and close for S&P 500 and Nasdaq, plus the day's driver/catalyst (search `"stock market today <weekday> <date>"`).
2. **Current / overnight ES + NQ** front-month futures level (Sept = `ESU26`/`NQU26` mid-2026; roll at quarterly expiry, 3rd Friday).
3. **Moving averages**: 50-day and 200-day on the S&P 500 (cash). These are the regime lines.
4. **VIX** level (regime context: <20 calm/orderly, 20–28 elevated, >28 stress).
5. **Recent range**: multi-week high and low (the magnets).
6. **Econ calendar for the target session** — any release in the 07:30–10:00 CT window governs the open. Also flag month/quarter-end and holiday-shortened weeks (thin liquidity → amplified whipsaw).

## Step 2 — Reconcile cash vs futures basis

MA levels come from **cash** (e.g. SPX 50-day). Corey's and the tradeable levels are **futures**, which trade at a premium (cost of carry − dividends; tens of points on ES at mid-2026 rates). When mapping a cash MA onto a futures level, add the prevailing basis — do not present a cash MA as a futures level. State the approximation.

## Step 3 — Optional system data (only if engine reachable)

If `curl -s http://localhost:8010/health` returns ok, you MAY pull the live MES levels / hourly ATR for an exact (not approximate) stop. If the engine is unreachable (e.g. cloud session), say so and mark the stop as approximate. Never block the brief on the engine.

## Step 4 — Write the brief (use the template below verbatim in structure)

# Output template (fixed structure)

```
📢 **Morning Framing — <target weekday>, <date>**
**Reference Pivots (<last close / overnight>):** $ES ~<level> | $NQ ~<level>

🧭 **Market Overview (Weekly Structure Context)**
<2–4 short paras: where we open, what the higher timeframe says vs the
50/200-day, and what is confirmed vs unconfirmed. Correct any third-party
"downtrend" claim against the actual MA distance.>

📚 **Auction Market Theory Cues**
### "<one-line regime label>"
1. <value migration direction>
2. <unfinished business — above and below>
3. <the single decision shelf and what acceptance/rejection means>

🎲 **Game Theory Dynamics**
1. <trapped/offside participants>
2. <momentum/relief participants>
3. <flows: quarter/month-end, holiday liquidity, gamma if known>

📊 **Structural Levels**
### $ES (<contract>)
Resistance: <4 levels, nearest first>
Support: <4 levels, nearest first>
Bias: <constructive/cautious> above <anchor>; confirmed <dir> only on acceptance above/below <shelf>
### $NQ (<contract>)
Resistance / Support / Bias  (note which index is leading)

🧠 **Why <ES shelf> and <NQ shelf> Matter**
<why these two levels define the session's regime; name the leadership tell>

📊 **Scenario Map**
Scenario 1 — <base case, highest prob>: triggers + targets
Scenario 2 — <chop/trap>: triggers + "stand aside"
Scenario 3 — <lower prob>: triggers + what catalyst it needs

📌 **Final Thoughts + System Overlay (MES)**
- Honest lean: <bias + conviction (low/moderate/high) + the trap to respect>
- One authorized trade: long MES on acceptance > <shelf>, stop under <anchor> (~$<n>/micro), targets <t1> → <t2>
- Size: 1 micro to start (−2% daily halt ≈ $<n> on the account is tighter than a 2-contract 2.0xATR stop)
- No short, no chase in the <anchor>–<shelf> pocket; human approval + safety layer non-negotiable
- Leadership tell: if NQ can't hold <NQ shelf>, skip the ES long

> "<one-line memorable thesis>"

**Caveats:** (1) web quotes are aggregated + delayed with a futures/cash basis — levels solid, exact tick approximate, IB feed is truth. (2) <econ release / holiday note>.

Sources: <markdown links to every source used>
```

# Bias rules (apply mechanically — do not freelance direction)

- **AMT gives levels, catalysts give direction.** Never set the directional lean from structure alone. A structural "downtrend" that is +5% above the 200-day is a *pullback*, not a downtrend — say so.
- **Acceptance, not touch.** A level is "reclaimed/lost" only on acceptance (hold/build), not a wick. Until then the bias is a *claim, not a fact*.
- **Long-only system bias.** The MES edge is SMA(50,200)+2.0×ATR, long-only. The overlay never recommends a short — downside scenarios are spectator-only.
- **Catalyst overrides structure.** If a release or headline (Fed, jobs, geopolitics) is pending, name it and subordinate the structural read to it. This is the lesson from the origin note, which missed a de-escalation rally by reading structure over catalyst.
- **Conviction scales with confirmation + catalyst alignment.** One-day relief pops into resistance on thin (quarter-end / holiday) liquidity = low conviction, "respect the trap," even if direction looks right.

# Hard rules

- **Never fabricate a level.** Every price comes from a fetched source or the engine. If you can't fetch it, say "not retrieved" — do not invent.
- **Always fix the clock (Step 0) before pulling data.** A stale-session brief is worse than no brief.
- **Never recommend live trading.** Paper only; `REQUIRE_HUMAN_APPROVAL=True`; the brief is a plan to approve, not an order.
- **Mark data quality.** Web quotes = approximate tick + basis; IB feed = truth. Say which you used.
- **Size to the daily halt.** Default 1 micro on the trigger — a 2.0×ATR stop on 2 micros can trip the −2% daily halt by itself (~$200 on a ~$10K account).
- **Grade third-party notes honestly.** If a note is supplied, split the verdict: levels vs directional bias vs process. Praise good rails; call a wrong directional call wrong.

# Example headline (for shape only)

`Cautiously bullish, unconfirmed: ES pinned under 7,475 after Mon +1.2% relief rally on Iran de-escalation; long MES only on acceptance >7,475, NQ>30,030 is the leadership tell, respect the quarter-end/holiday trap.`
