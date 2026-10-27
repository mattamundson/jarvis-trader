from __future__ import annotations

import json
import platform
from enum import StrEnum
from hashlib import sha256

import numpy as np
import scipy
import statsmodels
from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class VerificationIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    code_commit: str = Field(min_length=1)
    spec_version: str = Field(min_length=1)
    data_manifest_hash: str = Field(min_length=64, max_length=64)
    candidate_population_hash: str = Field(min_length=64, max_length=64)
    trial_ledger_hash: str = Field(min_length=64, max_length=64)
    seeds: dict[str, int] = Field(default_factory=dict)


class VerificationComponentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    status: VerificationStatus
    evidence_id: str = Field(min_length=64, max_length=64)


class VerificationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity: VerificationIdentity
    components: tuple[VerificationComponentEvidence, ...]
    overall_status: VerificationStatus
    python_version: str
    numpy_version: str
    scipy_version: str
    statsmodels_version: str
    receipt_id: str = Field(min_length=64, max_length=64)
    summary: str | None = None
    disclaimer: str = "VERIFICATION RECEIPT IS NOT A STRATEGY PROMOTION OR EDGE VERDICT"


def _hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def _overall(components: tuple[VerificationComponentEvidence, ...]) -> VerificationStatus:
    if any(item.status is VerificationStatus.FAILED for item in components):
        return VerificationStatus.FAILED
    if any(item.status is VerificationStatus.INCOMPLETE for item in components):
        return VerificationStatus.INCOMPLETE
    return VerificationStatus.VERIFIED


def build_verification_receipt(
    identity: VerificationIdentity,
    components: tuple[VerificationComponentEvidence, ...] | list[VerificationComponentEvidence],
    *,
    summary: str | None = None,
) -> VerificationReceipt:
    evidence = tuple(components)
    if not evidence:
        raise ValueError("verification receipt requires at least one component")
    if len({item.name for item in evidence}) != len(evidence):
        raise ValueError("verification component names must be unique")

    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "statsmodels": statsmodels.__version__,
    }
    overall = _overall(evidence)
    identity_payload = {
        "identity": identity.model_dump(mode="json"),
        "components": [item.model_dump(mode="json") for item in evidence],
        "overall_status": overall.value,
        "versions": versions,
    }
    return VerificationReceipt(
        identity=identity,
        components=evidence,
        overall_status=overall,
        python_version=versions["python"],
        numpy_version=versions["numpy"],
        scipy_version=versions["scipy"],
        statsmodels_version=versions["statsmodels"],
        receipt_id=_hash(identity_payload),
        summary=summary,
    )
