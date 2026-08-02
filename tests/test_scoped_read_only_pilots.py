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
from apps.control_plane.pilot_readiness import (
    PilotReadinessService,
    ReadOnlyPilotRow,
)
from apps.control_plane.pilot_runs import (
    PilotRunService,
    ReadOnlyPilotRunRow,
)
from apps.control_plane.runtime import runtime
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


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    engine = database()
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
    scoped = ScopedReadOnlyPilotAuthority(
        engine=engine,
        pilots=pilots,
        pilot_runs=runs,
        scoped_evidence=ScopedEvidenceAuthority(evidence=evidence),
    )
    return engine, evidence, pilots, runs, scoped


def scoped_evidence(
    evidence,
    *,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
    source_ref: str = "pilot-source-a",
):
    return evidence.capture(
        content=f"{tenant_ref}:{entity_ref}:{store_ref}".encode(),
        filename=f"{source_ref}.txt",
        content_type="text/plain",
        source="test",
        source_ref=source_ref,
        grade=EvidenceGrade.A,
        effective_at=(AS_OF - timedelta(hours=1)).isoformat(),
        effective_until=None,
        created_by="evidence-owner",
        metadata={
            "evidence_scope_contract_id": DIRECT_CONTRACT,
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "reviewed_by": "independent-reviewer",
        },
    )


def create_native(
    scoped,
    evidence_id: str,
    *,
    principal_value=None,
    entity_scope_value=None,
    idempotency_key: str = "native-pilot-key",
):
    principal_value = principal_value or principal()
    entity_scope_value = entity_scope_value or entity_scope()
    return scoped.create(
        principal=principal_value,
        entity_scope=entity_scope_value,
        store_ref="store-a",
        as_of=AS_OF,
        requested_by=principal_value.actor_id,
        idempotency_key=idempotency_key,
        platform="ozon",
        account_alias="ozon-main",
        allowed_operations=["ozon.product.read"],
        max_daily_requests=10,
        max_targets=3,
        starts_at=(AS_OF - timedelta(days=1)).isoformat(),
        ends_at=(AS_OF + timedelta(days=2)).isoformat(),
        evidence_ids=[evidence_id],
    )


def add_run(engine, *, pilot_id: str, run_id: str):
    with Session(engine) as session, session.begin():
        session.add(
            ReadOnlyPilotRunRow(
                id=run_id,
                idempotency_key=f"key-{run_id}",
                request_hash="b" * 64,
                pilot_id=pilot_id,
                operation="ozon.product.read",
                target_hash="c" * 64,
                worker_id="reader",
                request_id=f"req-{run_id}",
                trace_id=f"trace-{run_id}",
                status="started",
                outcome=None,
                response_sha256=None,
                response_byte_size=None,
                record_count=None,
                summary_json=None,
                error_code=None,
                evidence_id=None,
                started_at=AS_OF - timedelta(minutes=1),
                lease_expires_at=AS_OF + timedelta(minutes=10),
                completed_at=None,
            )
        )


def test_native_create_freezes_scope_and_scoped_evidence_authority():
    _, evidence, _, _, scoped = services()
    source = scoped_evidence(evidence)

    created = create_native(scoped, source.id)
    replay = create_native(scoped, source.id)

    assert created == replay
    assert created["scope"]["tenant_ref"] == "tenant-a"
    assert created["scope"]["entity_ref"] == "entity-a"
    assert created["scope"]["store_ref"] == "store-a"
    assert (
        len(created["scope"]["scope_evidence_authority_sha256"])
        == 64
    )
    assert created["scope"]["authority"] == "native"
    assert created["platform_write_allowed"] is False
    assert created["external_write_allowed"] is False


def test_scoped_lists_exclude_legacy_and_other_tenant_before_runs():
    engine, evidence, pilots, _, scoped = services()
    source_a = scoped_evidence(evidence)
    source_b = scoped_evidence(
        evidence,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        source_ref="pilot-source-b",
    )
    native_a = create_native(scoped, source_a.id)
    native_b = create_native(
        scoped,
        source_b.id,
        principal_value=principal(tenant_ref="tenant-b"),
        entity_scope_value=entity_scope(
            entity_ref="entity-b",
            authority="9" * 64,
        ),
    )
    legacy = pilots.create(
        idempotency_key="legacy-key",
        platform="ozon",
        account_alias="legacy-account",
        allowed_operations=["ozon.product.read"],
        max_daily_requests=10,
        max_targets=3,
        starts_at=(AS_OF - timedelta(days=1)).isoformat(),
        ends_at=(AS_OF + timedelta(days=2)).isoformat(),
        evidence_ids=[source_a.id],
        requested_by="legacy-owner",
    )
    add_run(engine, pilot_id=native_a["id"], run_id="run-a")
    add_run(engine, pilot_id=native_b["id"], run_id="run-b")
    add_run(engine, pilot_id=legacy["id"], run_id="run-legacy")
    read_cutoff = datetime.now(UTC)

    pilots_a = scoped.list(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=read_cutoff,
    )
    runs_a = scoped.list_runs(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=read_cutoff,
    )

    assert [item["id"] for item in pilots_a["items"]] == [
        native_a["id"]
    ]
    assert [item["id"] for item in runs_a["items"]] == ["run-a"]
    with pytest.raises(KeyError, match="authorized scope"):
        scoped.get_run(
            "run-b",
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=read_cutoff,
        )
    with pytest.raises(KeyError, match="authorized scope"):
        scoped.get(
            legacy["id"],
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=read_cutoff,
        )


def test_missing_entity_returns_no_data_without_database_or_evidence_read():
    _, _, _, _, scoped = services()

    class MustNotRead:
        def connect(self):
            raise AssertionError("database must not be read")

    class EvidenceMustNotRead:
        def project_targets(self, **_values):
            raise AssertionError("Evidence must not be read")

    scoped.engine = MustNotRead()
    scoped.scoped_evidence = EvidenceMustNotRead()
    missing = {
        "status": "no_data",
        "entity_ref": None,
        "authority_sha256": None,
        "reason": "entity_scope_authority_missing",
    }

    listing = scoped.list(
        principal=principal(),
        entity_scope=missing,
        store_ref="store-a",
        as_of=AS_OF,
    )
    runs = scoped.list_runs(
        principal=principal(),
        entity_scope=missing,
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert listing["status"] == "no_data"
    assert listing["items"] == []
    assert runs["status"] == "no_data"
    assert runs["items"] == []
    with pytest.raises(ValueError, match="entity scope grant"):
        create_native(
            scoped,
            "evd-never-read",
            entity_scope_value=missing,
        )


def test_bad_or_unbound_evidence_creates_no_native_pilot():
    engine, evidence, _, _, scoped = services()
    unbound = evidence.capture(
        content=b"unbound",
        filename="unbound.txt",
        content_type="text/plain",
        source="test",
        source_ref="unbound",
        grade=EvidenceGrade.A,
        effective_at=(AS_OF - timedelta(hours=1)).isoformat(),
        effective_until=None,
        created_by="owner",
    )

    with pytest.raises(ValueError, match="not current and"):
        create_native(scoped, unbound.id)

    with Session(engine) as session:
        assert session.scalars(
            select(ReadOnlyPilotRow).where(
                ReadOnlyPilotRow.tenant_ref.is_not(None)
            )
        ).all() == []


def test_distinct_subject_hash_same_scope_can_require_pilot_and_expired_evidence_blocks():
    engine, evidence, _, _, scoped = services()
    source = evidence.capture(
        content=b"expiring-scoped-evidence",
        filename="expiring.txt",
        content_type="text/plain",
        source="test",
        source_ref="expiring-pilot-source",
        grade=EvidenceGrade.A,
        effective_at=(AS_OF - timedelta(hours=1)).isoformat(),
        effective_until=(AS_OF + timedelta(days=1)).isoformat(),
        created_by="evidence-owner",
        metadata={
            "evidence_scope_contract_id": DIRECT_CONTRACT,
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "reviewed_by": "independent-reviewer",
        },
    )
    native = create_native(scoped, source.id)

    # A distinct subject with its own grant authority hash on the same exact
    # tenant/entity/store scope may review/operate the pilot (SoD review).
    fresh_cutoff = datetime.now(UTC)
    scoped.require_pilot(
        native["id"],
        principal=principal(),
        entity_scope=entity_scope(authority="7" * 64),
        store_ref="store-a",
        as_of=fresh_cutoff,
    )
    with Session(engine) as session, session.begin():
        record = evidence.get(source.id)
        session.execute(
            update(EvidenceRecordRow)
            .where(EvidenceRecordRow.id == source.id)
            .values(
                effective_until=(
                    fresh_cutoff - timedelta(minutes=1)
                )
            )
        )
        assert record.id
    with pytest.raises(ValueError, match="not current and"):
        scoped.require_pilot(
            native["id"],
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=fresh_cutoff,
        )


def test_reaper_only_changes_runs_joined_to_authorized_pilots():
    engine, evidence, _, _, scoped = services()
    source_a = scoped_evidence(evidence)
    source_b = scoped_evidence(
        evidence,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        source_ref="pilot-source-b",
    )
    native_a = create_native(scoped, source_a.id)
    native_b = create_native(
        scoped,
        source_b.id,
        principal_value=principal(tenant_ref="tenant-b"),
        entity_scope_value=entity_scope(
            entity_ref="entity-b",
            authority="9" * 64,
        ),
    )
    add_run(engine, pilot_id=native_a["id"], run_id="run-expired-a")
    add_run(engine, pilot_id=native_b["id"], run_id="run-expired-b")
    with Session(engine) as session, session.begin():
        session.execute(
            update(ReadOnlyPilotRunRow).values(
                lease_expires_at=AS_OF - timedelta(minutes=1)
            )
        )

    result = scoped.reap_expired(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=datetime.now(UTC),
        limit=100,
        actor_id="admin-a",
    )

    assert result["run_ids"] == ["run-expired-a"]
    assert result["external_write_allowed"] is False
    with Session(engine) as session:
        statuses = {
            row.id: row.status
            for row in session.scalars(
                select(ReadOnlyPilotRunRow).where(
                    ReadOnlyPilotRunRow.id.in_(
                        {"run-expired-a", "run-expired-b"}
                    )
                )
            )
        }
    assert statuses == {
        "run-expired-a": "expired",
        "run-expired-b": "started",
    }


def test_database_rejects_partial_scope_and_scopes_idempotency():
    engine, evidence, _, _, scoped = services()
    source_a = scoped_evidence(evidence)
    source_b = scoped_evidence(
        evidence,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        source_ref="pilot-source-b",
    )
    native_a = create_native(scoped, source_a.id)
    native_b = create_native(
        scoped,
        source_b.id,
        principal_value=principal(tenant_ref="tenant-b"),
        entity_scope_value=entity_scope(
            entity_ref="entity-b",
            authority="9" * 64,
        ),
    )

    assert native_a["id"] != native_b["id"]
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.execute(
            update(ReadOnlyPilotRow)
            .where(ReadOnlyPilotRow.id == native_a["id"])
            .values(scope_grant_authority_sha256=None)
        )


def test_pilot_and_run_routes_require_auth_and_exact_store(monkeypatch):
    def reject(_):
        raise AuthenticationFailure(
            "X-KJDS-API-Key is required",
            401,
        )

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    client = TestClient(app)

    assert client.get("/v1/read-only-pilots").status_code == 401
    assert client.get("/v1/read-only-pilots/pilot-x").status_code == 401
    assert client.get("/v1/read-only-pilot-runs").status_code == 401
    assert (
        client.get("/v1/read-only-pilot-runs/run-x").status_code
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
        "/v1/read-only-pilots",
        params={"store_ref": "store-a"},
        headers={"X-KJDS-API-Key": "test"},
    )
    forbidden = client.get(
        "/v1/read-only-pilot-runs",
        params={"store_ref": "store-b"},
        headers={"X-KJDS-API-Key": "test"},
    )
    rejected = client.post(
        "/v1/read-only-pilots",
        json={
            "idempotency_key": "api-pilot",
            "platform": "ozon",
            "account_alias": "ozon-main",
            "allowed_operations": ["ozon.product.read"],
            "max_daily_requests": 10,
            "max_targets": 3,
            "starts_at": (AS_OF - timedelta(days=1)).isoformat(),
            "ends_at": (AS_OF + timedelta(days=2)).isoformat(),
            "evidence_ids": ["evd-never-read"],
            "store_ref": "store-a",
        },
        headers={"X-KJDS-API-Key": "test"},
    )

    assert no_entity.status_code == 200
    assert no_entity.json()["status"] == "no_data"
    assert no_entity.json()["items"] == []
    assert forbidden.status_code == 403
    assert rejected.status_code == 422
    assert (
        rejected.json()["detail"]
        == "Read-only Pilot requires one current entity scope grant"
    )
    schema = app.openapi()
    assert schema["paths"]["/v1/read-only-pilots"]["get"][
        "security"
    ] == [{"KjdsApiKey": []}]
    assert schema["paths"]["/v1/read-only-pilot-runs/{run_id}"][
        "get"
    ]["security"] == [{"KjdsApiKey": []}]
