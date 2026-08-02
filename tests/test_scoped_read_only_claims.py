from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.evidence import (
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.evidence_scope import (
    DIRECT_CONTRACT,
    ScopedEvidenceAuthority,
)
from apps.control_plane.pilot_readiness import PilotReadinessService
from apps.control_plane.pilot_runs import (
    PilotRunService,
    ReadOnlyPilotRunRow,
)
from apps.control_plane.read_only_claims import (
    ReadOnlyClaimRow,
    ReadOnlyClaimService,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_read_only_claims import (
    ScopedReadOnlyClaimAuthority,
)
from apps.control_plane.scoped_read_only_pilots import (
    ScopedReadOnlyPilotAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.sql_repository import Base

AS_OF = datetime.now(UTC) - timedelta(minutes=2)


class Incidents:
    def list(self):
        return []


class Switch:
    def current(self):
        return SimpleNamespace(engaged=False)


def principal(
    *,
    tenant_ref: str = "tenant-a",
    actor_id: str = "operator-a",
    stores: frozenset[str] = frozenset({"store-a"}),
) -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=frozenset(
            {
                "operator",
                "reviewer",
                "compliance",
                "pilot_reader",
            }
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
    pilots = PilotReadinessService(
        engine=engine,
        evidence=evidence,
        incidents=Incidents(),
        kill_switch=Switch(),
    )
    runs = PilotRunService(
        engine=engine,
        pilots=pilots,
        evidence=evidence,
    )
    scoped_evidence = ScopedEvidenceAuthority(evidence=evidence)
    scoped_pilots = ScopedReadOnlyPilotAuthority(
        engine=engine,
        pilots=pilots,
        pilot_runs=runs,
        scoped_evidence=scoped_evidence,
    )
    claims = ReadOnlyClaimService(engine=engine, evidence=evidence)
    scoped_claims = ScopedReadOnlyClaimAuthority(
        engine=engine,
        claims=claims,
        scoped_pilots=scoped_pilots,
        scoped_evidence=scoped_evidence,
    )
    return (
        engine,
        evidence,
        pilots,
        runs,
        claims,
        scoped_pilots,
        scoped_claims,
    )


def scoped_evidence(
    evidence,
    *,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
    source_ref: str,
    effective_until: datetime | None = None,
):
    return evidence.capture(
        content=f"{tenant_ref}:{entity_ref}:{source_ref}".encode(),
        filename=f"{source_ref}.json",
        content_type="application/json",
        source="test",
        source_ref=source_ref,
        grade=EvidenceGrade.A,
        effective_at=(AS_OF - timedelta(hours=1)).isoformat(),
        effective_until=(
            effective_until.isoformat()
            if effective_until is not None
            else None
        ),
        created_by="evidence-owner",
        metadata={
            "evidence_scope_contract_id": DIRECT_CONTRACT,
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "reviewed_by": "independent-reviewer",
        },
    )


def native_run(
    values,
    *,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    grant_hash: str = "a" * 64,
    suffix: str = "a",
    run_evidence_until: datetime | None = None,
):
    engine, evidence, _, _, _, scoped_pilots, _ = values
    principal_value = principal(tenant_ref=tenant_ref)
    entity_value = entity_scope(
        entity_ref=entity_ref,
        authority=grant_hash,
    )
    pilot_evidence = scoped_evidence(
        evidence,
        tenant_ref=tenant_ref,
        entity_ref=entity_ref,
        source_ref=f"pilot-{suffix}",
    )
    pilot = scoped_pilots.create(
        principal=principal_value,
        entity_scope=entity_value,
        store_ref="store-a",
        as_of=AS_OF,
        requested_by=principal_value.actor_id,
        idempotency_key=f"pilot-{suffix}",
        platform="ozon",
        account_alias=f"ozon-{suffix}",
        allowed_operations=["ozon.product.read"],
        max_daily_requests=10,
        max_targets=3,
        starts_at=(AS_OF - timedelta(days=1)).isoformat(),
        ends_at=(AS_OF + timedelta(days=2)).isoformat(),
        evidence_ids=[pilot_evidence.id],
    )
    run_evidence = scoped_evidence(
        evidence,
        tenant_ref=tenant_ref,
        entity_ref=entity_ref,
        source_ref=f"run-{suffix}",
        effective_until=run_evidence_until,
    )
    run_id = f"run-{suffix}"
    state_hash = (suffix[0].lower() if suffix[0].isalnum() else "a") * 64
    if len(state_hash) != 64 or any(
        character not in "0123456789abcdef" for character in state_hash
    ):
        state_hash = "e" * 64
    with Session(engine) as session, session.begin():
        session.add(
            ReadOnlyPilotRunRow(
                id=run_id,
                idempotency_key=f"run-key-{suffix}",
                request_hash="b" * 64,
                pilot_id=pilot["id"],
                operation="ozon.product.read",
                target_hash="c" * 64,
                worker_id="reader",
                status="completed",
                outcome="succeeded",
                response_sha256="d" * 64,
                response_byte_size=10,
                record_count=2,
                summary_json={
                    "contract_version": "ozon-product-read-v1",
                    "state_sha256": state_hash,
                    "info_item_count": 1,
                    "attribute_item_count": 1,
                },
                error_code=None,
                evidence_id=run_evidence.id,
                started_at=AS_OF - timedelta(minutes=1),
                lease_expires_at=AS_OF + timedelta(minutes=10),
                completed_at=AS_OF - timedelta(seconds=30),
                request_id=f"request-{suffix}",
                trace_id=f"trace-{suffix}",
            )
        )
    return principal_value, entity_value, run_id, state_hash, run_evidence


def propose(
    scoped_claims,
    principal_value,
    entity_value,
    run_id,
    state_hash,
    *,
    key: str = "claim-key",
):
    return scoped_claims.propose(
        run_id,
        principal=principal_value,
        entity_scope=entity_value,
        store_ref="store-a",
        as_of=datetime.now(UTC),
        proposed_by=principal_value.actor_id,
        idempotency_key=key,
        claim_type="product_attribute",
        payload={"stock_count": 4},
        source_state_sha256=state_hash,
        effective_at=(AS_OF - timedelta(seconds=10)).isoformat(),
    )


def test_native_claim_freezes_scope_evidence_and_replays():
    values = services()
    *_, scoped_claims = values
    actor, entity, run_id, state_hash, _ = native_run(values)

    created = propose(
        scoped_claims,
        actor,
        entity,
        run_id,
        state_hash,
    )
    replay = propose(
        scoped_claims,
        actor,
        entity,
        run_id,
        state_hash,
    )

    assert replay["id"] == created["id"]
    assert created["scope"]["tenant_ref"] == "tenant-a"
    assert created["scope"]["entity_ref"] == "entity-a"
    assert created["scope"]["store_ref"] == "store-a"
    assert created["scope"]["authority"] == "native"
    assert len(
        created["scope"]["scope_evidence_authority_sha256"]
    ) == 64
    assert created["authority_status"] == "ready"
    assert created["formal_fact_promoted"] is False
    assert created["external_write_allowed"] is False


def test_claim_queries_exclude_legacy_and_cross_tenant_before_serialization():
    values = services()
    _, _, _, _, raw_claims, _, scoped_claims = values
    actor_a, entity_a, run_a, state_a, _ = native_run(values, suffix="a")
    actor_b, entity_b, run_b, state_b, _ = native_run(
        values,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        grant_hash="9" * 64,
        suffix="b",
    )
    claim_a = propose(
        scoped_claims,
        actor_a,
        entity_a,
        run_a,
        state_a,
    )
    claim_b = propose(
        scoped_claims,
        actor_b,
        entity_b,
        run_b,
        state_b,
    )
    legacy = raw_claims.propose(
        run_a,
        idempotency_key="legacy-claim",
        claim_type="price_observation",
        payload={"currency_code": "RUB", "amount": 10},
        source_state_sha256=state_a,
        effective_at=(AS_OF - timedelta(seconds=10)).isoformat(),
        proposed_by="legacy-reader",
    )

    listing = scoped_claims.list(
        principal=actor_a,
        entity_scope=entity_a,
        store_ref="store-a",
        as_of=datetime.now(UTC),
    )

    assert [item["id"] for item in listing["items"]] == [claim_a["id"]]
    assert listing["legacy_rows_inferred"] is False
    with pytest.raises(KeyError, match="authorized scope"):
        scoped_claims.get(
            claim_b["id"],
            principal=actor_a,
            entity_scope=entity_a,
            store_ref="store-a",
            as_of=datetime.now(UTC),
        )
    with pytest.raises(KeyError, match="authorized scope"):
        scoped_claims.get(
            legacy["id"],
            principal=actor_a,
            entity_scope=entity_a,
            store_ref="store-a",
            as_of=datetime.now(UTC),
        )


def test_missing_entity_returns_no_data_without_claim_or_evidence_read():
    values = services()
    *_, scoped_claims = values

    class MustNotRead:
        def connect(self):
            raise AssertionError("database must not be read")

    class EvidenceMustNotRead:
        def project_targets(self, **_values):
            raise AssertionError("Evidence must not be read")

    scoped_claims.engine = MustNotRead()
    scoped_claims.scoped_evidence = EvidenceMustNotRead()
    missing = {
        "status": "no_data",
        "entity_ref": None,
        "authority_sha256": None,
        "reason": "entity_scope_authority_missing",
    }

    result = scoped_claims.list(
        principal=principal(),
        entity_scope=missing,
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["items"] == []
    assert result["counts"]["claims"] == 0
    with pytest.raises(ValueError, match="entity scope grant"):
        scoped_claims.get(
            "claim-never-read",
            principal=principal(),
            entity_scope=missing,
            store_ref="store-a",
            as_of=AS_OF,
        )


def test_unbound_run_evidence_creates_no_native_claim():
    values = services()
    engine, evidence, _, _, _, _, scoped_claims = values
    actor, entity, run_id, state_hash, _ = native_run(values)
    unbound = evidence.capture(
        content=b"unbound-run",
        filename="unbound.json",
        content_type="application/json",
        source="test",
        source_ref="unbound-run",
        grade=EvidenceGrade.A,
        effective_at=(AS_OF - timedelta(hours=1)).isoformat(),
        effective_until=None,
        created_by="owner",
    )
    with Session(engine) as session, session.begin():
        session.execute(
            update(ReadOnlyPilotRunRow)
            .where(ReadOnlyPilotRunRow.id == run_id)
            .values(evidence_id=unbound.id)
        )

    with pytest.raises(ValueError, match="not current and"):
        propose(
            scoped_claims,
            actor,
            entity,
            run_id,
            state_hash,
        )
    with Session(engine) as session:
        assert session.scalars(
            select(ReadOnlyClaimRow).where(
                ReadOnlyClaimRow.tenant_ref.is_not(None)
            )
        ).all() == []


def test_review_revalidates_grant_evidence_and_independent_actor():
    values = services()
    engine, _, _, _, _, _, scoped_claims = values
    actor, entity, run_id, state_hash, run_evidence = native_run(values)
    claim = propose(
        scoped_claims,
        actor,
        entity,
        run_id,
        state_hash,
    )

    with pytest.raises(KeyError, match="authorized scope"):
        scoped_claims.review(
            claim["id"],
            principal=principal(actor_id="reviewer-a"),
            entity_scope=entity_scope(authority="7" * 64),
            store_ref="store-a",
            as_of=datetime.now(UTC),
            reviewed_by="reviewer-a",
            decision="accepted",
            rationale="scope changed",
        )
    with pytest.raises(ValueError, match="independent"):
        scoped_claims.review(
            claim["id"],
            principal=actor,
            entity_scope=entity,
            store_ref="store-a",
            as_of=datetime.now(UTC),
            reviewed_by=actor.actor_id,
            decision="accepted",
            rationale="self review",
        )
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceRecordRow)
            .where(EvidenceRecordRow.id == run_evidence.id)
            .values(effective_until=AS_OF)
        )
    with pytest.raises(ValueError, match="not current and"):
        scoped_claims.review(
            claim["id"],
            principal=principal(actor_id="reviewer-a"),
            entity_scope=entity,
            store_ref="store-a",
            as_of=datetime.now(UTC),
            reviewed_by="reviewer-a",
            decision="accepted",
            rationale="expired",
        )


def test_database_rejects_partial_scope_and_scopes_idempotency():
    values = services()
    engine, _, _, _, _, _, scoped_claims = values
    actor_a, entity_a, run_a, state_a, _ = native_run(values, suffix="a")
    actor_b, entity_b, run_b, state_b, _ = native_run(
        values,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        grant_hash="9" * 64,
        suffix="b",
    )
    claim_a = propose(
        scoped_claims,
        actor_a,
        entity_a,
        run_a,
        state_a,
        key="same-client-key",
    )
    claim_b = propose(
        scoped_claims,
        actor_b,
        entity_b,
        run_b,
        state_b,
        key="same-client-key",
    )

    assert claim_a["id"] != claim_b["id"]
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.execute(
            update(ReadOnlyClaimRow)
            .where(ReadOnlyClaimRow.id == claim_a["id"])
            .values(scope_evidence_authority_sha256=None)
        )


def test_claim_routes_require_auth_exact_store_and_entity(monkeypatch):
    def reject(_):
        raise AuthenticationFailure(
            "X-KJDS-API-Key is required",
            401,
        )

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    client = TestClient(app)

    assert client.get("/v1/read-only-claims").status_code == 401
    assert client.get("/v1/read-only-claims/claim-x").status_code == 401
    assert (
        client.post(
            "/v1/read-only-claims/claim-x/review",
            json={"decision": "accepted", "rationale": "reviewed"},
        ).status_code
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
        "/v1/read-only-claims",
        params={"store_ref": "store-a"},
        headers={"X-KJDS-API-Key": "test"},
    )
    forbidden = client.get(
        "/v1/read-only-claims",
        params={"store_ref": "store-b"},
        headers={"X-KJDS-API-Key": "test"},
    )

    assert no_entity.status_code == 200
    assert no_entity.json()["status"] == "no_data"
    assert no_entity.json()["items"] == []
    assert forbidden.status_code == 403
    schema = app.openapi()
    assert schema["paths"]["/v1/read-only-claims"]["get"][
        "security"
    ] == [{"KjdsApiKey": []}]
    assert schema["paths"]["/v1/read-only-claims/{claim_id}"][
        "get"
    ]["security"] == [{"KjdsApiKey": []}]
