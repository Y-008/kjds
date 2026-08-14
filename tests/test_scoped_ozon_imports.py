from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.imports import ImportJobRow, OzonImportService
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_ozon_imports import (
    ScopedOzonImportAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.sql_repository import Base

CONTENT = (
    "номер заказа;артикул;количество;валюта;цена;дата заказа\n"
    "1001;SKU-1;2;RUB;1299.50;2026-07-16T10:00:00+03:00\n"
).encode()


def principal(
    *,
    tenant_ref: str = "tenant-a",
    stores: frozenset[str] = frozenset({"store-a"}),
) -> Principal:
    return Principal(
        actor_id="operator-a",
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
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    imports = OzonImportService(engine)
    scoped = ScopedOzonImportAuthority(
        engine=engine,
        imports=imports,
        evidence=evidence,
    )
    return engine, evidence, imports, scoped


def source_evidence(
    evidence,
    *,
    source_ref: str,
    content: bytes = CONTENT,
):
    return evidence.capture(
        content=content,
        filename="orders.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref=source_ref,
        grade=EvidenceGrade.A,
        effective_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        effective_until=None,
        created_by="operator-a",
    )


def import_native(
    scoped,
    evidence_id: str,
    *,
    principal_value=None,
    entity_value=None,
):
    return scoped.import_file(
        filename="orders.csv",
        content=CONTENT,
        evidence_id=evidence_id,
        principal=principal_value or principal(),
        entity_scope=entity_value or entity_scope(),
        store_ref="store-a",
        as_of=datetime.now(UTC),
    )


def test_native_import_freezes_scope_and_replays_without_fact_promotion():
    _, evidence, _, scoped = services()
    source = source_evidence(evidence, source_ref="tenant-a-orders")

    first = import_native(scoped, source.id)
    replay = import_native(scoped, source.id)

    assert replay["id"] == first["id"]
    assert replay["duplicate"] is True
    assert first["scope"]["tenant_ref"] == "tenant-a"
    assert first["scope"]["entity_ref"] == "entity-a"
    assert first["scope"]["store_ref"] == "store-a"
    assert first["scope"]["source_evidence_sha256"] == source.sha256
    assert first["formal_fact_promotion_allowed"] is False
    assert first["accounting_posted"] is False
    assert first["product_mapping_performed"] is False
    assert first["external_write_allowed"] is False


def test_same_file_is_independent_across_tenants_and_exact_id_is_scoped():
    _, evidence, _, scoped = services()
    source_a = source_evidence(
        evidence,
        source_ref="tenant-a-orders",
    )
    source_b = source_evidence(
        evidence,
        source_ref="tenant-b-orders",
    )
    imported_a = import_native(scoped, source_a.id)
    imported_b = import_native(
        scoped,
        source_b.id,
        principal_value=principal(tenant_ref="tenant-b"),
        entity_value=entity_scope(
            entity_ref="entity-b",
            authority="b" * 64,
        ),
    )

    assert imported_a["id"] != imported_b["id"]
    with pytest.raises(KeyError, match="authorized scope"):
        scoped.get(
            imported_b["id"],
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=datetime.now(UTC),
        )


def test_changed_grant_and_bad_evidence_fail_before_new_import():
    engine, evidence, _, scoped = services()
    source = source_evidence(evidence, source_ref="tenant-a-orders")
    import_native(scoped, source.id)

    with pytest.raises(ValueError, match="grant authority changed"):
        scoped.find_by_content(
            CONTENT,
            principal=principal(),
            entity_scope=entity_scope(authority="9" * 64),
            store_ref="store-a",
            as_of=datetime.now(UTC),
        )
    mismatched = source_evidence(
        evidence,
        source_ref="wrong-content",
        content=b"different",
    )
    with pytest.raises(ValueError, match="invalid or mismatched"):
        import_native(scoped, mismatched.id)
    with Session(engine) as session:
        assert session.scalar(
            select(ImportJobRow).where(
                ImportJobRow.tenant_ref == "tenant-a"
            )
        ).id


def test_missing_entity_fails_before_evidence_or_import_read():
    _, _, _, scoped = services()

    class MustNotRead:
        def connect(self):
            raise AssertionError("database must not be read")

    class EvidenceMustNotRead:
        def require_current(self, *_args, **_kwargs):
            raise AssertionError("Evidence must not be read")

    scoped.engine = MustNotRead()
    scoped.evidence = EvidenceMustNotRead()
    missing = {
        "status": "no_data",
        "entity_ref": None,
        "authority_sha256": None,
        "reason": "entity_scope_authority_missing",
    }

    with pytest.raises(ValueError, match="entity scope grant"):
        scoped.get(
            "import-never-read",
            principal=principal(),
            entity_scope=missing,
            store_ref="store-a",
            as_of=datetime.now(UTC),
        )
    with pytest.raises(ValueError, match="entity scope grant"):
        import_native(
            scoped,
            "evd-never-read",
            entity_value=missing,
        )


def test_database_rejects_partial_scope_and_scopes_file_hash():
    engine, evidence, _, scoped = services()
    source = source_evidence(evidence, source_ref="tenant-a-orders")
    imported = import_native(scoped, source.id)

    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.execute(
            update(ImportJobRow)
            .where(ImportJobRow.id == imported["id"])
            .values(source_evidence_sha256=None)
        )


def test_import_routes_require_auth_exact_store_and_entity(monkeypatch):
    def reject(_):
        raise AuthenticationFailure(
            "X-KJDS-API-Key is required",
            401,
        )

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    client = TestClient(app)

    assert client.get("/v1/imports/import-x").status_code == 401
    assert (
        client.get("/v1/imports/import-x/finance-review").status_code
        == 401
    )
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
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )

    no_entity = client.get(
        "/v1/imports/import-x",
        params={"store_ref": "store-a"},
        headers={"X-KJDS-API-Key": "test"},
    )
    forbidden = client.get(
        "/v1/imports/import-x",
        params={"store_ref": "store-b"},
        headers={"X-KJDS-API-Key": "test"},
    )

    assert no_entity.status_code == 422
    assert forbidden.status_code == 403
    schema = app.openapi()
    assert schema["paths"]["/v1/imports/{import_id}"]["get"][
        "security"
    ] == [{"KjdsApiKey": []}]
    assert schema["paths"][
        "/v1/imports/{import_id}/finance-review"
    ]["get"]["security"] == [{"KjdsApiKey": []}]
