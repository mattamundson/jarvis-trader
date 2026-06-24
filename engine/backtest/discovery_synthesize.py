#!/usr/bin/env python
"""
JARVIS TRADER -- discovery-factory synthesizer (Phase 3, Stage 3).

Read-only aggregator over the per-spec verdict JSONs the discovery factory
writes to ``data/discovery_factory/``. It does NOT run backtests and does NOT
touch ``gate_v2_verdicts/`` -- it only reads what the factory already produced
and ranks it into a human-facing findings report.

Why read per-spec JSONs (not LEADERBOARD.json): when several targeted sweeps
run concurrently (e.g. MGC 5m + ORB at once), each ``main()`` overwrites
LEADERBOARD.json with only its own specs, so the leaderboard is racy and
partial. The per-spec ``{label}.json`` files are write-once-per-spec and never
collide, so they are the durable source of truth.

Output:
  * stdout: a ranked table (PASS -> near-miss -> FAIL -> INSUFFICIENT_SAMPLE)
  * data/discovery_factory/FINDINGS.md: the same table plus a candidate brief
    for every spec that PASSED with >= MIN_OOS_TRADES_TOTAL trades, and an
    explicit honest-negative section when nothing passes.

Usage (from engine/):
    .venv/Scripts/python -m backtest.discovery_synthesize
    .venv/Scripts/python -m backtest.discovery_synthesize --tag intraday
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

engine_root = Path(__file__).parent.parent
OUTPUT_DIR = engine_root / "data" / "discovery_factory"
MIN_OOS_TRADES_TOTAL = 30  # mirror _gate_v2_helpers; sample-adequacy floor


def _do_not_trade() -> frozenset[str]:
    """The live engine's symbol block list -- the single source of truth. A
    candidate on one of these has passed the *discovery* gate but is STILL
    barred from live/paper, so the brief must say so. Lazy import keeps the
    synthesizer runnable standalone; fall back to the known set if signals
    can't be imported (e.g. outside the engine venv)."""
    try:
        from backtest import signals

        return frozenset(signals.DO_NOT_TRADE_SYMBOLS)
    except Exception:
        return frozenset({"MCL", "MNQ", "M2K"})


DO_NOT_TRADE = _do_not_trade()


def _load_specs(output_dir: Path) -> list[dict]:
    """Load every per-spec verdict JSON (skip the racy LEADERBOARD aggregate)."""
    specs = []
    for f in sorted(glob.glob(str(output_dir / "*.json"))):
        if os.path.basename(f) == "LEADERBOARD.json":
            continue
        try:
            specs.append(json.load(open(f)))
        except (json.JSONDecodeError, OSError):
            continue  # a spec mid-write; skip and let the next run pick it up
    return specs


def _metrics(d: dict) -> dict:
    """Flatten the nested gate_v2 block to the handful of fields we rank on."""
    g = d.get("gate_v2") or d.get("gate_v2_metrics") or {}
    return {
        "label": d.get("label"),
        "symbol": d.get("symbol"),
        "family": d.get("family"),
        "interval": d.get("interval"),
        "verdict": d.get("verdict"),
        "passed_via": d.get("passed_via"),
        "source_file": d.get("source_file"),
        "champion_params": d.get("champion_params") or {},
        "tags": tuple(d.get("tags") or ()),
        "pf_ci_lower": g.get("pf_ci_lower"),
        "p_edge": g.get("p_edge"),
        "dsr": g.get("dsr"),
        "mc_95th_dd_pct": g.get("mc_95th_dd_pct"),
        "wfo_consistency": g.get("wfo_consistency"),
        "fixed_params_min_pf": g.get("fixed_params_min_pf"),
        "cost_survives_through": g.get("cost_survives_through"),
        "total_oos_trades": g.get("total_oos_trades"),
        "sample_adequate": g.get("sample_adequate"),
    }


def _is_near_miss(m: dict) -> bool:
    """A FAIL that has an adequate sample AND already clears the two hardest
    structural bars (PF lower-bound >= 1.10 and DSR >= 0.10). These are the
    rows worth deeper data / a tweak, vs. structural no-edge FAILs."""
    if m["verdict"] != "FAIL":
        return False
    pf, dsr, n = m["pf_ci_lower"], m["dsr"], m["total_oos_trades"]
    return bool(
        n
        and n >= MIN_OOS_TRADES_TOTAL
        and pf is not None
        and pf >= 1.10
        and dsr is not None
        and dsr >= 0.10
    )


def _rank_key(m: dict) -> tuple:
    order = {"PASS": 0, "FAIL": 1, "INSUFFICIENT_SAMPLE": 2}
    # within a bucket, sort by DSR then PF lower-bound (desc)
    return (
        order.get(m["verdict"], 3),
        0 if not _is_near_miss(m) else -1,  # near-misses float to the top of FAIL
        -(m["dsr"] or 0.0),
        -(m["pf_ci_lower"] or 0.0),
    )


def _fmt(v, nd=4):
    return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def _table(rows: list[dict]) -> str:
    hdr = (
        f"{'LABEL':<26} {'VERDICT':<19} {'TRADES':>6} {'PF_LO':>7} "
        f"{'P_EDGE':>7} {'DSR':>7} {'DD%':>6} {'WFO':<9}"
    )
    lines = [hdr, "-" * len(hdr)]
    for m in rows:
        flag = " *" if _is_near_miss(m) else ""
        if m["symbol"] in DO_NOT_TRADE:
            flag += " !DNT"
        lines.append(
            f"{(m['label'] or '?'):<26} {(m['verdict'] or '?'):<19} "
            f"{_fmt(m['total_oos_trades']):>6} {_fmt(m['pf_ci_lower'], 3):>7} "
            f"{_fmt(m['p_edge'], 3):>7} {_fmt(m['dsr'], 3):>7} "
            f"{_fmt(m['mc_95th_dd_pct'], 2):>6} {(m['wfo_consistency'] or '-'):<9}{flag}"
        )
    return "\n".join(lines)


# ALT drawdown ceiling for $50K+ routing (GATE_MC_DD_ALT=0.04). A PASS that
# clears it by less than this epsilon is a razor-thin margin, not robust headroom.
_ALT_DD_CEILING_PCT = 4.0
_DD_MARGIN_EPS_PCT = 0.1


def _fragility_warnings(m: dict) -> list[str]:
    """Single-spec heuristics that flag a PASS as fragile / not yet trustworthy.

    The synthesizer reads one spec at a time and cannot see cross-size context,
    so it cannot prove a knife-edge by itself -- but two signals ARE visible from
    one JSON and reliably mark a pass that needs more scrutiny before promotion."""
    warns: list[str] = []
    dd = m.get("mc_95th_dd_pct")
    if (
        m.get("passed_via") == "alt"
        and dd is not None
        and dd >= _ALT_DD_CEILING_PCT - _DD_MARGIN_EPS_PCT
    ):
        warns.append(
            f"**Razor-thin drawdown margin:** mc_95th_dd={dd:.2f}% clears the {_ALT_DD_CEILING_PCT:.0f}% "
            f"ALT ceiling by <{_DD_MARGIN_EPS_PCT:.1f}pp -- a coin-flip from FAIL, not robust headroom."
        )
    if "drawdown_attack" in m.get("tags", ()):
        warns.append(
            "**Sizing-tuned pass:** this spec was found by lowering `risk_per_trade` to fit the "
            "drawdown budget. The `max_drawdown=0.05` breaker couples size to per-window champion "
            "selection, so dsr and mc_95th_dd are non-monotonic in size -- a pass at one size is a "
            "knife-edge artifact unless it holds across a BAND. Verify against the size band before "
            "trusting (see DRAWDOWN_ATTACK_FINDINGS.md)."
        )
    return warns


def _candidate_brief(m: dict) -> str:
    dnt = ""
    if m["symbol"] in DO_NOT_TRADE:
        dnt = (
            f"\n> **⛔ {m['symbol']} IS ON THE LIVE `DO_NOT_TRADE_SYMBOLS` BLOCK LIST.** "
            f"Passing the discovery gate does NOT lift that block. This combo cannot be "
            f"promoted to live/paper without first resolving why {m['symbol']} is barred "
            f"(see signals.DO_NOT_TRADE_SYMBOLS / rules/jarvis-trader.md) -- a separate, "
            f"explicit human decision.\n"
        )
    frag = ""
    for w in _fragility_warnings(m):
        frag += f"\n> ⚠️ {w}\n"
    return (
        f"### CANDIDATE: {m['label']}  (passed_via={m['passed_via']})\n"
        f"{dnt}{frag}\n"
        f"- **Symbol / family / interval:** {m['symbol']} / {m['family']} / {m['interval']}\n"
        f"- **Champion params:** `{json.dumps(m['champion_params'])}`\n"
        f"- **Found on cache:** `{m['source_file']}`\n"
        f"- **Sample:** {m['total_oos_trades']} OOS trades (adequate={m['sample_adequate']})\n"
        f"- **Gate metrics:** pf_ci_lower={_fmt(m['pf_ci_lower'],3)}, p_edge={_fmt(m['p_edge'],3)}, "
        f"dsr={_fmt(m['dsr'],3)}, mc_95th_dd={_fmt(m['mc_95th_dd_pct'],2)}%, "
        f"wfo={m['wfo_consistency']}, cost_survives={m['cost_survives_through']}\n\n"
        f"> Research candidate only. Promotion to live/paper is a **human** decision "
        f"(Phase 1 unified config) -- the factory never writes gate_v2_verdicts/.\n"
    )


def _sample_ok(m: dict) -> bool:
    n = m["total_oos_trades"]
    return bool(n and n >= MIN_OOS_TRADES_TOTAL)


def synthesize(output_dir: Path, tag_filter: str | None = None) -> dict:
    specs = [_metrics(d) for d in _load_specs(output_dir)]
    if tag_filter:
        specs = [m for m in specs if tag_filter in m["tags"]]
    specs.sort(key=_rank_key)

    # A candidate must BOTH pass the gate AND clear the sample floor. A PASS with
    # < 30 OOS trades is statistically indistinguishable from INSUFFICIENT_SAMPLE
    # (the post-gate override should catch it; older verdict JSONs predate that),
    # so we never brief it as deployable -- we surface it as an under-sampled caution.
    passes = [m for m in specs if m["verdict"] == "PASS" and _sample_ok(m)]
    undersampled_pass = [m for m in specs if m["verdict"] == "PASS" and not _sample_ok(m)]
    near = [m for m in specs if _is_near_miss(m)]

    md = ["# Discovery-factory findings\n"]
    md.append(
        f"_{len(specs)} specs synthesized | {len(passes)} deployable PASS (>= "
        f"{MIN_OOS_TRADES_TOTAL} trades) | {len(undersampled_pass)} under-sampled PASS | "
        f"{len(near)} near-miss (FAIL w/ adequate sample, PF>=1.10, DSR>=0.10)_\n"
    )
    md.append("```\n" + _table(specs) + "\n```")
    md.append("\n`*` = near-miss watchlist.\n")

    if undersampled_pass:
        rows = ", ".join(f"{m['label']} (n={m['total_oos_trades']})" for m in undersampled_pass)
        md.append(
            f"\n## Caution -- under-sampled PASS (NOT candidates)\n\n"
            f"These cleared the gate metrics but on **< {MIN_OOS_TRADES_TOTAL} OOS trades**, so "
            f"the result is statistical noise, not an edge -- treated as INSUFFICIENT_SAMPLE and "
            f"**not** briefed for promotion: {rows}.\n"
        )

    if passes:
        md.append("\n## Candidate briefs (PASS, sample-adequate)\n")
        for m in passes:
            md.append(_candidate_brief(m))
    else:
        md.append(
            "\n## Honest negative\n\n"
            "**Zero specs PASSED gate-v2 (core or alt).** This is a valid, trustworthy "
            "result -- the factory's job includes producing fast, honest negatives so we "
            "don't deploy un-edged strategies. The near-miss rows above (if any) are the "
            "only ones worth a second look: they clear the structural bars (sample, PF "
            "lower-bound, DSR) and fail on p_edge / drawdown, which is where deeper data or "
            "a regime filter could plausibly move the needle. Everything else is a "
            "structural no-edge FAIL or data-starved INSUFFICIENT_SAMPLE.\n"
        )

    report = "\n".join(md)
    (output_dir / "FINDINGS.md").write_text(report, encoding="utf-8")
    return {"n_specs": len(specs), "n_pass": len(passes), "n_near": len(near), "report": report}


def main() -> None:
    ap = argparse.ArgumentParser(description="Synthesize discovery-factory verdicts.")
    ap.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="dir of per-spec verdict JSONs (default data/discovery_factory/)",
    )
    ap.add_argument("--tag", default=None, help="only specs carrying this tag (e.g. intraday)")
    args = ap.parse_args()

    res = synthesize(Path(args.output_dir), tag_filter=args.tag)
    print("\n".join(res["report"].split("\n")))
    print(f"\n-> wrote {Path(args.output_dir) / 'FINDINGS.md'}")
    print(f"   {res['n_specs']} specs | {res['n_pass']} PASS | {res['n_near']} near-miss")


if __name__ == "__main__":
    main()
