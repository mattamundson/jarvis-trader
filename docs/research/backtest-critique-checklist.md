# JARVIS Backtest Critique Checklist

**Status:** draft · **Owner:** strategy-research · **Review cadence:** per-strategy promotion gate  
**Derived from:** `claude-trading-skills` backtest-expert skill (5-dimension scoring, 10+ red flags, Deploy/Refine/Abandon verdict) + `awesome-quant` backtesting library patterns + JARVIS promotion policy.

> This checklist is a mandatory review artifact at the backtest → walk-forward → paper promotion gate. A strategy record in the registry must carry a completed critique before it advances.

---

## 1. Five-dimension scorecard (0–100)

Score each dimension independently, then sum. A strategy scoring below 60 total, or any dimension below 8, fails the gate automatically.

| Dimension | Weight | What we measure | Top score | Zero score |
|---|---|---|---|---|
| **Sample size** | 20 | Trade count, trades/year density, number of independent market environments | ≥200 trades across ≥3 regimes | <30 trades or single-regime backtest |
| **Expectancy** | 20 | Profit factor, win rate × avg win / loss rate × avg loss, R-multiple distribution, **uncertainty estimates (bootstrap CI on PF, DSR or equivalent)** | PF ≥1.5, positive expectancy after costs, **tight uncertainty bounds** | PF ≤1.0 or negative after costs, **or wide/overlapping confidence intervals** |
| **Risk management** | 20 | Max drawdown severity, recovery time, ruin risk, position-sizing coherence | DD <15%, full recovery within 1× strategy cycle | DD >40% or no documented sizing rule |
| **Robustness** | 20 | Parameter count, parameter stability, out-of-sample / walk-forward performance, regime split | ≤4 parameters, OOS within 10% of in-sample, stable across regimes | >7 tunable parameters, OOS degradation >30%, single-regime curve fit |
| **Execution realism** | 20 | Slippage modeled, commission/fee modeling, realistic fill assumptions, latency considered | Slippage at 1.5–2× estimated, commissions modeled, fills realistic | No slippage, idealized fills, no latency model |

**Verdict bands:**

- **Deploy** (≥80, no critical red flags) — advance to walk-forward / paper shadow.
- **Refine** (60–79, or non-critical red flags) — document required fixes; re-run backtest before advancing.
- **Abandon** (<60, or any critical red flag) — strategy record is closed; capture lessons in `second-brain`.

---

## 2. Mandatory red-flag scan

Any **critical** red flag fails the gate. **Warning** flags require a written mitigation in the strategy record.

### Critical (auto-fail)

- Fewer than 30 trades total, or fewer than 10 trades per year of test window.
- Negative expectancy after modeled costs (commission + slippage).
- 7 or more freely tuned parameters with no out-of-sample validation.
- Maximum drawdown >40% of peak equity.
- No slippage or commission modeling at all.
- Test window shorter than 3 years with no regime diversity.
- Look-ahead bias: any feature or signal that uses data not available at decision time.
- Survivorship bias: universe construction that excludes delisted/inactive instruments without a documented adjustment.
- Uncertainty evidence absent: no bootstrap CI on profit factor, no Monte Carlo path distribution reporting the 95th-percentile drawdown (`mc_95th_dd`), or no multiple-testing control when the strategy was selected from many trials. DSR measures Sharpe significance after selection-bias adjustment and is not a drawdown-survival estimate; when drawdown survival is intended, path-based/Monte Carlo drawdown evidence must accompany the performance statistics.

### Warning (require documented mitigation)

- Profit factor between 1.0 and 1.2 after costs.
- Max drawdown 25–40%.
- Parameter count 5–7 with partial OOS validation.
- Test window 3–5 years with only one dominant market regime.
- Slippage modeled at less than 1× estimated real cost.
- Trade clustering in a single year or single volatility regime.
- Win rate >70% with avg win ≤ avg loss (likely overfit to a thin positive tail).
- No walk-forward or out-of-sample split documented.

---

## 3. JARVIS-specific gates

These are in addition to the generic scorecard above. All must pass for a strategy to enter paper shadow in JARVIS.

- **[ ] Data provenance recorded:** source (Databento / IBKR / YFinance / CSV), contract/venue, bar frequency, first/last date, any gap or adjustment notes.
- **[ ] Point-in-time integrity:** no backward fills, no future values, no stale data, and no adjusted-price leakage. For daily or monthly features aligned onto intraday bars, causal forward-fill of a previously published value is permitted under the freshness gate; the source value must be available before the bars it fills.
- **[ ] Futures roll and session validation:** for futures strategies, continuous-contract construction, roll date/method, symbol mappings, timezone, and session calendar are documented and consistent with the backtest data. A stitched or back-adjusted series without explicit roll handling fails this gate.
- **[ ] Regime split reported:** backtest metrics are broken down by at least coarse regime segments (e.g. high-vol / low-vol, trend / range, risk-on / risk-off) so a single calm regime cannot hide a strategy that only works in one environment. A strategy with no regime diversity in its test window is a warning flag; a strategy whose edge exists only in one regime must say so in the record.
- **[ ] Execution model matches JARVIS reality:** same broker/slippage assumptions used in backtest as will be used in paper/live; IB Gateway fill model documented if applicable.
- **[ ] Circuit-breaker coherence:** strategy's max position, daily loss limit, and drawdown halt are compatible with JARVIS risk layer limits in `engine/risk/`.
- **[ ] Kill-criterion written:** every strategy record carries an explicit "what makes this wrong" clause before paper entry (from `claude-trading-skills` quant-strategy-framework kill rule).
- **[ ] Paper shadow duration met:** minimum 20 trading days or 1 full volatility regime cycle, whichever is longer, before live promotion consideration. (This gate applies at the paper→live transition; the backtest→paper step only initializes the shadow. See `strategy-registry-schema.md` step 4 for the paper→live gate.)
- **[ ] No live config mutation:** backtest critique does not touch `engine/config.py`, `.env`, broker routing, API keys, or live order behavior. Those changes require a separate safety review.

---

## 4. Output artifacts

Every completed critique produces:

1. **`backtest-critique-<strategy-slug>-<YYYY-MM-DD>.json`** — machine-readable scorecard + red-flag list + verdict.
2. **`backtest-critique-<strategy-slug>-<YYYY-MM-DD>.md`** — human-readable report with dimension scores, red-flag narrative, and required fixes for Refine verdicts.
3. **Strategy record update:** the strategy registry YAML/record is updated with `backtest_critique_ref` pointing to the above artifacts and a `promotion_state` of `walkforward`, `paper`, or `closed`.

---

## 5. Red_flag quick reference (from backtest-expert)

| # | Flag | Type | Fix |
|---|---|---|---|
| 1 | Too few trades (<30) | Critical | Extend test window or broaden universe; do not promote on small samples |
| 2 | Negative expectancy after costs | Critical | Revisit edge hypothesis; do not paper trade a negative-E strategy |
| 3 | Over-optimization (7+ parameters) | Critical | Reduce parameter count; add OOS / walk-forward |
| 4 | Extreme drawdown (>40%) | Critical | Reduce position size; add circuit-breaker; re-evaluate risk model |
| 5 | Untested slippage | Critical | Add slippage model at 1.5–2× estimate; re-run |
| 6 | Short test period (<3 years) | Critical | Extend window; if unavailable, mark as "insufficient sample" |
| 7 | Look-ahead bias | Critical | Fix feature construction; re-run from clean point-in-time data |
| 8 | Survivorship bias | Critical | Rebuild universe with delisting/+adjustment history |
| 9 | Low profit factor (1.0–1.2) | Warning | Document; require walk-forward confirmation before paper |
| 10 | High drawdown (25–40%) | Warning | Document sizing reduction and risk-layer compatibility |
| 11 | Parameter instability | Warning | Report parameter stability range; narrow to stable plateau |
| 12 | Single-regime test | Warning | Note regime diversity gap; paper shadow must span a regime change |

---

## 6. Related

- Strategy registry schema: `docs/research/strategy-registry-schema.md`
- Macro/FRED regime-context spec: `docs/research/macro-regime-context-spec.md`
- Chart review runbook: `docs/research/chart-review-runbook.md`
- Source skill: `claude-trading-skills` backtest-expert — https://github.com/tradermonty/claude-trading-skills/blob/main/skills/backtest-expert/ (MIT, distilled as a checklist; original skill package remains the canonical interactive version)
- Source playbook: `claude-trading-skills` quant-strategy-framework — 7-layer signal stack + kill rule
