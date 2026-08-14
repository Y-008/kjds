from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.control_plane.api_contracts import current_principal
from apps.control_plane.routers import strategic_capital_dashboard as dashboard_router
from apps.control_plane.security import Principal
from apps.control_plane.strategic_capital_dashboard import (
    CurrentScopeAuthority,
    RuntimeCurrentScopeAuthority,
    StrategicCapitalDashboardService,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


class ScopeAuthority:
    def current(self, *, principal, store_ref, checked_at):
        assert checked_at == NOW
        return CurrentScopeAuthority(
            tenant_ref=principal.tenant_ref,
            entity_ref="entity-api",
            store_ref=store_ref,
            authority_sha256="a" * 64,
        )


def _principal() -> Principal:
    return Principal(
        actor_id="reviewer-api",
        roles=frozenset({"reviewer"}),
        tenant_ref="tenant-api",
        store_refs=frozenset({"store-api"}),
    )


def _client(
    monkeypatch,
    *,
    principal: Principal | None = None,
    scope_authority=None,
) -> TestClient:
    service = StrategicCapitalDashboardService(
        scope_authority=scope_authority or ScopeAuthority(),
        section_ports={},
        clock=lambda: NOW,
    )
    app = FastAPI()
    app.include_router(dashboard_router.router)
    active_principal = principal or _principal()
    app.dependency_overrides[current_principal] = lambda: active_principal
    monkeypatch.setattr(
        dashboard_router,
        "_runtime_services",
        lambda: SimpleNamespace(strategic_capital_dashboard=service),
    )
    return TestClient(app, raise_server_exceptions=False)


def test_single_get_returns_explicit_read_only_dashboard(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get(
        "/v1/strategic-capital-dashboard",
        params={"store_ref": "store-api", "as_of": NOW.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_state"] == "no_data"
    assert len(payload["sections"]) == 8
    assert all(section["status"] == "not_connected" for section in payload["sections"])
    assert payload["global_top1_claim"] is False
    assert payload["production_admission"] is False
    assert payload["budget_authority"] is False
    assert set(payload["side_effects"].values()) == {0}
    assert "tenant-api" not in response.text
    assert "entity-api" not in response.text


def test_dashboard_cross_scope_is_uniform_404(monkeypatch) -> None:
    response = _client(monkeypatch).get(
        "/v1/strategic-capital-dashboard",
        params={"store_ref": "other-store"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "'strategic dashboard not found'"}


def test_risk_only_role_is_rejected_before_upstream_reads(monkeypatch) -> None:
    response = _client(
        monkeypatch,
        principal=Principal(
            actor_id="risk-api",
            roles=frozenset({"risk"}),
            tenant_ref="tenant-api",
            store_refs=frozenset({"store-api"}),
        ),
    ).get("/v1/strategic-capital-dashboard", params={"store_ref": "store-api"})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "authority_result",
    [
        ValueError("private-authority-ambiguity"),
        RuntimeError("private-authority-integrity"),
        {
            "status": "ready",
            "tenant_ref": "tenant-api",
            "entity_ref": None,
            "store_ref": "store-api",
            "authority_sha256": "a" * 64,
        },
    ],
)
def test_authority_adapter_failure_is_uniform_404_without_details(
    monkeypatch, authority_result
) -> None:
    class Grants:
        @staticmethod
        def current(**_kwargs):
            if isinstance(authority_result, Exception):
                raise authority_result
            return authority_result

    response = _client(
        monkeypatch,
        scope_authority=RuntimeCurrentScopeAuthority(scope_grants=Grants()),
    ).get("/v1/strategic-capital-dashboard", params={"store_ref": "store-api"})

    assert response.status_code == 404
    assert "private-authority" not in response.text
    assert "tenant-api" not in response.text


def test_openapi_exposes_one_get_and_explicit_response(monkeypatch) -> None:
    schema = _client(monkeypatch).app.openapi()
    operation = schema["paths"]["/v1/strategic-capital-dashboard"]

    assert set(operation) == {"get"}
    response_schema = operation["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["$ref"].endswith("StrategicCapitalDashboardResponse")
    response_model = schema["components"]["schemas"][
        "StrategicCapitalDashboardResponse"
    ]
    assert response_model["additionalProperties"] is False
    assert "sections" in response_model["required"]
    section_items = response_model["properties"]["sections"]["items"]
    assert len(section_items["oneOf"]) == 3
    assert section_items["discriminator"]["propertyName"] == "status"


def test_response_model_rejects_status_payload_scope_and_order_drift(
    monkeypatch,
) -> None:
    payload = _client(monkeypatch).get(
        "/v1/strategic-capital-dashboard",
        params={"store_ref": "store-api", "as_of": NOW.isoformat()},
    ).json()
    mutations = []

    ready_without_projection = deepcopy(payload)
    ready_without_projection["sections"][0]["status"] = "ready"
    mutations.append(ready_without_projection)

    unavailable_with_projection = deepcopy(payload)
    unavailable_with_projection["sections"][0]["display_items"] = [
        {"item_ref": "leak", "label": "leak", "display_text": "leak"}
    ]
    mutations.append(unavailable_with_projection)

    cross_scope = deepcopy(payload)
    cross_scope["sections"][0]["scope_binding_sha256"] = "b" * 64
    mutations.append(cross_scope)

    wrong_order = deepcopy(payload)
    wrong_order["sections"][0], wrong_order["sections"][1] = (
        wrong_order["sections"][1],
        wrong_order["sections"][0],
    )
    mutations.append(wrong_order)

    for mutation in mutations:
        with pytest.raises(ValidationError):
            dashboard_router.StrategicCapitalDashboardResponse.model_validate(
                mutation
            )


@pytest.mark.parametrize("token", ["evd_raw-uuid", "123e4567-e89b-12d3-a456-426614174000"])
def test_response_model_rejects_raw_or_unscoped_citation_tokens(token: str) -> None:
    with pytest.raises(ValidationError):
        dashboard_router.DashboardCitationResponse.model_validate(
            {"token": token, "summary_sha256": "a" * 64}
        )
