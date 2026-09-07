from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.control_plane.data_fabric_contracts import ScopeRef
from apps.control_plane.objective_control_loop import (
    MetricObservation,
    ObjectiveControlLoopError,
    ObjectiveDefinition,
    evaluate_objective,
)

SCOPE = ScopeRef(tenant_id="tenant-a", entity_id="entity-a", store_ids=("store-a",))
NOW = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)


def objective(**overrides):
    values = {
        "objective_id": "obj-profit",
        "scope": SCOPE,
        "metric_id": "cm3",
        "direction": "maximize",
        "target": "100",
        "cadence": "medium",
        "max_change": "20",
        "hysteresis": "2",
        "owner": "pm",
        "rollback_rule": "restore-last-approved",
    }
    values.update(overrides)
    return ObjectiveDefinition(**values)


def observation(**overrides):
    values = {
        "objective_id": "obj-profit",
        "scope": SCOPE,
        "snapshot_sha256": "a" * 64,
        "observed_value": "80",
        "quality_state": "VALID",
        "observed_at": NOW,
        "evidence_refs": ("ev-1",),
    }
    values.update(overrides)
    return MetricObservation(**values)


def test_proposes_bounded_change_and_is_deterministic():
    first = evaluate_objective(objective(), observation())
    second = evaluate_objective(objective(), observation())
    assert first.status == "PROPOSED"
    assert first.action == "increase"
    assert first.delta == Decimal("20")
    assert first.external_write_allowed is False
    assert first.decision_hash == second.decision_hash


def test_target_reached_stops_and_quality_can_hold():
    stopped = evaluate_objective(objective(), observation(observed_value="99"))
    held = evaluate_objective(objective(), observation(quality_state="STALE"))
    assert (stopped.status, stopped.action, stopped.reason) == ("STOPPED", "stop", "target_reached_within_hysteresis")
    assert (held.status, held.action) == ("HOLD", "hold")
    assert held.delta == 0


def test_cooldown_and_safety_event_are_explicit():
    previous = evaluate_objective(objective(), observation(snapshot_sha256="b" * 64))
    current = observation(snapshot_sha256="c" * 64, observed_at=NOW + timedelta(minutes=5))
    assert evaluate_objective(objective(), current, previous=previous).reason == "cooldown_active"
    urgent = evaluate_objective(objective(), current.model_copy(update={"safety_event": True}), previous=previous)
    assert urgent.status == "PROPOSED"


def test_scope_and_objective_mismatch_fail_closed():
    with pytest.raises(ObjectiveControlLoopError):
        evaluate_objective(objective(), observation(objective_id="other"))
    with pytest.raises(ObjectiveControlLoopError):
        evaluate_objective(objective(), observation(scope=ScopeRef(tenant_id="tenant-a", entity_id="entity-a", store_ids=("store-b",))))


def test_quality_invalid_stop_rule_stops():
    result = evaluate_objective(objective(stop_rule="quality_invalid"), observation(quality_state="UNKNOWN_OUTCOME"))
    assert (result.status, result.action, result.reason) == ("STOPPED", "stop", "quality_invalid")
