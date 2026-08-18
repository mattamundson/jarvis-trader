"""Backlog generator. Triages ClassifiedUpgrade into Tiers and renders markdown.

Phase 2 of the Hermes Self-Improvement Loop. Takes the output of
`classifier.classify_batch()` and produces:

  ~/.hermes/upgrade/backlog.md       — human-readable, sectioned by tier
  ~/.hermes/upgrade/backlog.jsonl    — machine-readable sidecar for the applier

The JSONL is the source of truth for apply_status across runs — re-running the
scanner preserves any prior apply outcomes via `merge_with_existing()`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import BacklogEntry, ClassifiedUpgrade, Tier

# Trusted orgs whose Hermes-applicable artifacts (skills, MCPs) don't get the
# community-source risk demotion. Anything OUTSIDE this list that points at a
# github.com URL is treated as untrusted community source and bumped from
# tier_1 -> tier_2 (still applicable, but requires manual review before apply
# because Hermes' built-in security scanner will likely block it on first try).
#
# Empirically discovered via the 2026-05-20 AgentMemory probe — Hermes returned
# "Decision: BLOCKED — community source + caution verdict, 2 findings". The LLM
# classifier rated AgentMemory tier_1 + low risk; Hermes' deterministic scanner
# rated it CAUTION. This list closes the gap between classifier optimism and
# scanner reality.
TRUSTED_SKILL_ORGS = frozenset(
    {
        "nous-research",
        "nousresearch",
        "anthropic",
        "anthropics",
        "openai",
        "mattamundson",  # Amo's own repos
        "amoSZN",  # Amo's prior github identity (deleted but historical references survive)
    }
)

_GITHUB_URL_RE = re.compile(r"github\.com/([^/\s]+)(?:/|$)", re.IGNORECASE)

# Per-upgrade-type regexes that detect a CONCRETE extractable target.
# If none of the patterns match in implementation_steps/extracted_content/notes,
# the entry is narrative-only and shouldn't qualify for tier_1.
_CONCRETENESS_PATTERNS: dict[str, list[re.Pattern]] = {
    "skill": [
        re.compile(
            r"https?://(?:github|gitlab)\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", re.IGNORECASE
        ),
        re.compile(r"hermes\s+skills?\s+install\s+\S+", re.IGNORECASE),
        re.compile(r"\b[a-z0-9][a-z0-9_-]+/[a-z0-9][a-z0-9_./-]+\b"),  # slug shape org/repo
    ],
    "mcp_server": [
        re.compile(
            r"https?://(?:github|gitlab)\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", re.IGNORECASE
        ),
        re.compile(r"npx\s+-?y?\s*\S+", re.IGNORECASE),
        re.compile(r"npm\s+install\s+-?g?\s*\S+", re.IGNORECASE),
        re.compile(r"python\s+-m\s+\S+", re.IGNORECASE),
        re.compile(r'"command"\s*:\s*"', re.IGNORECASE),
    ],
    "cron_pattern": [
        re.compile(r"hermes\s+cron\s+add\b", re.IGNORECASE),
        re.compile(r"\b\d{1,2}\s+\d{1,2}\s+\*\s+\*\s+\*"),  # cron expr like "0 9 * * *"
        re.compile(r"every\s+\d+\s*(?:m|min|minute|h|hour|hr|d|day)\b", re.IGNORECASE),
        re.compile(r"\b(?:30m|1h|2h|6h|12h|1d)\b"),  # hermes shorthand
    ],
    "soul_template": [
        re.compile(r"```(?:markdown|md)?\s*\n[\s\S]{40,}\n```"),  # fenced markdown block >=40 chars
        re.compile(r"(?im)^#{1,3}\s+(?:soul|persona|operating contract|guardrails)\b"),
        re.compile(r"(?i)\byou are\b.*\byour\s+(?:main|primary|core)\s+(?:job|role|task)\b"),
        re.compile(r"(?im)^(?:[-*]\s+)?(?:[A-Z][a-z]+\s+){2,8}(?:principle|rule|guardrail)s?\b"),
    ],
    "library": [
        re.compile(r"pip\s+install\s+\S+", re.IGNORECASE),
        re.compile(r"uv\s+(?:pip\s+install|add)\s+\S+", re.IGNORECASE),
        re.compile(r"https?://(?:github|gitlab|pypi)\.\w+/\S+", re.IGNORECASE),
    ],
    "config_improvement": [
        re.compile(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\s*[:=]\s*\S+"
        ),  # key.path: value
        re.compile(
            r"(?i)(?:set|change|switch|update)\s+(?:the\s+)?[A-Za-z_][A-Za-z0-9_.]+\s+(?:to|from\s+\S+\s+to)\s+\S+"
        ),
        re.compile(r"^\s*[A-Z][A-Z0-9_]+=\S+", re.MULTILINE),  # ENV_VAR=value
    ],
    "gepa_target": [
        # GepaApplier always writes a YAML from the entry; any non-empty rationale qualifies.
        re.compile(r"."),
    ],
}


def _has_extractable_target(upgrade: ClassifiedUpgrade) -> bool:
    """True iff the entry contains a concrete artifact an applier can execute on.

    GROUND TRUTH variant (2026-05-21): instead of parallel regex patterns that
    can false-positive (e.g., a slug-shape substring buried in prose), this
    delegates to the SAME extractor functions the appliers actually use. If
    SkillInstaller._extract_slug_or_url returns None, the entry isn't a real
    skill candidate — full stop.

    Built from a minimal mock BacklogEntry since extractors only read the
    classifier fields (implementation_steps, extracted_content, notes, title,
    rationale).

    Falls back to the regex patterns for upgrade_types whose extractors are
    not available at import time (avoids hard-coupling backlog.py to every
    applier import).
    """
    upgrade_type = upgrade.upgrade_type
    if upgrade_type == "none" or not upgrade_type:
        return False

    # gepa_target is always concrete — GepaApplier just writes a YAML from
    # entry fields. Skip the extractor probe.
    if upgrade_type == "gepa_target":
        return True

    # Build a minimal entry-shaped object the extractors can read.
    mock_entry = _make_mock_entry(upgrade)

    try:
        if upgrade_type == "skill":
            from .appliers.skill_installer import SkillInstaller

            return SkillInstaller()._extract_slug_or_url(mock_entry) is not None
        if upgrade_type == "mcp_server":
            from .appliers.mcp_adder import McpAdder

            return McpAdder()._parse_mcp_spec(mock_entry) is not None
        if upgrade_type == "cron_pattern":
            from .appliers.cron_register import CronRegister

            return CronRegister()._extract_cron_spec(mock_entry) is not None
        if upgrade_type == "soul_template":
            from .appliers.soul_patcher import SoulPatcher

            return SoulPatcher()._extract_soul_addition(mock_entry) is not None
        if upgrade_type == "library":
            from .appliers.library_integrator import LibraryIntegrator

            return LibraryIntegrator()._extract_pip_spec(mock_entry) is not None
        if upgrade_type == "config_improvement":
            from .appliers.config_patcher import ConfigPatcher

            return ConfigPatcher()._extract_config_change(mock_entry) is not None
    except Exception as exc:
        logger.warning(
            "concreteness check raised for %s/%s: %s — fail-closed",
            upgrade.bookmark_id,
            upgrade_type,
            exc,
        )
        return False

    # Unknown upgrade_type — regex-pattern fallback (catches future types
    # without requiring a code change here).
    patterns = _CONCRETENESS_PATTERNS.get(upgrade_type)
    if not patterns:
        return False
    haystack = "\n".join(
        [
            upgrade.extracted_content or "",
            "\n".join(upgrade.implementation_steps or []),
            upgrade.notes or "",
            upgrade.title or "",
            upgrade.rationale or "",
        ]
    )
    return any(p.search(haystack) for p in patterns)


def _make_mock_entry(upgrade: ClassifiedUpgrade):
    """Build a minimal object with the fields applier extractors need.

    SkillInstaller / McpAdder / etc. read .implementation_steps, .extracted_content,
    .notes, .title, .rationale, .bookmark_id from a BacklogEntry. They don't need
    source URLs or apply_status during extraction. We can satisfy them with a
    SimpleNamespace rather than constructing a full BacklogEntry.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        bookmark_id=upgrade.bookmark_id,
        title=upgrade.title or "",
        rationale=upgrade.rationale or "",
        implementation_steps=list(upgrade.implementation_steps or []),
        extracted_content=upgrade.extracted_content or "",
        notes=upgrade.notes or "",
        upgrade_type=upgrade.upgrade_type,
        leverage_rank=upgrade.leverage_rank,
        risk=upgrade.risk,
        dependencies=list(upgrade.dependencies or []),
    )


def _is_community_source(upgrade: ClassifiedUpgrade) -> bool:
    """Return True iff the upgrade's source URL is a community (untrusted) github org.

    Applies to upgrade_type in (skill, mcp_server, library) — those are the
    types Hermes/Claude will install code from. Other types (cron, soul,
    config) don't fetch external code so this check is skipped.
    """
    if upgrade.upgrade_type not in ("skill", "mcp_server", "library"):
        return False
    # Look across all fields the classifier might have put a URL into.
    haystack = " ".join(
        [
            upgrade.extracted_content or "",
            " ".join(upgrade.implementation_steps or []),
            upgrade.notes or "",
            upgrade.title or "",
        ]
    )
    m = _GITHUB_URL_RE.search(haystack)
    if not m:
        # No github URL found — can't determine source; trust other signals.
        return False
    org = m.group(1).lower().lstrip("@")
    return org not in TRUSTED_SKILL_ORGS


logger = logging.getLogger(__name__)

# Discord guild id used to build canonical discord.com message URLs.
# (channel_id is per-call; this is the parent guild for the futures bookmark
#  channel on Amo's server.)
DEFAULT_GUILD_ID = "1490851279180660819"

_TIER_HEADINGS: dict[Tier, str] = {
    "tier_1": "Tier 1 — High leverage, low risk (do first)",
    "tier_2": "Tier 2 — High leverage, medium risk",
    "tier_3": "Tier 3 — Speculative",
    "defer": "Deferred",
}


def default_backlog_dir() -> Path:
    """Resolve ``~/.hermes/upgrade`` on this platform.

    Python on Windows can't reliably expand ``~`` to the WSL mount, so we hand
    Windows a literal path. Everywhere else we just expand.
    """
    if os.name == "nt":
        return Path(r"C:\Users\mattm\.hermes\upgrade")
    return Path(os.path.expanduser("~/.hermes/upgrade"))


# ---------------------------------------------------------------------------
# Tiering
# ---------------------------------------------------------------------------


def assign_tier(upgrade: ClassifiedUpgrade) -> Tier:
    """Tier the upgrade based on leverage, risk, and source-trust.

    Rules:
      - defer:  not applicable, OR leverage<=1 (noise)
      - tier_1: applicable, leverage>=4, risk=low, NOT community-source github org
      - tier_2: applicable, leverage>=3, risk in (low|med); OR would-be tier_1
                demoted due to untrusted community source
      - tier_3: everything else applicable (leverage>=2, or any risk=high)

    Community-source demotion (2026-05-20): skills/MCPs/libraries from github
    orgs NOT in TRUSTED_SKILL_ORGS are demoted tier_1 -> tier_2 because Hermes'
    deterministic security scanner BLOCKS community sources with CAUTION verdict
    on first apply. The LLM classifier doesn't see scanner verdicts, so it rates
    them low risk; this demotion closes the gap.
    """
    if not upgrade.applicable or upgrade.leverage_rank <= 1:
        return "defer"
    if upgrade.leverage_rank >= 4 and upgrade.risk == "low":
        # Concreteness gate — narrative-only entries can't be batch-applied.
        if not _has_extractable_target(upgrade):
            return "tier_3"
        if _is_community_source(upgrade):
            return "tier_2"
        return "tier_1"
    if upgrade.leverage_rank >= 3 and upgrade.risk in ("low", "med"):
        # tier_2 also requires a concrete target; otherwise applier would
        # immediately graceful-fail. Demote narrative items to tier_3.
        if not _has_extractable_target(upgrade):
            return "tier_3"
        return "tier_2"
    return "tier_3"


# ---------------------------------------------------------------------------
# Hydration — pull bookmark / vault context out of the production sqlite db
# ---------------------------------------------------------------------------


def hydrate_entry(
    upgrade: ClassifiedUpgrade,
    db_path: str | Path,
    channel_id: str = "1490851279180660819",
    guild_id: str = DEFAULT_GUILD_ID,
) -> BacklogEntry:
    """Compose a BacklogEntry by joining the upgrade with bookmark + analysis rows.

    Missing rows degrade gracefully — we fall back to empty strings rather than
    raise, so the backlog still renders if a bookmark was deleted between scan
    and render.
    """
    bookmark_url = ""
    vault_path = ""
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                """
                SELECT b.url, COALESCE(a.vault_path, '') AS vault_path
                FROM discord_bookmarks b
                LEFT JOIN discord_analyses a ON a.bookmark_id = b.message_id
                WHERE b.message_id = ?
                ORDER BY a.id DESC
                LIMIT 1
                """,
                (upgrade.bookmark_id,),
            ).fetchone()
            if row:
                bookmark_url = row[0] or ""
                vault_path = row[1] or ""
        finally:
            conn.close()
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        logger.warning("hydrate_entry: sqlite read failed for %s: %s", upgrade.bookmark_id, exc)

    discord_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{upgrade.bookmark_id}"

    return BacklogEntry(
        bookmark_id=upgrade.bookmark_id,
        source_bookmark_url=bookmark_url,
        source_discord_url=discord_url,
        source_vault_path=vault_path,
        upgrade_type=upgrade.upgrade_type,
        title=upgrade.title,
        rationale=upgrade.rationale,
        implementation_steps=list(upgrade.implementation_steps),
        leverage_rank=upgrade.leverage_rank,
        risk=upgrade.risk,
        dependencies=list(upgrade.dependencies),
        estimated_cost_usd=upgrade.estimated_cost_usd,
        extracted_content=upgrade.extracted_content,
        notes=upgrade.notes,
        tier="defer",  # caller overwrites via assign_tier()
        apply_status="pending",
    )


# ---------------------------------------------------------------------------
# Sorting + grouping
# ---------------------------------------------------------------------------


_TIER_ORDER: dict[Tier, int] = {"tier_1": 0, "tier_2": 1, "tier_3": 2, "defer": 3}


def _sort_key(entry: BacklogEntry) -> tuple[int, int, float, str]:
    """Sort: tier asc, leverage desc, cost asc, bookmark_id asc (stable).

    Within a tier the highest-leverage, cheapest items come first.
    """
    return (
        _TIER_ORDER.get(entry.tier, 99),
        -entry.leverage_rank,
        entry.estimated_cost_usd,
        entry.bookmark_id,
    )


def _group_by_tier(entries: Iterable[BacklogEntry]) -> dict[Tier, list[BacklogEntry]]:
    grouped: dict[Tier, list[BacklogEntry]] = {
        "tier_1": [],
        "tier_2": [],
        "tier_3": [],
        "defer": [],
    }
    for e in entries:
        grouped[e.tier].append(e)
    return grouped


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int = 500) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _render_entry(entry: BacklogEntry) -> list[str]:
    lines: list[str] = []
    title = entry.title or "(untitled upgrade)"
    lines.append(f"### [{entry.bookmark_id}] {title}")
    lines.append("")
    lines.append(
        f"- **Type:** {entry.upgrade_type}  "
        f"**Leverage:** {entry.leverage_rank}/5  "
        f"**Risk:** {entry.risk}  "
        f"**Cost:** ${entry.estimated_cost_usd:.2f}"
    )
    if entry.rationale:
        lines.append(f"- **Rationale:** {entry.rationale}")
    if entry.implementation_steps:
        lines.append("- **Implementation:**")
        for i, step in enumerate(entry.implementation_steps, 1):
            lines.append(f"  {i}. `{step}`")
    if entry.dependencies:
        deps = ", ".join(entry.dependencies)
        lines.append(f"- **Dependencies:** {deps}")
    src_parts: list[str] = []
    if entry.source_bookmark_url:
        src_parts.append(f"[bookmark]({entry.source_bookmark_url})")
    if entry.source_discord_url:
        src_parts.append(f"[Discord]({entry.source_discord_url})")
    if entry.source_vault_path:
        src_parts.append(f"[vault]({entry.source_vault_path})")
    if src_parts:
        lines.append("- **Source:** " + " | ".join(src_parts))
    if entry.notes:
        lines.append(f"- **Notes:** {entry.notes}")
    if entry.apply_status and entry.apply_status != "pending":
        # apply_timestamp can be a datetime (from a fresh classify run) OR a
        # string (when reloaded from JSONL via Pydantic model_validate). Handle
        # both — call isoformat() only on the datetime branch.
        if entry.apply_timestamp is None:
            ts = ""
        elif hasattr(entry.apply_timestamp, "isoformat"):
            ts = entry.apply_timestamp.isoformat()
        else:
            ts = str(entry.apply_timestamp)
        outcome = f" — {entry.apply_outcome}" if entry.apply_outcome else ""
        lines.append(f"- **Apply status:** {entry.apply_status} ({ts}){outcome}")
    if entry.extracted_content:
        lines.append("- **Extracted content:**")
        quote = _truncate(entry.extracted_content, 500)
        for qline in quote.splitlines() or [quote]:
            lines.append(f"  > {qline}")
    lines.append("")
    return lines


def _render_deferred_line(entry: BacklogEntry) -> str:
    title = entry.title or "(untitled)"
    reason = entry.rationale or entry.notes or "not applicable"
    return f"- `[{entry.bookmark_id}]` {title} — {_truncate(reason, 140)}"


def render_markdown(entries: list[BacklogEntry], *, now: datetime | None = None) -> str:
    """Render the backlog as a single markdown document with sections per tier."""
    now = now or datetime.now(timezone.utc)
    grouped = _group_by_tier(sorted(entries, key=_sort_key))
    tally = Counter({t: len(v) for t, v in grouped.items()})

    out: list[str] = []
    out.append(f"# Hermes Upgrade Backlog — generated {now.strftime('%Y-%m-%d %H:%M UTC')}")
    out.append("")
    out.append(
        f"Total candidates: {len(entries)}  |  "
        f"tier_1: {tally['tier_1']}  |  "
        f"tier_2: {tally['tier_2']}  |  "
        f"tier_3: {tally['tier_3']}  |  "
        f"deferred: {tally['defer']}"
    )
    out.append("")

    for tier in ("tier_1", "tier_2", "tier_3"):
        heading = _TIER_HEADINGS[tier]
        bucket = grouped[tier]
        out.append(f"## {heading}")
        out.append("")
        if not bucket:
            out.append("_None._")
            out.append("")
            continue
        for entry in bucket:
            out.extend(_render_entry(entry))

    # Deferred — collapsed, one line per item
    deferred = grouped["defer"]
    out.append(f"## Deferred ({len(deferred)} items)")
    out.append("")
    if deferred:
        for entry in deferred:
            out.append(_render_deferred_line(entry))
        out.append("")
    else:
        out.append("_None._")
        out.append("")

    out.append("---")
    out.append("")
    out.append("Apply with: `python -m discord.hermes_upgrade.applier --bookmark-id <id>`")
    out.append(
        "Apply all tier_1: "
        "`python -m discord.hermes_upgrade.applier --tier tier_1 --auto-approve-low-risk`"
    )
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write_backlog(
    entries: list[BacklogEntry],
    *,
    out_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write backlog.md and backlog.jsonl. Creates parent dir if missing.

    Returns (md_path, jsonl_path).
    """
    out = out_dir or default_backlog_dir()
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / "backlog.md"
    jsonl_path = out / "backlog.jsonl"

    md_path.write_text(render_markdown(entries), encoding="utf-8")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e.model_dump(mode="json"), default=str) + "\n")
    return md_path, jsonl_path


def merge_with_existing(
    new_entries: list[BacklogEntry],
    jsonl_path: Path,
) -> list[BacklogEntry]:
    """Preserve apply state from the previous JSONL, keyed by bookmark_id.

    If the prior entry was applied/skipped/failed/rolled_back, we keep its
    ``apply_status``, ``apply_timestamp``, ``apply_outcome``, and
    ``rollback_path``. Everything else (classification fields, rationale,
    extracted_content, ...) comes from the fresh ``new_entries`` — the
    classifier is authoritative for those.

    Unknown bookmark_ids in the file are dropped; the new run defines the
    universe.
    """
    if not jsonl_path.exists():
        return new_entries

    prior: dict[str, dict] = {}
    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                bid = row.get("bookmark_id")
                if bid:
                    prior[bid] = row
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("merge_with_existing: failed to read %s: %s", jsonl_path, exc)
        return new_entries

    merged: list[BacklogEntry] = []
    for entry in new_entries:
        prev = prior.get(entry.bookmark_id)
        if not prev:
            merged.append(entry)
            continue
        prev_status = prev.get("apply_status", "pending")
        if prev_status == "pending":
            merged.append(entry)
            continue
        updated = entry.model_copy(
            update={
                "apply_status": prev_status,
                "apply_timestamp": prev.get("apply_timestamp"),
                "apply_outcome": prev.get("apply_outcome", ""),
                "rollback_path": prev.get("rollback_path", ""),
            }
        )
        merged.append(updated)
    return merged


def is_classifier_error(entry: BacklogEntry) -> bool:
    """True iff this entry represents a failed classification attempt.

    classify_one() degrades errors (network, credit-exhaustion, malformed
    reply) to title="<classifier error>" rather than raising (see
    classifier.py). Those are NOT a real classification result and must
    stay eligible for retry on the next incremental scan, unlike a genuine
    upgrade_type="none" verdict which the classifier reached successfully.
    """
    return entry.title == "<classifier error>"


def load_prior_entries(jsonl_path: Path) -> dict[str, BacklogEntry]:
    """Load the previous run's BacklogEntry objects, keyed by bookmark_id.

    Powers incremental scanning: a bookmark_id with a real (non-error) prior
    classification doesn't need to hit the LLM again next run. Malformed
    rows are skipped rather than raising, matching merge_with_existing's
    defensive-read style.
    """
    if not jsonl_path.exists():
        return {}
    prior: dict[str, BacklogEntry] = {}
    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = BacklogEntry.model_validate(json.loads(raw))
                except (json.JSONDecodeError, ValueError):
                    continue
                prior[entry.bookmark_id] = entry
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("load_prior_entries: failed to read %s: %s", jsonl_path, exc)
        return {}
    return prior


__all__ = [
    "assign_tier",
    "default_backlog_dir",
    "hydrate_entry",
    "is_classifier_error",
    "load_prior_entries",
    "merge_with_existing",
    "render_markdown",
    "write_backlog",
]
