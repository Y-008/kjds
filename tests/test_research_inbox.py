import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.research_inbox import ResearchInboxService
from apps.control_plane.sql_repository import Base


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    return evidence, ResearchInboxService(evidence=evidence)


def capture(service, **overrides):
    values = {
        "content": b"provider export row",
        "filename": "signal.csv",
        "content_type": "text/csv",
        "provider": "Seerfar",
        "provider_record_id": "seerfar://export/row-1",
        "source_url": "https://www.seerfar.cn/features/",
        "observed_at": "2026-07-20T00:00:00Z",
        "declared_grade": EvidenceGrade.C,
        "license_status": "requires_review",
        "raw_fields": {"keyword": "storage box", "search_index": 81.5},
        "candidate_refs": ["candidate://storage-box-v1"],
        "created_by": "operator-1",
    }
    values.update(overrides)
    return service.capture(**values)


def test_signal_is_append_only_deduplicated_and_can_link_multiple_candidates():
    evidence, service = make_service()
    first = capture(service)
    retry = capture(service, candidate_refs=["candidate://storage-box-v1", "candidate://storage-box-v2"])

    assert retry["evidence"]["id"] == first["evidence"]["id"]
    assert retry["duplicate"] is True
    assert retry["candidate_refs"] == ["candidate://storage-box-v1", "candidate://storage-box-v2"]
    assert retry["integrity_valid"] is True
    assert retry["automatic_listing"] is False
    assert evidence.get(first["evidence"]["id"]).metadata["review_status"] == "pending_authority_review"

    changed = capture(service, content=b"new provider export row")
    assert changed["evidence"]["id"] != first["evidence"]["id"]

    later_retry = capture(
        service,
        observed_at="2026-07-21T00:00:00Z",
        candidate_refs=["candidate://storage-box-v1"],
    )
    assert later_retry["evidence"]["id"] == first["evidence"]["id"]
    assert later_retry["duplicate"] is True


def test_candidate_filter_returns_only_linked_research_signals():
    _, service = make_service()
    one = capture(service)
    capture(
        service,
        content=b"another signal",
        provider_record_id="seerfar://export/row-2",
        candidate_refs=["candidate://other-v1"],
    )

    rows = service.list(candidate_ref="candidate://storage-box-v1")
    assert [row["evidence"]["id"] for row in rows] == [one["evidence"]["id"]]
    assert rows[0]["decision_use"] == "auxiliary_only_pending_independent_authority_review"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"raw_fields": {"api_key": "secret"}}, "Sensitive or invalid"),
        ({"source_url": "https://example.com/export?token=secret"}, "credential query"),
        ({"license_status": "unknown"}, "license_status"),
        ({"candidate_refs": ["bad candidate ref"]}, "Candidate reference"),
    ],
)
def test_signal_intake_rejects_sensitive_or_unbounded_metadata(overrides, message):
    _, service = make_service()
    with pytest.raises(ValueError, match=message):
        capture(service, **overrides)
