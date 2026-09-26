# Backtest critique: `MES_sma_trend_vix_pctile`

**Date:** 2026-09-24  
**Verdict:** REFINE (score 73/100)
**Checklist:** `docs/research/backtest-critique-checklist.md`  
**Source data:** `docs/research/mes-vix-pctile-rank1-verdict-snapshot-2026-09-18.json`  
**Strategy registry entry:** `docs/research/strategy-registry/entries/mes_sma_trend_vix_pctile.json`

---

## Strategy at a glance

Long-only MES (E-mini S&P 500) on 1-hour bars. Entry when price is above SMA-200 and SMA-60 is above SMA-200, restricted to VIX-percentile tiers that are **not** in the walk-forward-selected blocked set. Exit on a 2× ATR trailing stop or SMA cross below. Fixed 1-contract sizing. The adaptive component is the VIX-percentile tier block: rather than a fixed `vix_min`/`vix_max` gate, the strategy selects which volatility tiers (Crisis, HighVol) to block via walk-forward, giving 4 tier-block combinations.

---

## Five-dimension scorecard

| Dimension | Score / 20 | Key facts |
|---|---|---|
| Sample size | 14 | 122 trades over 7.3 years (~16.7/yr). 82 OOS windows, 54 with trades. Spans pre-COVID, COVID crash, 2022 bear, 2023–24 range, 2025–26. Below the 200-trade ideal; median 1 trade/window = sparse signal. |
| Expectancy | 15 | Realistic PF 1.648, catastrophic-tier PF 1.508 — all tiers pass. p_edge 0.593. DSR grid 0.9688 but campaign DSR only 0.1937 (lower bound; experiment ledger incomplete). No formal bootstrap CI on PF in the snapshot. |
| Risk management | 18 | mc_95th_dd = 0.89% — far below the 15% threshold and dramatically below the 40% critical line. Fixed 1-contract sizing; no dynamic sizing; no explicit recovery-time metric. |
| Robustness | 11 | Only 1 freely varied parameter group (tier-block, 4 combos) — excellent parameter count. Fixed SMA/ATR locked at champion values. BUT WFO consistency is MODERATE; many OOS windows show PF=0 or Infinity; sparse windows weaken the walk-forward narrative. |
| Execution realism | 15 | Four-tier cost model (optimistic/realistic/pessimistic/catastrophic), all pass. No explicit latency model (1h bars make intraday latency largely irrelevant). No explicit link between cost tiers and JARVIS IB Gateway fill model. |
| **Total** | **73 / 100** | **Band: REFINE** |

---

## Red flags

### Critical — none triggered

All five critical checks pass: ≥30 trades (122), positive expectancy after costs (lowest tier PF 1.508), fewer than 7 tunable parameters (1 free group), max DD well under 40% (0.89%), slippage/commission modeled (four-tier cost model), test window >3 years with regime diversity (7.3 years, ≥4 regimes), no look-ahead bias, no survivorship bias, and uncertainty evidence is present in the form of mc_95th_dd + DSR (though the PF bootstrap CI gap is an open item — see below).

### Warnings — 1 open item, 2 mitigated

1. **Open: No bootstrap CI on profit factor.** The verdict snapshot reports cost-tier spread (1.508–1.706) and DSR, but not a bootstrap confidence interval on PF. The DSR is not a drawdown-survival estimate; the mc_95th_dd fills the drawdown-survival role, but PF uncertainty is unquantified. This is the single most important open item before paper entry.

2. **Mitigated: Parameter instability.** The only freely varied parameter is the tier-block selection (4 combos). Fixed SMA/ATR params are locked at champion values. Fixed-param PF range 1.479–1.666, mean 1.572 — stable enough, but MODERATE WFO consistency means the locked params' stability is not fully validated across all regimes. Not a firm warning given the healthy min PF.

3. **Not triggered: Trade clustering.** 122 trades spread across 7.3 years and multiple regimes; the tier-block design explicitly prevents Crisis/HighVol clustering. Sparse-signal nature (median 1 trade/window) is low frequency, not clustering.

4. **Not triggered: No walk-forward split.** 82 OOS windows are fully documented with per-window PF, DD, Sharpe, and trade counts. Full WFO split is present.

---

## JARVIS-specific gates

| Gate | Status | Detail |
|---|---|---|
| Data provenance recorded | ✅ Pass | Databento, MES, 1h, America/Chicago, 2019-05-05 → 2026-08-26, 43,010 rows, SHA256 verified in snapshot. |
| Point-in-time integrity | ✅ Pass | 1h bars; VIX percentile computed on 252-day daily lookback, causally forward-filled. No backward fills or future values. |
| Futures roll and session validation | ⚠️ Open | MES continuous-contract roll date/method and symbol mapping not explicitly documented in the snapshot. Confirm whether the Databento series is back-adjusted or stitched with explicit roll handling. |
| Regime split reported | ✅ Pass | OOS PF by tier-block combo reported; edge persists across all blocks; HighVol-only block is strongest. Coarser trend/range overlay would strengthen the record. |
| Execution model matches JARVIS | ⚠️ Open | Cost tiers are defined but not explicitly linked to the engine's fee/slippage configuration in `engine/risk/`. A note connecting the four tiers to the JARVIS IB Gateway fill model is required before paper entry. |
| Circuit-breaker coherence | ✅ Pass | Max 1 contract; daily loss halt inherits engine risk layer; kill-criterion written and compatible. |
| Kill-criterion written | ✅ Pass | Kill: 3 consecutive zero-trade OOS windows, or any single OOS window PF < 0.5. Also: MES/ES correlation regime break or contract-roll behavior change. |
| Paper shadow duration met | N/A | Not yet applicable — this critique is at the backtest→robustness stage. Applies at the robustness→paper transition. |
| No live config mutation | ✅ Pass | This critique touches no live config, `.env`, broker routing, API keys, or order behavior. |

---

## Open items before paper entry

1. **Add a bootstrap confidence interval on profit factor** to the verdict snapshot, or document why the cost-tier spread is an acceptable proxy for this strategy. This is the top-priority gap.

2. **Document MES continuous-contract roll date/method and symbol mapping** in the data provenance record. Confirm whether the Databento series is back-adjusted or stitched.

3. **Link the four cost tiers to the engine's fee/slippage configuration** in `engine/risk/` so the execution model is verifiably consistent with JARVIS paper/live fill assumptions.

4. **Complete the experiment ledger** so the DSR campaign figure (currently a lower bound of 0.1937) is not understating deflation. Until then, treat the high grid DSR (0.9688) as provisional.

5. **Consider a coarse trend/range regime overlay** in addition to the volatility-tier split for the regime-split gate.

---

## Promotion recommendation

**Refine.** The strategy has genuine edge (realistic PF 1.648, catastrophic-tier survival, strong MC drawdown, positive p_edge) and excellent parameter discipline (1 free group, 4 combos). The core verdict FAIL is expected — this strategy is only promotable via the alt-verdict pathway with explicit human approval of the adaptive-tier rationale.

Do not advance to paper shadow until items 1–3 are closed. The MODERATE WFO consistency and the sparse-signal nature (median 1 trade/window, several zero-trade OOS windows) mean the strategy can go long periods without trading and must not be judged on a few favorable recent windows alone. The DSR campaign figure must be non-lower-bound before paper entry, because the high grid DSR (0.9688) is plausibly inflated by an incomplete experiment ledger.

---

## Related

- Verdict snapshot: `docs/research/mes-vix-pctile-rank1-verdict-snapshot-2026-09-18.json`
- Strategy registry schema: `docs/research/strategy-registry/schema.json`
- Strategy registry operating contract: `docs/research/strategy-registry.md`
- Backtest critique checklist: `docs/research/backtest-critique-checklist.md`
- Macro/FRED regime-context spec: `docs/research/macro-regime-context-spec.md`
- Alt-promotion bar dossier: `docs/research/alt-promotion-bar-dossier-2026-09-18.md`
