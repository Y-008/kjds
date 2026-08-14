from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.control_plane.api import app, is_write_safety_control_path
from apps.control_plane.api_contracts import (
    TeamControlAdvanceInput,
    TeamControlBriefOutput,
)
from apps.control_plane.routers import system
from apps.control_plane.security import Principal

ENTERPRISE_PROJECTION_KEYS = (
    "squad_readiness",
    "role_conflicts",
    "parallel_execution",
    "integration_queue",
    "capacity_risk",
    "next_release_train",
)


def _unknown_projection(name: str) -> dict:
    return {
        "projection": name,
        "status": "UNKNOWN",
        "reason_codes": ["exact_scope_authority_unavailable"],
        "source_refs": [],
        "as_of": "2026-08-08T00:00:00+00:00",
        "projection_sha256": "a" * 64,
    }


def _scope_invalid_brief() -> dict:
    projection = _unknown_projection("organization_readiness")
    return {
        "contract_id": "kjds-team-control-tower-v1",
        "contract_version": "1.3.0",
        "status": "scope_invalid",
        "headline": "exact scope unavailable",
        "scope": None,
        "as_of": "2026-08-08T00:00:00+00:00",
        "executive_summary": {},
        "next_action": None,
        "flows": [],
        "conflicts": [],
        "organization_readiness": projection,
        "critical_path": {**projection, "projection": "critical_path"},
        "top1_scorecard": {**projection, "projection": "top1_scorecard"},
        "cash_at_risk": {**projection, "projection": "cash_at_risk"},
        "delivery_gate": {**projection, "projection": "delivery_gate"},
        **{name: _unknown_projection(name) for name in ENTERPRISE_PROJECTION_KEYS},
        "decision_basis_sha256": None,
        "source_refs": [],
        "control_envelope": {"external_write_allowed": False},
        "snapshot_sha256": "b" * 64,
    }


class FakeScopeGrants:
    def __init__(self) -> None:
        self.current_calls = []

    def current(self, *, principal, store_ref, as_of):
        self.current_calls.append(
            {"principal": principal, "store_ref": store_ref, "as_of": as_of}
        )
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": "entity-cn-1",
            "store_ref": store_ref,
            "authority_sha256": "a" * 64,
            "as_of": as_of.isoformat(),
        }


class RevokedScopeGrants(FakeScopeGrants):
    def __init__(self, *, revoked_at: datetime) -> None:
        super().__init__()
        self.revoked_at = revoked_at

    def current(self, *, principal, store_ref, as_of):
        self.current_calls.append(
            {"principal": principal, "store_ref": store_ref, "as_of": as_of}
        )
        if as_of < self.revoked_at:
            return {
                "status": "ready",
                "tenant_ref": principal.tenant_ref,
                "entity_ref": "entity-cn-1",
                "store_ref": store_ref,
                "authority_sha256": "a" * 64,
                "as_of": as_of.isoformat(),
            }
        return {
            "status": "no_data",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": None,
            "store_ref": store_ref,
            "authority_sha256": "b" * 64,
            "reason": "entity_scope_authority_missing",
        }


class RotatedScopeGrants(FakeScopeGrants):
    OLD_AUTHORITY_SHA256 = "c" * 64
    NEW_AUTHORITY_SHA256 = "d" * 64

    def __init__(self, *, rotated_at: datetime) -> None:
        super().__init__()
        self.rotated_at = rotated_at

    def current(self, *, principal, store_ref, as_of):
        self.current_calls.append(
            {"principal": principal, "store_ref": store_ref, "as_of": as_of}
        )
        if as_of < self.rotated_at:
            return {
                "status": "ready",
                "tenant_ref": principal.tenant_ref,
                "entity_ref": "entity-old-1",
                "store_ref": store_ref,
                "authority_sha256": self.OLD_AUTHORITY_SHA256,
                "as_of": as_of.isoformat(),
            }
        return {
            "status": "blocked",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": None,
            "store_ref": store_ref,
            "authority_sha256": self.NEW_AUTHORITY_SHA256,
            "rejected_authority_sha256": self.OLD_AUTHORITY_SHA256,
            "reason": "entity_scope_authority_rotated",
        }


class FakeTower:
    def __init__(self) -> None:
        self.brief_calls = []
        self.advance_calls = []
        self.business_adapter_reads = 0

    def brief(self, **values):
        self.brief_calls.append(values)
        if values["entity_scope"].get("status") != "ready":
            return {"status": "scope_invalid", "next_action": None}
        self.business_adapter_reads += 1
        return {"status": "attention_required", "next_action": {"continuation": "b" * 64}}

    def advance(self, **values):
        self.advance_calls.append(values)
        return {"outcome": "accepted", "external_write_allowed": False}


def principal(*roles: str) -> Principal:
    return Principal(
        actor_id="actor-1",
        roles=frozenset(roles),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"ozon-primary"}),
    )


def test_team_control_openapi_has_only_brief_and_advance_interfaces():
    paths = app.openapi()["paths"]

    assert set(paths["/v1/team-control/brief"]) == {"get"}
    assert set(paths["/v1/team-control/advance"]) == {"post"}
    assert paths["/v1/team-control/brief"]["get"]["security"]
    assert paths["/v1/team-control/advance"]["post"]["security"]
    schema_ref = paths["/v1/team-control/advance"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    schema_name = schema_ref.rsplit("/", 1)[-1]
    fields = set(app.openapi()["components"]["schemas"][schema_name]["properties"])
    assert fields == {
        "continuation",
        "result",
        "rationale",
        "evidence_ids",
        "idempotency_key",
    }
    assert not fields.intersection(
        {"tenant_ref", "entity_ref", "scope_authority_sha256", "actor_id", "credential"}
    )
    assert is_write_safety_control_path("/v1/team-control/advance") is False

    brief_schema_ref = paths["/v1/team-control/brief"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    brief_schema_name = brief_schema_ref.rsplit("/", 1)[-1]
    assert brief_schema_name == "TeamControlBriefOutput"
    brief_schema = app.openapi()["components"]["schemas"][brief_schema_name]
    assert brief_schema["additionalProperties"] is False
    assert set(ENTERPRISE_PROJECTION_KEYS).issubset(brief_schema["required"])
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["TeamControlUnavailableSquadReadiness"]["properties"]["status"][
        "const"
    ] == "UNKNOWN"
    assert schemas["TeamControlCapacityRisk"]["properties"][
        "capacity_proven_available"
    ]["const"] is False
    assert schemas["TeamControlNextReleaseTrain"]["properties"]["gate_status"][
        "const"
    ] == "UNKNOWN"
    assert schemas["TeamControlNextReleaseTrain"]["properties"][
        "registry_proves_schedule"
    ]["const"] is False


def test_team_control_brief_contract_accepts_minimal_unknown_and_fails_closed():
    brief = _scope_invalid_brief()

    validated = TeamControlBriefOutput.model_validate(brief).model_dump()

    assert validated["status"] == "scope_invalid"
    assert all(validated[name]["status"] == "UNKNOWN" for name in ENTERPRISE_PROJECTION_KEYS)
    assert all(validated[name]["program_contract"] is None for name in ENTERPRISE_PROJECTION_KEYS)

    missing = dict(brief)
    missing.pop("capacity_risk")
    with pytest.raises(ValidationError):
        TeamControlBriefOutput.model_validate(missing)

    wrong_projection = _scope_invalid_brief()
    wrong_projection["capacity_risk"] = _unknown_projection("role_conflicts")
    with pytest.raises(ValidationError):
        TeamControlBriefOutput.model_validate(wrong_projection)

    extra = _scope_invalid_brief()
    extra["client_computed_gate"] = "PASS"
    with pytest.raises(ValidationError):
        TeamControlBriefOutput.model_validate(extra)

    promoted = _scope_invalid_brief()
    promoted["squad_readiness"]["status"] = "VERIFIED"
    with pytest.raises(ValidationError):
        TeamControlBriefOutput.model_validate(promoted)


def test_team_control_brief_contract_preserves_unknown_capacity_observations():
    brief = _scope_invalid_brief()
    brief["capacity_risk"] = {
        "projection": "capacity_risk",
        "status": "UNKNOWN",
        "limits": {
            "control_agent_count": 1,
            "max_parallel_specialist_agents": 3,
            "max_active_writers": 3,
            "max_active_tasks_per_specialist": 1,
            "max_active_tasks_per_writer": 1,
            "max_current_tasks_per_lane": 1,
            "max_weekly_company_outcomes": 3,
        },
        "observed_active_writers": None,
        "observed_specialist_wip": None,
        "observed_lane_wip": None,
        "observed_weekly_company_outcomes": None,
        "capacity_proven_available": False,
        "program_contract": {
            "contract_id": "kjds-enterprise-ai-erp-program-v1",
            "contract_version": "1.0.0",
            "program_snapshot_sha256": "c" * 64,
            "registry_sha256": "d" * 64,
            "source_bundle_sha256": "e" * 64,
            "static_contract_integrity": "VERIFIED",
            "runtime_authority_connected": False,
        },
        "reason_codes": ["runtime_work_authority_not_connected"],
        "source_refs": [
            {"ref": "enterprise_ai_erp_program_registry", "sha256": "d" * 64}
        ],
        "as_of": "2026-08-08T00:00:00+00:00",
        "projection_sha256": "f" * 64,
    }

    capacity = TeamControlBriefOutput.model_validate(brief).model_dump()[
        "capacity_risk"
    ]

    assert capacity["status"] == "UNKNOWN"
    assert capacity["capacity_proven_available"] is False
    assert capacity["observed_active_writers"] is None

    brief["capacity_risk"]["capacity_proven_available"] = True
    with pytest.raises(ValidationError):
        TeamControlBriefOutput.model_validate(brief)


def test_team_control_brief_contract_rejects_release_truth_without_authority():
    brief = _scope_invalid_brief()
    brief["next_release_train"] = {
        "projection": "next_release_train",
        "status": "UNKNOWN",
        "release_trains_per_week": 2,
        "scheduled_at": None,
        "eligible_work_item_refs": None,
        "gate_status": "UNKNOWN",
        "registry_proves_schedule": False,
        "program_contract": {
            "contract_id": "kjds-enterprise-ai-erp-program-v1",
            "contract_version": "1.0.0",
            "program_snapshot_sha256": "c" * 64,
            "registry_sha256": "d" * 64,
            "source_bundle_sha256": "e" * 64,
            "static_contract_integrity": "VERIFIED",
            "runtime_authority_connected": False,
        },
        "reason_codes": ["release_authority_not_connected"],
        "source_refs": [
            {"ref": "enterprise_ai_erp_program_registry", "sha256": "d" * 64}
        ],
        "as_of": "2026-08-08T00:00:00+00:00",
        "projection_sha256": "f" * 64,
    }

    TeamControlBriefOutput.model_validate(brief)

    brief["next_release_train"]["gate_status"] = "VERIFIED"
    with pytest.raises(ValidationError):
        TeamControlBriefOutput.model_validate(brief)

    brief["next_release_train"]["gate_status"] = "UNKNOWN"
    brief["next_release_train"]["registry_proves_schedule"] = True
    with pytest.raises(ValidationError):
        TeamControlBriefOutput.model_validate(brief)


def test_monitor_reads_brief_but_only_operator_or_admin_advances(monkeypatch):
    scope_grants = FakeScopeGrants()
    tower = FakeTower()
    monkeypatch.setattr(system.runtime, "scope_grants", scope_grants)
    monkeypatch.setattr(system.runtime, "team_control_tower", tower)

    checked_before = datetime.now(UTC)
    brief = system.team_control_brief(principal=principal("monitor"))
    body = TeamControlAdvanceInput(
        continuation="b" * 64,
        result="take",
        rationale="领取唯一下一动作",
        idempotency_key="advance-1",
    )
    accepted = system.advance_team_control(body=body, principal=principal("operator"))
    checked_after = datetime.now(UTC)

    assert brief["status"] == "attention_required"
    assert accepted == {"outcome": "accepted", "external_write_allowed": False}
    assert tower.brief_calls[0]["principal"].actor_id == "actor-1"
    assert tower.advance_calls[0]["idempotency_key"] == "advance-1"
    assert len(scope_grants.current_calls) == 2
    assert all(
        checked_before <= call["as_of"] <= checked_after
        for call in scope_grants.current_calls
    )
    assert tower.brief_calls[0]["as_of"] == scope_grants.current_calls[0]["as_of"]
    assert tower.advance_calls[0]["as_of"] == scope_grants.current_calls[1]["as_of"]
    with pytest.raises(HTTPException) as error:
        system.advance_team_control(body=body, principal=principal("reviewer"))
    assert error.value.status_code == 403


def test_historical_brief_cutoff_cannot_rewind_revoked_scope(monkeypatch):
    checked_before = datetime.now(UTC)
    historical_cutoff = checked_before - timedelta(days=2)
    scope_grants = RevokedScopeGrants(
        revoked_at=checked_before - timedelta(days=1),
    )
    tower = FakeTower()
    monkeypatch.setattr(system.runtime, "scope_grants", scope_grants)
    monkeypatch.setattr(system.runtime, "team_control_tower", tower)

    result = system.team_control_brief(
        principal=principal("monitor"),
        as_of=historical_cutoff.isoformat(),
    )
    checked_after = datetime.now(UTC)

    assert result == {"status": "scope_invalid", "next_action": None}
    assert len(scope_grants.current_calls) == 1
    authority_checked_at = scope_grants.current_calls[0]["as_of"]
    assert checked_before <= authority_checked_at <= checked_after
    assert authority_checked_at > scope_grants.revoked_at
    assert len(tower.brief_calls) == 1
    assert tower.brief_calls[0]["as_of"] == historical_cutoff
    assert tower.brief_calls[0]["entity_scope"]["status"] == "no_data"
    assert tower.business_adapter_reads == 0


def test_historical_brief_cutoff_cannot_restore_rotated_authority(monkeypatch):
    checked_before = datetime.now(UTC)
    historical_cutoff = checked_before - timedelta(days=2)
    scope_grants = RotatedScopeGrants(
        rotated_at=checked_before - timedelta(days=1),
    )
    tower = FakeTower()
    monkeypatch.setattr(system.runtime, "scope_grants", scope_grants)
    monkeypatch.setattr(system.runtime, "team_control_tower", tower)

    result = system.team_control_brief(
        principal=principal("monitor"),
        as_of=historical_cutoff.isoformat(),
    )
    checked_after = datetime.now(UTC)

    assert result == {"status": "scope_invalid", "next_action": None}
    assert len(scope_grants.current_calls) == 1
    authority_checked_at = scope_grants.current_calls[0]["as_of"]
    assert checked_before <= authority_checked_at <= checked_after
    assert authority_checked_at > scope_grants.rotated_at
    assert len(tower.brief_calls) == 1
    assert tower.brief_calls[0]["as_of"] == historical_cutoff
    current_scope = tower.brief_calls[0]["entity_scope"]
    assert current_scope["status"] == "blocked"
    assert current_scope["authority_sha256"] == scope_grants.NEW_AUTHORITY_SHA256
    assert (
        current_scope["rejected_authority_sha256"]
        == scope_grants.OLD_AUTHORITY_SHA256
    )
    assert current_scope["authority_sha256"] != scope_grants.OLD_AUTHORITY_SHA256
    assert tower.business_adapter_reads == 0
