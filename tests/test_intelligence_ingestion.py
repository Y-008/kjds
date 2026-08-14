from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
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
from apps.control_plane.marketplace_observation import (
    MarketplaceObservationSnapshotRow,
    MarketplaceObservationWorkspace,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_marketplace_observation import (
    ScopedMarketplaceObservationAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.sql_repository import Base

AS_OF = datetime(2026, 7, 28, 5, tzinfo=UTC)


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


def entity_scope(
    *,
    entity_ref: str = "entity-a",
    authority_sha256: str = "a" * 64,
) -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": authority_sha256,
    }


def observation_request(
    *,
    idempotency_key: str = "native-observation-1",
    displayed_price: str = "19.90",
    source_profile: str = "browser_observation",
) -> dict:
    return {
        "source_profile": source_profile,
        "marketplace": "1688",
        "store_ref": "store-a",
        "source_url": "https://detail.1688.com/offer/100.html",
        "observed_at": "2026-07-28T04:00:00Z",
        "idempotency_key": idempotency_key,
        "confirmed": True,
        "items": [
            {
                "external_item_id": "100",
                "supplier_ref": "supplier-100",
                "title": "allowed public observation",
                "variant_key": "black-3-pack",
                "currency": "CNY",
                "displayed_price": displayed_price,
                "price_kind": "public_display_price",
                "min_order_quantity": 1,
                "availability": "in_stock",
                "specifications": {"color": "black", "quantity": "3"},
            }
        ],
    }


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


def scope_authority(
    *,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    grant_sha256: str = "a" * 64,
) -> dict:
    return {
        "tenant_ref": tenant_ref,
        "entity_ref": entity_ref,
        "store_ref": "store-a",
        "scope_grant_authority_sha256": grant_sha256,
        "scope_as_of": AS_OF.isoformat(),
    }


def source_contract(
    registry: IntelligenceSourceAdapterRegistry,
    *,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    grant_sha256: str = "a" * 64,
) -> dict:
    return registry.observation_contract(
        principal=principal(tenant_ref=tenant_ref),
        entity_scope=entity_scope(
            entity_ref=entity_ref,
            authority_sha256=grant_sha256,
        ),
        store_ref="store-a",
        as_of=AS_OF,
        source_profile="browser_observation",
        marketplace="1688",
    )


def bind_evidence(
    evidence: EvidenceService,
    *,
    evidence_id: str,
    tenant_ref: str,
    entity_ref: str,
    grant_sha256: str,
) -> None:
    target = evidence.get(evidence_id)
    evidence.capture(
        content=f"independent scope binding:{evidence_id}".encode(),
        filename=f"{evidence_id}-binding.txt",
        content_type="text/plain",
        source="independent-scope-review",
        source_ref=f"internal://scope-binding/{evidence_id}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-28T04:30:00Z",
        effective_until=None,
        created_by="binding-recorder",
        metadata={
            "evidence_scope_contract_id": BINDING_CONTRACT,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": "store-a",
            "scope_grant_authority_sha256": grant_sha256,
            "reviewed_by": "independent-reviewer",
        },
    )


def test_registry_is_deterministic_read_only_and_entity_scoped() -> None:
    registry = IntelligenceSourceAdapterRegistry()
    no_entity = registry.snapshot(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
        },
        store_ref="store-a",
        as_of=AS_OF,
    )
    ready = registry.snapshot(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert no_entity["status"] == "no_data"
    assert no_entity["scope"]["entity_ref"] is None
    assert no_entity["source_gaps"] == ["entity_scope_authority_missing"]
    assert ready == registry.snapshot(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    assert ready["status"] == "ready"
    assert ready["counts"] == {
        "implemented": 10,
        "contract_only": 1,
        "external_write_enabled": 0,
    }
    assert ready["control_envelope"]["external_write_allowed"] is False


def test_registry_freezes_public_adapter_and_blocks_generic_export() -> None:
    registry = IntelligenceSourceAdapterRegistry()
    first = source_contract(registry)
    second = source_contract(registry)

    assert first == second
    assert first["adapter"]["adapter_id"] == (
        "allowed-public-1688-observation-v1"
    )
    assert first["adapter"]["max_source_grade"] == "C"
    assert first["adapter"]["semantic_authority"] == (
        "supplier_market_observation_only"
    )
    assert first["adapter"]["allowed_hosts"] == ["1688.com"]
    assert first["capture_allowed"] is True
    assert first["external_write_allowed"] is False
    with pytest.raises(ValueError, match="not admitted"):
        registry.observation_contract(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=AS_OF,
            source_profile="seller_tool_export",
            marketplace="1688",
        )


@pytest.mark.parametrize(
    ("marketplace", "adapter_id", "allowed_host"),
    [
        ("alibaba", "allowed-public-alibaba-observation-v1", "alibaba.com"),
        (
            "pinduoduo",
            "allowed-public-pinduoduo-observation-v1",
            "pinduoduo.com",
        ),
        ("taobao", "allowed-public-taobao-observation-v1", "taobao.com"),
        ("tmall", "allowed-public-tmall-observation-v1", "tmall.com"),
        ("tvcmall", "allowed-public-tvcmall-observation-v1", "tvcmall.com"),
        ("xianyu", "allowed-public-xianyu-observation-v1", "goofish.com"),
        ("yiwugo", "allowed-public-yiwugo-observation-v1", "yiwugo.com"),
    ],
)
def test_registry_freezes_each_supplier_platform_independently(
    marketplace: str,
    adapter_id: str,
    allowed_host: str,
) -> None:
    registry = IntelligenceSourceAdapterRegistry()
    snapshot = registry.snapshot(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    adapter = next(
        item for item in snapshot["adapters"]
        if item["adapter_id"] == adapter_id
    )

    assert adapter["status"] == "implemented"
    assert allowed_host in adapter["allowed_hosts"]
    assert adapter["semantic_authority"] == (
        "supplier_market_observation_only"
    )
    contract = registry.observation_contract(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        source_profile="browser_observation",
        marketplace=marketplace,
    )
    assert contract["adapter"]["adapter_id"] == adapter_id
    assert contract["capture_allowed"] is True
    assert contract["external_write_allowed"] is False


def test_registry_freezes_only_admitted_ozon_catalog_adapter() -> None:
    registry = IntelligenceSourceAdapterRegistry()

    contract = registry.catalog_contract(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert contract["adapter"]["adapter_id"] == (
        "ozon-seller-api-product-read-v1"
    )
    assert contract["adapter"]["ingestion_surface"] == (
        "catalog_evidence_import"
    )
    assert contract["adapter"]["source_contract"] == (
        "ozon-product-read-v1"
    )
    assert contract["adapter"]["max_source_grade"] == "A"
    assert contract["adapter"]["semantic_authority"] == (
        "own_listing_catalog_fact"
    )
    assert contract["import_allowed"] is True
    assert contract["external_write_allowed"] is False
    assert len(contract["adapter_contract_sha256"]) == 64
    with pytest.raises(ValueError, match="entity scope grant"):
        registry.catalog_contract(
            principal=principal(),
            entity_scope={
                "status": "no_data",
                "entity_ref": None,
                "authority_sha256": None,
            },
            store_ref="store-a",
            as_of=AS_OF,
        )


def test_registry_is_not_effective_before_its_version_boundary() -> None:
    registry = IntelligenceSourceAdapterRegistry()
    before = datetime(2026, 7, 27, 23, 59, tzinfo=UTC)

    snapshot = registry.snapshot(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=before,
    )

    assert snapshot["status"] == "no_data"
    assert snapshot["source_gaps"] == [
        "source_adapter_registry_not_effective"
    ]
    with pytest.raises(ValueError, match="not effective"):
        registry.observation_contract(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=before,
            source_profile="browser_observation",
            marketplace="1688",
        )
    with pytest.raises(ValueError, match="not effective"):
        registry.catalog_contract(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=before,
        )


def test_registry_rejects_unsafe_acquisition_policy(tmp_path) -> None:
    source = IntelligenceSourceAdapterRegistry()._registry
    unsafe = deepcopy(source)
    unsafe["adapters"][0]["policy"]["cookie_or_local_storage"] = True
    path = tmp_path / "unsafe-intelligence-adapters.json"
    path.write_text(json.dumps(unsafe), encoding="utf-8")

    with pytest.raises(ValueError, match="reject unsafe acquisition"):
        IntelligenceSourceAdapterRegistry(registry_path=path)


def test_native_capture_freezes_scope_adapter_and_scoped_idempotency() -> None:
    engine = database()
    evidence = EvidenceService(engine)
    workspace = MarketplaceObservationWorkspace(
        engine=engine,
        evidence=evidence,
    )
    registry = IntelligenceSourceAdapterRegistry()
    request = observation_request()

    created = workspace.capture(
        request,
        actor_id="operator-a",
        scope_authority=scope_authority(),
        source_contract=source_contract(registry),
    )
    replay = workspace.capture(
        request,
        actor_id="operator-a",
        scope_authority=scope_authority(),
        source_contract=source_contract(registry),
    )
    other_tenant = workspace.capture(
        request,
        actor_id="operator-b",
        scope_authority=scope_authority(
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            grant_sha256="b" * 64,
        ),
        source_contract=source_contract(
            registry,
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            grant_sha256="b" * 64,
        ),
    )

    assert replay["id"] == created["id"]
    assert other_tenant["id"] != created["id"]
    assert created["scope"]["tenant_ref"] == "tenant-a"
    assert created["scope"]["entity_ref"] == "entity-a"
    assert created["source_adapter"]["status"] == "frozen"
    assert created["source_adapter"]["adapter_id"] == (
        "allowed-public-1688-observation-v1"
    )
    assert created["supplier_offer_created"] is False
    assert created["actual_cost_created"] is False
    assert created["external_write_allowed"] is False
    with Session(engine) as session:
        record = session.get(EvidenceRecordRow, created["evidence_id"])
        assert record is not None
        blob = session.get(EvidenceBlobRow, record.blob_sha256)
        assert blob is not None
        artifact = json.loads(bytes(blob.content_bytes))
    assert artifact["source_adapter"]["allowed_hosts"] == ["1688.com"]
    assert artifact["source_adapter"]["policy"][
        "cookie_or_local_storage"
    ] is False
    assert artifact["source_adapter"]["policy"]["internal_api"] is False
    assert artifact["source_adapter"]["policy"]["captcha_bypass"] is False

    changed = observation_request(displayed_price="18.90")
    with pytest.raises(ValueError, match="different immutable content"):
        workspace.capture(
            changed,
            actor_id="operator-a",
            scope_authority=scope_authority(),
            source_contract=source_contract(registry),
        )

    wrong_host = observation_request(idempotency_key="wrong-host")
    wrong_host["source_url"] = "https://example.com/not-1688"
    with pytest.raises(ValueError, match="outside the frozen source adapter"):
        workspace.capture(
            wrong_host,
            actor_id="operator-a",
            scope_authority=scope_authority(),
            source_contract=source_contract(registry),
        )


def test_native_query_filters_tenant_before_current_fact_deduplication() -> None:
    engine = database()
    evidence = EvidenceService(engine)
    workspace = MarketplaceObservationWorkspace(
        engine=engine,
        evidence=evidence,
    )
    registry = IntelligenceSourceAdapterRegistry()
    scoped = ScopedMarketplaceObservationAuthority(
        observations=workspace,
        scoped_evidence=ScopedEvidenceAuthority(evidence=evidence),
    )
    tenant_a = workspace.capture(
        observation_request(idempotency_key="tenant-a"),
        actor_id="operator-a",
        scope_authority=scope_authority(),
        source_contract=source_contract(registry),
    )
    tenant_b_request = observation_request(idempotency_key="tenant-b")
    tenant_b_request["observed_at"] = "2026-07-28T04:30:00Z"
    workspace.capture(
        tenant_b_request,
        actor_id="operator-b",
        scope_authority=scope_authority(
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            grant_sha256="b" * 64,
        ),
        source_contract=source_contract(
            registry,
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            grant_sha256="b" * 64,
        ),
    )
    bind_evidence(
        evidence,
        evidence_id=tenant_a["evidence_id"],
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        grant_sha256="a" * 64,
    )

    result = scoped.latest(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        marketplace="1688",
    )

    assert result["status"] == "ready"
    assert result["counts"]["queried_in_exact_store_scope"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["tenant_ref"] == "tenant-a"
    assert result["items"][0]["snapshot_id"] == tenant_a["id"]


def test_database_rejects_partial_native_scope_adapter_tuple() -> None:
    engine = database()
    evidence = EvidenceService(engine)
    workspace = MarketplaceObservationWorkspace(
        engine=engine,
        evidence=evidence,
    )
    registry = IntelligenceSourceAdapterRegistry()
    created = workspace.capture(
        observation_request(),
        actor_id="operator-a",
        scope_authority=scope_authority(),
        source_contract=source_contract(registry),
    )

    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.execute(
            update(MarketplaceObservationSnapshotRow)
            .where(
                MarketplaceObservationSnapshotRow.id == created["id"]
            )
            .values(adapter_contract_sha256=None)
        )


def test_ingestion_routes_require_auth_scope_and_freeze_capture(
    monkeypatch,
) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal(),
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: entity_scope(),
    )

    def fake_capture(request, **values):
        captured.update({"request": request, **values})
        return {
            "id": "mos-api",
            "scope": values["scope_authority"],
            "source_adapter": values["source_contract"]["adapter"],
            "external_write_allowed": False,
        }

    monkeypatch.setattr(
        runtime.marketplace_observation,
        "capture",
        fake_capture,
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    adapters = client.get(
        "/v1/intelligence-ingestion/adapters",
        params={"store_ref": "store-a", "as_of": AS_OF.isoformat()},
        headers=headers,
    )
    created = client.post(
        "/v1/marketplace-observations",
        json=observation_request(),
        headers=headers,
    )
    forbidden = client.get(
        "/v1/intelligence-ingestion/adapters",
        params={"store_ref": "store-b"},
        headers=headers,
    )
    blocked_export = client.post(
        "/v1/marketplace-observations",
        json=observation_request(
            idempotency_key="generic-export",
            source_profile="seller_tool_export",
        ),
        headers=headers,
    )

    assert adapters.status_code == 200
    assert adapters.json()["status"] == "ready"
    assert created.status_code == 201
    assert captured["scope_authority"]["tenant_ref"] == "tenant-a"
    assert captured["scope_authority"]["entity_ref"] == "entity-a"
    assert captured["scope_authority"]["store_ref"] == "store-a"
    assert captured["source_contract"]["adapter"]["adapter_id"] == (
        "allowed-public-1688-observation-v1"
    )
    assert forbidden.status_code == 403
    assert blocked_export.status_code == 422
    assert "not admitted" in blocked_export.json()["detail"]
    assert app.openapi()["paths"][
        "/v1/intelligence-ingestion/adapters"
    ]["get"]["security"] == [{"KjdsApiKey": []}]


def test_ingestion_adapter_route_rejects_anonymous(monkeypatch) -> None:
    def reject(_key):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    response = TestClient(app).get(
        "/v1/intelligence-ingestion/adapters",
        params={"store_ref": "store-a"},
    )
    assert response.status_code == 401


def test_ingestion_adapter_route_rejects_future_as_of(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal(),
    )
    response = TestClient(app).get(
        "/v1/intelligence-ingestion/adapters",
        params={
            "store_ref": "store-a",
            "as_of": "2999-01-01T00:00:00Z",
        },
        headers={"X-KJDS-API-Key": "test-key"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "as_of cannot be in the future"
