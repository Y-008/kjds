import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile

from apps.control_plane.api import (
    CandidateEvidenceAuthorityReviewInput,
    DemandReportReviewInput,
    LineageLinkInput,
    OzonFinanceReportReviewInput,
    capture_evidence,
    link_evidence,
    review_candidate_evidence_authority,
    review_demand_report,
    review_finance_report,
)
from apps.control_plane.evidence import EvidenceGrade
from apps.control_plane.security import Principal


def operator():
    return Principal(actor_id="operator-1", roles=frozenset({"operator"}))


@pytest.mark.parametrize(
    "source",
    ["candidate_evidence_authority_review", "gate_requirement_review", "ozon_finance_report_review"],
)
def test_generic_capture_cannot_forge_reserved_review_source(source):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            capture_evidence(
                file=None,
                source=source,
                source_ref="gate://SKU-000/review/forged",
                grade=EvidenceGrade.A,
                effective_at="2026-07-19T00:00:00Z",
                principal=operator(),
                effective_until=None,
                metadata_json="{}",
            )
        )
    assert exc.value.status_code == 422


def test_generic_capture_cannot_forge_research_signal_role():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            capture_evidence(
                file=UploadFile(filename="forged.csv", file=io.BytesIO(b"forged")),
                source="third_party_tool",
                source_ref="provider://forged",
                grade=EvidenceGrade.C,
                effective_at="2026-07-20T00:00:00Z",
                principal=operator(),
                effective_until=None,
                metadata_json='{"evidence_role":"research_signal"}',
            )
        )
    assert exc.value.status_code == 422


def test_generic_lineage_cannot_forge_gate_or_review_relationships():
    with pytest.raises(HTTPException) as gate_exc:
        link_evidence(
            "evd_forged",
            LineageLinkInput(
                target_type="gate_requirement",
                target_id="SKU-000",
                relationship="source_report",
            ),
            operator(),
        )
    assert gate_exc.value.status_code == 422

    with pytest.raises(HTTPException) as review_exc:
        link_evidence(
            "evd_forged",
            LineageLinkInput(
                target_type="evidence",
                target_id="evd_report",
                relationship="reviews",
            ),
            operator(),
        )
    assert review_exc.value.status_code == 422

    with pytest.raises(HTTPException) as authority_exc:
        link_evidence(
            "evd_forged",
            LineageLinkInput(
                target_type="evidence",
                target_id="evd_candidate",
                relationship="candidate_authority_review",
            ),
            operator(),
        )
    assert authority_exc.value.status_code == 422

    with pytest.raises(HTTPException) as research_exc:
        link_evidence(
            "evd_forged",
            LineageLinkInput(
                target_type="candidate_research",
                target_id="candidate://forged",
                relationship="research_signal",
            ),
            operator(),
        )
    assert research_exc.value.status_code == 422


def test_operator_cannot_use_demand_report_review_endpoint():
    with pytest.raises(HTTPException) as exc:
        review_demand_report(
            DemandReportReviewInput(
                report_evidence_id="evd_report",
                accepted=True,
                rationale="forged acceptance",
            ),
            operator(),
        )
    assert exc.value.status_code == 403


def test_operator_cannot_use_finance_report_review_endpoint():
    with pytest.raises(HTTPException) as exc:
        review_finance_report(
            "imp_forged",
            OzonFinanceReportReviewInput(
                accepted=True,
                authentic_account_export=True,
                period_matches=True,
                not_public_sample=True,
                complete_export=True,
                rationale="forged acceptance",
            ),
            operator(),
        )
    assert exc.value.status_code == 403


def test_operator_cannot_use_candidate_authority_review_endpoint():
    with pytest.raises(HTTPException) as exc:
        review_candidate_evidence_authority(
            "evd_forged",
            CandidateEvidenceAuthorityReviewInput(
                metric="demand_signal",
                approved_grade=EvidenceGrade.B,
                accepted=True,
                authentic_original=True,
                source_scope_matches=True,
                authority_basis_verified=True,
                rationale="forged acceptance",
            ),
            operator(),
        )
    assert exc.value.status_code == 403
