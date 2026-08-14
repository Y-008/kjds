from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.control_plane.api import app
from apps.control_plane.api_contracts import EnterprisePositioningOutput
from apps.control_plane.enterprise_positioning import EnterprisePositioningAdvisor
from apps.control_plane.runtime import runtime
from apps.control_plane.security import AuthenticationFailure, Principal

HEADERS = {"X-KJDS-API-Key": "test-key"}


def _principal(*roles: str) -> Principal:
    return Principal(
        actor_id="enterprise-positioning-test",
        roles=frozenset(roles),
        tenant_ref="enterprise-test",
    )


def _authenticate(monkeypatch, *roles: str) -> TestClient:
    principal = _principal(*roles)
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    return TestClient(app)


def _resign_snapshot(payload: dict) -> None:
    projection = {key: value for key, value in payload.items() if key != "snapshot_sha256"}
    canonical = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["snapshot_sha256"] = hashlib.sha256(canonical).hexdigest()


def test_current_enterprise_positioning_is_authenticated_and_read_only(monkeypatch) -> None:
    client = _authenticate(monkeypatch, "operator")

    response = client.get(
        "/v1/enterprise-positioning/current",
        headers=HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "RECOMMENDATION_ONLY"
    assert payload["enterprise_profile"]["enterprise_ref"] == "kjds"
    assert payload["role_summary"] == {
        "catalog_total": 35,
        "required_now": 12,
        "supporting_ai": 9,
        "on_demand": 9,
        "standby": 5,
        "unsupported_gap": 0,
        "core": 18,
        "ai_specialist": 12,
        "independent_control": 5,
    }
    assert len(payload["role_roster"]) == 35
    assert len(payload["seat_plan"]) == 4
    assert payload["profile_scope"]["grants_authority"] is False
    assert payload["next_role_activation"]["role_ref"] == (
        "russia_ozon_general_manager"
    )
    assert payload["system_actions"] == {
        "identities_created": False,
        "agents_created": False,
        "humans_appointed": False,
        "appointments_created": False,
        "roles_bound": False,
        "tasks_started": False,
        "budgets_created": False,
        "approvals_created": False,
        "permits_issued": False,
        "production_authority_granted": False,
        "facts_promoted": False,
        "external_write_performed": False,
    }


def test_recommendation_accepts_profile_without_write_gate_or_side_effect(monkeypatch) -> None:
    client = _authenticate(monkeypatch, "reviewer")
    write_gate_calls = []
    current_before = client.get(
        "/v1/enterprise-positioning/current",
        headers=HEADERS,
    ).json()

    def fail_if_write_gate_called() -> None:
        write_gate_calls.append(True)
        raise AssertionError("read-only recommendation must not enter the write gate")

    monkeypatch.setattr(
        runtime.kill_switch,
        "ensure_writes_allowed",
        fail_if_write_gate_called,
    )
    response = client.post(
        "/v1/enterprise-positioning/recommend",
        headers=HEADERS,
        json={
            "enterprise_ref": "acme-cn",
            "business_model": "commerce_control_plane_provider",
            "stage": "scale",
            "headcount_band": "medium",
            "markets": ["cn"],
            "platforms": ["amazon"],
            "risk_class": "regulated",
            "primary_objective": "multi_market_scale",
        },
    )

    assert response.status_code == 200
    assert write_gate_calls == []
    payload = response.json()
    assert payload["enterprise_profile"]["markets"] == ["CN"]
    assert payload["enterprise_profile"]["platforms"] == ["amazon"]
    assert payload["enterprise_positioning"]["archetype_ref"] == "multi_market_scale_company"
    assert payload["role_summary"] == {
        "catalog_total": 35,
        "required_now": 21,
        "supporting_ai": 12,
        "on_demand": 0,
        "standby": 2,
        "unsupported_gap": 2,
        "core": 18,
        "ai_specialist": 12,
        "independent_control": 5,
    }
    assert payload["capacity_plan"] == {
        "headcount_band": "medium",
        "max_human_seats": 4,
        "planned_human_seats": 4,
        "max_parallel_workstreams": 6,
        "max_active_work_per_human": 2,
        "role_bundle_mode": "dedicated_role_bindings_preferred",
        "ai_templates_count_as_humans": False,
    }
    assert payload["role_gaps"] == [
        {
            "gap_ref": "country_general_manager:CN",
            "recommendation_status": "unsupported_gap",
            "reason_code": "market_specific_role_contract_missing",
            "authority_status": "UNKNOWN",
        },
        {
            "gap_ref": "channel_operations_lead:amazon",
            "recommendation_status": "unsupported_gap",
            "reason_code": "platform_specific_role_contract_missing",
            "authority_status": "UNKNOWN",
        },
    ]
    current_after = client.get(
        "/v1/enterprise-positioning/current",
        headers=HEADERS,
    ).json()
    assert current_after == current_before
    assert current_after["snapshot_sha256"] == (
        "e9b043c6052276de1b4da9a5fac11b5e7543f5d2ea73718b236724063e94085b"
    )


def test_enterprise_positioning_rejects_missing_auth_and_unapproved_role(monkeypatch) -> None:
    def reject(_key):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    client = TestClient(app)
    assert client.get("/v1/enterprise-positioning/current").status_code == 401

    client = _authenticate(monkeypatch, "executor")
    assert (
        client.get(
            "/v1/enterprise-positioning/current",
            headers=HEADERS,
        ).status_code
        == 403
    )


def test_enterprise_profile_contract_is_strict(monkeypatch) -> None:
    client = _authenticate(monkeypatch, "admin")
    response = client.post(
        "/v1/enterprise-positioning/recommend",
        headers=HEADERS,
        json={
            "enterprise_ref": "acme",
            "business_model": "merchant_operator",
            "stage": "validation",
            "headcount_band": "small",
            "markets": ["RU"],
            "platforms": ["ozon"],
            "risk_class": "standard",
            "primary_objective": "actual_cash_truth",
            "auto_appoint": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_enterprise_positioning_openapi_contract_is_explicit() -> None:
    schema = app.openapi()
    for path, method in (
        ("/v1/enterprise-positioning/current", "get"),
        ("/v1/enterprise-positioning/recommend", "post"),
    ):
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"KjdsApiKey": []}]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/EnterprisePositioningOutput"
        }


def test_enterprise_positioning_output_rejects_jointly_resigned_semantic_drift() -> None:
    canonical = EnterprisePositioningAdvisor().position()
    mutations = []

    summary_drift = deepcopy(canonical)
    summary_drift["role_summary"]["required_now"] += 1
    _resign_snapshot(summary_drift)
    mutations.append(summary_drift)

    source_drift = deepcopy(canonical)
    source_drift["source_hashes"]["team_control_tower"] = "0" * 64
    _resign_snapshot(source_drift)
    mutations.append(source_drift)

    sod_drift = deepcopy(canonical)
    sod_drift["separation_of_duties"][0]["right_function_ref"] = "self_verifier"
    _resign_snapshot(sod_drift)
    mutations.append(sod_drift)

    snapshot_drift = deepcopy(canonical)
    snapshot_drift["snapshot_sha256"] = "f" * 64
    mutations.append(snapshot_drift)

    for payload in mutations:
        with pytest.raises(ValidationError):
            EnterprisePositioningOutput.model_validate(payload)
