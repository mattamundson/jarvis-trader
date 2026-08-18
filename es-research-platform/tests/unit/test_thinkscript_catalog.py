from __future__ import annotations

from pathlib import Path

import pytest

from es_research.strategies.thinkscript_catalog import build_thinkscript_catalog


def test_catalog_rejects_registry_path_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside.ts"
    outside.write_text("plot signal = close;", encoding="utf-8")
    source = tmp_path / "sources"
    source.mkdir()
    (source / "docs.md").write_text("docs", encoding="utf-8")
    (source / "registry.yaml").write_text(
        """version: 1
generated: '2026-07-28'
duplicates_to_skip: []
scripts:
  - id: escape
    file: ../outside.ts
    docs: docs.md
    status: research
    layer: 1
    layer_name: Regime
    python_counterpart: null
    tos_inputs: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="escapes source directory"):
        build_thinkscript_catalog(source)


def test_catalog_hash_changes_when_script_changes(tmp_path: Path) -> None:
    source = tmp_path / "sources"
    source.mkdir()
    script = source / "study.ts"
    script.write_text("plot signal = close;", encoding="utf-8")
    (source / "docs.md").write_text("docs", encoding="utf-8")
    (source / "registry.yaml").write_text(
        """version: 1
generated: '2026-07-28'
duplicates_to_skip: []
scripts:
  - id: study
    file: study.ts
    docs: docs.md
    status: research
    layer: 1
    layer_name: Regime
    python_counterpart: null
    tos_inputs: {length: 14}
""",
        encoding="utf-8",
    )
    first = build_thinkscript_catalog(source)
    script.write_text("plot signal = open;", encoding="utf-8")
    second = build_thinkscript_catalog(source)
    assert first.catalog_hash != second.catalog_hash
    assert first.sources[0].file_hashes != second.sources[0].file_hashes
