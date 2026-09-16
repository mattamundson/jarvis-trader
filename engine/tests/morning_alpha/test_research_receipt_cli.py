from hashlib import sha256
from pathlib import Path
import json

from morning_alpha.cli import main
from morning_alpha.research.campaign import ResearchArtifactKind


def test_cli_research_receipt_create_hashes_existing_artifact(tmp_path: Path, capsys):
    root = tmp_path / "research"
    evidence = root / "evidence"
    evidence.mkdir(parents=True)
    artifact = evidence / "universe.csv"
    artifact.write_text("symbol,effective_from\nSPY,2016-01-01\n", encoding="utf-8")

    rc = main(
        [
            "research-receipt-create",
            "--data-root",
            str(root),
            "--kind",
            "universe_membership",
            "--path",
            "evidence/universe.csv",
            "--provider",
            "fixture",
            "--row-count",
            "1",
            "--symbol-count",
            "1",
            "--point-in-time",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["sha256"] == sha256(artifact.read_bytes()).hexdigest()
    receipt_path = root / "receipts" / "universe_membership.json"
    assert receipt_path.is_file()
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["path"] == "evidence/universe.csv"


def test_cli_research_manifest_build_uses_receipts_not_manual_flags(tmp_path: Path, capsys):
    root = tmp_path / "research"
    receipts = root / "receipts"
    receipts.mkdir(parents=True)
    evidence = root / "evidence"
    evidence.mkdir()

    for kind in ResearchArtifactKind:
        artifact = evidence / f"{kind.value}.dat"
        artifact.write_text(kind.value, encoding="utf-8")
        receipt = {
            "kind": kind.value,
            "path": f"evidence/{artifact.name}",
            "sha256": sha256(artifact.read_bytes()).hexdigest(),
            "provider": "fixture",
            "row_count": 1000,
            "symbol_count": 800 if kind.value == "daily_bars" else 250,
            "earliest_timestamp": "2016-01-01T00:00:00+00:00",
            "latest_timestamp": "2026-09-15T00:00:00+00:00",
            "point_in_time": True,
        }
        (receipts / f"{kind.value}.json").write_text(json.dumps(receipt), encoding="utf-8")

    rc = main(["research-manifest-build", "--data-root", str(root), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["manifest_version"] == "1.1.0"
    assert payload["point_in_time_universe"] is True
    assert payload["source_lineage"] is True
    assert len(payload["artifacts"]) == len(ResearchArtifactKind)
    saved = json.loads((root / "research_manifest.json").read_text(encoding="utf-8"))
    assert saved == payload


def test_cli_research_manifest_build_fails_closed_without_receipts(tmp_path: Path, capsys):
    root = tmp_path / "research"
    root.mkdir()
    rc = main(["research-manifest-build", "--data-root", str(root), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["error"] == "NO_RECEIPTS"
