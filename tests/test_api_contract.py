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
            find_by_content=lambda _: SimpleNamespace(evidence_id="evd-existing"),
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
            find_by_content=lambda _: import_calls.append("find") or None,
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
