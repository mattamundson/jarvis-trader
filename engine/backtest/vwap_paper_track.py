"""MES VWAP reversion -- DARK forward paper-shadow (observe-only).

The honest next gate for the lone survivor of the 2026-06-26 robust-strategy-funnel
Phase 2: MES VWAP deviation reversion (champion band=2.5/stop=0.75/no-reversal/
regime-filtered). It passes gate-v2 ALT (5/5) + PBO 0.198 (not overfit) + H1/H2
consistent + clean cache. The backtest established the prior; a *forward* record tests
whether the edge persists out-of-sample, post-inception.

DARK = observe-only, exactly like ``preholiday_paper_track`` / ``spread_paper_track``:
  * NO orders, NO live DB, nothing tradeable is touched.
  * Each tick re-runs the native vwap_backtester over the latest MES 1h cache and records
    any NEW closed trades whose ENTRY is strictly after the inception bar into an ISOLATED
    JSONL ledger under the MAIN-checkout ``engine/data/vwap_paper_track/`` (durable;
    survives a worktree prune).
  * Idempotent -- keyed on (entry_date, exit_date); re-running never double-records.
  * ``--report`` grades the accumulated FORWARD record vs the backtest prior
    (PF 4.07, per-trade Sharpe 0.40, win rate 0.40 over 250 OOS trades).

Bars come from the newest MES 1h cache (same loader as run_mes_vwap_rank1) -- self-contained,
no dependency on the live engine being up. The shadow advances whenever the cache refreshes.

Usage (from engine/):
    .venv/Scripts/python -m backtest.vwap_paper_track            # one observe-only tick
    .venv/Scripts/python -m backtest.vwap_paper_track --report   # forward record + grade
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# Champion params (gate-v2 ALT + PBO 0.198 survivor; verdict MES_vwap_rank1.json)
CHAMPION = {
    "band_mult": 2.5,
    "stop_mult": 0.75,
    "require_reversal_bar": False,
    "regime_filter": True,
}
SYMBOL = "MES"
CAPITAL = 50_000.0

# Backtest prior the forward record is compared against (250 OOS trades, 2024-2026):
BACKTEST_PF = 4.07
BACKTEST_PER_TRADE_SHARPE = 0.40
BACKTEST_WIN_RATE = 0.40
_MIN_FORWARD_FOR_GRADE = 20  # forward trades before a metric grade is meaningful

_MAIN_CHECKOUT = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine")


def _track_dir(base: Path | None = None) -> Path:
    d = (base or _MAIN_CHECKOUT) / "data" / "vwap_paper_track" / SYMBOL
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ledger(track_dir: Path) -> Path:
    return track_dir / "vwap_forward_ledger.jsonl"


def _state_path(track_dir: Path) -> Path:
    return track_dir / "vwap_state.json"


def _load_state(track_dir: Path) -> dict:
    p = _state_path(track_dir)
    if p.exists():
        return json.loads(p.read_text())
    return {"inception_ts": None, "recorded_keys": []}


def _save_state(track_dir: Path, state: dict) -> None:
    _state_path(track_dir).write_text(json.dumps(state, indent=2))


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _load_bars() -> pd.DataFrame:
    """Newest MES 1h cache via the same loader the runner uses (self-contained)."""
    from backtest.run_mes_vwap_rank1 import _find_data_file, _load_data

    return _load_data(_find_data_file(_MAIN_CHECKOUT / "backtest" / "cache"))


def _champion_trades(bars: pd.DataFrame) -> list:
    from backtest.vwap_backtester import run_vwap_backtest

    res = run_vwap_backtest(bars, symbol=SYMBOL, **CHAMPION)
    return res.trades


def _key(t) -> str:
    return f"{t.entry_date}|{t.exit_date}"


def run_once(bars: pd.DataFrame | None = None, *, track_base: Path | None = None) -> dict:
    """One observe-only tick: record any new forward closed trades. Idempotent.

    On first run, inception = the latest bar timestamp, so only trades that ENTER
    strictly after tracking began count as forward observations.
    """
    track_dir = _track_dir(track_base)
    state = _load_state(track_dir)
    if bars is None:
        bars = _load_bars()

    latest_ts = str(bars.index.max())
    if state.get("inception_ts") is None:
        state["inception_ts"] = latest_ts
        _save_state(track_dir, state)
    inception = pd.Timestamp(state["inception_ts"])

    recorded = set(state.get("recorded_keys", []))
    trades = _champion_trades(bars)
    new = 0
    for t in trades:
        entry_ts = pd.Timestamp(t.entry_date)
        if entry_ts <= inception:
            continue  # not a forward trade (originated before/at inception)
        k = _key(t)
        if k in recorded:
            continue
        pnl = float(t.pnl)
        _append_jsonl(
            _ledger(track_dir),
            {
                "entry_date": str(t.entry_date),
                "exit_date": str(t.exit_date),
                "side": t.side,
                "entry_price": float(t.entry_price),
                "exit_price": float(t.exit_price),
                "exit_reason": t.exit_reason,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl / CAPITAL * 100, 4),
            },
        )
        recorded.add(k)
        new += 1

    if new:
        state["recorded_keys"] = sorted(recorded)
        _save_state(track_dir, state)
    return {
        "recorded": new,
        "inception": state["inception_ts"],
        "latest": latest_ts,
        "total_forward": len(recorded),
    }


def load_records(track_base: Path | None = None) -> list[dict]:
    path = _ledger(_track_dir(track_base))
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def report(track_base: Path | None = None) -> dict:
    """Grade the accumulated FORWARD record vs the backtest prior."""
    recs = load_records(track_base)
    state = _load_state(_track_dir(track_base))
    n = len(recs)
    if n == 0:
        print(
            f"VWAP@MES forward paper-shadow: 0 forward trades since "
            f"{state.get('inception_ts')} (accumulating)."
        )
        return {"forward_n": 0, "status": "ACCUMULATING", "inception": state.get("inception_ts")}

    pnls = np.array([r["pnl"] for r in recs], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    gp, gl = float(wins.sum()), float(abs(losses.sum()))
    pf = gp / gl if gl > 0 else float("inf")
    rets = pnls / CAPITAL
    per_trade_sharpe = (
        float(rets.mean() / rets.std(ddof=1)) if n > 1 and rets.std(ddof=1) > 0 else 0.0
    )
    eq = np.cumsum(pnls)
    max_dd = float(abs((eq - np.maximum.accumulate(eq)).min())) if n else 0.0

    out = {
        "forward_n": n,
        "inception": state.get("inception_ts"),
        "net_pnl": round(float(pnls.sum()), 2),
        "win_rate": round(float(len(wins) / n), 4),
        "profit_factor": round(pf, 3) if np.isfinite(pf) else None,
        "per_trade_sharpe": round(per_trade_sharpe, 4),
        "max_dd_dollars": round(max_dd, 2),
        "max_dd_pct": round(max_dd / CAPITAL * 100, 4),
        "backtest_pf": BACKTEST_PF,
        "backtest_per_trade_sharpe": BACKTEST_PER_TRADE_SHARPE,
        "status": (
            "GRADED"
            if n >= _MIN_FORWARD_FOR_GRADE
            else f"ACCUMULATING ({n}/{_MIN_FORWARD_FOR_GRADE} forward trades for a grade)"
        ),
    }
    print(
        f"VWAP@MES forward paper-shadow -- {n} forward trades since {out['inception']}  [{out['status']}]"
    )
    print(
        f"  forward: net ${out['net_pnl']}  PF {out['profit_factor']}  "
        f"WR {out['win_rate']:.1%}  per-trade Sharpe {out['per_trade_sharpe']}  maxDD {out['max_dd_pct']:.2f}%"
    )
    print(
        f"  backtest prior: PF {BACKTEST_PF}  per-trade Sharpe {BACKTEST_PER_TRADE_SHARPE} (persistence test)"
    )
    return out


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="MES VWAP DARK forward paper-shadow")
    ap.add_argument("--report", action="store_true", help="print the forward record + grade")
    args = ap.parse_args()
    if args.report:
        report()
        return
    result = run_once()
    print(
        f"VWAP@MES tick: recorded {result['recorded']} new forward trade(s); "
        f"total_forward={result['total_forward']}; inception={result['inception']}; latest={result['latest']}"
    )


if __name__ == "__main__":
    main()
