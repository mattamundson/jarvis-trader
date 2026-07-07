"""Render Discord bookmarks (SQLite) → Obsidian vault Markdown pages.

v1 policy — CATCH-UP MODE:
  - If the target .md already exists, SKIP. Preserves the 2026-04-17 one-shot
    render (user triage, README excerpts, enriched GitHub metadata).
  - If the target file is missing, CREATE it with minimal-but-complete
    frontmatter + a placeholder body suitable for manual triage.
  - Index is regenerated on every run (it's pure-derivable from SQLite).

GitHub API enrichment (stars/language/license/pushed_at) is intentionally OUT
of scope for v1. Pages created by v1 have empty enrichment fields — a future
pass with a `--force-enrich` flag will fill them in. The existing 282 pages
already carry enrichment from the 2026-04-17 render; those are preserved.

Shape references — reproduce the existing render's frontmatter keys exactly:
    second-brain/wiki/discord-bookmarks/github/aaif-goose__goose.md
    second-brain/wiki/discord-bookmarks/x/0xjeff-2043656911044870203.md
    second-brain/wiki/discord-bookmarks/index.md
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# Engine package lives at the parent of this scripts/ dir. Make sibling modules
# (`discord.*`) importable whether we're run from `engine/` or `jarvis-trader/`.
_ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

logger = logging.getLogger(__name__)


DEFAULT_VAULT_DIR = r"C:\Users\mattm\second-brain\wiki\discord-bookmarks"
DEFAULT_DB_PATH = "engine/data/jarvis_trader.db"

# Module touch-point text mirrors the 2026-04-17 index header comments.
MODULE_TOUCH_POINTS = {
    "strategy": "engine/agents/pipeline.py, engine/strategies/, engine/backtest/, engine/agents/technical_analyst.py",
    "execution": "engine/execution/, engine/connectors/, engine/risk/safety_layer.py",
    "risk": "engine/risk/, engine/agents/risk_manager.py, engine/notifications/",
    "data": "engine/data/, engine/connectors/polygon.py, engine/connectors/ibkr/",
    "ml-ai": "engine/llm/, engine/agents/, engine/analytics/ic_ensemble.py",
    "infra": "engine/main.py, engine/scripts/, .claude/, dashboard/",
    "misc": "(general — review and route)",
    "unclassified": "(unclassified — needs triage)",
}


# ── Slug rules ────────────────────────────────────────────────────────────────

_GITHUB_PATH_RE = re.compile(r"^/([^/]+)/([^/#?]+)")
_X_PATH_RE = re.compile(r"^/([^/]+)/status/(\d+)")


def github_owner_repo(url: str) -> tuple[str, str]:
    """github.com/<Owner>/<Repo>[/...] → (Owner, Repo) with original case preserved.

    Trailing path segments (tree/, blob/, pull/, anchors, query strings) are stripped.
    Frontmatter uses the case-preserved pair; the filename slug lowercases them both
    for stability across renders — see `github_slug`.
    """
    parsed = urlparse(url)
    m = _GITHUB_PATH_RE.match(parsed.path)
    if not m:
        raise ValueError(f"not a github URL: {url}")
    return m.group(1), m.group(2)


def github_slug(url: str) -> str:
    """github.com/Owner/Repo → `owner__repo` (lowercased, for filename stability).

    Matches the 2026-04-17 vault render: see
    `second-brain/wiki/discord-bookmarks/github/ai4finance-foundation__fingpt.md`.
    """
    owner, repo = github_owner_repo(url)
    return f"{owner.lower()}__{repo.lower()}"


def x_post_handle_and_id(url: str) -> tuple[str, str]:
    """x.com/<Handle>/status/<id>[?s=12] → (Handle, id) with original case preserved.

    Frontmatter and body heading use the case-preserved handle; `x_post_slug`
    lowercases it for the filename.
    """
    parsed = urlparse(url)
    m = _X_PATH_RE.match(parsed.path)
    if not m:
        raise ValueError(f"not an x.com status URL: {url}")
    return m.group(1), m.group(2)


def x_post_slug(url: str) -> str:
    """x.com/<handle>/status/<id>[?s=12] → `<handle-lowercased>-<id>`."""
    handle, status_id = x_post_handle_and_id(url)
    return f"{handle.lower()}-{status_id}"


def other_slug(url: str, message_id: str) -> str:
    """Fallback for video/other — `<domain-with-underscores>-<message_id>`."""
    parsed = urlparse(url)
    domain = (parsed.netloc or "unknown").replace(".", "_").replace("-", "_").lower()
    if domain.startswith("www_"):
        domain = domain[4:]
    return f"{domain}-{message_id}"


# ── Page rendering ────────────────────────────────────────────────────────────

def _fmt_date(iso_ts: str) -> str:
    """Take an ISO-8601 timestamp and return the YYYY-MM-DD prefix."""
    if not iso_ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return iso_ts[:10]


def _fmt_captured_at() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _escape_yaml(value: Optional[str]) -> str:
    """Quote-and-escape a scalar so it is safe inside YAML frontmatter."""
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def render_github_page(bm) -> str:
    """Build a github vault page. Enrichment fields (stars/language/...) left blank
    for v1 — future `--force-enrich` pass will fill them via the GitHub API."""
    owner, repo = github_owner_repo(bm.url)  # original case for frontmatter/heading
    captured_at = _fmt_captured_at()

    return (
        "---\n"
        'source: "discord-bookmark"\n'
        'kind: "github"\n'
        f'url: "{_escape_yaml(bm.url)}"\n'
        f'owner: "{_escape_yaml(owner)}"\n'
        f'repo: "{_escape_yaml(repo)}"\n'
        'language: ""\n'
        'stars: ""\n'
        'license: ""\n'
        'archived: ""\n'
        'pushed_at: ""\n'
        f'captured_at: "{captured_at}"\n'
        f'posted_at: "{_escape_yaml(bm.posted_at)}"\n'
        f'posted_by: "{_escape_yaml(bm.author_name)}"\n'
        'jarvis_module: "unclassified"\n'
        'status: "pending-review"\n'
        "tags:\n"
        "  - discord/unclassified\n"
        "  - discord-bookmark\n"
        "---\n"
        "\n"
        f"# {owner}/{repo}\n"
        "\n"
        f"> {_escape_body(bm.embed_description) or '(description pending GitHub enrichment)'}\n"
        "\n"
        "## Source\n"
        f"- Repository: <{bm.url}>\n"
        f"- Posted by: **@{bm.author_name or 'unknown'}** on {bm.posted_at[:19] if bm.posted_at else 'unknown'}\n"
        "\n"
        "## Discord context\n"
        "\n"
        f"{_blockquote(bm.content) if bm.content and bm.content.strip() != bm.url.strip() else '_(no commentary — bare URL drop)_'}\n"
        "\n"
        "## Jarvis-Trader integration target\n"
        "- **Module:** `unclassified`\n"
        f"- **Touch points:** {MODULE_TOUCH_POINTS['unclassified']}\n"
        "\n"
        "## Suggested integration\n"
        "_(fill during review — what skill, hook, or pattern from this repo gets "
        "ported into jarvis-trader, and which file changes)_\n"
        "\n"
        "## Related\n"
        "- [[wiki/AI-Research-Queue]]\n"
        "- [[wiki/trading/research-queue]]\n"
        "- [[wiki/discord-bookmarks/index]]\n"
    )


def render_x_post_page(bm) -> str:
    handle, status_id = x_post_handle_and_id(bm.url)  # original case for frontmatter/body
    captured_at = _fmt_captured_at()

    # Title: prefer embed_title, fall back to a short content snippet, then generic
    title = (bm.embed_title or "").strip()
    if not title:
        snippet = (bm.content or "").strip()
        # Strip the URL from the snippet if content == bare URL
        if snippet and snippet != bm.url:
            title = snippet[:80]
        else:
            title = f"Tweet by @{handle}"

    # Quote body: embed_description > embed_title > content > blank
    quote = (bm.embed_description or bm.embed_title or "").strip()
    if not quote:
        # Use content only if it adds info beyond the bare URL
        c = (bm.content or "").strip()
        if c and c != bm.url.strip():
            quote = c

    return (
        "---\n"
        'source: "discord-bookmark"\n'
        'kind: "x-post"\n'
        f'url: "{_escape_yaml(bm.url)}"\n'
        f'author: "{_escape_yaml(handle)}"\n'
        f'status_id: "{status_id}"\n'
        f'captured_at: "{captured_at}"\n'
        f'posted_at: "{_escape_yaml(bm.posted_at[:19] if bm.posted_at else "")}"\n'
        f'posted_by: "{_escape_yaml(bm.author_name)}"\n'
        'jarvis_module: "unclassified"\n'
        'status: "pending-review"\n'
        "tags:\n"
        "  - discord/unclassified\n"
        "  - discord-bookmark\n"
        "  - x-post\n"
        f"  - author/{handle.lower()}\n"
        "---\n"
        "\n"
        f"# {_escape_body(title)}\n"
        "\n"
        f"**@{handle}** — {bm.posted_at[:19] if bm.posted_at else 'unknown'}  \n"
        f"<{bm.url}>\n"
        "\n"
        "## Quote\n"
        "\n"
        f"{_blockquote(quote) if quote else '> _(no embed captured)_'}\n"
        "\n"
        "## Dropped by\n"
        f"- **@{bm.author_name or 'unknown'}** (author_id `{bm.author_id or '?'}`)\n"
        "\n"
        "## Jarvis-Trader integration target\n"
        "- **Module:** `unclassified`\n"
        f"- **Touch points:** {MODULE_TOUCH_POINTS['unclassified']}\n"
        "\n"
        "## Suggested integration\n"
        "_(fill during review — does this idea become a new signal, agent prompt, "
        "ensemble tweak, or risk rule?)_\n"
        "\n"
        "## Related\n"
        "- [[wiki/AI-Research-Queue]]\n"
        "- [[wiki/trading/research-queue]]\n"
        "- [[wiki/discord-bookmarks/index]]\n"
    )


def render_other_page(bm) -> str:
    captured_at = _fmt_captured_at()
    domain = bm.domain or urlparse(bm.url).netloc

    return (
        "---\n"
        'source: "discord-bookmark"\n'
        f'kind: "{bm.source_type or "other"}"\n'
        f'url: "{_escape_yaml(bm.url)}"\n'
        f'domain: "{_escape_yaml(domain)}"\n'
        f'captured_at: "{captured_at}"\n'
        f'posted_at: "{_escape_yaml(bm.posted_at)}"\n'
        f'posted_by: "{_escape_yaml(bm.author_name)}"\n'
        'jarvis_module: "unclassified"\n'
        'status: "pending-review"\n'
        "tags:\n"
        "  - discord/unclassified\n"
        "  - discord-bookmark\n"
        f"  - source/{bm.source_type or 'other'}\n"
        "---\n"
        "\n"
        f"# Link from {domain}\n"
        "\n"
        f"<{bm.url}>\n"
        "\n"
        "## Discord context\n"
        "\n"
        f"{_blockquote(bm.content) if bm.content else '_(bare URL)_'}\n"
        "\n"
        "## Related\n"
        "- [[wiki/discord-bookmarks/index]]\n"
    )


def render_page_for_bookmark(bm) -> str:
    """Dispatch by source_type."""
    if bm.source_type == "github":
        return render_github_page(bm)
    if bm.source_type == "x_post":
        return render_x_post_page(bm)
    return render_other_page(bm)


def _blockquote(text: Optional[str]) -> str:
    if not text:
        return ""
    return "\n".join(f"> {line}" for line in text.splitlines())


def _escape_body(text: Optional[str]) -> str:
    if not text:
        return ""
    return text.replace("\n", " ").strip()


# ── Vault orchestration ───────────────────────────────────────────────────────

def _target_path(vault_dir: Path, bm) -> Optional[Path]:
    """Return the Path the bookmark should render to, or None if we can't place it."""
    try:
        if bm["source_type"] == "github":
            return vault_dir / "github" / f"{github_slug(bm['url'])}.md"
        if bm["source_type"] == "x_post":
            return vault_dir / "x" / f"{x_post_slug(bm['url'])}.md"
        return vault_dir / "other" / f"{other_slug(bm['url'], bm['message_id'])}.md"
    except ValueError as e:
        logger.warning(f"skipping bookmark {bm['message_id']}: {e}")
        return None


def _bookmark_from_row(row) -> "Bookmark":  # noqa: F821 - lazy import below
    # Local import to avoid a hard dependency when only the slug helpers are used
    from discord.models import Bookmark
    return Bookmark(**dict(row))


def render_vault(db_path: str, vault_dir: str) -> dict:
    """Render all bookmarks in SQLite into the vault. Returns stats dict."""
    vault_root = Path(vault_dir)
    vault_root.mkdir(parents=True, exist_ok=True)
    for sub in ("github", "x", "other"):
        (vault_root / sub).mkdir(exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT message_id, channel_id, posted_at, url, domain, source_type,
                   embed_title, embed_description, content, author_id, author_name
              FROM discord_bookmarks
             ORDER BY posted_at ASC
            """
        ).fetchall()
    finally:
        conn.close()

    stats = {"created": 0, "skipped_existing": 0, "failed": 0, "by_kind": {}}
    entries_for_index: list[dict] = []

    for row in rows:
        target = _target_path(vault_root, row)
        if target is None:
            stats["failed"] += 1
            continue

        entries_for_index.append(
            {
                "source_type": row["source_type"] or "other",
                "slug": target.stem,
                "url": row["url"],
                "subdir": target.parent.name,
            }
        )

        if target.exists():
            stats["skipped_existing"] += 1
            continue

        try:
            bm = _bookmark_from_row(row)
            page = render_page_for_bookmark(bm)
            target.write_text(page, encoding="utf-8")
            stats["created"] += 1
            stats["by_kind"].setdefault(row["source_type"] or "other", 0)
            stats["by_kind"][row["source_type"] or "other"] += 1
        except Exception as e:
            logger.error(f"failed to render {row['message_id']}: {e}")
            stats["failed"] += 1

    _write_index(vault_root, entries_for_index)
    return stats


def _write_index(vault_root: Path, entries: list[dict]) -> None:
    total = len(entries)
    captured_at = _fmt_captured_at()
    lines: list[str] = [
        "---",
        'source: "discord-bookmark"',
        'kind: "index"',
        f'captured_at: "{captured_at}"',
        f'total_links: "{total}"',
        "tags:",
        "  - discord-bookmark",
        "  - index",
        "---",
        "",
        "",
        "# Discord Bookmarks — Index",
        "",
        f"_Generated {captured_at}. {total} per-link pages from the Jarvis-Trader Discord #general channel._",
        "",
        "Status legend: `pending-review` (needs triage) → `reviewed` (analyzed) → `implemented` (code shipped) → `deferred` (low priority) → `dropped` (no fit).",
        "",
        "## Related queues",
        "- [[wiki/trading/research-queue]] — flat list of trading-relevant links",
        "- [[wiki/AI-Research-Queue]] — flat list of AI/infra-relevant links",
        "",
        f"## unclassified ({total})",
        "",
        f"_Touch points: {MODULE_TOUCH_POINTS['unclassified']}_",
        "",
    ]

    for entry in sorted(entries, key=lambda e: e["slug"].lower()):
        wikilink = f"wiki/discord-bookmarks/{entry['subdir']}/{entry['slug']}"
        lines.append(f"- [[{wikilink}|{entry['slug']}]] — <{entry['url']}>")

    (vault_root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── CLI entry ─────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db_path = os.environ.get("JARVIS_DB", DEFAULT_DB_PATH)
    vault_dir = os.environ.get("BOOKMARK_VAULT", DEFAULT_VAULT_DIR)
    logger.info(f"rendering bookmarks: db={db_path} -> vault={vault_dir}")
    stats = render_vault(db_path, vault_dir)
    logger.info(
        f"rendered: {stats['created']} new | skipped_existing={stats['skipped_existing']} "
        f"| failed={stats['failed']} | by_kind={stats['by_kind']}"
    )
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
