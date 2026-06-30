# Worked example — market-framing-brief output

Illustrative end-to-end run of the skill (Tue 2026-06-30 target session), kept as
a regression reference for the brief's shape and the level-derivation method. The
levels here were **computed** by `compute_levels.py` from prior-session OHLC, not
parroted. This run used the **web-fallback (LOW confidence)** path because the
cloud session could not reach the engine; the ES input range was abnormally
narrow, so the ES ladder is flagged illustrative. On a machine with the engine
up, Step 1a (`/levels`) supplies the authoritative ladder and confidence is HIGH.

Method-validation note: computed levels independently reproduced a professional
note's hand-drawn levels with no knowledge of that note —
ES S2 7,421.83 ≈ their 7,421 anchor; ES R3 7,485.92 ≈ their 7,489 pivot;
NQ S1 29,566 ≈ their 29,570 trigger.

---

📢 **Morning Framing — Tuesday, June 30, 2026**
**Level confidence:** LOW (web fallback — engine unreachable; ES OHLC snapshot narrow)
**Artifact type:** pre-open forecast (late Mon-night CT; target session = Tue 6/30)
**Reference (prior close / overnight):** $ES ~7,444 | $NQ ~29,728

🧭 **Overview.** Tuesday opens the morning after a strong risk-on session — Monday
+1.18% (S&P 7,440), Nasdaq +2%, on US–Iran de-escalation. Price is back above the
50-day; the intermediate uptrend that wobbled last week is repairing. But it is
month/quarter-end into a holiday-shortened week — rebalancing flows and thin
liquidity, so respect chop. Both indices sit below their computed pivots
(ES 7,448 / NQ 29,655) on the overnight reference — a mild give-back, not a reversal.

📚 **AMT — "Post-rally retrace, acceptance test."** Monday was the expansion leg;
the overnight pullback probes whether buyers defend. Decision shelves:
ES 7,448 pivot / 7,422 anchor, NQ 29,655 pivot / 29,566 trigger.

🎲 **Game theory.** Late-Monday longs are vulnerable on a give-back; trapped shorts
from last week defend the upside. Quarter-end flows are the wildcard referee.

📊 **Structural Levels (computed — compute_levels.py, floor pivots + rails)**

**$ES** *(illustrative — narrow input)*
- Resistance: 7,459 (R1) · 7,475 (R2) · 7,486 (R3 ≈ pro-note 7,489 pivot)
- Pivot 7,448
- Support: 7,433 (S1 ≈ pro-note 7,438 trigger) · 7,422 (S2 ≈ pro-note 7,421 anchor) · 7,406 (S3)

**$NQ** *(cleaner input)*
- Resistance: 29,817 (R1) · 29,906 (R2) · 30,067 (R3)
- Pivot 29,655 · prior-value 29,619
- Support: 29,566 (S1 ≈ pro-note 29,570 trigger) · 29,405 (S2) · 29,316 (S3)

🧠 **Why ES 7,448 / NQ 29,655 matter.** These pivots split the session: hold above
→ Monday's repair extends toward R1/R2; lose them and accept below → give-back
deepens to S1/S2 (ES 7,422, NQ 29,566), where buyers must show to keep the rally
valid. NQ leads — it is the tell.

📊 **Scenario Map**
1. Hold pivots → continuation: ES reclaims 7,448 → 7,459/7,475; NQ holds 29,655 → 29,817.
2. Lose pivots → retrace: ES accepts < 7,448 → 7,433 → 7,422; NQ < 29,655 → 29,566.
3. Quarter-end chop: two-way through pivots, no acceptance — stand aside.

📌 **Final Thoughts + System Overlay (MES).** Lean: cautiously constructive, but
below pivot at the open = wait for reclaim. The MES system
(SMA(50,200)+2.0×ATR, long-only) wants acceptance back above the ES pivot/R1 zone
(~7,448–7,459) before a long; flat below, cannot short. One authorized trade:
long MES on acceptance > ~7,459, stop under 7,422 (~$185/micro at $5/pt), targets
7,475 → 7,486. 1 micro (−2% halt ≈ $200). Human approval + safety layer
non-negotiable. Leadership tell: if NQ can't hold 29,566, skip the ES long.

> "Monday proved the buyers; the overnight give-back tests whether they meant it.
> Reclaim the pivot or stand aside."

**Caveats:** (1) pre-open forecast. (2) Level confidence LOW — web fallback, ES
input range abnormally narrow; engine /levels would supply the authoritative
ladder and flip this to HIGH. (3) month/quarter-end + holiday-thin liquidity
amplifies whipsaw.
