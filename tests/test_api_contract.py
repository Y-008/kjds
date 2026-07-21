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
