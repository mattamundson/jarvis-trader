# Gate-v2 Metric Audit — 2026-05-30

Read-only audit of the three contested gate-v2 metrics behind the live MES/MGC ALT-lane PASS.
All rulings below are based on source and verdict artifacts actually read this session. Wiring was
traced end-to-end: `gate_v2_orchestrator.orchestrate_gate_v2()` → `validate_strategy.validate()`
(computes `drawdown_mc` via `bootstrap_max_dd` and `deflated_sharpe` via `deflated_sharpe_from_returns`)
→ `_evaluate_gate_v2()` → persisted verdict JSON read by `gate_v2_policy.is_strategy_authorized()`.

Certified artifacts inspected: `MES_trend_rank11.json` (verdict PASS via alt), `MGC_trend_rank4.json`
(verdict PASS via alt).

## Ruling table

| # | Claim | Supplied ruling | My ruling | Anchor (file:line) | What the code actually does | Fix warranted |
|---|---|---|---|---|---|---|
| 1 | `mc_95th_dd` is a fake / non-computed MC drawdown | REFUTED | **REFUTED (confirmed)** | `engine/backtest/monte_carlo.py:423,459-472`; wired at `engine/scripts/validate_strategy.py:423` | `bootstrap_max_dd` runs `n_resamples` (10k, set by orchestrator default) iterations: `rng.permutation(pnls_arr)` shuffles per-trade PnL, rebuilds equity via `initial_capital + np.cumsum(shuffled)`, takes max DD per path with `_compute_max_dd`, returns `np.percentile(dds, 95)` as `mc_95th`. Genuine path-dependent permutation MC. `validate()` calls it on the real per-trade pnl array. | None — code is correct. |
| 2 | `dsr=1.0` is a binary selection-bias pass-flag, NOT a Deflated Sharpe | CONFIRMED | **CONFIRMED** | `engine/backtest/deflated_sharpe.py:126-127`; wired at `engine/scripts/validate_strategy.py:425-426` | `deflated_sharpe_ratio()` lines 126-127: `if not np.isfinite(sigma) or sigma == 0: dsr = 0.0 if sharpe <= expected_max else 1.0`. The Bailey-López de Prado z-score path `Φ((SR - E[maxSR])/σ_SR)` (lines 128-130) is bypassed. `σ_SR` goes non-finite via `_sharpe_standard_error` (line 72 `n_obs<2` → inf; line 75-76 `variance<=0` → inf). Both certified verdicts show `dsr=1.0` produced by this fallback. | Yes. |
| 3 | `cost_sweep` regenerates trades per cost tier → trades flip winner↔loser, WR varies at constant n | CONFIRMED | **PARTIAL → mostly REFUTED for the certified verdicts** | `engine/scripts/cost_sensitivity_sweep.py:143-159`; runner `engine/scripts/mes_trend_search.py:70-167` | True that the sweep re-invokes the strategy `runner()` per cost tier with a `_scaled_spec` (commission×mult, slippage×mult) rather than re-pricing a fixed trade list. BUT in the certified artifacts the trade count is **constant** across all cost tiers (MES rank11: 30 trades in every tier; MGC rank4: 50 in every tier), and PF decays monotonically (MES 2.2426→2.1527; MGC 3.2288→3.1691). The "WR varies at constant n" evidence the verification cited is from `MES_trend_rank1` cost_sweep — a different, non-certified rank — and does NOT appear in the rank11/rank4 verdicts that actually authorize live MES/MGC. | Defensible code-hygiene improvement, but NOT a defect in the live authorization. |

## How the MES/MGC ALT PASS is actually constructed (from the certified JSONs)

Both certified verdicts FAIL the CORE gate (on `p_positive_edge < 0.95`) and PASS only via the ALT path with **5/5 alt criteria**. The ALT criteria and the value each rests on:

| Alt criterion | MES rank11 | MGC rank4 | Threshold | Metric trustworthy? |
|---|---|---|---|---|
| `dsr >= 0.3` | 1.000000 | 1.000000 | 0.3 | **NO — binary fallback (claim 2)** |
| `rolling_wfo in [MODERATE, STRONG]` | STRONG | MODERATE | — | not in scope |
| `fixed_params_min_pf >= 1.2` | 1.524 | 1.357 | 1.2 | not in scope |
| `cost_survives_through >= realistic` | catastrophic | catastrophic | realistic | YES (claim 3 — constant n, monotonic PF) |
| `mc_95th_dd_pct <= 4.0` | 0.8055 | 1.2386 | 4.0 | YES (claim 1) |

## Honest bottom line

**Yes — the live MES/MGC ALT authorization rests, in part, on a broken metric: the Deflated Sharpe Ratio.**

- The `dsr >= 0.30` alt-floor is one of the 5 alt criteria. In BOTH certified verdicts `dsr = 1.0`, and that 1.0 is produced by the degenerate-variance binary fallback at `deflated_sharpe.py:126-127`, not by the Bailey-López de Prado z-score. No selection-bias deflation was actually applied. A `1.0` trivially clears `>= 0.30`. So one of the five load-bearing ALT criteria is not measuring what its name and the module docstring claim. This is a genuine defect in live-certification logic, and it is independently flagged as a known gap in the project's own `ml-pitfalls-defense.md` (pitfall #3).

- The drawdown leg (`mc_95th_dd <= 4%`) is sound (claim 1 REFUTED, correctly). Real 10k-iteration permutation MC on the actual trade pnls; certified values 0.81% / 1.24% are far inside the 4% ceiling.

- The cost-sweep leg is sound *for the certified verdicts* (claim 3 largely REFUTED as applied). The supplied "win-rate varies at constant n" evidence was drawn from a non-certified rank (rank1), not the rank11/rank4 artifacts that authorize live trading. In the certified artifacts trade count is constant per tier and PF decays monotonically — exactly the property the supplied fix aims to guarantee.

Net: the DD and cost legs of the MES/MGC ALT PASS are trustworthy. The DSR leg is not — for these specific low-edge winners it is a rubber stamp. Because the ALT path requires all 5 criteria, a fail-conservative DSR (returning 0.0 instead of 1.0 on degenerate variance) would have flipped both `dsr >= 0.1` (core) and `dsr >= 0.3` (alt) to FAIL — and since alt requires 5/5, **both MES rank11 and MGC rank4 would have failed gate v2 entirely.** The defect is therefore outcome-determinative, not cosmetic.

## Prioritized fixes actually warranted

1. **[HIGH — outcome-determinative] Fail conservatively on non-finite/zero σ_SR in DSR.** `engine/backtest/deflated_sharpe.py:126-127`: when `sigma` is non-finite or zero, return `dsr = 0.0`, never `1.0`. A binary 1.0 on degenerate-variance samples is not a Deflated Sharpe and is indefensible as a live-trading gate criterion. This directly removes a fake pass from both certified MES/MGC ALT verdicts (which then fail 5/5). Touches gate-adjacent statistics — route through `[safety-review]` per repo commit rules; do not alter the 0.10/0.30 thresholds. After the fix, re-run `gate_v2_orchestrator` for MES trend rank11 and MGC trend rank4 and expect FAIL unless a non-degenerate DSR can be computed (which for ~16 OOS trades it likely cannot — meaning these strategies need more trade history before honest certification).

2. **[MED] Decouple trade generation from cost pricing in the cost sweep (code hygiene, not a live-cert defect).** `engine/scripts/cost_sensitivity_sweep.py:143-159`: generate a FIXED trade list once at baseline cost, then per scenario recompute only `pnl = (exit-entry)*mult - slip_scenario - commission_scenario`. Guarantees monotonic PF decay and constant n by construction for ALL ranks (not just the ones that happen to be constant today), and removes the latent risk that a future rank's slippage-dependent stop placement silently changes trade outcomes across tiers. NOT urgent — the certified verdicts already exhibit the desired property — but it closes the door the supplied verification correctly identified as architecturally open.

3. **[MED] Record a `dsr_fallback` flag (or `sharpe_std_error=-1`) in the verdict artifact and surface it in `gate_v2` reasons.** When the binary fallback fires, the verdict JSON should mark it so a `dsr=1.0` from the degenerate branch is never read as a genuine deflation pass by dashboards, the scoreboard, or a future hard-enforcement layer. Improves auditability of every future gate verdict and would have made this audit unnecessary.

## What is NOT warranted

- No change to `bootstrap_max_dd` / `mc_95th_dd` (claim 1 REFUTED — correct as written).
- No urgent change to the cost sweep on the basis of the supplied "WR varies" evidence — that evidence does not hold for the certified rank11/rank4 verdicts.
