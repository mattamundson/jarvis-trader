from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("validate_jarvis_mip", ROOT / "scripts/validate_jarvis_mip.py")
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class PlanValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.valid = VALIDATOR.load_graph(VALIDATOR.DEFAULT_GRAPH)
        cls.adoption = VALIDATOR.load_graph(VALIDATOR.DEFAULT_ADOPTION)

    def graph(self) -> dict:
        return copy.deepcopy(self.valid)

    def candidate_graph(self) -> dict:
        graph = self.graph()
        graph.update(plan_status="ADOPTION_CANDIDATE", planning_adoption_gate="CLOSED")
        graph["gates"][0].update(status="CLOSED", evidence_manifest=None)
        return graph

    def candidate_adoption(self) -> dict:
        adoption = copy.deepcopy(self.adoption)
        adoption.update(reviewed_plan_commit=None, decision_state="PENDING", pag_0="CLOSED")
        for item in adoption["decisions"]:
            item.update(disposition="PENDING", accountable_human=None, decided_at=None, rationale=None)
        return adoption

    def assert_invalid(self, graph: dict, message: str, profile: str = "structural") -> None:
        with self.assertRaisesRegex(VALIDATOR.ValidationError, message):
            VALIDATOR.validate_graph(graph, profile=profile)

    def test_adopted_pag0_bundle_is_valid(self) -> None:
        counts = VALIDATOR.validate_bundle(self.graph(), copy.deepcopy(self.adoption), "structural")
        self.assertEqual(counts["work_packages"], 103)
        self.assertEqual(counts["epics"], 34)
        self.assertEqual(counts["gates"], 14)

    def test_duplicate_work_package_is_rejected(self) -> None:
        graph = self.graph()
        graph["work_packages"][1]["id"] = graph["work_packages"][0]["id"]
        self.assert_invalid(graph, "IDs must be unique")

    def test_missing_dependency_is_rejected(self) -> None:
        graph = self.graph()
        graph["work_packages"][0]["dependencies"] = ["P-99"]
        self.assert_invalid(graph, "missing dependency P-99")

    def test_dependency_cycle_is_rejected(self) -> None:
        graph = self.graph()
        graph["work_packages"][0]["dependencies"] = ["A-01"]
        self.assert_invalid(graph, "dependency cycle")

    def test_epic_mismatch_is_rejected(self) -> None:
        graph = self.graph()
        graph["work_packages"][0]["epic"] = "A-E2"
        self.assert_invalid(graph, "epic backlink mismatch")

    def test_ready_package_requires_charter(self) -> None:
        graph = self.graph()
        package = graph["work_packages"][0]
        package["draft_charter_path"] = None
        package["charter_path"] = None
        package["status"] = "READY"
        self.assert_invalid(graph, "active status requires charter_path")

    def test_done_package_requires_evidence_manifest(self) -> None:
        graph = self.graph()
        package = graph["work_packages"][0]
        package["draft_charter_path"] = None
        package["status"] = "DONE"
        package["charter_path"] = "docs/plans/charters/A-01.md"
        self.assert_invalid(graph, "DONE requires evidence_manifest_path")

    def test_open_gate_requires_evidence_manifest(self) -> None:
        graph = self.graph()
        graph["gates"][2]["status"] = "OPEN"
        self.assert_invalid(graph, "open/passed gate requires evidence_manifest", profile="structural")

    def test_structural_profile_allows_governed_future_state(self) -> None:
        graph = self.graph()
        graph["plan_status"] = "ADOPTED"
        graph["planning_adoption_gate"] = "OPEN"
        graph["gates"][0]["status"] = "OPEN"
        graph["gates"][0]["evidence_manifest"] = "docs/plans/evidence/PAG-0.json"
        VALIDATOR.validate_graph(graph, profile="structural")
        self.assert_invalid(graph, "plan must remain an adoption candidate", profile="adoption-candidate")

    def test_s4_evidence_requires_human_capital_owner(self) -> None:
        graph = self.graph()
        package = next(item for item in graph["work_packages"] if item["id"] == "P-04")
        package["evidence_requirements"]["required_reviews"].remove("human_capital_owner")
        self.assert_invalid(graph, "P-04: S4 evidence requires human_capital_owner")

    def test_adoption_decision_requires_human_evidence(self) -> None:
        adoption = copy.deepcopy(self.adoption)
        adoption["decisions"][0]["accountable_human"] = None
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "accountable_human"):
            VALIDATOR.validate_adoption(adoption, "structural")

    def test_adoption_candidate_rejects_decided_items(self) -> None:
        adoption = self.candidate_adoption()
        item = adoption["decisions"][0]
        item.update(
            disposition="ACCEPT",
            accountable_human="human-owner",
            decided_at="2026-09-02T00:00:00Z",
            rationale="Reviewed and accepted.",
        )
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "decisions must remain PENDING"):
            VALIDATOR.validate_adoption(adoption, "adoption-candidate")

    def test_bundle_rejects_gate_status_drift(self) -> None:
        adoption = copy.deepcopy(self.adoption)
        adoption["pag_0"] = "CLOSED"
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "bundle: PAG-0 status mismatch"):
            VALIDATOR.validate_bundle(self.graph(), adoption, "structural")

    def test_pag0_requires_accepted_decisions(self) -> None:
        graph = self.graph()
        adoption = copy.deepcopy(self.adoption)
        adoption["decision_state"] = "PENDING"
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "PAG-0 requires accepted decisions"):
            VALIDATOR.validate_bundle(graph, adoption, "structural")

    def test_adoption_candidate_requires_all_phase_zero_draft_charters(self) -> None:
        graph = self.candidate_graph()
        package = next(item for item in graph["work_packages"] if item["id"] == "A-02")
        package["draft_charter_path"] = None
        self.assert_invalid(graph, "A-02: Phase 0 draft charter is required", profile="adoption-candidate")


if __name__ == "__main__":
    unittest.main()
