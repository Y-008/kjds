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
from apps.control_plane.marketplace_observation import (
    MarketplaceObservationWorkspace,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_marketplace_observation import (
    ScopedMarketplaceObservationAuthority,
)
from apps.control_plane.security import (
    AuthenticationFailure,
    Principal,
)
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


def request(
    *,
    store_ref: str,
    idempotency_key: str,
    external_item_id: str,
    observed_at: str = "2026-07-28T01:00:00Z",
) -> dict:
    return {
        "source_profile": "browser_observation",
        "marketplace": "1688",
        "store_ref": store_ref,
        "source_url": (
            f"https://detail.1688.com/offer/{external_item_id}.html"
        ),
        "observed_at": observed_at,
        "idempotency_key": idempotency_key,
        "confirmed": True,
        "items": [
            {
                "external_item_id": external_item_id,
                "supplier_ref": f"supplier-{external_item_id}",
                "title": f"observed item {external_item_id}",
                "variant_key": "black-3-pack",
                "currency": "CNY",
                "displayed_price": "19.90",
                "price_kind": "public_display_price",
                "min_order_quantity": 1,
                "availability": "in_stock",
                "specifications": {
                    "color": "black",
                    "quantity": "3",
                },
            }
        ],
    }


def bind(
    evidence: EvidenceService,
    target_id: str,
    *,
    tenant_ref: str,
    entity_ref: str,
    store_ref: str,
) -> str:
    target = evidence.get(target_id)
    binding = evidence.capture(
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
    return binding.id


def services():
    engine = database()
    evidence = EvidenceService(engine)
    raw = MarketplaceObservationWorkspace(
        engine=engine,
        evidence=evidence,
    )
    authority = ScopedMarketplaceObservationAuthority(
        observations=raw,
        scoped_evidence=ScopedEvidenceAuthority(evidence=evidence),
    )
    return engine, evidence, raw, authority


def test_missing_entity_scope_returns_no_data_without_reading_raw():
    class RawMustNotRun:
        @staticmethod
        def latest(**_):
            raise AssertionError("raw Observation must not be read")

    authority = ScopedMarketplaceObservationAuthority(
        observations=RawMustNotRun(),
        scoped_evidence=object(),
    )
    result = authority.latest(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-a",
        as_of=AS_OF,
        marketplace="1688",
    )

    assert result["status"] == "no_data"
    assert result["items"] == []
    assert result["counts"]["queried_in_exact_store_scope"] == 0
    assert result["scope"]["entity_ref"] is None
    assert result["blockers"][0]["owner"] == "identity-governance"
    assert result["control_envelope"]["external_write_allowed"] is False


def test_exact_store_evidence_scope_and_as_of_are_deterministic():
    _, evidence, raw, authority = services()
    store_a = raw.capture(
        request(
            store_ref="store-a",
            idempotency_key="store-a-current",
            external_item_id="100",
        ),
        actor_id="collector-a",
    )
    store_b = raw.capture(
        request(
            store_ref="store-b",
            idempotency_key="store-b-current",
            external_item_id="100",
        ),
        actor_id="collector-b",
    )
    future = raw.capture(
        request(
            store_ref="store-a",
            idempotency_key="store-a-future",
            external_item_id="200",
            observed_at="2026-07-28T03:00:00Z",
        ),
        actor_id="collector-a",
    )
    external = raw.capture(
        request(
            store_ref="external",
            idempotency_key="legacy-external",
            external_item_id="300",
        ),
        actor_id="legacy-collector",
    )
    bind(
        evidence,
        store_a["evidence_id"],
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
    )
    bind(
        evidence,
        store_b["evidence_id"],
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
    )
    bind(
        evidence,
        future["evidence_id"],
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
    )
    bind(
        evidence,
        external["evidence_id"],
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
    )

    values = {
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "as_of": AS_OF,
        "marketplace": "1688",
    }
    first = authority.latest(**values)
    second = authority.latest(**values)

    assert first == second
    assert first["status"] == "ready"
    assert first["counts"] == {
        "queried_in_exact_store_scope": 1,
        "included": 1,
        "excluded": 0,
    }
    assert [item["external_item_id"] for item in first["items"]] == ["100"]
    assert first["scope"] == {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "scope_grant_authority_sha256": "a" * 64,
    }
    assert first["evidence_authority_sha256"]
    assert first["control_envelope"]["observation_input_ready"] is True
    assert first["control_envelope"]["candidate_scoring_allowed"] is False

    after_future = authority.latest(
        **{**values, "as_of": datetime(2026, 7, 28, 4, tzinfo=UTC)}
    )
    assert {
        item["external_item_id"] for item in after_future["items"]
    } == {"100", "200"}
    assert "300" not in {
        item["external_item_id"] for item in after_future["items"]
    }


def test_unbound_cross_scope_and_damaged_evidence_disclose_only_counts():
    engine, evidence, raw, authority = services()
    unbound = raw.capture(
        request(
            store_ref="store-a",
            idempotency_key="unbound",
            external_item_id="unbound-secret",
        ),
        actor_id="collector-a",
    )
    cross_scope = raw.capture(
        request(
            store_ref="store-a",
            idempotency_key="cross-scope",
            external_item_id="cross-scope-secret",
        ),
        actor_id="collector-a",
    )
    damaged = raw.capture(
        request(
            store_ref="store-a",
            idempotency_key="damaged",
            external_item_id="damaged-secret",
        ),
        actor_id="collector-a",
    )
    bind(
        evidence,
        cross_scope["evidence_id"],
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-a",
    )
    bind(
        evidence,
        damaged["evidence_id"],
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
    )
    damaged_record = evidence.get(damaged["evidence_id"])
    with Session(engine) as session, session.begin():
        blob = session.get(EvidenceBlobRow, damaged_record.sha256)
        assert blob is not None
        blob.content_bytes = b"corrupted"

    result = authority.latest(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        marketplace="1688",
    )
    serialized = str(result)

    assert result["status"] == "blocked"
    assert result["items"] == []
    assert result["excluded"]["count"] == 3
    assert result["excluded"]["details_disclosed"] is False
    assert "unbound-secret" not in serialized
    assert "cross-scope-secret" not in serialized
    assert "damaged-secret" not in serialized
    assert unbound["evidence_id"] not in serialized
    assert cross_scope["evidence_id"] not in serialized
    assert damaged["evidence_id"] not in serialized
    assert result["control_envelope"]["candidate_scoring_allowed"] is False


def test_scoped_page_never_emits_cursor_for_excluded_row():
    _, _, raw, authority = services()
    raw.capture(
        request(
            store_ref="store-a",
            idempotency_key="page-unbound",
            external_item_id="page-secret",
        ),
        actor_id="collector-a",
    )

    result = authority.page(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        marketplace="1688",
        page_size=1,
    )

    assert result["items"] == []
    assert result["pagination"]["next_cursor"] is None
    assert "page-secret" not in str(result)


def test_scoped_observation_authentication_and_store_scope(monkeypatch):
    def reject_missing_key(_):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        reject_missing_key,
    )
    assert (
        TestClient(app).get(
            "/v1/marketplace-observations",
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
            "/v1/marketplace-observations",
            params={"store_ref": "store-b"},
            headers={"X-KJDS-API-Key": "test-key"},
        ).status_code
        == 403
    )

    with pytest.raises(PermissionError, match="not authorized"):
        ScopedMarketplaceObservationAuthority(
            observations=object(),
            scoped_evidence=object(),
        ).latest(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-b",
            as_of=AS_OF,
        )
