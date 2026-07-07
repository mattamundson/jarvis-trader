# Gate v2 Calibrator — Runbook

**Module:** `engine/analytics/gate_v2_calibrator.py`
**CLI:** `scripts/gate_v2_calibration_report.py`
**HTTP:** `GET /readiness/gate-v2-calibration?days=90`
**Default state:** `ENABLE_GATE_V2_CALIBRATOR=0` (off; does not gate trading)

---

## What it computes

Gate-v2 thresholds (`pf_ci_lower >= 1.10`, `p_edge >= 0.95`,
`mc_95th_dd <= 5%`, `dsr >= 0.10`) were set when the strategy backlog
was thin.  As paper data accumulates, the calibrator uses **Bayesian
posteriors** to recommend whether each threshold should be tightened,
loosened, or held.

For each of the 4 metrics the calibrator:

1. Collects all gate-v2 verdict JSON files (live + archive) whose
   `created_at` falls within the lookback window (default 90 days).
2. Augments each verdict with the symbol's actual paper-trade win rate
   from `paper_trades` (SQLite).
3. Defines a "good outcome" as: verdict == PASS **and** win_rate >= 50%
   (or win_rate is NaN, giving benefit of the doubt).
4. Searches a candidate grid for the threshold that **maximises precision**
   while keeping **recall >= 80%** — i.e., don't raise the bar so high
   that we discard most strategies that would have been good.
5. Anchors on a **Beta(2, 2)** prior before any data.  This prior converges
   fast: by n=50 verdicts the data dominates, by n=200 the prior is
   negligible.

## Bayesian prior choice

`Beta(2, 2)` is symmetric, centred on 0.5 win probability, and weakly
informative.  Key properties:

- At n < 20, recommendations are nearly identical to the prior mean (50%
  win probability); very little data-driven pull.
- At n = 50 (weak/moderate boundary), the data starts to dominate.
- At n = 200 (strong boundary), the prior contributes < 2% weight.

The Beta prior was chosen over a flat or Jeffreys prior specifically
because flat priors produce erratic recommendations at n < 30 — a real
risk when strategies are re-scored weekly but paper trades accumulate
slowly.

## Recommendation strength

| Strength | Sample size | Interpretation |
|---|---|---|
| `weak` | n < 50 | Prior dominates; treat as directional only. Do not change thresholds. |
| `moderate` | 50–199 | Credible signal. Review with market-regime intuition before acting. |
| `strong` | >= 200 | Data dominates prior. Worth discussing a threshold change. |

With 5 live verdict files scored once per week, reaching "moderate"
requires roughly 10 weeks; "strong" requires ~40 weeks.  Phase 3
(100+ paper trades target) roughly coincides with "weak-to-moderate"
transition.

## Why thresholds should NOT be auto-applied

1. **Sample-size sensitivity:** 5 verdict files cannot distinguish a true
   regime signal from noise.  The calibrator warns explicitly when
   `recommendation_strength == "weak"`.

2. **Regime shifts:** A threshold optimised on 2024–2025 trend data may not
   generalise to a volatility-compression regime in 2026.  The model has no
   regime-awareness; only you do.

3. **Live trading consequences:** Loosening `p_edge` from 0.95 to 0.85
   would let through strategies with 15% of OOS windows having PF < 1.0.
   At current capital ($10K), a wrong threshold change has direct dollar
   consequences.

4. **Code coupling:** Gate thresholds are consumed in multiple places
   (`_gate_v2_helpers.py`, runner files, `gate_v2_policy.py`).  Env-var
   overrides can create a divergence between the constant values and
   whatever the env var says.  Human review ensures these stay synchronised.

## Suggested workflow

```
# 1. Run weekly (e.g. Sunday pre-market)
engine/.venv/Scripts/python scripts/gate_v2_calibration_report.py \
    --days 90 --output md

# 2. Review the vault snapshot
# -> master-jarvis/second-brain/raw/_session-calibration/gate-v2-YYYY-MM-DD.md

# 3. If strength == "strong" AND action agrees with intuition:
#    a. Propose threshold change in PR (update _gate_v2_helpers.py constants).
#    b. Tag with [safety-review] per .claude/rules/commits.md.
#    c. Run full test suite; verify no runner files hard-code the old values.

# 4. If strength == "weak" or "moderate": log the report, do nothing.
```

HTTP equivalent (requires API key):
```bash
curl -H "X-API-Key: <key>" \
     "http://127.0.0.1:8010/readiness/gate-v2-calibration?days=90&format=markdown"
```

## Interpreting the diff table

| Action | Meaning |
|---|---|
| `^ TIGHTEN` | Raise the hurdle (pf/p_edge/dsr) or lower the ceiling (mc_95th_dd). |
| `v LOOSEN` | Lower the hurdle or raise the ceiling — the current gate may be excluding good strategies. |
| `= HOLD` | No evidence to change. Delta < 0.001 in absolute terms. |

## Scheduling

The calibrator is intentionally **not** wired into any nightly cron.
It is a human-in-the-loop tool.  If you want a weekly cron, add it via
Windows Task Scheduler pointing to:

```
engine/.venv/Scripts/python scripts/gate_v2_calibration_report.py --days 90 --output md
```

Output is idempotent — re-running the same day overwrites the vault
snapshot for that date.

## Cross-references

- `[[KRONOS_AND_RESEARCH_AGENT_RUNBOOK]]` — parallel threshold-tuning
  context for the Kronos timing strategy.
- Phase 3 readiness criterion **C5** (`max_drawdown <= 5%`) — the
  `mc_95th_dd` threshold directly governs whether C5 is met.
- `engine/backtest/_gate_v2_helpers.py` — canonical constant values;
  the **only** place thresholds should be changed (single-line edit).
- `engine/analytics/gate_v2_calibrator.py` — source for this runbook.
- `docs/runbooks/PHASE3_READINESS.md` — full Phase 3 transition checklist.

## Files modified / created by the calibrator

| Action | Files written |
|---|---|
| CLI `--output md` | stdout + `master-jarvis/second-brain/raw/_session-calibration/gate-v2-<date>.md` |
| CLI `--output json` | stdout only |
| HTTP endpoint | Response body only — no files written |

The calibrator **never** writes to `engine/.env`, `engine/backtest/_gate_v2_helpers.py`,
`engine/data/gate_v2_verdicts/`, or any other engine config path.
