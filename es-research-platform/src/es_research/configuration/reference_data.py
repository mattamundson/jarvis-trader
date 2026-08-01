"""Validated, hashable reference-data inputs for vendor normalization."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from es_research.contracts import SessionCalendar
from es_research.hashing import sha256_hash


def load_instrument_map(path: Path) -> tuple[dict[int, str], str]:
    """Load a JSON object of Databento instrument IDs to raw contract symbols."""
    payload = _load_json(path)
    if not isinstance(payload, dict) or not payload:
        raise ValueError("instrument map must be a non-empty JSON object")
    mapping: dict[int, str] = {}
    for raw_id, raw_symbol in payload.items():
        try:
            instrument_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid instrument ID in mapping: {raw_id!r}") from exc
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise ValueError(f"instrument {instrument_id} requires a non-empty symbol")
        mapping[instrument_id] = raw_symbol.strip()
    return mapping, sha256_hash(mapping)


def load_session_calendars(path: Path) -> tuple[tuple[SessionCalendar, ...], str]:
    """Load and validate a JSON array of UTC session-calendar contracts."""
    payload = _load_json(path)
    sessions = TypeAdapter(tuple[SessionCalendar, ...]).validate_python(payload)
    if not sessions:
        raise ValueError("session calendar must contain at least one session")
    ordered = tuple(sorted(sessions, key=lambda session: session.session_open))
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.session_open < previous.session_close:
            raise ValueError(
                f"session calendars overlap: {previous.session_id!r} and {current.session_id!r}"
            )
    return ordered, sha256_hash(ordered)


def _load_json(path: Path) -> object:
    if not path.is_file():
        raise FileNotFoundError(f"reference-data file does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
