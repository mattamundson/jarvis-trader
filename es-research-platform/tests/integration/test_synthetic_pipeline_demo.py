from __future__ import annotations

from es_research.pipeline.synthetic import run_synthetic_pipeline


def test_synthetic_pipeline_reproducibility(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = run_synthetic_pipeline(tmp_path / "first")
    second = run_synthetic_pipeline(tmp_path / "second")

    assert first.manifest_hash == second.manifest_hash
    assert first.normalized_rows_hash == second.normalized_rows_hash
    assert first.bars_hash == second.bars_hash
    assert first.parquet_sha256 == second.parquet_sha256
    assert first.report_hash == second.report_hash
    assert first.row_count == second.row_count == 12
    assert first.bar_count == second.bar_count == 3
    assert first.parquet_path.exists()
    assert second.parquet_path.exists()
    assert first.report_path.exists()
    assert second.report_path.exists()
    assert "manifest_hash" in first.report_path.read_text(encoding="utf-8")
