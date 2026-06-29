"""Obsidian vault integration for jarvis-trader.

Taxonomy and helpers shared by the overnight automations (synthesis brief,
contradiction check, capture routing, GitHub backup). The folder layout mirrors
DamiDefi's five-folder "second brain" structure, renamed to the trading domain:

    00-Inbox     raw captures + automation outputs (briefs, triage, contradictions)
    01-Sources   external material (Discord deep-analyzer, papers, articles)
    02-Theses    documented market positions / developing theses
    03-Projects  active research and writing
    04-Engine    pipeline / backtest outputs Claude generates

Vault root resolves from JARVIS_VAULT_ROOT (env), defaulting to ~/my-vault to
match engine/discord/deep_analyzer/vault.py.
"""

from .paths import (
    ENGINE,
    INBOX,
    PROJECTS,
    SOURCES,
    THESES,
    VAULT_FOLDERS,
    ensure_folders,
    iter_recent_notes,
    note_path,
    read_notes_text,
    vault_root,
    write_note,
)

__all__ = [
    "INBOX",
    "SOURCES",
    "THESES",
    "PROJECTS",
    "ENGINE",
    "VAULT_FOLDERS",
    "vault_root",
    "ensure_folders",
    "note_path",
    "write_note",
    "iter_recent_notes",
    "read_notes_text",
]
