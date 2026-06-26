"""Relative-value spread mean-reversion -- DARK forward paper track (observe-only).

The in-sample backtests (`spread_backtest.py` / `spread_pairs_scan.py`, see
`data/spread_es_nq_results.md` and `data/spread_pairs_results.md`) found genuine but
NON-STATIONARY edges across index-spread pairs: on 1h data they pass the pooled gate-v2
thresholds yet the profit is back-loaded into the favorable 2025 regime, so persistence
is unprovable on the 26-month / 7-window history available. The only honest resolution is
out-of-sample TIME -- so this module records what each strategy WOULD do on live, forward
bars, building clean OOS records we can evaluate in a few months.

Two pairs are tracked (PAIR_REGISTRY): the original **ES-NQ** (root ledger, kept for
continuity) and **MES-M2K** (the stronger candidate found by the multi-pair scan -- its
H1 half is genuinely profitable, where ES-NQ's loses), each in its own ledger subdir.

DARK = observe-only. For each pair it:
  * pulls fresh leg bars from the live engine's read-only /analyze/bars endpoint,
  * computes the spread z-score and the desired position with the SAME pure functions as
    the backtest (`compute_spread_z` / `step_position` -- single source of truth),
  * writes spread closed-trade records into an ISOLATED JSONL ledger (NOT the live DB),
    in the exact shape `forward_test.build_windows`/`forward_stats` consume, so the
    forward record is graded on the same gate-v2 statistical bar as the rest of the campaign.

It routes NO orders, makes NO paper-broker calls, and never touches the live pipeline,
the live SQLite DB, or any position. MNQ is in DO_NOT_TRADE_SYMBOLS, but that gates
directional LIVE sizing; an observe-only relative-value RECORD touches nothing tradeable.

Durable state/ledgers live under the MAIN-checkout `engine/data/spread_paper_track/` so
they survive worktree pruning and a future merge to the live tree.

Run once (each invocation processes the latest closed 1h bar, idempotent within the hour):
    .venv/Scripts/python -m backtest.spread_paper_track
Report the forward record on the gate-v2 bar:
    .venv/Scripts/python -m backtest.spread_paper_track --report
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backtest.spread_backtest import (
    DEFAULT_COST_BPS_PER_LEG,
    DEFAULT_PARAMS,
    compute_spread_z,
    step_position,
)

LINEAGE = "es_nq_spread_v1"
SPREAD_SYMBOL = "ES_NQ_SPREAD"
DEFAULT_BASE_URL = "http://127.0.0.1:8010"

# Pairs forward-tracked each run. ES-NQ keeps the legacy root ledger (subdir="") for
# continuity; MES-M2K (the stronger candidate per data/spread_pairs_results.md) gets its
# own subdir. sym_a/sym_b are the engine /analyze/bars symbols (a=ES-leg, b=NQ-leg).
PAIR_REGISTRY: dict[str, dict] = {
    "ES-NQ": {
        "sym_a": "MES",
        "sym_b": "MNQ",
        "symbol": "ES_NQ_SPREAD",
        "lineage": "es_nq_spread_v1",
        "subdir": "",
    },
    "MES-M2K": {
        "sym_a": "MES",
        "sym_b": "M2K",
        "symbol": "MES_M2K_SPREAD",
        "lineage": "mes_m2k_spread_v1",
        "subdir": "MES-M2K",
    },
}
# Synthetic dollar-neutral book: per-leg notional. pnl = net_spread_log_return * NOTIONAL.
# A 1% spread move on the book ~= $200. This is a unit book for readability, NOT real
# contract sizing (the backtest edge is execution-agnostic / return-based).
NOTIONAL_PER_LEG = 20_000.0

# Durable, stable location (main checkout) -- not the ephemeral worktree.
_CANONICAL_DATA = Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\data")
_ENGINE_ENV = Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env")


def _track_dir(base: Path | None = None, subdir: str = "") -> Path:
    d = (base or _CANONICAL_DATA) / "spread_paper_track"
    if subdir:
        d = d / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── pure core (fully unit-tested, no IO) ────────────────────────────────────────


def _empty_state() -> dict:
    return {
        "position": 0,
        "entry_es": None,
        "entry_nq": None,
        "entry_time": None,
        "entry_z": None,
        "last_bar_ts": None,
    }


def close_trade(
    state: dict,
    es: float,
    nq: float,
    z_exit: float,
    ts: str,
    cost_bps_per_leg: float,
    notional: float,
    pair_symbol: str = SPREAD_SYMBOL,
    lineage: str = LINEAGE,
) -> dict:
    """Build a closed spread-trade record (build_windows-shaped) from the open `state`.

    A +1 long-spread unit earns dlogA - dlogB since entry; -1 earns the negative. Cost
    is the full round trip: entry (2 legs) + exit (2 legs) = 4 leg-turns * cost_bps,
    matching the per-bar turn cost the backtest charges over an open->close cycle.

    pair_symbol/lineage default to the ES-NQ track for backward compatibility; the
    multi-pair orchestrator passes the per-pair values from PAIR_REGISTRY.
    """
    pos = state["position"]
    r_es = math.log(es / state["entry_es"])
    r_nq = math.log(nq / state["entry_nq"])
    gross_ret = pos * (r_es - r_nq)
    cost_ret = 4.0 * (cost_bps_per_leg / 1e4)
    net_ret = gross_ret - cost_ret
    return {
        "symbol": pair_symbol,
        "direction": "long_spread" if pos == 1 else "short_spread",
        "entry_time": state["entry_time"],
        "exit_time": ts,
        "entry_es": state["entry_es"],
        "exit_es": es,
        "entry_nq": state["entry_nq"],
        "exit_nq": nq,
        "entry_z": state["entry_z"],
        "exit_z": round(float(z_exit), 4),
        "ret": round(net_ret, 6),
        "pnl": round(net_ret * notional, 2),
        # Nested decision_identity so forward_test.trade_lineage() picks it up and the
        # dark record graduates through the lineage track. The lineage is per-pair and
        # carries the composite symbol (e.g. "mes_m2k_spread_v1::MES_M2K_SPREAD"), which
        # is_pre_registered() matches by id stem against the decision_registry.
        "strategy_params": {
            "decision_identity": {"lineage": f"{lineage}::{pair_symbol}"},
            "params": dict(DEFAULT_PARAMS),
        },
    }


def decide_transition(
    state: dict,
    z: float,
    es: float,
    nq: float,
    ts: str,
    params: dict,
    cost_bps_per_leg: float = DEFAULT_COST_BPS_PER_LEG,
    notional: float = NOTIONAL_PER_LEG,
    pair_symbol: str = SPREAD_SYMBOL,
    lineage: str = LINEAGE,
) -> tuple[dict, str, dict | None]:
    """Pure transition: given the open `state` and the latest (z, prices, ts), return
    (new_state, event, closed_trade_or_None). event in {hold, in_position, open, close, flip}.

    No-look-ahead is the caller's job (pass the latest CLOSED bar). This only mutates the
    synthetic book; it returns a new state dict and never performs IO.
    """
    cur = state.get("position", 0)
    new_pos = step_position(cur, z, params["entry"], params["exit"], params["stop"])
    new_state = dict(state)
    new_state["last_bar_ts"] = ts

    if new_pos == cur:
        return new_state, ("hold" if cur == 0 else "in_position"), None

    closed = None
    if cur != 0:
        closed = close_trade(state, es, nq, z, ts, cost_bps_per_leg, notional, pair_symbol, lineage)

    if new_pos != 0:
        new_state.update(
            position=new_pos, entry_es=es, entry_nq=nq, entry_time=ts, entry_z=round(float(z), 4)
        )
        event = "flip" if cur != 0 else "open"
    else:
        new_state.update(position=0, entry_es=None, entry_nq=None, entry_time=None, entry_z=None)
        event = "close"
    return new_state, event, closed


def align_latest(
    bars_a: list[dict], bars_b: list[dict], window: int
) -> tuple[str, float, float, float] | None:
    """Inner-join two bar lists on timestamp; compute the z of the latest aligned bar.

    Returns (ts, close_a, close_b, z_latest) or None if there is insufficient overlap
    (need > window aligned bars to form a valid z). Pure.
    """
    ma = {b["timestamp"]: float(b["close"]) for b in bars_a if b.get("close") is not None}
    mb = {b["timestamp"]: float(b["close"]) for b in bars_b if b.get("close") is not None}
    common = sorted(set(ma) & set(mb))
    if len(common) <= window:
        return None
    a = np.array([ma[t] for t in common])
    b = np.array([mb[t] for t in common])
    _, z = compute_spread_z(a, b, window)
    z_latest = z[-1]
    if np.isnan(z_latest):
        return None
    return common[-1], float(a[-1]), float(b[-1]), float(z_latest)


# ── IO wrappers (exercised live, thin) ──────────────────────────────────────────


def _read_api_key(env_path: Path = _ENGINE_ENV) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s.startswith("API_KEY="):
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def fetch_bars(
    symbol: str, base_url: str, api_key: str | None, interval: str = "1h", limit: int = 80
) -> list[dict]:  # pragma: no cover - network IO
    url = f"{base_url}/analyze/bars/{symbol}?interval={interval}&futures=true&limit={limit}&days=30"
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return [{"timestamp": b["timestamp"], "close": b.get("close")} for b in payload.get("bars", [])]


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _load_state(track_dir: Path) -> dict:
    p = track_dir / "state.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return _empty_state()


def _save_state(track_dir: Path, state: dict) -> None:
    (track_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def run_once(
    base_url: str = DEFAULT_BASE_URL,
    tf: str = "1h",
    params: dict | None = None,
    cost_bps_per_leg: float = DEFAULT_COST_BPS_PER_LEG,
    track_base: Path | None = None,
    pair: str = "ES-NQ",
) -> dict:  # pragma: no cover - orchestration over network + files
    """One observe-only tick for ONE pair: fetch -> compute z -> transition -> persist.
    Idempotent within an hour (skips if the latest bar timestamp was already processed).

    `pair` keys into PAIR_REGISTRY; ES-NQ keeps the legacy root ledger (subdir="") so its
    live forward record is undisturbed, MES-M2K writes to its own subdir."""
    params = params or DEFAULT_PARAMS
    cfg = PAIR_REGISTRY[pair]
    sym_a, sym_b = cfg["sym_a"], cfg["sym_b"]
    td = _track_dir(track_base, cfg["subdir"])
    now = datetime.now(timezone.utc).isoformat()
    api_key = _read_api_key()

    try:
        bars_a = fetch_bars(sym_a, base_url, api_key, tf)
        bars_b = fetch_bars(sym_b, base_url, api_key, tf)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        obs = {"run_at": now, "pair": pair, "event": "fetch_failed", "error": str(e)}
        _append_jsonl(td / "observations.jsonl", obs)
        return obs

    aligned = align_latest(bars_a, bars_b, params["window"])
    if aligned is None:
        obs = {
            "run_at": now,
            "pair": pair,
            "event": "insufficient_data",
            "n_a": len(bars_a),
            "n_b": len(bars_b),
        }
        _append_jsonl(td / "observations.jsonl", obs)
        return obs

    ts, es, nq, z = aligned
    state = _load_state(td)

    if state.get("last_bar_ts") == ts:
        obs = {
            "run_at": now,
            "pair": pair,
            "event": "no_new_bar",
            "bar_ts": ts,
            "z": round(z, 4),
            "position": state.get("position", 0),
        }
        _append_jsonl(td / "observations.jsonl", obs)
        return obs

    new_state, event, closed = decide_transition(
        state,
        z,
        es,
        nq,
        ts,
        params,
        cost_bps_per_leg,
        pair_symbol=cfg["symbol"],
        lineage=cfg["lineage"],
    )
    _save_state(td, new_state)
    if closed is not None:
        _append_jsonl(td / "closed_trades.jsonl", closed)
    obs = {
        "run_at": now,
        "pair": pair,
        "bar_ts": ts,
        "event": event,
        "z": round(z, 4),
        "es": es,
        "nq": nq,
        "position": new_state["position"],
        "closed_pnl": closed["pnl"] if closed else None,
    }
    _append_jsonl(td / "observations.jsonl", obs)
    return obs


def load_closed_trades(track_base: Path | None = None, subdir: str = "") -> list[dict]:
    p = _track_dir(track_base, subdir) / "closed_trades.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def report(
    track_base: Path | None = None,
    window_days: int = 30,
    subdir: str = "",
    lineage: str = LINEAGE,
) -> dict:
    """Grade ONE pair's forward record on the SAME gate-v2 bar as the rest of the campaign,
    by reusing forward_test.build_windows / forward_stats over the isolated ledger."""
    from backtest.forward_test import build_windows, forward_stats

    closed = load_closed_trades(track_base, subdir)
    windows = build_windows(closed, window_days)
    stats = forward_stats(windows)
    stats["n_closed_trades"] = len(closed)
    stats["total_pnl_dollars"] = round(sum(t.get("pnl", 0.0) for t in closed), 2)
    return {"lineage": lineage, "windows": windows, "stats": stats}


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--report", action="store_true", help="print the forward record + gate-v2 stats"
    )
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--window-days", type=int, default=30)
    ap.add_argument(
        "--pair",
        default=None,
        help="run/report a single pair (default: all of PAIR_REGISTRY)",
    )
    args = ap.parse_args()
    pairs = [args.pair] if args.pair else list(PAIR_REGISTRY)

    if args.report:
        for pair in pairs:
            cfg = PAIR_REGISTRY[pair]
            rep = report(window_days=args.window_days, subdir=cfg["subdir"], lineage=cfg["lineage"])
            print(f"\n=== {pair} ({cfg['lineage']}) ===")
            print(json.dumps(rep["stats"], indent=2))
            print(f"windows ({len(rep['windows'])}):")
            for w in rep["windows"]:
                print(
                    f"  {w['start']}..{w['end']}: n={w['n_trades']} pf={w['pf']:.3f} pnl={w['pnl']:.2f}"
                )
        return

    for pair in pairs:
        obs = run_once(base_url=args.base_url, pair=pair)
        print(json.dumps(obs, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
