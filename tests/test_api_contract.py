from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from apps.control_plane import api as api_module
from apps.control_plane.api import (
    API_SCHEMA_VERSION,
    FeeMappingInput,
    app,
    contract_error,
    cost_authority_catalog,
    register_fee_mapping,
    validated_report_period,
)
from apps.control_plane.domain import ChargeType
from apps.control_plane.finance import FeeSignRule
from apps.control_plane.imports import ImportPreview
from apps.control_plane.routers.evidence_governance import capture_evidence
from apps.control_plane.routers.seller_erp_bridge import (
    submit_seller_erp_bridge_source,
)
from apps.control_plane.security import Principal


def test_success_response_declares_compatible_schema_version() -> None:
    response = TestClient(app).get(
        "/version",
        headers={"X-Request-ID": "contract-success", "X-Trace-ID": "trace-contract"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "contract-success"
    assert response.headers["X-Trace-ID"] == "trace-contract"
    assert response.headers["X-KJDS-Schema-Version"] == API_SCHEMA_VERSION
    assert response.json()["schema_version"] == API_SCHEMA_VERSION


def test_error_contract_keeps_legacy_detail_and_adds_stable_metadata() -> None:
    response = contract_error(status_code=422, detail="invalid amount", request_id="contract-error")
    payload = json.loads(response.body)

    assert payload["detail"] == "invalid amount"
    assert payload["error"] == {"code": "VALIDATION_FAILED", "message": "invalid amount"}
    assert payload["request_id"] == "contract-error"
    assert payload["schema_version"] == API_SCHEMA_VERSION
    assert response.headers["X-KJDS-Schema-Version"] == API_SCHEMA_VERSION


def test_openapi_v1_snapshot_matches_runtime_contract() -> None:
    snapshot_path = Path(__file__).resolve().parents[1] / "docs" / "project" / "contracts" / "openapi-v1.json"
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == app.openapi()


def test_generic_evidence_upload_rejects_reserved_execution_source() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            capture_evidence(
                file=UploadFile(file=io.BytesIO(b"untrusted"), filename="artifact.json"),
                source="ozon-isolated-execution-worker",
                source_ref="lxc-1/before-read",
                grade=api_module.EvidenceGrade.A,
                effective_at="2026-07-24T00:00:00Z",
                principal=Principal("operator-1", frozenset({"operator"})),
            )
        )
    assert error.value.status_code == 422
    assert "dedicated workflow" in str(error.value.detail)


def test_generic_evidence_upload_rejects_reserved_seller_erp_source() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            capture_evidence(
                file=UploadFile(
                    file=io.BytesIO(b"untrusted"),
                    filename="seller-export.csv",
                ),
                source="seller_erp_bridge_source",
                source_ref="forged://source",
                grade=api_module.EvidenceGrade.A,
                effective_at="2026-07-29T00:00:00Z",
                principal=Principal(
                    "operator-1", frozenset({"operator"})
                ),
            )
        )
    assert error.value.status_code == 422
    assert "dedicated workflow" in str(error.value.detail)


def test_seller_erp_upload_checks_entity_before_reading_file(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    class NeverReadUpload:
        filename = "seller-export.csv"
        content_type = "text/csv"

        async def read(self, _size):
            raise AssertionError("file must not be read without entity scope")

    principal = Principal(
        actor_id="bridge-upload-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            submit_seller_erp_bridge_source(
                file=NeverReadUpload(),
                provider="dianxiaomi",
                source_kind="seller_erp_formal_export",
                domain="catalog",
                schema_version="seller-erp-bridge-catalog-v1",
                column_map_json="{}",
                exported_at="2026-07-29T00:00:00Z",
                authorization_mode="account_owner_export",
                idempotency_key="never-read",
                principal=principal,
                store_ref="store-cn-1",
            )
        )
    assert error.value.status_code == 422
    assert "before reading" in str(error.value.detail)


def test_openapi_declares_api_key_security_for_protected_operations() -> None:
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["KjdsApiKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-KJDS-API-Key",
    }
    assert schema["paths"]["/v1/products"]["get"]["security"] == [
        {"KjdsApiKey": []}
    ]


def test_operating_intelligence_named_aliases_share_endpoints_and_require_authentication(
    monkeypatch,
) -> None:
    from apps.control_plane.api import registered_routes
    from apps.control_plane.runtime import runtime
    from apps.control_plane.security import AuthenticationFailure

    routes = {
        (route.path, method): route.endpoint
        for route in registered_routes()
        if hasattr(route, "endpoint")
        for method in getattr(route, "methods", set())
    }
    pairs = (
        (
            ("/v1/operating-intelligence/metrics", "GET"),
            ("/v1/metrics", "GET"),
        ),
        (
            ("/v1/operating-intelligence/anomaly-scans", "POST"),
            ("/v1/anomaly-scans", "POST"),
        ),
    )
    schema = app.openapi()
    for canonical, legacy in pairs:
        assert routes[canonical] is routes[legacy]
        assert schema["paths"][canonical[0]][canonical[1].lower()][
            "security"
        ] == [{"KjdsApiKey": []}]
        assert schema["paths"][legacy[0]][legacy[1].lower()][
            "security"
        ] == [{"KjdsApiKey": []}]

    def reject_missing_key(_key):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject_missing_key)
    client = TestClient(app)
    assert client.get("/v1/operating-intelligence/metrics").status_code == 401
    assert (
        client.post(
            "/v1/operating-intelligence/anomaly-scans",
            json={"store_ref": "ozon-primary"},
        ).status_code
        == 401
    )


def test_operating_tasks_and_queue_require_exact_authenticated_store_scope(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="operator-scope-test",
        roles=frozenset({"operator", "monitor"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    tasks = client.get(
        "/v1/operating-tasks?store_ref=store-cn-1",
        headers=headers,
    )
    queue = client.get(
        "/v1/operations-control/queue?store_ref=store-cn-1",
        headers=headers,
    )
    task_forbidden = client.get(
        "/v1/operating-tasks?store_ref=other-store",
        headers=headers,
    )
    queue_forbidden = client.get(
        "/v1/operations-control/queue?store_ref=other-store",
        headers=headers,
    )

    assert tasks.status_code == 200
    assert tasks.json() == []
    assert queue.status_code == 200
    assert queue.json()["status"] == "no_data"
    assert queue.json()["items"] == []
    assert queue.json()["external_write_allowed"] is False
    assert task_forbidden.status_code == 403
    assert queue_forbidden.status_code == 403


def test_operations_queue_endpoints_require_authentication(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime
    from apps.control_plane.security import AuthenticationFailure

    def reject_missing_key(_key):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject_missing_key)
    client = TestClient(app)

    assert client.get("/v1/operations-control/queue").status_code == 401
    assert (
        client.post(
            "/v1/operations-control/escalation-scan",
            json={"store_ref": "ozon-primary"},
        ).status_code
        == 401
    )
    assert (
        client.get("/v1/operations-control/escalations").status_code
        == 401
    )


def test_missing_entity_read_workspaces_do_not_call_legacy_global_sources(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="operator-scope-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )

    def fail_legacy_read(*_args, **_kwargs):
        raise AssertionError("legacy global source must not be read")

    monkeypatch.setattr(
        runtime.operating_workbench.readiness,
        "report",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        runtime.operating_workbench.automation,
        "list_recommendations",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        runtime.operating_analytics.marketplace_catalog,
        "latest_items",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        runtime.operating_analytics.finance,
        "list_entries",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        runtime.batch_opportunity,
        "latest",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        runtime.profit_erp_sync,
        "workspace",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        runtime.media_workbench,
        "snapshot",
        fail_legacy_read,
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    workbench = client.get(
        "/v1/operating-workbench/briefing?store_ref=store-cn-1"
        "&as_of=2026-07-28T01%3A00%3A00Z",
        headers=headers,
    )
    analytics = client.get(
        "/v1/operating-analytics/snapshot?store_ref=store-cn-1"
        "&as_of=2026-07-28T01%3A00%3A00Z",
        headers=headers,
    )
    workspace = client.get(
        "/v1/operating-workspaces/points/market_signal_inbox"
        "?store_ref=store-cn-1"
        "&as_of=2026-07-28T01%3A00%3A00Z",
        headers=headers,
    )
    evidenceops = client.post(
        "/v1/evidenceops/plan",
        headers=headers,
        json={
            "objective": "分析利润证据缺口",
            "store_ref": "store-cn-1",
        },
    )
    commerce = client.get(
        "/v1/commerce-os/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-28T01%3A00%3A00Z",
        headers=headers,
    )

    assert workbench.status_code == 200
    assert workbench.json()["status"] == "no_data"
    assert analytics.status_code == 200
    assert analytics.json()["status"] == "no_data"
    assert analytics.json()["summary"]["catalog_items"] == 0
    assert workspace.status_code == 200
    assert workspace.json()["control_envelope"][
        "external_write_allowed"
    ] is False
    assert evidenceops.status_code == 200
    assert evidenceops.json()["control_envelope"][
        "external_write_allowed"
    ] is False
    assert commerce.status_code == 200
    assert commerce.json()["status"] == "no_data"
    assert commerce.json()["outcome"]["observed_listings"] == 0


def test_anomaly_scan_uses_current_grant_not_historical_cutoff(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="operator-scope-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    scope_calls = []

    def scope_at(**values):
        scope_calls.append(values["as_of"])
        is_historical = (
            values["as_of"].isoformat()
            == "2026-01-01T00:00:00+00:00"
        )
        return {
            "status": "ready" if not is_historical else "no_data",
            "entity_ref": None if is_historical else "entity-cn-1",
            "authority": None,
            "authority_sha256": None if is_historical else "a" * 64,
            "reason": (
                "entity_scope_authority_missing"
                if is_historical
                else "entity_scope_ready"
            ),
        }

    captured = {}

    def scan(**values):
        captured.update(values)
        return {
            "id": None,
            "status": "no_data",
            "persisted": False,
            "external_write_allowed": False,
        }

    monkeypatch.setattr(runtime.scope_grants, "current", scope_at)
    monkeypatch.setattr(runtime.operating_intelligence, "scan", scan)
    response = TestClient(app).post(
        "/v1/operating-intelligence/anomaly-scans",
        headers={"X-KJDS-API-Key": "test-key"},
        json={
            "store_ref": "store-cn-1",
            "as_of": "2026-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 201
    assert len(scope_calls) == 2
    assert captured["as_of"] == "2026-01-01T00:00:00+00:00"
    assert captured["entity_scope"]["status"] == "ready"
    assert captured["entity_scope"]["entity_ref"] == "entity-cn-1"


def test_profit_ledger_requires_store_scope_and_does_not_read_raw_without_entity(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime
    from apps.control_plane.security import AuthenticationFailure

    principal = Principal(
        actor_id="operator-scope-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    def authenticate(key):
        if not key:
            raise AuthenticationFailure(
                "X-KJDS-API-Key is required",
                401,
            )
        return principal

    monkeypatch.setattr(runtime.authenticator, "authenticate", authenticate)
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )

    def fail_raw_read(**_values):
        raise AssertionError("raw ledger must not be read without entity scope")

    monkeypatch.setattr(
        runtime.profit_ledger.finance,
        "read_scoped_sources",
        fail_raw_read,
    )
    monkeypatch.setattr(
        runtime.profit_ledger.finance,
        "read_scoped_profit_authorities",
        fail_raw_read,
    )
    monkeypatch.setattr(
        runtime.profit_ledger,
        "_read_products",
        fail_raw_read,
    )
    client = TestClient(app)

    anonymous = client.get(
        "/v1/profit-ledger?store_ref=store-cn-1"
    )
    response = client.get(
        "/v1/profit-ledger?store_ref=store-cn-1"
        "&as_of=2026-07-27T02%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/profit-ledger?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert anonymous.status_code == 401
    assert response.status_code == 200
    assert response.json()["status"] == "no_data"
    assert response.json()["rows"] == []
    assert response.json()["source_snapshot_sha256"] is None
    assert (
        response.json()["control_envelope"]["scoped_input_read"]
        is False
    )
    assert forbidden.status_code == 403
    parameters = {
        item["name"]
        for item in app.openapi()["paths"]["/v1/profit-ledger"]["get"][
            "parameters"
        ]
    }
    assert {
        "as_of",
        "query",
        "page_size",
        "cursor",
    } <= parameters
    assert app.openapi()["paths"]["/v1/profit-ledger"]["get"][
        "security"
    ] == [{"KjdsApiKey": []}]


def test_marketplace_observation_and_portfolio_pilot_contracts_are_protected(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime
    from apps.control_plane.security import AuthenticationFailure

    schema = app.openapi()
    for path, methods in (
        ("/v1/marketplace-observations", {"get", "post"}),
        ("/v1/portfolio-pilot/prepare", {"post"}),
        ("/v1/batch-market-scans", {"post"}),
        ("/v1/batch-opportunities/latest", {"get"}),
        ("/v1/ozon-global-rules", {"get"}),
        ("/v1/ozon-global-rules/evaluate", {"post"}),
        ("/v1/seller-os/strategy-packs", {"get"}),
        ("/v1/seller-os/evaluate", {"post"}),
        ("/v1/erp/profit-items", {"get"}),
        ("/v1/erp/profit-items/syncs", {"post"}),
        ("/v1/erp/profit-items/syncs/{sync_id}/dispatch", {"post"}),
        ("/v1/oms/workspace", {"get"}),
        ("/v1/inventory/workspace", {"get"}),
        ("/v1/pim/workspace", {"get"}),
        ("/v1/listing-lifecycle/workspace", {"get"}),
        ("/v1/media-factory/workspace", {"get"}),
        ("/v1/media/workbench", {"get"}),
        ("/v1/finance-control/workspace", {"get"}),
        ("/v1/procurement/workspace", {"get"}),
        ("/v1/accounts-payable/workspace", {"get"}),
        ("/v1/returns/workspace", {"get"}),
        ("/v1/customer-service/workspace", {"get"}),
        ("/v1/customer-service/cases", {"post"}),
        (
            "/v1/customer-service/cases/{case_id}/events",
            {"post"},
        ),
        ("/v1/accounts-payable/invoices", {"post"}),
        (
            "/v1/accounts-payable/invoices/{invoice_id}/authority-review",
            {"post"},
        ),
        ("/v1/sourcing-intelligence/workspace", {"get"}),
        ("/v1/seller-erp-bridge/sources", {"post"}),
        ("/v1/seller-erp-bridge/reviews", {"post"}),
        ("/v1/seller-erp-bridge/bindings", {"post"}),
        ("/v1/seller-erp-bridge/revocations", {"post"}),
        ("/v1/seller-erp-bridge/reconcile", {"get"}),
    ):
        assert set(schema["paths"][path]) == methods
        for method in methods:
            assert schema["paths"][path][method]["security"] == [
                {"KjdsApiKey": []}
            ]
    capture = schema["components"]["schemas"][
        "MarketplaceObservationCaptureInput"
    ]
    item = schema["components"]["schemas"][
        "MarketplaceObservationItemInput"
    ]
    pilot = schema["components"]["schemas"]["PortfolioPilotPrepareInput"]
    batch = schema["components"]["schemas"]["BatchOpportunityPrepareInput"]
    ozon_rules = schema["components"]["schemas"][
        "OzonGlobalRuleEvaluationInput"
    ]
    seller_os = schema["components"]["schemas"][
        "SellerOperatingSystemInput"
    ]
    assert capture["additionalProperties"] is False
    assert item["additionalProperties"] is False
    assert pilot["additionalProperties"] is False
    assert batch["additionalProperties"] is False
    assert ozon_rules["additionalProperties"] is False
    assert seller_os["additionalProperties"] is False
    assert "observed_checkout_price" in item["properties"]["price_kind"][
        "enum"
    ]
    assert "public_search_index_observation" in capture["properties"][
        "source_profile"
    ]["enum"]
    assert set(batch["required"]) == {"idempotency_key"}
    assert "confirmed" in capture["required"]
    assert "displayed_price" in item["required"]
    assert "target_specification" in pilot["required"]

    def reject_missing_key(_key):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        reject_missing_key,
    )
    client = TestClient(app)
    assert (
        client.get(
            "/v1/batch-opportunities/latest?store_ref=ozon-primary"
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/v1/batch-market-scans",
            json={"idempotency_key": "anonymous-batch"},
        ).status_code
        == 401
    )
    assert client.get("/v1/ozon-global-rules").status_code == 401
    assert (
        client.post(
            "/v1/ozon-global-rules/evaluate",
            json={"sku_ref": "anonymous"},
        ).status_code
        == 401
    )
    assert client.get("/v1/seller-os/strategy-packs").status_code == 401
    assert client.get("/v1/erp/profit-items").status_code == 401
    assert client.get("/v1/oms/workspace").status_code == 401
    assert client.get("/v1/inventory/workspace").status_code == 401
    assert client.get("/v1/pim/workspace").status_code == 401
    assert client.get("/v1/listing-lifecycle/workspace").status_code == 401
    assert client.get("/v1/media-factory/workspace").status_code == 401
    assert client.get("/v1/media/workbench").status_code == 401
    assert client.get("/v1/finance-control/workspace").status_code == 401
    assert client.get("/v1/procurement/workspace").status_code == 401
    assert client.get("/v1/accounts-payable/workspace").status_code == 401
    assert client.get("/v1/returns/workspace").status_code == 401
    assert client.get("/v1/customer-service/workspace").status_code == 401
    assert client.post("/v1/customer-service/cases", json={}).status_code == 401
    assert (
        client.get("/v1/sourcing-intelligence/workspace").status_code
        == 401
    )
    assert client.get("/v1/seller-erp-bridge/reconcile").status_code == 401
    assert (
        client.post(
            "/v1/seller-erp-bridge/reviews",
            json={},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/v1/seller-os/evaluate",
            json={"seller_facts": {"shops": 1}},
        ).status_code
        == 401
    )


def test_oms_workspace_enforces_store_scope_and_keeps_missing_entity_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="oms-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/oms/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/oms/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "no_data"
    assert response.json()["scope"]["entity_ref"] is None
    assert response.json()["control_envelope"]["scoped_input_read"] is False
    assert response.json()["control_envelope"]["external_write_allowed"] is False
    assert forbidden.status_code == 403


def test_inventory_workspace_enforces_scope_and_reports_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="inventory-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/inventory/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/inventory/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["legacy_inventory_rows_read"] == 0
    assert payload["counts"]["marketplace_observations_inferred"] == 0
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert forbidden.status_code == 403


def test_finance_control_enforces_scope_and_reports_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="finance-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/finance-control/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/finance-control/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total_cycles"] == 0
    assert payload["cycles"] == []
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["finance_entry_created"] is False
    assert payload["control_envelope"]["reconciliation_created"] is False
    assert payload["control_envelope"]["payment_initiated"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert (
        payload["agent_artifact"]["self_approval_allowed"] is False
    )
    assert (
        payload["agent_artifact"]["permit_issue_allowed"] is False
    )
    assert forbidden.status_code == 403


def test_procurement_workspace_enforces_scope_and_reports_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="procurement-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/procurement/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/procurement/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total"] == 0
    assert payload["orders"] == []
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["purchase_order_created"] is False
    assert payload["control_envelope"]["receipt_confirmed"] is False
    assert payload["control_envelope"]["payment_initiated"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert (
        payload["agent_artifact"]["self_approval_allowed"] is False
    )
    assert (
        payload["agent_artifact"]["permit_issue_allowed"] is False
    )
    assert forbidden.status_code == 403


def test_accounts_payable_workspace_enforces_scope_and_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="accounts-payable-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    response = client.get(
        "/v1/accounts-payable/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers=headers,
    )
    forbidden = client.get(
        "/v1/accounts-payable/workspace?store_ref=other-store",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total"] == 0
    assert payload["invoices"] == []
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["invoice_created"] is False
    assert payload["control_envelope"]["payment_initiated"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert payload["control_envelope"]["private_erp_interface_allowed"] is False
    assert payload["agent_artifact"]["self_approval_allowed"] is False
    assert payload["agent_artifact"]["permit_issue_allowed"] is False
    assert forbidden.status_code == 403


def test_returns_workspace_enforces_scope_and_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="returns-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    response = client.get(
        "/v1/returns/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers=headers,
    )
    forbidden = client.get(
        "/v1/returns/workspace?store_ref=other-store",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total_returns"] == 0
    assert payload["returns"] == []
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["return_fact_created"] is False
    assert payload["control_envelope"]["refund_created"] is False
    assert payload["control_envelope"]["customer_message_sent"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert (
        payload["control_envelope"]["private_erp_interface_allowed"]
        is False
    )
    assert payload["agent_artifact"]["self_approval_allowed"] is False
    assert payload["agent_artifact"]["permit_issue_allowed"] is False
    assert forbidden.status_code == 403


def test_customer_service_workspace_enforces_scope_privacy_and_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="customer-service-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    response = client.get(
        "/v1/customer-service/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers=headers,
    )
    forbidden = client.get(
        "/v1/customer-service/workspace?store_ref=other-store",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total_cases"] == 0
    assert payload["cases"] == []
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["privacy_envelope"]["raw_message_body_exposed"] is False
    assert payload["privacy_envelope"]["customer_email_exposed"] is False
    assert payload["control_envelope"]["message_marked_sent"] is False
    assert payload["control_envelope"]["message_adapter_enabled"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert (
        payload["control_envelope"]["private_erp_interface_allowed"]
        is False
    )
    assert payload["agent_artifact"]["raw_pii_read_allowed"] is False
    assert payload["agent_artifact"]["self_approval_allowed"] is False
    assert payload["agent_artifact"]["permit_issue_allowed"] is False
    assert forbidden.status_code == 403
    schema = app.openapi()["components"]["schemas"]
    for name in ("CustomerServiceCaseInput", "CustomerServiceEventInput"):
        properties = schema[name]["properties"]
        for forbidden_field in (
            "raw_message_body",
            "customer_name",
            "customer_address",
            "customer_phone",
            "customer_email",
            "platform_handle",
            "cookie",
            "token",
        ):
            assert forbidden_field not in properties


def test_pim_workspace_enforces_scope_and_reports_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="pim-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/pim/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/pim/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total_product_groups"] == 0
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert forbidden.status_code == 403


def test_listing_lifecycle_enforces_scope_and_reports_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="listing-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/listing-lifecycle/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/listing-lifecycle/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total"] == 0
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["permit_created"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert forbidden.status_code == 403


def test_media_factory_enforces_scope_and_reports_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="media-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/media-factory/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    legacy = client.get(
        "/v1/media/workbench?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/media-factory/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == legacy.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total_product_groups"] == 0
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["asset_created"] is False
    assert payload["control_envelope"]["job_created"] is False
    assert payload["control_envelope"]["manifest_created"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert forbidden.status_code == 403


def test_sourcing_intelligence_enforces_scope_and_reports_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="sourcing-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/sourcing-intelligence/workspace?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/sourcing-intelligence/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total_work_items"] == 0
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["supplier_contacted"] is False
    assert payload["control_envelope"]["rfq_dispatched"] is False
    assert payload["control_envelope"]["purchase_order_created"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert forbidden.status_code == 403


def test_seller_erp_bridge_enforces_scope_and_reports_true_no_data(
    monkeypatch,
) -> None:
    from apps.control_plane.runtime import runtime

    principal = Principal(
        actor_id="bridge-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)

    response = client.get(
        "/v1/seller-erp-bridge/reconcile?store_ref=store-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/seller-erp-bridge/reconcile?store_ref=other-store",
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total_diff_items"] == 0
    assert payload["control_envelope"]["scoped_input_read"] is False
    assert payload["control_envelope"]["formal_fact_promoted"] is False
    assert payload["control_envelope"]["private_interface_used"] is False
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert forbidden.status_code == 403


def test_execution_checkpoint_contract_is_closed_and_protected() -> None:
    operation = app.openapi()["paths"][
        "/v1/limited-execution-commands/{command_id}/response-checkpoint"
    ]["post"]
    assert operation["security"] == [{"KjdsApiKey": []}]
    request_body = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert "$ref" in request_body
    schema_name = request_body["$ref"].rsplit("/", 1)[-1]
    schema = app.openapi()["components"]["schemas"][schema_name]
    assert set(schema["required"]) == {"artifact_kind", "response_sha256", "file"}
    assert set(schema["properties"]) == {
        "artifact_kind",
        "response_sha256",
        "file",
        "sequence_number",
    }


def test_approved_listing_execution_plan_contract_is_narrow_and_uses_principal(monkeypatch) -> None:
    captured: dict = {}

    def create(draft_id: str, **values):
        captured.update({"draft_id": draft_id, **values})
        return {"id": "gxp-1", "approval_id": "apr-execution-1"}

    monkeypatch.setattr(
        api_module.app.state.runtime,
        "execution_plans",
        SimpleNamespace(create_from_approved_listing=create),
    )
    monkeypatch.setattr(
        api_module.app.state.runtime.scope_grants,
        "current",
        lambda **_: {
            "status": "ready",
            "entity_ref": "entity-a",
            "authority_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        api_module.app.state.runtime.sourcing_store,
        "get_listing_draft_scoped",
        lambda **_: SimpleNamespace(id="draft-1"),
    )
    body = api_module.ApprovedListingExecutionPlanInput(
        idempotency_key="listing-plan-1",
        precondition_state_hash="a" * 64,
        evidence_ids=["evd-claim-1"],
        risk_limits={
            "max_quantity": "1",
            "max_daily_runs": "1",
            "max_expected_loss": "500",
        },
        risk_values={"quantity": "1", "expected_loss": "100"},
        risk_currency="CNY",
    )

    result = api_module.prepare_ozon_listing_execution_plan(
        "draft-1",
        body,
        Principal("operator-1", frozenset({"operator"})),
    )

    assert result == {"id": "gxp-1", "approval_id": "apr-execution-1"}
    assert captured == {
        "draft_id": "draft-1",
        **body.model_dump(),
        "created_by": "operator-1",
    }
    request_schema = app.openapi()["components"]["schemas"][
        "ApprovedListingExecutionPlanInput"
    ]
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["properties"]) == {
        "idempotency_key",
        "precondition_state_hash",
        "evidence_ids",
        "risk_limits",
        "risk_values",
        "risk_currency",
    }
    assert app.openapi()["paths"][
        "/v1/listings/ozon/drafts/{draft_id}/execution-plan"
    ]["post"]["security"] == [{"KjdsApiKey": []}]


def test_listing_execution_authority_contracts_are_strict_and_protected() -> None:
    schema = app.openapi()
    listing_schema = schema["components"]["schemas"]["ListingRussianNativeReviewInput"]
    identity_schema = schema["components"]["schemas"][
        "OzonExecutionIdentityAuthorityReviewInput"
    ]
    assert listing_schema["additionalProperties"] is False
    assert identity_schema["additionalProperties"] is False
    assert set(listing_schema["required"]) == {
        "accepted",
        "native_russian_verified",
        "listing_snapshot_reviewed",
        "terminology_accepted",
        "claims_grounded",
        "ozon_policy_checked",
        "rationale",
    }
    assert set(identity_schema["required"]) == {
        "identity_ref",
        "accepted",
        "inventory_complete",
        "credential_material_absent",
        "owner_verified",
        "caller_system_verified",
        "scope_minimized",
        "dedicated_executor",
        "rationale",
    }
    for path in (
        "/v1/listings/ozon/drafts/{draft_id}/russian-native-review",
        "/v1/operations/ozon/execution-identities/{evidence_id}/authority-review",
    ):
        assert schema["paths"][path]["post"]["security"] == [{"KjdsApiKey": []}]


def test_openapi_exposes_control_only_accrual_classification_contract() -> None:
    schema = app.openapi()
    path = "/v1/imports/{import_id}/accrual-classifications"
    assert set(schema["paths"][path]) == {"get", "post"}
    request_schema = schema["components"]["schemas"]["OzonAccrualClassificationInput"]
    assert set(request_schema["required"]) == {
        "accrual_group",
        "accrual_type",
        "accounting_class",
        "expected_sign",
        "effective_from",
        "rationale",
    }


def test_openapi_exposes_read_only_operating_workbench_briefing() -> None:
    schema = app.openapi()

    assert set(schema["paths"]["/v1/operating-workbench/briefing"]) == {"get"}


def test_openapi_exposes_read_only_operating_flow_analytics() -> None:
    schema = app.openapi()

    path = "/v1/operating-analytics/snapshot"
    assert set(schema["paths"][path]) == {"get"}
    assert schema["paths"][path]["get"]["security"] == [{"KjdsApiKey": []}]


def test_openapi_exposes_read_only_cross_border_capability_atlas() -> None:
    schema = app.openapi()

    path = "/v1/capability-atlas/snapshot"
    assert set(schema["paths"][path]) == {"get"}
    assert schema["paths"][path]["get"]["security"] == [{"KjdsApiKey": []}]


def test_openapi_exposes_read_only_operating_workspace_drillthrough() -> None:
    schema = app.openapi()

    path = "/v1/operating-workspaces/{kind}/{item_id}"
    assert set(schema["paths"][path]) == {"get"}
    assert schema["paths"][path]["get"]["security"] == [{"KjdsApiKey": []}]
    parameters = {
        item["name"]: item for item in schema["paths"][path]["get"]["parameters"]
    }
    assert set(parameters) == {
        "kind",
        "item_id",
        "store_ref",
        "as_of",
    }
    assert parameters["kind"]["in"] == "path"
    assert parameters["item_id"]["in"] == "path"
    assert parameters["store_ref"]["in"] == "query"


def test_openapi_exposes_read_only_commerce_operating_system() -> None:
    schema = app.openapi()

    path = "/v1/commerce-os/workspace"
    assert set(schema["paths"][path]) == {"get"}
    assert schema["paths"][path]["get"]["security"] == [
        {"KjdsApiKey": []}
    ]
    parameters = {
        item["name"]: item
        for item in schema["paths"][path]["get"]["parameters"]
    }
    assert set(parameters) == {"store_ref", "as_of"}


def test_openapi_exposes_evidenceops_plan_as_one_protected_post() -> None:
    schema = app.openapi()

    path = "/v1/evidenceops/plan"
    assert set(schema["paths"][path]) == {"post"}
    assert schema["paths"][path]["post"]["security"] == [{"KjdsApiKey": []}]
    request = schema["components"]["schemas"]["EvidenceOpsPlanInput"]
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"objective"}
    assert set(request["properties"]) == {"objective", "store_ref"}


def test_openapi_exposes_persisted_marketplace_growth_fact_loop() -> None:
    schema = app.openapi()

    assert set(schema["paths"]["/v1/marketplace-growth/snapshots"]) == {"post"}
    assert set(
        schema["paths"]["/v1/marketplace-growth/observations/latest"]
    ) == {"get"}
    assert set(
        schema["paths"]["/v1/marketplace-growth/portfolio-plan/latest"]
    ) == {"post"}
    snapshot_input = schema["components"]["schemas"][
        "MarketplaceGrowthSnapshotInput"
    ]
    assert snapshot_input["additionalProperties"] is False
    assert set(snapshot_input["required"]) == {
        "source",
        "idempotency_key",
        "observations",
    }
    for path, method in (
        ("/v1/marketplace-growth/snapshots", "post"),
        ("/v1/marketplace-growth/observations/latest", "get"),
        ("/v1/marketplace-growth/portfolio-plan/latest", "post"),
    ):
        assert schema["paths"][path][method]["security"] == [{"KjdsApiKey": []}]


def test_openapi_exposes_verified_marketplace_catalog_and_existing_binding() -> None:
    schema = app.openapi()

    assert set(
        schema["paths"]["/v1/marketplace-catalog/ozon/import-evidence"]
    ) == {"post"}
    assert set(
        schema["paths"]["/v1/marketplace-catalog/items/latest"]
    ) == {"get"}
    assert set(
        schema["paths"]["/v1/marketplace-catalog/items/bind-existing"]
    ) == {"post"}
    request_schema = schema["components"]["schemas"][
        "OzonCatalogEvidenceImportInput"
    ]
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["required"]) == {
        "evidence_ids",
        "store_ref",
        "idempotency_key",
    }
    binding_schema = schema["components"]["schemas"][
        "ExistingOzonListingBindingInput"
    ]
    assert binding_schema["additionalProperties"] is False
    assert set(binding_schema["required"]) == {
        "store_ref",
        "offer_id",
        "expected_item_hash",
        "confirmed",
    }
    assert binding_schema["properties"]["confirmed"]["const"] is True
    for path, method in (
        ("/v1/marketplace-catalog/ozon/import-evidence", "post"),
        ("/v1/marketplace-catalog/items/latest", "get"),
        ("/v1/marketplace-catalog/items/bind-existing", "post"),
    ):
        assert schema["paths"][path][method]["security"] == [{"KjdsApiKey": []}]


def test_openapi_exposes_immutable_supplier_rfq_and_reply_lineage() -> None:
    schema = app.openapi()
    collection = schema["paths"]["/v1/sourcing/rfq-packages"]
    item = schema["paths"]["/v1/sourcing/rfq-packages/{evidence_id}"]

    assert set(collection) == {"get", "post"}
    assert set(item) == {"get"}
    request_schema = schema["components"]["schemas"]["SupplierRfqPackageInput"]
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["required"]) == {
        "store_ref",
        "offer_id",
        "expected_item_hash",
        "idempotency_key",
        "quantity_breaks",
        "required_specifications",
        "destination",
        "response_due_at",
        "sample_required",
        "tax_invoice_required",
        "required_documents",
        "packaging_requirements",
        "confirmed",
    }
    assert request_schema["properties"]["confirmed"]["const"] is True
    for path, method in (
        ("/v1/sourcing/rfq-packages", "get"),
        ("/v1/sourcing/rfq-packages", "post"),
        ("/v1/sourcing/rfq-packages/{evidence_id}", "get"),
    ):
        assert schema["paths"][path][method]["security"] == [{"KjdsApiKey": []}]

    quote_operation = schema["paths"]["/v1/sourcing/quote-evidence"]["post"]
    multipart_ref = quote_operation["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]["$ref"]
    multipart_schema = schema["components"]["schemas"][
        multipart_ref.rsplit("/", 1)[-1]
    ]
    assert "rfq_package_evidence_id" in multipart_schema["properties"]


def test_openapi_exposes_supplier_rfq_dispatch_proof_and_review() -> None:
    schema = app.openapi()
    collection = schema["paths"]["/v1/sourcing/rfq-dispatches"]
    item = schema["paths"][
        "/v1/sourcing/rfq-dispatches/{evidence_id}"
    ]
    review = schema["paths"][
        "/v1/sourcing/rfq-dispatches/{evidence_id}/authority-review"
    ]

    assert set(collection) == {"get", "post"}
    assert set(item) == {"get"}
    assert set(review) == {"post"}
    capture_ref = collection["post"]["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]["$ref"]
    capture_schema = schema["components"]["schemas"][
        capture_ref.rsplit("/", 1)[-1]
    ]
    assert set(capture_schema["required"]) == {
        "rfq_package_evidence_id",
        "supplier_ref",
        "supplier_platform",
        "supplier_locator",
        "conversation_ref",
        "sent_at",
        "sent_message_text",
        "idempotency_key",
        "confirmed",
        "file",
    }
    review_schema = schema["components"]["schemas"][
        "SupplierRfqDispatchAuthorityReviewInput"
    ]
    assert review_schema["additionalProperties"] is False
    assert set(review_schema["required"]) == {
        "accepted",
        "authentic_platform_proof",
        "supplier_identity_matches",
        "frozen_message_matches",
        "timestamp_and_conversation_match",
        "rationale",
    }
    for path, method in (
        ("/v1/sourcing/rfq-dispatches", "get"),
        ("/v1/sourcing/rfq-dispatches", "post"),
        ("/v1/sourcing/rfq-dispatches/{evidence_id}", "get"),
        (
            "/v1/sourcing/rfq-dispatches/{evidence_id}/authority-review",
            "post",
        ),
    ):
        assert schema["paths"][path][method]["security"] == [
            {"KjdsApiKey": []}
        ]

    quote_ref = schema["paths"]["/v1/sourcing/quote-evidence"][
        "post"
    ]["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
    quote_schema = schema["components"]["schemas"][
        quote_ref.rsplit("/", 1)[-1]
    ]
    assert "rfq_dispatch_evidence_id" in quote_schema["properties"]


def test_openapi_exposes_versioned_logistics_cost_workspace() -> None:
    schema = app.openapi()

    for path, methods in (
        ("/v1/logistics/rate-cards", {"get", "post"}),
        ("/v1/logistics/calculations", {"get", "post"}),
        (
            "/v1/logistics/calculations/{calculation_id}/decision-support",
            {"get"},
        ),
    ):
        assert set(schema["paths"][path]) == methods
        for method in methods:
            assert schema["paths"][path][method]["security"] == [{"KjdsApiKey": []}]
    rate_card = schema["components"]["schemas"]["LogisticsRateCardInput"]
    calculation = schema["components"]["schemas"]["LogisticsCalculationInput"]
    assert rate_card["additionalProperties"] is False
    assert calculation["additionalProperties"] is False
    assert {
        "evidence_id",
        "source_sheet",
        "source_range",
        "declared_value_currency",
        "effective_at",
    }.issubset(rate_card["required"])
    assert "logistics_calculation_id" in schema["components"]["schemas"][
        "ProfitScenarioInput"
    ]["properties"]


def test_cost_authority_catalog_is_read_only_and_complete() -> None:
    result = cost_authority_catalog(Principal("operator-1", frozenset({"operator"})))

    assert result["schema_version"] == "cost-actual-authority-v1"
    assert len(result["items"]) == 15
    assert all(len(item["authorities"]) == 1 for item in result["items"])
    assert result["automatic_state_change"] is False
    assert result["automatic_finance_posting"] is False
    assert result["automatic_procurement"] is False
    assert result["automatic_listing"] is False
    assert set(app.openapi()["paths"]["/v1/finance/cost-authorities"]) == {"get"}


def test_research_signal_endpoint_preserves_raw_fields_and_never_returns_an_action(monkeypatch) -> None:
    captured: dict = {}

    def record(**values):
        captured.update(values)
        return {"automatic_listing": False, "automatic_procurement": False}

    monkeypatch.setattr(api_module.app.state.runtime, "research_inbox", SimpleNamespace(capture=record))
    result = asyncio.run(
        api_module.capture_research_signal(
            file=UploadFile(file=io.BytesIO(b"raw export"), filename="signal.csv"),
            provider="Seerfar",
            provider_record_id="seerfar://row-1",
            source_url="https://www.seerfar.cn/features/",
            observed_at="2026-07-20T00:00:00Z",
            declared_grade=api_module.EvidenceGrade.C,
            license_status="requires_review",
            principal=Principal("operator-1", frozenset({"operator"})),
            raw_fields_json='{"keyword":"storage box","search_index":81.5}',
            candidate_refs_json='["candidate://storage-box-v1"]',
        )
    )

    assert captured["raw_fields"] == {"keyword": "storage box", "search_index": 81.5}
    assert captured["candidate_refs"] == ["candidate://storage-box-v1"]
    assert result == {"automatic_listing": False, "automatic_procurement": False}


def test_ozon_import_period_is_required_and_duplicate_conflicts_fail_closed(monkeypatch) -> None:
    assert validated_report_period("2025-10-01", "2025-10-31") == {
        "report_period_start": "2025-10-01",
        "report_period_end": "2025-10-31",
    }
    with pytest.raises(HTTPException, match="requires both"):
        validated_report_period("", "2025-10-31")

    monkeypatch.setattr(
        api_module.app.state.runtime,
        "imports",
        SimpleNamespace(
            preview_file=lambda **_: ImportPreview(
                filename="transactions.csv",
                sha256="digest",
                record_type="ozon_fee",
                row_count=1,
                mapping={"external_id": "operation_id"},
                missing_columns=[],
                ready=True,
            ),
        ),
    )
    monkeypatch.setattr(
        api_module.app.state.runtime,
        "scope_grants",
        SimpleNamespace(
            current=lambda **_: {
                "status": "ready",
                "entity_ref": "entity-a",
                "authority_sha256": "a" * 64,
            }
        ),
    )
    monkeypatch.setattr(
        api_module.app.state.runtime,
        "scoped_imports",
        SimpleNamespace(
            find_by_content=lambda *_args, **_kwargs: {
                "evidence_id": "evd-existing"
            }
        ),
    )
    monkeypatch.setattr(
        api_module.app.state.runtime,
        "evidence",
        SimpleNamespace(
            get=lambda _: SimpleNamespace(
                metadata={"report_period_start": "2025-09-01", "report_period_end": "2025-09-30"}
            )
        ),
    )
    upload = UploadFile(file=io.BytesIO(b"same report"), filename="transactions.csv")
    with pytest.raises(HTTPException, match="conflicts") as error:
        asyncio.run(
            api_module.import_ozon(
                file=upload,
                principal=Principal("operator-1", frozenset({"operator"})),
                report_period_start="2025-10-01",
                report_period_end="2025-10-31",
            )
        )
    assert error.value.status_code == 409


def test_ozon_import_preflight_serializes_and_formal_import_fails_before_persistence(monkeypatch) -> None:
    preview = ImportPreview(
        filename="transactions.csv",
        sha256="digest",
        record_type="ozon_fee",
        row_count=1,
        mapping={"external_id": "operation_id"},
        missing_columns=["amount"],
        ready=False,
    )
    import_calls: list[str] = []
    monkeypatch.setattr(
        api_module.app.state.runtime,
        "imports",
        SimpleNamespace(
            preview_file=lambda **_: preview,
        ),
    )
    monkeypatch.setattr(
        api_module.app.state.runtime,
        "scope_grants",
        SimpleNamespace(
            current=lambda **_: {
                "status": "ready",
                "entity_ref": "entity-a",
                "authority_sha256": "a" * 64,
            }
        ),
    )
    monkeypatch.setattr(
        api_module.app.state.runtime,
        "scoped_imports",
        SimpleNamespace(
            find_by_content=lambda *_args, **_kwargs: (
                import_calls.append("find") or None
            )
        ),
    )

    principal = Principal("operator-1", frozenset({"operator"}))
    preflight = asyncio.run(
        api_module.preflight_ozon_import(
            file=UploadFile(file=io.BytesIO(b"report"), filename="transactions.csv"),
            principal=principal,
            report_period_start="2025-10-01",
            report_period_end="2025-10-31",
        )
    )
    assert preflight["missing_columns"] == ["amount"]
    assert preflight["ready"] is False
    assert preflight["report_period_start"] == "2025-10-01"
    assert preflight["scope"]["entity_ref"] == "entity-a"
    assert preflight["formal_fact_promotion_allowed"] is False

    with pytest.raises(HTTPException, match="preflight failed") as error:
        asyncio.run(
            api_module.import_ozon(
                file=UploadFile(file=io.BytesIO(b"report"), filename="transactions.csv"),
                principal=principal,
                report_period_start="2025-10-01",
                report_period_end="2025-10-31",
            )
        )
    assert error.value.status_code == 422
    assert import_calls == []


def test_generic_fee_mapping_endpoint_rejects_ozon_bypass() -> None:
    body = FeeMappingInput(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        evidence_id="not-used-because-the-route-fails-closed",
    )

    with pytest.raises(HTTPException) as error:
        register_fee_mapping(body, Principal("reviewer-1", frozenset({"reviewer"})))

    assert error.value.status_code == 422
    assert "accepted Ozon import" in str(error.value.detail)


def test_profit_growth_and_agent_runtime_read_contracts_are_exposed() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/v1/profit-command/remediation",
        "/v1/seller-os/store-profile-proposal",
        "/v1/growth-channels/capabilities",
        "/v1/agent-control/runtime",
    ):
        assert set(paths[path]) == {"get"}
