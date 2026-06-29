"""Vault path resolution and note read/write helpers.

Pure filesystem logic — no LLM, no network. Kept dependency-free so the
overnight job scripts and their tests can import it without spinning up the
engine.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Taxonomy ──────────────────────────────────────────────────────────────
# Numbered prefixes keep Obsidian's file-explorer sort order stable.
INBOX = "00-Inbox"
SOURCES = "01-Sources"
THESES = "02-Theses"
PROJECTS = "03-Projects"
ENGINE = "04-Engine"

VAULT_FOLDERS: tuple[str, ...] = (INBOX, SOURCES, THESES, PROJECTS, ENGINE)

# Matches engine/discord/deep_analyzer/vault.py so both writers agree.
_DEFAULT_VAULT_ROOT = Path(os.path.expanduser("~/my-vault"))


def vault_root() -> Path:
    """Resolve the vault root, honouring the JARVIS_VAULT_ROOT override.

    Read fresh on every call so the path can be repointed at runtime without a
    restart (the same gating discipline the cron scripts use).
    """
    override = os.getenv("JARVIS_VAULT_ROOT", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return _DEFAULT_VAULT_ROOT


def ensure_folders(root: Path | None = None) -> Path:
    """Create the five taxonomy folders under ``root`` if absent. Idempotent."""
    base = Path(root) if root is not None else vault_root()
    for folder in VAULT_FOLDERS:
        (base / folder).mkdir(parents=True, exist_ok=True)
    return base


def note_path(folder: str, filename: str, root: Path | None = None) -> Path:
    """Absolute path to ``filename`` inside taxonomy ``folder``."""
    base = Path(root) if root is not None else vault_root()
    return base / folder / filename


def write_note(
    folder: str,
    filename: str,
    content: str,
    root: Path | None = None,
) -> Path:
    """Write ``content`` to ``folder/filename`` (creating the folder). Returns the path."""
    path = note_path(folder, filename, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def iter_recent_notes(
    folder: str,
    days: int,
    root: Path | None = None,
) -> list[Path]:
    """Markdown notes under ``folder`` modified within the last ``days`` days.

    Recurses (the Discord writer nests by date), sorted newest-first. A
    missing folder yields an empty list rather than raising — the jobs must
    degrade gracefully before the vault is populated.
    """
    root_dir = Path(root) if root is not None else vault_root()
    base = root_dir / folder
    if not base.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()
    recent = [p for p in base.rglob("*.md") if p.is_file() and p.stat().st_mtime >= cutoff_ts]
    recent.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return recent


def read_notes_text(
    paths: list[Path],
    max_chars_each: int = 4000,
    vault_base: Path | None = None,
) -> str:
    """Concatenate notes into one LLM-friendly block, headed by relative path.

    Each note is truncated to ``max_chars_each`` so one long capture cannot
    blow the context budget. ``vault_base`` makes the header paths relative
    (e.g. ``01-Sources/foo.md``) for readable LLM citations.
    """
    base = Path(vault_base) if vault_base is not None else vault_root()
    chunks: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            # as_posix() forces forward slashes so the LLM-facing citation label is
            # identical on every OS. str(PurePath) uses backslashes on Windows, which
            # both reads wrong in a citation and broke test_read_notes_text on Windows
            # (it asserts "02-Theses/thesis.md"); CI on Linux never saw the divergence.
            label = path.relative_to(base).as_posix()
        except ValueError:
            label = path.name
        if len(text) > max_chars_each:
            text = text[:max_chars_each] + "\n…[truncated]"
        chunks.append(f"### NOTE: {label}\n{text}")
    return "\n\n".join(chunks)
