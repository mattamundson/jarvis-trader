# Execution-model cost-tier link — mes_sma_trend_vix_pctile (runner-anchored)

**Strategy:** `mes_sma_trend_vix_pctile`
**Record date:** 2026-09-26
**Author:** Hermes Agent cron run
**Scope:** docs/evidence only — this record does not touch `engine/config.py`, `.env`, broker
routing, API keys, PM2, scheduled tasks, risk limits, kill-switch code, or live order behavior.
**Companion critique:** `docs/research/backtest-critique-mes_sma_trend_vix_pctile-2026-09-24.json`
(verdict REFINE, score 73/100, open item 3)
**Related item-1 record:** `docs/research/cost-tier-pf-uncertainty-proxy-mes_sma_trend_vix_pctile-2026-09-25.md`
(shipped separately in PR #949; referenced here per the critique's open-items list)

---

## 1. Source of truth for the cost tiers

The four cost tiers in the 2026-09-24 critique were produced by
`engine/backtest/run_mes_trend_vix_pctile_rank1.py`, not by `engine/config.py`. The runner's
constants are the authoritative source for the tier mapping:

**Runner constants (`run_mes_trend_vix_pctile_rank1.py`, lines 60–61, 85–90):**

```python
COMMISSION = 0.62       # per-contract commission for the realistic tier
SLIPPAGE_TICKS = 2.0    # slippage ticks for the realistic tier

COST_SWEEP_TIERS = {
    "optimistic":   {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic":    {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic":  {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}
```

The runner varies **both** commission and slippage across every tier. Commission scales as
0.31 → 0.62 → 1.24 → 2.48 (a 2× step per tier), and slippage scales as 1.0 → 2.0 → 3.0 → 4.0
ticks. The realistic tier uses `COMMISSION=0.62, SLIPPAGE_TICKS=2.0`.

---

## 2. Mapping the four cost tiers to the runner

| Tier | Commission | Slippage (ticks) | PF reported in critique | Role |
|---|---|---|---|---|
| Optimistic | 0.31 | 1.0 | 1.706 | Lower-bound commission + mild slippage |
| Realistic | 0.62 | 2.0 | 1.648 | Primary reported figure; runner's central assumption |
| Pessimistic | 1.24 | 3.0 | 1.602 | Heavier commission + slippage |
| Catastrophic | 2.48 | 4.0 | 1.508 | 2× realistic commission + 2× realistic slippage |

All four tiers clear 1.0. The critique's red-flag check for "profit factor between 1.0 and 1.2
after costs" does **not** fire at any tier.

---

## 3. Relationship to engine/config.py (divergence, not match)

`engine/config.py` (section "Execution Cost Modeling (Backtests)") carries different defaults:

| Setting | Value | Notes |
|---|---|---|
| `COMMISSION_PER_CONTRACT` | 1.42 | MES/MNQ round-trip commission ($0.72 exchange + $0.70 clearing) |
| `SLIPPAGE_TICKS` | 1.0 | Conservative 1-tick adverse slippage per fill |
| `SPREAD_TICKS` | 0.5 | Half-spread ticks, paid on entry AND exit |
| `COMMISSION_ENABLED` | True | |
| `SLIPPAGE_ENABLED` | True | |
| `SPREAD_ENABLED` | True | |

**The runner's realistic tier does NOT match `engine/config.py`'s defaults.** The divergence is:

- **Commission:** runner realistic = 0.62 vs. config default = 1.42. The runner's commission is
  lower than the config default. The runner's catastrophic commission (2.48) exceeds the config
  default (1.42), so the runner's upper bound is more conservative on commission than the config.
- **Slippage:** runner realistic = 2.0 ticks vs. config default = 1.0 tick. The runner's slippage
  assumption is 2× the config default.
- **Spread:** the runner's cost model does not include a separate bid-ask spread term; the config
  default includes `SPREAD_TICKS=0.5` (round-trip 1.0 tick). The runner's slippage (2.0 ticks
  realistic) is the only per-fill price impact term; spread is not separately modeled in the runner.

**Net:** the critique's cost-tier PFs were produced under a cost model that is *different from* the
engine/config.py defaults — lower commission, higher slippage, no explicit spread. The realistic
tier (PF 1.648) is the runner's central assumption, not a reading of the engine config. This record
reports that divergence rather than asserting a match.

---

## 4. What this record does and does not close

**This record documents the cost-tier → runner-constant mapping and reports the divergence from
engine/config.py.** It addresses the *literal text* of critique open item 3 ("Add a note linking
the four cost tiers to the engine's fee/slippage configuration in engine/risk/"), interpreted as a
documentation request: the four tiers are now linked to their authoritative source (the runner
constants) and the relationship to engine/config.py is stated explicitly, including the divergence.

**This record does NOT close the execution-realism gate.** The critique's item 3 framing — "so the
execution model is verifiably consistent with JARVIS paper/live fill assumptions" — is a stronger
claim than a documentation link. The runner's cost model is a backtest cost sweep; it is not a
verified model of IB Gateway paper/live fills. Establishing that the backtest cost tiers are
consistent with realized paper/live fill costs is a separate execution-realism study that has not
been performed. This record does not perform that study and does not claim its conclusion.

---

## 5. Gate state after this record

Per the critique's `required_fixes`:

> "Before advancing to walk-forward/paper: close the five open items above; at minimum items 1
> (bootstrap PF CI or documented proxy acceptance) and 3 (cost-tier-to-engine-execution-model link)
> are gating."

After this record:

- **Item 3 (literal documentation link):** the four cost tiers are linked to their authoritative
  source (runner constants `run_mes_trend_vix_pctile_rank1.py` lines 85–90) and the divergence from
  engine/config.py is documented. The documentation leg of item 3 is satisfied. The execution-realism
  leg (verifiable consistency with paper/live fill assumptions) remains open and is explicitly not
  addressed by this record.
- **Item 1 (bootstrap PF CI or documented proxy acceptance):** addressed by the separate item-1
  evidence record `docs/research/cost-tier-pf-uncertainty-proxy-mes_sma_trend_vix_pctile-2026-09-25.md`
  (PR #949), which documents the cost-tier spread as a PF uncertainty proxy pending sponsor acceptance.
  That record is NOT included in this tree; readers should consult PR #949 or wait for it to merge
  before treating item 1 as addressed.
- **Items 2, 4, 5:** unchanged and out of scope for this record (MES roll provenance, experiment
  ledger completion, coarse regime overlay).

**Recommendation:** if the promotion workflow treats item 3 as a hard gate requiring execution-realism
closure, this record satisfies only the documentation leg. The execution-realism leg should be tracked
as a separate open item (backtest-cost-model vs. IB Gateway fill validation) until a fill-comparison
study is performed. If the workflow treats item 3 as a documentation request only, this record closes
it; the residual execution-realism gap should be recorded as a separate future item.

---

## 6. Acceptance note

**Documentation leg of item 3 — satisfied by this record.** The four cost tiers are linked to their
authoritative source (the runner constants in `engine/backtest/run_mes_trend_vix_pctile_rank1.py`)
and the relationship to `engine/config.py` is documented, including the explicit divergence (runner
commission 0.62 vs config 1.42; runner slippage 2.0 vs config 1.0; no separate spread in runner).

**Execution-realism leg — NOT closed.** Consistent with JARVIS paper/live fill assumptions has not
been established. The runner's backtest cost model is not a verified model of IB Gateway fills. This
record flags the gap; it does not close it. If the promotion gate requires execution-realism closure,
item 3 remains open until a fill-comparison study is performed.

**Item 1 — pending separate PR #949.** The item-1 proxy-acceptance record is not in this tree; it
ships in PR #949 (`docs/research/cost-tier-pf-uncertainty-proxy-mes_sma_trend_vix_pctile-2026-09-25.md`).
Item 1 should be treated as pending until PR #949 merges and the sponsor either accepts the documented
proxy or supplies a bootstrap CI.

No live trading config, risk limit, kill-switch, broker routing, API key, `.env`, PM2 state, or
scheduled task was changed.

---

*Generated 2026-09-26 as the item-3 evidence record for `mes_sma_trend_vix_pctile`. Anchored to the
runner constants in `engine/backtest/run_mes_trend_vix_pctile_rank1.py` after review feedback. Reports
divergence from engine/config.py rather than asserting a match. Does not close the execution-realism
gate; documents the gap.*
