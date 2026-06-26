"""Calendar seasonals -- DARK forward paper-shadow (observe-only), GENERIC.

The honest next gate for the calendar gate-v2 PASSers surfaced by
``daily_calendar_discovery`` (9 PASSes across equity / gold / EM / intl / credit).
The backtest establishes the prior; a *forward* record tests whether each effect
persists out-of-sample, post-inception.

Generalizes ``preholiday_paper_track`` to a REGISTRY of (symbol, effect) sleeves so
every passer accrues its own isolated forward record under ONE daily task. The
strongest *new* structural find -- ``last_day_of_month`` as a rates/duration effect
(LQD gate-PASS; negative in equities) -- is included alongside the risk-on holiday /
year-end sleeves, so the forward record can confirm the mechanism out-of-sample.

DARK = observe-only, exactly like ``preholiday_paper_track`` / ``tom_paper_track`` /
``spread_paper_track``:
  * NO orders, NO live DB, nothing tradeable is touched.
  * Each sleeve records realized held-day close-to-close returns into an ISOLATED JSONL
    ledger under the MAIN-checkout ``engine/data/calendar_paper_track/<symbol>__<effect>/``
    (durable; survives a worktree prune).
  * Only held days strictly AFTER that sleeve's inception count as forward observations.
  * Idempotent -- re-running on the same data never double-records.

The calendar masks are INLINED (not imported from the screener) so the daily tick runs
from ANY worktree regardless of which screener version is checked out -- the same
self-containment ``preholiday_paper_track`` uses. ``--report`` lazily imports the
canonical gate-v2 grader; the daily tick needs none of it.

SPY pre_holiday is deliberately NOT registered here -- it is already shadowed by
``preholiday_paper_track`` (avoid a double ledger). This tracks the OTHER passers.

Usage:
    .venv/Scripts/python -m backtest.calendar_paper_track            # one observe-only tick (all sleeves)
    .venv/Scripts/python -m backtest.calendar_paper_track --report   # forward record + gate per sleeve
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COST_BPS = 2.0
_MIN_FORWARD_FOR_GATE = 16  # held days before a gate verdict is meaningful
_MAIN_CHECKOUT = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine")


# ── calendar masks (pure, inlined; identical to daily_calendar_discovery) ─────────
def _month_ranks(idx: pd.DatetimeIndex):
    ym = np.asarray(idx.year) * 12 + np.asarray(idx.month)
    df = pd.DataFrame({"ym": ym})
    rank_start = (df.groupby("ym").cumcount() + 1).to_numpy()
    size = df.groupby("ym")["ym"].transform("size").to_numpy()
    rank_end = size - rank_start + 1
    return rank_start, rank_end, np.asarray(idx.month), size


def mask_pre_holiday(idx: pd.DatetimeIndex) -> np.ndarray:
    """True on the trading day BEFORE an abnormal gap (calendar-free; last day never
    flagged -> naturally forward-safe)."""
    d = idx.to_series().reset_index(drop=True)
    gap = (d.shift(-1) - d).dt.days
    wd = d.dt.dayofweek
    normal = (gap == 1) | ((wd == 4) & (gap == 3))
    return (gap.notna() & ~normal).to_numpy()


def mask_last_day_of_month(idx: pd.DatetimeIndex) -> np.ndarray:
    """ONLY the final trading day of each month (the rates/duration month-end day)."""
    _, rank_end, _, _ = _month_ranks(idx)
    return rank_end <= 1


def mask_santa_claus(idx: pd.DatetimeIndex, n_dec: int = 5, n_jan: int = 2) -> np.ndarray:
    """Last ``n_dec`` trading days of Dec + first ``n_jan`` of Jan (Hirsch)."""
    rs, re_, mo, _ = _month_ranks(idx)
    return ((mo == 12) & (re_ <= n_dec)) | ((mo == 1) & (rs <= n_jan))


EFFECT_MASKS = {
    "pre_holiday": mask_pre_holiday,
    "last_day_of_month": mask_last_day_of_month,
    "santa_claus": mask_santa_claus,
}


@dataclass(frozen=True)
class Sleeve:
    symbol: str
    effect: str

    @property
    def key(self) -> str:
        return f"{self.symbol}__{self.effect}"


# Forward-shadow registry: the gate-v2 PASSers (minus SPY pre_holiday, already
# shadowed by preholiday_paper_track) + the two rates month-end sleeves (LQD PASS,
# TLT strong candidate) so the duration mechanism is forward-tested too.
SLEEVES: list[Sleeve] = [
    Sleeve("GLD", "pre_holiday"),
    Sleeve("HYG", "pre_holiday"),
    Sleeve("LQD", "last_day_of_month"),
    Sleeve("TLT", "last_day_of_month"),
    Sleeve("SPY", "santa_claus"),
    Sleeve("DIA", "santa_claus"),
    Sleeve("EEM", "santa_claus"),
    Sleeve("EFA", "santa_claus"),
    Sleeve("HYG", "santa_claus"),
]


# ── stats (inlined; standard) ─────────────────────────────────────────────────────
def _sharpe(r: pd.Series, ppy: int = 252) -> float:
    a = r.to_numpy(dtype=float)
    if len(a) < 2 or a.std(ddof=1) == 0:
        return 0.0
    return float(a.mean() / a.std(ddof=1) * np.sqrt(ppy))


def _pf(r: pd.Series) -> float:
    g, ls = float(r[r > 0].sum()), float(-r[r < 0].sum())
    return (g / ls) if ls > 0 else (float("inf") if g > 0 else 0.0)


def _max_dd_pct(r: pd.Series) -> float:
    if len(r) == 0:
        return 0.0
    eq = (1.0 + r).cumprod()
    return float(abs(((eq - eq.cummax()) / eq.cummax()).min()) * 100.0)


def _closes(bars_df: pd.DataFrame) -> pd.Series:
    col = "date" if "date" in bars_df.columns else "timestamp"
    return pd.Series(
        pd.to_numeric(bars_df["close"]).to_numpy(), index=pd.to_datetime(bars_df[col])
    ).sort_index()


def held_returns(bars_df: pd.DataFrame, effect: str) -> pd.Series:
    """Close-to-close returns on the effect's held days, indexed by date string."""
    closes = _closes(bars_df)
    r = closes.pct_change()
    mask = EFFECT_MASKS[effect](closes.index)
    sel = r[mask].dropna()
    return pd.Series(sel.to_numpy(), index=[str(d.date()) for d in sel.index])


# ── ledger plumbing (per sleeve) ──────────────────────────────────────────────────
def _track_dir(sleeve: Sleeve, base: Path | None = None) -> Path:
    d = (base or _MAIN_CHECKOUT) / "data" / "calendar_paper_track" / sleeve.key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_state(track_dir: Path) -> dict:
    p = track_dir / "state.json"
    return (
        json.loads(p.read_text())
        if p.exists()
        else {"inception_date": None, "last_recorded_date": None}
    )


def _save_state(track_dir: Path, state: dict) -> None:
    (track_dir / "state.json").write_text(json.dumps(state, indent=2))


def run_once_sleeve(
    sleeve: Sleeve, bars_df: pd.DataFrame, *, track_base: Path | None = None
) -> dict:
    """One observe-only tick for one sleeve. Idempotent; inception = latest date on
    first run, so only held days strictly AFTER tracking began are forward obs."""
    track_dir = _track_dir(sleeve, track_base)
    state = _load_state(track_dir)
    hr = held_returns(bars_df, sleeve.effect)

    col = "date" if "date" in bars_df.columns else "timestamp"
    all_dates = [str(d.date()) for d in pd.to_datetime(bars_df[col])]
    if not all_dates:
        return {"sleeve": sleeve.key, "recorded": 0}
    latest_all = max(all_dates)
    if state.get("inception_date") is None:
        state["inception_date"] = latest_all
        _save_state(track_dir, state)
    inception = state["inception_date"]
    last_rec = state.get("last_recorded_date") or inception
    new_days = sorted(d for d in hr.index if d > inception and d > last_rec)

    ledger = track_dir / "forward_ledger.jsonl"
    recorded = 0
    with ledger.open("a", encoding="utf-8") as fh:
        for d in new_days:
            ret = float(hr[d])
            fh.write(
                json.dumps(
                    {
                        "date": d,
                        "ret": ret,
                        "ret_bps": round(ret * 1e4, 3),
                        "net_bps": round(ret * 1e4 - COST_BPS, 3),
                    }
                )
                + "\n"
            )
            recorded += 1
    if recorded:
        state["last_recorded_date"] = new_days[-1]
        _save_state(track_dir, state)
    return {
        "sleeve": sleeve.key,
        "recorded": recorded,
        "inception": inception,
        "latest": latest_all,
    }


def load_records(sleeve: Sleeve, track_base: Path | None = None) -> list[dict]:
    p = _track_dir(sleeve, track_base) / "forward_ledger.jsonl"
    return (
        [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        if p.exists()
        else []
    )


def report_sleeve(sleeve: Sleeve, track_base: Path | None = None) -> dict:
    recs = load_records(sleeve, track_base)
    state = _load_state(_track_dir(sleeve, track_base))
    n = len(recs)
    if n == 0:
        return {
            "sleeve": sleeve.key,
            "forward_n": 0,
            "status": "ACCUMULATING",
            "inception": state.get("inception_date"),
        }
    net = pd.Series([r["ret"] for r in recs], index=[r["date"] for r in recs]) - COST_BPS / 1e4
    out = {
        "sleeve": sleeve.key,
        "forward_n": n,
        "inception": state.get("inception_date"),
        "mean_bps_net": float(net.mean() * 1e4),
        "sharpe_net": _sharpe(net),
        "pf_net": _pf(net),
        "max_dd_pct": _max_dd_pct(net),
    }
    if n >= _MIN_FORWARD_FOR_GATE:
        try:  # canonical gate grader is optional and lives in the screener module
            from backtest.daily_calendar_discovery import gate_v2_verdict

            out["gate"] = gate_v2_verdict(net, n_grid_combos=1, freq="ME")
            out["status"] = "GRADED"
        except Exception:  # noqa: BLE001
            out["status"] = "GRADED (gate grader unavailable)"
    else:
        out["status"] = f"ACCUMULATING ({n}/{_MIN_FORWARD_FOR_GATE})"
    return out


def _fetch_daily(symbol: str) -> pd.DataFrame:  # pragma: no cover - network
    import yfinance as yf

    df = yf.download(symbol, period="max", interval="1d", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(
        columns={c: c.lower() for c in ["Date", "Open", "High", "Low", "Close", "Volume"]}
    )
    return df[["date", "open", "high", "low", "close", "volume"]]


def run_all(*, track_base: Path | None = None, fetch=_fetch_daily) -> list[dict]:
    """Tick every registered sleeve. One fetch per distinct symbol (shared across its
    sleeves)."""
    by_symbol: dict[str, pd.DataFrame] = {}
    results = []
    for s in SLEEVES:
        if s.symbol not in by_symbol:
            by_symbol[s.symbol] = fetch(s.symbol)
        results.append(run_once_sleeve(s, by_symbol[s.symbol], track_base=track_base))
    return results


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="calendar seasonals DARK forward paper-shadow")
    ap.add_argument("--report", action="store_true", help="per-sleeve forward record + gate")
    args = ap.parse_args()
    if args.report:
        for s in SLEEVES:
            o = report_sleeve(s)
            line = f"{o['sleeve']:24} n={o['forward_n']:>3} [{o['status']}]"
            if o["forward_n"]:
                line += (
                    f"  mean {o['mean_bps_net']:.2f}bps/day net  Sharpe {o['sharpe_net']:.2f}"
                    f"  PF {o['pf_net']:.2f}  maxDD {o['max_dd_pct']:.1f}%"
                )
                if "gate" in o:
                    line += f"  gate={o['gate'].get('verdict')}"
            else:
                line += f"  inception {o.get('inception')}"
            print(line)
        return
    for r in run_all():
        print(
            f"{r['sleeve']:24} recorded {r['recorded']} new forward day(s); latest={r.get('latest')}"
        )


if __name__ == "__main__":
    main()
