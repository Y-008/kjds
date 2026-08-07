from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from apps.control_plane.enterprise_ai_erp_program import (
    EnterpriseAiErpProgram,
    EnterpriseAiErpProgramError,
)

ROOT = Path(__file__).parents[1]
REGISTRIES = ROOT / "docs" / "project" / "registries"
PROGRAM_PATH = REGISTRIES / "enterprise_ai_erp_program.json"
TEAM_PATH = REGISTRIES / "team_control_tower_registry.json"
EXPERT_PATH = REGISTRIES / "global_expert_team_registry.json"
ATLAS_PATH = REGISTRIES / "cross_border_capability_atlas.json"


def _payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mutated(path: Path, tmp_path: Path, name: str, mutate) -> Path:
    payload = _payload(path)
    mutate(payload)
    target = tmp_path / name
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def _program(tmp_path: Path, mutate) -> EnterpriseAiErpProgram:
    path = _mutated(PROGRAM_PATH, tmp_path, "program.json", mutate)
    return EnterpriseAiErpProgram(path)


def test_project_compiles_exact_static_contract_counts_and_unknown_truth():
    projection = EnterpriseAiErpProgram().project()

    assert projection["status"] == "UNKNOWN"
    assert projection["contract_integrity"]["status"] == "VERIFIED"
    assert projection["counts"] == {
        "existing_core_roles": 18,
        "ai_specialists": 12,
        "enterprise_domain_roles": 14,
        "squads": 8,
        "day_0_30_work_items": 6,
        "independent_control_roles": 5,
        "expert_pool_capacity_minimum": 30,
        "expert_pool_capacity_maximum": 60,
        "sod_rules": 6,
        "maturity_levels": 5,
    }
    assert projection["organization_readiness"]["status"] == "UNKNOWN"
    assert projection["organization_readiness"]["registry_proves_human_appointment"] is False
    assert projection["organization_readiness"]["verified_expert_pool_members"] is None
    assert projection["expert_pool_contract"]["target_minimum"] == 30
    assert projection["expert_pool_contract"]["target_maximum"] == 60
    assert projection["expert_pool_contract"]["registry_proves_engagement"] is False


def test_role_contracts_have_exact_ids_controls_and_unknown_bindings():
    service = EnterpriseAiErpProgram()
    roles = service.project()["role_contracts"]

    assert tuple(item["role_ref"] for item in roles) == tuple(sorted(service.DOMAIN_ROLES))
    assert all(item["binding_status"] == "UNKNOWN" for item in roles)
    assert all(item["budget_authority_status"] == "UNKNOWN" for item in roles)
    assert all(item["maximum_loss_authority_status"] == "UNKNOWN" for item in roles)
    assert all(item["conflict_attestation_required"] is True for item in roles)
    assert all(set(item["outcomes"]) == {"day_30", "day_60", "day_90"} for item in roles)


def test_squads_require_five_functions_and_never_claim_readiness():
    service = EnterpriseAiErpProgram()
    readiness = service.project()["squad_readiness"]

    assert readiness["status"] == "UNKNOWN"
    assert tuple(item["squad_ref"] for item in readiness["items"]) == service.SQUAD_IDS
    assert all(item["status"] == "UNKNOWN" for item in readiness["items"])
    assert all(
        tuple(item["required_functions"]) == service.SQUAD_FUNCTIONS
        for item in readiness["items"]
    )


def test_work_program_has_stable_parallel_waves_and_no_runtime_claim():
    projection = EnterpriseAiErpProgram().project()

    assert projection["parallel_waves"] == [
        ["EAERP-01", "EAERP-02", "EAERP-04"],
        ["EAERP-03"],
        ["EAERP-05"],
        ["EAERP-06"],
    ]
    assert [item["work_item_ref"] for item in projection["work_program"]] == [
        "EAERP-01",
        "EAERP-02",
        "EAERP-04",
        "EAERP-03",
        "EAERP-05",
        "EAERP-06",
    ]
    assert all(item["planned_initial_state"] == "NOT_STARTED" for item in projection["work_program"])
    assert all(item["execution_status"] == "UNKNOWN" for item in projection["work_program"])
    assert all(item["achieved_maturity"] == "UNKNOWN" for item in projection["work_program"])
    assert all(item["resolved_task_promotes_maturity"] is False for item in projection["work_program"])


def test_phases_and_maturity_require_authority_instead_of_calendar_promotion():
    projection = EnterpriseAiErpProgram().project()

    assert [item["status"] for item in projection["phases"]] == ["UNKNOWN"] * 5
    assert [item["planned_initial_state"] for item in projection["phases"]] == [
        "NOT_STARTED"
    ] * 5
    assert [item["gate_status"] for item in projection["phases"]] == ["UNKNOWN"] * 5
    maturity = projection["maturity_model"]
    assert maturity["status"] == "UNKNOWN"
    assert [item["level"] for item in maturity["levels"]] == ["M0", "M1", "M2", "M3", "M4"]
    assert all(item["status"] == "UNKNOWN" for item in maturity["levels"])
    assert maturity["execution_state_is_maturity_authority"] is False
    assert maturity["registry_requirement_is_completion_evidence"] is False


def test_sod_and_parallel_limits_are_policy_not_observed_identity_or_wip():
    projection = EnterpriseAiErpProgram().project()

    conflicts = projection["role_conflicts"]
    assert conflicts["status"] == "UNKNOWN"
    assert conflicts["contract_rules_verified"] is True
    assert conflicts["observed_conflicts"] is None
    assert [item["rule_ref"] for item in conflicts["rules"]] == list(
        EnterpriseAiErpProgram.SOD_RULES
    )
    parallel = projection["parallel_execution"]
    assert parallel["status"] == "UNKNOWN"
    assert parallel["policy"]["control_agent_count"] == 1
    assert parallel["policy"]["max_parallel_specialist_agents"] == 3
    assert parallel["policy"]["max_active_writers"] == 3
    assert parallel["policy"]["max_active_tasks_per_specialist"] == 1
    assert parallel["policy"]["max_active_tasks_per_writer"] == 1
    assert parallel["policy"]["max_current_tasks_per_lane"] == 1
    assert parallel["observed_active_writers"] is None
    assert parallel["observed_writer_wip"] is None
    assert parallel["observed_lane_current_tasks"] is None


def test_project_is_deterministic_content_bound_and_returns_defensive_copy():
    service = EnterpriseAiErpProgram()
    first = service.project()
    second = service.project()

    assert first == second
    basis = dict(first)
    supplied = basis.pop("snapshot_sha256")
    assert supplied == service._canonical_hash(basis)
    first["counts"]["squads"] = 999
    first["work_program"][0]["title"] = "mutated"
    assert service.project()["counts"]["squads"] == 8
    assert service.project()["work_program"][0]["title"] != "mutated"


def test_project_performs_no_file_io_after_construction(monkeypatch):
    service = EnterpriseAiErpProgram()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("project performed filesystem I/O")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)

    assert service.project()["contract_integrity"]["status"] == "VERIFIED"


def test_project_bound_method_accepts_no_runtime_or_authority_arguments():
    service = EnterpriseAiErpProgram()

    assert inspect.signature(service.project).parameters == {}


def test_projection_hashes_all_four_static_sources():
    projection = EnterpriseAiErpProgram().project()

    assert [item["source_ref"] for item in projection["source_hashes"]] == [
        "capability_atlas",
        "enterprise_ai_erp_program",
        "global_expert_team",
        "team_control_tower",
    ]
    assert all(len(item["sha256"]) == 64 for item in projection["source_hashes"])
    assert projection["contract_integrity"]["source_bundle_sha256"]


def test_control_envelope_denies_every_runtime_or_external_authority():
    envelope = EnterpriseAiErpProgram().project()["control_envelope"]

    assert envelope["read_only"] is True
    assert all(
        envelope[key] is False
        for key in (
            "static_registry_is_runtime_authority",
            "registry_proves_human_appointment",
            "registry_proves_active_wip",
            "registry_proves_maturity",
            "resolved_task_promotes_maturity",
            "operating_task_created",
            "fact_created",
            "finance_entry_created",
            "approval_created",
            "permit_created",
            "external_write_allowed",
        )
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("primary_human_ref", "person-1"),
        ("verified_binding_refs", ["binding-1"]),
        ("current_task", {"task_id": "EAERP-01"}),
        ("task_status", "done"),
        ("execution_state", "running"),
        ("active_writer_ref", "agent-1"),
        ("achieved_maturity", "M4"),
        ("verified_evidence_refs", ["evidence-1"]),
        ("gate_passed", True),
        ("owner_thread_id", "thread-1"),
        ("current_kpi_value", 1),
        ("current_release_result", "PASS"),
    ],
)
def test_static_registry_rejects_dynamic_truth_fields(tmp_path: Path, field: str, value):
    def mutate(payload):
        payload["role_contracts"][0][field] = value

    with pytest.raises(EnterpriseAiErpProgramError, match="dynamic truth field"):
        _program(tmp_path, mutate)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: payload.update(schema_version="future"), "schema or version"),
        (lambda payload: payload.update(version="2.0.0"), "schema or version"),
        (lambda payload: payload.update(status="draft"), "schema or version"),
        (lambda payload: payload["role_contracts"].pop(), "fourteen"),
        (
            lambda payload: payload["role_contracts"][1].update(
                role_ref=payload["role_contracts"][0]["role_ref"]
            ),
            "identifiers",
        ),
        (
            lambda payload: payload["role_contracts"][0].pop("kpis"),
            "fields drift",
        ),
        (
            lambda payload: payload["role_contracts"][0].update(
                alternate_role_ref="unknown_role"
            ),
            "Invalid alternate",
        ),
        (
            lambda payload: payload["role_contracts"][0].update(
                alternate_role_ref=payload["role_contracts"][0][
                    "reviewer_role_ref"
                ]
            ),
            "Primary, alternate and reviewer must differ",
        ),
        (
            lambda payload: payload["role_contracts"][0].update(
                budget_authority_status="VERIFIED"
            ),
            "fail closed",
        ),
    ],
)
def test_program_rejects_role_and_header_contract_drift(tmp_path: Path, mutate, match: str):
    with pytest.raises(EnterpriseAiErpProgramError, match=match):
        _program(tmp_path, mutate)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: payload["squads"].pop(), "eight squads"),
        (
            lambda payload: payload["squads"][0]["required_functions"].pop(),
            "five canonical functions",
        ),
        (
            lambda payload: payload["squads"][0]["capability_atlas_ids"].append(
                "unknown_capability"
            ),
            "unknown capability",
        ),
        (
            lambda payload: payload["squads"][0].update(primary_lane_id="Z"),
            "lane reference drift",
        ),
        (
            lambda payload: payload["squads"][0]["work_item_refs"].append(
                "EAERP-99"
            ),
            "unknown work item",
        ),
    ],
)
def test_program_rejects_squad_contract_drift(tmp_path: Path, mutate, match: str):
    with pytest.raises(EnterpriseAiErpProgramError, match=match):
        _program(tmp_path, mutate)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: payload["work_items"].pop(), "six EAERP"),
        (
            lambda payload: payload["work_items"][0].pop("rollback"),
            "work item fields drift",
        ),
        (
            lambda payload: payload["work_items"][0]["dependency_refs"].append(
                "EAERP-99"
            ),
            "dependency drift",
        ),
        (
            lambda payload: payload["work_items"][0].update(
                alternate_role_ref=payload["work_items"][0]["owner_role_ref"]
            ),
            "role separation drift",
        ),
        (
            lambda payload: payload["work_items"][0].update(sla_hours=0),
            "SLA must be positive",
        ),
    ],
)
def test_program_rejects_wbs_contract_drift(tmp_path: Path, mutate, match: str):
    with pytest.raises(EnterpriseAiErpProgramError, match=match):
        _program(tmp_path, mutate)


def test_program_rejects_work_item_cycle(tmp_path: Path):
    def mutate(payload):
        payload["work_items"][0]["dependency_refs"] = ["EAERP-06"]

    with pytest.raises(EnterpriseAiErpProgramError, match="DAG contains a cycle"):
        _program(tmp_path, mutate)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: payload["phases"].pop(), "Five delivery phases"),
        (
            lambda payload: payload["phases"][1].update(day_from=30),
            "phase boundaries drift",
        ),
        (
            lambda payload: payload["maturity_model"]["levels"].reverse(),
            "ordered M0 to M4",
        ),
        (
            lambda payload: payload["maturity_model"]["levels"][0].update(
                status="VERIFIED"
            ),
            "level fields drift",
        ),
        (lambda payload: payload["sod_rules"].pop(), "Six SoD rules"),
        (
            lambda payload: payload["sod_rules"][0].update(
                same_principal_allowed=True
            ),
            "fail closed",
        ),
        (
            lambda payload: payload["execution_policy"].update(
                max_active_writers=4
            ),
            "execution policy drift",
        ),
        (
            lambda payload: payload["control_boundary"].update(
                grants_external_write=True
            ),
            "boundary must fail closed",
        ),
    ],
)
def test_program_rejects_phase_maturity_sod_and_control_drift(
    tmp_path: Path, mutate, match: str
):
    with pytest.raises(EnterpriseAiErpProgramError, match=match):
        _program(tmp_path, mutate)


@pytest.mark.parametrize(
    "source_path,name,mutate,match,argument",
    [
        (
            TEAM_PATH,
            "team.json",
            lambda payload: payload.update(version="9.0"),
            "Team control registry",
            "organization_registry_path",
        ),
        (
            EXPERT_PATH,
            "experts.json",
            lambda payload: payload["specialist_roles"].pop(),
            "twelve AI specialist",
            "expert_registry_path",
        ),
        (
            ATLAS_PATH,
            "atlas.json",
            lambda payload: payload.update(registry_version="9.0.0"),
            "Capability atlas contract",
            "capability_atlas_path",
        ),
    ],
)
def test_program_rejects_source_contract_drift(
    tmp_path: Path,
    source_path: Path,
    name: str,
    mutate,
    match: str,
    argument: str,
):
    path = _mutated(source_path, tmp_path, name, mutate)

    with pytest.raises(EnterpriseAiErpProgramError, match=match):
        EnterpriseAiErpProgram(**{argument: path})


def test_program_rejects_team_and_expert_specialist_reference_drift(tmp_path: Path):
    def mutate(payload):
        payload["organization_model"]["ai_specialist_role_refs"][0] = "unknown_specialist"

    path = _mutated(TEAM_PATH, tmp_path, "team.json", mutate)
    with pytest.raises(EnterpriseAiErpProgramError, match="specialist references drift"):
        EnterpriseAiErpProgram(organization_registry_path=path)


def test_program_rejects_control_role_order_drift(tmp_path: Path):
    def mutate(payload):
        payload["control_role_refs"].reverse()

    with pytest.raises(EnterpriseAiErpProgramError, match="control role contract drift"):
        _program(tmp_path, mutate)


def test_equivalent_json_key_order_has_identical_registry_and_snapshot_hashes(
    tmp_path: Path,
):
    baseline = EnterpriseAiErpProgram()
    payload = _payload(PROGRAM_PATH)
    reordered = dict(reversed(list(payload.items())))
    path = tmp_path / "reordered.json"
    path.write_text(json.dumps(reordered, ensure_ascii=False, indent=4), encoding="utf-8")
    changed_format = EnterpriseAiErpProgram(path)

    assert baseline.registry_sha256 == changed_format.registry_sha256
    assert baseline.project()["snapshot_sha256"] == changed_format.project()["snapshot_sha256"]


def test_semantic_program_change_changes_registry_and_snapshot_hashes(tmp_path: Path):
    baseline = EnterpriseAiErpProgram()

    changed = _program(
        tmp_path,
        lambda payload: payload["role_contracts"][0].update(
            title="Enterprise Ontology and MDM Lead"
        ),
    )

    assert baseline.registry_sha256 != changed.registry_sha256
    assert baseline.project()["snapshot_sha256"] != changed.project()["snapshot_sha256"]


def test_semantic_upstream_change_changes_source_bundle_and_snapshot_hashes(
    tmp_path: Path,
):
    baseline = EnterpriseAiErpProgram()

    def mutate(payload):
        payload["organization_model"]["core_roles"][0]["title"] = "Updated title"

    path = _mutated(TEAM_PATH, tmp_path, "team.json", mutate)
    changed = EnterpriseAiErpProgram(organization_registry_path=path)

    assert baseline.source_bundle_sha256 != changed.source_bundle_sha256
    assert baseline.project()["snapshot_sha256"] != changed.project()["snapshot_sha256"]
