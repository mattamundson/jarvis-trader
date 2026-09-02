"""Identity checks for the immutable owner-supplied ThinkScript corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path

SOURCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "research"
    / "source"
    / "thinkscript"
    / "supplied-2026-09-02"
)


def test_supplied_thinkscript_manifest_matches_exact_bytes():
    manifest = SOURCE_DIR / "SHA256SUMS"
    rows = [line.split(maxsplit=1) for line in manifest.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 16
    expected_names = {name for _digest, name in rows}
    actual_names = {path.name for path in SOURCE_DIR.iterdir() if path.name != "SHA256SUMS"}
    assert actual_names == expected_names

    for expected_digest, name in rows:
        payload = (SOURCE_DIR / name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected_digest
