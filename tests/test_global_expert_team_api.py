from __future__ import annotations

import pytest
from fastapi import HTTPException

from apps.control_plane.api import app, is_write_safety_control_path
from apps.control_plane.api_contracts import GlobalExpertTaskRouteInput
from apps.control_plane.routers.system import (
    global_expert_team_registry,
    route_global_expert_task,
)
from apps.control_plane.security import Principal


def test_global_expert_team_openapi_is_authenticated_and_proposal_only():
    paths = app.openapi()["paths"]

    assert set(paths["/v1/global-expert-team/registry"]) == {"get"}
    assert set(paths["/v1/global-expert-team/route"]) == {"post"}
    assert is_write_safety_control_path("/v1/global-expert-team/route") is True
    assert paths["/v1/global-expert-team/registry"]["get"]["security"]
    assert paths["/v1/global-expert-team/route"]["post"]["security"]
    schema_ref = paths["/v1/global-expert-team/route"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    schema_name = schema_ref.rsplit("/", 1)[-1]
    fields = set(app.openapi()["components"]["schemas"][schema_name]["properties"])
    assert fields == {
        "task_ref",
        "task_type",
        "market",
        "platform",
        "risk_level",
        "evidence_refs",
    }
    assert not fields.intersection(
        {"credential", "api_key", "cookie", "tenant_ref", "entity_ref", "actor_id"}
    )


def test_operator_can_compile_a_global_research_route():
    result = route_global_expert_task(
        body=GlobalExpertTaskRouteInput(
            task_ref="api-global-research-001",
            task_type="market_research",
            market="GLOBAL",
            platform="all",
            risk_level="L0",
        ),
        principal=Principal(
            actor_id="operator-1",
            roles=frozenset({"operator"}),
            tenant_ref="tenant-a",
            store_refs=frozenset({"ozon-primary"}),
        ),
    )

    assert result["status"] == "proposal_routable"
    assert result["control_envelope"]["external_write_allowed"] is False


def test_monitor_can_read_registry_but_cannot_compile_routes():
    principal = Principal(
        actor_id="monitor-1",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )

    assert global_expert_team_registry(principal=principal)["counts"]["specialists"] == 12
    with pytest.raises(HTTPException) as error:
        route_global_expert_task(
            body=GlobalExpertTaskRouteInput(
                task_ref="api-global-research-002",
                task_type="market_research",
                market="GLOBAL",
                platform="all",
                risk_level="L0",
            ),
            principal=principal,
        )
    assert error.value.status_code == 403
