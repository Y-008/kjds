import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.candidate_evidence_review import CandidateEvidenceAuthorityService
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    review = CandidateEvidenceAuthorityService(
        evidence=evidence,
        allowed_metrics={"demand_signal", "compliance_redline"},
    )
    original = evidence.capture(
        content=b"original candidate research",
        filename="candidate.csv",
        content_type="text/csv",
        source="candidate_research",
        source_ref="controlled://candidate/original",
        grade=EvidenceGrade.C,
        effective_at="2026-07-19T00:00:00Z",
        effective_until=None,
        created_by="operator-1",
    )
    return evidence, review, original


def accept(service, original, **overrides):
    values = {
        "evidence_id": original.id,
        "metric": "demand_signal",
        "approved_grade": EvidenceGrade.B,
        "accepted": True,
        "authentic_original": True,
        "source_scope_matches": True,
        "authority_basis_verified": True,
        "rationale": "已核对原件、来源主体和指标范围。",
        "reviewed_by": "reviewer-1",
    }
    values.update(overrides)
    return service.review(**values)


def test_independent_review_can_approve_effective_grade_without_mutating_original():
    evidence, service, original = make_service()
    result = accept(service, original)

    assert result["idempotent"] is False
    assert evidence.get(original.id).grade == EvidenceGrade.C
    assert service.require_approved_grade(original.id, "demand_signal") == EvidenceGrade.B
    assert service.status(original.id, "demand_signal")["status"] == "accepted"


def test_uploader_cannot_review_and_acceptance_requires_all_checks():
    _, service, original = make_service()
    with pytest.raises(ValueError, match="cannot review their own"):
        accept(service, original, reviewed_by="operator-1")
    with pytest.raises(ValueError, match="all checks"):
        accept(service, original, authentic_original=False)


def test_review_is_metric_scoped_immutable_and_idempotent():
    _, service, original = make_service()
    first = accept(service, original)
    retry = accept(service, original)
    assert retry["idempotent"] is True
    assert retry["review"].id == first["review"].id
    with pytest.raises(ValueError, match="immutable"):
        accept(service, original, accepted=False, rationale="改为拒绝。")
    with pytest.raises(ValueError, match="independent authority review"):
        service.require_approved_grade(original.id, "compliance_redline")


def test_any_valid_rejection_fails_closed_even_after_acceptance():
    _, service, original = make_service()
    accept(service, original)
    accept(
        service,
        original,
        accepted=False,
        rationale="无法证明来源主体与声明一致。",
        reviewed_by="reviewer-2",
    )
    assert service.status(original.id, "demand_signal")["status"] == "rejected"
    with pytest.raises(ValueError, match="independent authority review"):
        service.require_approved_grade(original.id, "demand_signal")
