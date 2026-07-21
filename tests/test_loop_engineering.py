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
