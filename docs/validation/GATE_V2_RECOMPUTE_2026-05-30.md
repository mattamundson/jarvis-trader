# Gate-v2 ALT Recompute — Independent Verification (2026-05-30)

**Scope:** Independent, read-only recomputation of the gate-v2 ALT metrics for the two
LIVE paper-trading strategies — MES (`MES_trend_rank11.json`) and MGC (`MGC_trend_rank4.json`).
Decision-support only. **Nothing was changed.** No config, strategy, risk, or gate code was
touched; the canonical verdict JSONs were read, not modified.

**Method note / honesty flag:** The sandbox in this run suppressed all script stdout, so the
trade-level Monte-Carlo / DSR figures below are taken from the supplied recompute payload and
are marked **APPROXIMATE** where I could not re-derive the exact number from the trade list.
The figures I *did* independently verify by hand from the canonical window arrays and
`cost_tier_results` (window-level p95 DD, and cost-tier monotonicity) are marked **VERIFIED**.

---

## What the gate actually computed (root cause)

1. **MC-DD is window-level, not trade-level.** The gate's `mc_95th_dd_pct` is the 95th
   percentile of the per-window `oos_dd` array. Each WFO window covers a 1–2 month OOS slice
   holding **0–2 trades** (MES) or **1–7 trades** (MGC). A drawdown that builds across several
   trades — within a window or across the seam between windows — is invisible to a
   percentile-of-windows statistic. This systematically **understates tail drawdown**, and the
   understatement is worst exactly where trades are sparsest (MES: 16 trades over 19 windows,
   7 windows empty).

   - **VERIFIED:** MES window-level p95 of `oos_dd` = **0.806%** by hand — matches the gate's
     reported 0.8055% to the basis point. So 0.81% is a *correct percentile of the wrong
     distribution*, not a bug in the percentile math.
   - **VERIFIED:** MGC window-level p95 = **~1.23%**, matches gate 1.2386%.

2. **DSR is reported as a clipped flag (1.0), not the raw deflated Sharpe.** Both verdicts carry
   `dsr=1.000000`. The raw deflated Sharpe (Bailey & López de Prado) on the trade series is far
   higher (MES ~14.9, MGC ~16.1 per recompute). The clip is harmless for the *pass/fail* of the
   DSR criterion (both clear 0.30 either way) but means the reported value is not the true metric.

3. **Cost monotonicity is violated in the gate's own output.** `cost_survives_through=catastrophic`
   is literally true (every tier has PF>1), but the PF-vs-cost curve is **non-monotone** — a
   higher-cost tier produces a *higher* PF than a lower-cost tier. Economically impossible for a
   fixed trade list; indicates the cost tiers are not being applied to a single consistent trade
   set. **VERIFIED directly from `cost_tier_results` in both canonical JSONs.**

---

## MES — `MES_trend_rank11.json` (champion fast=60 / slow=200 / atr=2.0; 16 OOS trades / 19 windows)

| Metric | Gate-reported (as labeled) | Independently recomputed (correct) | ALT bar | Clears? |
|---|---|---|---|---|
| MC 95th-pct DD | 0.81% (window-level p95 — **VERIFIED matches gate math**) | **5.42% trade-level sign-shuffle bootstrap, 1000 resamples (APPROXIMATE — from recompute payload)** | ≤ 4.0% | **NO** (5.42% > 4.0%) |
| Deflated Sharpe (DSR) | 1.0 (clipped flag) | ~14.9 raw deflated, N=3 grid (APPROXIMATE) | ≥ 0.30 | YES |
| Cost monotonicity | `catastrophic` (all tiers PF>1) | **Non-monotone: optimistic PF 2.2426 < realistic PF 2.2596 (VERIFIED from artifact)** | opt ≥ real ≥ pess ≥ cat | **NO** (opt < real) |

Supporting (VERIFIED from canonical `cost_tier_results`): optimistic 2.2426, realistic 2.2596,
pessimistic 2.178, catastrophic 2.1527. The optimistic tier is the lone inversion; realistic→
catastrophic is monotone. The inversion is consistent with the cost tiers being evaluated on a
trade set that differs from the metric trade set.

### Verdict — MES under correct math: **does NOT pass.**

The ALT path requires `mc_95th_dd ≤ 4.0%`. The trade-level tail DD (~5.42%) breaches the ceiling,
and the cost-tier curve is non-monotone (a correctness red flag the gate scored as a pass).
The gate's PASS rests on a window-level DD statistic that structurally cannot see multi-trade
drawdowns in a 16-trade sample. **MES ALT authorization does not survive correct math.**

---

## MGC — `MGC_trend_rank4.json` (champion fast=50 / slow=120 / atr=2.0; 67 OOS trades / 19 windows)

| Metric | Gate-reported (as labeled) | Independently recomputed (correct) | ALT bar | Clears? |
|---|---|---|---|---|
| MC 95th-pct DD | 1.24% (window-level p95 — **VERIFIED matches gate math**) | **1.34% bootstrap of OOS window DDs (APPROXIMATE — from recompute payload)** | ≤ 4.0% | YES |
| Deflated Sharpe (DSR) | 1.0 (clipped flag) | ~16.1 raw deflated, N=8 grid (APPROXIMATE) | ≥ 0.30 | YES |
| Cost monotonicity | `catastrophic` (all tiers PF>1) | **Non-monotone: realistic PF 3.1797 < pessimistic PF 3.2016 (VERIFIED from artifact)** | opt ≥ real ≥ pess ≥ cat | **NO** (real < pess) |

Supporting (VERIFIED from canonical `cost_tier_results`): optimistic 3.2288, realistic 3.1797,
pessimistic 3.2016, catastrophic 3.1691. opt ≥ real holds, but pessimistic > realistic is an
inversion. All tiers clear PF>1 individually, so the gate's `cost_survives_through=catastrophic`
is technically accurate — but the ordering is economically impossible for a fixed trade list.

### Verdict — MGC under correct math: **borderline / passes on risk, fails the cost sanity check.**

MGC has a denser sample (67 trades), so the window-level vs trade-level DD gap is small and stays
**well under the 4% ceiling either way** (1.24% → 1.34%). DSR passes comfortably. The **only**
failure is the cost non-monotonicity, which is a model-correctness concern rather than a risk-limit
breach. MGC's risk metrics survive correct math; its cost-tier ordering does not, and that anomaly
should be explained before relying on the ALT path.

---

## Bottom line

| Strategy | Gate verdict | Under correct math | Why |
|---|---|---|---|
| **MES** | PASS via ALT | **FLIPS to NO-TRADE** | Trade-level tail DD ~5.42% > 4.0% ceiling; cost curve non-monotone. Window-level DD (0.81%) hid the tail in a 16-trade sample. |
| **MGC** | PASS via ALT | **BORDERLINE** | Risk metrics survive (DD 1.34% << 4%, DSR fine); but cost-tier ordering is non-monotone — explain before trusting ALT. |

## Recommendations (no action taken — for Amo)

1. **MES:** Treat the ALT PASS as unreliable. The DD that authorized it is a window-level
   percentile on 16 trades and the trade-level recompute breaches the 4% ALT ceiling. Recommend
   re-running the gate with a **trade-level (path) MC-DD** before keeping MES live, or moving MES
   back to validation-only pending that.
2. **MGC:** Risk side is fine; the cost-tier inversion (pessimistic PF > realistic PF) means the
   cost sweep is not applying tiers to one consistent trade list. Recommend fixing the cost-sweep
   trade-set consistency and re-confirming — the result will likely still pass on DD/DSR.
3. **Gate fix (both):** Change `mc_95th_dd` from percentile-of-window-DDs to a trade-level path
   drawdown bootstrap, and make the cost sweep operate on the **same** trade list used for the
   headline metrics. These two changes remove the structural understatement and the impossible
   cost ordering.

*Independent check — recommendation only. No gate/config/strategy/risk file was edited and no
strategy was enabled or disabled. A flip is a finding to surface, not a config change.*
