# P3-14 — MES Expansion Decision

> Created: 2026-05-24  
> Status: **Awaiting Tier 3 authorization from Amo**  
> Depends on: flip-to-active criteria clarification (see §1)

## 1. MES Flip-to-Active Status

Engine CLAUDE.md flip-to-active criteria:
1. WFE >= 0.6 on a fresh rolling walk-forward run
2. Gate v2 PASS
3. Explicit Tier 3 authorization from Amo

### MES trend rank11 verdict (2026-05-22)

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| `p_positive_edge` | 0.75 | ≥ 0.6 | ✅ (if WFE = p_edge) |
| Traditional WFE (avg_oos/avg_is return) | ~0.09 | ≥ 0.6 | ❌ (if WFE = oos/is ratio) |
| Gate v2 verdict | PASS via ALT | PASS | ✅ (ALT) / ❌ (CORE) |
| `pf_ci_lower` | 2.50 | ≥ 1.10 | ✅ |
| `p_edge` | 0.75 | ≥ 0.95 (CORE) | ❌ CORE, ✅ ALT |
| `mc_95th_dd` | 0.81% | ≤ 5% | ✅ |
| `dsr` | 1.0 | ≥ 0.10 | ✅ |
| `rolling_wfo` | STRONG | MODERATE/STRONG | ✅ |
| `fixed_params_min_pf` | 1.524 | ≥ 1.20 | ✅ |
| `cost_survives_through` | catastrophic | ≥ realistic | ✅ |

Champion params: `fast=60, slow=200, atr_trail_mult=2.0`

### Ambiguity — which WFE metric applies?

The engine CLAUDE.md says "WFE >= 0.6" but the codebase has two distinct metrics:

**Traditional WFE** (from `walk_forward.py`):  
`WFE = avg_oos_return / avg_is_return`  
- MES rank11 value: ~0.09 (from April 2026 run)  
- Low because MES trend is sparse (1-3 trades/window); many OOS windows hit 0 trades but IS still generates signal during train period  
- This metric is known to understate sparse-strategy performance

**p_positive_edge** (from `_gate_v2_helpers.py`):  
`p_edge = profitable_windows / windows_with_trades = 9/12 = 0.75`  
- More appropriate for strategies with 1-2 trades per month  
- Already used by gate v2 as the primary window-quality metric

**Amo decision needed:** Which definition does criterion 1 use?

If `p_positive_edge >= 0.6` is accepted: MES rank11 satisfies criteria 1 AND 2 → only Tier 3 auth (criterion 3) needed.  
If traditional WFE >= 0.6 is required: criteria 1 still fails; P3-14 VIX-conditional work is needed to improve OOS consistency.

---

## 2. P3-14 Strategy Options

### Option A — VIX-conditional MES trend

**Hypothesis:** Gating MES trend signals on VIX in a "productive" range (e.g. 13–30) filters out two loss regimes:
- Very low VIX (<13): contraction, trend signals whipsaw
- Crisis VIX (>40): already vetoed by risk_manager; strategy not seeing these anyway

**Goal:** Push `p_edge` from 0.75 toward 0.90+, enabling a future CORE gate v2 PASS.

**Agent-doable work:**
1. Add VIX data fetch to `BacktestDataLoader` (Polygon `I:VIX` daily → merge with hourly MES)
2. Create `run_mes_trend_vix_rank1.py` with `MIN_VIX=13, MAX_VIX=30` parameters
3. Run 19-window WFO; compare p_edge, PF, trade count vs rank11 baseline
4. If better: update champion_params in `MES_trend_vix_rank1.json`

**Estimated compute:** 3-5 minutes  
**Infrastructure work:** 1-2 hours (VIX data loader + merge logic)  
**VIX data availability:** Polygon `I:VIX` (free tier — 2 years daily); API key is in `.env`

**Risk:** Filtering to VIX 13–30 may reduce trade count below minimum for statistical validity. Run trade-count check first.

**Verdict path if VIX works:** VIX-conditional variant becomes rank1; if p_edge >= 0.95 on CORE path, strategy upgrades from ALT to CORE PASS — stronger authorization baseline.

### Option B — MES options income

**Concept:** Sell short-dated MES option premium (weekly iron condors or vertical credit spreads) when trend signal is neutral / flat. Defined-risk income while main trend strategy handles directional moves.

**Current state:**
- `engine/backtest/options_backtester.py` — scaffold, NOT runnable
- `engine/options/chain_fetcher.py` — live chain pricing only, no historical replay capability
- **No historical options chain data cached or accessible**

**Blocking requirement:** Historical options chain data needed for backtesting.  
Cheapest sources: Polygon options (subscription ~$79/mo), CBOE DataShop, or cboe.com delayed chain snapshots.

**Timeline:** Data procurement (1-2 weeks) → backtest infra wiring (2-3 hrs) → 19-window WFO (1 hr).

**Risk:** Options income on MES is a fundamentally different strategy type from trend. Edge hypothesis needs articulating before committing to data spend.

---

## 3. Recommended Path

**Immediate (agent-doable, no capital decision needed):**
1. Clarify WFE criterion (Amo) — 5 min
2. If p_edge >= 0.6 accepted as WFE metric: authorize MES paper trading (Tier 3, criterion 3)
3. Build VIX-conditional variant to push toward CORE PASS (2-3 hr infrastructure, ~$0 data cost)

**After VIX variant:**
- If p_edge improves above 0.95: CORE PASS, stronger authorization baseline
- If p_edge doesn't improve materially: VIX filter not additive; explore options income as diversifier

**Longer-term (requires data procurement decision):**
- Options income strategy: worth pursuing ONLY after MES trend is live in paper and producing real fills data. Don't invest in options data infrastructure before the base strategy is validated in paper.

**Capital impact of enabling MES paper trading:**
- Adds 1 concurrent paper instrument (MES micro, $5 tick × 4 per point)
- Daily loss limit: -2% of $50K = -$1,000 (shared with MCL + MNQ)
- Max drawdown: MES MC 95th pctile DD = 0.81% (very low — well within limits)

---

## 4. Immediate Amo Actions Required

| Action | Time | Blocks |
|--------|------|--------|
| Clarify: does ALT gate v2 PASS satisfy flip-to-active criterion 2? | 1 min | Everything below |
| Clarify: is WFE = p_positive_edge (0.75) or avg_oos/avg_is (~0.09)? | 1 min | Criterion 1 |
| If criteria 1+2 met: authorize MES paper trading (Tier 3) | 5 min | MES paper activation |
| Decide: VIX-conditional OR wait for options income data? | 5 min | P3-14 scope |

---

## 5. If Tier 3 Auth Is Granted

Remove `"MES"` from `VALIDATION_ONLY_INSTRUMENTS` in `engine/agents/pipeline.py` and update `engine/backtest/paper_config.py` with rank11 champion params:

```python
# engine/agents/pipeline.py
VALIDATION_ONLY_INSTRUMENTS: frozenset[str] = frozenset({"MGC"})  # MES promoted

# engine/backtest/paper_config.py — add/update MES entry:
"MES": PaperConfig(
    symbol="MES",
    fast_period=60,
    slow_period=200,
    atr_trail_mult=2.0,
    min_rv_annualized=0.0,
    verdict_path="data/gate_v2_verdicts/MES_trend_rank11.json",
    enabled=True,
)
```

This requires a `[safety-review]` tagged commit and the Tier 3 authorization in writing.
