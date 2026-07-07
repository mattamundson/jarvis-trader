"""
Strategy Development Roadmap Generator — P3-40.

Produces a Kanban-style Markdown dashboard (engine/data/_ROADMAP.md) by:
  1. Parsing the REMAINING_WORK_REPORT for all P3-* task definitions.
  2. Scanning git log for commit messages referencing those task IDs to mark DONE.
  3. Categorizing remaining tasks by class (AGENT-DOABLE vs AMO-ONLY vs AMO-AUTHORIZE).

Output columns:
  DONE     — tasks with a git commit referencing the task ID
  AGENT    — open 🤖 AGENT-DOABLE tasks, sorted by estimate
  AMO      — open 👤 AMO-ONLY and ⚠️ AMO-AUTHORIZE-FIRST tasks
  BLOCKED  — tasks marked as BLOCKED in the agent queue (if readable)

Usage (from engine/ directory):
    .venv/Scripts/python backtest/gen_roadmap.py
    .venv/Scripts/python backtest/gen_roadmap.py --watch   (refresh every 5 min)

Output: engine/data/_ROADMAP.md (overwritten on every run)
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ENGINE_ROOT = Path(__file__).resolve().parent.parent
# Git repo root: try engine/ first (has .git/), fall back to jarvis-trader/
_REPO_ROOT = _ENGINE_ROOT if (_ENGINE_ROOT / ".git").exists() else _ENGINE_ROOT.parent
_REMAINING_WORK = Path.home() / ".claude" / "handoffs" / "REMAINING_WORK_REPORT_2026-05-07.md"
_OUTPUT = _ENGINE_ROOT / "data" / "_ROADMAP.md"

# Estimate weights (minutes) for sorting — shorter = more urgent
_ESTIMATE_WEIGHTS = {
    "5 min": 5,
    "10 min": 10,
    "15 min": 15,
    "20 min": 20,
    "30 min": 30,
    "1 hr": 60,
    "1-2 hr": 90,
    "2-3 hr": 150,
    "3-4 hr": 210,
    "4-6 hr": 300,
    "trivial": 5,
    "passive": 9999,
    "decision": 30,
    "months": 99999,
}


# ---------------------------------------------------------------------------
# Parse task table from REMAINING_WORK_REPORT
# ---------------------------------------------------------------------------


def _parse_tasks(report_path: Path) -> list[dict]:
    """Extract task rows from the | ID | Task | Class | … | Estimate | table."""
    if not report_path.exists():
        return []

    text = report_path.read_text(encoding="utf-8", errors="replace")
    tasks = []

    # Match any markdown table row that starts with | P<n>-<n>
    row_re = re.compile(
        r"^\|\s*(P\d+-\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|.*?\|\s*(.+?)\s*\|",
        re.MULTILINE,
    )
    for m in row_re.finditer(text):
        task_id = m.group(1)
        description = m.group(2).strip()
        task_class = m.group(3).strip()
        estimate_raw = m.group(4).strip()
        tasks.append(
            {
                "id": task_id,
                "description": description,
                "class": task_class,
                "estimate": estimate_raw,
                "weight": _estimate_to_weight(estimate_raw),
            }
        )
    return tasks


def _estimate_to_weight(est: str) -> int:
    for key, w in _ESTIMATE_WEIGHTS.items():
        if key in est:
            return w
    return 60  # default 1hr


# ---------------------------------------------------------------------------
# Detect completed tasks via git log + supplemental overrides file
# ---------------------------------------------------------------------------

# Supplemental done-overrides: engine/data/_ROADMAP_DONE.txt
# Format: one task ID per line; lines starting with # are comments.
# Used for tasks verified via file inspection (not git commit message).
_DONE_OVERRIDES = _ENGINE_ROOT / "data" / "_ROADMAP_DONE.txt"


def _get_done_ids(repo_root: Path, task_ids: list[str]) -> set[str]:
    """Scan git log messages and supplemental override file for Done task IDs."""
    if not task_ids:
        return set()

    # 1. Git log scan
    done: set[str] = set()
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-500"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        log = result.stdout
        for task_id in task_ids:
            if re.search(rf"\b{re.escape(task_id)}\b", log):
                done.add(task_id)
    except Exception:
        pass

    # 2. Supplemental overrides (file-verified tasks)
    if _DONE_OVERRIDES.exists():
        for line in _DONE_OVERRIDES.read_text(encoding="utf-8").splitlines():
            # Strip inline comments before matching
            content = line.split("#")[0].strip()
            if content and re.match(r"^P\d+-\d+$", content):
                done.add(content)

    return done


# ---------------------------------------------------------------------------
# Generate Markdown
# ---------------------------------------------------------------------------


def _class_badge(cls: str) -> str:
    if "🤖" in cls or "AGENT" in cls.upper():
        return "🤖"
    if "👤" in cls or "AMO-ONLY" in cls.upper():
        return "👤"
    if "⚠️" in cls or "AMO-AUTHORIZE" in cls.upper():
        return "⚠️"
    return "?"


def generate(report_path: Path, repo_root: Path) -> str:
    tasks = _parse_tasks(report_path)
    if not tasks:
        return f"No tasks parsed from {report_path}\n"

    all_ids = [t["id"] for t in tasks]
    done_ids = _get_done_ids(repo_root, all_ids)

    done = [t for t in tasks if t["id"] in done_ids]
    open_tasks = [t for t in tasks if t["id"] not in done_ids]

    agent_tasks = [t for t in open_tasks if "🤖" in t["class"] or "AGENT" in t["class"].upper()]
    amo_tasks = [t for t in open_tasks if t not in agent_tasks]

    agent_tasks.sort(key=lambda t: t["weight"])

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    source_name = report_path.name

    lines = [
        "# JARVIS TRADER — Strategy Development Roadmap",
        "",
        f"> Auto-generated by `backtest/gen_roadmap.py` · {now}",
        f"> Source: `~/.claude/handoffs/{source_name}`",
        ">",
        "> Columns: **DONE** (git-verified) | **AGENT** (autonomous) | **AMO** (needs Amo) ",
        "",
    ]

    # DONE
    lines += ["## ✅ Done", ""]
    if done:
        for t in sorted(done, key=lambda x: x["id"]):
            lines.append(f"- **{t['id']}** — {t['description']}")
    else:
        lines.append("- *(none detected in git log)*")
    lines.append("")

    # AGENT-DOABLE open tasks
    lines += [
        "## 🤖 Agent-Doable (open, sorted by estimate)",
        "",
        "| ID | Task | Estimate |",
        "|----|------|---------|",
    ]
    if agent_tasks:
        for t in agent_tasks:
            lines.append(f"| {t['id']} | {t['description']} | {t['estimate']} |")
    else:
        lines.append("| — | All agent tasks complete! | — |")
    lines.append("")

    # AMO-ONLY open tasks
    lines += [
        "## 👤 / ⚠️ Amo-Gated (open)",
        "",
        "| ID | Class | Task | Estimate |",
        "|----|-------|------|---------|",
    ]
    if amo_tasks:
        for t in sorted(amo_tasks, key=lambda x: x["id"]):
            badge = _class_badge(t["class"])
            lines.append(f"| {t['id']} | {badge} | {t['description']} | {t['estimate']} |")
    else:
        lines.append("| — | — | All Amo tasks done or gated — nothing pending | — |")
    lines.append("")

    # Summary
    total = len(tasks)
    n_done = len(done)
    n_open = len(open_tasks)
    lines += [
        "## Summary",
        "",
        "| Stat | Count |",
        "|------|-------|",
        f"| Total tasks | {total} |",
        f"| Done (git-verified) | {n_done} |",
        f"| Open agent-doable | {len(agent_tasks)} |",
        f"| Open Amo-gated | {len(amo_tasks)} |",
        f"| Remaining | {n_open} |",
        "",
        "Run `backtest/gen_scoreboard.py` to refresh the strategy verdict table.",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    watch = "--watch" in sys.argv

    def _run_once() -> None:
        content = generate(_REMAINING_WORK, _REPO_ROOT)
        _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        _OUTPUT.write_text(content, encoding="utf-8")
        print(f"[roadmap] Written -> {_OUTPUT}  ({content.count(chr(10))} lines)")

    if watch:
        print("[roadmap] Watch mode — refreshing every 300s. Ctrl-C to stop.")
        while True:
            try:
                _run_once()
                time.sleep(300)
            except KeyboardInterrupt:
                print("\n[roadmap] Stopped.")
                break
    else:
        _run_once()
        # Print abbreviated summary (ASCII-safe for Windows console)
        lines = [
            ln
            for ln in _OUTPUT.read_text(encoding="utf-8").splitlines()
            if ln.startswith("| ") or ln.startswith("## ")
        ]
        for line in lines[:30]:
            print(line.encode("ascii", errors="replace").decode("ascii"))


if __name__ == "__main__":
    if str(_ENGINE_ROOT) not in sys.path:
        sys.path.insert(0, str(_ENGINE_ROOT))
    main()
