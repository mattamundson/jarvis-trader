"""Shared machinery for the SPY DARK observe-only forward paper-shadows.

DARK = observe-only, exactly like ``vwap_paper_track`` / ``preholiday_paper_track``:
  * NO orders, NO live DB, nothing tradeable is touched.
  * Each tick re-runs the signal generator over the newest SPY daily bars, resamples
    to the strategy timeframe, extracts CLOSED long trades, and records any whose
    ENTRY is strictly after the inception bar into an ISOLATED JSONL under the
    MAIN-checkout ``engine/data/<name>_paper_track/`` (gitignored; durable — survives
    a worktree prune).
  * Idempotent — keyed on (entry_date, exit_date); re-running never double-records.
  * ``report`` grades the accumulated FORWARD record against the full-history backtest
    prior computed by the SAME extractor (no hardcoded magic numbers to drift).

Validates whether the X-bookmark trend edges persist out-of-sample. Research only —
does NOT authorize paper routing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

# Ledgers live in the MAIN checkout so they persist across worktree prunes and the
# live engine reads them. engine/data/*_paper_track/ is gitignored (runtime output).
_MAIN_ENGINE = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine")
_CACHE = _MAIN_ENGINE / "backtest" / "cache"


def _track_dir(name: str, base: Path | None = None) -> Path:
    d = (base or _MAIN_ENGINE) / "data" / f"{name}_paper_track"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ledger(td: Path) -> Path:
    return td / "forward_ledger.jsonl"


def _state_path(td: Path) -> Path:
    return td / "state.json"


def _load_state(td: Path) -> dict:
    p = _state_path(td)
    if p.exists():
        return json.loads(p.read_text())
    return {"inception_ts": None, "recorded_keys": []}


def _save_state(td: Path, state: dict) -> None:
    _state_path(td).write_text(json.dumps(state, indent=2))


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"]))
        else:
            df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[["open", "high", "low", "close"]]


def _full_history_cache() -> Path | None:
    """The widest-history SPY daily cache (earliest start, then latest end).

    Filenames are ``SPY_<start>_<end>_1d.csv``. A naive ``sorted()[-1]`` picks
    lexicographically (a 2025 file beats the 1993 one), so choose by parsed dates.
    """
    files = list(_CACHE.glob("SPY_*_1d.csv"))
    if not files:
        return None

    def _bounds(f: Path) -> tuple:
        parts = f.stem.split("_")  # SPY, start, end, 1d
        try:
            start = pd.Timestamp(parts[1])
        except (IndexError, ValueError):
            start = pd.Timestamp.max
        try:
            end = pd.Timestamp(parts[2])
        except (IndexError, ValueError):
            end = pd.Timestamp.min
        return (start, -end.value)  # earliest start, then latest end

    return sorted(files, key=_bounds)[0]


def _load_spy_daily() -> pd.DataFrame:
    """Full-history SPY daily bars, best-effort extended with fresh bars.

    Always loads the widest-history cache (offline-safe, deterministic), then appends
    only bars strictly newer than the cache via DataLoader (Polygon freshness — SPY is
    equity, not futures-blocklisted). A mis-matched/short DataLoader result can never
    shrink or corrupt the series because only strictly-newer bars are merged in; if no
    fresh feed is available the track is simply dormant, not broken.
    """
    cache = _full_history_cache()
    if cache is None:
        raise FileNotFoundError(f"No SPY daily cache found in {_CACHE}")
    df = _norm(pd.read_csv(cache, parse_dates=["timestamp"]).set_index("timestamp").sort_index())
    last = df.index.max()

    try:
        import sys

        sys.path.insert(0, str(_MAIN_ENGINE))
        from backtest.data_loader import DataLoader

        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (last - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        fresh = DataLoader().load("SPY", start, end, "1d")
        if fresh is not None and not fresh.empty:
            add = _norm(fresh)
            add = add[add.index > last]
            if not add.empty:
                df = pd.concat([df, add]).sort_index()
                df = df[~df.index.duplicated(keep="last")]
    except Exception:
        pass

    return df


def _closed_long_trades(sig: pd.DataFrame, capital: float) -> list[dict]:
    """Extract closed long trades from a signals frame with a 0/1 ``position``.

    Uses ``traded = position.shift(1)`` (act next bar — matches the backtest). For each
    contiguous run of traded==1 over bars [a..b], the trade is entry at close[a-1] (the
    signal-commit bar) → exit at close[b]; return = close[b]/close[a-1] - 1. A run that
    starts at bar 0 (no prior commit bar) is skipped.
    """
    close = sig["close"].to_numpy()
    idx = sig.index
    traded = sig["position"].shift(1).fillna(0.0).to_numpy()
    trades: list[dict] = []
    n = len(traded)
    i = 0
    while i < n:
        if traded[i] == 1.0:
            a = i
            while i + 1 < n and traded[i + 1] == 1.0:
                i += 1
            b = i
            if a - 1 >= 0 and close[a - 1] > 0:
                ep, xp = float(close[a - 1]), float(close[b])
                ret = xp / ep - 1.0
                trades.append({
                    "entry_date": str(pd.Timestamp(idx[a - 1]).date()),
                    "exit_date": str(pd.Timestamp(idx[b]).date()),
                    "entry_price": round(ep, 4),
                    "exit_price": round(xp, 4),
                    "return": round(ret, 6),
                    "pnl": round(capital * ret, 2),
                })
        i += 1
    return trades


def _trade_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    rets = [t["return"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gp, gl = sum(wins), abs(sum(losses))
    pf = (gp / gl) if gl > 0 else None  # None => no losing trades (undefined PF)
    return {
        "n": len(trades),
        "win_rate": round(len(wins) / len(trades), 3),
        "pf": round(pf, 3) if pf is not None else None,
        "mean_return": round(sum(rets) / len(rets), 5),
        "total_return": round(sum(rets), 4),
    }


def _bars(resample_rule: str) -> pd.DataFrame:
    daily = _load_spy_daily()
    return (
        daily.resample(resample_rule)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )


def tick(
    *,
    name: str,
    resample_rule: str,
    signal_fn: Callable[[pd.DataFrame], pd.DataFrame],
    capital: float,
    base: Path | None = None,
    inception_override: str | None = None,
) -> dict:
    """One observe-only tick: record post-inception closed trades (idempotent)."""
    td = _track_dir(name, base)
    state = _load_state(td)
    bars = _bars(resample_rule)
    sig = signal_fn(bars)
    all_trades = _closed_long_trades(sig, capital)

    last_bar = str(pd.Timestamp(bars.index[-1]).date())
    if state["inception_ts"] is None:
        # First run sets inception to the newest bar: forward = entries strictly AFTER.
        state["inception_ts"] = inception_override or last_bar

    inception = state["inception_ts"]
    recorded = set(state["recorded_keys"])
    new = 0
    for t in all_trades:
        if t["entry_date"] <= inception:
            continue
        key = f'{t["entry_date"]}|{t["exit_date"]}'
        if key in recorded:
            continue
        _append_jsonl(_ledger(td), t)
        recorded.add(key)
        new += 1

    state["recorded_keys"] = sorted(recorded)
    state["last_bar"] = last_bar
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_state(td, state)
    return {
        "name": name, "inception": inception, "last_bar": last_bar,
        "closed_trades_all_history": len(all_trades),
        "new_forward_recorded": new, "forward_total": len(recorded),
    }


def report(
    *,
    name: str,
    resample_rule: str,
    signal_fn: Callable[[pd.DataFrame], pd.DataFrame],
    capital: float,
    base: Path | None = None,
) -> dict:
    """Grade the accumulated forward record vs the full-history backtest prior."""
    td = _track_dir(name, base)
    bars = _bars(resample_rule)
    prior = _trade_stats(_closed_long_trades(signal_fn(bars), capital))

    fwd_trades: list[dict] = []
    lp = _ledger(td)
    if lp.exists():
        for line in lp.read_text().splitlines():
            if line.strip():
                fwd_trades.append(json.loads(line))
    fwd = _trade_stats(fwd_trades)

    n_fwd = fwd.get("n", 0)
    if n_fwd < 10:
        grade = f"INSUFFICIENT (forward n={n_fwd} < 10)"
    elif fwd.get("pf") is None or fwd["pf"] >= 1.0:
        grade = "FORWARD_POSITIVE"
    else:
        grade = "FORWARD_DIVERGENT (pf < 1.0)"

    return {"name": name, "prior_backtest": prior, "forward_record": fwd, "grade": grade}
