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


def variant_matrix_envelope() -> dict:
    base = {
        "contract_version": "kjds-browser-capture-envelope/1.2",
        "source_profile": "browser_observation",
        "marketplace": "1688",
        "store_ref": "store-a",
        "source_url": "https://detail.1688.com/offer/38547222320.html",
        "observed_at": "2026-07-29T03:30:00Z",
        "idempotency_key": "capture-1688-38547222320-matrix",
        "page": {
            "title": "加厚牛津布旅行收纳六件套",
            "canonical_url": (
                "https://detail.1688.com/offer/38547222320.html"
            ),
            "language": "zh-CN",
            "extractor_version": "kjds-visible-dom/1.2",
            "capture_mode": "active_tab_visible_dom",
            "capture_kind": "product_detail_variant_matrix",
            "provider_id": "1688-current-document-provider",
            "provider_version": "1.0.0",
            "structured_data_source": "serialized_ssr_window.context",
            "capture_coverage": {
                "discovered_count": 2,
                "captured_count": 2,
                "truncated": False,
                "exact_sku_identity_count": 2,
            },
        },
        "merchant": {
            "supplier_ref": "戴贺喜188",
            "company_name": "义乌市喜哥日用品厂",
            "login_id": "戴贺喜188",
            "public_signals": {
                "service_score": "4.5",
                "repeat_rate_3m": "69.96%",
                "good_rate_percent": "98.8%",
            },
        },
        "items": [],
        "confirmed": True,
    }
    common = {
        "external_item_id": "38547222320",
        "supplier_ref": "戴贺喜188",
        "title": "加厚牛津布旅行收纳六件套",
        "currency": "CNY",
        "price_scope": "unit_price",
        "price_kind": "public_display_price",
        "min_order_quantity": 1,
        "availability": "in_stock",
        "observed_quantity": None,
        "checkout_verified": False,
        "tax_included": None,
        "domestic_freight_included": None,
        "purchase_available": False,
        "confidence": "0.92",
        "media_rights_status": "unverified_external_reference",
        "source_url": "https://detail.1688.com/offer/38547222320.html",
    }
    base["items"] = [
        {
            **common,
            "variant_key": "颜色:西瓜红三件套收纳袋",
            "displayed_price": "3.90",
            "specifications": {
                "货号": "A-2-1",
                "selected_variant": "颜色:西瓜红三件套收纳袋",
            },
            "product_identity": {
                "offer_id": "38547222320",
                "sku_id": "sku-3",
                "spec_id": "spec-3",
                "item_code": "A-2-1",
            },
            "comparison_dimensions": {
                "category_id": "1036894",
                "pack_count": "3",
                "material": "防水加厚牛津布",
                "trade_unit": "件",
            },
            "market_signals": {"sku_sale_count_signal": 2},
            "supply_signals": {
                "stock_count": 470,
                "advertised_price_range": "3.90-9.90",
                "price_tiers": [
                    {"minimum_quantity": 1, "price": "3.90"}
                ],
            },
        },
        {
            **common,
            "variant_key": "颜色:宝蓝六件套",
            "displayed_price": "9.90",
            "specifications": {
                "货号": "A-2-1",
                "selected_variant": "颜色:宝蓝六件套",
            },
            "product_identity": {
                "offer_id": "38547222320",
                "sku_id": "sku-6",
                "spec_id": "spec-6",
                "item_code": "A-2-1",
            },
            "comparison_dimensions": {
                "category_id": "1036894",
                "pack_count": "6",
                "material": "防水加厚牛津布",
                "trade_unit": "件",
            },
            "market_signals": {"sku_sale_count_signal": 10},
            "supply_signals": {
                "stock_count": 13,
                "advertised_price_range": "3.90-9.90",
                "price_tiers": [
                    {"minimum_quantity": 1, "price": "9.90"}
                ],
            },
        },
    ]
    return base


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

    def fake_list(**values):
        captured["list"] = values
        return {
            "contract_id": "kjds-browser-capture-inbox/1.0",
            "status": "no_data",
            "items": [],
        }

    monkeypatch.setattr(
        runtime.browser_capture_inbox,
        "list",
        fake_list,
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    accepted = client.post(
        "/v1/browser-capture-inbox/preflight",
        json=envelope(),
        headers=headers,
    )
    accepted_v12 = client.post(
        "/v1/browser-capture-inbox/preflight",
        json=variant_matrix_envelope(),
        headers=headers,
    )
    forbidden = client.post(
        "/v1/browser-capture-inbox/preflight",
        json={**envelope(), "store_ref": "store-b"},
        headers=headers,
    )
    listed = client.get(
        "/v1/browser-capture-inbox/submissions",
        params={"store_ref": "store-a", "reference_quantity": 300},
        headers=headers,
    )
    invalid_quantity = client.get(
        "/v1/browser-capture-inbox/submissions",
        params={"store_ref": "store-a", "reference_quantity": 0},
        headers=headers,
    )

    assert accepted.status_code == 200
    assert accepted_v12.status_code == 200
    assert captured["body"]["contract_version"] == (
        "kjds-browser-capture-envelope/1.2"
    )
    assert captured["body"]["merchant"]["login_id"] == "戴贺喜188"
    assert len(captured["body"]["items"]) == 2
    assert captured["principal"].tenant_ref == "tenant-a"
    assert captured["entity_scope"]["entity_ref"] is None
    assert forbidden.status_code == 403
    assert listed.status_code == 200
    assert captured["list"]["reference_quantity"] == 300
    assert invalid_quantity.status_code == 422
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


def test_v12_variant_matrix_preserves_exact_sku_mapping_and_erp_staging():
    _, _, inbox = services()

    result = inbox.preflight(
        variant_matrix_envelope(),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )

    normalized = result["normalized"]
    assert normalized["merchant"]["login_id"] == "戴贺喜188"
    assert normalized["page"]["capture_coverage"]["captured_count"] == 2
    by_sku = {
        item["product_identity"]["sku_id"]: item
        for item in normalized["items"]
    }
    assert by_sku["sku-3"]["unit_price"] == "3.90"
    assert by_sku["sku-3"]["product_identity"]["spec_id"] == "spec-3"
    assert by_sku["sku-3"]["supply_signals"]["stock_count"] == 470
    assert by_sku["sku-3"]["price_tiers"] == [
        {"minimum_quantity": 1, "price": "3.90"}
    ]
    assert by_sku["sku-6"]["unit_price"] == "9.90"
    assert by_sku["sku-6"]["market_signals"][
        "sku_sale_count_signal"
    ] == 10
    summary = normalized["variant_summary"][0]
    assert summary["variant_count"] == 2
    assert summary["minimum_unit_price"] == "3.90"
    assert summary["minimum_variants"][0]["sku_id"] == "sku-3"
    assert len(summary["comparison_groups"]) == 2
    assert {
        group["comparison_dimensions"]["pack_count"]
        for group in summary["comparison_groups"]
    } == {"3", "6"}
    assert normalized["erp_staging"]["status"] == "exact_variant_staged"
    assert normalized["erp_staging"]["contract_id"] == (
        "kjds-erp-sourcing-staging/1.1"
    )
    assert normalized["erp_staging"]["exact_variant_count"] == 2
    assert {
        (row["sku_id"], row["spec_id"], row["unit_price"])
        for row in normalized["erp_staging"]["rows"]
    } == {
        ("sku-3", "spec-3", "3.90"),
        ("sku-6", "spec-6", "9.90"),
    }
    staged_by_sku = {
        row["sku_id"]: row for row in normalized["erp_staging"]["rows"]
    }
    sku_3 = staged_by_sku["sku-3"]
    assert sku_3["source_observed_at"] == "2026-07-29T03:30:00+00:00"
    assert sku_3["supplier_public_profile"] == normalized["merchant"]
    assert sku_3["supplier_public_profile"]["public_signals"][
        "repeat_rate_3m"
    ] == "69.96%"
    assert sku_3["source_capture"]["capture_kind"] == (
        "product_detail_variant_matrix"
    )
    assert sku_3["source_capture"]["capture_coverage"] == normalized[
        "page"
    ]["capture_coverage"]
    assert sku_3["product_identity"] == by_sku["sku-3"][
        "product_identity"
    ]
    assert sku_3["specifications"] == by_sku["sku-3"][
        "specifications"
    ]
    assert sku_3["comparison_dimensions"] == by_sku["sku-3"][
        "comparison_dimensions"
    ]
    assert sku_3["min_order_quantity"] == 1
    assert sku_3["availability"] == "in_stock"
    assert sku_3["supply_signals"]["stock_count"] == 470
    assert sku_3["price_tiers"] == [
        {"minimum_quantity": 1, "price": "3.90"}
    ]
    assert sku_3["market_signals"]["sku_sale_count_signal"] == 2
    assert sku_3["checkout_verified"] is False
    assert sku_3["tax_included"] is None
    assert sku_3["domestic_freight_included"] is None
    assert sku_3["purchase_available"] is False
    assert sku_3["source_observation"] == by_sku["sku-3"]
    assert sku_3["source_observation"]["item_sha256"] == (
        sku_3["item_sha256"]
    )
    assert normalized["erp_staging"]["formal_product_write"] is False
    assert normalized["erp_staging"]["supplier_offer_write"] is False
    assert normalized["erp_staging"]["external_write"] is False
    assert normalized["semantic_limits"]["supplier_offer_created"] is False
    assert normalized["semantic_limits"]["sales_fact_inferred"] is False


def test_v12_rejects_merchant_identity_drift_and_coverage_mismatch():
    _, _, inbox = services()
    merchant_drift = variant_matrix_envelope()
    merchant_drift["merchant"]["supplier_ref"] = "other-supplier"
    with pytest.raises(ValueError, match="merchant supplier_ref"):
        inbox.preflight(
            merchant_drift,
            principal=principal(),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )

    coverage_drift = variant_matrix_envelope()
    coverage_drift["page"]["capture_coverage"]["captured_count"] = 1
    with pytest.raises(ValueError, match="full SKU matrix"):
        inbox.preflight(
            coverage_drift,
            principal=principal(),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )

    missing_spec = variant_matrix_envelope()
    del missing_spec["items"][1]["product_identity"]["spec_id"]
    with pytest.raises(ValueError, match="requires sku_id and spec_id"):
        inbox.preflight(
            missing_spec,
            principal=principal(),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )

    duplicate_tiers = variant_matrix_envelope()
    duplicate_tiers["items"][0]["supply_signals"]["price_tiers"] = [
        {"minimum_quantity": 1, "price": "3.90"},
        {"minimum_quantity": 1, "price": "9.90"},
    ]
    with pytest.raises(ValueError, match="must be unique"):
        inbox.preflight(
            duplicate_tiers,
            principal=principal(),
            entity_scope=entity_scope(),
            as_of=AS_OF,
        )


def test_quantity_price_requires_an_applicable_public_tier():
    _, _, inbox = services()
    value = variant_matrix_envelope()
    value["idempotency_key"] = "capture-1688-quantity-tier-gap"
    value["items"] = [value["items"][1]]
    value["items"][0]["supply_signals"]["price_tiers"] = [
        {"minimum_quantity": 5, "price": "8.00"},
    ]
    value["page"]["capture_coverage"] = {
        "discovered_count": 1,
        "captured_count": 1,
        "truncated": False,
        "exact_sku_identity_count": 1,
    }
    inbox.submit(
        value,
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )

    quantity_1 = inbox.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        reference_quantity=1,
    )["sourcing_comparison"]
    quantity_5 = inbox.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        reference_quantity=5,
    )["sourcing_comparison"]

    row_at_1 = quantity_1["groups"][0]["rows"][0]
    row_at_5 = quantity_5["groups"][0]["rows"][0]
    assert row_at_1["eligibility"] == "quantity_price_unverified"
    assert row_at_1["effective_unit_price"] is None
    assert row_at_1["effective_price_source"] == (
        "no_public_price_tier_for_quantity"
    )
    assert row_at_5["eligibility"] == "eligible_public_display_price"
    assert row_at_5["effective_unit_price"] == "8.00"
    assert row_at_5["applied_price_tier_minimum_quantity"] == 5


def test_v12_candidate_cards_reach_erp_only_as_detail_enrichment_queue():
    _, _, inbox = services()
    candidate = variant_matrix_envelope()
    candidate["idempotency_key"] = "capture-1688-search-candidates"
    candidate["page"]["capture_kind"] = "search_result_candidates"
    candidate["page"]["structured_data_source"] = (
        "visible_current_page_product_cards"
    )
    candidate["merchant"] = None
    candidate["items"] = [candidate["items"][0]]
    candidate["items"][0]["variant_key"] = "unselected"
    candidate["items"][0]["product_identity"] = {
        "offer_id": "38547222320",
        "identity_resolution": "offer_only",
    }
    candidate["items"][0]["comparison_dimensions"] = {}
    candidate["page"]["capture_coverage"] = {
        "discovered_count": 1,
        "captured_count": 1,
        "truncated": False,
        "exact_sku_identity_count": 0,
    }

    result = inbox.preflight(
        candidate,
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )

    staging = result["normalized"]["erp_staging"]
    assert staging["status"] == "partial_requires_detail_enrichment"
    assert staging["exact_variant_count"] == 0
    assert staging["rows"][0]["mapping_status"] == (
        "requires_detail_enrichment"
    )
    assert staging["rows"][0]["market_signals"] == {
        "sku_sale_count_signal": 2
    }
    assert staging["rows"][0]["supply_signals"]["stock_count"] == 470
    assert staging["rows"][0]["source_observation"] == result[
        "normalized"
    ]["items"][0]
    assert staging["rows"][0]["supplier_public_profile"] is None
    assert "variant_selection_unverified" in result[
        "promotion_readiness"
    ]["source_gaps"]


def test_list_compares_latest_exact_offers_and_respects_reference_moq():
    _, _, inbox = services()

    def exact_offer(
        *,
        offer_id: str,
        supplier_ref: str,
        price: str,
        moq: int,
        observed_at: str,
        idempotency_key: str,
        price_tiers: list[dict] | None = None,
    ) -> dict:
        value = json.loads(json.dumps(variant_matrix_envelope()))
        value["observed_at"] = observed_at
        value["idempotency_key"] = idempotency_key
        value["source_url"] = (
            f"https://detail.1688.com/offer/{offer_id}.html"
        )
        value["page"]["canonical_url"] = value["source_url"]
        value["page"]["capture_coverage"] = {
            "discovered_count": 1,
            "captured_count": 1,
            "truncated": False,
            "exact_sku_identity_count": 1,
        }
        value["merchant"] = {
            "supplier_ref": supplier_ref,
            "company_name": f"供应商 {supplier_ref}",
            "login_id": supplier_ref,
            "public_signals": {},
        }
        item = value["items"][1]
        item["external_item_id"] = offer_id
        item["supplier_ref"] = supplier_ref
        item["displayed_price"] = price
        item["min_order_quantity"] = moq
        if price_tiers is not None:
            item.setdefault("supply_signals", {})["price_tiers"] = (
                price_tiers
            )
        item["source_url"] = value["source_url"]
        item["product_identity"] = {
            **item["product_identity"],
            "offer_id": offer_id,
            "sku_id": f"sku-{offer_id}",
            "spec_id": f"spec-{offer_id}",
        }
        value["items"] = [item]
        return value

    inbox.submit(
        variant_matrix_envelope(),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )
    inbox.submit(
        exact_offer(
            offer_id="200",
            supplier_ref="supplier-200",
            price="8.50",
            moq=1,
            observed_at="2026-07-29T03:31:00Z",
            idempotency_key="capture-offer-200-old",
        ),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )
    inbox.submit(
        exact_offer(
            offer_id="400",
            supplier_ref="supplier-400-old",
            price="7.50",
            moq=1,
            observed_at="2026-07-29T03:34:00Z",
            idempotency_key="capture-offer-400-old-supplier",
        ),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )
    inbox.submit(
        exact_offer(
            offer_id="400",
            supplier_ref="supplier-400-drift",
            price="7.40",
            moq=1,
            observed_at="2026-07-29T03:35:00Z",
            idempotency_key="capture-offer-400-supplier-drift",
        ),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )
    inbox.submit(
        exact_offer(
            offer_id="200",
            supplier_ref="supplier-200",
            price="8.40",
            moq=1,
            observed_at="2026-07-29T03:32:00Z",
            idempotency_key="capture-offer-200-latest",
            price_tiers=[
                {"minimum_quantity": 1, "price": "8.40"},
                {"minimum_quantity": 100, "price": "8.00"},
            ],
        ),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )
    inbox.submit(
        exact_offer(
            offer_id="300",
            supplier_ref="supplier-300",
            price="3.80",
            moq=300,
            observed_at="2026-07-29T03:33:00Z",
            idempotency_key="capture-offer-300-moq",
            price_tiers=[
                {"minimum_quantity": 300, "price": "3.80"},
                {"minimum_quantity": 500, "price": "3.50"},
            ],
        ),
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )
    candidate = json.loads(json.dumps(variant_matrix_envelope()))
    candidate["idempotency_key"] = "capture-search-queue"
    candidate["source_url"] = (
        "https://s.1688.com/selloffer/offer_search.htm?keywords=bag"
    )
    candidate["page"]["canonical_url"] = candidate["source_url"]
    candidate["page"]["capture_kind"] = "search_result_candidates"
    candidate["page"]["structured_data_source"] = (
        "visible_current_page_product_cards"
    )
    candidate["page"]["capture_coverage"] = {
        "discovered_count": 1,
        "captured_count": 1,
        "truncated": False,
        "exact_sku_identity_count": 0,
    }
    candidate["merchant"] = None
    candidate_item = candidate["items"][0]
    candidate_item["variant_key"] = "unselected"
    candidate_item["product_identity"] = {
        "offer_id": candidate_item["external_item_id"],
        "identity_resolution": "offer_only",
    }
    candidate_item["comparison_dimensions"] = {}
    candidate["items"] = [candidate_item]
    inbox.submit(
        candidate,
        principal=principal(),
        entity_scope=entity_scope(),
        as_of=AS_OF,
    )

    listed = inbox.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    comparison = listed["sourcing_comparison"]
    six_piece = next(
        group
        for group in comparison["groups"]
        if group["comparison_dimensions"].get("pack_count") == "6"
    )

    assert comparison["contract_id"] == "kjds-sourcing-comparison/1.1"
    assert comparison["reference_quantity"] == 1
    assert comparison["latest_exact_offer_count"] == 3
    assert comparison["supplier_drift_offer_count"] == 1
    assert comparison["candidate_capture_count"] == 1
    assert comparison["candidate_row_count"] == 1
    assert six_piece["status"] == "comparable"
    assert six_piece["exact_offer_count"] == 3
    assert six_piece["eligible_offer_count"] == 2
    assert six_piece["minimum_eligible_unit_price"] == "8.40"
    assert {row["unit_price"] for row in six_piece["rows"]} == {
        "3.80",
        "8.40",
        "9.90",
    }
    assert all(row["offer_id"] != "400" for row in six_piece["rows"])
    assert six_piece["lowest_rows"][0]["offer_id"] == "200"
    high_moq = next(
        row for row in six_piece["rows"] if row["offer_id"] == "300"
    )
    assert high_moq["eligibility"] == "reference_quantity_below_moq"
    assert high_moq["effective_unit_price"] is None
    assert high_moq["price_tiers"] == [
        {"minimum_quantity": 300, "price": "3.80"},
        {"minimum_quantity": 500, "price": "3.50"},
    ]

    quantity_300 = inbox.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        reference_quantity=300,
    )["sourcing_comparison"]
    six_piece_300 = next(
        group
        for group in quantity_300["groups"]
        if group["comparison_dimensions"].get("pack_count") == "6"
    )
    offer_200_at_300 = next(
        row for row in six_piece_300["rows"] if row["offer_id"] == "200"
    )
    offer_300_at_300 = next(
        row for row in six_piece_300["rows"] if row["offer_id"] == "300"
    )
    assert quantity_300["reference_quantity"] == 300
    assert six_piece_300["eligible_offer_count"] == 3
    assert six_piece_300["minimum_eligible_unit_price"] == "3.80"
    assert offer_200_at_300["unit_price"] == "8.40"
    assert offer_200_at_300["effective_unit_price"] == "8.00"
    assert offer_200_at_300["applied_price_tier_minimum_quantity"] == 100
    assert offer_300_at_300["effective_unit_price"] == "3.80"
    assert offer_300_at_300["eligibility"] == (
        "eligible_public_display_price"
    )
    assert six_piece_300["lowest_rows"][0]["offer_id"] == "300"
    assert comparison["formal_cost_created"] is False
    assert comparison["freight_included"] is False
    assert comparison["tax_included"] is False
    assert comparison["external_write"] is False
    with pytest.raises(ValueError, match="reference_quantity"):
        inbox.list(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=AS_OF,
            reference_quantity=0,
        )
