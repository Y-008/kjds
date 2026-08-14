from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.primary_source_intake import (
    CONTRACT_ID,
    PrimarySourceIntake,
    PrimarySourceIntakeRow,
    PrimarySourceRecordRow,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

NOW = datetime(2026, 8, 3, 13, tzinfo=UTC)
NOW_QUERY = NOW.isoformat().replace("+00:00", "Z")


class ApiScopeGrants:
    def current(self, *, principal, store_ref, as_of):
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": f"entity-{principal.tenant_ref}",
            "store_ref": store_ref,
            "authority_sha256": (
                "a" * 64 if principal.tenant_ref == "tenant-a" else "b" * 64
            ),
        }


class ApiScopedEvidence:
    def project(self, **_kwargs):
        return {"status": "ready"}


def principal(tenant: str, *roles: str) -> Principal:
    return Principal(
        actor_id=f"actor-{tenant}",
        roles=frozenset(roles or ("admin",)),
        tenant_ref=tenant,
        store_refs=frozenset({"store-a"}),
    )


@pytest.fixture
def api_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            EvidenceBlobRow.__table__,
            EvidenceRecordRow.__table__,
            PrimarySourceIntakeRow.__table__,
            PrimarySourceRecordRow.__table__,
        ],
    )
    service = PrimarySourceIntake(
        engine=engine,
        evidence=EvidenceService(engine),
        scope_grants=ApiScopeGrants(),
        scoped_evidence=ApiScopedEvidence(),
        clock=lambda: NOW,
    )
    active = {"principal": principal("tenant-a")}
    monkeypatch.setattr(runtime, "primary_source_intake", service)
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: active["principal"],
    )
    monkeypatch.setattr(runtime.kill_switch, "ensure_writes_allowed", lambda: None)
    return TestClient(app), active


def body(*, confidence_bps: int = 8700):
    captured = NOW - timedelta(hours=2)
    return {
        "store_ref": "store-a",
        "as_of": NOW.isoformat(),
        "envelope": {
            "source_pack_id": "global_trade_lead_intelligence",
            "source_contract_id": "amazon-seller-export",
            "source_contract_version": "2026-08-03",
            "subject_ref": "subject://api-batch-a",
            "source_locator_ref": "customer-vault://exports/api-batch-a",
            "blob_sha256": "c" * 64,
            "byte_count": 1024,
            "mime_type": "application/json",
            "captured_at": captured.isoformat(),
            "effective_at": captured.isoformat(),
            "acquisition_mode": "account_owner_export",
            "license_or_terms_basis": "account owner export terms v2",
            "allowed_purpose": "B2B market research",
            "jurisdiction": "US",
            "retention_class": "operational",
            "data_classification": "business_public",
            "cross_border_transfer_classification": "domestic_only",
            "parser_version": "lead-normalizer-1",
            "field_count": 16,
            "pagination": {
                "expected_pages": 1,
                "received_pages": 1,
                "failed_page_refs": [],
                "checkpoint_ref": None,
            },
            "integrity": {
                "raw_blob_reverified": True,
                "verifier_id": "sha256-byte-verifier",
                "verifier_version": "1",
                "verified_at": (NOW - timedelta(hours=1)).isoformat(),
            },
            "conservation": {
                "source_total": 1,
                "quarantined_count": 0,
                "duplicate_count": 0,
            },
            "review_due_at": (NOW + timedelta(days=30)).isoformat(),
        },
        "records": [
            {
                "source_family": "阿里巴巴国际站",
                "marketplace_or_site": "alibaba.com",
                "business_entity_name": "Acme Trading LLC",
                "country_or_region": "US",
                "category": "home-and-kitchen",
                "public_business_url": "https://seller.example/store/acme",
                "entity_type": "prospect_account",
                "signal_type": "seller_presence",
                "signal_observed_at": captured.isoformat(),
                "license_or_terms_basis": "official public business page terms v3",
                "contact_ref": None,
                "contact_purpose_basis": "not_applicable",
                "jurisdiction": "US",
                "do_not_contact_status": "unknown",
                "confidence_bps": confidence_bps,
                "evidence_refs": [],
            }
        ],
    }


def post(client, *, key="api-batch-a", payload=None):
    return client.post(
        "/v1/primary-source-intakes",
        headers={"X-KJDS-API-Key": "test", "Idempotency-Key": key},
        json=payload or body(),
    )


def test_primary_source_api_admit_list_and_get(api_client):
    client, _active = api_client
    response = post(client)
    assert response.status_code == 201
    payload = response.json()
    assert payload["contract_id"] == CONTRACT_ID
    assert payload["records"][0]["source_family"] == "alibaba_com"
    assert payload["intake"]["raw_source_retained"] is False
    assert "tenant_ref" not in payload["intake"]
    assert "entity_ref" not in payload["intake"]
    intake_ref = payload["intake"]["intake_ref"]

    query = f"store_ref=store-a&as_of={NOW_QUERY}"
    listed = client.get(
        f"/v1/primary-source-intakes?{query}",
        headers={"X-KJDS-API-Key": "test"},
    )
    assert listed.status_code == 200
    assert [item["intake_ref"] for item in listed.json()["items"]] == [intake_ref]
    fetched = client.get(
        f"/v1/primary-source-intakes/{intake_ref}?{query}",
        headers={"X-KJDS-API-Key": "test"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["records"][0]["business_entity_name"] == "Acme Trading LLC"


def test_primary_source_api_idempotency_drift_is_409(api_client):
    client, _active = api_client
    first = post(client)
    replay = post(client)
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["intake"]["idempotent_replay"] is True
    drift = post(client, payload=body(confidence_bps=8600))
    assert drift.status_code == 409


def test_primary_source_api_cross_tenant_is_404(api_client):
    client, active = api_client
    intake_ref = post(client).json()["intake"]["intake_ref"]
    active["principal"] = principal("tenant-b", "monitor")
    response = client.get(
        f"/v1/primary-source-intakes/{intake_ref}"
        f"?store_ref=store-a&as_of={NOW_QUERY}",
        headers={"X-KJDS-API-Key": "test"},
    )
    assert response.status_code == 404
    listed = client.get(
        f"/v1/primary-source-intakes?store_ref=store-a&as_of={NOW_QUERY}",
        headers={"X-KJDS-API-Key": "test"},
    )
    assert listed.status_code == 200
    assert listed.json()["items"] == []


def test_primary_source_api_rejects_scope_override_raw_contact_and_wrong_role(
    api_client,
):
    client, active = api_client
    extra = body()
    extra["tenant_ref"] = "tenant-b"
    assert post(client, payload=extra).status_code == 422

    raw_contact = body()
    raw_contact["records"][0]["contact_ref"] = "buyer@example.com"
    assert post(client, key="raw-contact", payload=raw_contact).status_code == 422

    active["principal"] = principal("tenant-a", "monitor")
    assert post(client, key="wrong-role").status_code == 403


def test_primary_source_openapi_is_frozen_and_scope_is_server_derived():
    schema = app.openapi()
    snapshot = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "project"
            / "contracts"
            / "openapi-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert schema == snapshot
    expected = {
        "/v1/primary-source-intakes": {"get", "post"},
        "/v1/primary-source-intakes/{intake_ref}": {"get"},
    }
    for path, methods in expected.items():
        assert set(schema["paths"][path]) == methods
        for method in methods:
            operation = schema["paths"][path][method]
            assert operation["security"] == [{"KjdsApiKey": []}]
            serialized = json.dumps(operation, sort_keys=True)
            assert "tenant_ref" not in serialized
            assert "entity_ref" not in serialized
            assert "scope_authority" not in serialized
