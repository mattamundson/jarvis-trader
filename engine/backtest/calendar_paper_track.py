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


# Scheduled FOMC announcement (last-meeting-day) dates 1994-2027, sourced from the
# Fed's calendars + per-year historical pages (federalreserve.gov). INLINED here (not
# imported from the screener) so the daily tick is self-contained from any worktree --
# emergency/intermeeting cuts and the cancelled 2020 March meeting are excluded.
# Keep in sync with daily_calendar_discovery.FOMC_ANNOUNCEMENTS.
_FOMC_DATES: tuple[str, ...] = (
    "1994-02-04",
    "1994-03-22",
    "1994-05-17",
    "1994-07-06",
    "1994-08-16",
    "1994-09-27",
    "1994-11-15",
    "1994-12-20",
    "1995-02-01",
    "1995-03-28",
    "1995-05-23",
    "1995-07-06",
    "1995-08-22",
    "1995-09-26",
    "1995-11-15",
    "1995-12-19",
    "1996-01-31",
    "1996-03-26",
    "1996-05-21",
    "1996-07-03",
    "1996-08-20",
    "1996-09-24",
    "1996-11-13",
    "1996-12-17",
    "1997-02-05",
    "1997-03-25",
    "1997-05-20",
    "1997-07-02",
    "1997-08-19",
    "1997-09-30",
    "1997-11-12",
    "1997-12-16",
    "1998-02-04",
    "1998-03-31",
    "1998-05-19",
    "1998-07-01",
    "1998-08-18",
    "1998-09-29",
    "1998-11-17",
    "1998-12-22",
    "1999-02-03",
    "1999-03-30",
    "1999-05-18",
    "1999-06-30",
    "1999-08-24",
    "1999-10-05",
    "1999-11-16",
    "1999-12-21",
    "2000-02-02",
    "2000-03-21",
    "2000-05-16",
    "2000-06-28",
    "2000-08-22",
    "2000-10-03",
    "2000-11-15",
    "2000-12-19",
    "2001-01-31",
    "2001-03-20",
    "2001-05-15",
    "2001-06-27",
    "2001-08-21",
    "2001-10-02",
    "2001-11-06",
    "2001-12-11",
    "2002-01-30",
    "2002-03-19",
    "2002-05-07",
    "2002-06-26",
    "2002-08-13",
    "2002-09-24",
    "2002-11-06",
    "2002-12-10",
    "2003-01-29",
    "2003-03-18",
    "2003-05-06",
    "2003-06-25",
    "2003-08-12",
    "2003-09-16",
    "2003-10-28",
    "2003-12-09",
    "2004-01-28",
    "2004-03-16",
    "2004-05-04",
    "2004-06-30",
    "2004-08-10",
    "2004-09-21",
    "2004-11-10",
    "2004-12-14",
    "2005-02-02",
    "2005-03-22",
    "2005-05-03",
    "2005-06-30",
    "2005-08-09",
    "2005-09-20",
    "2005-11-01",
    "2005-12-13",
    "2006-01-31",
    "2006-03-28",
    "2006-05-10",
    "2006-06-29",
    "2006-08-08",
    "2006-09-20",
    "2006-10-25",
    "2006-12-12",
    "2007-01-31",
    "2007-03-21",
    "2007-05-09",
    "2007-06-28",
    "2007-08-07",
    "2007-09-18",
    "2007-10-31",
    "2007-12-11",
    "2008-01-30",
    "2008-03-18",
    "2008-04-30",
    "2008-06-25",
    "2008-08-05",
    "2008-09-16",
    "2008-10-29",
    "2008-12-16",
    "2009-01-28",
    "2009-03-18",
    "2009-04-29",
    "2009-06-24",
    "2009-08-12",
    "2009-09-23",
    "2009-11-04",
    "2009-12-16",
    "2010-01-27",
    "2010-03-16",
    "2010-04-28",
    "2010-06-23",
    "2010-08-10",
    "2010-09-21",
    "2010-11-03",
    "2010-12-14",
    "2011-01-26",
    "2011-03-15",
    "2011-04-27",
    "2011-06-22",
    "2011-08-09",
    "2011-09-21",
    "2011-11-02",
    "2011-12-13",
    "2012-01-25",
    "2012-03-13",
    "2012-04-25",
    "2012-06-20",
    "2012-08-01",
    "2012-09-13",
    "2012-10-24",
    "2012-12-12",
    "2013-01-30",
    "2013-03-20",
    "2013-05-01",
    "2013-06-19",
    "2013-07-31",
    "2013-09-18",
    "2013-10-30",
    "2013-12-18",
    "2014-01-29",
    "2014-03-19",
    "2014-04-30",
    "2014-06-18",
    "2014-07-30",
    "2014-09-17",
    "2014-10-29",
    "2014-12-17",
    "2015-01-28",
    "2015-03-18",
    "2015-04-29",
    "2015-06-17",
    "2015-07-29",
    "2015-09-17",
    "2015-10-28",
    "2015-12-16",
    "2016-01-27",
    "2016-03-16",
    "2016-04-27",
    "2016-06-15",
    "2016-07-27",
    "2016-09-21",
    "2016-11-02",
    "2016-12-14",
    "2017-02-01",
    "2017-03-15",
    "2017-05-03",
    "2017-06-14",
    "2017-07-26",
    "2017-09-20",
    "2017-11-01",
    "2017-12-13",
    "2018-01-31",
    "2018-03-21",
    "2018-05-02",
    "2018-06-13",
    "2018-08-01",
    "2018-09-26",
    "2018-11-08",
    "2018-12-19",
    "2019-01-30",
    "2019-03-20",
    "2019-05-01",
    "2019-06-19",
    "2019-07-31",
    "2019-09-18",
    "2019-10-30",
    "2019-12-11",
    "2020-01-29",
    "2020-04-29",
    "2020-06-10",
    "2020-07-29",
    "2020-09-16",
    "2020-11-05",
    "2020-12-16",
    "2021-01-27",
    "2021-03-17",
    "2021-04-28",
    "2021-06-16",
    "2021-07-28",
    "2021-09-22",
    "2021-11-03",
    "2021-12-15",
    "2022-01-26",
    "2022-03-16",
    "2022-05-04",
    "2022-06-15",
    "2022-07-27",
    "2022-09-21",
    "2022-11-02",
    "2022-12-14",
    "2023-02-01",
    "2023-03-22",
    "2023-05-03",
    "2023-06-14",
    "2023-07-26",
    "2023-09-20",
    "2023-11-01",
    "2023-12-13",
    "2024-01-31",
    "2024-03-20",
    "2024-05-01",
    "2024-06-12",
    "2024-07-31",
    "2024-09-18",
    "2024-11-07",
    "2024-12-18",
    "2025-01-29",
    "2025-03-19",
    "2025-05-07",
    "2025-06-18",
    "2025-07-30",
    "2025-09-17",
    "2025-10-29",
    "2025-12-10",
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
    "2027-01-27",
    "2027-03-17",
    "2027-04-28",
    "2027-06-09",
    "2027-07-28",
    "2027-09-15",
    "2027-10-27",
    "2027-12-08",
)
_FOMC_TS = pd.DatetimeIndex(pd.to_datetime(list(_FOMC_DATES))).sort_values()


def mask_pre_fomc(idx: pd.DatetimeIndex, max_gap_days: int = 6) -> np.ndarray:
    """The single trading day BEFORE each scheduled FOMC announcement (Lucca-Moench
    pre-FOMC drift). Forward-safe: the ``max_gap_days`` guard means a FUTURE meeting
    (no bar yet on its day-before) never flags the last available bar."""
    vals = np.asarray(idx.values)
    out = np.zeros(len(idx), dtype=bool)
    if len(vals) == 0:
        return out
    ann = np.asarray(_FOMC_TS.values)
    pos = np.searchsorted(vals, ann, side="left") - 1
    for p, d in zip(pos, ann, strict=False):
        if p < 0:
            continue
        if (d - vals[p]) / np.timedelta64(1, "D") <= max_gap_days:
            out[p] = True
    return out


EFFECT_MASKS = {
    "pre_holiday": mask_pre_holiday,
    "last_day_of_month": mask_last_day_of_month,
    "santa_claus": mask_santa_claus,
    "pre_fomc": mask_pre_fomc,
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
# TLT strong candidate) so the duration mechanism is forward-tested too + the two
# pre_fomc sleeves -- TLT (the gate-PASS) and SPY (the canonical Lucca-Moench
# instrument whose H1/H2 1.68->1.04 decay we forward-watch). pre_fomc fires ~8x/yr:
# the fastest-accruing forward record of the whole family.
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
    Sleeve("TLT", "pre_fomc"),
    Sleeve("SPY", "pre_fomc"),
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
