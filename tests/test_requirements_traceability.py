from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from apps.control_plane.requirements_traceability import (
    RequirementsTraceabilityError,
    RequirementsTraceabilityProgram,
)

ROOT = Path(__file__).parents[1]
REGISTRY_PATH = (
    ROOT / "docs" / "project" / "registries" / "requirements_traceability.json"
)


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _write_registry(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "requirements-traceability.json"
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _program_from(tmp_path: Path, value: dict) -> RequirementsTraceabilityProgram:
    return RequirementsTraceabilityProgram(_write_registry(tmp_path, value))


def _entry(value: dict, trace_ref: str) -> dict:
    return next(
        item
        for item in value["traceability_entries"]
        if item["trace_ref"] == trace_ref
    )


def test_project_compiles_every_historical_requirement_status():
    projection = RequirementsTraceabilityProgram().project()

    assert projection["contract_id"] == "kjds-requirements-traceability-program-v1"
    assert projection["contract_integrity"]["status"] == "VERIFIED"
    assert projection["counts"]["total"] == 13
    assert sum(projection["counts"]["by_status"].values()) == 13
    assert set(projection["counts"]["by_status"]) == set(
        RequirementsTraceabilityProgram.STATUS_VOCABULARY
    )
    assert all(
        count > 0 for count in projection["counts"]["by_status"].values()
    )
    assert len(projection["snapshot_sha256"]) == 64
    assert len(projection["registry_sha256"]) == 64


def test_every_entry_contains_the_user_requested_traceability_fields():
    projection = RequirementsTraceabilityProgram().project()
    required = RequirementsTraceabilityProgram.ENTRY_FIELDS

    for entry in projection["traceability_entries"]:
        assert required.issubset(entry)
        assert entry["requirement_sources"]
        assert entry["requirement_ids"]
        assert entry["machine_contract_refs"]
        assert entry["implementation_paths"]
        assert entry["current_version"]
        assert entry["owner"]["role_ref"] != entry["owner"]["alternate_role_ref"]
        assert entry["gate_refs"]
        assert entry["evidence_refs"]
        assert entry["unfinished_items"]
        assert entry["business_truth_status"] == "UNKNOWN"
        assert entry["business_truth_proven"] is False


def test_automation_core_and_isolated_runtime_are_traced_separately():
    projection = RequirementsTraceabilityProgram().project()
    core = next(
        item
        for item in projection["traceability_entries"]
        if item["trace_ref"] == "TRACE-005A"
    )
    isolated = next(
        item
        for item in projection["traceability_entries"]
        if item["trace_ref"] == "TRACE-005B"
    )

    assert core["status"] == "ADOPTED_ENGINEERING"
    assert core["current_version"]["ref"] == "bas-219a-mainline-core@1.0.0"
    assert all(not path.startswith("isolated:") for path in core["implementation_paths"])
    assert "runtime_api_web_integration" in core["unfinished_items"]
    assert isolated["status"] == "ISOLATED_IMPLEMENTED"
    assert isolated["current_version"]["branch"] == (
        "feat/automated-commerce-linkback-20260808"
    )
    assert isolated["current_version"]["head"] == (
        "5078b9fdaf781863f6f0700bd90abb3bdfad24c2"
    )
    assert isolated["current_version"]["mainline_integration_status"] == (
        "NOT_STARTED"
    )
    assert "selective_mainline_integration_gate" in isolated["gate_refs"]
    assert all(path.startswith("isolated:") for path in isolated["implementation_paths"])


def test_real_sku_rfq_and_cash_remain_blocked_evidence():
    projection = RequirementsTraceabilityProgram().project()
    blocked = next(
        item
        for item in projection["traceability_entries"]
        if item["trace_ref"] == "TRACE-010"
    )

    assert blocked["status"] == "BLOCKED_EVIDENCE"
    assert "formal_supplier_quotes" in blocked["blocking_evidence_refs"]
    assert "bank_cash_readback" in blocked["blocking_evidence_refs"]
    assert blocked["business_truth_status"] == "UNKNOWN"
    assert blocked["business_truth_proven"] is False


def test_duplicate_erp_and_task_bus_are_explicitly_rejected():
    projection = RequirementsTraceabilityProgram().project()
    rejected = next(
        item
        for item in projection["traceability_entries"]
        if item["trace_ref"] == "TRACE-011"
    )

    assert rejected["status"] == "REJECTED_DUPLICATE"
    assert "CommerceOperatingSystem" in rejected["canonical_owner_ref"]
    assert "second ERP" in rejected["rejection_reason"]
    assert projection["control_envelope"]["external_write_allowed"] is False


def test_automation_control_contracts_stay_contract_only_and_zero_authority():
    projection = RequirementsTraceabilityProgram().project()
    contracts = projection["automation_control_contracts"]

    assert [item["contract_ref"] for item in contracts] == list(
        RequirementsTraceabilityProgram.AUTOMATION_CONTRACT_REFS
    )
    assert all(item["status"] == "CONTRACT_ONLY" for item in contracts)
    assert all(item["runtime_connected"] is False for item in contracts)
    assert all(item["creates_authority"] is False for item in contracts)
    assert all(item["external_write_allowed"] is False for item in contracts)
    assert projection["dynamic_truth"] == {
        "status": "UNKNOWN",
        "human_bindings": None,
        "real_sku_cash_loop": None,
        "real_rfq_and_quotes": None,
        "customer_value": None,
        "production_gate": None,
        "top1_claim": False,
        "reason_codes": ["runtime_business_authorities_not_connected"],
    }


def test_project_returns_a_defensive_copy_and_performs_no_io(monkeypatch):
    program = RequirementsTraceabilityProgram()
    first = program.project()
    first["traceability_entries"][0]["title"] = "mutated"

    def _forbidden_read(*_args, **_kwargs):
        raise AssertionError("project performed filesystem I/O")

    monkeypatch.setattr(Path, "read_bytes", _forbidden_read)
    second = program.project()

    assert second["traceability_entries"][0]["title"] != "mutated"


def test_unknown_status_fails_closed(tmp_path):
    registry = _registry()
    registry["traceability_entries"][0]["status"] = "DONE"

    with pytest.raises(RequirementsTraceabilityError, match="Unsupported status"):
        _program_from(tmp_path, registry)


def test_missing_requested_field_fails_closed(tmp_path):
    registry = _registry()
    del registry["traceability_entries"][0]["unfinished_items"]

    with pytest.raises(RequirementsTraceabilityError, match="missing required fields"):
        _program_from(tmp_path, registry)


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_result", "complete"),
        ("gate_passed", True),
        ("production_ready", True),
        ("runtime_execution_enabled", True),
    ],
)
def test_dynamic_truth_fields_are_rejected(tmp_path, field, value):
    registry = _registry()
    registry["traceability_entries"][0][field] = value

    with pytest.raises(RequirementsTraceabilityError, match="forbidden dynamic truth"):
        _program_from(tmp_path, registry)


def test_missing_repository_reference_fails_closed(tmp_path):
    registry = _registry()
    registry["traceability_entries"][0]["implementation_paths"][0] = (
        "apps/control_plane/not-a-real-module.py"
    )

    with pytest.raises(RequirementsTraceabilityError, match="missing repository file"):
        _program_from(tmp_path, registry)


def test_isolated_entry_cannot_claim_mainline_or_drop_integration_gate(tmp_path):
    registry = _registry()
    isolated = _entry(registry, "TRACE-005B")
    isolated["current_version"]["mainline_integration_status"] = "DONE"
    isolated["gate_refs"].remove("selective_mainline_integration_gate")

    with pytest.raises(RequirementsTraceabilityError, match="mainline integration"):
        _program_from(tmp_path, registry)


def test_non_isolated_entry_cannot_reference_isolated_implementation(tmp_path):
    registry = _registry()
    registry["traceability_entries"][0]["implementation_paths"][0] = (
        "isolated:apps/control_plane/team_control_tower.py"
    )

    with pytest.raises(RequirementsTraceabilityError, match="without isolated status"):
        _program_from(tmp_path, registry)


def test_pilot_pending_requires_entry_and_exit_gates(tmp_path):
    registry = _registry()
    del _entry(registry, "TRACE-006")["pilot"]

    with pytest.raises(RequirementsTraceabilityError, match="pilot gate contract"):
        _program_from(tmp_path, registry)


def test_blocked_evidence_requires_named_missing_authorities(tmp_path):
    registry = _registry()
    del _entry(registry, "TRACE-010")["blocking_evidence_refs"]

    with pytest.raises(RequirementsTraceabilityError, match="blocking_evidence_refs"):
        _program_from(tmp_path, registry)


def test_rejected_duplicate_requires_canonical_owner_and_reason(tmp_path):
    registry = _registry()
    del _entry(registry, "TRACE-011")["canonical_owner_ref"]

    with pytest.raises(RequirementsTraceabilityError, match="canonical_owner_ref"):
        _program_from(tmp_path, registry)


def test_contract_cannot_self_enable_runtime_or_external_write(tmp_path):
    registry = _registry()
    contract = registry["automation_control_contracts"][0]
    contract["runtime_connected"] = True
    contract["external_write_allowed"] = True

    with pytest.raises(RequirementsTraceabilityError, match="runtime_connected"):
        _program_from(tmp_path, registry)


def test_truth_boundary_must_remain_all_false(tmp_path):
    registry = deepcopy(_registry())
    registry["truth_boundary"]["engineering_status_proves_business_result"] = True

    with pytest.raises(RequirementsTraceabilityError, match="grant no authority"):
        _program_from(tmp_path, registry)


def test_contract_only_cannot_be_relabelled_as_an_engineering_version(tmp_path):
    registry = _registry()
    _entry(registry, "TRACE-007")["current_version"]["kind"] = "engineering_commit"

    with pytest.raises(RequirementsTraceabilityError, match="incompatible with status"):
        _program_from(tmp_path, registry)


def test_blocked_entry_cannot_be_relabelled_as_adopted_engineering(tmp_path):
    registry = _registry()
    blocked = _entry(registry, "TRACE-010")
    blocked["status"] = "ADOPTED_ENGINEERING"

    with pytest.raises(RequirementsTraceabilityError, match="incompatible with status"):
        _program_from(tmp_path, registry)


def test_status_specific_fields_cannot_be_attached_to_another_status(tmp_path):
    registry = _registry()
    registry["traceability_entries"][0]["blocking_evidence_refs"] = ["fake_gap"]

    with pytest.raises(RequirementsTraceabilityError, match="optional fields"):
        _program_from(tmp_path, registry)


def test_entry_cannot_claim_business_truth(tmp_path):
    registry = _registry()
    registry["traceability_entries"][0]["business_truth_status"] = "VERIFIED"
    registry["traceability_entries"][0]["business_truth_proven"] = True

    with pytest.raises(RequirementsTraceabilityError, match="business truth status"):
        _program_from(tmp_path, registry)
