"""Cross-index turn-of-month robustness — is TOM a broad equity month-turn effect,
or an SPY-specific artifact?

The beta-harvest gate variant (BETA_HARVEST_GATE_PROPOSAL.md) lowers the p_edge floor in
exactly the way that unblocks turn-of-month on SPY. Before that gate change is worth making,
TOM should be shown to be real on OTHER equity indices: a genuine month-turn liquidity/flow
effect appears across the index complex; an SPY-only result is data-mined and should NOT
justify lowering the gate. This module runs the SAME honest pipeline TOM was graded on
(``session_anomaly_backtest``) across a registry of indices and reports a pre-registered
corroborate/kill verdict. It imports and reuses — it changes nothing in the core module.

Pre-registered decision rule (written before running):
  * An index CORROBORATES if, beta-sized to a 5% DD budget and net of 2bps, its TOM series is
    chronologically stationary (H1 and H2 PF > 1) AND clears pf_ci_lower >= 1.10 AND the
    canonical compute_gate_v2 either PASSes or FAILs the core on EXACTLY the p_edge criterion
    (the one the beta-harvest variant addresses) — i.e. no OTHER criterion is the blocker.
  * TOM is CORROBORATED overall if >= CORROBORATION_THRESHOLD of the registry corroborate.
  * Every index's verdict is reported; none is silently dropped.

Usage:
    .venv/Scripts/python -m backtest.tom_cross_index            # fetch (cache) + run all
    .venv/Scripts/python -m backtest.tom_cross_index --symbols SPY QQQ IWM
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

try:
    from backtest.session_anomaly_backtest import (
        PF_CI_LOWER_MIN,
        _tom_series,
        annualized_sharpe,
        beta_size,
        decompose_daily,
        gate_v2_beta_harvest_verdict,
        gate_v2_verdict,
        profit_factor,
    )
except ImportError:  # pragma: no cover
    from session_anomaly_backtest import (
        PF_CI_LOWER_MIN,
        _tom_series,
        annualized_sharpe,
        beta_size,
        decompose_daily,
        gate_v2_beta_harvest_verdict,
        gate_v2_verdict,
        profit_factor,
    )

#: Equity-index complex: large / tech / small / blue-chip / mid / intl-developed. If TOM is a
#: real month-turn flow effect it should appear broadly here, not just in SPY.
INDEX_REGISTRY: dict[str, str] = {
    "SPY": "US large cap (S&P 500)",
    "QQQ": "US tech (Nasdaq-100)",
    "IWM": "US small cap (Russell 2000)",
    "DIA": "US blue-chip (Dow 30)",
    "MDY": "US mid cap (S&P 400)",
    "EFA": "Intl developed (MSCI EAFE)",
}

#: >= this many of the registry must corroborate for TOM to be CORROBORATED overall.
CORROBORATION_THRESHOLD = 4

COST_BPS = 2.0
DD_BUDGET_PCT = 5.0

_CACHE = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache")


def _cache_path(sym: str, cache_dir: Path | None = None) -> Path:
    return (cache_dir or _CACHE) / f"{sym}_daily.csv"


def fetch_index_daily(
    sym: str, cache_dir: Path | None = None
) -> pd.DataFrame:  # pragma: no cover - network
    """Pull free public daily OHLC for ``sym`` via yfinance and cache it. Mirrors the SPY
    fetch in session_anomaly_backtest._fetch_spy_daily, generalized to any symbol."""
    import yfinance as yf

    df = yf.download(sym, period="max", interval="1d", auto_adjust=True, progress=False)
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
    df = df[["date", "open", "high", "low", "close", "volume"]]
    out = _cache_path(sym, cache_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df


def load_or_fetch(sym: str, cache_dir: Path | None = None) -> pd.DataFrame:
    """Return cached daily OHLC for ``sym`` if present, else fetch + cache it."""
    p = _cache_path(sym, cache_dir)
    if p.exists():
        return pd.read_csv(p)
    return fetch_index_daily(sym, cache_dir)


def validate_index(
    sym: str,
    *,
    cost_bps: float = COST_BPS,
    dd_budget: float = DD_BUDGET_PCT,
    df: pd.DataFrame | None = None,
    cache_dir: Path | None = None,
) -> dict:
    """Grade turn-of-month on one index with the canonical + beta-harvest gates."""
    raw = df if df is not None else load_or_fetch(sym, cache_dir)
    sessions = decompose_daily(raw)
    tom = _tom_series(sessions, net=False)
    tom_net = tom - cost_bps / 1e4
    sized, scale, dd = beta_size(tom_net, dd_budget_pct=dd_budget)

    can = gate_v2_verdict(sized)
    bh = gate_v2_beta_harvest_verdict(sized)

    n = len(sized)
    h1, h2 = sized.iloc[: n // 2], sized.iloc[n // 2 :]
    h1_pf, h2_pf = profit_factor(h1), profit_factor(h2)
    stationary = bool(h1_pf > 1.0 and h2_pf > 1.0)

    core_fails = [c for c in can.get("core_reasons", []) if c.strip().upper().startswith("FAIL")]
    only_p_edge = len(core_fails) == 1 and "p_edge" in core_fails[0]
    canonical_pass = can.get("verdict") == "PASS"
    pf_ci = float(can.get("pf_ci_lower", 0.0))

    # Corroborates iff stationary, clears pf_ci, and the ONLY thing standing between it and a
    # canonical PASS is the p_edge criterion the beta-harvest variant addresses (a full PASS is
    # strictly stronger and also corroborates).
    corroborates = bool(stationary and pf_ci >= PF_CI_LOWER_MIN and (canonical_pass or only_p_edge))

    return {
        "symbol": sym,
        "label": INDEX_REGISTRY.get(sym, ""),
        "n": int(len(tom)),
        "sharpe_net": annualized_sharpe(tom_net),
        "beta_scale": float(scale),
        "sized_dd_pct": float(dd),
        "canonical_verdict": can.get("verdict"),
        "p_edge": float(can.get("p_edge", 0.0)),
        "pf_ci_lower": pf_ci,
        "dsr": float(can.get("dsr", 0.0)),
        "beta_harvest_verdict": bh.get("verdict"),
        "beta_harvest_reclassified": bool(bh.get("beta_harvest_reclassified", False)),
        "h1_pf": float(h1_pf),
        "h2_pf": float(h2_pf),
        "stationary": stationary,
        "core_fails": core_fails,
        "fails_only_on_p_edge": only_p_edge,
        "corroborates": corroborates,
    }


def run(symbols: list[str] | None = None, *, cache_dir: Path | None = None) -> dict:
    """Run the cross-index TOM check and print the comparison table + pre-registered verdict."""
    syms = symbols or list(INDEX_REGISTRY)
    results = [validate_index(s, cache_dir=cache_dir) for s in syms]
    n_corr = sum(1 for r in results if r.get("corroborates"))
    verdict = "CORROBORATED" if n_corr >= CORROBORATION_THRESHOLD else "NOT-CORROBORATED"

    print("Cross-index turn-of-month robustness (beta-sized 5% DD, net@2bps)\n")
    print(
        f"{'sym':5s} {'n':>5s} {'Shrp':>6s} {'pf_ci':>6s} {'p_edge':>7s} "
        f"{'H1pf':>5s} {'H2pf':>5s} {'stat':>5s} {'canon':>5s} {'bh':>5s}  core-fail"
    )
    for r in results:
        if "n" not in r:  # monkeypatched/minimal result (tests)
            continue
        cf = ",".join(c.split("=")[0].replace("FAIL ", "").strip() for c in r["core_fails"]) or "-"
        print(
            f"{r['symbol']:5s} {r['n']:5d} {r['sharpe_net']:6.2f} {r['pf_ci_lower']:6.2f} "
            f"{r['p_edge']:7.3f} {r['h1_pf']:5.2f} {r['h2_pf']:5.2f} "
            f"{('Y' if r['stationary'] else 'n'):>5s} {str(r['canonical_verdict'])[:5]:>5s} "
            f"{str(r['beta_harvest_verdict'])[:5]:>5s}  {cf}"
            + ("   <= corroborates" if r["corroborates"] else "")
        )
    print(
        f"\nVERDICT: {verdict}  ({n_corr}/{len(results)} corroborate; threshold {CORROBORATION_THRESHOLD})"
    )
    return {
        "results": results,
        "n_corroborating": n_corr,
        "n_total": len(results),
        "verdict": verdict,
    }


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="cross-index turn-of-month robustness")
    ap.add_argument("--symbols", nargs="*", default=None, help="subset of the registry to run")
    args = ap.parse_args()
    run(symbols=args.symbols)


if __name__ == "__main__":
    main()
