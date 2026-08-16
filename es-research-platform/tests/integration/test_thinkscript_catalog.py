from __future__ import annotations

import json
from pathlib import Path

from es_research.strategies.thinkscript_catalog import (
    build_thinkscript_catalog,
    write_thinkscript_catalog,
)


def test_repository_thinkscript_catalog_is_complete_and_deterministic(tmp_path: Path) -> None:
    source_dir = Path(__file__).resolve().parents[3] / "thinkorswim-scripts"
    first = build_thinkscript_catalog(source_dir)
    second = build_thinkscript_catalog(source_dir)
    assert first == second
    assert first.source_count == 28
    assert first.duplicate_count == 12
    assert {source.status for source in first.sources} >= {
        "active",
        "deprecated",
        "experimental",
        "ported",
        "reference_only",
    }

    output = tmp_path / "catalog.json"
    write_thinkscript_catalog(first, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["catalog_hash"] == first.catalog_hash
    assert all(len(digest) == 64 for source in first.sources for digest in source.file_hashes)
