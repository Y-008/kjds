from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.evidence_scope import ScopedEvidenceAuthority
from apps.control_plane.evidence_scope_binding import (
    EvidenceScopeBindingService,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

NOW = datetime.now(UTC)


def principal(actor: str, *roles: str) -> Principal:
    return Principal(
        actor_id=actor,
        roles=frozenset(roles),
        tenant_ref="default",
        store_refs=frozenset({"ozon-primary"}),
    )


def ready_scope() -> dict:
    return {
        "status": "ready",
        "entity_ref": "kjds",
        "authority_sha256": "a" * 64,
    }


def services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    return (
        engine,
        evidence,
        EvidenceScopeBindingService(
            evidence=evidence,
            scoped_evidence=ScopedEvidenceAuthority(evidence=evidence),
        ),
    )


def target_evidence(evidence: EvidenceService) -> object:
    return evidence.capture(
        content=b'{"marketplace":"1688","offer_id":"1045914391146"}',
        filename="1688-offer.json",
        content_type="application/json",
        source="test_observation_source",
        source_ref="test-observation-1",
        grade=EvidenceGrade.C,
        effective_at=NOW.isoformat(),
        effective_until=None,
        created_by="capture-worker",
        metadata={
            "marketplace": "1688",
            "observed_at": NOW.isoformat(),
        },
    )


def test_full_binding_flow_projects_target_scope_ready():
    _, evidence, service = services()
    target = target_evidence(evidence)
    submitted = service.submit_binding(
        principal=principal("operator-1", "operator"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        target_evidence_id=target.id,
        idempotency_key="bind-1",
        effective_at=NOW.isoformat(),
        as_of=NOW,
    )
    reviewed = service.review_binding(
        principal=principal("reviewer-1", "reviewer"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        submission_evidence_id=submitted["submission_evidence_id"],
        accepted=True,
        rationale="Verified the immutable observation belongs to the exact store scope.",
        effective_at=NOW.isoformat(),
        idempotency_key="review-1",
        as_of=NOW,
    )
    recorded = service.record_binding(
        principal=principal("compliance-1", "compliance"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        submission_evidence_id=submitted["submission_evidence_id"],
        review_evidence_id=reviewed["review_evidence_id"],
        effective_at=NOW.isoformat(),
        idempotency_key="record-1",
        as_of=NOW,
    )
    assert recorded["binding_recorded"] is True
    projection = service.scoped_evidence.project_targets(
        evidence_ids=[target.id],
        principal=principal("operator-1", "operator"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        as_of=NOW,
    )
    record = next(
        item
        for item in projection["records"]
        if item["evidence_id"] == target.id
    )
    assert record["scope_binding"]["status"] == "ready"

    # Replay is idempotent.
    replay = service.record_binding(
        principal=principal("compliance-1", "compliance"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        submission_evidence_id=submitted["submission_evidence_id"],
        review_evidence_id=reviewed["review_evidence_id"],
        effective_at=NOW.isoformat(),
        idempotency_key="record-1",
        as_of=NOW,
    )
    assert replay["binding_evidence_id"] == recorded["binding_evidence_id"]


def test_binding_requires_independent_roles_and_rejects_already_bound():
    _, evidence, service = services()
    target = target_evidence(evidence)
    with pytest.raises(PermissionError, match="independent"):
        service.submit_binding(
            principal=principal(target.created_by, "operator"),
            entity_scope=ready_scope(),
            store_ref="ozon-primary",
            target_evidence_id=target.id,
            idempotency_key="bind-self",
            effective_at=NOW.isoformat(),
            as_of=NOW,
        )
    submitted = service.submit_binding(
        principal=principal("operator-1", "operator"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        target_evidence_id=target.id,
        idempotency_key="bind-2",
        effective_at=NOW.isoformat(),
        as_of=NOW,
    )
    with pytest.raises(PermissionError, match="independent"):
        service.review_binding(
            principal=principal(target.created_by, "reviewer"),
            entity_scope=ready_scope(),
            store_ref="ozon-primary",
            submission_evidence_id=submitted["submission_evidence_id"],
            accepted=True,
            rationale="self review must fail",
            effective_at=NOW.isoformat(),
            idempotency_key="review-self",
            as_of=NOW,
        )
    reviewed = service.review_binding(
        principal=principal("reviewer-1", "reviewer"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        submission_evidence_id=submitted["submission_evidence_id"],
        accepted=True,
        rationale="independent review",
        effective_at=NOW.isoformat(),
        idempotency_key="review-2",
        as_of=NOW,
    )
    service.record_binding(
        principal=principal("compliance-1", "compliance"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        submission_evidence_id=submitted["submission_evidence_id"],
        review_evidence_id=reviewed["review_evidence_id"],
        effective_at=NOW.isoformat(),
        idempotency_key="record-2",
        as_of=NOW,
    )
    second = service.submit_binding(
        principal=principal("operator-2", "operator"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        target_evidence_id=target.id,
        idempotency_key="bind-3",
        effective_at=NOW.isoformat(),
        as_of=NOW,
    )
    second_review = service.review_binding(
        principal=principal("reviewer-2", "reviewer"),
        entity_scope=ready_scope(),
        store_ref="ozon-primary",
        submission_evidence_id=second["submission_evidence_id"],
        accepted=True,
        rationale="independent second review",
        effective_at=NOW.isoformat(),
        idempotency_key="review-3",
        as_of=NOW,
    )
    with pytest.raises(ValueError, match="already has an exact-scope binding"):
        service.record_binding(
            principal=principal("compliance-2", "compliance"),
            entity_scope=ready_scope(),
            store_ref="ozon-primary",
            submission_evidence_id=second["submission_evidence_id"],
            review_evidence_id=second_review["review_evidence_id"],
            effective_at=NOW.isoformat(),
            idempotency_key="record-3",
            as_of=NOW,
        )
