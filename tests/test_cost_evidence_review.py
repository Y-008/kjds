import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.cost_evidence_review import (
    ACTUAL_COST_AUTHORITIES,
    ACTUAL_COST_AUTHORITY_LABELS,
    CostEvidenceAuthorityService,
)
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    service = CostEvidenceAuthorityService(evidence=evidence)
    original = evidence.capture(
        content=b"supplier invoice and payment",
        filename="supplier-invoice.pdf",
        content_type="application/pdf",
        source="supplier_invoice",
        source_ref="controlled://supplier/invoice/100",
        grade=EvidenceGrade.A,
        effective_at="2026-07-20T00:00:00Z",
        effective_until=None,
        created_by="operator-1",
    )
    return evidence, service, original


def accept(service, original, **overrides):
    values = {
        "evidence_id": original.id,
        "cost_type": "product_cost",
        "authority_id": "supplier_invoice_payment",
        "accepted": True,
        "authentic_original": True,
        "cost_scope_matches": True,
        "charging_party_matches": True,
        "amount_currency_period_matches": True,
        "rationale": "已核对发票、付款、计费主体、金额、币种和期间。",
        "reviewed_by": "reviewer-1",
    }
    values.update(overrides)
    return service.review(**values)


def test_independent_review_proves_actual_cost_without_mutating_original():
    evidence, service, original = make_service()
    result = accept(service, original)

    assert result["idempotent"] is False
    assert evidence.get(original.id).source == "supplier_invoice"
    assert service.require_actual(original.id, "product_cost")["status"] == "accepted"


def test_actual_cost_review_fails_closed_on_self_review_scope_and_checks():
    _, service, original = make_service()
    with pytest.raises(ValueError, match="cannot review their own"):
        accept(service, original, reviewed_by="operator-1")
    with pytest.raises(ValueError, match="all checks"):
        accept(service, original, amount_currency_period_matches=False)
    with pytest.raises(ValueError, match="not allowed"):
        accept(service, original, authority_id="ozon_transaction_settlement")


def test_review_is_cost_scoped_immutable_and_idempotent():
    _, service, original = make_service()
    first = accept(service, original)
    retry = accept(service, original)
    assert retry["idempotent"] is True
    assert retry["review"].id == first["review"].id
    with pytest.raises(ValueError, match="immutable"):
        accept(service, original, accepted=False, rationale="改为拒绝。")
    with pytest.raises(ValueError, match="independent authority review"):
        service.require_actual(original.id, "domestic_logistics")


def test_any_valid_rejection_blocks_actual_cost_even_after_acceptance():
    _, service, original = make_service()
    accept(service, original)
    accept(
        service,
        original,
        accepted=False,
        rationale="付款期间无法与该成本项对应。",
        reviewed_by="reviewer-2",
    )
    assert service.status(original.id, "product_cost")["status"] == "rejected"
    with pytest.raises(ValueError, match="independent authority review"):
        service.require_actual(original.id, "product_cost")


def test_every_actual_authority_has_one_human_readable_server_label():
    authority_ids = {authority_id for values in ACTUAL_COST_AUTHORITIES.values() for authority_id in values}
    assert len(ACTUAL_COST_AUTHORITIES) == 15
    assert set(ACTUAL_COST_AUTHORITY_LABELS) == authority_ids
    assert all(label.strip() for label in ACTUAL_COST_AUTHORITY_LABELS.values())
