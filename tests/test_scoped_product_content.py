from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.batch_opportunity import BatchOpportunityWorkspace
from apps.control_plane.domain import (
    ContentAsset,
    ContentStatus,
    ContentType,
    Passport,
    PassportType,
    Product,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_product_content import (
    ScopedProductContentAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.sql_repository import (
    Base,
    ProductRow,
    SqlAlchemyRepository,
)

AS_OF = datetime(2026, 7, 28, 10, tzinfo=UTC)


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute(
            "PRAGMA foreign_keys=ON"
        ),
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
    *,
    entity_ref: str = "entity-a",
    authority_sha256: str = "a" * 64,
) -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": authority_sha256,
    }


class Catalog:
    def __init__(self, items: list[dict] | None = None):
        self.items = items or []
        self.calls = 0

    def latest(self, **_):
        self.calls += 1
        return {
            "contract_id": "kjds-scoped-marketplace-catalog-v1",
            "status": "ready" if self.items else "no_data",
            "items": self.items,
            "source_gaps": [] if self.items else ["catalog_not_available"],
            "blockers": [],
            "snapshot_sha256": "c" * 64,
        }


class Evidence:
    def __init__(self, *, blocked: set[str] | None = None):
        self.blocked = blocked or set()

    def project_targets(self, *, evidence_ids, **_):
        invalid = sorted(set(evidence_ids) & self.blocked)
        records = [
            {
                "evidence_id": evidence_id,
                "sha256": evidence_id[-1:] * 64,
                "scope_binding": {
                    "status": (
                        "blocked"
                        if evidence_id in self.blocked
                        else "ready"
                    ),
                    "reasons": (
                        ["tenant_ref_mismatch"]
                        if evidence_id in self.blocked
                        else []
                    ),
                },
            }
            for evidence_id in evidence_ids
        ]
        return {
            "status": "blocked" if invalid else "ready",
            "records": records,
            "invalid_evidence_ids": invalid,
            "binding_authority_sha256": "e" * 64,
            "source_gaps": (
                ["evidence_scope_conflict"] if invalid else []
            ),
            "blockers": [],
        }


class Sourcing:
    def __init__(self):
        self.store = SimpleNamespace(
            get_offer=self._missing,
            get_scenario=self._missing,
        )
        self.approvals_created = 0

    @staticmethod
    def _missing(_):
        raise KeyError("not found")

    @staticmethod
    def require_release_ready(_):
        raise AssertionError("missing scenario cannot be release ready")


def authority(
    repo,
    *,
    catalog: Catalog | None = None,
    evidence: Evidence | None = None,
):
    source = catalog or Catalog()
    return (
        source,
        ScopedProductContentAuthority(
            repository=repo,
            scoped_catalog=source,
            scoped_evidence=evidence or Evidence(),
            sourcing=Sourcing(),
        ),
    )


def native_product(
    *,
    sku: str,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
    product_id: str | None = None,
) -> Product:
    values = {
        "sku": sku,
        "name": f"Product {sku}",
        "created_at": "2026-07-28T01:00:00+00:00",
        "tenant_ref": tenant_ref,
        "entity_ref": entity_ref,
        "store_ref": store_ref,
        "scope_grant_authority_sha256": "a" * 64,
        "scope_as_of": "2026-07-28T01:00:00+00:00",
        "created_by": "operator-a",
    }
    if product_id:
        values["id"] = product_id
    return Product(**values)


def approved_facts(kind: PassportType) -> dict:
    values = {
        PassportType.PRODUCT: {
            "material": "steel",
            "intended_use": "storage",
            "country_of_origin": "CN",
            "weight_kg": "1",
            "dimensions_cm": "10x10x10",
        },
        PassportType.COMPLIANCE: {
            "hs_code": "0000",
            "eaeu_rules": "checked",
            "eac_requirement": "not_applicable",
            "chestny_znak_requirement": "not_applicable",
            "russian_labeling": "required",
            "ip_status": "cleared",
            "transport_restrictions": "none",
            "sellability": "allowed",
        },
        PassportType.QUALITY: {
            "golden_sample_ref": "sample-1",
            "inspection_plan": "plan-1",
            "packaging_test": "passed",
        },
    }[kind]
    return {"decision": "approved", **values}


def test_missing_entity_scope_performs_no_raw_product_or_catalog_read():
    class RawMustNotRun:
        def __getattr__(self, _):
            raise AssertionError("raw Product/content must not be read")

    result = ScopedProductContentAuthority(
        repository=RawMustNotRun(),
        scoped_catalog=RawMustNotRun(),
        scoped_evidence=RawMustNotRun(),
        sourcing=RawMustNotRun(),
    ).project(
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
    assert result["products"] == []
    assert result["control_envelope"]["raw_product_content_read"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_native_product_scope_excludes_other_tenant_and_store():
    repo = SqlAlchemyRepository(database())
    allowed = repo.add_product(native_product(sku="same-sku"))
    repo.add_product(
        native_product(
            sku="same-sku",
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
        )
    )
    catalog, scoped = authority(repo)

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "partial"
    assert [item["product"]["id"] for item in result["products"]] == [
        allowed.id
    ]
    assert result["products"][0]["scope_authority"] == (
        "native_product_scope"
    )
    assert catalog.calls == 1


def test_legacy_product_requires_scoped_catalog_canonical_binding():
    repo = SqlAlchemyRepository(database())
    legacy = repo.add_product(
        Product(
            sku="legacy",
            name="Legacy",
            created_at="2026-07-28T01:00:00+00:00",
        )
    )
    catalog = Catalog(
        [
            {
                "canonical_product_id": legacy.id,
                "offer_id": "offer-1",
            }
        ]
    )
    _, scoped = authority(repo, catalog=catalog)

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        product_id=legacy.id,
    )

    assert result["products"][0]["scope_authority"] == (
        "scoped_catalog_canonical_binding"
    )
    assert result["scope"]["tenant_ref"] == "tenant-a"


def test_passport_and_asset_evidence_conflict_blocks_content_readiness():
    repo = SqlAlchemyRepository(database())
    product = repo.add_product(native_product(sku="blocked"))
    for index, kind in enumerate(PassportType, start=1):
        repo.add_passport(
            Passport(
                product_id=product.id,
                kind=kind,
                version=1,
                facts=approved_facts(kind),
                evidence=[f"evd-{index}"],
                approved_by="reviewer",
                created_at="2026-07-28T02:00:00+00:00",
            )
        )
    repo.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="OZON",
            brief={"source_asset_evidence_ids": ["evd-image-source"]},
            source_facts={"evidence_ids": ["evd-image-source"]},
            status=ContentStatus.APPROVED,
            artifact_ref="evd-bad-artifact",
            created_at="2026-07-28T03:00:00+00:00",
        )
    )
    _, scoped = authority(
        repo,
        evidence=Evidence(blocked={"evd-bad-artifact"}),
    )

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        product_id=product.id,
    )

    item = result["products"][0]
    assert result["status"] == "blocked"
    assert item["readiness"]["passport_approved"] is True
    assert item["readiness"]["media_qa_ready"] is False
    assert item["readiness"]["listing_draft_allowed"] is False
    assert item["readiness"]["external_write_allowed"] is False


def test_as_of_excludes_later_passport_and_content_asset():
    repo = SqlAlchemyRepository(database())
    product = repo.add_product(native_product(sku="as-of"))
    repo.add_passport(
        Passport(
            product_id=product.id,
            kind=PassportType.PRODUCT,
            version=1,
            facts={"decision": "draft"},
            evidence=[],
            created_at="2026-07-28T02:00:00+00:00",
        )
    )
    repo.add_passport(
        Passport(
            product_id=product.id,
            kind=PassportType.PRODUCT,
            version=2,
            facts=approved_facts(PassportType.PRODUCT),
            evidence=["evd-future"],
            approved_by="reviewer",
            created_at="2026-07-28T12:00:00+00:00",
        )
    )
    repo.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="OZON",
            brief={},
            source_facts={},
            status=ContentStatus.APPROVED,
            artifact_ref="evd-future-asset",
            created_at="2026-07-28T12:00:00+00:00",
        )
    )
    _, scoped = authority(repo)

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        product_id=product.id,
    )

    item = result["products"][0]
    assert item["passports"][0]["version"] == 1
    assert item["content_assets"] == []


def test_listing_plan_is_deterministic_and_creates_no_approval_or_permit():
    repo = SqlAlchemyRepository(database())
    product = repo.add_product(native_product(sku="plan"))
    _, scoped = authority(repo)
    values = {
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "as_of": AS_OF,
        "product_id": product.id,
        "offer_id": "offer-missing",
        "scenario_id": "scenario-missing",
        "content_asset_ids": ["asset-missing"],
        "listing_data": {
            "title": "Товар",
            "description": "Описание",
            "category_id": "1",
            "attributes": {},
            "images": [],
        },
    }

    first = scoped.listing_approval_plan(**values)
    second = scoped.listing_approval_plan(**values)
    changed = scoped.listing_approval_plan(
        **{
            **values,
            "listing_data": {
                **values["listing_data"],
                "title": "Другой товар",
            },
        }
    )

    assert first == second
    assert first["allowed"] is False
    assert first["approval_plan_sha256"] != changed[
        "approval_plan_sha256"
    ]
    assert first["control_envelope"] == {
        "read_only_plan": True,
        "listing_draft_created": False,
        "approval_created": False,
        "permit_created": False,
        "pilot_started": False,
        "external_write_allowed": False,
    }


def test_scoped_batch_content_never_calls_global_passport_or_asset_loader():
    class RawMustNotRun:
        def __getattr__(self, _):
            raise AssertionError("global Product/content loader must not run")

    result = BatchOpportunityWorkspace._content(
        SimpleNamespace(repository=RawMustNotRun()),
        market={
            "title": "Тестовый товар",
            "product_identity": {"color": "black"},
            "target_product_id": "prd-1",
            "media_rights_status": "owned",
        },
        supplier={"media_rights_status": "licensed"},
        scoped_product_content={
            "prd-1": {
                "passports": [
                    {"kind": kind.value, "status": "approved"}
                    for kind in PassportType
                ],
                "content_assets": [
                    {
                        "id": "image-1",
                        "content_type": "image",
                        "status": "approved",
                        "evidence_ready": True,
                    },
                    {
                        "id": "copy-1",
                        "content_type": "copy",
                        "status": "approved",
                        "evidence_ready": True,
                    },
                ],
            }
        },
    )

    assert result["content_authority"] == "scoped_product_content"
    assert result["content_ready"] is True
    assert result["observed_title_not_content_draft"] is True


def test_product_database_scope_check_and_scoped_sku_uniqueness():
    engine = database()
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.add(
            ProductRow(
                id="bad-partial",
                sku="partial",
                name="bad",
                market="RU",
                channel="OZON",
                status="candidate",
                created_at=AS_OF,
                tenant_ref="tenant-a",
            )
        )
        session.flush()

    repo = SqlAlchemyRepository(engine)
    repo.add_product(native_product(sku="shared"))
    repo.add_product(
        native_product(
            sku="shared",
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
        )
    )
    with pytest.raises(ValueError, match="SKU already exists"):
        repo.add_product(native_product(sku="shared"))


def test_scoped_product_content_api_requires_auth_and_store_scope(
    monkeypatch,
):
    def missing(_):
        raise AuthenticationFailure("missing", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", missing)
    client = TestClient(app)
    assert (
        client.get(
            "/v1/product-content/workspace",
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
        client.get(
            "/v1/product-content/workspace",
            params={"store_ref": "store-b"},
            headers={"X-KJDS-API-Key": "test"},
        ).status_code
        == 403
    )

    listing_payload = {
        "product_id": "product-a",
        "offer_id": "offer-a",
        "scenario_id": "scenario-a",
        "content_asset_ids": ["asset-a"],
        "listing_data": {
            "title": "Товар",
            "description": "Описание",
            "category_id": "1",
            "attributes": {},
            "images": ["asset-a"],
        },
        "store_ref": "store-b",
    }
    calls = []
    monkeypatch.setattr(
        runtime.scoped_product_content,
        "listing_approval_plan",
        lambda **values: calls.append(values),
    )
    response = client.post(
        "/v1/listings/ozon/approval-plan",
        json=listing_payload,
        headers={"X-KJDS-API-Key": "test"},
    )
    assert response.status_code == 403
    assert calls == []


def test_listing_approval_plan_api_rejects_anonymous(monkeypatch):
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: (_ for _ in ()).throw(
            AuthenticationFailure("missing", 401)
        ),
    )
    response = TestClient(app).post(
        "/v1/listings/ozon/approval-plan",
        json={
            "product_id": "product-a",
            "offer_id": "offer-a",
            "scenario_id": "scenario-a",
            "content_asset_ids": ["asset-a"],
            "listing_data": {
                "title": "Товар",
                "description": "Описание",
                "category_id": "1",
                "attributes": {},
                "images": ["asset-a"],
            },
            "store_ref": "store-a",
        },
    )
    assert response.status_code == 401


def test_product_create_missing_entity_is_409_and_does_not_write(
    monkeypatch,
):
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
    calls = []
    monkeypatch.setattr(
        runtime.commerce,
        "create_product",
        lambda **values: calls.append(values),
    )

    response = TestClient(app).post(
        "/v1/products",
        json={"sku": "never-created", "name": "Never"},
        headers={"X-KJDS-API-Key": "test"},
    )

    assert response.status_code == 409
    assert calls == []
