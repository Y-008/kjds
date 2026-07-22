import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.demand_report_gate import DemandReportGateService
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    return evidence, DemandReportGateService(evidence=evidence)


def capture_report(
    service,
    *,
    created_by="operator-1",
    source_system="ozon_data",
    content=b"date,views,orders\n2026-07-01,100,5\n",
):
    return service.capture_report(
        content=content,
        filename="ozon-data.csv",
        content_type="text/csv",
        effective_at="2026-07-01T00:00:00+03:00",
        report_window_days=28,
        created_by=created_by,
        source_system=source_system,
    )["evidence"]


def test_upload_alone_remains_pending_until_independent_acceptance():
    _, service = make_service()
    report = capture_report(service)

    pending = service.status()
    assert pending["ready"] is False
    assert pending["pending_report_ids"] == [report.id]

    review = service.review(
        report_evidence_id=report.id,
        accepted=True,
        rationale="已核对 Ozon Data 导出页、日期范围和字段。",
        reviewed_by="approver-1",
    )
    accepted = service.status()
    assert accepted["ready"] is True
    assert accepted["accepted_report_ids"] == [report.id]
    assert accepted["readiness"]["real_execution"]["evidence_ids"] == sorted(
        [report.id, review["review"].id]
    )
    service.require_accepted(report.id)


def test_candidate_gate_rejects_pending_or_rejected_report():
    _, service = make_service()
    report = capture_report(service)
    with pytest.raises(ValueError, match="not currently accepted"):
        service.require_accepted(report.id)

    service.review(
        report_evidence_id=report.id,
        accepted=False,
        rationale="无法复核真实导出范围。",
        reviewed_by="approver-1",
    )
    with pytest.raises(ValueError, match="not currently accepted"):
        service.require_accepted(report.id)


def test_uploader_cannot_review_own_report():
    _, service = make_service()
    report = capture_report(service)

    with pytest.raises(ValueError, match="cannot review their own"):
        service.review(
            report_evidence_id=report.id,
            accepted=True,
            rationale="self approval",
            reviewed_by="operator-1",
        )


def test_rejection_blocks_report_even_if_another_reviewer_accepts_it():
    _, service = make_service()
    report = capture_report(service)
    service.review(
        report_evidence_id=report.id,
        accepted=True,
        rationale="字段范围看起来正确。",
        reviewed_by="approver-1",
    )
    service.review(
        report_evidence_id=report.id,
        accepted=False,
        rationale="无法在 Ozon 后台复现该导出范围。",
        reviewed_by="approver-2",
    )

    status = service.status()
    assert status["ready"] is False
    assert status["rejected_report_ids"] == [report.id]


def test_review_is_idempotent_but_cannot_be_overwritten():
    _, service = make_service()
    report = capture_report(service)
    first = service.review(
        report_evidence_id=report.id,
        accepted=True,
        rationale="独立核对通过。",
        reviewed_by="approver-1",
    )
    retry = service.review(
        report_evidence_id=report.id,
        accepted=True,
        rationale="独立核对通过。",
        reviewed_by="approver-1",
    )
    assert retry["idempotent"] is True
    assert retry["review"].id == first["review"].id

    with pytest.raises(ValueError, match="immutable"):
        service.review(
            report_evidence_id=report.id,
            accepted=False,
            rationale="change decision",
            reviewed_by="approver-1",
        )


def test_generic_evidence_cannot_masquerade_as_source_report():
    evidence, service = make_service()
    generic = evidence.capture(
        content=b"public sample",
        filename="sample.csv",
        content_type="text/csv",
        source="gate_requirement",
        source_ref="public://sample",
        grade=EvidenceGrade.A,
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        created_by="operator-1",
        metadata={
            "requirement_id": "SKU-000",
            "evidence_role": "source_report",
            "source_system": "public_sample",
            "report_window_days": 28,
        },
    )
    evidence.link(
        evidence_id=generic.id,
        target_type="gate_requirement",
        target_id="SKU-000",
        relationship="source_report",
        created_by="operator-1",
    )

    status = service.status()
    assert status["ready"] is False
    assert status["invalid_report_ids"] == [generic.id]


def test_partial_review_lineage_fails_closed():
    evidence, service = make_service()
    report = capture_report(service)
    review = evidence.capture(
        content=b'{"decision":"accepted"}',
        filename="partial-review.json",
        content_type="application/json",
        source="gate_requirement_review",
        source_ref=f"gate://SKU-000/review/{report.id}/approver-1",
        grade=EvidenceGrade.A,
        effective_at="2026-07-19T00:00:00Z",
        effective_until=None,
        created_by="approver-1",
        metadata={
            "requirement_id": "SKU-000",
            "evidence_role": "review_attestation",
            "report_evidence_id": report.id,
            "report_sha256": report.sha256,
            "submitted_by": report.created_by,
            "reviewed_by": "approver-1",
            "decision": "accepted",
            "rationale": "partial transaction",
        },
    )
    evidence.link(
        evidence_id=review.id,
        target_type="evidence",
        target_id=report.id,
        relationship="reviews",
        created_by="approver-1",
    )

    status = service.status()
    assert status["ready"] is False
    assert status["pending_report_ids"] == [report.id]


def test_fixed_test_data_unlocks_research_but_not_real_execution():
    _, service = make_service()
    report = capture_report(service, source_system="fixed_test_data")
    service.review(
        report_evidence_id=report.id,
        accepted=True,
        rationale="固定测试数据仅用于研究闭环演练。",
        reviewed_by="approver-1",
    )

    status = service.status()
    assert status["research_ready"] is True
    assert status["real_execution_ready"] is False
    assert status["ready"] is False
    service.require_accepted(report.id, scope="research")
    with pytest.raises(ValueError, match="not eligible for real_execution"):
        service.require_accepted(report.id, scope="real_execution")


def test_seller_analytics_unlocks_research_but_not_real_execution():
    _, service = make_service()
    report = capture_report(
        service,
        source_system="ozon_seller_analytics",
        content=b"seller analytics 28-day screenshot",
    )
    service.review(
        report_evidence_id=report.id,
        accepted=True,
        rationale="已核对 Seller Analytics 店铺级 28 天页面，仅用于研究。",
        reviewed_by="approver-1",
    )

    status = service.status()
    assert status["research_ready"] is True
    assert status["real_execution_ready"] is False
    assert report.metadata["eligible_scopes"] == ["research"]
    service.require_accepted(report.id, scope="research")
    with pytest.raises(ValueError, match="not eligible for real_execution"):
        service.require_accepted(report.id, scope="real_execution")


def test_two_independent_official_sources_unlock_real_execution_scope():
    _, service = make_service()
    category = capture_report(
        service,
        source_system="ozon_category_analytics",
        content=b"category analytics export",
    )
    trends = capture_report(
        service,
        source_system="ozon_trends",
        content=b"trend analytics export",
    )
    reviews = []
    for report in (category, trends):
        reviews.append(
            service.review(
                report_evidence_id=report.id,
                accepted=True,
                rationale="已核对官方入口、窗口和原始内容。",
                reviewed_by="approver-1",
            )
        )

    status = service.status()
    assert status["research_ready"] is True
    assert status["real_execution_ready"] is True
    assert status["readiness"]["real_execution"][
        "independent_official_source_systems"
    ] == ["ozon_category_analytics", "ozon_trends"]
    assert status["readiness"]["real_execution"]["evidence_ids"] == sorted(
        [category.id, trends.id, *(item["review"].id for item in reviews)]
    )
    service.require_accepted(category.id, scope="real_execution")
