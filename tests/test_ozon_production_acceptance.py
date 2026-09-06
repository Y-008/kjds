from datetime import UTC, datetime

from apps.control_plane.api import registered_routes
from apps.control_plane.ozon_production_acceptance import OzonProductionAcceptanceService
from apps.control_plane.routers import execution_operations
from apps.control_plane.security import Principal


def _principal() -> Principal:
    return Principal(
        actor_id="reviewer",
        roles=frozenset({"reviewer"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )


def test_production_acceptance_route_is_registered_and_read_only():
    paths = {route.path for route in registered_routes()}
    assert "/v1/read-only-pilot-runs/{run_id}/production-acceptance" in paths


def test_missing_entity_scope_is_explicit_no_data_without_authority_access():
    class _Forbidden:
        def require_run(self, **_kwargs):  # pragma: no cover - must not execute
            raise AssertionError("missing entity scope must not query a run")

    service = OzonProductionAcceptanceService(
        scoped_pilots=_Forbidden(),
        evidence=object(),
        clock=lambda: datetime(2026, 9, 7, 0, tzinfo=UTC),
    )
    result = service.evaluate(
        principal=_principal(),
        entity_scope={"status": "missing"},
        store_ref="store-a",
        run_id="run-1",
        as_of=datetime(2026, 9, 7, 0, tzinfo=UTC),
    )
    assert result["status"] == "no_data"
    assert result["gate_status"] == "NO_DATA"
    assert result["accepted"] is False
    assert result["blockers"] == ["entity_scope_authority_missing"]
    assert result["external_write_allowed"] is False


def test_route_delegates_to_server_acceptance_projection(monkeypatch):
    class _ScopeGrants:
        def current(self, **_kwargs):
            return {
                "status": "ready",
                "entity_ref": "entity-a",
                "authority_sha256": "a" * 64,
            }

    class _Acceptance:
        def evaluate(self, **kwargs):
            assert kwargs["run_id"] == "run-1"
            assert kwargs["store_ref"] == "store-a"
            return {
                "status": "blocked",
                "gate_status": "BLOCKED_EVIDENCE",
                "external_write_allowed": False,
            }

    monkeypatch.setattr(execution_operations.runtime, "scope_grants", _ScopeGrants())
    monkeypatch.setattr(execution_operations.runtime, "ozon_production_acceptance", _Acceptance())
    result = execution_operations.evaluate_ozon_production_acceptance(
        run_id="run-1",
        principal=_principal(),
        store_ref="store-a",
        as_of="2026-09-06T00:00:00+00:00",
    )
    assert result["gate_status"] == "BLOCKED_EVIDENCE"
    assert result["external_write_allowed"] is False
