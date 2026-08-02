from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.evidence import (
    EvidenceGrade,
    EvidenceService,
    LineageEdgeRow,
)
from apps.control_plane.evidence_scope import (
    BINDING_CONTRACT,
    ScopedEvidenceAuthority,
)
from apps.control_plane.facts import FactRecordRow, PromotionRunRow
from apps.control_plane.finance import FinanceService
from apps.control_plane.imports import ImportDataRow, OzonImportService
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_facts import ScopedFactPromotionAuthority
from apps.control_plane.scoped_ozon_imports import (
    ScopedOzonImportAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.sql_repository import Base, ProductRow

CONTENT = (
    "номер заказа;артикул;количество;валюта;цена;дата заказа\n"
    "1001;SKU-1;2;RUB;1299.50;2026-07-16T10:00:00+03:00\n"
).encode()


def principal(
    *,
    tenant_ref: str = "tenant-a",
    actor_id: str = "operator-a",
    stores: frozenset[str] = frozenset({"store-a"}),
) -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=frozenset(
            {"operator", "reviewer", "compliance", "admin"}
        ),
        tenant_ref=tenant_ref,
        store_refs=stores,
    )


def entity_scope(
    *,
    entity_ref: str = "entity-a",
    authority: str = "a" * 64,
) -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": authority,
    }


def services():
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
    evidence = EvidenceService(engine)
    imports = OzonImportService(engine)
    scoped_imports = ScopedOzonImportAuthority(
        engine=engine,
        imports=imports,
        evidence=evidence,
    )
    authority = ScopedFactPromotionAuthority(
        engine=engine,
        scoped_imports=scoped_imports,
        scoped_evidence=ScopedEvidenceAuthority(evidence=evidence),
    )
    return engine, evidence, scoped_imports, authority


def capture_bound_source(
    evidence: EvidenceService,
    *,
    as_of: datetime,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
    source_ref: str = "tenant-a-orders",
):
    target = evidence.capture(
        content=CONTENT,
        filename="orders.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref=source_ref,
        grade=EvidenceGrade.A,
        effective_at=(as_of - timedelta(hours=3)).isoformat(),
        effective_until=None,
        created_by="source-uploader",
    )
    binding = evidence.capture(
        content=f"binding:{source_ref}".encode(),
        filename=f"{source_ref}-scope-binding.json",
        content_type="application/json",
        source="scope_review",
        source_ref=f"scope-review://{source_ref}",
        grade=EvidenceGrade.A,
        effective_at=(as_of - timedelta(hours=2)).isoformat(),
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
    return target, binding


def add_product(
    engine,
    *,
    as_of: datetime,
    tenant_ref: str | None = "tenant-a",
    entity_ref: str | None = "entity-a",
    store_ref: str | None = "store-a",
    authority: str | None = "a" * 64,
    product_id: str = "product-a",
) -> None:
    native = tenant_ref is not None
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id=product_id,
                sku="SKU-1",
                name="Scoped product",
                market="RU",
                channel="OZON",
                status="candidate",
                created_at=as_of - timedelta(hours=1),
                tenant_ref=tenant_ref,
                entity_ref=entity_ref,
                store_ref=store_ref,
                scope_grant_authority_sha256=authority,
                scope_as_of=(
                    as_of - timedelta(hours=1) if native else None
                ),
                created_by="product-owner" if native else None,
            )
        )


def native_import(
    scoped_imports: ScopedOzonImportAuthority,
    *,
    evidence_id: str,
    as_of: datetime,
    principal_value: Principal | None = None,
    entity_value: dict | None = None,
) -> dict:
    principal_value = principal_value or principal()
    entity_value = entity_value or entity_scope()
    return scoped_imports.import_file(
        filename="orders.csv",
        content=CONTENT,
        evidence_id=evidence_id,
        principal=principal_value,
        entity_scope=entity_value,
        store_ref="store-a",
        as_of=as_of,
    )


def promotion_values(
    imported: dict,
    *,
    as_of: datetime,
    principal_value: Principal | None = None,
    entity_value: dict | None = None,
) -> dict:
    principal_value = principal_value or principal()
    return {
        "import_id": imported["id"],
        "principal": principal_value,
        "entity_scope": entity_value or entity_scope(),
        "store_ref": "store-a",
        "as_of": as_of,
        "created_by": principal_value.actor_id,
    }


def test_native_promotion_is_atomic_scoped_and_idempotent():
    engine, evidence, scoped_imports, authority = services()
    as_of = datetime.now(UTC) - timedelta(seconds=2)
    source, _ = capture_bound_source(evidence, as_of=as_of)
    imported = native_import(
        scoped_imports,
        evidence_id=source.id,
        as_of=as_of,
    )
    add_product(engine, as_of=as_of)

    first = authority.promote(**promotion_values(imported, as_of=as_of))
    replay = authority.promote(**promotion_values(imported, as_of=as_of))
    listed = authority.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=datetime.now(UTC),
    )

    assert first["promoted_count"] == 1
    assert first["idempotent"] is False
    assert replay["id"] == first["id"]
    assert replay["idempotent"] is True
    assert replay["fact_ids"] == first["fact_ids"]
    assert listed["formal_fact_count"] == 1
    fact = listed["items"][0]
    assert fact["product_id"] == "product-a"
    assert fact["scope"]["tenant_ref"] == "tenant-a"
    assert fact["scope"]["source_evidence_sha256"] == source.sha256


def test_native_inventory_import_promotes_exact_cell_without_write_side_effects():
    engine, evidence, scoped_imports, authority = services()
    as_of = datetime.now(UTC) - timedelta(seconds=2)
    content = (
        "external_id,sku,warehouse_id,delivery_scheme,"
        "available_stock,reserved_stock,effective_at\n"
        f"snapshot-1,SKU-1,warehouse-cn-1,realFBS,3,0,"
        f"{(as_of - timedelta(hours=1)).isoformat()}\n"
    ).encode()
    source = evidence.capture(
        content=content,
        filename="warehouse_stock.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref="tenant-a-inventory",
        grade=EvidenceGrade.A,
        effective_at=(as_of - timedelta(hours=2)).isoformat(),
        effective_until=None,
        created_by="source-uploader",
    )
    evidence.capture(
        content=b"binding:tenant-a-inventory",
        filename="tenant-a-inventory-scope-binding.json",
        content_type="application/json",
        source="scope_review",
        source_ref="scope-review://tenant-a-inventory",
        grade=EvidenceGrade.A,
        effective_at=(as_of - timedelta(hours=1)).isoformat(),
        effective_until=None,
        created_by="binding-recorder",
        metadata={
            "evidence_scope_contract_id": BINDING_CONTRACT,
            "target_evidence_id": source.id,
            "target_evidence_sha256": source.sha256,
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "reviewed_by": "independent-reviewer",
        },
    )
    imported = scoped_imports.import_file(
        filename="warehouse_stock.csv",
        content=content,
        evidence_id=source.id,
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=as_of,
    )
    add_product(engine, as_of=as_of)

    promoted = authority.promote(
        **promotion_values(imported, as_of=as_of)
    )
    listed = authority.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=datetime.now(UTC),
        fact_type="ozon_inventory",
    )

    assert promoted["promoted_count"] == 1
    assert promoted["external_write_allowed"] is False
    assert listed["formal_fact_count"] == 1
    fact = listed["items"][0]
    assert fact["fact_type"] == "ozon_inventory"
    assert fact["natural_key"] == (
        "SKU-1:warehouse-cn-1:realFBS:-"
    )
    assert fact["payload"]["available_quantity"] == "3"
    assert fact["formal_fact"] is True
    assert fact["accounting_posted"] is False
    assert fact["external_write_allowed"] is False
    assert fact["approval_created"] is False
    assert fact["permit_created"] is False
    with Session(engine) as session:
        assert session.scalar(select(func.count(FactRecordRow.id))) == 1
        assert session.scalar(select(func.count(PromotionRunRow.id))) == 1
        assert (
            session.scalar(select(func.count(LineageEdgeRow.id)))
            == 1
        )


def test_same_payload_is_independent_across_tenants():
    engine, evidence, scoped_imports, authority = services()
    as_of = datetime.now(UTC) - timedelta(seconds=2)
    source_a, _ = capture_bound_source(evidence, as_of=as_of)
    source_b, _ = capture_bound_source(
        evidence,
        as_of=as_of,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        source_ref="tenant-b-orders",
    )
    imported_a = native_import(
        scoped_imports,
        evidence_id=source_a.id,
        as_of=as_of,
    )
    principal_b = principal(tenant_ref="tenant-b", actor_id="operator-b")
    entity_b = entity_scope(
        entity_ref="entity-b",
        authority="b" * 64,
    )
    imported_b = native_import(
        scoped_imports,
        evidence_id=source_b.id,
        as_of=as_of,
        principal_value=principal_b,
        entity_value=entity_b,
    )
    add_product(engine, as_of=as_of)
    add_product(
        engine,
        as_of=as_of,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        authority="b" * 64,
        product_id="product-b",
    )

    result_a = authority.promote(
        **promotion_values(imported_a, as_of=as_of)
    )
    result_b = authority.promote(
        **promotion_values(
            imported_b,
            as_of=as_of,
            principal_value=principal_b,
            entity_value=entity_b,
        )
    )

    assert result_a["id"] != result_b["id"]
    assert result_a["fact_ids"] != result_b["fact_ids"]
    with Session(engine) as session:
        assert session.scalar(select(func.count(FactRecordRow.id))) == 2


def test_global_product_bad_binding_and_claim_id_all_fail_zero_write():
    engine, evidence, scoped_imports, authority = services()
    as_of = datetime.now(UTC) - timedelta(seconds=2)
    source, _ = capture_bound_source(evidence, as_of=as_of)
    imported = native_import(
        scoped_imports,
        evidence_id=source.id,
        as_of=as_of,
    )
    add_product(
        engine,
        as_of=as_of,
        tenant_ref=None,
        entity_ref=None,
        store_ref=None,
        authority=None,
        product_id="legacy-product",
    )
    with pytest.raises(ValueError, match="scoped Product/SKU"):
        authority.promote(**promotion_values(imported, as_of=as_of))

    class BlockedEvidence:
        @staticmethod
        def project_targets(**_):
            return {
                "status": "blocked",
                "records": [],
                "invalid_evidence_ids": [],
                "binding_authority_sha256": None,
            }

    authority.scoped_evidence = BlockedEvidence()
    with pytest.raises(ValueError, match="independent exact-scope review"):
        authority.promote(**promotion_values(imported, as_of=as_of))
    with pytest.raises(KeyError):
        authority.promote(
            "claim-not-an-import",
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=as_of,
            created_by="operator-a",
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count(FactRecordRow.id))) == 0
        assert session.scalar(select(func.count(PromotionRunRow.id))) == 0


def test_missing_entity_and_future_cutoff_fail_before_dependencies():
    _, _, _, authority = services()

    class MustNotRun:
        def __getattr__(self, _):
            raise AssertionError("dependency must not be read")

    authority.engine = MustNotRun()
    authority.scoped_imports = MustNotRun()
    authority.scoped_evidence = MustNotRun()
    missing = {
        "status": "no_data",
        "entity_ref": None,
        "authority_sha256": None,
    }
    with pytest.raises(ValueError, match="entity scope grant"):
        authority.promote(
            "never-read",
            principal=principal(),
            entity_scope=missing,
            store_ref="store-a",
            as_of=datetime.now(UTC) - timedelta(seconds=1),
            created_by="operator-a",
        )
    with pytest.raises(ValueError, match="future"):
        authority.list(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=datetime.now(UTC) + timedelta(hours=1),
        )


def test_database_rejects_partial_fact_and_promotion_scope():
    engine, evidence, scoped_imports, _ = services()
    as_of = datetime.now(UTC) - timedelta(seconds=2)
    source, _ = capture_bound_source(evidence, as_of=as_of)
    imported = native_import(
        scoped_imports,
        evidence_id=source.id,
        as_of=as_of,
    )
    with Session(engine) as session:
        import_row_id = session.scalar(
            select(ImportDataRow.id).where(
                ImportDataRow.import_id == imported["id"]
            )
        )
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.add(
            FactRecordRow(
                id="bad-fact",
                source="ozon",
                fact_type="ozon_order",
                natural_key="bad",
                contract_version="bad",
                payload_json={},
                payload_hash="0" * 64,
                effective_at=as_of,
                recorded_at=as_of,
                evidence_id=source.id,
                import_row_id=import_row_id,
                product_id=None,
                resolution_status="resolved",
                created_by="operator-a",
                tenant_ref="tenant-a",
            )
        )
        session.flush()
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.add(
            PromotionRunRow(
                id="bad-run",
                import_id=imported["id"],
                promoted_count=0,
                duplicate_count=0,
                blocked_count=0,
                errors_json=[],
                created_by="operator-a",
                created_at=as_of,
                tenant_ref="tenant-a",
                request_sha256="0" * 64,
            )
        )
        session.flush()


def test_scoped_list_excludes_legacy_rows_and_finance_bypass():
    engine, evidence, scoped_imports, authority = services()
    as_of = datetime.now(UTC) - timedelta(seconds=2)
    source, _ = capture_bound_source(evidence, as_of=as_of)
    imported = native_import(
        scoped_imports,
        evidence_id=source.id,
        as_of=as_of,
    )
    add_product(engine, as_of=as_of)
    promoted = authority.promote(
        **promotion_values(imported, as_of=as_of)
    )
    with Session(engine) as session:
        import_row_id = session.scalar(
            select(ImportDataRow.id).where(
                ImportDataRow.import_id == imported["id"]
            )
        )
    with Session(engine) as session, session.begin():
        session.add(
            FactRecordRow(
                id="legacy-fact",
                source="legacy",
                fact_type="ozon_order",
                natural_key="legacy-key",
                contract_version="legacy-v1",
                payload_json={"effective_at": as_of.isoformat()},
                payload_hash="9" * 64,
                effective_at=as_of,
                recorded_at=as_of,
                evidence_id=source.id,
                import_row_id=import_row_id,
                product_id=None,
                resolution_status="requires_product_mapping",
                created_by="legacy",
            )
        )
    listed = authority.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=datetime.now(UTC),
    )

    assert [item["id"] for item in listed["items"]] == promoted["fact_ids"]
    with pytest.raises(
        ValueError,
        match="accounting ingestion is not authorized",
    ):
        FinanceService(engine).ingest_fact(
            promoted["fact_ids"][0],
            created_by="finance-reviewer",
        )


def test_fact_routes_require_auth_store_and_entity_before_authority(
    monkeypatch,
):
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: (_ for _ in ()).throw(
            AuthenticationFailure("missing", 401)
        ),
    )
    client = TestClient(app)
    assert client.get("/v1/facts").status_code == 401
    assert client.get("/v1/facts/fact-x").status_code == 401
    assert client.post("/v1/imports/import-x/promote").status_code == 401

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: principal(),
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        runtime.scoped_facts,
        "list",
        lambda **values: calls.append(values),
    )
    forbidden = client.get(
        "/v1/facts",
        params={"store_ref": "store-b"},
        headers={"X-KJDS-API-Key": "test"},
    )
    assert forbidden.status_code == 403
    assert calls == []

    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    no_entity = client.get(
        "/v1/facts",
        params={"store_ref": "store-a"},
        headers={"X-KJDS-API-Key": "test"},
    )
    assert no_entity.status_code == 422
    assert calls == []
    schema = app.openapi()
    assert schema["paths"]["/v1/facts"]["get"]["security"] == [
        {"KjdsApiKey": []}
    ]
    assert schema["paths"]["/v1/facts/{fact_id}"]["get"][
        "security"
    ] == [{"KjdsApiKey": []}]
    assert schema["paths"]["/v1/imports/{import_id}/promote"]["post"][
        "security"
    ] == [{"KjdsApiKey": []}]
