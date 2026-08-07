import json

import pytest

from apps.control_plane.loop_engineering import (
    LOOP_MODULES,
    LoopEngineeringService,
    LoopRegistryError,
)


def test_loop_contract_reports_missing_controls_and_blocks_active_mode():
    service = LoopEngineeringService()

    incomplete = service.validate(
        module="automations",
        mode="shadow",
        controls={"run_id": "run-1"},
    )
    assert incomplete.allowed is False
    assert incomplete.status == "missing_controls"
    assert "evidence_id" in incomplete.missing_controls

    complete = service.validate(
        module="automations",
        mode="active",
        controls={
            "idempotency_key": "batch-1",
            "timeout": 30,
            "retry_limit": 0,
            "kill_switch": False,
            "run_id": "run-1",
            "evidence_id": "evd-1",
        },
    )
    assert complete.allowed is False
    assert complete.status == "promotion_gate_required"
    assert complete.missing_controls == ()


def test_loop_registry_snapshot_is_canonical_and_detached():
    service = LoopEngineeringService()
    snapshot = service.registry_snapshot()

    assert tuple(module["id"] for module in snapshot["modules"]) == LOOP_MODULES
    snapshot["modules"][0]["state"] = "ready"
    assert service.registry_snapshot()["modules"][0]["state"] == "partial"


def test_loop_contract_rejects_unknown_module():
    service = LoopEngineeringService()
    with pytest.raises(LoopRegistryError, match="Unknown loop module"):
        service.validate(module="unknown", mode="proposal", controls={})


def test_loop_contract_rejects_global_expert_leader_authority_drift(tmp_path):
    source = LoopEngineeringService().registry_snapshot()
    source["team_agent_contract"]["leader_authority"] = "single_actor_all_authority"
    path = tmp_path / "loop-registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(LoopRegistryError, match="operating contract drift"):
        LoopEngineeringService(path)


@pytest.mark.parametrize(
    "mutation",
    ("add_skip", "drop_gate", "duplicate", "terminal_escape"),
)
def test_evolution_transition_set_is_frozen(tmp_path, mutation):
    source = LoopEngineeringService().registry_snapshot()
    transitions = source["evolution_loop"]["allowed_transitions"]
    if mutation == "add_skip":
        transitions.append("skill_candidate->active")
    elif mutation == "drop_gate":
        transitions.remove("shadow->independent_review")
    elif mutation == "duplicate":
        transitions.append(transitions[0])
    else:
        transitions.append("retired->active")
    path = tmp_path / "loop-registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(
        LoopRegistryError,
        match="transitions do not match the frozen contract",
    ):
        LoopEngineeringService(path)
