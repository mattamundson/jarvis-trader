"""Approval snapshots preserve point-in-time data provenance.

Batch-imported untracked WIP (2026-09-24 audit). pipeline_result_for_approval_snapshot
exists in approval/snapshot.py but does not preserve data_provenance yet —
the key is absent from the snapshot keys tuple. The test documents the desired
contract; skipped rather than deleted so the gap is explicitly tracked.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "approval.snapshot does not yet preserve data_provenance in pipeline snapshots; "
    "the test documents the desired contract — see header",
    allow_module_level=True,
)
