from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from apps.control_plane.api import registered_routes
from apps.control_plane.data_fabric_contracts import ScopeRef
from apps.control_plane.routers import control_loop
from apps.control_plane.security import Principal

SCOPE = ScopeRef(tenant_id="tenant-a", entity_id="entity-a", store_ids=("store-a",))
ACTOR = Principal(
    actor_id="operator-a",
    roles=frozenset({"operator"}),
    tenant_ref="tenant-a",
    store_refs=frozenset({"store-a"}),
)
WHEN = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)


class _Repo:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def events_after(self, sequence: int):
        return [item for item in self.events if int(item.get("sequence", 0)) > sequence]

    def append_event(self, event_type, aggregate_id, payload, *, actor_id, source_evidence_id=None):
        self.events.append(
            {
                "sequence": len(self.events) + 1,
                "type": event_type,
                "aggregate_id": aggregate_id,
                "payload": payload,
                "actor_id": actor_id,
                "source_evidence_id": source_evidence_id,
            }
        )


def _objective(**overrides):
    values = {
        "objective_id": "obj-cm3",
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
    return control_loop.ObjectiveRequest(**values)


def _observation(**overrides):
    values = {
        "objective_id": "obj-cm3",
        "scope": SCOPE,
        "snapshot_sha256": "a" * 64,
        "observed_value": "80",
        "quality_state": "VALID",
        "observed_at": WHEN,
        "evidence_refs": ("ev-cm3-1",),
    }
    values.update(overrides)
    return control_loop.ObservationRequest(**values)


def test_control_loop_routes_are_registered():
    paths = {route.path for route in registered_routes()}
    assert "/v1/control-loop/objectives/evaluate" in paths
    assert "/v1/control-loop/metrics/compile" in paths
    assert "/v1/control-loop/decisions" in paths
    assert "/v1/control-loop/status" in paths


def test_objective_evaluation_is_scoped_and_proposal_only():
    result = control_loop.evaluate_control_loop(
        control_loop.EvaluateRequest(
            objective=_objective(),
            observation=_observation(),
        ),
        principal=ACTOR,
    )
    assert result["status"] == "PROPOSED"
    assert result["decision"]["action"] == "increase"
    assert result["decision"]["external_write_allowed"] is False
    assert result["execution"] == "proposal_only"

    with pytest.raises(HTTPException) as caught:
        control_loop.evaluate_control_loop(
            control_loop.EvaluateRequest(
                objective=_objective(scope=ScopeRef(tenant_id="other", entity_id="entity-a", store_ids=("store-a",))),
                observation=_observation(),
            ),
            principal=ACTOR,
        )
    assert caught.value.status_code == 403


def test_metric_compile_returns_versioned_read_only_plan():
    result = control_loop.compile_control_metric(
        control_loop.MetricRecipeRequest(
            recipe_id="cm3-dashboard",
            scope=SCOPE,
            metric_id="cm3",
            metric_version="1",
            dimensions=("store", "sku"),
            currency="CNY",
        ),
        principal=ACTOR,
    )
    assert result["status"] == "COMPILED"
    assert result["execution"] == "read_only"
    assert result["source_dataset"] == "profit.cm3.v1"
    assert len(result["plan_hash"]) == 64
    assert result["external_write_allowed"] is False


def test_decision_append_is_idempotent_and_persisted(monkeypatch):
    repository = _Repo()
    monkeypatch.setattr(control_loop.runtime, "repo", repository)
    key = "control-loop-api-test-unique"
    body = control_loop.DecisionAppendRequest(
        event_type="decision_proposed",
        decision_id="decision-api-1",
        scope=SCOPE,
        payload={"action": "increase", "delta": "5", "evidence_refs": ["ev-1"]},
        idempotency_key=key,
        occurred_at=WHEN,
    )
    first = control_loop.append_control_decision(body, principal=ACTOR)
    retry = control_loop.append_control_decision(body.model_copy(update={"occurred_at": None}), principal=ACTOR)
    assert first["status"] == "recorded"
    assert retry["status"] == "replayed"
    assert first["event"] == retry["event"]
    assert len(repository.events) == 1
    assert first["external_write_allowed"] is False

    with pytest.raises(HTTPException) as caught:
        control_loop.append_control_decision(
            body.model_copy(update={"payload": {"action": "decrease"}}),
            principal=ACTOR,
        )
    assert caught.value.status_code == 409


def test_decision_payload_rejects_authority_fields():
    with pytest.raises(HTTPException) as caught:
        control_loop.append_control_decision(
            control_loop.DecisionAppendRequest(
                event_type="decision_proposed",
                decision_id="decision-api-secret",
                scope=SCOPE,
                payload={"permit": "should-never-be-here"},
                idempotency_key="control-loop-secret-test",
                occurred_at=WHEN,
            ),
            principal=ACTOR,
        )
    assert caught.value.status_code == 422
    assert "not allowed" in str(caught.value.detail)
