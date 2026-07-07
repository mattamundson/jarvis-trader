"""
engine.journal — daily trading journal generator.

Public API:
    build_journal_entry(date, db_path, log_path=None) -> dict
    render_markdown(entry: dict) -> str
    write_to_vault(entry: dict, vault_root: str) -> Path
"""

from engine.journal.builder import build_journal_entry, render_markdown, write_to_vault

__all__ = ["build_journal_entry", "render_markdown", "write_to_vault"]
