"""
JARVIS TRADER — Bookmark Weekly-Delta Synthesizer
==================================================

Produces a weekly markdown digest of new bookmarks added to the
`discord_bookmarks` table between two timestamps. Designed to replace
the ad-hoc scripts previously living in `~/discord-export/` (removed
during home cleanup 2026-05-08) and the hand-built `bookmark_delta.py`
under `%TEMP%` used to produce
`docs/digest/delta-2026-05-19-since-2026-05-05.md`.

Scope (v1 scaffold)
-------------------
* Pure, deterministic synthesis (NO LLM calls). The LLM-triaged
  "actionable / probe / noise" classification of the GitHub bucket
  is intentionally deferred — for now we just list embed titles +
  descriptions and let the human triage.
* GitHub bucket: every item in the window with `source_type='github'`
  is listed with title + blurb.
* X.com bucket: aggregate by author handle, report top 30 by count,
  total distinct authors, top-10 coverage percentage.
* Output: markdown matching the structure of the 2026-05-19 reference
  delta — headline, volume table, GitHub triage, X.com author table,
  provenance footer.

Companion module:
  * `engine/agents/bookmark_clusterer.py` — LLM clusterer that ALREADY
    handles the thematic-cluster pass (not duplicated here). When the
    LLM-triaged GitHub-classifier is added, it belongs in a follow-up
    PR that wires the clusterer into the GitHub bucket — not here.

CLI:
    .venv/Scripts/python -m engine.discord.bookmark_synthesizer \
        --since 2026-05-05 --until 2026-05-19

The CLI writes to `docs/digest/delta-<until>-since-<since>.md`.
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "jarvis_trader.db")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "digest"

# Top-30 X authors by post count, configurable for tests
TOP_XCOM_AUTHORS_LIMIT = 30
# Coverage metric is "top-N covers X% of posts" — N=10 matches reference doc
COVERAGE_TOP_N = 10
# Max length of any single embed-description blurb in the markdown table
MAX_BLURB_LEN = 280

_XCOM_HOST_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/", re.IGNORECASE)
_XCOM_AUTHOR_RE = re.compile(
    r"^https?://(?:www\.)?(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
_GITHUB_REPO_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/\s]+/[^/\s?#]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)


# ── Models ───────────────────────────────────────────────────────────────────


@dataclass
class BookmarkRow:
    """One row from `discord_bookmarks`, narrowed to fields the synthesizer uses."""

    message_id: str
    channel_id: str
    posted_at: str
    url: str
    domain: Optional[str]
    source_type: Optional[str]
    embed_title: Optional[str]
    embed_description: Optional[str]


# ── Query helpers ────────────────────────────────────────────────────────────


def _normalize_window(since: str, until: Optional[str]) -> Tuple[str, str]:
    """Coerce `since`/`until` into ISO date strings (YYYY-MM-DD).

    `until=None` means "today" (UTC date). Accepts either YYYY-MM-DD or
    a full ISO timestamp; the date portion is always retained.
    """

    def _to_date_str(s: str) -> str:
        if not s:
            raise ValueError("date string is empty")
        # accept YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS forms
        head = s.split("T", 1)[0].split(" ", 1)[0]
        # validate
        datetime.strptime(head, "%Y-%m-%d")
        return head

    since_norm = _to_date_str(since)
    until_norm = _to_date_str(until) if until else date.today().isoformat()
    return since_norm, until_norm


def _query_bookmarks_in_window(
    since: str,
    until: str,
    db_path: str = DEFAULT_DB_PATH,
    channel_id: Optional[str] = None,
) -> List[BookmarkRow]:
    """Query the `discord_bookmarks` table for rows in `[since, until)`.

    `since` is inclusive, `until` is exclusive (so calling with
    `since='2026-05-05', until='2026-05-19'` yields 14 days of data,
    matching the reference delta).
    """
    sql = """
        SELECT message_id, channel_id, posted_at, url, domain,
               source_type, embed_title, embed_description
          FROM discord_bookmarks
         WHERE posted_at >= ?
           AND posted_at < ?
    """
    params: List[str] = [since, until]
    if channel_id:
        sql += " AND channel_id = ?"
        params.append(channel_id)
    sql += " ORDER BY posted_at ASC"

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [
        BookmarkRow(
            message_id=r[0],
            channel_id=r[1],
            posted_at=r[2],
            url=r[3],
            domain=r[4],
            source_type=r[5],
            embed_title=r[6],
            embed_description=r[7],
        )
        for r in rows
    ]


# ── Bucketing ────────────────────────────────────────────────────────────────


def _split_by_domain(rows: List[BookmarkRow]) -> dict[str, List[BookmarkRow]]:
    """Bucket rows into `github` / `xcom` / `other` by URL/source_type.

    Trusts `source_type` first (populated by the bookmark parser), with a
    URL-pattern fallback for older rows that may have `source_type=None`.
    """
    buckets: dict[str, List[BookmarkRow]] = {"github": [], "xcom": [], "other": []}
    for r in rows:
        st = (r.source_type or "").lower()
        if st == "github" or "github.com" in (r.url or "").lower():
            buckets["github"].append(r)
        elif st in ("xcom", "twitter", "x") or _XCOM_HOST_RE.match(r.url or ""):
            buckets["xcom"].append(r)
        else:
            buckets["other"].append(r)
    return buckets


def _extract_xcom_author(url: str) -> Optional[str]:
    """Extract the leading `/<author>` segment from a twitter/x.com URL.

    Returns the bare handle without the leading `@`.
    """
    if not url:
        return None
    m = _XCOM_AUTHOR_RE.match(url.strip())
    if not m:
        return None
    handle = m.group(1)
    # Filter out reserved paths that aren't actually authors
    if handle.lower() in {"home", "explore", "notifications", "messages", "i", "search"}:
        return None
    return handle


def _extract_github_repo(url: str) -> Optional[str]:
    """Extract `owner/repo` from a github.com URL. Returns None if not a repo URL."""
    if not url:
        return None
    m = _GITHUB_REPO_RE.match(url.strip())
    if not m:
        return None
    # strip a trailing `.git` if present
    return m.group(1).rstrip("/").removesuffix(".git")


# ── Section builders ─────────────────────────────────────────────────────────


def _truncate(s: Optional[str], limit: int = MAX_BLURB_LEN) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _summarize_github_items(rows: List[BookmarkRow]) -> str:
    """Build the GitHub section markdown — title + blurb listing (no LLM triage).

    The LLM-triaged "actionable / probe / noise" pass is OUT OF SCOPE
    for this scaffold (see module docstring).
    """
    if not rows:
        return "_No GitHub bookmarks in this window._\n"

    lines = [
        f"_{len(rows)} GitHub bookmarks in window. Triage call (actionable / probe / noise) "
        "is deferred to a future LLM pass — this section lists embed metadata only._\n",
        "| # | Repo | Posted | Title | Blurb |",
        "|---:|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        repo = _extract_github_repo(r.url) or r.domain or "—"
        posted = (r.posted_at or "").split("T", 1)[0].split(" ", 1)[0]
        title = _truncate(r.embed_title, 80) or "_(no title)_"
        blurb = _truncate(r.embed_description, MAX_BLURB_LEN) or "_(no blurb)_"
        # escape pipes in markdown table content
        title = title.replace("|", r"\|")
        blurb = blurb.replace("|", r"\|")
        lines.append(f"| {i} | [`{repo}`]({r.url}) | {posted} | {title} | {blurb} |")
    return "\n".join(lines) + "\n"


def _summarize_xcom_authors(rows: List[BookmarkRow]) -> str:
    """Aggregate X.com posts by author and emit a top-30 markdown table."""
    if not rows:
        return "_No X.com bookmarks in this window._\n"

    handles: List[str] = []
    unknown_count = 0
    for r in rows:
        h = _extract_xcom_author(r.url)
        if h:
            handles.append(h.lower())
        else:
            unknown_count += 1

    counts = Counter(handles)
    total_posts = len(rows)
    total_authors = len(counts)
    top_n = counts.most_common(TOP_XCOM_AUTHORS_LIMIT)
    top_coverage_sum = sum(c for _, c in counts.most_common(COVERAGE_TOP_N))
    coverage_pct = (top_coverage_sum / total_posts * 100.0) if total_posts else 0.0

    lines = [
        f"_{total_posts} X.com posts in window across {total_authors} distinct authors. "
        f"Top {COVERAGE_TOP_N} authors cover {coverage_pct:.0f}% of posts._\n",
    ]
    if unknown_count:
        lines.append(f"_{unknown_count} URLs did not match the X.com author pattern._\n")
    lines.extend(
        [
            "| Posts | Handle |",
            "|---:|---|",
        ]
    )
    for handle, n in top_n:
        lines.append(f"| {n} | @{handle} |")
    return "\n".join(lines) + "\n"


# ── Public API ───────────────────────────────────────────────────────────────


def synthesize_delta(
    since: str,
    until: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
    channel_id: Optional[str] = None,
) -> str:
    """Synthesize a markdown delta digest for `[since, until)`.

    Pure function — no file I/O, no LLM calls. Caller decides where to
    write the output (or whether to write at all).
    """
    since_norm, until_norm = _normalize_window(since, until)
    rows = _query_bookmarks_in_window(
        since_norm, until_norm, db_path=db_path, channel_id=channel_id
    )
    buckets = _split_by_domain(rows)

    total = len(rows)
    gh_n = len(buckets["github"])
    x_n = len(buckets["xcom"])
    other_n = len(buckets["other"])

    # avoid div-by-zero
    def _pct(n: int) -> str:
        return f"{(n / total * 100.0):.0f}%" if total else "—"

    parts: List[str] = []
    parts.append(f"# Discord Bookmarks Delta — {since_norm} → {until_norm}\n")
    parts.append(
        "_Auto-generated by `engine.discord.bookmark_synthesizer`. "
        f"Window `[{since_norm}, {until_norm})` over the `discord_bookmarks` table._\n"
    )

    parts.append("## Headline\n")
    parts.append(
        f"**{total} new bookmarks in window. {gh_n} GitHub ({_pct(gh_n)}). "
        f"{x_n} X.com ({_pct(x_n)}). {other_n} other ({_pct(other_n)}).**\n"
    )

    parts.append("## Volume profile\n")
    parts.append("| Bucket | Count | Share |")
    parts.append("|---|---:|---:|")
    parts.append(f"| GitHub | {gh_n} | {_pct(gh_n)} |")
    parts.append(f"| X.com  | {x_n} | {_pct(x_n)} |")
    parts.append(f"| Other  | {other_n} | {_pct(other_n)} |")
    parts.append(f"| **Total** | **{total}** | **100%** |\n")

    parts.append("## GitHub bucket\n")
    parts.append(_summarize_github_items(buckets["github"]))

    parts.append("## X.com bucket — author concentration\n")
    parts.append(_summarize_xcom_authors(buckets["xcom"]))

    parts.append("## Provenance\n")
    parts.append(
        f"- Source DB: `{db_path}` table `discord_bookmarks`, "
        f"window `posted_at >= '{since_norm}' AND posted_at < '{until_norm}'`.\n"
        "- Pure synthesis — no LLM calls. GitHub-bucket LLM triage is deferred.\n"
        "- Generated by `engine.discord.bookmark_synthesizer.synthesize_delta`.\n"
    )

    return "\n".join(parts)


def write_delta_file(
    since: str,
    until: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    channel_id: Optional[str] = None,
) -> Path:
    """Synthesize and write the digest to `docs/digest/delta-<until>-since-<since>.md`.

    Returns the path written.
    """
    since_norm, until_norm = _normalize_window(since, until)
    md = synthesize_delta(since_norm, until_norm, db_path=db_path, channel_id=channel_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"delta-{until_norm}-since-{since_norm}.md"
    out_path.write_text(md, encoding="utf-8")
    return out_path


# ── CLI ──────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize a weekly bookmark-delta markdown digest."
    )
    parser.add_argument("--since", required=True, help="Window start (YYYY-MM-DD, inclusive).")
    parser.add_argument(
        "--until", default=None, help="Window end (YYYY-MM-DD, exclusive). Defaults to today."
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to jarvis_trader.db.")
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (defaults to <repo>/docs/digest/).",
    )
    parser.add_argument(
        "--channel-id",
        default=None,
        help="Restrict to a single Discord channel id.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print to stdout instead of writing to a file.",
    )
    return parser.parse_args(argv)


def _cli_main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.print:
        md = synthesize_delta(args.since, args.until, db_path=args.db, channel_id=args.channel_id)
        sys.stdout.write(md)
        return 0
    out_dir = Path(args.out) if args.out else DEFAULT_OUTPUT_DIR
    path = write_delta_file(
        args.since,
        args.until,
        db_path=args.db,
        output_dir=out_dir,
        channel_id=args.channel_id,
    )
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
