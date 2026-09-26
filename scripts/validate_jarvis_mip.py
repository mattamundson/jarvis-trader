#!/usr/bin/env python3
"""Validate the machine-readable JARVIS Master Implementation Plan graph."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = ROOT / "docs/plans/jarvis-mip-1.1/work_packages.json"
DEFAULT_ADOPTION = ROOT / "docs/plans/jarvis-mip-1.1/adoption_decisions.json"
WP_ID = re.compile(r"^[A-P]-\d{2}$")
STATUSES = {
    "NOT_STARTED",
    "READY",
    "IN_PROGRESS",
    "BLOCKED",
    "VALIDATION",
    "DONE",
    "SUPERSEDED",
}
SAFETY_CLASSES = {f"S{number}" for number in range(5)}
CODEX_LEVELS = {f"A{number}" for number in range(3)}
EVIDENCE_RUNGS = {f"E{number}" for number in range(6)}
PROFILES = {"structural", "adoption-candidate"}
PHASE_ZERO_CHARTERS = {"A-01", "A-02", "A-03", "A-06", "K-01", "O-01", "O-05"}


class ValidationError(ValueError):
    """Raised when the plan graph violates a structural invariant."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load_graph(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        graph = json.load(handle)
    require(isinstance(graph, dict), "graph root must be an object")
    return graph


def validate_adoption(adoption: dict[str, Any], profile: str) -> None:
    require(adoption.get("plan_id") == "JARVIS-MIP-1.1", "adoption: unexpected plan_id")
    decisions = adoption.get("decisions")
    require(isinstance(decisions, list) and len(decisions) == 14, "adoption: expected 14 decisions")
    require([item.get("id") for item in decisions] == [f"AD-{i:02d}" for i in range(1, 15)], "adoption: IDs must be AD-01 through AD-14")
    for item in decisions:
        disposition = item.get("disposition")
        require(disposition in {"PENDING", "ACCEPT", "AMEND", "REJECT"}, f"{item.get('id')}: invalid disposition")
        if disposition != "PENDING":
            require(item.get("accountable_human"), f"{item['id']}: decision requires accountable_human")
            require(item.get("decided_at"), f"{item['id']}: decision requires decided_at")
            require(item.get("rationale"), f"{item['id']}: decision requires rationale")
    if profile == "adoption-candidate":
        require(adoption.get("decision_state") == "PENDING", "adoption: decision state must remain PENDING")
        require(adoption.get("pag_0") == "CLOSED", "adoption: PAG-0 must remain closed")
        require(adoption.get("isg_0") == "CLOSED", "adoption: ISG-0 must remain closed")
        require(all(item["disposition"] == "PENDING" for item in decisions), "adoption: decisions must remain PENDING")


def validate_bundle(graph: dict[str, Any], adoption: dict[str, Any], profile: str) -> dict[str, int]:
    counts = validate_graph(graph, profile=profile)
    validate_adoption(adoption, profile=profile)
    require(adoption.get("pag_0") == graph.get("planning_adoption_gate"), "bundle: PAG-0 status mismatch")
    require(adoption.get("isg_0") == graph.get("implementation_start_gate"), "bundle: ISG-0 status mismatch")
    if adoption.get("decision_state") == "ACCEPTED":
        require(all(item["disposition"] == "ACCEPT" for item in adoption["decisions"]), "adoption: ACCEPTED requires all decisions accepted")
        require(adoption.get("reviewed_plan_commit"), "adoption: ACCEPTED requires reviewed_plan_commit")
    if adoption.get("pag_0") == "OPEN":
        require(adoption.get("decision_state") == "ACCEPTED", "adoption: PAG-0 requires accepted decisions")
    if adoption.get("isg_0") == "OPEN":
        require(adoption.get("pag_0") == "OPEN", "adoption: ISG-0 requires PAG-0 open")
    return counts


def validate_graph(graph: dict[str, Any], profile: str = "adoption-candidate") -> dict[str, int]:
    require(profile in PROFILES, f"unknown validation profile {profile}")
    require(graph.get("plan_id") == "JARVIS-MIP-1.1", "unexpected plan_id")
    require(graph.get("schema_version") == "1.1", "unexpected schema_version")
    if profile == "adoption-candidate":
        require(graph.get("plan_status") == "ADOPTION_CANDIDATE", "plan must remain an adoption candidate")
        require(graph.get("formal_implementation_status") == "NOT_STARTED", "formal implementation must remain NOT_STARTED")
        require(graph.get("planning_adoption_gate") == "CLOSED", "planning adoption gate must remain closed")
        require(graph.get("implementation_start_gate") == "CLOSED", "ISG-0 must remain closed")

    programs = graph.get("programs")
    require(isinstance(programs, list), "programs must be a list")
    program_ids = [program.get("id") for program in programs]
    require(program_ids == list("ABCDEFGHIJKLMNOP"), "programs must cover A-P in order")

    packages = graph.get("work_packages")
    require(isinstance(packages, list), "work_packages must be a list")
    require(len(packages) == 103, f"expected 103 work packages, found {len(packages)}")
    ids = [package.get("id") for package in packages]
    require(len(ids) == len(set(ids)), "work-package IDs must be unique")
    require(all(isinstance(item, str) and WP_ID.fullmatch(item) for item in ids), "invalid work-package ID")
    by_id = {package["id"]: package for package in packages}

    phase_counts: Counter[int] = Counter()
    for package in packages:
        package_id = package["id"]
        require(package.get("program") == package_id[0], f"{package_id}: program does not match ID")
        require(package.get("status") in STATUSES, f"{package_id}: invalid status")
        require(package.get("safety_class") in SAFETY_CLASSES, f"{package_id}: invalid safety class")
        require(package.get("codex_level") in CODEX_LEVELS, f"{package_id}: invalid Codex level")
        evidence = package.get("evidence_requirements")
        require(isinstance(evidence, dict), f"{package_id}: evidence_requirements must be an object")
        require(evidence.get("minimum_rung") in EVIDENCE_RUNGS, f"{package_id}: invalid evidence rung")
        for field in ("required_reviews", "required_observations"):
            require(isinstance(evidence.get(field), list), f"{package_id}: {field} must be a list")
            require(len(evidence[field]) == len(set(evidence[field])), f"{package_id}: duplicate {field}")
        for field in ("numeric_cross_check", "pit_verification"):
            require(isinstance(evidence.get(field), bool), f"{package_id}: {field} must be boolean")
        if package.get("safety_class") == "S4":
            require(
                "human_capital_owner" in evidence["required_reviews"],
                f"{package_id}: S4 evidence requires human_capital_owner",
            )
        require(package.get("charter_required") is True, f"{package_id}: charter_required must be true")
        draft_charter = package.get("draft_charter_path")
        if draft_charter:
            require(package.get("status") == "NOT_STARTED", f"{package_id}: draft charter is only valid for NOT_STARTED")
            charter_path = ROOT / draft_charter
            require(charter_path.is_file(), f"{package_id}: draft charter path does not exist")
            charter = charter_path.read_text(encoding="utf-8")
            require(charter.startswith(f"# {package_id} —"), f"{package_id}: draft charter heading mismatch")
            require("**Status:** DRAFT — NOT READY; PAG-0 CLOSED" in charter, f"{package_id}: draft charter must remain gated")
        require(isinstance(package.get("objective"), str) and package["objective"], f"{package_id}: objective is required")
        require(
            isinstance(package.get("acceptance_summary"), str) and package["acceptance_summary"],
            f"{package_id}: acceptance_summary is required",
        )
        if package.get("status") != "NOT_STARTED":
            require(package.get("charter_path"), f"{package_id}: active status requires charter_path")
        if package.get("status") == "DONE":
            require(package.get("evidence_manifest_path"), f"{package_id}: DONE requires evidence_manifest_path")
        phase = package.get("phase")
        require(isinstance(phase, int) and 0 <= phase <= 12, f"{package_id}: phase must be 0-12")
        expected_milestone = "ISG-0" if phase == 0 else f"M{phase}"
        require(package.get("milestone") == expected_milestone, f"{package_id}: milestone/phase mismatch")
        phase_counts[phase] += 1
        dependencies = package.get("dependencies")
        require(isinstance(dependencies, list), f"{package_id}: dependencies must be a list")
        require(len(dependencies) == len(set(dependencies)), f"{package_id}: duplicate dependency")
        for dependency in dependencies:
            require(dependency in by_id, f"{package_id}: missing dependency {dependency}")
            require(by_id[dependency]["phase"] <= phase, f"{package_id}: forward-phase dependency {dependency}")

    require(set(phase_counts) == set(range(13)), "delivery phases must cover 0-12")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(package_id: str) -> None:
        if package_id in visiting:
            raise ValidationError(f"dependency cycle includes {package_id}")
        if package_id in visited:
            return
        visiting.add(package_id)
        for dependency in by_id[package_id]["dependencies"]:
            visit(dependency)
        visiting.remove(package_id)
        visited.add(package_id)

    for package_id in ids:
        visit(package_id)

    epics = graph.get("epics")
    require(isinstance(epics, list), "epics must be a list")
    epic_names = [epic.get("id") for epic in epics]
    require(len(epic_names) == len(set(epic_names)), "epic IDs must be unique")
    epic_members = [item for epic in epics for item in epic.get("work_packages", [])]
    require(Counter(epic_members) == Counter(ids), "every work package must appear in one epic")
    epic_by_id = {epic["id"]: epic for epic in epics}
    for package in packages:
        epic_id = package.get("epic")
        require(epic_id in epic_by_id, f"{package['id']}: missing epic {epic_id}")
        require(epic_by_id[epic_id].get("program") == package["program"], f"{package['id']}: epic/program mismatch")
        require(package["id"] in epic_by_id[epic_id]["work_packages"], f"{package['id']}: epic backlink mismatch")

    phases = graph.get("phases")
    require(isinstance(phases, list), "phases must be a list")
    require([phase.get("id") for phase in phases] == list(range(13)), "phases must cover 0-12 in order")

    gates = graph.get("gates")
    require(isinstance(gates, list), "gates must be a list")
    gate_ids = [gate.get("id") for gate in gates]
    expected_gates = ["PAG-0", "ISG-0", *(f"M{number}" for number in range(1, 13))]
    require(gate_ids == expected_gates, "gates must cover PAG-0, ISG-0 and M1-M12 in order")
    for gate in gates:
        gate_id = gate["id"]
        require(gate.get("status") in {"CLOSED", "OPEN", "PASSED"}, f"{gate_id}: invalid gate status")
        require(isinstance(gate.get("authority"), str) and gate["authority"], f"{gate_id}: authority is required")
        required = gate.get("required_work_packages")
        require(isinstance(required, list), f"{gate_id}: required_work_packages must be a list")
        require(len(required) == len(set(required)), f"{gate_id}: duplicate required work package")
        require(all(item in by_id for item in required), f"{gate_id}: unknown required work package")
        if gate["status"] != "CLOSED":
            require(gate.get("evidence_manifest"), f"{gate_id}: open/passed gate requires evidence_manifest")
    gate_by_id = {gate["id"]: gate for gate in gates}
    require(gate_by_id["PAG-0"]["status"] == graph.get("planning_adoption_gate"), "PAG-0 status mismatch")
    require(gate_by_id["ISG-0"]["status"] == graph.get("implementation_start_gate"), "ISG-0 status mismatch")
    for phase in phases:
        require(phase.get("exit_gate") in gate_by_id, f"phase {phase.get('id')}: unknown exit gate")
    if profile == "adoption-candidate":
        for package_id in sorted(PHASE_ZERO_CHARTERS):
            require(by_id[package_id].get("draft_charter_path"), f"{package_id}: Phase 0 draft charter is required")

    return {
        "work_packages": len(packages),
        "programs": len(programs),
        "phases": len(phase_counts),
        "epics": len(epics),
        "gates": len(gates),
        "dependencies": sum(len(package["dependencies"]) for package in packages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", nargs="?", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="adoption-candidate")
    parser.add_argument("--adoption", type=Path, default=DEFAULT_ADOPTION)
    args = parser.parse_args()
    try:
        counts = validate_bundle(load_graph(args.graph), load_graph(args.adoption), profile=args.profile)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"JARVIS-MIP validation: FAIL: {exc}", file=sys.stderr)
        return 1
    print("JARVIS-MIP validation: PASS")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    print("  dependency_cycles: 0")
    print("  forward_phase_dependencies: 0")
    print(f"  profile: {args.profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
