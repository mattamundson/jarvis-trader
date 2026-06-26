"""Turn-of-month — DARK forward paper-shadow (observe-only).

The honest next gate for the turn-of-month candidate (the first stationary, cost-
surviving, multi-regime edge of the arc; see SESSION_ANOMALY_FINDINGS.md). The
backtest established the prior on SPY 1993-2026; a *forward* record tests whether
the edge persists out-of-sample, post-inception.

DARK = observe-only, exactly like ``spread_paper_track``:
  * NO orders, NO live DB, nothing tradeable is touched.
  * Each tick records realized turn-of-month close-to-close returns into an ISOLATED
    JSONL ledger under the MAIN-checkout ``engine/data/tom_paper_track/`` (durable;
    survives a worktree prune).
  * Only TOM days strictly AFTER the inception date count as forward observations.
  * Idempotent — re-running on the same day never double-records.
  * ``--report`` grades the accumulated FORWARD record on the same gate-v2 bar and
    compares to the backtest expectation (SPY Sharpe ~0.79 net@2bps).

Tracks SPY daily (the validated vehicle; MES tracks SPX 1:1 for a calendar effect),
fetched free via yfinance — no dependency on the live engine being up. The deployable
instrument is MES; SPY is the clean persistence signal.

Usage:
    .venv/Scripts/python -m backtest.tom_paper_track            # one observe-only tick
    .venv/Scripts/python -m backtest.tom_paper_track --report   # forward record + gate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:
    from backtest.session_anomaly_backtest import (
        annualized_sharpe,
        daily_close_returns,
        decompose_daily,
        gate_v2_verdict,
        max_drawdown_pct,
        profit_factor,
        turn_of_month_mask,
    )
except ImportError:  # pragma: no cover
    from session_anomaly_backtest import (
        annualized_sharpe,
        daily_close_returns,
        decompose_daily,
        gate_v2_verdict,
        max_drawdown_pct,
        profit_factor,
        turn_of_month_mask,
    )

# Backtest baseline the forward record is compared against (SPY 33yr, net@2bps).
BACKTEST_SHARPE_NET = 0.79
BACKTEST_MEAN_BPS_NET = 4.0  # ~6 bps/day gross TOM, ~4 net; persistence is the test
COST_BPS = 2.0
_MIN_FORWARD_FOR_GATE = 24  # TOM days (~6 months) before a gate verdict is meaningful

_MAIN_CHECKOUT = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine")


def _track_dir(base: Path | None = None) -> Path:
    d = (base or _MAIN_CHECKOUT) / "data" / "tom_paper_track"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ledger(track_dir: Path) -> Path:
    return track_dir / "tom_forward_ledger.jsonl"


def _state_path(track_dir: Path) -> Path:
    return track_dir / "tom_state.json"


def _load_state(track_dir: Path) -> dict:
    p = _state_path(track_dir)
    if p.exists():
        return json.loads(p.read_text())
    return {"inception_date": None, "last_recorded_date": None}


def _save_state(track_dir: Path, state: dict) -> None:
    _state_path(track_dir).write_text(json.dumps(state, indent=2))


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def tom_returns(bars_df: pd.DataFrame) -> pd.Series:
    """Close-to-close returns on turn-of-month days, indexed by date string."""
    r = daily_close_returns(decompose_daily(bars_df), net=False)
    tom = r[turn_of_month_mask(r.index).to_numpy()]
    return pd.Series(tom.to_numpy(), index=[str(d) for d in tom.index])


def run_once(bars_df: pd.DataFrame, *, track_base: Path | None = None) -> dict:
    """One observe-only tick: record any new forward TOM days. Idempotent.

    On first run, inception is set to the latest date in the data, so only TOM days
    that occur strictly AFTER tracking began are recorded as forward observations.
    """
    track_dir = _track_dir(track_base)
    state = _load_state(track_dir)
    tom = tom_returns(bars_df)
    if tom.empty:
        return {"recorded": 0, "state": state}

    latest = max(tom.index)
    if state.get("inception_date") is None:
        # Inception = latest date available now; forward record starts empty.
        state["inception_date"] = str(max(str(d) for d in decompose_daily(bars_df).index))
        _save_state(track_dir, state)

    inception = state["inception_date"]
    last_rec = state.get("last_recorded_date") or inception
    new_days = [d for d in tom.index if d > inception and d > last_rec]

    recorded = 0
    for d in sorted(new_days):
        ret = float(tom[d])
        _append_jsonl(
            _ledger(track_dir),
            {
                "date": d,
                "ret": ret,
                "ret_bps": round(ret * 1e4, 3),
                "net_bps": round(ret * 1e4 - COST_BPS, 3),
            },
        )
        recorded += 1
    if recorded:
        state["last_recorded_date"] = str(latest)
        _save_state(track_dir, state)
    return {"recorded": recorded, "inception": inception, "latest": str(latest), "state": state}


def load_records(track_base: Path | None = None) -> list[dict]:
    path = _ledger(_track_dir(track_base))
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def report(track_base: Path | None = None) -> dict:
    """Grade the accumulated FORWARD record on the gate-v2 bar vs the backtest prior."""
    recs = load_records(track_base)
    n = len(recs)
    state = _load_state(_track_dir(track_base))
    if n == 0:
        out = {"forward_n": 0, "status": "ACCUMULATING", "inception": state.get("inception_date")}
        print(
            f"TOM forward paper-shadow: 0 forward TOM days since {out['inception']} (accumulating)."
        )
        return out

    idx = [r["date"] for r in recs]
    gross = pd.Series([r["ret"] for r in recs], index=idx)
    net = gross - COST_BPS / 1e4
    out = {
        "forward_n": n,
        "inception": state.get("inception_date"),
        "mean_bps_gross": float(gross.mean() * 1e4),
        "mean_bps_net": float(net.mean() * 1e4),
        "sharpe_gross": annualized_sharpe(gross),
        "sharpe_net": annualized_sharpe(net),
        "pf_net": profit_factor(net),
        "max_dd_pct": max_drawdown_pct(net),
        "backtest_sharpe_net": BACKTEST_SHARPE_NET,
    }
    if n >= _MIN_FORWARD_FOR_GATE:
        out["gate"] = gate_v2_verdict(net, freq="ME")  # monthly windows for the short forward span
        out["status"] = "GRADED"
    else:
        out["status"] = f"ACCUMULATING ({n}/{_MIN_FORWARD_FOR_GATE} TOM days for a gate verdict)"

    print(
        f"TOM forward paper-shadow — {n} forward TOM days since {out['inception']}  [{out['status']}]"
    )
    print(
        f"  forward: mean {out['mean_bps_net']:.2f} bps/day net  Sharpe {out['sharpe_net']:.3f} net  "
        f"PF {out['pf_net']:.3f}  maxDD {out['max_dd_pct']:.2f}%"
    )
    print(f"  backtest prior (SPY 33yr): Sharpe {BACKTEST_SHARPE_NET} net  (persistence test)")
    if "gate" in out:
        g = out["gate"]
        print(
            f"  gate-v2: {g.get('verdict')} pf_ci={g.get('pf_ci_lower'):.3f} "
            f"p_edge={g.get('p_edge'):.3f} dsr={g.get('dsr'):.3f}"
        )
    return out


def _fetch_spy_daily() -> pd.DataFrame:  # pragma: no cover - network
    import yfinance as yf

    df = yf.download("SPY", period="max", interval="1d", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    return df[["date", "open", "high", "low", "close", "volume"]]


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="turn-of-month DARK forward paper-shadow")
    ap.add_argument("--report", action="store_true", help="print the forward record + gate")
    ap.add_argument("--csv", type=Path, default=None, help="daily OHLC CSV (else fetch SPY)")
    args = ap.parse_args()
    if args.report:
        report()
        return
    bars = pd.read_csv(args.csv) if args.csv else _fetch_spy_daily()
    result = run_once(bars)
    print(
        f"TOM tick: recorded {result['recorded']} new forward TOM day(s); latest={result.get('latest')}"
    )


if __name__ == "__main__":
    main()
