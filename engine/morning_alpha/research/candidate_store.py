from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.research.population import PopulationBuildResult


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return _sha256_bytes(raw)


class CandidatePopulationManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_version: str = "1.0.0"
    decision_timestamp: datetime
    candidates_path: str = "candidates.jsonl"
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    population_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    population_hash: str
    universe_hash: str
    data_manifest_hash: str
    split_registry_hash: str
    code_commit: str
    candidate_count: int = Field(ge=0)
    qualified_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    strategy_versions: tuple[str, ...]


class CandidatePopulationWriter:
    def write(
        self,
        result: PopulationBuildResult,
        root: str | Path,
        *,
        code_commit: str,
        split_registry_hash: str,
    ) -> CandidatePopulationManifest:
        root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)
        observations = sorted(result.observations, key=lambda row: row.candidate_id)
        lines = [
            json.dumps(row.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            for row in observations
        ]
        candidate_bytes = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
        candidate_path = root_path / "candidates.jsonl"
        candidate_path.write_bytes(candidate_bytes)
        content_hash = _sha256_bytes(candidate_bytes)

        manifest_hashes = {row.data_manifest_hash for row in observations}
        if len(manifest_hashes) > 1:
            raise ValueError("MANIFEST_IDENTITY_MISMATCH: observations contain multiple manifests")
        data_manifest_hash = next(iter(manifest_hashes), "")
        strategy_versions = tuple(sorted({row.strategy.canonical for row in observations}))
        identity_payload = {
            "content_sha256": content_hash,
            "population_hash": result.population_hash,
            "universe_hash": result.universe_hash,
            "data_manifest_hash": data_manifest_hash,
            "split_registry_hash": split_registry_hash,
            "code_commit": code_commit,
            "decision_timestamp": result.decision_timestamp.isoformat(),
            "strategy_versions": strategy_versions,
        }
        population_identity = _canonical_hash(identity_payload)
        manifest = CandidatePopulationManifest(
            decision_timestamp=result.decision_timestamp,
            content_sha256=content_hash,
            population_identity=population_identity,
            population_hash=result.population_hash,
            universe_hash=result.universe_hash,
            data_manifest_hash=data_manifest_hash,
            split_registry_hash=split_registry_hash,
            code_commit=code_commit,
            candidate_count=len(observations),
            qualified_count=result.qualified_count,
            rejected_count=result.rejected_count,
            strategy_versions=strategy_versions,
        )
        (root_path / "population_manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        return manifest


def verify_population_artifact(root: str | Path, manifest: CandidatePopulationManifest) -> bool:
    artifact = Path(root) / manifest.candidates_path
    if not artifact.is_file():
        return False
    return _sha256_bytes(artifact.read_bytes()) == manifest.content_sha256
