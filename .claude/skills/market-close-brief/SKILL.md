---
name: market-close-brief
description: Generate a Corey-style pre-close read for ES + NQ, roughly 1 hour before the CME RTH close (15:00 CT / 16:00 ET), framing where today's session balance sits and what acceptance vs rejection at the close means for tomorrow. This is a same-day companion to market-framing-brief, not a replacement for it — it reads today's realized intraday action and the morning brief's stated levels, it does not re-derive a fresh forecast. Use when the user says "pre-close brief", "1pm read", "how's today setting up into the close", "acceptance or rejection today", "afternoon Corey-style update", or "what should I watch into the close".
---

# When to use

The user wants a same-day, into-the-close read — the kind a subscription service ("Corey")
posts roughly an hour before the bell — that frames **today's realized session** (not
tomorrow's forecast) against the levels the morning framing brief already stated.

This skill does NOT trade, place orders, or modify code. It produces a written brief. The
order-placing path is the engine pipeline + human approval, never this brief.

## Relationship to market-framing-brief — read this first

`market-framing-brief` (the AM skill) produces the structural levels and scenario map for
the *next* session, before the open. This skill runs the *same trading day*, ~1 hour before
the close, and does a fundamentally different job: it looks at how today actually traded
against those AM levels and asks whether the close will read as acceptance or rejection.

**Frame relative to the morning brief — don't re-litigate it.** If a morning framing brief
exists for today, treat its Structural Levels / Scenario Map as the reference frame this
brief is checking today's action against, not a starting point to redo from scratch. If none
exists (or is unusable), say so in the Caveats line and lean more heavily on today's own
session range and Corey's own pre-close commentary.

# Inputs

- **Instruments**: ES + NQ (same as the AM brief). MES is the tradeable micro.
- **Target session**: today — the currently-open RTH session, roughly 1 hour before its close.
- **Today's realized action**: session open/high/low so far, current price, and — where
  computable — a value area (VAH/VAL/POC) for today's session. This is genuinely new data
  the AM brief never has, since it runs before today's tape exists.
- **Corey's own pre-close commentary**, if ingested for today after midday — his stated
  balance/value-area read and his Buyers'/Sellers' Playbook framing, when available.
- **This morning's framing brief**, if one was generated for today, as the reference frame.

# Workflow

## Step 0 — Fix the clock (same discipline as the AM skill)

Confirm the current CT time and that the RTH session is still open (not yet 15:00 CT). This
brief is meaningless once the session has already closed — if invoked after the close, say
so explicitly rather than producing a stale "into the close" read.

## Step 1 — Pull today's realized session data (new capability vs. the AM skill)

The AM skill's level sources (`/levels/{symbol}`, `compute_levels.py`) are deliberately
pre-open-shaped and exclude today's forming session — they are not usable here. Instead:

- `/prices/snapshot` for the live current price, prev-close, and pct-change per symbol.
- Today-only bars (1h or intraday) to derive session open/high/low and a value area — where
  is the bulk of today's volume/time sitting, is it forming near the highs, lows, or
  mid-range.
- Corey's own pre-close commentary if it has posted for today (his raw text is the highest-
  confidence source for "where does he say the value area is forming" — prefer it over a
  DB-derived value area when both are present and don't quietly pick whichever is more
  convenient).

## Step 2 — Reconcile against the morning brief

If a framing brief exists for today, name the levels it flagged as the session's decision
shelf and state plainly whether today's realized range confirmed, extended, or invalidated
that read. This reconciliation is the brief's actual value-add over just restating today's
range — a pre-close read that ignores the morning's stated thesis is not doing its job.

## Step 3 — Write the brief (use the template below verbatim in structure)

# Output template

```
📢 **Pre-Close Update — <weekday>, <date> (~1hr to CME RTH close)**
**Level confidence:** <HIGHEST (Corey pre-close commentary) | HIGH (engine/DB intraday) | LOW (unavailable)>
**Session range so far:** $ES ~<low>–<high> | $NQ ~<low>–<high>

⚖️ **Balance / Value Area**
<2–3 short paras: where roughly is today's value area forming (ES / NQ), is it building
near the highs/lows/mid-range, and how does that compare to this morning's framing brief's
structural levels — confirming, extending, or invalidating that read.>

🎯 **Acceptance vs Rejection at the Close**
Intraday movement = noise, closing price = information. <1–2 paras: what does acceptance
vs rejection at today's key shelf mean for how the session prints, independent of the
intraday chop already seen.>

🎲 **Game Theory Cues**
- **Buyers' Playbook:** <what buyers need to do into the close to signal acceptance higher>
- **Sellers' Playbook:** <what sellers need to do into the close to signal continued distribution>
- **Behavioral Cue:** <the tell — who's trapped, who's offside, heading into the print>

📊 **Key Levels**
### $ES
Resistance: <levels, nearest first>
Support: <levels, nearest first>
Critical levels: <the one/two levels whose close-acceptance changes the read>
### $NQ
Resistance / Support / Critical levels (note which index is leading)

> "<one-line thesis for how today should print>"

**Caveats:** (1) this is a pre-close read, not a forecast — it does not replace or override
the morning framing brief's scenario map, it updates it against today's realized action; if
no morning brief exists for today, say so here. (2) level source = <Corey pre-close
commentary | engine/DB intraday snapshot>; if DB-only, session range reflects only bars
ingested as of generation time, not necessarily the literal tick-by-tick high/low. (3) <any
pending catalyst before the close>.

Sources: <what was used>
```

# Bias rules

- **AMT gives levels, catalysts give direction** — same rule as the AM skill. Never set the
  directional lean from structure alone.
- **Acceptance, not touch.** A level is "reclaimed/lost" only on acceptance (hold/build into
  the close), not an intraday wick.
- **Long-only system bias.** The MES edge is long-only; downside scenarios are spectator-only,
  never a short recommendation.
- **Frame relative to the morning brief, don't re-litigate it.** This brief's job is to check
  today's realized action against the AM read, not produce an independent fresh forecast —
  see Step 2.
- **Never invent a session-range number.** If today's high/low/value-area can't be pulled
  from a real source, say "not retrieved" rather than estimating from the current price alone.

# Hard rules

- **Corey's own pre-close commentary outranks a DB-derived value area** when both are
  available for today — same source-priority discipline as the AM skill.
- **Never fabricate a level.** Every level in Key Levels must trace to a real source
  (today's actual bars, `/prices/snapshot`, or Corey's stated commentary) — never a guess.
- **Always fix the clock (Step 0) first.** A "pre-close" brief generated after the close is
  worse than no brief — say so explicitly rather than presenting stale framing as current.
- **Never recommend live trading.** Paper only; `REQUIRE_HUMAN_APPROVAL=True`; the brief is
  a plan to approve, not an order.
- **This is a companion to the morning framing brief, not a substitute.** Do not restate a
  fresh structural forecast for tomorrow here — that remains the AM skill's job.

# Failure modes (anticipated — same family as the AM skill's, adapted)

1. **Cash/estimate-anchoring today's range.** Deriving "today's high/low" from a single
   current-price snapshot instead of actual intraday bars would silently invent a session
   range. Fix: Step 1 pulls real today-only bars, never a single point estimate.
2. **Ignoring the morning brief entirely.** A pre-close read that doesn't reconcile against
   today's AM framing brief is just restating the tape — it skips the brief's actual purpose.
   Fix: Step 2 is not optional.
3. **Running after the close.** Producing an "into the close" framing once the session has
   already settled misrepresents the brief's own premise. Fix: Step 0's clock check.
