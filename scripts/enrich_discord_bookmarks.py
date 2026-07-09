#!/usr/bin/env python3
"""
enrich_discord_bookmarks.py

Enriches raw Discord bookmark files with cross-links for Obsidian graph view
and gbrain semantic search. Idempotent — skips files already containing the
ENRICHED marker. Appends a "Cross-links" section at the end of each file.

Usage:
    python enrich_discord_bookmarks.py [--dry-run]

Options:
    --dry-run   Print enrichment plan for first 5 files; do not write.
"""

import os
import re
import sys
import time
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOOKMARKS_DIR = Path(r"C:\Users\mattm\master-jarvis\second-brain\raw\discord-bookmarks")
SKIP_FILES = {"_INDEX.md", "_LAST_EXTRACT.json"}
ENRICHED_MARKER = "<!-- ENRICHED:CROSS-LINKS -->"
TIME_LIMIT_SECONDS = 300  # 5 minutes

# Keyword → theme wiki-link map (order matters — first match wins)
THEME_MAP = [
    (
        ["agent", "claude", "hermes", "openclaw"],
        "[[hermes-openclaw-ecosystem-map]]",
    ),
    (
        ["trading", "quant", "options", "futures", "polymarket", "vol"],
        "[[discord-bookmark-thematic-index#trading-quant-markets]]",
    ),
    (
        ["memory", "rag", "embedding", "vector"],
        "[[discord-bookmark-thematic-index#agent-memory]]",
    ),
    (
        ["mcp", "model context protocol"],
        "[[discord-bookmark-thematic-index#mcp-servers]]",
    ),
    (
        ["karpathy"],
        "[[discord-bookmark-thematic-index#karpathy-educational]]",
    ),
    (
        ["foundation model", "transformer", "gpt", "llama", "qwen"],
        "[[discord-bookmark-thematic-index#foundation-models]]",
    ),
]
DEFAULT_THEME = "[[discord-bookmark-thematic-index]]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> dict:
    """Extract simple key: value pairs from YAML frontmatter."""
    meta: dict = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    block = text[3:end]
    for line in block.splitlines():
        m = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta


def classify_theme(title: str, description: str) -> str:
    """Return the best-matching theme wiki-link."""
    corpus = (title + " " + description).lower()
    for keywords, link in THEME_MAP:
        if any(kw in corpus for kw in keywords):
            return link
    return DEFAULT_THEME


def parse_github_repo(url: str) -> str | None:
    """Return 'owner/repo' from a github.com URL, or None."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/?#]+)", url)
    if m:
        owner, repo = m.group(1), m.group(2)
        # Strip .git suffix
        repo = re.sub(r"\.git$", "", repo)
        return f"{owner}/{repo}"
    return None


def repo_slug(owner_repo: str) -> str:
    """Convert 'owner/repo' to the vault filename slug used in wiki/repos/."""
    # Convention: "owner-repo.md" lowercased with slashes → hyphens
    return owner_repo.replace("/", "-").lower()


def build_cross_links_section(meta: dict, title: str, description: str) -> str:
    """Construct the Cross-links markdown section."""
    lines = [
        "",
        "---",
        "",
        "## Cross-links",
        "",
        ENRICHED_MARKER,
        "",
    ]

    # Author link
    author_raw = meta.get("author", "")
    if author_raw:
        author_slug = author_raw.lower().replace(" ", "_")
        lines.append(f"- **Author:** [[authors/{author_slug}]]")

    # GitHub repo link (if applicable)
    url = meta.get("url", "")
    repo = parse_github_repo(url)
    if repo:
        slug = repo_slug(repo)
        lines.append(f"- **Repo:** [[repos/{slug}]]")

    # Theme classification
    theme_link = classify_theme(title, description)
    lines.append(f"- **Theme:** {theme_link}")

    # Master index + channel
    lines.append("- **Index:** [[discord-extraction-master-index]]")
    lines.append("- **Channel:** [[discord-jarvis-mcp]]")
    lines.append("")

    return "\n".join(lines)


def extract_title_and_description(text: str) -> tuple[str, str]:
    """Pull the H1 title and Description block from the file body."""
    title = ""
    description = ""

    # Title: first # heading
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        title = m.group(1).strip()

    # Description: content after "## Description" up to the next heading / EOF
    m = re.search(r"## Description\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if m:
        description = m.group(1).strip()

    return title, description


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def enrich_file(path: Path, dry_run: bool = False) -> str:
    """
    Enrich a single file. Returns 'skipped', 'enriched', or 'failed'.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"  [ERROR] Cannot read {path.name}: {e}")
        return "failed"

    # Idempotent check
    if ENRICHED_MARKER in text:
        return "skipped"

    meta = parse_frontmatter(text)
    title, description = extract_title_and_description(text)
    section = build_cross_links_section(meta, title, description)

    if dry_run:
        print(f"\n--- {path.name} ---")
        print(f"  author={meta.get('author','?')}  url={meta.get('url','?')[:60]}")
        print(f"  title={title[:60]}")
        print(f"  desc={description[:80]}")
        print("  [WOULD APPEND]:")
        for line in section.splitlines():
            print(f"    {line}")
        return "enriched"

    new_text = text.rstrip() + "\n" + section
    try:
        path.write_text(new_text, encoding="utf-8")
    except Exception as e:
        print(f"  [ERROR] Cannot write {path.name}: {e}")
        return "failed"

    return "enriched"


def main():
    dry_run = "--dry-run" in sys.argv

    all_files = sorted(
        [
            f
            for f in BOOKMARKS_DIR.iterdir()
            if f.is_file() and f.name not in SKIP_FILES and f.suffix == ".md"
        ]
    )

    total = len(all_files)
    print(f"Found {total} bookmark files in {BOOKMARKS_DIR}")
    if dry_run:
        print("DRY-RUN mode: processing first 5 files only.\n")
        all_files = all_files[:5]

    counts = {"enriched": 0, "skipped": 0, "failed": 0}
    start = time.monotonic()
    checkpoint_written = False

    for i, path in enumerate(all_files, 1):
        # Time-box check (skip in dry-run)
        if not dry_run:
            elapsed = time.monotonic() - start
            if elapsed >= TIME_LIMIT_SECONDS:
                if not checkpoint_written:
                    print(
                        f"\n[CHECKPOINT] 5-minute limit reached after {i-1} files "
                        f"({counts['enriched']} enriched, {counts['skipped']} skipped, "
                        f"{counts['failed']} failed). "
                        f"Re-run to continue — already-enriched files will be skipped."
                    )
                    checkpoint_written = True
                break

        result = enrich_file(path, dry_run=dry_run)
        counts[result] += 1

        if not dry_run and i % 100 == 0:
            elapsed = time.monotonic() - start
            print(
                f"  Progress: {i}/{total} files | "
                f"enriched={counts['enriched']} skipped={counts['skipped']} "
                f"failed={counts['failed']} | {elapsed:.1f}s elapsed"
            )

    elapsed = time.monotonic() - start
    print(
        f"\n{'[DRY-RUN] ' if dry_run else ''}Done in {elapsed:.1f}s | "
        f"enriched={counts['enriched']} skipped={counts['skipped']} failed={counts['failed']}"
    )


if __name__ == "__main__":
    main()
