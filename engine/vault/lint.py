"""Vault wikilink lint pass — structural integrity, no LLM.

Complements the semantic synthesis jobs (``synthesis.py``) with a purely
structural check, the article's "lint pass that catches broken links":

  * Broken links — ``[[wikilinks]]`` whose target resolves to no note file.
  * Orphans      — notes that nothing links to (automation output in
                   ``00-Inbox`` is excluded, since briefs/contradictions/lint
                   reports are generated, not authored).

Pure filesystem logic — no LLM, no network — kept dependency-light like
``paths.py`` so the cron entry script and its tests import it without spinning
up the engine. Writes ``00-Inbox/lint-YYYY-MM-DD.md``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

# Obsidian wikilink: [[Target]], [[Target|alias]], [[Target#heading]],
# [[folder/Target]]. We capture the inner text and normalise it below.
_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")


def _link_target_key(raw: str) -> str:
    """Normalise a wikilink target to a comparison key (basename stem, lower).

    Obsidian resolves links by filename, ignoring folder path, heading anchor,
    and display alias, and is case-insensitive for resolution. Mirror that so
    ``[[01-Sources/Foo Bar|see Foo]]`` and ``[[foo bar#intro]]`` both key to
    ``foo bar``.
    """
    target = raw.split("|", 1)[0]  # drop display alias
    target = target.split("#", 1)[0]  # drop heading anchor
    target = target.strip().replace("\\", "/")
    stem = target.rsplit("/", 1)[-1]  # drop folder path → basename
    return stem.strip().lower()


def _iter_all_notes(root: Path) -> list[Path]:
    """Every markdown note under the five taxonomy folders, sorted by path."""
    notes: list[Path] = []
    for folder in paths.VAULT_FOLDERS:
        base = root / folder
        if base.exists():
            notes.extend(p for p in base.rglob("*.md") if p.is_file())
    notes.sort()
    return notes


def lint_vault(root: Path | None = None) -> dict:
    """Scan the vault for broken wikilinks and orphan notes.

    Returns a dict with ``note_count``, ``link_count``, ``broken`` (list of
    ``{"source", "target"}``) and ``orphans`` (list of relative paths). A note
    in ``00-Inbox`` is never reported as an orphan — that folder holds generated
    automation output, which legitimately nobody links to.
    """
    base = paths.ensure_folders(root)
    notes = _iter_all_notes(base)

    # Map every existing note to its resolution key so links can be matched.
    existing_keys: set[str] = {p.stem.strip().lower() for p in notes}

    broken: list[dict[str, str]] = []
    linked_keys: set[str] = set()
    link_count = 0

    for note in notes:
        try:
            text = note.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        source_label = note.relative_to(base).as_posix()
        for match in _WIKILINK_RE.finditer(text):
            raw = match.group(1)
            key = _link_target_key(raw)
            if not key:
                continue
            link_count += 1
            linked_keys.add(key)
            if key not in existing_keys:
                broken.append({"source": source_label, "target": raw.strip()})

    orphans: list[str] = []
    for note in notes:
        # 00-Inbox holds generated automation output — never flag as orphan.
        if note.relative_to(base).parts[0] == paths.INBOX:
            continue
        if note.stem.strip().lower() not in linked_keys:
            orphans.append(note.relative_to(base).as_posix())

    return {
        "note_count": len(notes),
        "link_count": link_count,
        "broken": broken,
        "orphans": sorted(orphans),
    }


def _frontmatter(note_count: int, broken: int, orphans: int) -> str:
    return (
        "---\n"
        f"generated: {datetime.now(timezone.utc).isoformat()}\n"
        "job: lint\n"
        f"notes_scanned: {note_count}\n"
        f"broken_links: {broken}\n"
        f"orphan_notes: {orphans}\n"
        "tags: [vault-automation, lint]\n"
        "---\n\n"
    )


def render_report(result: dict) -> str:
    """Render the lint result as a markdown body (no frontmatter)."""
    broken = result["broken"]
    orphans = result["orphans"]
    lines: list[str] = ["# Vault link lint\n"]
    lines.append(
        f"Scanned {result['note_count']} notes, {result['link_count']} wikilinks. "
        f"{len(broken)} broken, {len(orphans)} orphans.\n"
    )

    lines.append("## Broken links\n")
    if broken:
        for item in broken:
            lines.append(f"- `{item['source']}` → `[[{item['target']}]]` (no matching note)")
    else:
        lines.append("None. Every wikilink resolves.")
    lines.append("")

    lines.append("## Orphan notes\n")
    if orphans:
        lines.append("Notes nothing links to (excluding generated 00-Inbox output):\n")
        for rel in orphans:
            lines.append(f"- `{rel}`")
    else:
        lines.append("None. Every note is linked from somewhere.")
    lines.append("")

    return "\n".join(lines)


def run_lint(root: Path | None = None) -> Path | None:
    """Run the lint pass and write 00-Inbox/lint-YYYY-MM-DD.md.

    Returns the written path, or None if the vault has no notes to scan yet.
    """
    base = paths.ensure_folders(root)
    result = lint_vault(root=base)
    if result["note_count"] == 0:
        logger.info("vault lint: no notes found — skipping")
        return None

    body = _frontmatter(result["note_count"], len(result["broken"]), len(result["orphans"]))
    body += render_report(result)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = paths.write_note(paths.INBOX, f"lint-{date_str}.md", body, root=base)
    logger.info(
        "vault lint written: %s (%d broken, %d orphans)",
        out,
        len(result["broken"]),
        len(result["orphans"]),
    )
    return out
