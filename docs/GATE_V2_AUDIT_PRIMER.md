# Build Primer — Gate v2 Metric-Integrity Audit & Fix

> Source: `docs/validation/STRATEGY_VALIDATION_2026-05-30.md` (Stark-grade
> strategy-validation-panel, run wf_cbac027e-d88).
> Finding: the live MES/MGC authorization PASSes only via the gate-v2 ALT lane, and
> the adversarial panel claims three ALT metrics are mislabeled or not actually computed.
> If true, every gate verdict — including future ATR variants — is built on sand.
> Purpose: VERIFY each claim against the source FIRST, then fix only what's genuinely broken,
> then re-gate the live book honestly. Decision-support + validation-logic only — no live
> config change, no strategy/risk edit, no engine restart, promote nothing without Amo.

## ⚠️ SUPERSEDED 2026-05-30 (late) — the metric-audit MISLABELED which metric is broken

After reading the **exact certified-verdict runners** (`run_mes_trend_rank11.py:355-374`,
`run_mgc_trend_rank4.py:328-341`) the picture inverted. Trust THIS block over everything below it:

- **REAL defect = `mc_95th_dd` is WINDOW-LEVEL, not trade-level.** Both runners do
  `oos_dds = [r.max_drawdown_pct for r in oos_results]; mc_95th_dd = np.percentile(oos_dds, 95.0)`
  — one DD per WFO window, p95 across ~19 windows. They **never call** the real trade-level
  `bootstrap_max_dd` that exists in `monte_carlo.py:445-472`. For sparse strategies (MES 16 trades /
  19 windows, ~7 empty) this structurally hides multi-trade drawdowns. The recompute estimates MES's
  true trade-level p95 DD ≈ **5.42% > the 4% ALT ceiling → MES likely FLIPS to NO_TRADE** (magnitude
  APPROXIMATE — sandbox suppressed stdout; re-run with output visible to confirm). The metric-audit's
  "claim 1 REFUTED / MC is fine" was WRONG: it read `bootstrap_max_dd` + `scripts/validate_strategy.py`
  (a real trade-level path that these verdicts DO NOT USE).
- **DSR is MIS-SPECIFIED, not a binary fallback.** Both runners call
  `deflated_sharpe_ratio(sharpe=mean(oos_sharpes), n_trials=3or8, n_obs=max(all_trades,30),
  skew=0.0, kurt=3.0)` (MES :366-374, MGC :337-340). Three problems: (a) `sharpe` = arithmetic mean
  of **per-window** Sharpes, which are wildly unstable (a few-trade window yields a giant Sharpe),
  inflating the mean (recompute saw MGC mean_sharpe ≈ 16); (b) `n_obs = max(all_trades, 30)` is
  **floored at 30**, so a 16-trade MES is treated as 30 observations — shrinking σ_SR; (c) `skew/kurt`
  hardcoded Gaussian, discarding the fat tails / negative windows. Result: a genuine `Φ(z)` that rounds
  to `1.0` and auto-passes. **With `skew=0/kurt=3` the variance term `1+0.5·SR²` is ALWAYS > 0, so the
  `deflated_sharpe.py:126-127` degenerate-σ branch NEVER FIRES for these verdicts.** → **The
  line-127 "fix" specified below is a NO-OP for MES/MGC. Do not lead with it.** The real DSR fix is to
  call `deflated_sharpe_from_returns(trade_returns, n_trials=...)` (real skew/kurt, n_obs = trade count).
- **Cost sweep non-monotone: still CONFIRMED** (hand-verified from both verdict JSONs: MES opt 2.2426 <
  real 2.2596; MGC real 3.1797 < pess 3.2016). Re-runs signals per tier instead of re-pricing a fixed
  list. All tiers still PF>1, so not flip-determinative alone.

**Corrected Phase-2 priority:** (1) switch both runners' `mc_95th_dd` to trade-level `bootstrap_max_dd`
on the concatenated OOS trade list; (2) replace the `deflated_sharpe_ratio(mean_window_sharpe, …)` call
with `deflated_sharpe_from_returns(oos_trade_returns, …)`; (3) deterministic fixed-list cost re-pricing;
(4) re-gate MES+MGC, surface flips to Amo (never auto-disable). The `deflated_sharpe.py:127` hardening is
still worth doing defensively but is NOT why these two pass. No live-money risk (paper only,
`LIVE_TRADING_ENABLED=False`). This is a certification-integrity fix.

---

## PHASE 1 — source rulings in, ARTIFACT verification still owed (2026-05-30) — see SUPERSEDED block above

Two passes (workflow `gate-v2-metric-audit` wf_c47b6adc, run in clean subagent contexts +
a partial source read this session) on the *code*. Treat the source rulings below as solid;
**VERIFIED from artifacts (2026-05-30):** both `MES_trend_rank11.json` and `MGC_trend_rank4.json`
carry `gate_v2_metrics.dsr = 1.0` exactly, clearing both core (`>=0.1`) and ALT (`>=0.3`). MGC's
early OOS windows are strongly *negative* (`oos_sharpe = -10.04, -5.87, -1.69`); MES's are `0.0`
(0-trade windows) — a genuine deflated Sharpe of *exactly* 1.0 alongside negative-Sharpe windows is
the tell. **BUT the verdict JSON does NOT persist `sharpe_std_error`**, so you cannot prove the
degenerate-σ fallback fired by reading the artifact — a real `Φ(z)` with `z > ~4.75` also rounds to
`1.000000` (the system *does* emit non-1.0 values: lineage shows `rank7_dsr=0.667`, `rank9_dsr=0.999`).
**The ONLY way to know whether the fallback fired (and thus whether the fix flips the verdict) is to
recompute the DSR on the actual OOS trade list** — which is exactly what `gate-v2-independent-recompute`
(wf_6058cabf-27c) is doing. Treat "both flip" as **[UNVERIFIED until that recompute lands]**. Rulings:

- **Claim 1 — `mc_95th_dd` not a real MC: REFUTED ✅.** `bootstrap_max_dd`
  (`engine/backtest/monte_carlo.py:459-469`) runs a genuine 10,000-iteration permutation:
  `rng.permutation(pnls)` → rebuild equity → max-DD per path → `np.percentile(dds, 95)`. No fix.
- **Claim 2 — `dsr=1.0` is a rubber stamp, not a Deflated Sharpe: CONFIRMED ❌ (the load-bearing defect).**
  `engine/backtest/deflated_sharpe.py:126-127`: `if not np.isfinite(sigma) or sigma == 0: dsr = 0.0 if sharpe <= expected_max else 1.0`.
  **Likely mechanism (inferred — confirm with the recompute + artifacts, NOT yet proven):** σ_SR comes
  from `_sharpe_standard_error` (lines 71-77), which returns `inf` when its non-normal variance term
  `1 − skew·SR + (kurt−1)/4·SR²` goes **≤ 0** (line 75). That term is only negative in a *narrow* band
  (the `−skew·SR` term must dominate `1 + (kurt−1)/4·SR²`), so "few trades" does NOT automatically force
  it — this is the weak link in the diagnosis and must be checked, not assumed. The workflow *reported*
  both verdicts carry `dsr = 1.0` from the fallback; verify by reading `sharpe_std_error` in each verdict
  JSON. IF the fallback fired, the fabricated `1.0` clears BOTH core `dsr>=0.10` and ALT `dsr>=0.30`.
  **If true it is outcome-determinative:** ALT requires 5/5, so a fail-conservative DSR drops both to
  NO_TRADE. (If instead the verdicts show a *finite* σ and a genuinely high DSR, the audit mis-diagnosed
  and the line-127 fix is a real hardening but NOT the reason MES/MGC currently pass — re-scope then.)
- **Claim 3 — cost sweep non-monotonic: PARTIAL ⚠️ (hygiene, not a live-cert defect).** The sweep
  (`engine/scripts/cost_sensitivity_sweep.py:143-159`) DOES re-run signals per cost tier, but the
  **certified** rank11/rank4 artifacts show constant trade count (30 / 50) and monotonic PF decay — it
  did not bite the live authorization. The panel's "WR varies" evidence came from a non-certified rank1.

**[UNVERIFIED — garbled read, confirm first]:** `_compute_max_dd` in `deflated_sharpe.py` appeared to
`return 0.0` unconditionally. The gate's real DD is from `monte_carlo.py` (correct), so this is likely
dead code in this module — but verify before relying on any DD it produces.

### Turnkey fix (Phase 2 — run in a clean /jarvis-trader session; reads were unreliable this session)

1. `deflated_sharpe.py:126-127` — on `not np.isfinite(sigma) or sigma == 0`, set `dsr = 0.0`
   unconditionally (fail-conservative); drop the `else 1.0` branch. The degenerate σ means a deflated
   p-value is uncomputable — never certify on it.
2. Add a `dsr_fallback: bool` (or `degenerate_variance: bool`) key to the returned dict — `True` on the
   two degenerate-return guards (lines 113-122 and 64-73/76-85) and the σ-degenerate branch, `False` on
   the normal z-score path — so a degenerate 1.0/0.0 can never be misread as a real deflation pass by
   `gate_v2_policy`, dashboards, or any future hard-enforcement layer. Surface it in gate reasons.
3. **Test (verifiable goal):** `engine/tests/test_deflated_sharpe.py` **already exists** — EXTEND it,
   don't recreate. Add: an input that drives σ_SR non-finite returns `dsr == 0.0` AND `dsr_fallback is
   True`; a clean finite case still returns the z-score `Φ((SR−E[maxSR])/σ)` unchanged; the two
   `from_returns` guards (T<2, std==0) now also set `dsr_fallback True`. Run via
   `engine/.venv/Scripts/python -m pytest tests/test_deflated_sharpe.py -v`; ruff-clean.
4. **Re-gate** MES (`run_mes_trend_rank11.py`) and MGC (`run_mgc_trend_rank4.py`) through
   `gate_v2_orchestrator`; produce the before/after table. Whether both flip to NO_TRADE depends on the
   recompute result (does the real DSR fall below 0.3?) — do not pre-write the conclusion; let the
   re-gate produce it. The re-gate IS the proof, since it recomputes DSR on the live trade list.
5. `[safety-review]` commit tag; per-file staging; **no push; do NOT touch `paper_config.enabled`** — a
   flip is surfaced to Amo as a Tier-3 decision, never auto-executed. The fail-safe is already NO_TRADE
   on a stale verdict, so nothing live changes until Amo acts.

Empirical cross-check `gate-v2-independent-recompute` (wf_6058cabf-27c) was computing the real DSR value
on the actual trade lists in parallel — its number is the independent confirmation of the flip magnitude.

## How to run (fresh session)

1. `/jarvis-trader`
2. Read this file, then `docs/validation/STRATEGY_VALIDATION_2026-05-30.md`. Summarize the
   three claims before touching anything.
3. Execute the phases in order. **Do not skip Phase 1.** Do not "fix" a claim you have not
   first confirmed against the actual source — a wrong fix on certification logic is worse
   than the bug.

## Context — the three claims to test

From the validation brief, the gate-v2 ALT lane allegedly rests on:
1. **`mc_95th_dd` is NOT a Monte Carlo** — it's `np.percentile([per-OOS-window drawdowns], 95)`,
   an empirical window percentile, not a permutation/shuffle of the trade list. For sparse
   strategies (MES: ~16 OOS trades / 19 windows) this is outlier-dominated and understates DD.
2. **`dsr=1.0` is NOT a Deflated Sharpe Ratio** — it's a binary selection-bias pass-flag
   (`dsr >= 0.30` ALT), so multiple-testing inflation across the param grid (MES N=3, MGC N=8)
   is uncorrected. Overfitting is not actually screened.
3. **The cost sweep is non-monotonic** — PF sometimes *rises* as costs rise, proving the sweep
   re-runs the full signal+execution per tier (mutating the trade list) instead of re-pricing a
   fixed list. `cost_survives_through=catastrophic` is therefore a soft claim, not a hard boundary.

Reliable anchors (confirm, don't assume):
- Repo: `C:\Users\mattm\ThinkorSwim\jarvis-trader`; engine venv: `engine\.venv\Scripts\python.exe`
- Gate v2 source: `engine/backtest/gate_v2_policy.py`, `engine/backtest/verdict_schema.py`,
  `engine/backtest/gate_v2_orchestrator.py` (locate the actual MC/DSR/cost functions)
- Verdict artifacts: `engine/data/gate_v2_verdicts/MES_trend_rank11.json`, `MGC_trend_rank4.json`
- Backtest runners: `backtest/run_mes_trend_rank11.py`, `backtest/run_mgc_trend_rank4.py`
- Gate v2 PASS bar: `pf_ci_lower>=1.10`, `p_edge>=0.95`, `mc_95th_dd<=5%` (`<=7%`/ALT specifics
  per code), `dsr>=0.10` (ALT `>=0.30`). NO_TRADE on missing/stale verdict (fail-safe).

## Phase 1 — VERIFY each claim against the source (read-only, decisive)

For each of the three claims, read the actual function in the gate-v2 code and decide:
CONFIRMED (the claim is true) / REFUTED (the code does it correctly — the panel misread) /
PARTIAL. Cite the file:line. Suggested checks:

```bash
# from C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
# (use Grep/Read tools, not cat)
# Claim 1 — is mc_95th_dd a real permutation MC or an empirical percentile?
#   Grep: 'mc_95th_dd|monte|permut|shuffle|np.percentile' over backtest/**/*.py
# Claim 2 — is dsr a real Deflated Sharpe or a flag?
#   Grep: 'dsr|deflated|sharpe' over backtest/**/*.py ; try:
.venv\Scripts\python.exe -c "import backtest.deflated_sharpe as d; print('DSR module exists')"
# Claim 3 — does the cost sweep re-price a fixed trade list or re-run per tier?
#   Read the cost-sweep function; check whether trades are recomputed per cost tier.
```

Output a verdict table: Claim | CONFIRMED/REFUTED/PARTIAL | file:line | evidence.
**If all three REFUTE, STOP** — the gate is fine, write a short "panel-overcalled" note, and the
ATR work (docs/ATR_MES_BUILD_PRIMER.md) becomes the next priority. Only proceed to Phase 2 for
CONFIRMED claims.

## Phase 2 — FIX only the confirmed gaps (`[safety-review]` — this is certification logic)

Implement, with a unit test for each, additively (don't silently change existing verdict fields —
add corrected ones alongside, or version the schema):

1. **Real Monte-Carlo permutation DD** — 500+ sign-shuffles (or block-bootstrap) of each
   strategy's OOS trade-return list; report the true 95th-percentile drawdown. Test on a known
   distribution.
2. **Real Deflated Sharpe** (Bailey & López-de-Prado) correcting for N grid candidates and
   non-normal returns. Test against a published worked example.
3. **Deterministic cost re-pricing** — hold the champion trade list fixed, apply each cost tier
   post-hoc, assert strict monotonicity (PF must be non-increasing as costs rise). Test that the
   monotonicity assertion fires on a deliberately broken input.

Rules: `[safety-review]` tag on the commit subject (this logic authorizes live trading). New
tests in `engine/tests/`; never modify `test_safety_layer.py`. Per-file staging only. No push.
Do NOT touch `paper_config.py`, `signals.py`, `engine/risk/**`, or enable/disable any strategy.

## Phase 3 — RE-GATE the live book honestly, then report

- Re-run the gate on MES and MGC using the corrected metrics (via the existing runners /
  orchestrator). Backtests are offline — do NOT restart or disturb the live engine on port 8010.
- Produce a before/after table: metric | old (mislabeled) | new (correct) | gate result.
- **If a corrected metric flips MES or MGC from PASS to NO_TRADE, do NOT auto-disable it** —
  surface it to Amo as a Tier-3 / `[safety-review]` decision. The fail-safe is NO_TRADE, but
  changing `paper_config.enabled` is Amo's call.

## Definition of done

A verdict table for the three claims (confirmed/refuted) + corrected gate-v2 metrics with tests +
an honest re-gate of MES/MGC showing whether the live authorization survives real MC / real DSR /
deterministic costs. The deliverable is trust: future verdicts (incl. ATR variants) now mean what
they say.

## Hard guardrails (non-negotiable)

- `LIVE_TRADING_ENABLED=False`, `REQUIRE_HUMAN_APPROVAL=True` — invariants, never change.
- No live config change, no flag enabled/disabled, no engine restart, no IB/order routing, no git push.
- `[safety-review]` tag on any gate/validation-logic edit; never weaken a threshold to make a
  strategy pass.
- Verify before fixing; a wrong fix on certification logic is worse than the original bug.
- If corrected metrics downgrade a live strategy, that's a finding to surface — not a config edit to make.
