from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
    LineageEdgeRow,
)
from apps.control_plane.execution_authority import ListingExecutionAuthorityService
from apps.control_plane.sourcing import ListingDraft
from apps.control_plane.sql_repository import Base


class ListingStore:
    def __init__(self, draft):
        self.draft = draft

    def get_listing_draft(self, draft_id):
        if draft_id != self.draft.id:
            raise KeyError(draft_id)
        return self.draft


class ListingSourcing:
    def __init__(self, draft):
        self.store = ListingStore(draft)


def make_service():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    draft = ListingDraft(
        product_id="prd-1",
        offer_id="off-1",
        scenario_id="scn-1",
        target_platform="OZON",
        listing_data={
            "title": "Контейнер для хранения",
            "description": "Проверенное описание",
            "category_id": "123",
            "attributes": [{"id": 1, "values": [{"value": "белый"}]}],
            "images": ["evd-image-1"],
            "content_asset_ids": ["asset-1"],
        },
        requested_by="listing-requester",
    )
    service = ListingExecutionAuthorityService(
        evidence=evidence,
        sourcing=ListingSourcing(draft),
    )
    inventory = evidence.capture(
        content=b'{"identity_ref":"ozon-worker","credentials_included":false}',
        filename="ozon-execution-identity.json",
        content_type="application/json",
        source="ozon_execution_identity_inventory",
        source_ref="identity://ozon-worker/inventory/v1",
        grade=EvidenceGrade.A,
        effective_at=datetime.now(UTC).isoformat(),
        effective_until=None,
        created_by="identity-owner",
    )
    evidence.link(
        evidence_id=inventory.id,
        target_type="gate_requirement",
        target_id="OZN-001",
        relationship="satisfies",
        created_by="identity-owner",
    )
    return engine, evidence, service, draft, inventory


def review_listing(service, draft, **overrides):
    values = {
        "draft_id": draft.id,
        "accepted": True,
        "native_russian_verified": True,
        "listing_snapshot_reviewed": True,
        "terminology_accepted": True,
        "claims_grounded": True,
        "ozon_policy_checked": True,
        "rationale": "Проверены русский язык, терминология, факты и правила Ozon.",
        "reviewed_by": "native-reviewer",
    }
    values.update(overrides)
    return service.review_listing(**values)


def review_identity(service, inventory, **overrides):
    values = {
        "evidence_id": inventory.id,
        "identity_ref": "ozon-worker",
        "accepted": True,
        "inventory_complete": True,
        "credential_material_absent": True,
        "owner_verified": True,
        "caller_system_verified": True,
        "scope_minimized": True,
        "dedicated_executor": True,
        "rationale": "Verified the dedicated least-privilege Ozon execution identity inventory.",
        "reviewed_by": "identity-reviewer",
    }
    values.update(overrides)
    return service.review_execution_identity(**values)


def test_listing_review_is_independent_immutable_and_snapshot_scoped():
    _, _, service, draft, _ = make_service()

    with pytest.raises(ValueError, match="requester cannot"):
        review_listing(service, draft, reviewed_by=draft.requested_by)
    with pytest.raises(ValueError, match="all checks"):
        review_listing(service, draft, terminology_accepted=False)

    first = review_listing(service, draft)
    retry = review_listing(service, draft)
    assert first["idempotent"] is False
    assert retry["idempotent"] is True
    assert retry["review"].id == first["review"].id
    assert service.require_listing_review(draft)["status"] == "accepted"

    with pytest.raises(ValueError, match="immutable"):
        review_listing(service, draft, accepted=False, rationale="Отклонено.")

    draft.listing_data["title"] = "Измененный контейнер"
    assert service.listing_status(draft)["status"] == "pending"
    with pytest.raises(ValueError, match="accepted Russian native review"):
        service.require_listing_review(draft)


def test_listing_rejection_dominates_and_missing_lineage_fails_closed():
    engine, _, service, draft, _ = make_service()
    accepted = review_listing(service, draft)
    review_listing(
        service,
        draft,
        accepted=False,
        rationale="Описание требует исправления.",
        reviewed_by="native-reviewer-2",
    )
    assert service.listing_status(draft)["status"] == "rejected"

    with Session(engine) as session, session.begin():
        session.query(LineageEdgeRow).filter(
            LineageEdgeRow.from_id == accepted["review"].id,
            LineageEdgeRow.relationship == service.listing_relationship,
        ).delete()
    draft.listing_data["title"] = "Контейнер для хранения"
    assert accepted["review"].id not in service.listing_status(draft)["review_ids"]


def test_execution_identity_requires_grade_a_gate_evidence_and_independent_review():
    _, evidence, service, _, inventory = make_service()

    with pytest.raises(ValueError, match="cannot review their own"):
        review_identity(service, inventory, reviewed_by=inventory.created_by)
    with pytest.raises(ValueError, match="all checks"):
        review_identity(service, inventory, scope_minimized=False)

    unlinked = evidence.capture(
        content=b'{"identity_ref":"other-worker"}',
        filename="other-worker.json",
        content_type="application/json",
        source="ozon_execution_identity_inventory",
        source_ref="identity://other-worker/inventory/v1",
        grade=EvidenceGrade.A,
        effective_at=datetime.now(UTC).isoformat(),
        effective_until=None,
        created_by="other-owner",
    )
    with pytest.raises(ValueError, match="must satisfy OZN-001"):
        review_identity(
            service,
            unlinked,
            identity_ref="other-worker",
            reviewed_by="other-reviewer",
        )

    result = review_identity(service, inventory)
    retry = review_identity(service, inventory)
    assert result["idempotent"] is False
    assert retry["idempotent"] is True
    assert retry["review"].id == result["review"].id
    assert service.require_execution_identity("ozon-worker")["status"] == "accepted"

    with pytest.raises(ValueError, match="immutable"):
        review_identity(service, inventory, accepted=False, rationale="Rejected.")


def test_execution_identity_rejection_expiry_and_damaged_evidence_fail_closed():
    engine, _, service, _, inventory = make_service()
    accepted = review_identity(service, inventory)
    review_identity(
        service,
        inventory,
        accepted=False,
        rationale="The scope is broader than the approved execution role.",
        reviewed_by="identity-reviewer-2",
    )
    assert service.identity_status("ozon-worker")["status"] == "rejected"

    with Session(engine) as session, session.begin():
        session.query(EvidenceRecordRow).filter(
            EvidenceRecordRow.id == accepted["review"].id
        ).update({EvidenceRecordRow.effective_until: datetime.now(UTC) - timedelta(seconds=1)})
    status = service.identity_status("ozon-worker")
    assert accepted["review"].id not in status["review_ids"]

    with Session(engine) as session, session.begin():
        inventory_row = session.get(EvidenceRecordRow, inventory.id)
        blob = session.get(EvidenceBlobRow, inventory_row.blob_sha256)
        blob.content_bytes = b"tampered inventory"
    assert service.identity_status("ozon-worker")["status"] == "pending"
