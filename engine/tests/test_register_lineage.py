"""Operator CLI to register decision lineages (P3) -- behaviour + honesty guard."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from backtest import decision_registry as dr  # noqa: E402
from backtest import register_lineage as rl  # noqa: E402

_SCAFFOLD = {
    "schema_version": 1,
    "registered_at": "2026-06-15",
    "purpose": "test scaffold",
    "methodology": "test",
    "graduation_rule": {"min_forward_oos_windows": 6},
    "allowed_status": ["forward_testing", "graduated", "rejected", "paused"],
    "lineages": [],
}

_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _write_registry(tmp_path) -> str:
    path = os.path.join(str(tmp_path), "decision_registry.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_SCAFFOLD, fh, indent=2)
        fh.write("\n")
    return path


def _read(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_register_explicit_hash_creates_lineage_and_verifies(tmp_path) -> None:
    path = _write_registry(tmp_path)
    rc = rl.main(
        ["--registry", path, "register", "--id", "lin-a", "--symbol", "MES",
         "--hash", _HASH_A]
    )
    assert rc == 0
    written = _read(path)
    assert dr.verify_registry(written) == []
    lins = written["lineages"]
    assert len(lins) == 1
    assert lins[0]["id"] == "lin-a"
    assert lins[0]["member_config_hashes"] == [_HASH_A]
    assert lins[0]["symbols"] == ["MES"]
    assert lins[0]["status"] == "forward_testing"


def test_same_hash_under_second_lineage_is_rejected_unchanged(tmp_path) -> None:
    path = _write_registry(tmp_path)
    assert rl.main(
        ["--registry", path, "register", "--id", "lin-a", "--symbol", "MES",
         "--hash", _HASH_A]
    ) == 0
    before = _read(path)

    # Same config_hash claimed by a DIFFERENT lineage -> honesty guard must abort.
    rc = rl.main(
        ["--registry", path, "register", "--id", "lin-b", "--symbol", "MGC",
         "--hash", _HASH_A]
    )
    assert rc != 0
    after = _read(path)
    assert after == before  # nothing written
    assert [lin["id"] for lin in after["lineages"]] == ["lin-a"]


def test_same_hash_and_symbol_into_same_lineage_is_idempotent(tmp_path) -> None:
    path = _write_registry(tmp_path)
    args = ["--registry", path, "register", "--id", "lin-a", "--symbol", "MES",
            "--hash", _HASH_A]
    assert rl.main(args) == 0
    assert rl.main(args) == 0
    written = _read(path)
    assert len(written["lineages"]) == 1
    lin = written["lineages"][0]
    assert lin["member_config_hashes"] == [_HASH_A]  # no duplicate
    assert lin["symbols"] == ["MES"]


def test_extend_lineage_adds_new_hash_and_symbol(tmp_path) -> None:
    path = _write_registry(tmp_path)
    assert rl.main(
        ["--registry", path, "register", "--id", "lin-a", "--symbol", "MES",
         "--hash", _HASH_A]
    ) == 0
    assert rl.main(
        ["--registry", path, "register", "--id", "lin-a", "--symbol", "MGC",
         "--hash", _HASH_B]
    ) == 0
    lin = _read(path)["lineages"][0]
    assert lin["member_config_hashes"] == [_HASH_A, _HASH_B]
    assert lin["symbols"] == ["MES", "MGC"]


def test_dry_run_writes_nothing(tmp_path) -> None:
    path = _write_registry(tmp_path)
    before = _read(path)
    rc = rl.main(
        ["--registry", path, "register", "--id", "lin-a", "--symbol", "MES",
         "--hash", _HASH_A, "--dry-run"]
    )
    assert rc == 0
    assert _read(path) == before  # unchanged


def test_register_without_hash_errors(tmp_path) -> None:
    path = _write_registry(tmp_path)
    rc = rl.main(["--registry", path, "register", "--id", "lin-a", "--symbol", "MES"])
    assert rc == 2
    assert _read(path)["lineages"] == []


def test_list_runs_clean(tmp_path) -> None:
    path = _write_registry(tmp_path)
    assert rl.main(["--registry", path, "list"]) == 0
