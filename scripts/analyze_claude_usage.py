#!/usr/bin/env python3
"""
Claude Code Usage Self-Audit — Tier 0-2 deterministic backbone ("The Coach").

Walks the local Claude Code transcript store (~/.claude/projects/**), extracts
objective per-session signals across six facets (prompting, workflow, tooling,
model/cost, discipline, meta), clusters sessions into behavioral archetypes,
and writes machine- and human-readable summaries plus a stratified sample of
sessions worth a qualitative (LLM) deep-read.

No LLM calls, no third-party dependencies (stdlib only). Read-only against
~/.claude — it never modifies, moves, or deletes a transcript.

Correctness note: subagent/sidechain work lives in separate
`<session>/subagents/agent-*.jsonl` files (never inline — `isSidechain` is
always false in the main file), so those are read and joined via the `Agent`
tool_use `id`. Skipping them undercounts subagent usage.

Usage:
    python3 scripts/analyze_claude_usage.py                 # last 90 days, ./claude-usage-analysis
    python3 scripts/analyze_claude_usage.py --days 30
    python3 scripts/analyze_claude_usage.py --root ~/.claude/projects --out ./out
    python3 scripts/analyze_claude_usage.py --project -home-user-jarvis-trader
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_ROOT = Path(os.path.expanduser("~/.claude/projects"))
DEFAULT_OUT = Path("./claude-usage-analysis")
DEFAULT_DAYS = 90

# --- signal heuristics (heuristics: tune via the Coach feedback ledger) -------

CORRECTION_RE = re.compile(
    r"\b(no,|no\.|nope|that'?s (wrong|not right)|not what i (asked|meant|wanted)|"
    r"stop|undo|revert|roll ?back|don'?t do that|wrong (approach|file|answer|way)|"
    r"actually,|i said|re-?read|you (missed|ignored|broke|forgot)|"
    r"this is (broken|incorrect|wrong))",
    re.IGNORECASE,
)
DONE_CLAIM_RE = re.compile(
    r"\b(verified|works now|it works|done|fixed|shipped|complete[d]?|"
    r"confirmed working|good to go|all set|resolved)\b",
    re.IGNORECASE,
)
VERIFY_CMD_RE = re.compile(
    r"\b(pytest|tsc\s+--noEmit|npm (run )?test|pnpm (run )?(test|build)|"
    r"go test|cargo test|jest|vitest|ruff check|mypy|playwright test|"
    r"curl\s+.*localhost|npm run build)\b",
    re.IGNORECASE,
)
DESTRUCTIVE_RE = re.compile(
    r"\b(git push\s+.*--force|--force-with-lease|git reset --hard|rm\s+-rf|"
    r"git clean\s+-[a-z]*f|git branch\s+-D|DROP TABLE|--no-verify|--no-gpg-sign)\b",
    re.IGNORECASE,
)
IMPERATIVE_RE = re.compile(
    r"^\s*(add|fix|build|make|create|write|refactor|remove|delete|update|"
    r"implement|change|run|check|test|deploy|install|set|move|rename|split)\b",
    re.IGNORECASE,
)
CONSTRAINT_RE = re.compile(
    r"\b(must|only|don'?t|do not|never|always|before|after|ensure|require[ds]?|"
    r"should not|make sure)\b",
    re.IGNORECASE,
)
ACCEPTANCE_RE = re.compile(
    r"\b(so that|acceptance|expected( output| result)?|it should|verify that|"
    r"test that|the goal is|success (is|means)|passes when|until)\b",
    re.IGNORECASE,
)

# --- token pricing: ESTIMATE ONLY, per-million USD. Override with --pricing. --
# These are assumed rates for cost *estimation* and may be stale; token *counts*
# are exact (from the transcript). Do not present derived $ as authoritative.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-fable-5": {"in": 10.0, "out": 50.0, "cache_read": 1.0},
    "claude-opus-4-8": {"in": 15.0, "out": 75.0, "cache_read": 1.5},
    "claude-opus-4-6": {"in": 15.0, "out": 75.0, "cache_read": 1.5},
    "claude-sonnet-5": {"in": 3.0, "out": 15.0, "cache_read": 0.30},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0, "cache_read": 0.30},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0, "cache_read": 0.10},
}

# Claude Code capabilities tracked for the feature-adoption scorecard (Tier 4
# consumes this; Tier 1 emits raw usage booleans/counts it can key off).
TRACKED_FEATURES = [
    "plan_mode", "subagents", "parallel_fanout", "workflow_orchestrator",
    "background_tasks", "todo_tasks", "mcp_tools", "extended_thinking",
    "model_routing", "skills", "custom_commands", "verification_before_done",
]


# ===========================================================================
# I/O — read-only
# ===========================================================================

def iter_session_files(root: Path, project: str | None) -> list[Path]:
    """Return main-session .jsonl files (excludes subagents/ sidechain files)."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) == "subagents":
            dirnames[:] = []  # don't descend; joined explicitly per session
            continue
        if project and Path(dirpath).name != project and Path(root) != Path(dirpath):
            # allow project filter on the immediate project dir name
            if Path(dirpath).name != project:
                pass
        for fn in filenames:
            if fn.endswith(".jsonl") and not fn.endswith(".meta.json"):
                p = Path(dirpath) / fn
                if project and p.parent.name != project:
                    continue
                files.append(p)
    return files


def load_records(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL transcript, skipping malformed lines (never crashes)."""
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for lineno, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    logger.debug("%s:%d JSON parse error — %s", path.name, lineno, exc)
    except OSError as exc:
        logger.warning("Could not read %s — %s", path, exc)
    return records


def load_subagents(session_file: Path) -> list[dict[str, Any]]:
    """Load every subagents/agent-*.jsonl for a session, with its meta sidecar.

    Returns a list of {meta, records} — one per spawned subagent. The subagents/
    directory sits next to the main file, named `<session-stem>/subagents/`.
    """
    stem = session_file.stem
    sub_dir = session_file.parent / stem / "subagents"
    if not sub_dir.is_dir():
        sub_dir = session_file.parent / "subagents"  # fallback layout
        if not sub_dir.is_dir():
            return []
    out: list[dict[str, Any]] = []
    for jf in sorted(sub_dir.glob("agent-*.jsonl")):
        meta_path = jf.with_suffix(".meta.json")
        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                meta = {}
        out.append({"meta": meta, "records": load_records(jf)})
    return out


# ===========================================================================
# Parsing helpers
# ===========================================================================

def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def user_text(content: Any) -> str:
    """Return human-authored text for a user record (empty for tool_result turns)."""
    if isinstance(content, str):
        return content
    return ""  # list content on user records is tool_result blocks, not prose


def assistant_text(content: Any) -> str:
    if not isinstance(content, list):
        return str(content or "")
    return "\n".join(
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    )


def iter_tool_uses(content: Any):
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield b


def is_human_prompt(rec: dict[str, Any]) -> bool:
    """A genuine human turn: user record, string content, not a meta/injected one."""
    if rec.get("type") != "user" or rec.get("isMeta"):
        return False
    content = rec.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        return False
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    return True


# ===========================================================================
# Tier 1 — per-facet signal extraction
# ===========================================================================

def _new_stats(path: Path, project: str) -> dict[str, Any]:
    return {
        "file": str(path), "project": project, "session_id": None,
        "start": None, "end": None, "duration_min": 0.0,
        "cli_versions": set(), "git_branches": set(),
        # prompting
        "n_human_turns": 0, "human_turn_chars": [], "imperative_turns": 0,
        "constraint_turns": 0, "acceptance_turns": 0, "file_ref_turns": 0,
        "correction_turns": 0, "clarifying_questions": 0, "queue_ops": 0,
        # workflow
        "plan_mode": False, "subagent_count": 0, "subagent_types": Counter(),
        "max_spawn_depth": 0, "parallel_fanout_turns": 0, "workflow_calls": 0,
        "background_tasks": 0, "todo_max_items": 0, "rewind_branches": 0,
        "user_modified_edits": 0,
        # tooling
        "tool_calls": Counter(), "mcp_calls": Counter(), "skills": Counter(),
        "verify_cmds": 0, "destructive_cmds": 0, "interrupted_tools": 0,
        # model / cost
        "models": Counter(), "model_switches": 0,
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_creation_tokens": 0,
        "web_search": 0, "web_fetch": 0, "cache_miss_events": 0,
        "thinking_blocks": 0, "est_cost_usd": 0.0,
        # discipline
        "done_claims": 0, "unverified_done_claims": 0, "hook_runs": 0,
        "n_assistant_turns": 0,
    }


def _apply_prompt_signals(stats: dict[str, Any], text: str) -> None:
    stats["n_human_turns"] += 1
    stats["human_turn_chars"].append(len(text))
    if IMPERATIVE_RE.search(text):
        stats["imperative_turns"] += 1
    if CONSTRAINT_RE.search(text):
        stats["constraint_turns"] += 1
    if ACCEPTANCE_RE.search(text):
        stats["acceptance_turns"] += 1
    if "@" in text or re.search(r"[\w/]+\.(py|ts|tsx|js|md|json|ps1)\b", text):
        stats["file_ref_turns"] += 1
    if CORRECTION_RE.search(text):
        stats["correction_turns"] += 1


def _apply_tool_use(stats: dict[str, Any], block: dict[str, Any]) -> None:
    name = block.get("name", "unknown")
    stats["tool_calls"][name] += 1
    inp = block.get("input", {}) or {}
    if name.startswith("mcp__"):
        stats["mcp_calls"][name] += 1
    if name == "Skill":
        sk = inp.get("skill") or inp.get("name")
        if sk:
            stats["skills"][sk] += 1
    elif name == "Agent":
        stats["subagent_types"][inp.get("subagent_type", "unspecified")] += 1
        if inp.get("run_in_background"):
            stats["background_tasks"] += 1
    elif name == "Workflow":
        stats["workflow_calls"] += 1
    elif name in ("TaskCreate", "TaskUpdate"):
        pass  # todo usage tracked via task_reminder attachments
    elif name == "Bash":
        cmd = inp.get("command", "") or ""
        if inp.get("run_in_background"):
            stats["background_tasks"] += 1
        if VERIFY_CMD_RE.search(cmd):
            stats["verify_cmds"] += 1
        if DESTRUCTIVE_RE.search(cmd):
            stats["destructive_cmds"] += 1


def _apply_usage(stats: dict[str, Any], usage: dict[str, Any], pricing: dict) -> None:
    it = usage.get("input_tokens", 0) or 0
    ot = usage.get("output_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    cc = usage.get("cache_creation_input_tokens", 0) or 0
    stats["input_tokens"] += it
    stats["output_tokens"] += ot
    stats["cache_read_tokens"] += cr
    stats["cache_creation_tokens"] += cc
    stu = usage.get("server_tool_use") or {}
    stats["web_search"] += stu.get("web_search_requests", 0) or 0
    stats["web_fetch"] += stu.get("web_fetch_requests", 0) or 0


def _est_cost(stats: dict[str, Any], pricing: dict) -> float:
    """Rough $ estimate using the dominant model's rate (counts are exact)."""
    model = (stats["models"].most_common(1) or [("", 0)])[0][0]
    rate = pricing.get(model)
    if not rate:
        return 0.0
    m = 1_000_000
    return round(
        stats["input_tokens"] / m * rate["in"]
        + stats["output_tokens"] / m * rate["out"]
        + stats["cache_read_tokens"] / m * rate["cache_read"],
        4,
    )


def _detect_attachment(stats: dict[str, Any], rec: dict[str, Any]) -> None:
    att = rec.get("attachment")
    if not isinstance(att, dict):
        return
    atype = att.get("type") or att.get("reminderType") or ""
    if "plan_mode" in str(atype) or "planFilePath" in att or att.get("planExists"):
        stats["plan_mode"] = True
    if "task_reminder" in str(atype) or "itemCount" in att:
        stats["todo_max_items"] = max(stats["todo_max_items"], att.get("itemCount", 0) or 0)


def analyze_session(path: Path, project: str, records: list[dict[str, Any]],
                    subagents: list[dict[str, Any]], pricing: dict,
                    cutoff: datetime) -> dict[str, Any] | None:
    """Extract the full per-session signal catalog. Returns None if out of window."""
    ts_all = [t for r in records if (t := parse_ts(r.get("timestamp")))]
    if not ts_all:
        return None
    start, end = min(ts_all), max(ts_all)
    if end < cutoff:
        return None

    stats = _new_stats(path, project)
    stats["start"], stats["end"] = start.isoformat(), end.isoformat()
    stats["duration_min"] = round((end - start).total_seconds() / 60, 1)

    parent_children: Counter[str] = Counter()
    last_model: str | None = None

    for rec in records:
        rtype = rec.get("type")
        stats["session_id"] = rec.get("sessionId", stats["session_id"])
        if rec.get("version"):
            stats["cli_versions"].add(rec["version"])
        if rec.get("gitBranch"):
            stats["git_branches"].add(rec["gitBranch"])
        if rec.get("parentUuid"):
            parent_children[rec["parentUuid"]] += 1

        if rtype == "queue-operation":
            if rec.get("operation") == "enqueue":
                stats["queue_ops"] += 1
        elif rtype == "attachment":
            _detect_attachment(stats, rec)
        elif rtype == "system" and rec.get("subtype") == "stop_hook_summary":
            stats["hook_runs"] += rec.get("hookCount", 0) or 0
        elif rtype == "user":
            _process_user(stats, rec)
        elif rtype == "assistant":
            last_model = _process_assistant(stats, rec, pricing, last_model)

    # rewind/edit detection: a parent with >1 child = a branched/re-run turn
    stats["rewind_branches"] = sum(1 for c in parent_children.values() if c > 1)
    stats["parallel_fanout_turns"] = _detect_parallel_fanout(records)
    _process_subagents(stats, subagents)
    _score_discipline(stats, records)
    stats["est_cost_usd"] = _est_cost(stats, pricing)
    stats["archetype"] = classify_archetype(stats)
    # finalize sets -> sorted lists for JSON
    stats["cli_versions"] = sorted(stats["cli_versions"])
    stats["git_branches"] = sorted(stats["git_branches"])
    return stats


def _process_user(stats: dict[str, Any], rec: dict[str, Any]) -> None:
    content = rec.get("message", {}).get("content")
    if is_human_prompt(rec):
        _apply_prompt_signals(stats, content)
    # tool_result error / interruption signals
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                stats["interrupted_tools"] += 0  # errors counted below via toolUseResult
    tur = rec.get("toolUseResult")
    if isinstance(tur, dict):
        if tur.get("interrupted"):
            stats["interrupted_tools"] += 1
        if tur.get("userModified"):
            stats["user_modified_edits"] += 1


def _process_assistant(stats: dict[str, Any], rec: dict[str, Any],
                       pricing: dict, last_model: str | None) -> str | None:
    stats["n_assistant_turns"] += 1
    msg = rec.get("message", {})
    model = msg.get("model")
    if model and model.startswith("claude"):  # ignore <synthetic>/injected turns
        stats["models"][model] += 1
        if last_model and model != last_model:
            stats["model_switches"] += 1
        last_model = model
    _apply_usage(stats, msg.get("usage", {}) or {}, pricing)
    diag = msg.get("diagnostics")
    if isinstance(diag, dict) and diag.get("cache_miss_reason"):
        stats["cache_miss_events"] += 1
    content = msg.get("content")
    if isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "thinking":
                stats["thinking_blocks"] += 1
            elif b.get("type") == "tool_use":
                _apply_tool_use(stats, b)
                if b.get("name") == "AskUserQuestion":
                    stats["clarifying_questions"] += 1
    return last_model


def _detect_parallel_fanout(records: list[dict[str, Any]]) -> int:
    """Count parallel fan-out batches: runs of >=2 `Agent` invocations separated
    only by their own tool-result acks (no human turn, thinking/text, or other
    tool between them). The CLI emits each parallel Agent call as its own
    assistant record, so a single-record block-count misses real fan-out."""
    batches = run = 0
    counted = False
    for rec in records:
        if is_human_prompt(rec):
            run, counted = 0, False
            continue
        if rec.get("type") != "assistant":
            continue  # tool_result / attachment / system are transparent
        content = rec.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        agent_blocks = sum(
            1 for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Agent")
        resets = any(
            isinstance(b, dict) and (
                b.get("type") in ("thinking", "text")
                or (b.get("type") == "tool_use" and b.get("name") != "Agent"))
            for b in content)
        if resets:
            run, counted = 0, False
        if agent_blocks:
            run += agent_blocks
            if run >= 2 and not counted:
                batches += 1
                counted = True
    return batches


def _process_subagents(stats: dict[str, Any], subagents: list[dict[str, Any]]) -> None:
    # Note: subagent *type* counts come from the main-file `Agent` tool_use
    # (direct invocations) in _apply_tool_use — NOT re-counted here, or each
    # subagent would be double-counted (once per tool_use, once per file).
    for sa in subagents:
        stats["subagent_count"] += 1
        meta = sa.get("meta", {})
        stats["max_spawn_depth"] = max(stats["max_spawn_depth"], meta.get("spawnDepth", 0) or 0)
        # fold subagent tool calls + tokens into the session totals
        for rec in sa.get("records", []):
            if rec.get("type") != "assistant":
                continue
            for b in iter_tool_uses(rec.get("message", {}).get("content")):
                stats["tool_calls"][f"[sub]{b.get('name', '?')}"] += 1


def _score_discipline(stats: dict[str, Any], records: list[dict[str, Any]]) -> None:
    """'Compiling != behaving': per task (human-prompt span), a done-claim with
    no preceding verification command in that same task is a violation."""
    task_has_verify = False
    task_has_claim_unverified = False

    def close_task() -> None:
        nonlocal task_has_verify, task_has_claim_unverified
        if task_has_claim_unverified:
            stats["unverified_done_claims"] += 1
        task_has_verify = False
        task_has_claim_unverified = False

    for rec in records:
        if is_human_prompt(rec):
            close_task()
            continue
        if rec.get("type") == "assistant":
            content = rec.get("message", {}).get("content")
            for b in iter_tool_uses(content):
                if b.get("name") == "Bash":
                    if VERIFY_CMD_RE.search((b.get("input", {}) or {}).get("command", "") or ""):
                        task_has_verify = True
            txt = assistant_text(content)
            if DONE_CLAIM_RE.search(txt):
                stats["done_claims"] += 1
                if not task_has_verify:
                    task_has_claim_unverified = True
    close_task()


# ===========================================================================
# Tier 2 — archetype clustering
# ===========================================================================

def classify_archetype(s: dict[str, Any]) -> str:
    edits = s["tool_calls"].get("Edit", 0) + s["tool_calls"].get("Write", 0)
    reads = s["tool_calls"].get("Read", 0) + s["tool_calls"].get("Grep", 0) + s["tool_calls"].get("Glob", 0)
    if s["subagent_count"] >= 2 or s["workflow_calls"] > 0 or s["parallel_fanout_turns"] > 0:
        return "Orchestrator"
    if s["n_human_turns"] <= 1 and s["n_assistant_turns"] >= 1:
        return "One-shotter"
    if edits == 0 and reads > 0:
        return "Explorer"
    if s["duration_min"] < 15 and s["interrupted_tools"] + s["destructive_cmds"] > 0:
        return "Firefighter"
    if edits > 0 and s["verify_cmds"] > 0:
        return "Builder"
    return "Mixed"


# ===========================================================================
# Aggregation, sampling, rendering  (Tier 0 inventory + report)
# ===========================================================================

def _pct(numer: int, denom: int) -> float:
    return round(100 * numer / denom, 1) if denom else 0.0


def aggregate(sessions: list[dict[str, Any]], days: int) -> dict[str, Any]:
    n = len(sessions)
    tools, skills, agents, archetypes = Counter(), Counter(), Counter(), Counter()
    models, projects, weeks = Counter(), Counter(), Counter()
    hturns = corr = verify_sessions = plan_sessions = wf_sessions = 0
    skill_sessions = agent_sessions = unverified = done = 0
    tot_in = tot_out = tot_cache = 0
    est_cost = 0.0
    all_prompt_chars: list[int] = []

    for s in sessions:
        tools.update(s["tool_calls"])
        skills.update(s["skills"])
        agents.update(s["subagent_types"])
        archetypes[s["archetype"]] += 1
        models.update(s["models"])
        projects[s["project"]] += 1
        wk = datetime.fromisoformat(s["start"]).strftime("%G-W%V")
        weeks[wk] += 1
        hturns += s["n_human_turns"]
        corr += s["correction_turns"]
        all_prompt_chars.extend(s["human_turn_chars"])
        done += s["done_claims"]
        unverified += s["unverified_done_claims"]
        tot_in += s["input_tokens"]
        tot_out += s["output_tokens"]
        tot_cache += s["cache_read_tokens"]
        est_cost += s["est_cost_usd"]
        verify_sessions += 1 if s["verify_cmds"] > 0 else 0
        plan_sessions += 1 if s["plan_mode"] else 0
        wf_sessions += 1 if s["workflow_calls"] > 0 else 0
        skill_sessions += 1 if s["skills"] else 0
        agent_sessions += 1 if (s["subagent_count"] > 0 or s["tool_calls"].get("Agent", 0) > 0) else 0

    dates = sorted(s["start"] for s in sessions)
    avg_prompt = round(sum(all_prompt_chars) / len(all_prompt_chars), 1) if all_prompt_chars else 0.0
    return {
        "window_days": days, "sessions": n,
        "date_range": {"first": dates[0], "last": dates[-1]} if dates else {},
        "by_project": dict(projects.most_common()),
        "by_week": dict(sorted(weeks.items())),
        "by_archetype": dict(archetypes.most_common()),
        "tool_histogram": dict(tools.most_common()),
        "skill_histogram": dict(skills.most_common()),
        "agent_histogram": dict(agents.most_common()),
        "model_histogram": dict(models.most_common()),
        "avg_prompt_chars": avg_prompt,
        "correction_rate_pct": _pct(corr, hturns),
        "unverified_done_claim_rate_pct": _pct(unverified, done),
        "sessions_with_verification_pct": _pct(verify_sessions, n),
        "sessions_with_plan_mode_pct": _pct(plan_sessions, n),
        "sessions_with_workflow_pct": _pct(wf_sessions, n),
        "sessions_with_skills_pct": _pct(skill_sessions, n),
        "sessions_with_subagents_pct": _pct(agent_sessions, n),
        "total_input_tokens": tot_in, "total_output_tokens": tot_out,
        "total_cache_read_tokens": tot_cache,
        "estimated_cost_usd": round(est_cost, 2),
        "total_done_claims": done, "total_unverified_done_claims": unverified,
    }


def pick_samples(sessions: list[dict[str, Any]], max_samples: int = 30) -> list[dict[str, Any]]:
    picks: dict[str, dict[str, Any]] = {}

    def add(s: dict[str, Any], reason: str) -> None:
        rec = picks.setdefault(s["file"], {
            "file": s["file"], "project": s["project"], "session_id": s["session_id"],
            "start": s["start"], "archetype": s["archetype"], "reasons": [],
        })
        if reason not in rec["reasons"]:
            rec["reasons"].append(reason)

    for s in sorted(sessions, key=lambda x: x["duration_min"], reverse=True)[:6]:
        add(s, "longest")
    for s in sorted(sessions, key=lambda x: x["correction_turns"] / max(x["n_human_turns"], 1),
                    reverse=True)[:6]:
        if s["n_human_turns"] >= 3 and s["correction_turns"] > 0:
            add(s, "high-correction-rate")
    for s in sorted(sessions, key=lambda x: x["unverified_done_claims"], reverse=True)[:6]:
        if s["unverified_done_claims"] > 0:
            add(s, "unverified-done-claim")
    for s in sorted(sessions, key=lambda x: x["interrupted_tools"], reverse=True)[:4]:
        if s["interrupted_tools"] > 0:
            add(s, "most-interruptions")
    for s in [x for x in sessions if x["destructive_cmds"] > 0][:4]:
        add(s, "destructive-command")
    seen_arch: set[str] = set()
    for s in sessions:
        if s["archetype"] not in seen_arch:
            seen_arch.add(s["archetype"])
            add(s, f"archetype:{s['archetype']}")
    seen_wk: set = set()
    for s in sorted(sessions, key=lambda x: x["start"]):
        wk = datetime.fromisoformat(s["start"]).isocalendar()[:2]
        if wk not in seen_wk and len(picks) < max_samples:
            seen_wk.add(wk)
            add(s, "weekly-coverage")
    return list(picks.values())[:max_samples]


def _json_ready(s: dict[str, Any]) -> dict[str, Any]:
    out = dict(s)
    for k, v in list(out.items()):
        if isinstance(v, Counter):
            out[k] = dict(v.most_common())
    return out


def render_summary_md(agg: dict[str, Any], samples: list[dict[str, Any]],
                      pricing_note: str) -> str:
    dr = agg.get("date_range", {})
    lines = [
        "# Claude Code usage — Tier 1 quantitative report",
        "",
        f"Window: last {agg['window_days']} days "
        f"({dr.get('first', '?')[:10]} to {dr.get('last', '?')[:10]})",
        f"Sessions analyzed: {agg['sessions']}",
        "",
        "## Archetype mix",
        *[f"- {a}: {c}" for a, c in agg["by_archetype"].items()],
        "",
        "## Weekly volume",
        *[f"- {wk}: {c}" for wk, c in agg["by_week"].items()],
        "",
        "## Tool usage (top 25; `[sub]` = inside a subagent)",
        *[f"- {t}: {c}" for t, c in list(agg["tool_histogram"].items())[:25]],
        "",
        "## Model routing",
        *([f"- {m}: {c} assistant turns" for m, c in agg["model_histogram"].items()] or ["- (none)"]),
        "",
        "## Skills invoked",
        *([f"- {s}: {c}" for s, c in agg["skill_histogram"].items()] or ["- (none invoked in window)"]),
        "",
        "## Subagents invoked",
        *([f"- {a}: {c}" for a, c in agg["agent_histogram"].items()] or ["- (none invoked in window)"]),
        "",
        "## Habits",
        f"- Avg human prompt length: {agg['avg_prompt_chars']:.0f} chars",
        f"- Correction-turn rate: {agg['correction_rate_pct']}%",
        f"- **Unverified 'done' claim rate: {agg['unverified_done_claim_rate_pct']}%** "
        f"({agg['total_unverified_done_claims']}/{agg['total_done_claims']} done-claims had no "
        f"preceding test/build in the same task) — the CLAUDE.md PR#280 signal",
        f"- Sessions running a verification command: {agg['sessions_with_verification_pct']}%",
        f"- Sessions using plan mode: {agg['sessions_with_plan_mode_pct']}%",
        f"- Sessions using the Workflow orchestrator: {agg['sessions_with_workflow_pct']}%",
        f"- Sessions invoking a Skill: {agg['sessions_with_skills_pct']}%",
        f"- Sessions invoking a subagent: {agg['sessions_with_subagents_pct']}%",
        "",
        "## Cost (ESTIMATE — token counts exact, $ rates assumed)",
        f"- Input tokens: {agg['total_input_tokens']:,}",
        f"- Output tokens: {agg['total_output_tokens']:,}",
        f"- Cache-read tokens: {agg['total_cache_read_tokens']:,}",
        f"- Estimated spend: ~${agg['estimated_cost_usd']:,.2f}  ({pricing_note})",
        "",
        f"## Sampled sessions for Tier-3 deep-read ({len(samples)})",
        *[f"- {Path(s['file']).name}  [{s['archetype']}]  — {', '.join(s['reasons'])}"
          for s in samples],
        "",
        "## Files written",
        "- summary.json / summary.md — this report",
        "- sessions_raw.json — per-session full signal catalog",
        "- sample_sessions.json — sessions picked for the qualitative pass",
    ]
    return "\n".join(lines)


# ===========================================================================
# CLI
# ===========================================================================

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Claude Code usage self-audit (Tier 0-2).")
    p.add_argument("--root", default=str(DEFAULT_ROOT), help="~/.claude/projects root")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="output directory")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help="lookback window")
    p.add_argument("--project", default=None, help="restrict to one project dir name")
    p.add_argument("--pricing", default=None, help="path to a JSON pricing override")
    p.add_argument("--max-samples", type=int, default=30)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).expanduser()
    out_dir = Path(args.out).expanduser()
    if not root.exists():
        logger.error("Root %s does not exist. Run on the machine with your Claude Code CLI history.", root)
        return 1

    pricing = dict(DEFAULT_PRICING)
    pricing_note = "default assumed rates"
    if args.pricing:
        try:
            pricing.update(json.loads(Path(args.pricing).read_text()))
            pricing_note = f"rates from {args.pricing}"
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load --pricing %s (%s); using defaults.", args.pricing, exc)

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    sessions: list[dict[str, Any]] = []
    for path in iter_session_files(root, args.project):
        project = path.parent.name
        records = load_records(path)
        subs = load_subagents(path)
        stats = analyze_session(path, project, records, subs, pricing, cutoff)
        if stats:
            sessions.append(stats)

    if not sessions:
        logger.info("No sessions in the last %d days under %s.", args.days, root)
        return 0

    agg = aggregate(sessions, args.days)
    samples = pick_samples(sessions, args.max_samples)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(agg, indent=2))
    (out_dir / "sessions_raw.json").write_text(
        json.dumps([_json_ready(s) for s in sessions], indent=2))
    (out_dir / "sample_sessions.json").write_text(json.dumps(samples, indent=2))
    (out_dir / "summary.md").write_text(render_summary_md(agg, samples, pricing_note))

    dr = agg["date_range"]
    logger.info("Analyzed %d sessions (%s..%s) across %d project(s).",
                agg["sessions"], dr.get("first", "?")[:10], dr.get("last", "?")[:10],
                len(agg["by_project"]))
    logger.info("Wrote report to %s/ (summary.md, summary.json, sessions_raw.json, sample_sessions.json)",
                out_dir)
    logger.info("Picked %d sessions for the Tier-3 qualitative pass.", len(samples))
    return 0


if __name__ == "__main__":
    sys.exit(main())
