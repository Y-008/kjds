from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceService,
)
from apps.control_plane.evidence_scope import (
    BINDING_CONTRACT,
    ScopedEvidenceAuthority,
)
from apps.control_plane.marketplace_catalog import (
    InMemoryMarketplaceCatalogStore,
    MarketplaceCatalogWorkspace,
)
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_marketplace_catalog import (
    ScopedMarketplaceCatalogAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.sql_repository import Base

AS_OF = datetime(2026, 7, 28, 2, tzinfo=UTC)


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


def entity_scope(
    entity_ref: str = "entity-a",
    authority: str = "a" * 64,
) -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": authority,
    }


def capture(evidence: EvidenceService, name: str):
    return evidence.capture(
        content=f"catalog source:{name}".encode(),
        filename=f"{name}.json",
        content_type="application/json",
        source="official-export",
        source_ref=f"official://ozon/catalog/{name}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-28T01:00:00Z",
        effective_until=None,
        created_by="catalog-collector",
    )


def bind(
    evidence: EvidenceService,
    target_id: str,
    *,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
):
    target = evidence.get(target_id)
    return evidence.capture(
        content=f"scope binding:{target.id}:{tenant_ref}".encode(),
        filename=f"{target.id}-scope-binding.txt",
        content_type="text/plain",
        source="independent-scope-review",
        source_ref=f"internal://scope-binding/{target.id}/{tenant_ref}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-28T01:30:00Z",
        effective_until=None,
        created_by="binding-recorder",
        metadata={
            "evidence_scope_contract_id": BINDING_CONTRACT,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "reviewed_by": "independent-reviewer",
        },
    )


def item(
    *,
    offer_id: str,
    evidence_id: str,
    observed_at: str = "2026-07-28T01:00:00+00:00",
    canonical_product_id: str | None = None,
) -> dict:
    return {
        "offer_id": offer_id,
        "marketplace_sku": f"sku-{offer_id}",
        "name": f"catalog item {offer_id}",
        "currency_code": "RUB",
        "prices": {"price": "1000.00"},
        "available_stock": 3,
        "stocks": [],
        "statuses": {},
        "dimensions": {},
        "attributes": [],
        "attributes_with_defaults": [],
        "complex_attributes": [],
        "image_references": [],
        "video_references": [],
        "document_references": [],
        "media_rights_status": "unverified_external_reference",
        "source_evidence_id": evidence_id,
        "observed_at": observed_at,
        "item_hash": (offer_id[0] if offer_id else "a") * 64,
        "canonical_product_id": canonical_product_id,
    }


class FakeCatalog:
    def __init__(self, items: list[dict]):
        self.items = items
        self.calls = []

    def latest_items(self, **values):
        self.calls.append(values)
        assert values["store_ref"] == "store-a"
        assert values["as_of"] == AS_OF
        return self.items[: values["limit"]]


def authority(evidence: EvidenceService, items: list[dict]):
    catalog = FakeCatalog(items)
    return (
        catalog,
        ScopedMarketplaceCatalogAuthority(
            catalog=catalog,
            scoped_evidence=ScopedEvidenceAuthority(evidence=evidence),
        ),
    )


def test_missing_entity_scope_returns_no_data_without_raw_catalog_read():
    class RawMustNotRun:
        @staticmethod
        def latest_items(**_):
            raise AssertionError("raw Catalog must not be read")

    result = ScopedMarketplaceCatalogAuthority(
        catalog=RawMustNotRun(),
        scoped_evidence=object(),
    ).latest(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["items"] == []
    assert result["counts"]["queried_in_exact_store_scope"] == 0
    assert result["source_classes"]["store_catalog"] == "not_read"
    assert result["scope"]["entity_ref"] is None
    assert result["control_envelope"]["external_write_allowed"] is False


def test_exact_scope_projection_is_deterministic_and_evidence_bound():
    evidence = EvidenceService(database())
    source = capture(evidence, "ready")
    bind(evidence, source.id)
    catalog, scoped = authority(
        evidence,
        [item(offer_id="a", evidence_id=source.id)],
    )
    values = {
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "as_of": AS_OF,
    }

    first = scoped.latest(**values)
    second = scoped.latest(**values)

    assert first == second
    assert first["status"] == "ready"
    assert first["counts"] == {
        "queried_in_exact_store_scope": 1,
        "included": 1,
        "excluded": 0,
        "bound_to_canonical_product": 0,
    }
    assert first["items"][0]["offer_id"] == "a"
    assert first["evidence_authority_sha256"]
    assert first["control_envelope"]["catalog_input_ready"] is True
    assert first["control_envelope"]["candidate_scoring_allowed"] is False
    assert len(catalog.calls) == 2


def test_native_catalog_projection_requires_frozen_scope_and_evidence_hash():
    evidence = EvidenceService(database())
    source = capture(evidence, "native-ready")
    bind(evidence, source.id)
    scoped_evidence = ScopedEvidenceAuthority(evidence=evidence)
    evidence_projection = scoped_evidence.project_targets(
        evidence_ids=[source.id],
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    native = {
        **item(offer_id="native", evidence_id=source.id),
        "snapshot_id": "snapshot-native",
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "scope_grant_authority_sha256": "a" * 64,
        "scope_evidence_authority_sha256": evidence_projection[
            "binding_authority_sha256"
        ],
        "scope_as_of": "2026-07-28T01:30:00+00:00",
        "adapter_id": "ozon-seller-api-product-read-v1",
        "adapter_version": "1.0.0",
        "adapter_contract_sha256": "c" * 64,
        "source_grade": "A",
        "semantic_authority": "own_listing_catalog_fact",
        "snapshot_evidence_ids": [source.id],
    }
    catalog = FakeCatalog([native])
    scoped = ScopedMarketplaceCatalogAuthority(
        catalog=catalog,
        scoped_evidence=scoped_evidence,
    )

    ready = scoped.latest(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    native["scope_evidence_authority_sha256"] = "d" * 64
    blocked = scoped.latest(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert ready["status"] == "ready"
    assert ready["items"][0]["tenant_ref"] == "tenant-a"
    assert blocked["status"] == "blocked"
    assert blocked["items"] == []
    assert blocked["excluded"]["by_reason"] == {
        "catalog_native_evidence_authority_mismatch": 1
    }


def test_unbound_cross_scope_and_damaged_sources_disclose_only_counts():
    engine = database()
    evidence = EvidenceService(engine)
    unbound = capture(evidence, "unbound")
    cross_scope = capture(evidence, "cross-scope")
    damaged = capture(evidence, "damaged")
    bind(
        evidence,
        cross_scope.id,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
    )
    bind(evidence, damaged.id)
    with Session(engine) as session, session.begin():
        blob = session.get(EvidenceBlobRow, damaged.sha256)
        assert blob is not None
        blob.content_bytes = b"corrupted"
    _, scoped = authority(
        evidence,
        [
            item(offer_id="unbound-secret", evidence_id=unbound.id),
            item(
                offer_id="cross-scope-secret",
                evidence_id=cross_scope.id,
            ),
            item(offer_id="damaged-secret", evidence_id=damaged.id),
        ],
    )

    result = scoped.latest(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    serialized = str(result)

    assert result["status"] == "blocked"
    assert result["items"] == []
    assert result["excluded"]["count"] == 3
    assert result["excluded"]["details_disclosed"] is False
    for secret in (
        "unbound-secret",
        "cross-scope-secret",
        "damaged-secret",
        unbound.id,
        cross_scope.id,
        damaged.id,
    ):
        assert secret not in serialized


def test_catalog_as_of_excludes_future_snapshot_and_future_binding():
    store = InMemoryMarketplaceCatalogStore()
    store.save_snapshot(
        {
            "id": "snapshot-current",
            "store_ref": "store-a",
            "idempotency_key": "current",
            "snapshot_hash": "a" * 64,
            "imported_at": "2026-07-28T01:10:00+00:00",
            "items": [
                item(
                    offer_id="a",
                    evidence_id="evd-current",
                    canonical_product_id=None,
                )
            ],
        }
    )
    store.save_snapshot(
        {
            "id": "snapshot-future",
            "store_ref": "store-a",
            "idempotency_key": "future",
            "snapshot_hash": "b" * 64,
            "imported_at": "2026-07-28T03:00:00+00:00",
            "items": [
                item(
                    offer_id="b",
                    evidence_id="evd-future",
                    observed_at="2026-07-28T03:00:00+00:00",
                )
            ],
        }
    )
    store.save_binding(
        {
            "marketplace": "ozon",
            "store_ref": "store-a",
            "offer_id": "a",
            "marketplace_sku": "sku-a",
            "product_id": "prd-future-binding",
            "source_evidence_id": "evd-current",
            "item_hash": "a" * 64,
            "bound_by": "operator-a",
            "bound_at": "2026-07-28T03:00:00+00:00",
        }
    )
    workspace = MarketplaceCatalogWorkspace(
        verified_bundle_loader=lambda _: None,
        store=store,
        evidence=object(),
        repository=InMemoryRepository(),
    )

    before = workspace.latest_items(store_ref="store-a", as_of=AS_OF)
    after = workspace.latest_items(
        store_ref="store-a",
        as_of=datetime(2026, 7, 28, 4, tzinfo=UTC),
    )

    assert [row["offer_id"] for row in before] == ["a"]
    assert before[0]["canonical_product_id"] is None
    assert {row["offer_id"] for row in after} == {"a", "b"}
    assert next(
        row for row in after if row["offer_id"] == "a"
    )["canonical_product_id"] == "prd-future-binding"


def test_catalog_import_preflight_rejects_unbound_evidence():
    evidence = EvidenceService(database())
    source = capture(evidence, "unbound-import")
    _, scoped = authority(evidence, [])

    with pytest.raises(ValueError, match="independently bound"):
        scoped.require_import_evidence(
            evidence_ids=[source.id],
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=AS_OF,
        )

    bind(evidence, source.id)
    result = scoped.require_import_evidence(
        evidence_ids=[source.id],
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    assert result["status"] == "ready"
    assert result["evidence_ids"] == [source.id]


def test_scoped_catalog_api_requires_authentication_and_store_scope(monkeypatch):
    def reject_missing_key(_):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        reject_missing_key,
    )
    assert (
        TestClient(app).get(
            "/v1/marketplace-catalog/items/latest",
            params={"store_ref": "store-a"},
        ).status_code
        == 401
    )

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: principal(),
    )
    assert (
        TestClient(app).get(
            "/v1/marketplace-catalog/items/latest",
            params={"store_ref": "store-b"},
            headers={"X-KJDS-API-Key": "test-key"},
        ).status_code
        == 403
    )


def test_scoped_catalog_api_missing_entity_is_read_only_and_mutations_fail(
    monkeypatch,
):
    class RawMustNotRun:
        @staticmethod
        def latest_items(**_):
            raise AssertionError("raw Catalog must not be read")

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: principal(),
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_: {
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
            "authority_sha256": None,
        },
    )
    monkeypatch.setattr(
        runtime.scoped_marketplace_catalog,
        "catalog",
        RawMustNotRun(),
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}

    read = client.get(
        "/v1/marketplace-catalog/items/latest",
        params={"store_ref": "store-a", "as_of": AS_OF.isoformat()},
        headers=headers,
    )
    assert read.status_code == 200
    assert read.json()["status"] == "no_data"
    assert read.json()["items"] == []
    assert (
        read.json()["source_classes"]["store_catalog"]
        == "not_read"
    )

    imported = client.post(
        "/v1/marketplace-catalog/ozon/import-evidence",
        json={
            "evidence_ids": ["evd-unbound"],
            "store_ref": "store-a",
            "idempotency_key": "catalog-import",
        },
        headers=headers,
    )
    assert imported.status_code == 422
    assert "entity scope grant" in imported.json()["detail"]

    binding = client.post(
        "/v1/marketplace-catalog/items/bind-existing",
        json={
            "store_ref": "store-a",
            "offer_id": "secret-offer",
            "expected_item_hash": "a" * 64,
            "confirmed": True,
        },
        headers=headers,
    )
    assert binding.status_code == 422
    assert "entity scope grant" in binding.json()["detail"]
    assert "secret-offer" not in str(binding.json())


def test_catalog_import_api_passes_server_scope_and_adapter_authority(
    monkeypatch,
):
    captured: dict = {}
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: principal(),
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_: entity_scope(),
    )
    monkeypatch.setattr(
        runtime.scoped_marketplace_catalog,
        "require_import_evidence",
        lambda **_: {
            "status": "ready",
            "evidence_ids": ["evd-ready"],
            "evidence_authority_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        runtime.intelligence_source_adapters,
        "catalog_contract",
        lambda **_: {
            "adapter": {
                "adapter_id": "ozon-seller-api-product-read-v1",
            },
            "adapter_contract_sha256": "c" * 64,
            "external_write_allowed": False,
        },
    )

    def fake_import(**values):
        captured.update(values)
        return {
            "id": "mcs-native",
            "external_write_allowed": False,
        }

    monkeypatch.setattr(
        runtime.marketplace_catalog,
        "import_ozon_evidence",
        fake_import,
    )
    response = TestClient(app).post(
        "/v1/marketplace-catalog/ozon/import-evidence",
        json={
            "evidence_ids": ["evd-ready"],
            "store_ref": "store-a",
            "idempotency_key": "native-import",
        },
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 201
    assert captured["scope_authority"]["tenant_ref"] == "tenant-a"
    assert captured["scope_authority"]["entity_ref"] == "entity-a"
    assert captured["scope_authority"]["store_ref"] == "store-a"
    assert captured["scope_authority"][
        "scope_grant_authority_sha256"
    ] == "a" * 64
    assert captured["scope_authority"][
        "scope_evidence_authority_sha256"
    ] == "b" * 64
    assert captured["source_contract"][
        "adapter_contract_sha256"
    ] == "c" * 64
    assert response.json()["external_write_allowed"] is False
