import inspect
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.security import (
    ApiKeyAuthenticator,
    AuthenticationFailure,
    KillSwitchService,
    WritesDisabled,
    credential_profile,
)
from apps.control_plane.sql_repository import Base


def test_api_key_identity_and_roles_are_derived_from_configuration(monkeypatch):
    monkeypatch.delenv("KJDS_API_KEY", raising=False)
    monkeypatch.setenv(
        "KJDS_API_KEYS_JSON",
        json.dumps({"request-key": credential_profile("operator-1", ["operator"])}),
    )
    authenticator = ApiKeyAuthenticator.from_environment()

    principal = authenticator.authenticate("request-key")
    assert principal.actor_id == "operator-1"
    assert principal.roles == {"operator"}

    with pytest.raises(AuthenticationFailure) as missing:
        authenticator.authenticate(None)
    assert missing.value.status_code == 401

    with pytest.raises(AuthenticationFailure) as invalid:
        authenticator.authenticate("wrong-key")
    assert invalid.value.status_code == 403


def test_dedicated_worker_identities_keep_minimum_roles(monkeypatch):
    monkeypatch.delenv("KJDS_API_KEY", raising=False)
    monkeypatch.setenv(
        "KJDS_API_KEYS_JSON",
        json.dumps(
            {
                "pilot-key": credential_profile("ozon-read-worker", ["pilot_reader"]),
                "executor-key": credential_profile("ozon-worker", ["executor"]),
            }
        ),
    )
    authenticator = ApiKeyAuthenticator.from_environment()

    pilot = authenticator.authenticate("pilot-key")
    executor = authenticator.authenticate("executor-key")
    assert pilot.roles == {"pilot_reader"}
    assert executor.roles == {"executor"}
    assert "executor" not in pilot.roles
    assert "pilot_reader" not in executor.roles


def test_actor_resolution_is_credential_free_and_rejects_profile_ambiguity(
    monkeypatch,
):
    monkeypatch.delenv("KJDS_API_KEY", raising=False)
    monkeypatch.setenv(
        "KJDS_API_KEYS_JSON",
        json.dumps(
            {
                "operator-key-a": credential_profile(
                    "operator-a",
                    ["operator"],
                ),
                "operator-key-b": credential_profile(
                    "operator-a",
                    ["operator"],
                ),
            }
        ),
    )
    authenticator = ApiKeyAuthenticator.from_environment()
    resolved = authenticator.resolve_actor("operator-a")
    assert resolved.actor_id == "operator-a"
    assert resolved.roles == {"operator"}
    assert "operator-key" not in repr(resolved)
    with pytest.raises(KeyError, match="not found"):
        authenticator.resolve_actor("missing-actor")

    monkeypatch.setenv(
        "KJDS_API_KEYS_JSON",
        json.dumps(
            {
                "operator-key": credential_profile(
                    "operator-a",
                    ["operator"],
                ),
                "reviewer-key": credential_profile(
                    "operator-a",
                    ["reviewer"],
                ),
            }
        ),
    )
    ambiguous = ApiKeyAuthenticator.from_environment()
    with pytest.raises(ValueError, match="ambiguous"):
        ambiguous.resolve_actor("operator-a")


def test_non_admin_identity_cannot_combine_request_and_approval_roles(monkeypatch):
    monkeypatch.delenv("KJDS_API_KEY", raising=False)
    monkeypatch.setenv(
        "KJDS_API_KEYS_JSON",
        json.dumps({"conflicted-key": credential_profile("conflicted-user", ["operator", "approver"])}),
    )
    with pytest.raises(RuntimeError, match="cannot combine operator and approver"):
        ApiKeyAuthenticator.from_environment()


def test_api_fails_closed_when_identity_is_not_configured(monkeypatch):
    monkeypatch.delenv("KJDS_API_KEYS_JSON", raising=False)
    monkeypatch.delenv("KJDS_API_KEY", raising=False)
    authenticator = ApiKeyAuthenticator.from_environment()
    with pytest.raises(AuthenticationFailure) as failure:
        authenticator.authenticate("anything")
    assert failure.value.status_code == 503


def test_empty_identity_map_falls_back_to_development_key(monkeypatch):
    monkeypatch.setenv("KJDS_ENVIRONMENT", "development")
    monkeypatch.setenv("KJDS_API_KEYS_JSON", "{}")
    monkeypatch.setenv("KJDS_API_KEY", "development-key")
    monkeypatch.setenv("KJDS_API_ROLES", "operator")
    authenticator = ApiKeyAuthenticator.from_environment()
    assert authenticator.authenticate("development-key").roles == {"operator"}
    assert authenticator.safe_summary()["legacy_mode"] is True


@pytest.mark.parametrize(
    ("environment", "mapping", "api_key", "message"),
    [
        ("production", "{}", "shared-key", "Production requires"),
        ("development", '{"key":{"actor":"worker","roles":["root"]}}', "", "Unknown API roles"),
        ("development", "{}", "replace-with-a-key", "Placeholder"),
        (
            "development",
            '{"worker-key":{"actor":"worker","roles":["pilot_reader"]}}',
            "web-key",
            "must appear",
        ),
    ],
)
def test_runtime_identity_configuration_fails_closed(monkeypatch, environment, mapping, api_key, message):
    monkeypatch.setenv("KJDS_ENVIRONMENT", environment)
    monkeypatch.setenv("KJDS_API_KEYS_JSON", mapping)
    monkeypatch.setenv("KJDS_API_KEY", api_key)
    with pytest.raises(RuntimeError, match=message):
        ApiKeyAuthenticator.from_environment()


def test_secret_scan_detects_forbidden_files_and_high_confidence_tokens(tmp_path):
    from scripts.verify_secrets import scan_paths

    (tmp_path / ".env").write_text("SAFE=value", encoding="utf-8")
    token = "ghp_" + "123456789012345678901234"
    (tmp_path / "config.txt").write_text(f"token={token}", encoding="utf-8")
    findings = scan_paths(tmp_path, [".env", "config.txt"])
    assert findings == [".env: forbidden environment file", "config.txt: github-token"]


def test_kill_switch_is_append_only_and_blocks_writes():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    service = KillSwitchService(engine)

    assert service.current().engaged is False
    engaged = service.set_state(engaged=True, reason="incident exercise", actor_id="risk-owner")
    assert engaged.engaged is True
    with pytest.raises(WritesDisabled, match="incident exercise"):
        service.ensure_writes_allowed()

    released = service.set_state(engaged=False, reason="incident resolved", actor_id="admin-owner")
    assert released.sequence == engaged.sequence + 1
    service.ensure_writes_allowed()


def test_business_write_endpoints_declare_endpoint_level_minimum_roles():
    from apps.control_plane.api import registered_routes

    expected_paths = {
        "/v1/models/discover",
        "/v1/recommendations",
        "/v1/products",
        "/v1/market/observations",
        "/v1/market/opportunities",
        "/v1/market/candidates/intake",
        "/v1/market/candidates/sourcing-handoff",
        "/v1/content/assets",
        "/v1/content/assets/{asset_id}/generated",
        "/v1/content/assets/{asset_id}/review",
        "/v1/experiments",
        "/v1/experiments/{experiment_id}/start",
        "/v1/orders",
        "/v1/orders/{order_id}/charges",
    }
    routes = {
        route.path: route.endpoint
        for route in registered_routes()
        if hasattr(route, "endpoint") and "POST" in getattr(route, "methods", set())
    }
    for path in expected_paths:
        source = inspect.getsource(routes[path])
        assert "current_principal" in source
        assert "ensure_role" in source


def test_read_only_control_plane_reads_declare_endpoint_level_roles():
    from apps.control_plane.api import registered_routes

    expected_paths = {
        "/v1/integrations/health",
        "/v1/loop-engineering/registry",
        "/v1/read-only-pilot-runs",
        "/v1/read-only-pilot-runs/{run_id}",
        "/v1/read-only-pilots/{pilot_id}/usage",
        "/v1/read-only-claims",
        "/v1/read-only-claims/{claim_id}",
        "/v1/oms/workspace",
        "/v1/inventory/workspace",
    }
    routes = {
        route.path: route.endpoint
        for route in registered_routes()
        if hasattr(route, "endpoint") and "GET" in getattr(route, "methods", set())
    }
    for path in expected_paths:
        source = inspect.getsource(routes[path])
        assert "current_principal" in source
        assert "ensure_role" in source


def test_loop_validation_remains_available_as_a_safety_control():
    from apps.control_plane.api import is_write_safety_control_path, registered_routes

    assert is_write_safety_control_path("/v1/loop-engineering/validate") is True
    route = next(
        route for route in registered_routes() if getattr(route, "path", None) == "/v1/loop-engineering/validate"
    )
    source = inspect.getsource(route.endpoint)
    assert "current_principal" in source
    assert "ensure_role" in source


def test_evidence_integrity_scan_remains_available_as_a_safety_control():
    from apps.control_plane.api import is_write_safety_control_path, registered_routes

    path = "/v1/evidence/integrity-scan"
    assert is_write_safety_control_path(path) is True
    route = next(route for route in registered_routes() if getattr(route, "path", None) == path)
    source = inspect.getsource(route.endpoint)
    assert "current_principal" in source
    assert "ensure_role" in source


def test_limited_execution_safety_bookkeeping_remains_available_after_containment():
    from apps.control_plane.api import is_write_safety_control_path, registered_routes

    allowed = {
        "/v1/limited-execution-commands/{command_id}/response-checkpoint",
        "/v1/limited-execution-commands/{command_id}/receipt",
    }
    blocked = {
        "/v1/governed-execution-plans/{plan_id}/commands",
        "/v1/limited-execution-commands/{command_id}/claim",
        "/v1/limited-execution-commands/{command_id}/write-attempt",
    }
    routes = {
        route.path: route.endpoint
        for route in registered_routes()
        if hasattr(route, "endpoint") and "POST" in getattr(route, "methods", set())
    }
    for path in allowed:
        assert is_write_safety_control_path(path) is True
        source = inspect.getsource(routes[path])
        assert "current_principal" in source
        assert "ensure_role(principal, \"executor\", \"admin\")" in source
    for path in blocked:
        assert is_write_safety_control_path(path) is False


def test_kill_switch_middleware_blocks_execution_but_not_safety_bookkeeping(monkeypatch):
    from apps.control_plane.api import app
    from apps.control_plane.runtime import runtime
    from apps.control_plane.security import Principal

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: Principal("ozon-worker", frozenset({"executor"})),
    )
    monkeypatch.setattr(
        runtime.kill_switch,
        "ensure_writes_allowed",
        lambda: (_ for _ in ()).throw(WritesDisabled("contained")),
    )
    client = TestClient(app)

    blocked = client.post(
        "/v1/limited-execution-commands/lxc-1/write-attempt",
        headers={"X-KJDS-API-Key": "executor-key"},
    )
    assert blocked.status_code == 423

    checkpoint = client.post(
        "/v1/limited-execution-commands/lxc-1/response-checkpoint",
        headers={"X-KJDS-API-Key": "executor-key"},
        data={
            "artifact_kind": "before_read",
            "response_sha256": "a" * 64,
        },
        files={"file": ("before.json", b"{}", "application/json")},
    )
    assert checkpoint.status_code != 423

    receipt = client.post(
        "/v1/limited-execution-commands/lxc-1/receipt",
        headers={"X-KJDS-API-Key": "executor-key"},
        json={
            "outcome": "uncertain",
            "remote_operation_id": None,
            "resulting_state_hash": None,
            "mutation_applied": False,
            "error_code": "REMOTE_WRITE_UNCERTAIN",
            "error_detail": "requires reconciliation",
            "evidence_ids": ["evd-1"],
        },
    )
    assert receipt.status_code != 423


def test_correlation_ids_are_bounded_and_reused_when_safe():
    from fastapi import Request

    from apps.control_plane.api import request_id_for, trace_id_for

    safe = Request({"type": "http", "headers": [(b"x-request-id", b"pilot-001")]})
    assert request_id_for(safe) == "pilot-001"

    unsafe = Request({"type": "http", "headers": [(b"x-request-id", b"bad value\n")]})
    generated = request_id_for(unsafe)
    assert generated.startswith("req_")
    assert len(generated) <= 128

    unsafe_trace = Request({"type": "http", "headers": [(b"x-trace-id", b"bad trace")]})
    generated_trace = trace_id_for(unsafe_trace)
    assert generated_trace.startswith("trace_")
    assert len(generated_trace) <= 128
