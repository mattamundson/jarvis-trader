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

## Step 1 — Pull FUTURES levels first, directly (WebSearch / WebFetch)

The single biggest accuracy failure (see Failure Modes) is anchoring a futures
brief on cash. **The brief is about ES/NQ futures — pull futures levels
directly and make them the anchor. Cash and MAs are secondary context, never
the level anchor.** Fetch, and cite, in this order:

1. **Front-month ES + NQ futures, native levels** — current/overnight price,
   the **overnight Globex session high and low** (the pre-open reference rails),
   and the prior session's futures range. Sept = `ESU26`/`NQU26` mid-2026; roll
   at quarterly expiry, 3rd Friday. These futures levels ARE the pivots/triggers
   in the brief. Pull them from a futures source (Barchart/CME/TradingView
   futures pages), not by adding a guessed basis to a cash index.
2. **Immediately-prior session — date, direction, magnitude.** State it
   explicitly: "prior session = <weekday date>, <up/down X%>, driver <…>."
   This defuses the aggregator habit of surfacing OLD selloff/rally stories
   (e.g. an early-month −4% day) as if they were the current week. If you can't
   confirm the prior session's *direction*, you do not yet know the setup — keep
   searching before writing context.
3. **Last completed session result** — % change/close for S&P 500 + Nasdaq and
   the day's catalyst (search `"stock market today <weekday> <date>"`).
4. **Moving averages**: 50-day and 200-day on S&P 500 (cash) — regime context
   only, and remember they are CASH levels (convert to the futures frame before
   citing any of them as a level).
5. **VIX** (regime: <20 calm, 20–28 elevated, >28 stress).
6. **Recent range**: multi-week futures high and low (the magnets).
7. **Econ calendar for the target session** — any release 07:30–10:00 CT governs
   the open. Flag month/quarter-end and holiday-shortened weeks (thin liquidity).

## Step 2 — Level integrity (cross-check before publishing any level)

- **Every tradeable level (pivot, trigger, support, resistance) must come from a
  futures source.** Never present a cash level — or cash + an assumed basis — as
  a futures level. A basis-bridged number is a guess, not a level.
- **Two-source cross-check.** Confirm each anchor level against a second source
  before publishing. If two sources disagree by more than a few points, say so
  and give the range, not a false-precise single tick.
- **No fabricated bridge numbers — for ANY instrument.** If you cannot pull a
  real futures level for ES *or* NQ, mark it "not retrieved" and do not invent a
  derived one. (Origin incident: NQ was correctly marked "not retrieved" while ES
  got an invented "cash + ~40 basis" number that landed ~40–90 pts below the real
  futures tape — the whole map was wrong. Honesty-flagging one instrument does not
  license guessing the other.)

## Step 2b — Declare the artifact type

State at the top whether this is a **pre-open forecast** (no tape yet — levels
come from the overnight session) or an **at/post-open reaction** (the opening
move has happened and is being framed forward). They are different products: a
post-open note can cite precise live levels a pre-open forecast cannot. Do not
compare two briefs, or grade one, without matching their type.

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

**Caveats:** (1) artifact type = <pre-open forecast | at/post-open reaction>. (2) levels are native futures from <source(s)>; web quotes are delayed — IB feed is truth. (3) <econ release / holiday note>.

Sources: <markdown links to every source used>
```

# Bias rules (apply mechanically — do not freelance direction)

- **AMT gives levels, catalysts give direction.** Never set the directional lean from structure alone. A structural "downtrend" that is +5% above the 200-day is a *pullback*, not a downtrend — say so.
- **Acceptance, not touch.** A level is "reclaimed/lost" only on acceptance (hold/build), not a wick. Until then the bias is a *claim, not a fact*.
- **Long-only system bias.** The MES edge is SMA(50,200)+2.0×ATR, long-only. The overlay never recommends a short — downside scenarios are spectator-only.
- **Catalyst overrides structure.** If a release or headline (Fed, jobs, geopolitics) is pending, name it and subordinate the structural read to it. This is the lesson from the origin note, which missed a de-escalation rally by reading structure over catalyst.
- **Conviction scales with confirmation + catalyst alignment.** One-day relief pops into resistance on thin (quarter-end / holiday) liquidity = low conviction, "respect the trap," even if direction looks right.

# Hard rules

- **Anchor on futures, not cash.** Levels come from native ES/NQ futures (Step 1). Never anchor on a cash index or cash+basis. This is the #1 historical failure.
- **Never fabricate a level — for any instrument.** Every price comes from a fetched futures source or the engine. If you can't fetch it, say "not retrieved" — do not invent, and do not bridge from cash with an assumed basis.
- **Verify the prior session's direction before writing context.** Don't let an aggregator's old selloff/rally story set the setup. State prior session date + direction explicitly.
- **Always fix the clock (Step 0) before pulling data.** A stale-session brief is worse than no brief.
- **Declare artifact type.** Pre-open forecast vs at/post-open reaction — state it; don't grade across types.
- **Never recommend live trading.** Paper only; `REQUIRE_HUMAN_APPROVAL=True`; the brief is a plan to approve, not an order.
- **Process hygiene ≠ accuracy.** Sources, look-ahead discipline, and uncertainty flags do not make a wrong level right. Verify the inputs, not just the method.
- **Size to the daily halt.** Default 1 micro on the trigger — a 2.0×ATR stop on 2 micros can trip the −2% daily halt by itself (~$200 on a ~$10K account).
- **Grade third-party notes honestly.** If a note is supplied, split the verdict: levels vs directional bias vs process. Praise good rails; call a wrong directional call wrong — and check your own levels against the same tape before judging theirs.

# Failure modes (learned — do not repeat)

These come from real misses building this skill's briefs. Each maps to a rule above.

1. **Cash-anchoring (worst).** A Friday brief anchored on S&P cash (7,357) + a guessed +40 basis put ES at "~7,400" with resistance at 7,420; the real futures tape was 7,437–7,489 with the pivot at 7,489. Levels were ~40–90 pts too low and the directional frame ("at the 50-day, post-selloff") was inverted from the actual "post-rally retrace." Fix: Step 1 pulls futures directly.
2. **Invented bridge number.** Same brief marked NQ "not retrieved" (correct) but fabricated the ES level from cash. Fix: the no-fabrication rule applies to every instrument.
3. **Stale-week contamination.** Searches surfaced early-month −4% selloff stories and they colored a "momentum-down" frame for a week that had actually rallied. Fix: verify prior-session direction + date explicitly (Step 1.2).
4. **False comfort from rigor.** A five-source, look-ahead-disciplined, uncertainty-flagged brief was *less* accurate than a confident single-feed note, because the inputs were wrong. Fix: process hygiene ≠ accuracy; cross-check levels.
5. **Defending instead of reconciling.** When a third-party note's levels didn't match, the first instinct was "they must be a different session" — wrong. Fix: when levels diverge, check your own against the tape first.

# Example headline (for shape only)

`Cautiously bullish, unconfirmed: ES pinned under 7,475 after Mon +1.2% relief rally on Iran de-escalation; long MES only on acceptance >7,475, NQ>30,030 is the leadership tell, respect the quarter-end/holiday trap.`
