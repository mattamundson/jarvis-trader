"""Funnel orchestrator: cards -> smoke -> robustness, all logged to the results DB.

Two-pass so the Deflated-Sharpe denominator is honest. Pass 1 enumerates every
candidate (card x native-instrument-in-universe x native-timeframe-in-universe) and
sums the total parameterizations the factory will try; that fixed total is the DSR
`n_trials` for EVERY survivor (multiple-testing is global, not per-card). Pass 2
runs smoke, then the robustness gauntlet only on smoke survivors. Every candidate
and every verdict is written to `ResultsDB` -- the audit trail that forecloses the
"quietly tested a tiny subset" failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backtest.factory.data import load_bars, spec_for
from backtest.factory.funnel import robustness_gauntlet, smoke_test
from backtest.factory.results_db import ResultsDB
from backtest.factory.strategy_card import StrategyCard


@dataclass
class Universe:
    instruments: list[str]
    timeframes: list[str]


def pilot_cards() -> list[StrategyCard]:
    """Four economically-motivated cards on generic column-emitting generators.

    Every card carries a real `economic_rationale` (the gate kills blank ones) and
    a small param grid. ORB/TPO have dedicated engines and are out of pilot scope.
    """
    return [
        StrategyCard(
            name="donchian_breakout",
            family="breakout",
            signal_ref="backtest.donchian_signals:generate_donchian_signals",
            entry="close breaks the N-bar high (channel breakout)",
            exit="opposite M-bar channel / ATR trail",
            economic_rationale="Trend persistence: a fresh N-bar breakout reflects a "
            "genuine order-flow imbalance (stops + breakout buyers) that tends to "
            "continue for several bars before mean-reverting.",
            native_instruments=["MES", "SPY"],
            native_timeframes=["1h"],
            default_params={"lookback_entry": 20, "lookback_exit": 10},
            param_grid={"lookback_entry": [20, 40, 55], "lookback_exit": [10, 20]},
            known_failure_modes=["chop/range regimes whipsaw the breakout"],
        ),
        StrategyCard(
            name="bollinger_rsi_meanrev",
            family="meanrev",
            signal_ref="backtest.meanrev_signals:generate_bollinger_rsi_signals",
            entry="price pierces lower/upper Bollinger band with RSI confirming exhaustion",
            exit="reversion to the band midline / ATR stop",
            economic_rationale="Short-horizon mean reversion: a 2-sigma band stretch with "
            "an RSI extreme marks a liquidity-driven overshoot that statistically snaps "
            "back toward the moving-average anchor intraday.",
            native_instruments=["MES", "SPY"],
            native_timeframes=["1h"],
            default_params={"bb_period": 20, "bb_std": 2.0, "rsi_long": 30.0, "rsi_short": 70.0},
            param_grid={"bb_period": [15, 20], "rsi_long": [25.0, 30.0]},
            known_failure_modes=["strong trends keep price pinned to one band"],
        ),
        StrategyCard(
            name="adx_ema_trend",
            family="trend",
            signal_ref="backtest.adx_ema_signals:generate_adx_ema_signals",
            entry="EMA slope direction with ADX above the strong-trend threshold",
            exit="ADX falls below exit threshold / ATR trail",
            economic_rationale="Trend-following with a strength gate: ADX confirms a "
            "directional regime so the EMA-slope entry only fires when a real trend (not "
            "noise) is paying, capturing the autocorrelation in trending instruments.",
            native_instruments=["MES", "SPY"],
            native_timeframes=["1h", "1d"],
            default_params={"adx_threshold": 25.0, "ema_period": 21},
            param_grid={"adx_threshold": [20.0, 25.0], "ema_period": [21, 50]},
            known_failure_modes=["lag at trend turns; ADX gate mutes early entries"],
        ),
        StrategyCard(
            name="sma_trend",
            family="trend",
            signal_ref="backtest.trend_signals:generate_sma_trend_signals",
            entry="fast SMA above/below slow SMA (classic dual-MA trend)",
            exit="opposite cross / ATR trail",
            economic_rationale="Long-horizon trend premium: the dual-SMA cross harvests "
            "the documented time-series momentum premium in equity indices, which is "
            "strongest on the daily timeframe over multi-month holds.",
            native_instruments=["MES", "SPY"],
            native_timeframes=["1d"],
            default_params={"fast": 60, "slow": 200},
            param_grid={"fast": [40, 60], "slow": [150, 200]},
            known_failure_modes=["range-bound years bleed via repeated false crosses"],
        ),
    ]


def enumerate_candidates(
    cards: list[StrategyCard], universe: Universe
) -> list[tuple[StrategyCard, str, str]]:
    """Card x (native instruments ∩ universe) x (native timeframes ∩ universe)."""
    inst = set(universe.instruments)
    tfs = set(universe.timeframes)
    out = []
    for card in cards:
        for sym in [s for s in card.native_instruments if s in inst]:
            for tf in [t for t in card.native_timeframes if t in tfs]:
                out.append((card, sym, tf))
    return out


def run_funnel(
    cards: list[StrategyCard],
    universe: Universe,
    cache_dir: str | Path,
    db_path: str | Path,
    created_at: str,
) -> dict:
    """Run the full pilot funnel. Returns a summary dict; full detail is in the DB."""
    db = ResultsDB(db_path)
    run_id = db.new_run(
        created_at,
        {"universe": vars(universe), "n_cards": len(cards), "cache_dir": str(cache_dir)},
    )

    candidates = enumerate_candidates(cards, universe)
    # Global DSR denominator = total parameterizations the factory will try.
    global_trials = sum(c.n_param_combos() for c, _, _ in candidates)

    rows = []
    for card, sym, tf in candidates:
        cid = db.record_candidate(run_id, card.name, sym, tf, card.default_params, "smoke")
        try:
            bars = load_bars(sym, tf, cache_dir)
        except FileNotFoundError as e:
            db.record_result(cid, "smoke", {"error": str(e)}, verdict="SKIP", kill_reason="no data")
            rows.append(
                {"card": card.name, "sym": sym, "tf": tf, "stage": "skip", "reason": "no data"}
            )
            continue
        mult = float(spec_for(sym)["multiplier"])

        survives, sm = smoke_test(card, bars, sym, mult)
        db.record_result(
            cid,
            "smoke",
            sm,
            verdict="PASS" if survives else "KILL",
            kill_reason=sm.get("kill_reason"),
        )
        row = {"card": card.name, "sym": sym, "tf": tf, "smoke": sm, "smoke_pass": survives}
        if not survives:
            row["stage"] = "killed_smoke"
            rows.append(row)
            continue

        gate = robustness_gauntlet(card, bars, sym, mult, global_trials)
        verdict = gate.get("verdict", "FAIL")
        db.record_result(cid, "robustness", gate, verdict=verdict)
        row["stage"] = "robustness"
        row["gate"] = gate
        row["verdict"] = verdict
        rows.append(row)

    summary = {
        "run_id": run_id,
        "created_at": created_at,
        "global_trials": global_trials,
        "n_candidates": len(candidates),
        "n_smoke_pass": sum(1 for r in rows if r.get("smoke_pass")),
        "n_robustness_pass": sum(1 for r in rows if r.get("verdict") == "PASS"),
        "rows": rows,
    }
    db.close()
    return summary


def render_report(summary: dict) -> str:
    """Markdown pilot report -- survivors, kills with reasons, and the global wiring."""
    s = summary
    lines = [
        "# Strategy-Factory Pilot Report",
        "",
        f"- Run ID: `{s['run_id']}`  |  Created: {s['created_at']}",
        f"- Candidates screened: **{s['n_candidates']}**  "
        f"(global DSR n_trials = **{s['global_trials']}** parameterizations)",
        f"- Smoke survivors: **{s['n_smoke_pass']}**  |  Robustness PASS: **{s['n_robustness_pass']}**",
        "",
        "## Per-candidate",
        "",
        "| Card | Sym | TF | Smoke | Verdict | OOS PF | mc_dd% | dsr | dsr_global | PBO |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in s["rows"]:
        smoke = "PASS" if r.get("smoke_pass") else ("skip" if r.get("stage") == "skip" else "KILL")
        g = r.get("gate", {}) or {}
        verdict = r.get("verdict", "-")
        pf = _fmt(g.get("pf_ci_lower"))
        dd = _fmt(g.get("mc_95th_dd_pct", g.get("mc_95th_dd")))
        dsr = _fmt(g.get("dsr"))
        dsrg = _fmt(g.get("dsr_global"))
        pbo = _fmt(g.get("pbo"))
        lines.append(
            f"| {r['card']} | {r['sym']} | {r['tf']} | {smoke} | {verdict} "
            f"| {pf} | {dd} | {dsr} | {dsrg} | {pbo} |"
        )

    # Kill reasons (Amo's explicit ask: why each failed is as valuable as survivors).
    lines += ["", "## Kill / fail reasons", ""]
    for r in s["rows"]:
        if r.get("smoke_pass") and r.get("verdict") == "PASS":
            continue
        if not r.get("smoke_pass"):
            reason = (r.get("smoke", {}) or {}).get("kill_reason") or r.get(
                "reason", "below smoke floor"
            )
            lines.append(f"- **{r['card']} {r['sym']} {r['tf']}** — killed at smoke: {reason}")
        else:
            g = r.get("gate", {}) or {}
            reason = g.get("reason") or _gate_fail_reason(g)
            lines.append(
                f"- **{r['card']} {r['sym']} {r['tf']}** — robustness {r.get('verdict')}: {reason}"
            )
    return "\n".join(lines)


def _fmt(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return str(v)


def _gate_fail_reason(gate: dict) -> str:
    """Best-effort human reason from gate sub-metrics."""
    bits = []
    if gate.get("pf_ci_lower") is not None and gate["pf_ci_lower"] < 1.10:
        bits.append(f"pf_ci_lower {gate['pf_ci_lower']:.2f}<1.10")
    if gate.get("p_edge") is not None and gate["p_edge"] < 0.95:
        bits.append(f"p_edge {gate['p_edge']:.2f}<0.95")
    dd = gate.get("mc_95th_dd_pct", gate.get("mc_95th_dd"))
    if dd is not None and dd > 5.0:
        bits.append(f"mc_dd {dd:.1f}%>5%")
    if gate.get("dsr") is not None and gate["dsr"] < 0.10:
        bits.append(f"dsr {gate['dsr']:.2f}<0.10")
    if gate.get("pbo") is not None and gate["pbo"] > 0.5:
        bits.append(f"PBO {gate['pbo']:.2f}>0.5 (overfit)")
    return "; ".join(bits) if bits else "did not clear gate-v2 core or ALT"
