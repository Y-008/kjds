from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceService,
)
from apps.control_plane.scope_grants import (
    ScopeGrantAuthority,
    ScopeGrantEventRow,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base


def principal(
    actor_id: str,
    *,
    tenant_ref: str = "tenant-cn-1",
    roles: frozenset[str] = frozenset({"admin"}),
    stores: frozenset[str] = frozenset({"store-cn-1"}),
) -> Principal:
    return Principal(actor_id, roles, tenant_ref, stores)


def reviewed_authority_evidence(
    authority: ScopeGrantAuthority,
    evidence: EvidenceService,
    *,
    event_type: str = "grant",
    owner_actor_id: str = "legal-owner-1",
    reviewer_actor_id: str = "compliance-reviewer-1",
    source_idempotency_key: str = "scope-source-1",
    review_idempotency_key: str = "scope-review-1",
):
    submitted = authority.submit_source(
        principal=principal(
            owner_actor_id,
            roles=frozenset({"reviewer"}),
        ),
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type=event_type,
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        idempotency_key=source_idempotency_key,
        content=(
            f"organization entity and store authority: {event_type}"
        ).encode(),
        filename=f"scope-authority-{event_type}.txt",
        content_type="text/plain",
    )
    reviewed = authority.review_source(
        principal=principal(
            reviewer_actor_id,
            roles=frozenset({"risk"}),
        ),
        source_evidence_id=submitted["source_evidence_id"],
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type=event_type,
        effective_at="2026-07-01T00:00:00Z",
        accepted=True,
        authentic_original=True,
        owner_authority_verified=True,
        scope_matches=True,
        rationale="Verified owner authority and exact operating scope.",
        idempotency_key=review_idempotency_key,
    )
    return evidence.get(reviewed["review_evidence_id"])


def services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    authority = ScopeGrantAuthority(engine=engine, evidence=evidence)
    source = reviewed_authority_evidence(
        authority,
        evidence,
    )
    return engine, evidence, authority, source


def empty_services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    authority = ScopeGrantAuthority(engine=engine, evidence=evidence)
    return engine, evidence, authority


def grant(authority, source, **overrides):
    values = {
        "principal": principal("admin-1"),
        "entity_ref": "entity-cn-1",
        "store_ref": "store-cn-1",
        "subject_actor_id": "operator-1",
        "event_type": "grant",
        "effective_at": "2026-07-02T00:00:00Z",
        "evidence_id": source.id,
        "reason": "Approved entity and store operating authority.",
        "idempotency_key": "scope-grant-1",
    }
    return authority.record(**{**values, **overrides})


def test_scope_grant_is_immutable_idempotent_and_resolves_by_as_of():
    _, _, authority, source = services()

    created = grant(authority, source)
    replay = grant(authority, source)
    before = authority.current(
        principal=principal("operator-1", roles=frozenset({"operator"})),
        store_ref="store-cn-1",
        as_of=datetime(2026, 7, 1, 12, tzinfo=UTC),
    )
    active = authority.current(
        principal=principal("operator-1", roles=frozenset({"operator"})),
        store_ref="store-cn-1",
        as_of=datetime(2026, 7, 27, tzinfo=UTC),
    )

    assert created["immutable"] is True
    assert replay["idempotent"] is True
    assert replay["id"] == created["id"]
    assert before["status"] == "no_data"
    assert active["status"] == "ready"
    assert active["entity_ref"] == "entity-cn-1"
    assert active["authority_sha256"]
    assert active["tenant_ref"] == "tenant-cn-1"
    assert active["store_ref"] == "store-cn-1"
    assert before["tenant_ref"] == "tenant-cn-1"
    assert before["store_ref"] == "store-cn-1"

    with pytest.raises(ValueError, match="Idempotency key conflicts"):
        grant(authority, source, reason="Changed immutable reason.")


def test_scope_grant_preflight_is_non_mutating_and_matches_record_request():
    engine, _, authority, source = services()
    values = {
        "principal": principal("admin-1"),
        "entity_ref": "entity-cn-1",
        "store_ref": "store-cn-1",
        "subject_actor_id": "operator-1",
        "event_type": "grant",
        "effective_at": "2026-07-02T00:00:00Z",
        "evidence_id": source.id,
        "reason": "Approved entity and store operating authority.",
        "idempotency_key": "scope-grant-preflight-1",
    }

    preflight = authority.preflight(**values)
    with Session(engine) as session:
        assert session.query(ScopeGrantEventRow).count() == 0

    created = authority.record(**values)

    assert preflight["state"] == "ready"
    assert preflight["would_record_event"] is True
    assert preflight["event_recorded"] is False
    assert preflight["external_write_allowed"] is False
    assert preflight["request_sha256"] == created["request_sha256"]


def test_scope_authority_intake_is_exact_scope_as_of_and_non_mutating():
    engine, evidence, authority = empty_services()
    requester = principal(
        "legal-owner-1",
        roles=frozenset({"reviewer"}),
    )
    subject = principal(
        "operator-1",
        roles=frozenset({"operator"}),
    )
    before = authority.intake(
        principal=requester,
        subject=subject,
        store_ref="store-cn-1",
        entity_ref=None,
        event_type="grant",
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
    )
    no_data = authority.intake(
        principal=requester,
        subject=subject,
        store_ref="store-cn-1",
        entity_ref="entity-cn-1",
        event_type="grant",
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert before["state"] == "input_required"
    assert before["blocker_codes"] == ["entity_ref_required"]
    assert before["allowed_actions"]["submit_source"] is True
    assert before["allowed_actions"]["record_grant"] is False
    assert no_data["state"] == "no_data"
    assert no_data["counts"]["sources"] == 0
    assert no_data["external_write_allowed"] is False
    assert no_data["grant_endpoint_exposed"] is False
    with Session(engine) as session:
        assert session.query(ScopeGrantEventRow).count() == 0
        assert session.query(EvidenceBlobRow).count() == 0

    submitted = authority.submit_source(
        principal=requester,
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type="grant",
        effective_at="2026-07-02T00:00:00Z",
        effective_until=None,
        idempotency_key="intake-source-1",
        content=b"owner authority source",
        filename="owner-authority.txt",
        content_type="text/plain",
    )
    historical = authority.intake(
        principal=requester,
        subject=subject,
        store_ref="store-cn-1",
        entity_ref="entity-cn-1",
        event_type="grant",
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
    )
    pending = authority.intake(
        principal=requester,
        subject=subject,
        store_ref="store-cn-1",
        entity_ref="entity-cn-1",
        event_type="grant",
        as_of=datetime.now(UTC),
    )

    assert historical["state"] == "no_data"
    assert pending["state"] == "blocked"
    assert pending["blocker_codes"] == [
        "scope_authority_independent_review_missing"
    ]
    assert pending["candidates"][0]["source_evidence_id"] == (
        submitted["source_evidence_id"]
    )
    assert pending["candidates"][0]["review_state"] == (
        "pending_independent_review"
    )
    assert evidence.list_by_source(authority.SOURCE_NAME)[0].id == (
        submitted["source_evidence_id"]
    )


def test_scope_authority_intake_only_advances_on_independent_review():
    engine, evidence, authority = empty_services()
    owner = principal(
        "legal-owner-1",
        roles=frozenset({"reviewer"}),
    )
    reviewer = principal(
        "reviewer-1",
        roles=frozenset({"risk"}),
    )
    recorder = principal(
        "recorder-1",
        roles=frozenset({"compliance"}),
    )
    subject = principal(
        "operator-1",
        roles=frozenset({"operator"}),
    )
    source = authority.submit_source(
        principal=owner,
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id=subject.actor_id,
        event_type="grant",
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        idempotency_key="intake-ready-source",
        content=b"owner authority source",
        filename="owner-authority.txt",
        content_type="text/plain",
    )
    review = authority.review_source(
        principal=reviewer,
        source_evidence_id=source["source_evidence_id"],
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id=subject.actor_id,
        event_type="grant",
        effective_at="2026-07-01T00:00:00Z",
        accepted=True,
        authentic_original=True,
        owner_authority_verified=True,
        scope_matches=True,
        rationale="Exact source and owner authority verified.",
        idempotency_key="intake-ready-review",
    )

    ready = authority.intake(
        principal=recorder,
        subject=subject,
        store_ref="store-cn-1",
        entity_ref="entity-cn-1",
        event_type="grant",
        as_of=datetime.now(UTC),
    )
    reviewer_view = authority.intake(
        principal=reviewer,
        subject=subject,
        store_ref="store-cn-1",
        entity_ref="entity-cn-1",
        event_type="grant",
        as_of=datetime.now(UTC),
    )

    assert ready["state"] == "ready_for_preflight"
    assert ready["blocker_codes"] == []
    assert ready["counts"] == {
        "sources": 1,
        "reviews": 1,
        "ready_for_preflight": 1,
        "invalid_sources": 0,
        "invalid_reviews": 0,
    }
    assert ready["candidates"][0]["accepted_review_evidence_id"] == (
        review["review_evidence_id"]
    )
    assert ready["candidates"][0]["can_current_actor_preflight"] is True
    assert reviewer_view["candidates"][0][
        "can_current_actor_preflight"
    ] is False
    assert ready["snapshot_sha256"] != reviewer_view["snapshot_sha256"]
    with Session(engine) as session:
        assert session.query(ScopeGrantEventRow).count() == 0
        assert session.query(EvidenceBlobRow).count() == 2


def test_scope_authority_intake_rejects_unprivileged_cross_subject_inspection():
    _, _, authority = empty_services()

    with pytest.raises(PermissionError, match="authority workflow roles"):
        authority.intake(
            principal=principal(
                "operator-2",
                roles=frozenset({"operator"}),
            ),
            subject=principal(
                "operator-1",
                roles=frozenset({"operator"}),
            ),
            store_ref="store-cn-1",
            entity_ref="entity-cn-1",
            event_type="grant",
            as_of=datetime.now(UTC),
        )


def test_scope_authority_source_and_review_are_idempotent_lineage_not_metadata():
    _, evidence, authority, review = services()
    source_id = review.metadata["source_evidence_id"]
    source = evidence.get(source_id)

    source_replay = authority.submit_source(
        principal=principal(
            "legal-owner-1",
            roles=frozenset({"reviewer"}),
        ),
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type="grant",
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        idempotency_key="scope-source-1",
        content=b"organization entity and store authority: grant",
        filename="scope-authority-grant.txt",
        content_type="text/plain",
    )
    review_replay = authority.review_source(
        principal=principal(
            "compliance-reviewer-1",
            roles=frozenset({"risk"}),
        ),
        source_evidence_id=source.id,
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type="grant",
        effective_at="2026-07-01T00:00:00Z",
        accepted=True,
        authentic_original=True,
        owner_authority_verified=True,
        scope_matches=True,
        rationale="Verified owner authority and exact operating scope.",
        idempotency_key="scope-review-1",
    )

    assert source_replay["idempotent"] is True
    assert review_replay["idempotent"] is True
    assert source.grade == EvidenceGrade.B
    assert review.grade == EvidenceGrade.A
    assert review.created_by == "compliance-reviewer-1"
    assert review.metadata["reviewed_by"] == review.created_by
    assert review.id in evidence.target_evidence_ids(
        target_type="evidence",
        target_id=source.id,
        relationship="scope_authority_review",
    )


def test_scope_authority_review_and_record_require_three_independent_actors():
    _, evidence, authority, review = services()
    source_id = review.metadata["source_evidence_id"]

    with pytest.raises(PermissionError, match="independent reviewer"):
        authority.review_source(
            principal=principal(
                "legal-owner-1",
                roles=frozenset({"reviewer"}),
            ),
            source_evidence_id=source_id,
            entity_ref="entity-cn-1",
            store_ref="store-cn-1",
            subject_actor_id="operator-1",
            event_type="grant",
            effective_at="2026-07-01T00:00:00Z",
            accepted=True,
            authentic_original=True,
            owner_authority_verified=True,
            scope_matches=True,
            rationale="Self review must fail.",
            idempotency_key="scope-self-review",
        )

    result = authority.preflight(
        principal=principal("compliance-reviewer-1"),
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type="grant",
        effective_at="2026-07-02T00:00:00Z",
        evidence_id=review.id,
        reason="Reviewer cannot also record the grant.",
        idempotency_key="reviewer-record-conflict",
    )
    assert result["state"] == "blocked"
    assert result["blocker_codes"] == [
        "scope_authority_independent_review_missing"
    ]
    assert evidence.get(source_id).created_by == "legal-owner-1"


def test_uploader_authored_reviewed_by_metadata_cannot_authorize_scope():
    _, evidence, authority, _ = services()
    forged = evidence.capture(
        content=b"forged reviewed_by metadata",
        filename="forged-scope-review.json",
        content_type="application/json",
        source="organization-scope-authority",
        source_ref="internal://forged-scope-authority",
        grade=EvidenceGrade.A,
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        created_by="legal-owner-1",
        metadata={
            "scope_authority_contract_id":
                "kjds-scope-authority-evidence-v1",
            "tenant_ref": "tenant-cn-1",
            "entity_ref": "entity-cn-1",
            "store_ref": "store-cn-1",
            "subject_actor_id": "operator-1",
            "decision": "grant",
            "reviewed_by": "compliance-reviewer-1",
        },
    )

    result = authority.preflight(
        principal=principal("admin-1"),
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type="grant",
        effective_at="2026-07-02T00:00:00Z",
        evidence_id=forged.id,
        reason="Forged metadata cannot authorize scope.",
        idempotency_key="forged-reviewed-by",
    )

    assert result["state"] == "blocked"
    assert result["would_record_event"] is False


def test_scope_grant_preflight_reports_evidence_blocker_without_recording():
    engine, evidence, authority, _ = services()
    weak = evidence.capture(
        content=b"self reported scope",
        filename="weak-preflight.txt",
        content_type="text/plain",
        source="self-report",
        source_ref="internal://weak-preflight",
        grade=EvidenceGrade.C,
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        created_by="account-owner-1",
        metadata={
            "scope_authority_contract_id": "kjds-scope-authority-evidence-v1",
            "tenant_ref": "tenant-cn-1",
            "entity_ref": "entity-cn-1",
            "store_ref": "store-cn-1",
            "subject_actor_id": "operator-1",
            "decision": "grant",
            "reviewed_by": "compliance-reviewer-1",
        },
    )

    result = authority.preflight(
        principal=principal("admin-1"),
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type="grant",
        effective_at="2026-07-02T00:00:00Z",
        evidence_id=weak.id,
        reason="Proposed authority.",
        idempotency_key="weak-preflight",
    )

    assert result["state"] == "blocked"
    assert result["blocker_codes"] == [
        "scope_authority_evidence_not_grade_a"
    ]
    assert result["would_record_event"] is False
    with Session(engine) as session:
        assert session.query(ScopeGrantEventRow).count() == 0


def test_revoke_is_append_only_and_effective_time_deterministic():
    _, evidence, authority, source = services()
    grant(authority, source)
    revocation_review = reviewed_authority_evidence(
        authority,
        evidence,
        event_type="revoke",
        source_idempotency_key="scope-revoke-source-1",
        review_idempotency_key="scope-revoke-review-1",
    )
    authority.record(
        principal=principal("admin-2"),
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        subject_actor_id="operator-1",
        event_type="revoke",
        effective_at="2026-07-20T00:00:00Z",
        evidence_id=revocation_review.id,
        reason="Authority withdrawn by the organization owner.",
        idempotency_key="scope-revoke-1",
    )
    subject = principal("operator-1", roles=frozenset({"operator"}))

    before = authority.current(
        principal=subject,
        store_ref="store-cn-1",
        as_of=datetime(2026, 7, 19, tzinfo=UTC),
    )
    after = authority.current(
        principal=subject,
        store_ref="store-cn-1",
        as_of=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert before["status"] == "ready"
    assert after["status"] == "no_data"
    assert after["reason"] == "entity_scope_authority_missing"
    assert len(
        authority.events(
            principal=principal("admin-2"),
            store_ref="store-cn-1",
            subject_actor_id="operator-1",
        )
    ) == 2


def test_scope_grant_rejects_self_grant_cross_store_and_non_a_evidence():
    _, evidence, authority, source = services()
    weak = evidence.capture(
        content=b"self reported scope",
        filename="weak.txt",
        content_type="text/plain",
        source="self-report",
        source_ref="internal://weak-scope",
        grade=EvidenceGrade.C,
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        created_by="operator-1",
        metadata={
            "scope_authority_contract_id": "kjds-scope-authority-evidence-v1",
            "tenant_ref": "tenant-cn-1",
            "entity_ref": "entity-cn-1",
            "store_ref": "store-cn-1",
            "subject_actor_id": "operator-1",
            "decision": "grant",
            "reviewed_by": "reviewer-1",
        },
    )

    with pytest.raises(PermissionError, match="independent actor"):
        grant(
            authority,
            source,
            principal=principal("operator-1"),
        )
    with pytest.raises(PermissionError, match="not authorized"):
        grant(authority, source, store_ref="other-store")
    with pytest.raises(ValueError, match="grade A"):
        grant(authority, weak, idempotency_key="weak-grant")


def test_scope_evidence_must_match_every_frozen_scope_dimension():
    _, _, authority, source = services()

    with pytest.raises(ValueError, match="does not match"):
        grant(
            authority,
            source,
            entity_ref="different-entity",
            idempotency_key="mismatched-evidence",
        )


def test_corrupt_grant_evidence_blocks_entity_scope():
    engine, _, authority, source = services()
    grant(authority, source)
    with Session(engine) as session, session.begin():
        blob = session.get(EvidenceBlobRow, source.sha256)
        assert blob is not None
        blob.content_bytes = b"tampered authority"

    current = authority.current(
        principal=principal("operator-1", roles=frozenset({"operator"})),
        store_ref="store-cn-1",
        as_of=datetime(2026, 7, 27, tzinfo=UTC),
    )

    assert current["status"] == "blocked"
    assert current["entity_ref"] is None
    assert current["reason"] == "entity_scope_evidence_invalid"
