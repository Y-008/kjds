from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.browser_capture_inbox import (
    BrowserCaptureInbox,
    BrowserCaptureSubmissionRow,
)
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.evidence_scope import (
    BINDING_CONTRACT,
    ScopedEvidenceAuthority,
)
from apps.control_plane.intelligence_ingestion import (
    IntelligenceSourceAdapterRegistry,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.security import (
    AuthenticationFailure,
    Principal,
)
from apps.control_plane.sql_repository import Base

AS_OF = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    return engine


def principal(
    *,
    tenant_ref: str = "tenant-a",
    stores: frozenset[str] = frozenset({"store-a"}),
) -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=stores,
    )


def entity_scope(*, ready: bool = False) -> dict:
    if ready:
        return {
            "status": "ready",
            "entity_ref": "entity-a",
            "authority_sha256": "a" * 64,
        }
    return {
        "status": "no_data",
        "entity_ref": None,
        "authority_sha256": None,
        "reason": "entity_scope_authority_missing",
    }


def envelope(
    *,
    idempotency_key: str = "capture-1688-100-black",
    displayed_price: str = "19.90",
) -> dict:
    return {
        "contract_version": "kjds-browser-capture-envelope/1.0",
        "source_profile": "browser_observation",
        "marketplace": "1688",
        "store_ref": "store-a",
        "source_url": "https://detail.1688.com/offer/100.html",
        "observed_at": "2026-07-29T03:30:00Z",
        "idempotency_key": idempotency_key,
        "page": {
            "title": "黑色收纳盒",
            "canonical_url": "https://detail.1688.com/offer/100.html",
            "language": "zh-CN",
            "extractor_version": "kjds-visible-dom/1.0",
            "capture_mode": "active_tab_visible_dom",
        },
        "items": [
            {
                "external_item_id": "100",
                "supplier_ref": "supplier-100",
                "title": "黑色收纳盒",
                "variant_key": "color=black",
                "currency": "CNY",
                "displayed_price": displayed_price,
                "price_scope": "unit_price",
                "price_kind": "public_display_price",
                "min_order_quantity": 1,
                "availability": "in_stock",
                "specifications": {"color": "black"},
                "product_identity": {"external_item_id": "100"},
                "media_rights_status": "unverified_external_reference",
            }
        ],
        "confirmed": True,
    }


def services():
    engine = database()
    evidence = EvidenceService(engine)
    scoped = ScopedEvidenceAuthority(evidence=evidence)
    inbox = BrowserCaptureInbox(
        engine=engine,
        evidence=evidence,
        scoped_evidence=scoped,
        source_adapters=IntelligenceSourceAdapterRegistry(),
    )
    return engine, evidence, inbox


def test_preflight_is_zero_write_and_missing_entity_remains_explicit():
    engine, _, inbox = services()

    result = inbox.preflight(
        envelope(),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )

    assert result["status"] == "ready_with_constraints"
    assert result["capture_allowed"] is True
    assert result["capture_state_if_saved"] == "quarantined"
    assert result["normalized"]["scope"]["tenant_ref"] == "tenant-a"
    assert result["normalized"]["scope"]["entity_ref"] is None
    assert result["normalized"]["scope"]["store_ref"] == "store-a"
    assert result["promotion_readiness"]["status"] == "no_data"
    assert result["control_envelope"]["external_write_allowed"] is False
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(
                    BrowserCaptureSubmissionRow
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EvidenceRecordRow)
            )
            == 0
        )


def test_submit_captures_immutable_evidence_without_entity_or_business_write():
    engine, evidence, inbox = services()

    created = inbox.submit(
        envelope(),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )
    replay = inbox.submit(
        envelope(),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )

    assert replay["id"] == created["id"]
    assert created["status"] == "quarantined"
    assert created["scope"]["entity_ref"] is None
    assert created["evidence"]["grade"] == "C"
    assert created["evidence"]["integrity_status"] == "ready"
    assert created["promotion_readiness"]["status"] == "no_data"
    assert created["control_envelope"] == {
        "internal_evidence_write_only": True,
        "formal_observation_created": False,
        "supplier_offer_created": False,
        "actual_cost_created": False,
        "product_created": False,
        "listing_created": False,
        "approval_created": False,
        "permit_created": False,
        "external_write_allowed": False,
    }
    content, record = evidence.content(created["evidence"]["evidence_id"])
    artifact = json.loads(content)
    assert record.sha256 == created["evidence"]["sha256"]
    assert artifact["scope"]["entity_ref"] is None
    assert artifact["semantic_limits"]["supplier_offer_created"] is False
    assert artifact["items"][0]["price_scope"] == "unit_price"
    assert artifact["items"][0]["unit_price"] == "19.90"
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(
                    BrowserCaptureSubmissionRow
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EvidenceRecordRow)
            )
            == 1
        )

    changed = envelope(displayed_price="20.90")
    with pytest.raises(ValueError, match="different immutable content"):
        inbox.submit(
            changed,
            principal=principal(),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )


def test_ready_entity_still_requires_independent_evidence_binding():
    _, evidence, inbox = services()
    ready_scope = entity_scope(ready=True)

    created = inbox.submit(
        envelope(),
        principal=principal(),
        entity_scope=ready_scope,
        as_of=AS_OF,
    )

    assert created["status"] == "pending_independent_binding"
    assert created["scope"]["entity_ref"] == "entity-a"
    assert created["promotion_readiness"]["status"] == "blocked"
    assert "evidence_scope_binding_missing" in (
        created["promotion_readiness"]["source_gaps"]
    )

    target = evidence.get(created["evidence"]["evidence_id"])
    evidence.capture(
        content=b"independent exact-scope browser capture review",
        filename="browser-capture-scope-review.txt",
        content_type="text/plain",
        source="independent-scope-review",
        source_ref=f"internal://browser-capture-binding/{target.id}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-29T03:40:00Z",
        effective_until=None,
        created_by="binding-recorder",
        metadata={
            "evidence_scope_contract_id": BINDING_CONTRACT,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "reviewed_by": "independent-reviewer",
        },
    )
    listed = inbox.list(
        principal=principal(),
        entity_scope=ready_scope,
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert listed["status"] == "ready"
    assert listed["counts"]["ready_for_promotion"] == 1
    assert listed["items"][0]["promotion_readiness"]["status"] == "ready"
    assert listed["items"][0]["promotion_readiness"][
        "observation_promotion_route_exposed"
    ] is False


def test_unselected_variant_remains_blocked_after_independent_binding():
    _, evidence, inbox = services()
    ready_scope = entity_scope(ready=True)
    unselected = envelope(idempotency_key="capture-unselected")
    unselected["items"][0]["variant_key"] = "unselected"

    preflight = inbox.preflight(
        unselected,
        principal=principal(),
        entity_scope=ready_scope,
        as_of=AS_OF,
    )
    assert "variant_selection_unverified" in (
        preflight["promotion_readiness"]["source_gaps"]
    )

    created = inbox.submit(
        unselected,
        principal=principal(),
        entity_scope=ready_scope,
        as_of=AS_OF,
    )
    target = evidence.get(created["evidence"]["evidence_id"])
    evidence.capture(
        content=b"independent exact-scope browser capture review",
        filename="browser-capture-unselected-scope-review.txt",
        content_type="text/plain",
        source="independent-scope-review",
        source_ref=f"internal://browser-capture-binding/{target.id}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-29T03:40:00Z",
        effective_until=None,
        created_by="binding-recorder",
        metadata={
            "evidence_scope_contract_id": BINDING_CONTRACT,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "reviewed_by": "independent-reviewer",
        },
    )
    listed = inbox.list(
        principal=principal(),
        entity_scope=ready_scope,
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert listed["counts"]["ready_for_promotion"] == 0
    assert listed["items"][0]["promotion_readiness"]["status"] == "blocked"
    assert "variant_selection_unverified" in (
        listed["items"][0]["promotion_readiness"]["source_gaps"]
    )


def test_host_time_checkout_and_scope_validation_fail_closed():
    _, _, inbox = services()
    wrong_host = envelope()
    wrong_host["source_url"] = "https://example.com/offer/100"
    with pytest.raises(ValueError, match="outside the frozen source adapter"):
        inbox.preflight(
            wrong_host,
            principal=principal(),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )

    future = envelope()
    future["observed_at"] = "2026-07-29T05:00:00Z"
    with pytest.raises(ValueError, match="future"):
        inbox.preflight(
            future,
            principal=principal(),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )

    checkout = envelope()
    checkout["items"][0].update(
        {
            "price_kind": "observed_checkout_price",
            "price_scope": "checkout_total",
            "observed_quantity": 3,
            "displayed_price": "59.70",
            "checkout_verified": False,
            "purchase_available": True,
            "tax_included": True,
            "domestic_freight_included": False,
        }
    )
    with pytest.raises(
        ValueError,
        match="checkout verification",
    ):
        inbox.preflight(
            checkout,
            principal=principal(),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )

    with pytest.raises(PermissionError, match="not authorized"):
        inbox.preflight(
            envelope(),
            principal=principal(stores=frozenset({"store-b"})),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )


def test_integrity_adapter_drift_and_database_partial_scope_are_blocked(
    monkeypatch,
):
    engine, _, inbox = services()
    created = inbox.submit(
        envelope(),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.execute(
            update(BrowserCaptureSubmissionRow)
            .where(BrowserCaptureSubmissionRow.id == created["id"])
            .values(entity_ref="fabricated-entity")
        )

    with Session(engine) as session, session.begin():
        evidence_id = created["evidence"]["evidence_id"]
        blob_sha = session.scalar(
            select(EvidenceRecordRow.blob_sha256).where(
                EvidenceRecordRow.id == evidence_id
            )
        )
        session.execute(
            update(EvidenceBlobRow)
            .where(EvidenceBlobRow.sha256 == blob_sha)
            .values(content_bytes=b"tampered")
        )
    broken = inbox.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    assert broken["items"][0]["evidence"]["integrity_status"] == "blocked"
    assert "capture_evidence_integrity_invalid" in (
        broken["items"][0]["promotion_readiness"]["source_gaps"]
    )

    monkeypatch.setattr(
        inbox.source_adapters,
        "browser_capture_contract",
        lambda **_: (_ for _ in ()).throw(ValueError("retired")),
    )
    drifted = inbox.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    assert "source_adapter_unavailable" in (
        drifted["items"][0]["promotion_readiness"]["source_gaps"]
    )


def test_browser_capture_routes_are_authenticated_scoped_and_canonical(
    monkeypatch,
):
    captured: dict = {}
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal(),
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_: entity_scope(),
    )

    def fake_preflight(body, **values):
        captured.update({"body": body, **values})
        return {
            "status": "ready_with_constraints",
            "capture_allowed": True,
            "external_write_allowed": False,
        }

    monkeypatch.setattr(
        runtime.browser_capture_inbox,
        "preflight",
        fake_preflight,
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    accepted = client.post(
        "/v1/browser-capture-inbox/preflight",
        json=envelope(),
        headers=headers,
    )
    forbidden = client.post(
        "/v1/browser-capture-inbox/preflight",
        json={**envelope(), "store_ref": "store-b"},
        headers=headers,
    )

    assert accepted.status_code == 200
    assert captured["principal"].tenant_ref == "tenant-a"
    assert captured["entity_scope"]["entity_ref"] is None
    assert forbidden.status_code == 403
    assert app.openapi()["paths"][
        "/v1/browser-capture-inbox/submissions"
    ]["post"]["security"] == [{"KjdsApiKey": []}]


def test_browser_capture_route_rejects_anonymous(monkeypatch):
    def reject(_key):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    response = TestClient(app).get(
        "/v1/browser-capture-inbox/submissions",
        params={"store_ref": "store-a"},
    )
    assert response.status_code == 401
