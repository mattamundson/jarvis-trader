"""
Weekly Strategy Tracker — OneDrive-synced status dashboard
==========================================================

Reads strategy cards and verdicts from a OneDrive sync folder, computes
week-over-week movement, and produces an HTML tearsheet plus a JSON snapshot
for downstream notifications.

Run manually:
    python -m jarvis_funnel.tracker \
        --sync-root "C:/Users/matt/OneDrive/jarvis-trader-handoff" \
        --notify

Or scheduled (cron / Task Scheduler / Computer cron):
    python -m jarvis_funnel.tracker --sync-root ... --notify --quiet

Outputs (under {sync-root}/tracker/):
  - week_YYYY-WW.html        — full HTML tearsheet for the week
  - week_YYYY-WW.json        — machine-readable snapshot
  - latest.html              — symlink/copy of current week
  - history.jsonl            — append-only weekly summaries
  - state.json               — last-run state for delta computation
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis_funnel.tracker")


# ── Configuration ────────────────────────────────────────────────────────────

# Directory layout expected under --sync-root:
#   cards/strategies_current.jsonl   (live, mutable card list)
#   verdicts/{hypothesis_id}__verdict.json
#   results/{hypothesis_id}/...
#   tracker/                          (this script's output)
DIRS = {
    "cards": "cards",
    "verdicts": "verdicts",
    "results": "results",
    "tracker": "tracker",
}


# ── Snapshot Data Model ──────────────────────────────────────────────────────


@dataclass
class StrategySnapshot:
    hypothesis_id: str
    name: str
    category: str
    tier: Optional[str]
    dsr: Optional[float]
    pbo: Optional[float]
    sharpe_oos: Optional[float]
    pf_ci_lower: Optional[float]
    n_oos_trades: Optional[int]
    failed_gates: list = field(default_factory=list)
    phase_status: dict = field(default_factory=dict)
    last_verdict_at: Optional[str] = None
    flags: list = field(default_factory=list)  # ["near_threshold", "gate_v2_disagreement", "contamination"]


@dataclass
class WeeklySnapshot:
    week_id: str  # YYYY-WW
    snapshot_at: str
    counts_by_tier: dict = field(default_factory=dict)
    strategies: list = field(default_factory=list)
    promotions: list = field(default_factory=list)  # B→A
    demotions: list = field(default_factory=list)  # A→C, A→B, B→C
    new_strategies: list = field(default_factory=list)
    near_threshold: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)
    disagreements: list = field(default_factory=list)


# ── Loading ──────────────────────────────────────────────────────────────────


def load_current_cards(sync_root: Path) -> dict[str, dict]:
    """Load strategies_current.jsonl into hypothesis_id -> card dict."""
    cards_file = sync_root / DIRS["cards"] / "strategies_current.jsonl"
    if not cards_file.exists():
        # Fall back to latest vN file
        cards_dir = sync_root / DIRS["cards"]
        v_files = sorted(cards_dir.glob("strategies_v*.jsonl"))
        if not v_files:
            logger.warning(f"No strategy card files found in {cards_dir}")
            return {}
        cards_file = v_files[-1]
        logger.info(f"Using {cards_file.name} as strategies_current substitute")

    cards = {}
    with cards_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            card = json.loads(line)
            cards[card["hypothesis_id"]] = card
    logger.info(f"Loaded {len(cards)} cards from {cards_file.name}")
    return cards


def load_verdicts(sync_root: Path) -> dict[str, dict]:
    verdicts_dir = sync_root / DIRS["verdicts"]
    verdicts = {}
    if not verdicts_dir.exists():
        return verdicts
    for vf in verdicts_dir.glob("*__verdict.json"):
        try:
            data = json.loads(vf.read_text(encoding="utf-8"))
            verdicts[data["hypothesis_id"]] = data
        except Exception as e:
            logger.warning(f"Failed to load {vf}: {e}")
    return verdicts


def load_state(sync_root: Path) -> dict:
    state_file = sync_root / DIRS["tracker"] / "state.json"
    if not state_file.exists():
        return {"last_week_id": None, "last_snapshot": {}}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load state: {e}")
        return {"last_week_id": None, "last_snapshot": {}}


def save_state(sync_root: Path, state: dict) -> None:
    state_file = sync_root / DIRS["tracker"] / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── Snapshot Computation ─────────────────────────────────────────────────────


def build_strategy_snapshots(cards: dict[str, dict], verdicts: dict[str, dict]) -> list[StrategySnapshot]:
    """Combine cards + verdicts into per-strategy snapshots."""
    snapshots = []

    for hid, card in cards.items():
        verdict = verdicts.get(hid, {})

        # Extract metrics from verdict's gate_results
        gate_metrics = {g["gate_number"]: g for g in verdict.get("gate_results", [])}
        dsr = verdict.get("overall_dsr")
        pbo = gate_metrics.get(2, {}).get("actual_value") if 2 in gate_metrics else None
        pf_ci = gate_metrics.get(3, {}).get("actual_value") if 3 in gate_metrics else None
        sr_oos = None  # not directly in verdict; would need results aggregation
        n_oos = gate_metrics.get(5, {}).get("actual_value") if 5 in gate_metrics else None

        snap = StrategySnapshot(
            hypothesis_id=hid,
            name=card.get("name", hid),
            category=card.get("category", ""),
            tier=verdict.get("tier") or card.get("current_tier"),
            dsr=dsr,
            pbo=pbo,
            sharpe_oos=sr_oos,
            pf_ci_lower=pf_ci,
            n_oos_trades=int(n_oos) if n_oos is not None else None,
            failed_gates=verdict.get("failed_gates", []),
            phase_status={
                "phase_1": card.get("phase_1_status"),
                "phase_2": card.get("phase_2_status"),
                "phase_3": card.get("phase_3_status"),
                "phase_4": card.get("phase_4_status"),
            },
            last_verdict_at=verdict.get("verdict_timestamp"),
        )

        # Flag computation
        if verdict.get("gate_v2_disagreement"):
            snap.flags.append("gate_v2_disagreement")
        if 10 in snap.failed_gates:
            snap.flags.append("contamination")
        if _is_near_threshold(snap):
            snap.flags.append("near_threshold")

        snapshots.append(snap)

    return snapshots


def _is_near_threshold(snap: StrategySnapshot) -> bool:
    """Within 10% of next tier boundary on ≥ 2 metrics."""
    near_count = 0
    if snap.dsr is not None:
        # Near DSR floor (0.80 for Tier A, 1.0 for Tier B confirm)
        if snap.tier == "B" and 0.70 <= snap.dsr < 0.80:
            near_count += 1
        elif snap.tier == "C" and snap.dsr >= 0.72:
            near_count += 1
    if snap.pbo is not None and snap.tier in {"B", "C"} and 0.40 <= snap.pbo <= 0.45:
        near_count += 1
    if snap.pf_ci_lower is not None and snap.tier in {"B", "C"} and 1.03 <= snap.pf_ci_lower <= 1.15:
        near_count += 1
    return near_count >= 2


def compute_deltas(current: list[StrategySnapshot], previous_state: dict) -> tuple[list, list, list]:
    """Compute (promotions, demotions, new_strategies) vs. last snapshot."""
    previous = {s["hypothesis_id"]: s for s in previous_state.get("last_snapshot", {}).get("strategies", [])}

    promotions, demotions, new_strats = [], [], []
    tier_rank = {"C": 0, "B": 1, "A": 2}

    for snap in current:
        prev = previous.get(snap.hypothesis_id)
        if prev is None:
            new_strats.append({"hypothesis_id": snap.hypothesis_id, "name": snap.name, "tier": snap.tier})
            continue
        prev_tier = prev.get("tier")
        if prev_tier == snap.tier:
            continue
        if prev_tier in tier_rank and snap.tier in tier_rank:
            if tier_rank[snap.tier] > tier_rank[prev_tier]:
                promotions.append({
                    "hypothesis_id": snap.hypothesis_id, "name": snap.name,
                    "from": prev_tier, "to": snap.tier,
                })
            else:
                demotions.append({
                    "hypothesis_id": snap.hypothesis_id, "name": snap.name,
                    "from": prev_tier, "to": snap.tier,
                })

    return promotions, demotions, new_strats


def detect_anomalies(current: list[StrategySnapshot], previous_state: dict) -> list[dict]:
    """Detect suspicious week-over-week metric jumps."""
    anomalies = []
    previous = {s["hypothesis_id"]: s for s in previous_state.get("last_snapshot", {}).get("strategies", [])}

    for snap in current:
        prev = previous.get(snap.hypothesis_id)
        if not prev:
            continue
        # Suspicious DSR jump
        prev_dsr = prev.get("dsr")
        if prev_dsr is not None and snap.dsr is not None:
            if abs(snap.dsr - prev_dsr) > 0.5:
                anomalies.append({
                    "hypothesis_id": snap.hypothesis_id,
                    "type": "large_dsr_jump",
                    "from": prev_dsr, "to": snap.dsr,
                    "investigate": "Verify backtest data hasn't been recalibrated or contaminated"
                })

    return anomalies


# ── HTML Rendering ───────────────────────────────────────────────────────────


def render_html(snap: WeeklySnapshot) -> str:
    """Generate the weekly HTML tearsheet."""
    css = """
<style>
  body { font-family: -apple-system, system-ui, sans-serif; margin: 32px; max-width: 1200px; color: #1f2328; }
  h1, h2, h3 { color: #1f2328; }
  h1 { border-bottom: 2px solid #d0d7de; padding-bottom: 8px; }
  h2 { margin-top: 28px; border-bottom: 1px solid #d0d7de; padding-bottom: 4px; }
  .summary { display: flex; gap: 24px; margin: 16px 0; }
  .tier-card { padding: 16px 24px; border-radius: 8px; flex: 1; }
  .tier-A { background: #dafbe1; border: 1px solid #2da44e; }
  .tier-B { background: #fff8c5; border: 1px solid #d4a72c; }
  .tier-C { background: #ffebe9; border: 1px solid #cf222e; }
  .tier-card .count { font-size: 32px; font-weight: 600; }
  .tier-card .label { font-size: 14px; color: #57606a; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }
  th, td { border: 1px solid #d0d7de; padding: 6px 10px; text-align: left; }
  th { background: #f6f8fa; }
  .flag { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-right: 4px; }
  .flag-warning { background: #fff8c5; color: #7d4900; }
  .flag-danger { background: #ffebe9; color: #82071e; }
  .flag-info { background: #ddf4ff; color: #0a3069; }
  .empty { color: #57606a; font-style: italic; }
  .delta-up { color: #1a7f37; font-weight: 600; }
  .delta-down { color: #cf222e; font-weight: 600; }
  .meta { color: #57606a; font-size: 12px; }
</style>
    """

    rows = ["<!doctype html>", "<html>", "<head>", "<meta charset='utf-8'>",
            f"<title>Jarvis Funnel — Week {snap.week_id}</title>", css, "</head>", "<body>"]
    rows.append(f"<h1>Jarvis Funnel — Week {snap.week_id}</h1>")
    rows.append(f"<div class='meta'>Snapshot: {snap.snapshot_at}</div>")

    # Tier summary
    counts = snap.counts_by_tier
    rows.append("<div class='summary'>")
    for tier, label in [("A", "Tier A — Paper Trade"), ("B", "Tier B — Watch List"), ("C", "Tier C — Killed")]:
        c = counts.get(tier, 0)
        rows.append(f"<div class='tier-card tier-{tier}'><div class='count'>{c}</div><div class='label'>{label}</div></div>")
    rows.append("</div>")

    # Promotions & demotions
    rows.append("<h2>Week-over-week movement</h2>")
    rows.append("<h3>Promotions</h3>")
    if snap.promotions:
        rows.append("<table><tr><th>Strategy</th><th>From</th><th>To</th></tr>")
        for p in snap.promotions:
            rows.append(f"<tr><td>{_e(p['name'])}<br><span class='meta'>{_e(p['hypothesis_id'])}</span></td>"
                        f"<td>{p['from']}</td><td class='delta-up'>{p['to']}</td></tr>")
        rows.append("</table>")
    else:
        rows.append("<div class='empty'>No promotions this week</div>")

    rows.append("<h3>Demotions</h3>")
    if snap.demotions:
        rows.append("<table><tr><th>Strategy</th><th>From</th><th>To</th></tr>")
        for d in snap.demotions:
            rows.append(f"<tr><td>{_e(d['name'])}<br><span class='meta'>{_e(d['hypothesis_id'])}</span></td>"
                        f"<td>{d['from']}</td><td class='delta-down'>{d['to']}</td></tr>")
        rows.append("</table>")
    else:
        rows.append("<div class='empty'>No demotions this week</div>")

    rows.append("<h3>New strategies entering pipeline</h3>")
    if snap.new_strategies:
        rows.append("<ul>")
        for n in snap.new_strategies:
            rows.append(f"<li>{_e(n['name'])} <span class='meta'>({_e(n['hypothesis_id'])})</span> — entering as Tier {n['tier'] or '?'}</li>")
        rows.append("</ul>")
    else:
        rows.append("<div class='empty'>No new strategies this week</div>")

    # Near-threshold
    rows.append("<h2>Near threshold (worth watching)</h2>")
    if snap.near_threshold:
        rows.append("<table><tr><th>Strategy</th><th>Tier</th><th>DSR</th><th>PBO</th><th>PF CI lower</th><th>Failed gates</th></tr>")
        for s in snap.near_threshold:
            rows.append(f"<tr><td>{_e(s['name'])}<br><span class='meta'>{_e(s['hypothesis_id'])}</span></td>"
                        f"<td>{s['tier']}</td><td>{_fmt(s['dsr'])}</td><td>{_fmt(s['pbo'])}</td>"
                        f"<td>{_fmt(s['pf_ci_lower'])}</td><td>{','.join(str(g) for g in s['failed_gates'])}</td></tr>")
        rows.append("</table>")
    else:
        rows.append("<div class='empty'>No strategies near a tier boundary</div>")

    # Anomalies
    rows.append("<h2>Anomalies</h2>")
    if snap.anomalies:
        rows.append("<table><tr><th>Strategy</th><th>Type</th><th>Detail</th><th>Investigate</th></tr>")
        for a in snap.anomalies:
            rows.append(f"<tr><td>{_e(a['hypothesis_id'])}</td><td>{a['type']}</td>"
                        f"<td>{_fmt(a.get('from'))} → {_fmt(a.get('to'))}</td><td>{_e(a.get('investigate', ''))}</td></tr>")
        rows.append("</table>")
    else:
        rows.append("<div class='empty'>No anomalies detected this week</div>")

    # Disagreements with gate_v2
    rows.append("<h2>Disagreements with gate_v2</h2>")
    if snap.disagreements:
        rows.append("<table><tr><th>Strategy</th><th>Funnel Tier</th><th>gate_v2</th></tr>")
        for d in snap.disagreements:
            rows.append(f"<tr><td>{_e(d['hypothesis_id'])}</td><td>{d['funnel_tier']}</td><td>{_e(d.get('gate_v2', ''))}</td></tr>")
        rows.append("</table>")
    else:
        rows.append("<div class='empty'>No disagreements this week</div>")

    # Full table
    rows.append("<h2>All strategies</h2>")
    rows.append("<table><tr><th>Strategy</th><th>Category</th><th>Tier</th><th>DSR</th><th>PBO</th><th>PF CI</th><th>OOS trades</th><th>Failed gates</th><th>Flags</th></tr>")
    for s in sorted(snap.strategies, key=lambda x: ({"A": 0, "B": 1, "C": 2, None: 3}.get(x["tier"], 3), x["name"])):
        flag_html = " ".join(f"<span class='flag flag-{'danger' if f == 'contamination' else 'warning' if f == 'gate_v2_disagreement' else 'info'}'>{f}</span>" for f in s["flags"])
        rows.append(f"<tr><td>{_e(s['name'])}<br><span class='meta'>{_e(s['hypothesis_id'])}</span></td>"
                    f"<td>{_e(s['category'])}</td><td>{s['tier'] or '—'}</td>"
                    f"<td>{_fmt(s['dsr'])}</td><td>{_fmt(s['pbo'])}</td><td>{_fmt(s['pf_ci_lower'])}</td>"
                    f"<td>{s['n_oos_trades'] if s['n_oos_trades'] is not None else '—'}</td>"
                    f"<td>{','.join(str(g) for g in s['failed_gates'])}</td><td>{flag_html}</td></tr>")
    rows.append("</table>")

    rows.append("</body></html>")
    return "\n".join(rows)


def _e(s) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


# ── Main ─────────────────────────────────────────────────────────────────────


def run_tracker(sync_root: Path, notify: bool = False) -> WeeklySnapshot:
    """Main orchestration."""
    now = datetime.now(timezone.utc)
    week_id = now.strftime("%G-%V")  # ISO week

    cards = load_current_cards(sync_root)
    verdicts = load_verdicts(sync_root)
    snapshots = build_strategy_snapshots(cards, verdicts)

    counts = {"A": 0, "B": 0, "C": 0}
    for s in snapshots:
        if s.tier in counts:
            counts[s.tier] += 1

    state = load_state(sync_root)
    promotions, demotions, new_strats = compute_deltas(snapshots, state)
    anomalies = detect_anomalies(snapshots, state)

    near_threshold = [asdict(s) for s in snapshots if "near_threshold" in s.flags]
    disagreements = [{"hypothesis_id": s.hypothesis_id, "funnel_tier": s.tier, "gate_v2": "see verdict"}
                     for s in snapshots if "gate_v2_disagreement" in s.flags]

    weekly = WeeklySnapshot(
        week_id=week_id,
        snapshot_at=now.isoformat(),
        counts_by_tier=counts,
        strategies=[asdict(s) for s in snapshots],
        promotions=promotions,
        demotions=demotions,
        new_strategies=new_strats,
        near_threshold=near_threshold,
        anomalies=anomalies,
        disagreements=disagreements,
    )

    # Write outputs
    tracker_dir = sync_root / DIRS["tracker"]
    tracker_dir.mkdir(parents=True, exist_ok=True)

    week_html = tracker_dir / f"week_{week_id}.html"
    week_json = tracker_dir / f"week_{week_id}.json"
    latest_html = tracker_dir / "latest.html"
    history_jsonl = tracker_dir / "history.jsonl"

    week_html.write_text(render_html(weekly), encoding="utf-8")
    week_json.write_text(json.dumps(asdict(weekly), indent=2, default=str), encoding="utf-8")
    latest_html.write_text(render_html(weekly), encoding="utf-8")  # copy, not symlink (Windows-friendly)

    summary_row = {
        "week_id": week_id, "snapshot_at": weekly.snapshot_at,
        "counts": counts,
        "n_promotions": len(promotions), "n_demotions": len(demotions),
        "n_new": len(new_strats), "n_anomalies": len(anomalies),
        "n_disagreements": len(disagreements),
    }
    with history_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary_row) + "\n")

    # Update state
    save_state(sync_root, {
        "last_week_id": week_id,
        "last_snapshot": asdict(weekly),
    })

    logger.info(f"Tracker run complete: Tier A={counts['A']}, B={counts['B']}, C={counts['C']}")
    logger.info(f"  +{len(promotions)} promotions, -{len(demotions)} demotions, {len(new_strats)} new")
    logger.info(f"  Wrote {week_html.name} and {week_json.name}")

    return weekly


def main():
    parser = argparse.ArgumentParser(description="Weekly tracker for the Jarvis Robust Strategy Funnel")
    parser.add_argument("--sync-root", type=Path, required=True, help="OneDrive handoff folder root")
    parser.add_argument("--notify", action="store_true", help="(Hook) Trigger notification after run")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    weekly = run_tracker(args.sync_root, notify=args.notify)

    if args.notify:
        # Print a JSON summary to stdout — wrapped by the scheduled task or
        # Computer cron to deliver as an in-app notification.
        print(json.dumps({
            "title": f"Jarvis Funnel — Week {weekly.week_id}",
            "tier_a": weekly.counts_by_tier.get("A", 0),
            "tier_b": weekly.counts_by_tier.get("B", 0),
            "tier_c": weekly.counts_by_tier.get("C", 0),
            "promotions": len(weekly.promotions),
            "demotions": len(weekly.demotions),
            "new": len(weekly.new_strategies),
            "anomalies": len(weekly.anomalies),
        }))


if __name__ == "__main__":
    main()
