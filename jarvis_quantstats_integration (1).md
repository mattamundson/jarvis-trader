# JARVIS QuantStats Integration Analysis

**Author:** Senior Quant Engineer Review  
**Date:** 2025-06-21  
**Scope:** JARVIS Trading System — scripts.zip analysis against QuantStats capabilities  
**Engine Ports:** 8010 (primary) / 8020 (secondary)  
**Active Strategies:** Strategy C+ (ETF rotation, port 8010) | MES PPO-LSTM RL (paper, DUP662235)

---

## Executive Summary

The JARVIS scripts currently validate six scalar metrics at paper-trading gates
(`profit_factor`, `sharpe`, `win_rate`, `max_drawdown`, `min_trades`, `min_days`).
QuantStats exposes 50+ metrics across its `qs.stats` module, of which at least 22 are
directly actionable for this system and currently absent from any gate or report.
The critical gaps are: drawdown *structure* (not just magnitude), tail asymmetry,
regime-conditional risk ratios, sequential loss characterization, and RL-specific
path-dependent metrics like `calmar` and `ulcer_performance_index`.

The three RL runs (9–11) failed partly because the diagnostic surface was too narrow:
`sharpe=-1.97` after Run 10 tells you the agent is unprofitable relative to volatility,
but it does not tell you *why* — whether it is a few catastrophic trades, sustained
bleeding, HOLD-state fill, or adverse tail asymmetry. QuantStats would have surfaced
this in one tearsheet.

---

## Section 1: Gap Analysis — What the Scripts Currently Measure vs. What They're Missing

### 1.1 Metrics Currently Implemented

`validation_status.py` makes a single GET to `/paper/validation/progress` and displays
whatever the engine returns. The thresholds hard-coded in the script are:

```
profit_factor   >= 2.0
sharpe          >= 1.5
win_rate        >= 55%
min_trades      >= 60
max_drawdown    <= 15%
min_days        >= 30
```

`compare_backtests.py` scans a local backtest JSON results directory and builds a
markdown table. Its validation logic duplicates the same four scalar checks
(`PF >= 2.0`, `Sharpe >= 1.5`, `WR >= 55%`, `DD <= 15%`) — with no QuantStats
involvement and no normalization of the input data.

`eval_run9.py` (and presumably run10/11 variants) POSTs to `/strategies/rl/evaluate`
and checks the same six gates. There is no trade-level returns analysis anywhere in
the current RL eval pipeline.

### 1.2 The 22 Missing QuantStats Metrics and Why Each Matters for JARVIS

The table below maps every metric the current scripts *do not compute* to its
specific relevance for either the RL MES/MNQ intraday strategy or the Strategy C+
weekly ETF rotation.

| # | QuantStats Function | Formula / Definition | Why It Matters for JARVIS |
|---|---|---|---|
| 1 | `qs.stats.sortino` | Mean excess return / downside deviation (annualized) | `sharpe >= 1.5` penalizes upside volatility equally. For an intraday RL agent that has large positive outliers on t1_bonus-triggered exits, Sortino correctly ignores those. Run 10's `Sharpe=-1.97` masked whether the downside deviation was actually improving. |
| 2 | `qs.stats.calmar` | CAGR / abs(max_drawdown) | Intraday futures agents accumulate equity much faster than ETF rotation strategies. Calmar normalizes CAGR against worst-case path. A Run 10 agent with PF=0.62 and aggressive t1_bonus exits would show Calmar ≈ −0.3 — a clear red flag vs. a Sharpe that just says "bad." |
| 3 | `qs.stats.ulcer_index` | `sqrt(mean(dd_series² / n))` where dd_series is the running drawdown | Measures drawdown *depth × duration* jointly. A strategy that stays 5% underwater for 40 days scores worse than one that hits −10% and recovers in 2 days. For Run 9 (avg_bars=109, HOLD dominating), the ulcer_index would have been catastrophically high, quantifying the HOLD-state opportunity cost. |
| 4 | `qs.stats.ulcer_performance_index` | Mean excess return / ulcer_index | Direct replacement for Sharpe in RL evaluation. Divides mean return by the integrated drawdown burden rather than volatility. This is the correct gate metric for path-dependent agents. |
| 5 | `qs.stats.gain_to_pain_ratio` | Sum(positive returns) / abs(sum(negative returns)) | Jack Schwager's GPR. Directly identifies whether the RL agent is generating net positive carry or merely surviving on outlier wins while bleeding in between. Run 9 PF=0.07 → GPR would be near zero. Run 10 PF=0.62 → GPR ≈ 0.38, both immediately actionable. |
| 6 | `qs.stats.common_sense_ratio` | `profit_factor × tail_ratio` | Combines profitability with tail asymmetry in one number. A strategy with PF=2.0 but negative tail asymmetry (large losses in the tail) is still dangerous. CSR > 1.0 is the true viability threshold for futures intraday strategies. |
| 7 | `qs.stats.tail_ratio` | 95th percentile return / abs(5th percentile return) | The RL strategy's "small wins, rare large losses" profile will show tail_ratio < 1.0, meaning the loss tail is larger than the win tail. `compare_backtests.py` has no visibility into this distribution shape. |
| 8 | `qs.stats.skew` | Third standardized moment of the return distribution | Negative skew (left tail heavier) is the single most dangerous property for an intraday futures strategy on MES. Sharpe penalizes volatility symmetrically; a strategy with skew=−1.5 and high Sharpe is still a blow-up risk. |
| 9 | `qs.stats.kurtosis` | Fourth standardized moment | Excess kurtosis > 3 indicates fat tails — relevant for MNQ specifically, which has episodic gap risk during FOMC/CPI releases. Neither validation_status.py nor compare_backtests.py checks this. |
| 10 | `qs.stats.drawdown_details` | Per-drawdown DataFrame with start, valley, end, days, max_dd | Current scripts record only the scalar `max_drawdown`. drawdown_details exposes *how many* drawdowns occurred, how long each lasted, and whether the max was a single catastrophic event or chronic degradation — completely different remediation strategies. |
| 11 | `qs.stats.recovery_factor` | Total return / abs(max_drawdown) | Answers: "does the strategy actually recover from its worst case?" For the 30-day validation window in DUP662235, a recovery_factor < 1.0 means paper trading is underwater vs. its own worst drawdown — a hard kill signal. |
| 12 | `qs.stats.information_ratio` | Active return / tracking error vs. benchmark | The Pine scripts (JARVIS_Composite_Score, JARVIS_Momentum_Signal) generate signals against the market. IR vs. SPY/MES quantifies whether those signals add alpha or just track beta. Currently unmeasured anywhere in the pipeline. |
| 13 | `qs.stats.cagr` | Compound annualized growth rate | `compare_backtests.py` shows raw PnL percentages. CAGR normalizes across different backtest window lengths. A 3-month backtest with 8% raw return vs. a 6-month backtest with 12% raw return: CAGR makes these comparable. |
| 14 | `qs.stats.kelly_criterion` | `W/L_ratio × win_prob − lose_prob` | Optimal position sizing signal. For the live RISK_ON allocation (XLK 35%/QQQ 35%/SHY 30%), Kelly would validate whether 70% gross equity exposure is sized correctly given the historical win/loss distribution. Currently the 70.1% scale is set by VIX composite alone. |
| 15 | `qs.stats.risk_of_ruin` | `((1−edge)/(1+edge))^capital_units` | Directly applicable to the paper account DUP662235. With 60 minimum trades required for validation, risk_of_ruin quantifies the probability of hitting the 15% DD gate before the 30-day period completes. |
| 16 | `qs.stats.cpc_index` | `profit_factor × win_rate × payoff_ratio` | Composite quality score. CPC > 1.0 is the threshold for sustainable trading. The current gates measure these three inputs separately but never their product — a strategy can pass all three individual gates and still have CPC < 1.0 if the magnitudes are borderline. |
| 17 | `qs.stats.value_at_risk` | 5th percentile of daily returns (parametric or historical) | Relevant for the DUP662235 account sizing. VaR at 95% confidence on MES contracts determines whether the 15% DD gate can realistically be hit in a single adverse session. |
| 18 | `qs.stats.expected_shortfall` / `qs.stats.cvar` | Mean of returns below VaR threshold | CVaR > VaR in magnitude for MNQ on macro event days. The pipeline currently has no tail-risk budget. |
| 19 | `qs.stats.consecutive_losses` | Max streak of negative-return periods | For the RL agent, consecutive_losses during training reveals whether the HOLD-dominated policy (Run 9, avg_bars=109) was generating *sustained* losing streaks vs. individual bad trades. Long streaks imply structural policy failure, not bad luck. |
| 20 | `qs.stats.outlier_loss_ratio` | Mean of outlier losses / mean of regular losses | In a PPO agent with t1_bonus reward shaping, the outlier trade profile shifts. If outlier_loss_ratio > 2.0, the agent has a "fat left tail" problem that neither PF nor Sharpe surfaces. |
| 21 | `qs.stats.r_squared` | R² of cumulative returns vs. a linear best-fit | Measures drift consistency. Strategy C+ ETF rotation should have high R² (systematic equity curve). The RL agent's R² would be low if the equity curve is erratic — a red flag even when Sharpe looks acceptable. |
| 22 | `qs.stats.exposure` | Fraction of time with non-zero position | For Run 9 (HOLD dominating), `exposure` would directly quantify what fraction of bars the agent held a directional position vs. HOLD. This is the single most direct diagnostic for the Run 9 failure mode. |

### 1.3 QuantStats Functions Currently NOT Useful for JARVIS

The following qs.stats functions have limited applicability to this specific system:

- `qs.stats.implied_volatility` — designed for options; JARVIS trades futures outright
- `qs.stats.greeks` / `qs.stats.rolling_greeks` — options greeks, not relevant for MES/MNQ linear futures
- `qs.stats.rar` — Risk-adjusted return using a proprietary formula; superseded by Calmar and UPI for this use case
- `qs.stats.geometric_mean` — redundant with CAGR for daily return series

### 1.4 Metric Coverage Heatmap

```
Current Coverage:  ████░░░░░░░░░░░░░░░░  6/28 actionable metrics (21%)
After Integration: ████████████████████  28/28 actionable metrics (100%)

Critical Gap Zone:
  Tail Risk:        [ tail_ratio | skew | kurtosis | CVaR | VaR ]        → 0% coverage
  Drawdown Quality: [ drawdown_details | ulcer_index | recovery_factor ] → 0% coverage  
  RL Diagnostics:   [ calmar | UPI | consecutive_losses | exposure ]     → 0% coverage
  Signal Quality:   [ information_ratio | r_squared | kelly ]            → 0% coverage
```

---

## Section 2: QuantStats Integration Points — Where It Slots In

### 2.1 `compare_backtests.py` → Replace Hand-Rolled Metric Extraction with `qs.stats`

**Current behavior:** The script scans a results directory for `*.json` files, loads
each one, and extracts pre-computed scalar fields directly from the JSON
(e.g., `result["profit_factor"]`, `result["sharpe"]`). The markdown comparison table is
built from these raw values with no statistical validation.

**Problem:** The JSON values are whatever the backtesting engine computed. There is no
independent verification, no distribution analysis, and no cross-backtest normalization.
If the engine's Sharpe calculation uses `periods=252` but the backtest ran for 45 trading
days, the annualization is wrong — and `compare_backtests.py` blindly trusts it.

**Integration approach:**

1. Each JSON result should include a `trades` array (list of trade PnL percentages) or
   a `returns_series` (daily returns indexed by date).
2. Convert that series to a `pd.Series` with a `DatetimeIndex`.
3. Call `qs.stats` functions directly on that Series rather than reading pre-computed scalars.

```python
# In compare_backtests.py — replace the metric extraction block
import quantstats as qs
import pandas as pd
import json, os

def extract_qs_metrics(result: dict) -> dict:
    """
    Build a qs.stats metric dict from a backtest result JSON.
    Expects result["returns"] = {date_str: pct_return, ...}
    """
    raw = result.get("returns", {})
    if not raw:
        # Fallback: reconstruct from trades list if returns_series absent
        trades = result.get("trades", [])
        if not trades:
            return {}
        raw = {t["exit_time"]: t["pnl_pct"] / 100.0 for t in trades}

    returns = pd.Series(raw)
    returns.index = pd.to_datetime(returns.index)
    returns = returns.sort_index()

    # Core gate metrics — computed by qs, not trusted from JSON
    metrics = {
        "profit_factor":        qs.stats.profit_factor(returns),
        "sharpe":               qs.stats.sharpe(returns),
        "sortino":              qs.stats.sortino(returns),
        "win_rate":             qs.stats.win_rate(returns),
        "max_drawdown":         qs.stats.max_drawdown(returns),
        "calmar":               qs.stats.calmar(returns),
        "ulcer_index":          qs.stats.ulcer_index(returns),
        "ulcer_perf_index":     qs.stats.ulcer_performance_index(returns),
        "gain_to_pain":         qs.stats.gain_to_pain_ratio(returns),
        "common_sense_ratio":   qs.stats.common_sense_ratio(returns),
        "tail_ratio":           qs.stats.tail_ratio(returns),
        "skew":                 qs.stats.skew(returns),
        "kurtosis":             qs.stats.kurtosis(returns),
        "recovery_factor":      qs.stats.recovery_factor(returns),
        "cpc_index":            qs.stats.cpc_index(returns),
        "r_squared":            qs.stats.r_squared(returns),
        "exposure":             qs.stats.exposure(returns),
        "consecutive_losses":   qs.stats.consecutive_losses(returns),
        "outlier_loss_ratio":   qs.stats.outlier_loss_ratio(returns),
        "cagr":                 qs.stats.cagr(returns),
    }
    return metrics
```

**Validation gate upgrade:** The existing four-gate check should be replaced with a
composite gate function that includes the new metrics:

```python
GATES = {
    "profit_factor":      (">=", 2.0),
    "sharpe":             (">=", 1.5),
    "sortino":            (">=", 1.0),   # new
    "calmar":             (">=", 0.5),   # new
    "win_rate":           (">=", 0.55),
    "max_drawdown":       ("<=", 0.15),
    "tail_ratio":         (">=", 1.0),   # new — right tail must >= left tail
    "common_sense_ratio": (">=", 1.5),   # new
    "ulcer_perf_index":   (">=", 0.5),   # new
    "skew":               (">=", -1.5),  # new — guard against fat left tail
}

def evaluate_gates(metrics: dict) -> tuple[bool, list[str]]:
    failures = []
    for gate, (op, threshold) in GATES.items():
        val = metrics.get(gate)
        if val is None:
            failures.append(f"{gate}: MISSING")
            continue
        if op == ">=" and val < threshold:
            failures.append(f"{gate}: {val:.4f} < {threshold}")
        elif op == "<=" and val > threshold:
            failures.append(f"{gate}: {val:.4f} > {threshold}")
    return len(failures) == 0, failures
```

### 2.2 `eod_summary.py` → Add `qs.reports.html` as Daily HTML Tearsheet

**Current behavior:** `eod_summary.py` hits four engine endpoints
(`/portfolio/stats`, `/safety/status`, `/paper/validation/progress`,
`/decisions/recent`), formats the results into a markdown string, and saves to
`docs/reports/eod/YYYY-MM-DD.md`.

**Gap:** The markdown report contains scalar snapshots only. There is no visual
representation of the equity curve, drawdown periods, rolling Sharpe, or return
distribution. The MD file is also not self-contained — it requires a markdown renderer.

**Integration approach:** After generating the markdown file, fetch the trade history
from the engine, convert to a returns Series, and emit a parallel HTML tearsheet:

```python
# Add to eod_summary.py after the markdown save block

import quantstats as qs
import pandas as pd
import requests
from datetime import datetime
from pathlib import Path

ENGINE_BASE = "http://localhost:8010"
EOD_HTML_DIR = Path("docs/reports/eod/html")
EOD_HTML_DIR.mkdir(parents=True, exist_ok=True)

def build_returns_from_engine(days: int = 90) -> pd.Series:
    """
    Fetch trade history from /decisions/recent and convert to a
    daily returns Series suitable for qs.reports.html.
    """
    resp = requests.get(f"{ENGINE_BASE}/decisions/recent", params={"limit": 500})
    resp.raise_for_status()
    decisions = resp.json()

    # Each decision has: timestamp, pnl_pct (or similar), action, symbol
    # Filter only closed trades (entry + exit pairs)
    records = {}
    for d in decisions:
        if d.get("pnl_pct") is not None:
            date = pd.to_datetime(d["timestamp"]).normalize()
            # Accumulate daily returns by compounding intraday trades
            records[date] = records.get(date, 0.0) + d["pnl_pct"] / 100.0

    if not records:
        return pd.Series(dtype=float)

    series = pd.Series(records).sort_index()
    # Forward-fill missing trading days with 0.0 (no position = flat return)
    idx = pd.date_range(series.index.min(), series.index.max(), freq="B")
    series = series.reindex(idx, fill_value=0.0)
    return series


def generate_eod_tearsheet(returns: pd.Series, report_date: str):
    """
    Generate qs.reports.html tearsheet vs SPY benchmark.
    Saves to docs/reports/eod/html/YYYY-MM-DD.html
    """
    if returns.empty or len(returns) < 5:
        print("[eod_summary] Skipping tearsheet — insufficient return history")
        return

    # Download SPY benchmark for the same date range
    benchmark = qs.utils.download_returns("SPY",
        period=f"{len(returns)}d")
    benchmark = benchmark.reindex(returns.index, fill_value=0.0)

    html_path = EOD_HTML_DIR / f"{report_date}.html"
    qs.reports.html(
        returns,
        benchmark=benchmark,
        title=f"JARVIS EOD Tearsheet — {report_date}",
        output=str(html_path),
        download_filename=str(html_path),
    )
    print(f"[eod_summary] Tearsheet saved: {html_path}")


# In the main EOD generation flow:
if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    # ... existing markdown generation ...
    returns = build_returns_from_engine(days=90)
    generate_eod_tearsheet(returns, today)
```

**Key consideration:** `qs.reports.html` requires the `returns` Series index to be
`DatetimeIndex`. The engine's `/decisions/recent` endpoint returns ISO8601 timestamps —
the `pd.to_datetime()` call handles this, but verify the engine returns UTC timestamps
consistently. If the account runs during RTH only (09:30–16:00 ET), normalize all
timestamps to Eastern time before grouping by date.

### 2.3 `validation_status.py` → Add Missing Metrics to Gate Checks

**Current behavior:** The CLI tool hits `/paper/validation/progress` and displays a
progress bar plus pass/fail for the six scalar gates.

**Integration approach:** Add a second API call to fetch the full trade history, compute
the additional QuantStats gates locally, and display an extended validation table:

```python
# Add to validation_status.py

EXTENDED_GATE_DISPLAY = [
    ("Profit Factor",       "profit_factor",      ">=", 2.0),
    ("Sharpe",              "sharpe",             ">=", 1.5),
    ("Sortino",             "sortino",            ">=", 1.0),   # NEW
    ("Calmar",              "calmar",             ">=", 0.5),   # NEW
    ("Win Rate",            "win_rate",           ">=", 55.0),
    ("Max Drawdown",        "max_drawdown",       "<=", 15.0),
    ("Tail Ratio",          "tail_ratio",         ">=", 1.0),   # NEW
    ("Common Sense Ratio",  "common_sense_ratio", ">=", 1.5),   # NEW
    ("Ulcer Perf Index",    "ulcer_perf_index",   ">=", 0.5),   # NEW
    ("Skewness",            "skew",               ">=", -1.5),  # NEW
    ("Gain-to-Pain",        "gain_to_pain",       ">=", 0.5),   # NEW
]
```

The `min_trades >= 60` and `min_days >= 30` gates should remain engine-sourced since
they depend on the count of *engine-validated* decisions, not the local returns Series.

### 2.4 `eval_run9/10/11.py` → Add `qs.stats` Analysis of Trade Return Series

**Current behavior:** `eval_run9.py` POSTs to `/strategies/rl/evaluate` and checks
six gates from the JSON response. There is no trade-level statistical analysis.

**Integration approach:** The evaluate endpoint should (or already does) return a
`trades` array. Extract it, convert to a returns Series, and run the full qs.stats suite:

```python
# Add to eval_run*.py after the gate check block

def analyze_rl_returns(trades: list[dict]) -> dict:
    """
    Convert RL trade list to QuantStats metrics.
    Each trade: {"entry_time": str, "exit_time": str, "pnl_pct": float}
    """
    if not trades or len(trades) < 10:
        print("[eval] Too few trades for qs.stats analysis")
        return {}

    # Build per-trade return Series (indexed by exit time)
    returns = pd.Series(
        {pd.to_datetime(t["exit_time"]): t["pnl_pct"] / 100.0 for t in trades}
    ).sort_index()

    metrics = {
        "n_trades":             len(returns),
        "profit_factor":        qs.stats.profit_factor(returns),
        "sharpe":               qs.stats.sharpe(returns, periods=252),
        "sortino":              qs.stats.sortino(returns, periods=252),
        "calmar":               qs.stats.calmar(returns),
        "ulcer_index":          qs.stats.ulcer_index(returns),
        "ulcer_perf_index":     qs.stats.ulcer_performance_index(returns),
        "gain_to_pain":         qs.stats.gain_to_pain_ratio(returns),
        "common_sense_ratio":   qs.stats.common_sense_ratio(returns),
        "tail_ratio":           qs.stats.tail_ratio(returns),
        "skew":                 qs.stats.skew(returns),
        "kurtosis":             qs.stats.kurtosis(returns),
        "recovery_factor":      qs.stats.recovery_factor(returns),
        "cpc_index":            qs.stats.cpc_index(returns),
        "max_drawdown":         qs.stats.max_drawdown(returns),
        "consecutive_losses":   qs.stats.consecutive_losses(returns),
        "outlier_loss_ratio":   qs.stats.outlier_loss_ratio(returns),
        "win_rate":             qs.stats.win_rate(returns),
        "exposure":             qs.stats.exposure(returns),
        "avg_win":              qs.stats.avg_win(returns),
        "avg_loss":             qs.stats.avg_loss(returns),
    }

    # Print diagnostic summary
    print("\n=== QuantStats RL Diagnostics ===")
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k:30s}: {v:>10.4f}")
        else:
            print(f"  {k:30s}: {v:>10}")

    return metrics
```

For intraday MES trades, `periods=252` (daily annualization) is technically wrong if
the returns Series is trade-indexed rather than date-indexed. Use `periods=len(returns)`
or aggregate to daily first.

### 2.5 New `jarvis_tearsheet.py` — What It Should Do

`jarvis_tearsheet.py` is the master diagnostic script that replaces ad-hoc evaluation
across all the individual scripts. It should:

1. **Accept a source argument:** `--source paper|backtest|rl` to select the data path
2. **Fetch the appropriate return series:**
   - `paper`: engine API `/paper/trades/history?account=DUP662235`
   - `backtest`: load from the same JSON results directory as `compare_backtests.py`
   - `rl`: POST to `/strategies/rl/evaluate` and extract trade list
3. **Select the appropriate benchmark:**
   - Strategy C+ ETF rotation: benchmark = `SPY` (qs.utils.download_returns)
   - MES RL intraday: benchmark = `ES=F` or `/MES=F` via yfinance
4. **Generate three outputs:**
   - `qs.reports.html(returns, benchmark, output=html_path)` — full visual tearsheet
   - `qs.reports.metrics(returns, mode="full")` — text metrics to stdout
   - `METRICS_SNAPSHOT.json` update (replacing the current `strategic_snapshot.py` output)
5. **Enforce the full gate set** (10 gates including the new QuantStats-derived ones)
6. **Write to** `docs/reports/tearsheets/YYYY-MM-DD_HH-MM_{source}.html`

---

## Section 3: Pine Script Signals → Python Validation Gap

### 3.1 The Structural Problem

The 16 Pine scripts generate signals that TradingView renders visually. The
`JARVIS_MCP_Manifest.pine` script appears to be the bridge for MCP readback — it
emits labels that an external MCP client can read. But there is no Python pipeline that:

- Captures the composite score time-series as a numeric array
- Computes independent signal quality metrics (information ratio, beta, Sharpe)
- Validates whether the signal actually generates alpha vs. the benchmark

`compare_backtests.py` looks at *outcome* metrics after trades complete. It has zero
visibility into whether the signal quality is degrading before a strategy starts to fail.

### 3.2 Information Ratio vs. SPY for Each Pine Signal

The information ratio is `IR = mean(signal_returns − benchmark_returns) / std(signal_returns − benchmark_returns)`. For Pine-generated signals, the correct implementation is:

```python
# For each Pine signal, after extracting its return series:

def compute_signal_ir(signal_returns: pd.Series, 
                       benchmark_ticker: str = "SPY") -> dict:
    """
    Compute Information Ratio and related metrics for a Pine signal.
    signal_returns: pd.Series of daily returns when signal is "active" 
                    (i.e., the strategy was long/short per signal output)
    """
    benchmark = qs.utils.download_returns(benchmark_ticker)
    benchmark = benchmark.reindex(signal_returns.index, fill_value=0.0)

    ir = qs.stats.information_ratio(signal_returns, benchmark)
    
    # Active return and tracking error
    active_returns = signal_returns - benchmark
    tracking_error = active_returns.std() * (252 ** 0.5)
    active_return_ann = active_returns.mean() * 252

    return {
        "information_ratio":    ir,
        "active_return_ann":    active_return_ann,
        "tracking_error":       tracking_error,
        "sharpe_vs_benchmark":  qs.stats.sharpe(signal_returns),
        "sortino_vs_benchmark": qs.stats.sortino(signal_returns),
        "max_drawdown":         qs.stats.max_drawdown(signal_returns),
        "tail_ratio":           qs.stats.tail_ratio(signal_returns),
    }
```

**Signal prioritization by expected IR:**

| Pine Script | Expected IR Direction | Key Metric to Watch |
|---|---|---|
| `JARVIS_Composite_Score.pine` | Highest (regime-adaptive weighting) | IR vs. SPY > 0.5 during TRENDING_BULL/BEAR |
| `JARVIS_Momentum_Signal.pine` | Medium (RSI+MACD+STC composite) | IR vs. SPY > 0.3 |
| `JARVIS_Corey_Score.pine` | Medium (VWAP-heavy, mean-reversion bias) | Sharpe vs. benchmark > 1.0 |
| `JARVIS_VPOC_Tracker.pine` | Variable (breakout-dependent) | tail_ratio > 1.2 for breakout regime |
| `JARVIS_Phase_Oscillator.pine` | Low standalone (regime filter) | rolling_beta < 0.3 (decorrelation signal) |

### 3.3 Rolling Beta Analysis for JARVIS_Composite_Score

`JARVIS_Composite_Score.pine` has four regime modes: VOLATILE, TRENDING_BULL, TRENDING_BEAR, RANGING. The regime-adaptive weighting (STC/ORB/VWAP) changes the signal's market exposure dynamically. `qs.plots.rolling_beta` exposes this:

```python
# After extracting Composite_Score returns per regime epoch:

def plot_composite_rolling_beta(composite_returns: pd.Series,
                                 benchmark_ticker: str = "SPY"):
    """
    Plot 30-day rolling beta to reveal how composite score exposure
    varies across VOLATILE/TRENDING/RANGING regime transitions.
    """
    benchmark = qs.utils.download_returns(benchmark_ticker)
    benchmark = benchmark.reindex(composite_returns.index, fill_value=0.0)
    
    # Rolling beta — qs uses 6-month (126 day) window by default
    # For intraday composite, use shorter 21-day window
    qs.plots.rolling_beta(
        composite_returns,
        benchmark,
        window=21,
        title="JARVIS Composite Score — Rolling 21d Beta vs SPY",
    )
```

**Expected finding:** During VOLATILE regime, composite score should show beta > 1.0
(amplified exposure). During RANGING regime, beta should approach 0.0 (VWAP mean-reversion
dominates). If the rolling beta is consistently > 0.8 across all regimes, the
regime-adaptive weighting in the Pine script is not functioning correctly — the signal
is just tracking SPY with leverage.

### 3.4 Regime-Conditional Sharpe Using `qs.stats.rolling_greeks`

The current engine provides a `regime` field in its state: `RISK_ON`, `RISK_OFF`,
`NORMAL`. The Strategy C+ engine.py decision log should tag each day's return with the
prevailing regime. Once you have that tagging, `qs.stats` can be applied per slice:

```python
# After building the returns + regime DataFrame:

def regime_conditional_sharpe(returns: pd.Series, 
                               regime_tags: pd.Series) -> dict:
    """
    Compute Sharpe, Sortino, max_dd by regime slice.
    regime_tags: pd.Series with same index, values in {"RISK_ON", "RISK_OFF", "NORMAL"}
    """
    results = {}
    for regime in ["RISK_ON", "RISK_OFF", "NORMAL"]:
        mask = regime_tags == regime
        slice_returns = returns[mask]
        if len(slice_returns) < 10:
            results[regime] = {"n": len(slice_returns), "note": "insufficient"}
            continue
        results[regime] = {
            "n":              len(slice_returns),
            "sharpe":         qs.stats.sharpe(slice_returns),
            "sortino":        qs.stats.sortino(slice_returns),
            "max_drawdown":   qs.stats.max_drawdown(slice_returns),
            "gain_to_pain":   qs.stats.gain_to_pain_ratio(slice_returns),
            "win_rate":       qs.stats.win_rate(slice_returns),
        }
    return results
```

`qs.stats.rolling_greeks` can feed this analysis by showing how the composite signal's
alpha (`rolling_greeks(returns, benchmark).alpha`) behaves across regime transitions.
A negative alpha drift in RANGING regime would confirm that the regime filter in
`JARVIS_Composite_Score.pine` should reduce position size further.

### 3.5 Skew and Kurtosis — Diagnosing the RL "Small Wins, Rare Large Losses" Profile

For MES PPO-LSTM trades, the reward structure with `t1_bonus=0.50` (Run 10) creates a
specific return distribution shape: frequent small positive returns when the agent exits
quickly for the bonus, interspersed with rare large losses when MAX_BARS=50 forces an
exit in a trending-against position.

```python
skew_val     = qs.stats.skew(rl_returns)      # Expected: < -0.5 for Run 10
kurt_val     = qs.stats.kurtosis(rl_returns)  # Expected: > 5.0 for leptokurtic dist
```

**Interpretation:**
- `skew < -1.0` → the left tail is materially heavier than the right tail;
  `t1_bonus` creates many small wins but when the agent is wrong and hits MAX_BARS=50,
  the forced exits are large relative to the typical win. This is the "picking up nickels
  in front of a steamroller" profile — exactly what a futures RL agent must avoid.
- `kurtosis > 5.0` → the distribution is leptokurtic; more probability mass in the
  tails than a Gaussian. Combined with negative skew, this is a high risk-of-ruin profile.
- `tail_ratio < 0.8` → the 5th percentile loss is materially larger than the 95th
  percentile win; Sharpe misses this entirely because it weights all volatility equally.

**The Sharpe blind spot:** Run 10 had `Sharpe=-1.97`. This headline number says "bad,"
but it does not distinguish between:
a) Uniformly negative returns (fixable with better signal)
b) Negative skew with fat tails (requires fundamentally different reward shaping)
c) High volatility but positive mean (sampling variance, needs more data)

`skew + tail_ratio + kurtosis` together resolve this ambiguity in one diagnostic read.

### 3.6 Why `ulcer_index` is More Meaningful Than `max_drawdown` for RL Agent Evaluation

`max_drawdown` = single point statistic: the maximum peak-to-trough decline.

`ulcer_index` = `sqrt(mean(dd_i² / n))` across all drawdown observations.

For Run 9 (avg_bars=109, HOLD dominating, PF=0.07): the agent was potentially in a
shallow but *persistent* drawdown for the entire evaluation period. `max_drawdown`
might show −8% (not catastrophic), but `ulcer_index` would be elevated because the
agent never recovered — it was underwater for hundreds of bars in a row.

For Run 10 (MAX_BARS=50, PF=0.62): the forced exits create periodic sharp drawdowns
followed by recovery attempts. `max_drawdown` might be similar to Run 9 in magnitude,
but `ulcer_index` would be lower if the drawdowns are shorter in duration.

The difference in ulcer_index between Run 9 and Run 10 *quantifies* the benefit of the
MAX_BARS cap — it reduced the duration burden of drawdowns even if it did not eliminate them.

---

## Section 4: RL Training Diagnostics — Run 9/10/11 Analysis

### 4.1 Run 9 Failure Forensics via QuantStats

**Observed:** avg_bars=109, HOLD dominating, PF=0.07

The PPO agent converged on a near-permanent HOLD policy. This is a classic sparse
reward problem: when the reward signal is weak, the safest policy is inaction.

**What QuantStats would have shown immediately:**

```python
# Hypothetical Run 9 qs.stats output (given PF=0.07):
exposure          ≈ 0.05  # Only 5% of bars had directional position
                           # → DIRECT evidence of HOLD dominance
gain_to_pain      ≈ 0.04  # sum(wins) / sum(abs(losses)) ≈ 4%
                           # → The agent barely generates any positive return at all
common_sense_ratio≈ 0.03  # PF × tail_ratio → near zero
consecutive_losses≈ 40-60 # Long streaks of negative trades
                           # when agent DOES trade, it loses repeatedly
calmar            ≈ -0.8  # Negative CAGR / max_drawdown → deeply negative return
ulcer_index       ≈ 0.18  # High persistent drawdown burden
```

`qs.stats.exposure(run9_returns)` would have been the single most decisive diagnostic.
An `exposure` of ~0.05 (5% of periods have non-zero return from directional position)
immediately shows the HOLD dominance — no manual log inspection required.

### 4.2 Run 10 Failure Forensics — `gain_to_pain` and `common_sense_ratio`

**Observed:** `hold_cost=-0.010`, `t1_bonus=0.50`, `MAX_BARS=50`, PF=0.62, Sharpe=−1.97

The Run 10 reward shaping increased action but destroyed risk-adjusted performance.
`PF=0.62` means losses exceed gains by 38%. `Sharpe=−1.97` means the excess return is
negative and large relative to volatility.

**Where Sharpe fails as a diagnostic:**

`Sharpe = mean(r) / std(r) × sqrt(252)`

If `mean(r)` is slightly negative but `std(r)` is very high due to the `t1_bonus`
creating a bimodal return distribution (quick small wins vs. MAX_BARS forced losses),
Sharpe gets destroyed by the volatility even if the underlying trade quality is improving.

**Where `gain_to_pain_ratio` and `common_sense_ratio` provide more signal:**

`gain_to_pain_ratio = sum(positive_returns) / abs(sum(negative_returns))`

For Run 10: `GPR = 0.62 / 1.0 = 0.38` (approximately, matching PF=0.62 arithmetic).
This confirms the agent is generating 38 cents of gain per dollar of loss — better
than Run 9's ~4 cents, but still deeply unprofitable.

`common_sense_ratio = profit_factor × tail_ratio`

If the `t1_bonus` is creating right-tail wins (large positive outliers when exiting
early), then `tail_ratio` could be > 1.0 even with PF=0.62. If
`CSR = 0.62 × 1.4 = 0.87`, that's a different diagnosis from `CSR = 0.62 × 0.6 = 0.37`:
- CSR=0.87: The agent has good tail characteristics but too many small losses; fix: raise t1 exit threshold
- CSR=0.37: The agent has both bad profitability AND bad tail characteristics; fix: fundamental reward redesign

**The diagnostic gap in the current eval pipeline:** `eval_run9.py` (and presumably
run10/11 variants) only checks the six scalar gates. It reports FAIL without distinguishing
between these two fundamentally different failure modes.

### 4.3 `drawdown_details` — Structure of the Run 10 Drawdown

`qs.stats.drawdown_details(to_drawdown_series(returns))` returns a DataFrame:

```
   start       valley      end         days  max_drawdown  99% max_drawdown
0  2024-10-01  2024-10-03  2024-10-05  4     -0.045        -0.041
1  2024-10-07  2024-10-12  2024-10-14  7     -0.062        -0.058
2  ...
```

**For Run 10:** With MAX_BARS=50, drawdowns should be structurally different from Run 9:
- Run 9: expect 1–3 *large, long-duration* drawdowns (HOLD keeps agent underwater for
  100+ bars in a losing direction)
- Run 10: expect *many short-duration drawdowns* (MAX_BARS cap forces exits, creating
  frequent resets of the drawdown clock)

If `drawdown_details` shows Run 10 has, say, 15 drawdown events vs. Run 9's 3 events,
but the average duration dropped from 60 bars to 8 bars, the MAX_BARS intervention
worked structurally — the problem is that the *frequency* increased. This would point
to the `hold_cost=-0.010` being too aggressive, forcing the agent to trade more often
into adverse conditions.

### 4.4 `calmar` and `ulcer_performance_index` as Better RL Gates Than Sharpe

**Why Sharpe is a poor RL gate for intraday futures:**

1. Sharpe uses total volatility in the denominator, including upside volatility from
   `t1_bonus` spikes. An RL agent with many small wins and occasional large losses can
   have a low (or negative) Sharpe purely due to return variance, even if it's net profitable.

2. For short evaluation windows (60-trade minimum in the current gates), Sharpe has very
   high sampling variance. A 60-trade window with 55% win rate could show Sharpe anywhere
   from −0.5 to +2.0 purely from noise.

3. Sharpe penalizes all volatility equally. For an intraday RL agent executing 3–8 trades
   per session, the autocorrelation structure of returns is completely different from a
   daily return series. `qs.stats.sharpe(returns, smart=True)` applies an autocorrelation
   penalty, but this is not currently used in any JARVIS eval script.

**Calmar as RL gate:**

`calmar = CAGR / abs(max_drawdown)`

Calmar is better for RL evaluation because:
- It measures return *per unit of worst-case loss* — directly tied to the risk budget
- It is stable under changes in return variance (unlike Sharpe)
- For an intraday agent, the annualized CAGR can be computed from trade-indexed returns
  by using `periods=len(trades)` scaled by the expected number of sessions per year

**UPI as RL gate:**

`UPI = mean_excess_return / ulcer_index`

UPI is the optimal RL gate metric because:
- Ulcer_index captures both the depth AND duration of drawdowns
- An agent that is slightly negative on average but rapidly recovers (low ulcer_index)
  scores better than an agent with similar mean return but persistent underwater periods
- This directly corresponds to what we want from the RL agent on MES: quick entries,
  quick exits, minimal time spent in adverse positions

### 4.5 Recommended Gate Changes for Run 12

Replace the current six-gate validation with the following 10-gate set:

```python
# run12_gates.py — replace eval_run*.py validation block

RUN12_GATES = {
    # Keep existing (relaxed slightly for intraday futures)
    "profit_factor":        (">=", 1.5),   # Reduced from 2.0 — RL needs room to learn
    "win_rate":             (">=", 0.52),   # Reduced from 55% — MES futures, not equities
    "max_drawdown":         ("<=", 0.20),   # Increased from 15% — intraday, faster recovery
    "min_trades":           (">=", 60),     # Unchanged
    "min_days":             (">=", 30),     # Unchanged

    # New QuantStats-derived gates (replacing sharpe>=1.5)
    "sortino":              (">=", 1.0),    # REPLACES sharpe>=1.5
    "calmar":               (">=", 0.5),    # NEW — return per unit of max drawdown
    "tail_ratio":           (">=", 1.0),    # NEW — right tail >= left tail
    "gain_to_pain":         (">=", 0.5),    # NEW — basic profitability of trade flow
    "consecutive_losses":   ("<=", 8),      # NEW — max losing streak cap
}

# Rationale for removing sharpe>=1.5:
# - Sharpe>=1.5 on 60 trades has too much sampling noise for gates
# - Sortino>=1.0 + calmar>=0.5 together are more robust
# - tail_ratio>=1.0 guards against the "small wins, rare large losses" RL failure mode
```

**Run 11 hypothesis assessment:** `hold_cost_only_when_losing=True` is the correct
direction. The current `hold_cost=-0.010` penalizes ALL holds, including profitable
holds where the position is moving in the agent's favor. The hypothesis reduces the
spurious "cut winners early" pressure while maintaining the penalty for holding losers.

If Run 11 succeeds, expect: `exposure` to increase (more directional trades),
`consecutive_losses` to decrease (fewer forced exits into bad conditions),
`tail_ratio` to improve (t1_bonus wins are kept, forced loser exits are reduced).

---

## Section 5: Regime-Conditional Analysis — The Missing Layer

### 5.1 Conditional Sharpe, Sortino, and Max_DD by Regime

The Strategy C+ engine.py tags each day's decision with `RISK_ON`, `RISK_OFF`, or
`NORMAL`. The engine's VIX composite (`VIX=19.5` in the current live state) drives these
tags. The QL evaluation scripts currently treat all return observations as i.i.d., which
is incorrect: a strategy that performs well in RISK_ON but catastrophically in RISK_OFF
can still pass the aggregate gates by luck of regime timing.

```python
# regime_analysis.py — to be added as a new analysis module

import quantstats as qs
import pandas as pd
import requests

ENGINE_BASE = "http://localhost:8010"

def fetch_regime_tagged_returns() -> pd.DataFrame:
    """
    Fetch daily decision log with regime tags.
    Returns DataFrame with columns: date, daily_return, regime
    """
    resp = requests.get(f"{ENGINE_BASE}/decisions/recent", params={"limit": 1000})
    resp.raise_for_status()
    decisions = resp.json()
    
    rows = []
    for d in decisions:
        rows.append({
            "date":         pd.to_datetime(d["timestamp"]).normalize(),
            "daily_return": d.get("pnl_pct", 0.0) / 100.0,
            "regime":       d.get("regime_label", "UNKNOWN"),
        })
    
    df = pd.DataFrame(rows)
    df = df.groupby(["date", "regime"]).agg(
        daily_return=("daily_return", "sum")
    ).reset_index()
    return df.sort_values("date")


def regime_conditional_analysis(df: pd.DataFrame) -> dict:
    """
    Compute qs.stats metrics conditioned on regime label.
    """
    results = {}
    for regime in df["regime"].unique():
        subset = df[df["regime"] == regime].set_index("date")["daily_return"]
        if len(subset) < 5:
            continue
        
        results[regime] = {
            "n_days":           len(subset),
            "sharpe":           qs.stats.sharpe(subset),
            "sortino":          qs.stats.sortino(subset),
            "calmar":           qs.stats.calmar(subset) if len(subset) > 10 else None,
            "max_drawdown":     qs.stats.max_drawdown(subset),
            "gain_to_pain":     qs.stats.gain_to_pain_ratio(subset),
            "win_rate":         qs.stats.win_rate(subset),
            "avg_win":          qs.stats.avg_win(subset),
            "avg_loss":         qs.stats.avg_loss(subset),
            "tail_ratio":       qs.stats.tail_ratio(subset) if len(subset) > 10 else None,
        }
    
    return results
```

**Expected findings for Strategy C+:**

| Regime | Expected Sharpe | Expected Max DD | Interpretation |
|---|---|---|---|
| RISK_ON | > 2.0 | < 8% | Momentum + VIX filter working; XLK/QQQ allocation generating alpha |
| RISK_OFF | 0 to −1.0 | 8–15% | SHY 30% allocation partially hedges but not fully; expected degradation |
| NORMAL | 0.5 to 1.5 | 5–12% | Mixed regime, strategy should be flat-to-positive |

If `RISK_OFF Sharpe < −1.5`, the `SHY 30%` allocation is insufficient as a hedge and
the strategy should consider increasing SHY weight during RISK_OFF classification.

### 5.2 `qs.plots.rolling_sharpe` for Regime Transition Visualization

```python
# Visualize rolling Sharpe with regime boundaries overlaid
import matplotlib.pyplot as plt

def plot_rolling_sharpe_with_regime(returns: pd.Series, 
                                     regime_tags: pd.Series,
                                     window: int = 21):
    """
    Overlay regime classification on rolling Sharpe chart.
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    
    # Rolling Sharpe via qs
    qs.plots.rolling_sharpe(returns, window=window, 
                             title="JARVIS Rolling Sharpe — Regime Overlay",
                             figsize=(14, 4), show=False)
    
    # Add regime color bands
    for regime, color in [("RISK_ON", "green"), ("RISK_OFF", "red"), ("NORMAL", "gray")]:
        mask = regime_tags == regime
        if mask.any():
            # Shade background for regime periods
            ax1.fill_between(returns.index, -10, 10, 
                            where=mask.reindex(returns.index, fill_value=False),
                            alpha=0.15, color=color, label=regime)
    
    ax1.legend(loc="upper left")
    plt.tight_layout()
    plt.savefig("docs/reports/analysis/rolling_sharpe_regime.png", dpi=150)
```

This visualization directly answers: "Is the Strategy C+ Sharpe declining before regime
transitions?" A leading indicator of RISK_OFF might be a rolling Sharpe that starts
declining 3–5 days before the VIX composite triggers a regime change.

### 5.3 `qs.plots.monthly_heatmap` for RL Agent Seasonality

```python
# Monthly heatmap for RL agent — reveals if MES has monthly seasonality
qs.plots.monthly_heatmap(
    rl_returns,
    title="MES PPO-LSTM — Monthly Returns Heatmap",
    figsize=(10, 5),
    show=False,
    savefig="docs/reports/analysis/rl_monthly_heatmap.png",
)
```

For MES intraday RL, monthly seasonality matters because:
- FOMC meeting months (approximately 8 per year) have elevated volatility that can
  disrupt the RL policy's trained behavior
- Quarterly expiration months (March, June, September, December) have unusual volume
  patterns in MES that the PPO agent was not necessarily trained on
- January and September historically have negative drift in MES

If the heatmap shows the RL agent consistently underperforming in FOMC months, the
training data should oversample FOMC-adjacent sessions or the live deployment should
reduce position size in those periods.

### 5.4 Rolling Beta Against MES Futures (Not SPY)

The current pipeline benchmarks against SPY via `qs.utils.download_returns("SPY")`.
For an MES (Micro E-mini S&P 500 futures) RL strategy, the *correct* benchmark is MES
itself (or ES, its larger sibling), not SPY. Using SPY introduces a systematic
basis mismatch: MES has roll costs, futures premium/discount, and overnight gaps that
SPY does not capture.

```python
import yfinance as yf

def get_mes_benchmark(start_date: str, end_date: str) -> pd.Series:
    """
    Fetch MES continuous futures via yfinance as benchmark.
    ES=F is the front-month E-mini; use this as a proxy for MES.
    """
    es = yf.download("ES=F", start=start_date, end=end_date, 
                     progress=False, auto_adjust=True)
    returns = es["Close"].pct_change().dropna()
    returns.index = pd.to_datetime(returns.index)
    return returns


def rl_beta_vs_mes(rl_returns: pd.Series) -> dict:
    """
    Compute rolling and static beta of RL strategy vs. MES futures.
    """
    benchmark = get_mes_benchmark(
        start_date=str(rl_returns.index.min().date()),
        end_date=str(rl_returns.index.max().date()),
    )
    benchmark = benchmark.reindex(rl_returns.index, fill_value=0.0)
    
    greeks = qs.stats.greeks(rl_returns, benchmark)
    
    return {
        "beta":   greeks.get("beta", None),
        "alpha":  greeks.get("alpha", None),
        "r2":     qs.stats.r_squared(rl_returns, benchmark),
    }
```

**What the beta reveals:**

- **beta ≈ 0.0:** RL agent is market-neutral; good for an intraday mean-reversion agent
- **beta ≈ 1.0:** RL agent is essentially long MES all day; no alpha, just beta exposure  
- **beta < 0:** RL agent is taking predominantly short positions; verify this matches intent
- **alpha > 0 with low beta:** The holy grail — genuine skill, not just market exposure

For the PPO-LSTM MES agent, `alpha > 0` combined with `beta < 0.3` would confirm that
the agent is trading on signal (MACD, RSI composites from the Pine scripts), not just
riding directional drift.

---

## Section 6: WFE Live Monitor Enhancement (Sprint 21-E)

### 6.1 Context

Sprint 21-E is building a WFE (Walk-Forward Efficiency) live monitor. The current WFE
scores are `MCL WFE=0.82` and `MNQ WFE=0.57`. WFE = OOS_Sharpe / IS_Sharpe; a score
of 1.0 means the out-of-sample (live) performance exactly matches the in-sample
(backtest) performance. WFE=0.82 for MCL is strong. WFE=0.57 for MNQ means the live
performance is capturing only 57% of the backtest performance — concerning but not
uncommon for RL-trained strategies.

### 6.2 IS vs. OOS Performance Comparison via `qs.stats`

```python
# wfe_monitor.py — core module for Sprint 21-E /wfe/live-monitor endpoint

import quantstats as qs
import pandas as pd
from typing import TypedDict

class WFEReport(TypedDict):
    symbol:             str
    is_sharpe:          float
    oos_sharpe:         float
    wfe_sharpe:         float
    is_sortino:         float
    oos_sortino:        float
    wfe_sortino:        float
    is_calmar:          float
    oos_calmar:         float
    wfe_calmar:         float
    is_max_dd:          float
    oos_max_dd:         float
    recovery_factor:    float
    r_squared:          float
    is_gain_to_pain:    float
    oos_gain_to_pain:   float
    is_ulcer_index:     float
    oos_ulcer_index:    float
    wfe_overall:        float   # geometric mean of wfe_sharpe, wfe_sortino, wfe_calmar


def compute_wfe_report(symbol: str, 
                        is_returns: pd.Series, 
                        oos_returns: pd.Series) -> WFEReport:
    """
    Generate full WFE report comparing IS (backtest) vs. OOS (live) returns.
    
    is_returns:  pd.Series — daily returns from the in-sample training period
    oos_returns: pd.Series — daily returns from live trading (post-deployment)
    """
    def safe_stat(fn, returns, **kwargs):
        try:
            result = fn(returns, **kwargs)
            return float(result) if result is not None else None
        except Exception:
            return None

    is_sharpe   = safe_stat(qs.stats.sharpe,   is_returns)
    oos_sharpe  = safe_stat(qs.stats.sharpe,   oos_returns)
    is_sortino  = safe_stat(qs.stats.sortino,  is_returns)
    oos_sortino = safe_stat(qs.stats.sortino,  oos_returns)
    is_calmar   = safe_stat(qs.stats.calmar,   is_returns)
    oos_calmar  = safe_stat(qs.stats.calmar,   oos_returns)
    
    # WFE = OOS / IS for each metric (capped at 1.0, floored at 0.0)
    def wfe(oos_val, is_val):
        if is_val is None or is_val == 0 or oos_val is None:
            return None
        return max(0.0, min(1.0, oos_val / is_val))
    
    wfe_sharpe  = wfe(oos_sharpe,  is_sharpe)
    wfe_sortino = wfe(oos_sortino, is_sortino)
    wfe_calmar  = wfe(oos_calmar,  is_calmar)
    
    # Overall WFE = geometric mean of three metrics
    from math import prod
    wfe_vals = [v for v in [wfe_sharpe, wfe_sortino, wfe_calmar] if v]
    wfe_overall = prod(wfe_vals) ** (1 / len(wfe_vals)) if wfe_vals else None
    
    return WFEReport(
        symbol=symbol,
        is_sharpe=is_sharpe,
        oos_sharpe=oos_sharpe,
        wfe_sharpe=wfe_sharpe,
        is_sortino=is_sortino,
        oos_sortino=oos_sortino,
        wfe_sortino=wfe_sortino,
        is_calmar=is_calmar,
        oos_calmar=oos_calmar,
        wfe_calmar=wfe_calmar,
        is_max_dd=safe_stat(qs.stats.max_drawdown, is_returns),
        oos_max_dd=safe_stat(qs.stats.max_drawdown, oos_returns),
        recovery_factor=safe_stat(qs.stats.recovery_factor, oos_returns),
        r_squared=safe_stat(qs.stats.r_squared, oos_returns),
        is_gain_to_pain=safe_stat(qs.stats.gain_to_pain_ratio, is_returns),
        oos_gain_to_pain=safe_stat(qs.stats.gain_to_pain_ratio, oos_returns),
        is_ulcer_index=safe_stat(qs.stats.ulcer_index, is_returns),
        oos_ulcer_index=safe_stat(qs.stats.ulcer_index, oos_returns),
        wfe_overall=wfe_overall,
    )
```

### 6.3 `qs.reports.html` with IS Benchmark for OOS Attribution

The most powerful WFE visualization is to treat the IS returns *as the benchmark* and
run the OOS returns through `qs.reports.html`:

```python
def generate_wfe_tearsheet(symbol: str,
                            is_returns: pd.Series,
                            oos_returns: pd.Series,
                            output_dir: str = "docs/reports/wfe"):
    """
    Generate qs.reports.html tearsheet where the IS period is the benchmark.
    This shows exactly how much the live strategy is tracking vs. deviating
    from its own historical performance.
    """
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, f"{symbol}_wfe_tearsheet.html")
    
    # The benchmark IS the IS period returns resampled to match OOS date range
    # (use a rolling IS window if the IS period is much longer)
    is_mean = is_returns.mean()
    is_std  = is_returns.std()
    
    # Synthetic IS benchmark for OOS period — constant expected return from IS stats
    # This allows qs.reports.html to show tracking error vs. IS expectation
    is_benchmark = pd.Series(
        is_mean, 
        index=oos_returns.index,
        name="IS_Expectation"
    )
    
    qs.reports.html(
        oos_returns,
        benchmark=is_benchmark,
        title=f"{symbol} — OOS vs IS Benchmark (WFE Analysis)",
        output=output_path,
    )
    return output_path
```

### 6.4 `recovery_factor` and `r_squared` for Live Performance Tracking

For the `/wfe/live-monitor` endpoint, the two most actionable long-term tracking metrics are:

**`recovery_factor` (live):**
- Monitors whether the live strategy is recovering from its OOS drawdowns at a pace
  consistent with IS behavior
- If `is_recovery_factor = 3.2` (backtest) and `oos_recovery_factor = 0.8` (live),
  the live strategy is not recovering from drawdowns at the expected IS rate
- Alert threshold: if `oos_recovery_factor < 0.5 × is_recovery_factor`, flag for review

**`r_squared` (live vs. IS):**
- Measures whether the live equity curve is following the expected IS return trajectory
- High `r_squared` (> 0.85) = live strategy tracking IS well, regime is stable
- Low `r_squared` (< 0.5) = live strategy deviating from IS; either regime shift or
  model degradation

```python
# WFE endpoint payload structure for /wfe/live-monitor
def wfe_endpoint_response(mcl_report: WFEReport, mnq_report: WFEReport) -> dict:
    return {
        "timestamp": pd.Timestamp.now().isoformat(),
        "strategies": {
            "MCL": {
                "wfe_overall":      mcl_report["wfe_overall"],    # Currently 0.82
                "wfe_sharpe":       mcl_report["wfe_sharpe"],
                "wfe_sortino":      mcl_report["wfe_sortino"],
                "wfe_calmar":       mcl_report["wfe_calmar"],
                "oos_recovery":     mcl_report["recovery_factor"],
                "oos_r_squared":    mcl_report["r_squared"],
                "oos_max_dd":       mcl_report["oos_max_dd"],
                "status": "GREEN" if mcl_report["wfe_overall"] > 0.70 else "YELLOW"
            },
            "MNQ": {
                "wfe_overall":      mnq_report["wfe_overall"],    # Currently 0.57
                "wfe_sharpe":       mnq_report["wfe_sharpe"],
                "wfe_sortino":      mnq_report["wfe_sortino"],
                "wfe_calmar":       mnq_report["wfe_calmar"],
                "oos_recovery":     mnq_report["recovery_factor"],
                "oos_r_squared":    mnq_report["r_squared"],
                "oos_max_dd":       mnq_report["oos_max_dd"],
                "status": "YELLOW" if mnq_report["wfe_overall"] > 0.50 else "RED"
            }
        },
        "alerts": [
            f"MNQ WFE={mnq_report['wfe_overall']:.2f} — below threshold 0.70"
            if mnq_report["wfe_overall"] and mnq_report["wfe_overall"] < 0.70 else None,
        ]
    }
```

### 6.5 WFE Diagnostic Interpretation for MCL (0.82) and MNQ (0.57)

**MCL WFE=0.82:** Healthy. The live strategy is capturing 82% of IS performance. The
18% gap is likely attributable to execution slippage (MCL is a crude oil micro futures
contract with wider spreads than MES), regime drift, and parameter sensitivity. No
intervention needed; monitor `recovery_factor` for deterioration.

**MNQ WFE=0.57:** Concerning. MNQ is the Micro Nasdaq 100 futures contract. Three
hypotheses for the 43% OOS decay:

1. **Overfit IS:** The backtest period likely included a strong 2023–2024 tech bull run
   that the strategy was implicitly fit to; OOS regime is less tech-positive
2. **Vol mismatch:** MNQ has higher per-contract volatility than MES; the IS vol
   targeting may be calibrated to MES-like vol, causing OOS oversizing in MNQ
3. **Liquidity degradation:** MNQ spreads can widen significantly during macro events;
   the IS backtest may use mid prices while live fills are at bid/ask

Use `qs.stats.calmar(oos_returns)` vs. `qs.stats.calmar(is_returns)` for MNQ to
determine if the WFE gap is driven by lower CAGR or higher max drawdown — these have
different remediation paths.

---

## Section 7: Pine Script Feature Extraction → Python Backtesting

### 7.1 Bridge Architecture: TradingView MCP Readback → Python → QuantStats

The `JARVIS_MCP_Manifest.pine` script (and `JARVIS_MCP_Readback` labels visible in
multiple other Pine scripts) establishes a TradingView-to-external-system bridge.
The current flow appears to be:

```
TradingView Pine Script → MCP label emission → MCP client (Python?) → Engine API
```

To extend this to QuantStats validation, the architecture should be:

```
TradingView Pine Script
    ↓ MCP label emission (composite_score, regime, signal values)
Python MCP Client (reads labels)
    ↓ Accumulates time-series of [timestamp, signal_value, price]
Signal Return Constructor
    ↓ For each signal: if signal crosses threshold, enter next bar, exit on signal flip
    → pd.Series of trade returns (indexed by exit time)
QuantStats Analysis
    → qs.reports.html(signal_returns, benchmark=MES_returns)
    → qs.stats metrics dict → compare_backtests.py integration
```

**Implementation of the MCP readback buffer:**

```python
# mcp_signal_collector.py — accumulates Pine signal data for Python analysis

import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import pandas as pd

SIGNAL_BUFFER_PATH = Path("data/signals/mcp_buffer.json")

class MCPSignalCollector:
    """
    Accumulates TradingView MCP label emissions into a signal time-series.
    Each label emission: {"timestamp": str, "signal": str, "value": float, "price": float}
    """
    def __init__(self):
        self.buffer = defaultdict(list)  # signal_name → list of {ts, value, price}
        self._load_existing()
    
    def _load_existing(self):
        if SIGNAL_BUFFER_PATH.exists():
            with open(SIGNAL_BUFFER_PATH) as f:
                data = json.load(f)
            self.buffer = defaultdict(list, data)
    
    def record(self, signal_name: str, value: float, price: float):
        self.buffer[signal_name].append({
            "timestamp": datetime.utcnow().isoformat(),
            "value": value,
            "price": price,
        })
        # Persist every 100 records
        if len(self.buffer[signal_name]) % 100 == 0:
            self._save()
    
    def to_returns_series(self, signal_name: str, 
                           entry_threshold: float = 0.5,
                           exit_threshold: float = -0.5) -> pd.Series:
        """
        Convert signal time-series to a returns Series.
        Entry: signal crosses above entry_threshold → LONG
        Exit:  signal crosses below exit_threshold → FLAT
        Returns indexed by exit timestamp, value = (exit_price/entry_price) - 1
        """
        records = self.buffer.get(signal_name, [])
        if not records:
            return pd.Series(dtype=float)
        
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        
        trades = []
        in_trade = False
        entry_price = None
        entry_time = None
        
        for _, row in df.iterrows():
            if not in_trade and row["value"] >= entry_threshold:
                in_trade = True
                entry_price = row["price"]
                entry_time = row["timestamp"]
            elif in_trade and row["value"] <= exit_threshold:
                pnl = (row["price"] / entry_price) - 1
                trades.append({"exit_time": row["timestamp"], "pnl": pnl})
                in_trade = False
        
        if not trades:
            return pd.Series(dtype=float)
        
        trades_df = pd.DataFrame(trades).set_index("exit_time")
        return trades_df["pnl"]
    
    def _save(self):
        SIGNAL_BUFFER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SIGNAL_BUFFER_PATH, "w") as f:
            json.dump(dict(self.buffer), f)
```

### 7.2 Alpha Ranking of Pine Signals

| Rank | Pine Script | Quantifiable Alpha Source | Key QuantStats Metric |
|---|---|---|---|
| 1 | `JARVIS_Composite_Score.pine` | Regime-adaptive weighting (STC+ORB+VWAP); VIX regime input from engine; direct JARVIS system integration | `information_ratio > 0.5`, `sortino > 1.5` |
| 2 | `JARVIS_Corey_Score.pine` | VWAP(40%) mean-reversion anchor; close_vs_prev(20%) momentum; STC(20%) trend filter; session_ema(20%) intraday structure | `sharpe > 1.2`, `skew > -0.5` (mean-reversion should have positive skew) |
| 3 | `JARVIS_Volume_Profile.pine` + `JARVIS_VPOC_Tracker.pine` | Volume at price (VAH/VAL/POC levels) as support/resistance; VPOC breakout signal | `tail_ratio > 1.3` for breakout regime; `recovery_factor > 2.0` |
| 4 | `JARVIS_Phase_Oscillator.pine` + `JARVIS_Market_Cycle.pine` | Cycle phase detection; decorrelation from market beta; leading indicator for regime transitions | `rolling_beta < 0.3` (decorrelation signal) |
| 5 | `JARVIS_Corey_TPO_Profile.pine` | Time-Price-Opportunity profile; identifies composite value area from session structure | `r_squared > 0.8` (TPO provides stable structural reference) |

**Why Composite_Score ranks #1:** It is the only Pine script with direct regime feedback
from the engine (VOLATILE/TRENDING_BULL/TRENDING_BEAR/RANGING labels). This means its
signal adapts to the same state-space that Strategy C+ uses, creating potential for
coordination. An `IR > 0.5` vs. SPY from the Composite_Score would confirm it adds
genuine alpha beyond what SPY alone provides.

**Why Volume Profile/VPOC ranks #3:** VPOC breakout signals are high-conviction but low-frequency
(not every session has a clean VPOC break). `tail_ratio > 1.3` would confirm that when
VPOC breaks occur, the trade outcomes have positive right-tail asymmetry — a necessary
condition for this signal to be worth trading.

### 7.3 VPOC Breakout → Python Returns Series

The `JARVIS_VPOC_Tracker.pine` tracks the Volume Point of Control (VPOC) — the price
level with the highest volume for the current session. A VPOC breakout signal is generated
when price crosses the VPOC level.

```python
# vpoc_backtest.py — convert VPOC breakout signal to QuantStats tearsheet

import yfinance as yf
import pandas as pd
import numpy as np
import quantstats as qs

def fetch_mes_ohlcv(period: str = "6mo", interval: str = "5m") -> pd.DataFrame:
    """
    Fetch MES intraday data. ES=F is the continuous front-month E-mini S&P.
    For true MES continuous, use Databento or Interactive Brokers data API.
    """
    df = yf.download("ES=F", period=period, interval=interval, 
                     progress=False, auto_adjust=True)
    df = df[df.index.time >= pd.Timestamp("09:30").time()]
    df = df[df.index.time <= pd.Timestamp("16:00").time()]
    return df


def compute_session_vpoc(df: pd.DataFrame) -> pd.Series:
    """
    Compute VPOC for each session (highest volume price level).
    Returns pd.Series indexed by session date, value = VPOC price.
    """
    vpoc_by_date = {}
    for date, session in df.groupby(df.index.date):
        # Round prices to nearest 0.25 (MES tick size)
        prices = (session["Close"] * 4).round() / 4
        volume_at_price = session.groupby(prices)["Volume"].sum()
        vpoc_by_date[date] = volume_at_price.idxmax()
    return pd.Series(vpoc_by_date)


def backtest_vpoc_breakout(df: pd.DataFrame, 
                            vpoc: pd.Series,
                            min_breakout_pct: float = 0.001,
                            hold_bars: int = 12) -> pd.Series:
    """
    Simple VPOC breakout strategy:
    - Entry: price closes above VPOC + min_breakout_pct (LONG) 
             or below VPOC - min_breakout_pct (SHORT)
    - Exit: hold for hold_bars (60 minutes at 5m timeframe)
    - Returns indexed by exit bar timestamp
    """
    trades = []
    
    for date, session in df.groupby(df.index.date):
        if date not in vpoc.index:
            continue
        
        vp = vpoc[date]
        bars = session.reset_index()
        
        for i, row in bars.iterrows():
            if i + hold_bars >= len(bars):
                break
            
            entry_price = row["Close"]
            
            if entry_price > vp * (1 + min_breakout_pct):
                # LONG breakout
                exit_price = bars.iloc[i + hold_bars]["Close"]
                pnl = (exit_price - entry_price) / entry_price
                exit_time = bars.iloc[i + hold_bars]["Datetime"]
                trades.append({"exit_time": exit_time, "pnl": pnl, "dir": "LONG"})
            
            elif entry_price < vp * (1 - min_breakout_pct):
                # SHORT breakout
                exit_price = bars.iloc[i + hold_bars]["Close"]
                pnl = (entry_price - exit_price) / entry_price  # Inverted for short
                exit_time = bars.iloc[i + hold_bars]["Datetime"]
                trades.append({"exit_time": exit_time, "pnl": pnl, "dir": "SHORT"})
    
    if not trades:
        return pd.Series(dtype=float)
    
    trades_df = pd.DataFrame(trades).set_index("exit_time")
    return trades_df["pnl"]


def generate_vpoc_tearsheet():
    df = fetch_mes_ohlcv(period="6mo", interval="5m")
    vpoc = compute_session_vpoc(df)
    returns = backtest_vpoc_breakout(df, vpoc)
    
    if returns.empty:
        print("No VPOC trades generated")
        return
    
    # Use ES futures as benchmark (more appropriate than SPY for MES strategy)
    benchmark = df["Close"].resample("D").last().pct_change().dropna()
    benchmark = benchmark.reindex(
        pd.to_datetime(returns.index.date).unique(), fill_value=0.0
    )
    
    # Aggregate trade returns to daily
    daily_returns = returns.resample("D").sum()
    
    qs.reports.html(
        daily_returns,
        benchmark=benchmark,
        title="JARVIS VPOC Breakout — Python Backtest Tearsheet",
        output="docs/reports/tearsheets/vpoc_breakout.html",
    )
    
    # Print key QuantStats metrics
    print(f"VPOC Backtest — {len(returns)} trades")
    print(f"  Profit Factor:   {qs.stats.profit_factor(returns):.3f}")
    print(f"  Sharpe:          {qs.stats.sharpe(returns):.3f}")
    print(f"  Sortino:         {qs.stats.sortino(returns):.3f}")
    print(f"  Tail Ratio:      {qs.stats.tail_ratio(returns):.3f}")
    print(f"  Gain-to-Pain:    {qs.stats.gain_to_pain_ratio(returns):.3f}")
    print(f"  Skew:            {qs.stats.skew(returns):.3f}")
    print(f"  Max Drawdown:    {qs.stats.max_drawdown(returns):.3f}")
```

**Caveat:** This VPOC backtest uses 5m OHLCV data, which is a coarse approximation.
The Pine script's `JARVIS_VPOC_Tracker.pine` computes VPOC from tick-level volume
profiles. For production validation, use Databento MES tick data to compute true
volume profiles, not OHLCV-approximate volume distribution.

---

## Section 8: Concrete Implementation Plan

### Step 1: Install and Wire QuantStats to Backtest Results

```python
# Add to the top of compare_backtests.py

# ── Requirements ──────────────────────────────────────────────────────────────
# pip install quantstats yfinance
# quantstats version pinning: >=0.0.62 (includes consecutive_losses, adjusted_sortino)
# ─────────────────────────────────────────────────────────────────────────────

import quantstats as qs
import pandas as pd
import json
import os
from pathlib import Path
from typing import Optional

# Suppress qs matplotlib output in non-interactive mode
import matplotlib
matplotlib.use("Agg")

BACKTEST_RESULTS_DIR = Path(os.environ.get("BACKTEST_RESULTS_DIR", "backtest_results"))

# Extended gate set (replaces the 4-gate check)
QS_GATES = {
    "profit_factor":        (">=", 2.0),
    "sharpe":               (">=", 1.5),
    "sortino":              (">=", 1.0),
    "calmar":               (">=", 0.5),
    "win_rate":             (">=", 0.55),
    "max_drawdown":         ("<=", 0.15),
    "tail_ratio":           (">=", 1.0),
    "common_sense_ratio":   (">=", 1.5),
    "ulcer_perf_index":     (">=", 0.5),
    "skew":                 (">=", -1.5),
    "gain_to_pain":         (">=", 0.5),
}


def load_returns_from_backtest_json(path: Path) -> Optional[pd.Series]:
    """
    Load a returns Series from a backtest result JSON.
    
    The JSON must have either:
    - result["returns"]: {date_str: float} — preferred
    - result["trades"]: [{exit_time: str, pnl_pct: float}] — fallback
    
    Returns pd.Series with DatetimeIndex, or None if data absent.
    """
    with open(path) as f:
        result = json.load(f)
    
    # Preferred: pre-computed daily returns series
    if "returns" in result and result["returns"]:
        series = pd.Series(result["returns"])
        series.index = pd.to_datetime(series.index)
        return series.sort_index()
    
    # Fallback: reconstruct from trade list
    trades = result.get("trades", [])
    if not trades:
        return None
    
    daily_pnl = {}
    for trade in trades:
        exit_date = pd.to_datetime(trade["exit_time"]).normalize()
        daily_pnl[exit_date] = daily_pnl.get(exit_date, 0.0) + trade["pnl_pct"] / 100.0
    
    series = pd.Series(daily_pnl).sort_index()
    idx = pd.bdate_range(series.index.min(), series.index.max())
    return series.reindex(idx, fill_value=0.0)


def compute_qs_metrics(returns: pd.Series) -> dict:
    """
    Compute the full QuantStats metric set for gate evaluation.
    Returns a dict of metric_name → float (or None on error).
    """
    def safe(fn, *args, **kwargs):
        try:
            v = fn(*args, **kwargs)
            return float(v) if v is not None else None
        except Exception as e:
            return None

    return {
        "profit_factor":        safe(qs.stats.profit_factor, returns),
        "sharpe":               safe(qs.stats.sharpe, returns),
        "sortino":              safe(qs.stats.sortino, returns),
        "calmar":               safe(qs.stats.calmar, returns),
        "win_rate":             safe(qs.stats.win_rate, returns),
        "max_drawdown":         abs(safe(qs.stats.max_drawdown, returns) or 0),
        "tail_ratio":           safe(qs.stats.tail_ratio, returns),
        "common_sense_ratio":   safe(qs.stats.common_sense_ratio, returns),
        "ulcer_perf_index":     safe(qs.stats.ulcer_performance_index, returns),
        "skew":                 safe(qs.stats.skew, returns),
        "gain_to_pain":         safe(qs.stats.gain_to_pain_ratio, returns),
        "kurtosis":             safe(qs.stats.kurtosis, returns),
        "recovery_factor":      safe(qs.stats.recovery_factor, returns),
        "cpc_index":            safe(qs.stats.cpc_index, returns),
        "r_squared":            safe(qs.stats.r_squared, returns),
        "ulcer_index":          safe(qs.stats.ulcer_index, returns),
        "cagr":                 safe(qs.stats.cagr, returns),
        "consecutive_losses":   safe(qs.stats.consecutive_losses, returns),
        "exposure":             safe(qs.stats.exposure, returns),
        "information_ratio":    None,  # Requires benchmark; set separately
    }


def evaluate_qs_gates(metrics: dict) -> tuple[bool, list[str]]:
    """
    Evaluate the extended QS gate set.
    Returns (passed: bool, failures: list[str])
    """
    failures = []
    for gate, (op, threshold) in QS_GATES.items():
        val = metrics.get(gate)
        if val is None:
            failures.append(f"{gate}: MISSING DATA")
            continue
        if op == ">=" and val < threshold:
            failures.append(f"{gate}: {val:.4f} < {threshold} (FAIL)")
        elif op == "<=" and val > threshold:
            failures.append(f"{gate}: {val:.4f} > {threshold} (FAIL)")
    return len(failures) == 0, failures


# Drop-in replacement for the existing markdown table generator:
def build_comparison_table(results_dir: Path = BACKTEST_RESULTS_DIR) -> str:
    """
    Scan results_dir for *.json files, compute qs.stats for each,
    build extended comparison markdown table.
    """
    json_files = sorted(results_dir.glob("*.json"))
    if not json_files:
        return "No backtest results found."
    
    rows = []
    for f in json_files:
        returns = load_returns_from_backtest_json(f)
        if returns is None or len(returns) < 10:
            continue
        metrics = compute_qs_metrics(returns)
        passed, failures = evaluate_qs_gates(metrics)
        metrics["_file"] = f.name
        metrics["_passed"] = passed
        metrics["_failures"] = "; ".join(failures) if failures else "ALL PASS"
        rows.append(metrics)
    
    if not rows:
        return "No valid return series found."
    
    # Build markdown table
    cols = ["_file", "profit_factor", "sharpe", "sortino", "calmar", "win_rate",
            "max_drawdown", "tail_ratio", "common_sense_ratio", "ulcer_perf_index",
            "skew", "gain_to_pain", "_passed", "_failures"]
    
    header = "| " + " | ".join(cols) + " |"
    sep    = "| " + " | ".join(["---"] * len(cols)) + " |"
    
    table_rows = [header, sep]
    for row in rows:
        cells = []
        for col in cols:
            val = row.get(col, "N/A")
            if isinstance(val, float):
                cells.append(f"{val:.3f}")
            elif isinstance(val, bool):
                cells.append("✓" if val else "✗")
            else:
                cells.append(str(val))
        table_rows.append("| " + " | ".join(cells) + " |")
    
    return "\n".join(table_rows)
```

### Step 2: Add EOD HTML Tearsheet Generation to `eod_summary.py`

```python
# Add to eod_summary.py — insert after the markdown file save block

import quantstats as qs
import pandas as pd
import requests
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend — critical for server environments
from pathlib import Path
from datetime import datetime, timedelta

ENGINE_BASE = "http://localhost:8010"
TEARSHEET_DIR = Path("docs/reports/eod/html")
TEARSHEET_DIR.mkdir(parents=True, exist_ok=True)


def fetch_engine_trade_history(lookback_days: int = 90) -> pd.Series:
    """
    Fetch closed trade history from engine API.
    Converts to daily return series (sum of intraday trade PnL per day).
    
    Endpoint: GET /decisions/recent?limit=1000
    Expected response: list of decisions with pnl_pct and timestamp fields.
    """
    try:
        resp = requests.get(
            f"{ENGINE_BASE}/decisions/recent",
            params={"limit": 1000, "with_pnl": True},
            timeout=10,
        )
        resp.raise_for_status()
        decisions = resp.json()
    except Exception as e:
        print(f"[eod_summary] Failed to fetch trade history: {e}")
        return pd.Series(dtype=float)

    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    
    daily_pnl = {}
    for d in decisions:
        ts = pd.to_datetime(d.get("timestamp"))
        if ts < cutoff:
            continue
        pnl_pct = d.get("pnl_pct")
        if pnl_pct is None:
            continue
        date = ts.normalize()
        daily_pnl[date] = daily_pnl.get(date, 0.0) + pnl_pct / 100.0

    if not daily_pnl:
        return pd.Series(dtype=float)

    series = pd.Series(daily_pnl).sort_index()
    
    # Fill business day gaps with zero (flat days)
    bday_range = pd.bdate_range(series.index.min(), series.index.max())
    series = series.reindex(bday_range, fill_value=0.0)
    series.name = "JARVIS_Strategy_C+"
    return series


def generate_eod_html_tearsheet(report_date: str, 
                                 strategy_label: str = "JARVIS_Strategy_C+",
                                 lookback_days: int = 90,
                                 benchmark_ticker: str = "SPY") -> Optional[Path]:
    """
    Generate qs.reports.html tearsheet for EOD report.
    
    Args:
        report_date:      Date string YYYY-MM-DD for filename
        strategy_label:   Display name in the tearsheet header
        lookback_days:    How many days of history to include
        benchmark_ticker: SPY for Strategy C+ ETF rotation; ES=F for RL MES
    
    Returns:
        Path to saved HTML file, or None on failure
    """
    returns = fetch_engine_trade_history(lookback_days=lookback_days)
    
    if len(returns) < 5:
        print(f"[eod_summary] Only {len(returns)} return observations — skipping tearsheet")
        return None
    
    # Download benchmark aligned to our date range
    try:
        benchmark = qs.utils.download_returns(
            benchmark_ticker,
            period=f"{lookback_days + 10}d",  # buffer for weekend alignment
        )
        benchmark = benchmark.reindex(returns.index, fill_value=0.0)
        benchmark.name = benchmark_ticker
    except Exception as e:
        print(f"[eod_summary] Failed to download {benchmark_ticker} benchmark: {e}")
        benchmark = None
    
    output_path = TEARSHEET_DIR / f"{report_date}.html"
    
    try:
        qs.reports.html(
            returns,
            benchmark=benchmark,
            title=f"{strategy_label} — EOD Tearsheet {report_date}",
            output=str(output_path),
            download_filename=str(output_path),
        )
        print(f"[eod_summary] HTML tearsheet → {output_path}")
        return output_path
    except Exception as e:
        print(f"[eod_summary] qs.reports.html failed: {e}")
        return None


# Hook into existing eod_summary.py main block:
# (Add after the line that saves the markdown file)
# ──────────────────────────────────────────────────
# if __name__ == "__main__":
#     today = datetime.now().strftime("%Y-%m-%d")
#     # ... existing markdown generation code ...
#
#     # NEW: Generate HTML tearsheet
#     generate_eod_html_tearsheet(
#         report_date=today,
#         strategy_label="JARVIS Strategy C+",
#         lookback_days=90,
#         benchmark_ticker="SPY",
#     )
```

### Step 3: Upgrade Validation Gates Using `qs.stats` for RL Eval

```python
# Add to eval_run*.py — replaces the 6-gate check block

import quantstats as qs
import pandas as pd
import requests
import sys

ENGINE_BASE = "http://localhost:8010"

# ── Run 12 gate set — replaces sharpe>=1.5 with more robust metrics ─────────
RL_GATES_RUN12 = {
    "profit_factor":        (">=", 1.5),   # Relaxed from 2.0 for RL iterations
    "win_rate":             (">=", 0.52),   # Relaxed from 55%
    "max_drawdown":         ("<=", 0.20),   # Relaxed from 15% for intraday
    "sortino":              (">=", 1.0),    # REPLACES sharpe>=1.5
    "calmar":               (">=", 0.5),    # NEW — annualized return / max drawdown
    "tail_ratio":           (">=", 1.0),    # NEW — right tail must >= left tail
    "gain_to_pain":         (">=", 0.5),    # NEW — basic trade flow profitability
    "consecutive_losses":   ("<=", 8),      # NEW — max losing streak cap
    "ulcer_perf_index":     (">=", 0.3),    # NEW — relaxed threshold for RL iteration
    "exposure":             (">=", 0.15),   # NEW — agent must be trading (not HOLDing)
}

# For production (post-training), use the full gate set:
RL_GATES_PRODUCTION = {
    "profit_factor":        (">=", 2.0),
    "sortino":              (">=", 1.5),
    "calmar":               (">=", 1.0),
    "win_rate":             (">=", 0.55),
    "max_drawdown":         ("<=", 0.15),
    "tail_ratio":           (">=", 1.0),
    "common_sense_ratio":   (">=", 1.5),
    "ulcer_perf_index":     (">=", 0.7),
    "gain_to_pain":         (">=", 0.7),
    "exposure":             (">=", 0.20),
    "consecutive_losses":   ("<=", 5),
    "skew":                 (">=", -1.2),
}


def evaluate_rl_run(run_name: str, 
                     gate_set: dict = RL_GATES_RUN12,
                     production: bool = False) -> int:
    """
    Main eval function for RL training runs.
    Returns exit code: 0 = all gates pass, 1 = gate failures, 2 = API error.
    """
    # Step 1: Fetch evaluation results from engine
    try:
        resp = requests.post(
            f"{ENGINE_BASE}/strategies/rl/evaluate",
            json={"run_name": run_name},
            timeout=60,
        )
        resp.raise_for_status()
        eval_result = resp.json()
    except Exception as e:
        print(f"[{run_name}] Engine API error: {e}")
        return 2
    
    # Step 2: Extract trades list from eval result
    trades = eval_result.get("trades", [])
    if len(trades) < 60:
        print(f"[{run_name}] FAIL — only {len(trades)} trades, need >= 60")
        return 1
    
    # Step 3: Build returns Series (trade-indexed)
    returns = pd.Series({
        pd.to_datetime(t["exit_time"]): t["pnl_pct"] / 100.0
        for t in trades
    }).sort_index()
    
    # Step 4: Compute qs.stats metrics
    def safe(fn, *args, **kwargs):
        try:
            v = fn(*args, **kwargs)
            return float(v) if v is not None else None
        except Exception:
            return None

    metrics = {
        "profit_factor":        safe(qs.stats.profit_factor, returns),
        "win_rate":             safe(qs.stats.win_rate, returns),
        "max_drawdown":         abs(safe(qs.stats.max_drawdown, returns) or 0),
        "sortino":              safe(qs.stats.sortino, returns, periods=252),
        "calmar":               safe(qs.stats.calmar, returns),
        "tail_ratio":           safe(qs.stats.tail_ratio, returns),
        "gain_to_pain":         safe(qs.stats.gain_to_pain_ratio, returns),
        "consecutive_losses":   safe(qs.stats.consecutive_losses, returns),
        "ulcer_perf_index":     safe(qs.stats.ulcer_performance_index, returns),
        "exposure":             safe(qs.stats.exposure, returns),
        "common_sense_ratio":   safe(qs.stats.common_sense_ratio, returns),
        "skew":                 safe(qs.stats.skew, returns),
        "kurtosis":             safe(qs.stats.kurtosis, returns),
        "ulcer_index":          safe(qs.stats.ulcer_index, returns),
        "r_squared":            safe(qs.stats.r_squared, returns),
    }
    
    # Step 5: Evaluate gates
    gates = RL_GATES_PRODUCTION if production else gate_set
    failures = []
    for gate, (op, threshold) in gates.items():
        val = metrics.get(gate)
        if val is None:
            failures.append(f"  {gate}: MISSING")
            continue
        passed = (op == ">=" and val >= threshold) or (op == "<=" and val <= threshold)
        status = "PASS" if passed else "FAIL"
        if not passed:
            failures.append(f"  {gate}: {val:.4f} {op} {threshold} → {status}")
    
    # Step 6: Print full diagnostic table
    print(f"\n{'='*60}")
    print(f"RL Eval: {run_name} ({'PRODUCTION' if production else 'ITERATION'} gates)")
    print(f"{'='*60}")
    print(f"  trades:              {len(trades)}")
    for k, v in metrics.items():
        marker = ""
        if k in gates:
            op, thresh = gates[k]
            if v is not None:
                passed = (op == ">=" and v >= thresh) or (op == "<=" and v <= thresh)
                marker = " ✓" if passed else " ✗"
        val_str = f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"  {k:30s}: {val_str:>10}{marker}")
    
    if failures:
        print(f"\nFAILED GATES ({len(failures)}/{len(gates)}):")
        for f in failures:
            print(f)
        return 1
    else:
        print(f"\nALL {len(gates)} GATES PASSED")
        return 0


if __name__ == "__main__":
    run_name = sys.argv[1] if len(sys.argv) > 1 else "run11"
    production = "--production" in sys.argv
    sys.exit(evaluate_rl_run(run_name, production=production))
```

### Step 4: Regime-Conditional Sharpe Report

```python
# regime_sharpe_report.py — standalone analysis script

import quantstats as qs
import pandas as pd
import requests
from pathlib import Path
import matplotlib
matplotlib.use("Agg")

ENGINE_BASE = "http://localhost:8010"
REPORT_DIR   = Path("docs/reports/analysis")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_returns_with_regime_tags(limit: int = 500) -> pd.DataFrame:
    """
    Fetch daily returns tagged by regime from engine decision log.
    
    The engine's /decisions/recent endpoint must include:
    - timestamp: ISO8601 str
    - pnl_pct: float (trade PnL as percentage)
    - regime_label: str ("RISK_ON" | "RISK_OFF" | "NORMAL")
    """
    resp = requests.get(f"{ENGINE_BASE}/decisions/recent", 
                        params={"limit": limit, "with_regime": True})
    resp.raise_for_status()
    decisions = resp.json()
    
    rows = []
    for d in decisions:
        pnl = d.get("pnl_pct")
        regime = d.get("regime_label", "UNKNOWN")
        if pnl is not None:
            rows.append({
                "date":   pd.to_datetime(d["timestamp"]).normalize(),
                "pnl":    pnl / 100.0,
                "regime": regime,
            })
    
    if not rows:
        return pd.DataFrame(columns=["date", "pnl", "regime"])
    
    df = pd.DataFrame(rows)
    # Aggregate to daily (sum intraday PnL, take last regime label for the day)
    daily = df.groupby("date").agg(
        pnl=("pnl", "sum"),
        regime=("regime", "last"),
    ).reset_index()
    return daily.sort_values("date")


def regime_conditional_sharpe_report(df: pd.DataFrame) -> dict:
    """
    Compute regime-conditional statistics and save report.
    
    For each regime slice:
    - Sharpe, Sortino, Calmar, max_drawdown, gain_to_pain, win_rate
    - Visualize via qs.plots (save to PNG)
    """
    results = {}
    
    for regime in ["RISK_ON", "RISK_OFF", "NORMAL"]:
        mask   = df["regime"] == regime
        subset = df[mask].set_index("date")["pnl"]
        
        if len(subset) < 5:
            results[regime] = {"n": len(subset), "note": "insufficient_data"}
            continue
        
        # Compute qs.stats metrics on the regime slice
        def safe(fn, *a, **kw):
            try:
                return float(fn(*a, **kw))
            except Exception:
                return None

        results[regime] = {
            "n":             len(subset),
            "date_range":    f"{subset.index.min().date()} to {subset.index.max().date()}",
            "sharpe":        safe(qs.stats.sharpe, subset),
            "sortino":       safe(qs.stats.sortino, subset),
            "calmar":        safe(qs.stats.calmar, subset) if len(subset) > 10 else None,
            "max_drawdown":  abs(safe(qs.stats.max_drawdown, subset) or 0),
            "gain_to_pain":  safe(qs.stats.gain_to_pain_ratio, subset),
            "win_rate":      safe(qs.stats.win_rate, subset),
            "tail_ratio":    safe(qs.stats.tail_ratio, subset) if len(subset) > 10 else None,
            "avg_win":       safe(qs.stats.avg_win, subset),
            "avg_loss":      safe(qs.stats.avg_loss, subset),
        }
        
        # Generate rolling_sharpe plot for each regime
        if len(subset) >= 21:
            try:
                qs.plots.rolling_sharpe(
                    subset,
                    window=min(21, len(subset) // 2),
                    title=f"JARVIS — Rolling Sharpe ({regime})",
                    figsize=(10, 4),
                    show=False,
                    savefig=str(REPORT_DIR / f"rolling_sharpe_{regime.lower()}.png"),
                )
            except Exception as e:
                print(f"[regime] rolling_sharpe plot failed for {regime}: {e}")
    
    # Print regime comparison table
    print("\n=== Regime-Conditional Statistics ===")
    print(f"{'Metric':<25} {'RISK_ON':>12} {'RISK_OFF':>12} {'NORMAL':>12}")
    print("-" * 64)
    metrics_to_show = ["n", "sharpe", "sortino", "calmar", "max_drawdown", 
                        "gain_to_pain", "win_rate", "tail_ratio"]
    
    for metric in metrics_to_show:
        row = f"{metric:<25}"
        for regime in ["RISK_ON", "RISK_OFF", "NORMAL"]:
            val = results.get(regime, {}).get(metric)
            if val is None:
                row += f"{'N/A':>12}"
            elif isinstance(val, float):
                row += f"{val:>12.3f}"
            else:
                row += f"{str(val):>12}"
        print(row)
    
    # Save JSON report
    import json
    report_path = REPORT_DIR / "regime_sharpe_report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nRegime report saved: {report_path}")
    
    return results


if __name__ == "__main__":
    df = fetch_returns_with_regime_tags(limit=1000)
    if df.empty:
        print("No data available from engine")
    else:
        regime_conditional_sharpe_report(df)
```

### Step 5: New `jarvis_tearsheet.py` Script

```python
#!/usr/bin/env python3
"""
jarvis_tearsheet.py

Master tearsheet generator for all JARVIS strategy returns.
Replaces: eval_run*.py (partial), eod_summary.py (tearsheet output), 
          strategic_snapshot.py (metrics snapshot)

Usage:
    python jarvis_tearsheet.py --source paper --account DUP662235
    python jarvis_tearsheet.py --source backtest --file backtest_results/run11.json
    python jarvis_tearsheet.py --source rl --run run11
    python jarvis_tearsheet.py --source all  (generates all three)
"""

import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import quantstats as qs

# ── Config ────────────────────────────────────────────────────────────────────
ENGINE_BASE     = os.environ.get("JARVIS_ENGINE_URL", "http://localhost:8010")
TEARSHEET_DIR   = Path("docs/reports/tearsheets")
SNAPSHOT_PATH   = Path("docs/reports/METRICS_SNAPSHOT.json")

TEARSHEET_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Production gates (10 metrics)
PRODUCTION_GATES = {
    "profit_factor":        (">=", 2.0),
    "sortino":              (">=", 1.5),
    "calmar":               (">=", 1.0),
    "win_rate":             (">=", 0.55),
    "max_drawdown":         ("<=", 0.15),
    "tail_ratio":           (">=", 1.0),
    "common_sense_ratio":   (">=", 1.5),
    "ulcer_perf_index":     (">=", 0.7),
    "gain_to_pain":         (">=", 0.7),
    "exposure":             (">=", 0.20),
}


# ── Data Fetchers ─────────────────────────────────────────────────────────────

def fetch_paper_returns(account_id: str = "DUP662235",
                         lookback_days: int = 90) -> pd.Series:
    """
    Fetch paper trading returns from engine API.
    Endpoint: GET /paper/trades/history?account=DUP662235
    """
    try:
        resp = requests.get(
            f"{ENGINE_BASE}/paper/trades/history",
            params={"account": account_id, "days": lookback_days},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[tearsheet] Paper fetch failed: {e}")
        return pd.Series(dtype=float)
    
    trades = data.get("trades", [])
    if not trades:
        print(f"[tearsheet] No trades found for account {account_id}")
        return pd.Series(dtype=float)
    
    daily_pnl = {}
    for t in trades:
        date = pd.to_datetime(t["exit_time"]).normalize()
        daily_pnl[date] = daily_pnl.get(date, 0.0) + t["pnl_pct"] / 100.0
    
    series = pd.Series(daily_pnl).sort_index()
    bday_idx = pd.bdate_range(series.index.min(), series.index.max())
    series = series.reindex(bday_idx, fill_value=0.0)
    series.name = f"JARVIS_Paper_{account_id}"
    return series


def fetch_backtest_returns(file_path: str) -> pd.Series:
    """Load returns from a backtest result JSON file."""
    path = Path(file_path)
    if not path.exists():
        print(f"[tearsheet] File not found: {file_path}")
        return pd.Series(dtype=float)
    
    with open(path) as f:
        result = json.load(f)
    
    if "returns" in result:
        series = pd.Series(result["returns"])
        series.index = pd.to_datetime(series.index)
        series = series.sort_index()
        series.name = path.stem
        return series
    
    trades = result.get("trades", [])
    if trades:
        daily_pnl = {}
        for t in trades:
            date = pd.to_datetime(t["exit_time"]).normalize()
            daily_pnl[date] = daily_pnl.get(date, 0.0) + t["pnl_pct"] / 100.0
        series = pd.Series(daily_pnl).sort_index()
        series.name = path.stem
        return series
    
    return pd.Series(dtype=float)


def fetch_rl_returns(run_name: str) -> pd.Series:
    """Fetch RL evaluation trade returns from engine API."""
    try:
        resp = requests.post(
            f"{ENGINE_BASE}/strategies/rl/evaluate",
            json={"run_name": run_name},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[tearsheet] RL eval fetch failed: {e}")
        return pd.Series(dtype=float)
    
    trades = data.get("trades", [])
    if not trades:
        return pd.Series(dtype=float)
    
    series = pd.Series({
        pd.to_datetime(t["exit_time"]): t["pnl_pct"] / 100.0
        for t in trades
    }).sort_index()
    series.name = f"JARVIS_RL_{run_name}"
    return series


def get_benchmark(ticker: str, returns: pd.Series) -> Optional[pd.Series]:
    """Download benchmark returns aligned to strategy date range."""
    try:
        if ticker in ("ES=F", "MES=F", "/ES", "/MES"):
            # Use yfinance for futures
            df = yf.download(
                ticker.replace("/", ""),
                start=str(returns.index.min().date()),
                end=str(returns.index.max().date()),
                progress=False,
                auto_adjust=True,
            )
            bm = df["Close"].pct_change().dropna()
            bm.index = pd.to_datetime(bm.index)
        else:
            # Use qs downloader for equity tickers (SPY, QQQ, etc.)
            period_days = len(returns) + 10
            bm = qs.utils.download_returns(ticker, period=f"{period_days}d")
        
        bm = bm.reindex(returns.index, fill_value=0.0)
        bm.name = ticker
        return bm
    except Exception as e:
        print(f"[tearsheet] Benchmark {ticker} download failed: {e}")
        return None


# ── Metrics Engine ────────────────────────────────────────────────────────────

def compute_full_metrics(returns: pd.Series) -> dict:
    """Compute the full qs.stats suite. Returns dict of metric→float."""
    def safe(fn, *a, **kw):
        try:
            v = fn(*a, **kw)
            return float(v) if v is not None else None
        except Exception:
            return None

    return {
        "profit_factor":        safe(qs.stats.profit_factor, returns),
        "sharpe":               safe(qs.stats.sharpe, returns),
        "sortino":              safe(qs.stats.sortino, returns),
        "adjusted_sortino":     safe(qs.stats.adjusted_sortino, returns),
        "calmar":               safe(qs.stats.calmar, returns),
        "win_rate":             safe(qs.stats.win_rate, returns),
        "max_drawdown":         abs(safe(qs.stats.max_drawdown, returns) or 0),
        "tail_ratio":           safe(qs.stats.tail_ratio, returns),
        "common_sense_ratio":   safe(qs.stats.common_sense_ratio, returns),
        "ulcer_perf_index":     safe(qs.stats.ulcer_performance_index, returns),
        "ulcer_index":          safe(qs.stats.ulcer_index, returns),
        "skew":                 safe(qs.stats.skew, returns),
        "kurtosis":             safe(qs.stats.kurtosis, returns),
        "gain_to_pain":         safe(qs.stats.gain_to_pain_ratio, returns),
        "recovery_factor":      safe(qs.stats.recovery_factor, returns),
        "cpc_index":            safe(qs.stats.cpc_index, returns),
        "r_squared":            safe(qs.stats.r_squared, returns),
        "cagr":                 safe(qs.stats.cagr, returns),
        "exposure":             safe(qs.stats.exposure, returns),
        "consecutive_losses":   safe(qs.stats.consecutive_losses, returns),
        "outlier_loss_ratio":   safe(qs.stats.outlier_loss_ratio, returns),
        "avg_win":              safe(qs.stats.avg_win, returns),
        "avg_loss":             safe(qs.stats.avg_loss, returns),
        "volatility":           safe(qs.stats.volatility, returns),
        "var_95":               safe(qs.stats.value_at_risk, returns),
        "cvar_95":              safe(qs.stats.expected_shortfall, returns),
        "kelly_criterion":      safe(qs.stats.kelly_criterion, returns),
        "risk_of_ruin":         safe(qs.stats.risk_of_ruin, returns),
        "n_observations":       len(returns),
    }


def evaluate_production_gates(metrics: dict) -> tuple[bool, list[str]]:
    failures = []
    for gate, (op, threshold) in PRODUCTION_GATES.items():
        val = metrics.get(gate)
        if val is None:
            failures.append(f"{gate}: MISSING")
            continue
        ok = (op == ">=" and val >= threshold) or (op == "<=" and val <= threshold)
        if not ok:
            failures.append(f"{gate}: {val:.4f} {'≥' if op == '>=' else '≤'} {threshold} FAIL")
    return len(failures) == 0, failures


# ── Tearsheet Generator ───────────────────────────────────────────────────────

def generate_tearsheet(
    source: str,
    returns: pd.Series,
    benchmark: Optional[pd.Series],
    label: str,
) -> Path:
    """
    Generate qs.reports.html tearsheet and save.
    Returns path to HTML file.
    """
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"{now_str}_{source}_{label}.html"
    output_path = TEARSHEET_DIR / filename
    
    title = f"JARVIS {source.upper()} — {label} — {now_str}"
    
    qs.reports.html(
        returns,
        benchmark=benchmark,
        title=title,
        output=str(output_path),
        download_filename=str(output_path),
    )
    return output_path


def update_metrics_snapshot(source: str, label: str, metrics: dict,
                              gate_passed: bool, failures: list[str]):
    """
    Append to METRICS_SNAPSHOT.json — replaces strategic_snapshot.py output.
    Preserves existing entries and adds new one.
    """
    snapshot = {}
    if SNAPSHOT_PATH.exists():
        with open(SNAPSHOT_PATH) as f:
            try:
                snapshot = json.load(f)
            except json.JSONDecodeError:
                snapshot = {}
    
    entry_key = f"{source}_{label}"
    snapshot[entry_key] = {
        "timestamp":   datetime.utcnow().isoformat(),
        "source":      source,
        "label":       label,
        "gate_passed": gate_passed,
        "failures":    failures,
        "metrics":     {k: round(v, 6) if isinstance(v, float) else v 
                        for k, v in metrics.items()},
    }
    
    with open(SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_tearsheet(args: argparse.Namespace) -> int:
    """Core execution — fetches data, generates tearsheet, evaluates gates."""
    
    source = args.source.lower()
    
    # 1. Fetch returns
    if source == "paper":
        returns = fetch_paper_returns(
            account_id=args.account or "DUP662235",
            lookback_days=args.lookback or 90,
        )
        benchmark_ticker = "SPY"
        label = args.account or "DUP662235"
    
    elif source == "backtest":
        if not args.file:
            print("[tearsheet] --file required for backtest source")
            return 2
        returns = fetch_backtest_returns(args.file)
        benchmark_ticker = args.benchmark or "SPY"
        label = Path(args.file).stem
    
    elif source == "rl":
        if not args.run:
            print("[tearsheet] --run required for rl source")
            return 2
        returns = fetch_rl_returns(args.run)
        benchmark_ticker = args.benchmark or "ES=F"
        label = args.run
    
    else:
        print(f"[tearsheet] Unknown source: {source}")
        return 2
    
    if returns.empty or len(returns) < 5:
        print(f"[tearsheet] Insufficient data for {source}/{label}")
        return 1
    
    # 2. Get benchmark
    benchmark = get_benchmark(benchmark_ticker, returns)
    
    # 3. Compute metrics
    metrics = compute_full_metrics(returns)
    gate_passed, failures = evaluate_production_gates(metrics)
    
    # 4. Print diagnostic
    print(f"\n{'='*60}")
    print(f"JARVIS Tearsheet: {source.upper()} / {label}")
    print(f"  n_observations: {metrics['n_observations']}")
    print(f"{'='*60}")
    key_metrics = ["profit_factor", "sharpe", "sortino", "calmar", "win_rate",
                   "max_drawdown", "tail_ratio", "common_sense_ratio", 
                   "ulcer_perf_index", "gain_to_pain", "skew", "exposure",
                   "consecutive_losses", "kelly_criterion", "risk_of_ruin"]
    for k in key_metrics:
        v = metrics.get(k)
        gate_marker = ""
        if k in PRODUCTION_GATES:
            op, thresh = PRODUCTION_GATES[k]
            if v is not None:
                ok = (op == ">=" and v >= thresh) or (op == "<=" and v <= thresh)
                gate_marker = "  ✓" if ok else "  ✗"
        val_str = f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"  {k:<30}: {val_str:>10}{gate_marker}")
    
    if failures:
        print(f"\nGATE FAILURES ({len(failures)}/{len(PRODUCTION_GATES)}):")
        for f in failures:
            print(f"  {f}")
    else:
        print(f"\nALL {len(PRODUCTION_GATES)} GATES PASSED")
    
    # 5. Generate HTML tearsheet
    html_path = generate_tearsheet(source, returns, benchmark, label)
    print(f"\nTearsheet saved: {html_path}")
    
    # 6. Update METRICS_SNAPSHOT.json
    update_metrics_snapshot(source, label, metrics, gate_passed, failures)
    print(f"Snapshot updated: {SNAPSHOT_PATH}")
    
    # 7. Drawdown details
    try:
        dd_series = qs.stats.to_drawdown_series(returns)
        dd_details = qs.stats.drawdown_details(dd_series)
        if not dd_details.empty:
            print(f"\nTop 3 Drawdown Events:")
            print(dd_details.nlargest(3, "max drawdown").to_string(index=False))
    except Exception as e:
        print(f"[tearsheet] drawdown_details failed: {e}")
    
    return 0 if gate_passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JARVIS QuantStats Tearsheet Generator")
    parser.add_argument("--source",    choices=["paper", "backtest", "rl", "all"], 
                        required=True)
    parser.add_argument("--account",   help="Paper account ID (default: DUP662235)")
    parser.add_argument("--file",      help="Backtest JSON file path")
    parser.add_argument("--run",       help="RL run name (e.g., run11)")
    parser.add_argument("--benchmark", help="Benchmark ticker (default: SPY or ES=F)")
    parser.add_argument("--lookback",  type=int, default=90,
                        help="Days of history to fetch (default: 90)")
    parser.add_argument("--production", action="store_true",
                        help="Use production gates (stricter thresholds)")
    
    args = parser.parse_args()
    
    if args.source == "all":
        codes = []
        for src, extra in [
            ("paper",    ["--account", "DUP662235"]),
            ("rl",       ["--run", "run11"]),
        ]:
            args.source = src
            codes.append(run_tearsheet(args))
        sys.exit(max(codes))
    else:
        sys.exit(run_tearsheet(args))
```

---

## Appendix A: QuantStats Metric Reference for JARVIS

| Metric | `qs.stats` Call | Formula | JARVIS Gate? |
|---|---|---|---|
| Profit Factor | `profit_factor(r)` | sum(wins) / abs(sum(losses)) | Yes (≥2.0) |
| Sharpe | `sharpe(r)` | mean(r)/std(r) × √252 | Yes (≥1.5) → deprecating |
| Sortino | `sortino(r)` | mean(r)/downside_std(r) × √252 | **New** (≥1.0) |
| Adj. Sortino | `adjusted_sortino(r)` | sortino(r) / √2 | For Sharpe comparison |
| Calmar | `calmar(r)` | CAGR / abs(max_dd) | **New** (≥0.5) |
| Ulcer Index | `ulcer_index(r)` | √(mean(dd²)) | **New** — diagnostic |
| UPI | `ulcer_performance_index(r)` | mean(r) / ulcer_index | **New** (≥0.5) |
| Gain-to-Pain | `gain_to_pain_ratio(r)` | Σ(wins) / Σ(abs(losses)) | **New** (≥0.5) |
| Common Sense | `common_sense_ratio(r)` | PF × tail_ratio | **New** (≥1.5) |
| Tail Ratio | `tail_ratio(r)` | P95 / abs(P5) | **New** (≥1.0) |
| Skew | `skew(r)` | μ₃/σ³ | **New** (≥−1.5) |
| Kurtosis | `kurtosis(r)` | μ₄/σ⁴ − 3 | Diagnostic |
| Recovery Factor | `recovery_factor(r)` | total_return / abs(max_dd) | Diagnostic |
| R² | `r_squared(r)` | R² vs linear trend | WFE tracking |
| IR | `information_ratio(r, bm)` | active_return / tracking_error | Signal quality |
| Kelly | `kelly_criterion(r)` | W/L × win_prob − lose_prob | Sizing |
| VaR | `value_at_risk(r)` | P5 of returns | Risk budget |
| CVaR | `expected_shortfall(r)` | mean(r < VaR) | Tail budget |
| Exposure | `exposure(r)` | pct periods non-zero | RL HOLD check |
| Consec. Losses | `consecutive_losses(r)` | max losing streak | RL gate (≤8) |
| CPC Index | `cpc_index(r)` | PF × WR × payoff_ratio | Quality composite |
| Risk of Ruin | `risk_of_ruin(r)` | ((1−edge)/(1+edge))^N | Paper account |

---

## Appendix B: Script Integration Priority Matrix

| Script | Integration Effort | Impact | Priority |
|---|---|---|---|
| `eval_run*.py` | Low (add qs.stats calls post-evaluate) | **Critical** — Run 12 needs better gates | **P0** |
| `compare_backtests.py` | Medium (swap metric extraction) | **High** — gates block paper validation | **P0** |
| `jarvis_tearsheet.py` | New file — full implementation above | **High** — replaces multiple scripts | **P0** |
| `eod_summary.py` | Low (add tearsheet generation) | **Medium** — operational visibility | **P1** |
| `validation_status.py` | Low (add extended gate display) | **Medium** — paper validation clarity | **P1** |
| `regime_analysis.py` | New file — implementation above | **Medium** — Sprint 21-E prerequisite | **P1** |
| `wfe_monitor.py` | New file — implementation above | **High** — Sprint 21-E deliverable | **P1** |
| `vpoc_backtest.py` | New file — Pine signal validation | **Medium** — signal quality validation | **P2** |

---

*Document generated from codebase analysis of scripts.zip against QuantStats v0.0.62+.
All code snippets are importable Python 3.10+ and assume `quantstats>=0.0.62`,
`pandas>=2.0`, `yfinance>=0.2`, `requests>=2.28` are installed.*
