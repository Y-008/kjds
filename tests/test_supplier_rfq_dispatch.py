import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base
from apps.control_plane.supplier_rfq_dispatch import (
    DISPATCH_SOURCE,
    SupplierRfqDispatchWorkspace,
)

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
PRODUCT_ID = "prd_ozon_real"
RFQ_MESSAGE = "冻结询价正文：500kg / 7.6m / 三控 / 220V。"


class RfqPackages:
    def __init__(
        self,
        evidence,
        *,
        offer_id="offer-1",
        product_id=PRODUCT_ID,
    ):
        package = {
            "contract_version": "supplier-rfq-package-v1",
            "package_hash": "a" * 64,
            "product": {
                "id": product_id,
                "sku": "ozon:ozon-primary:offer-1",
                "name": "Portable hoist",
            },
            "listing": {
                "marketplace": "ozon",
                "store_ref": "ozon-primary",
                "offer_id": offer_id,
                "marketplace_sku": "321" if offer_id else None,
            },
            "buyer_requirement": {
                "response_due_at": "2026-07-30T10:00:00+00:00",
            },
            "message_text": RFQ_MESSAGE,
        }
        self.record = evidence.capture(
            content=json.dumps(package).encode(),
            filename="rfq.json",
            content_type="application/json",
            source="supplier_rfq_package",
            source_ref=f"supplier-rfq://{product_id}/rfq-1",
            grade=EvidenceGrade.C,
            effective_at="2026-07-26T08:00:00+00:00",
            effective_until=None,
            created_by="operator-1",
            metadata={"product_id": product_id},
        )
        self.package = package

    def get(self, evidence_id):
        if evidence_id != self.record.id:
            raise KeyError(evidence_id)
        return {
            "evidence": self.record,
            "package": self.package,
        }


def make_workspace():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    rfqs = RfqPackages(evidence)
    workspace = SupplierRfqDispatchWorkspace(
        rfq_packages=rfqs,
        evidence=evidence,
        clock=lambda: NOW,
    )
    return workspace, evidence, rfqs


def capture_values(rfqs, **overrides):
    values = {
        "rfq_package_evidence_id": rfqs.record.id,
        "supplier_ref": "河北测试起重机械有限公司",
        "supplier_platform": "1688",
        "supplier_locator": "https://shop.1688.com/page/index.html",
        "conversation_ref": "1688-chat-20260726-001",
        "sent_at": "2026-07-26T10:00:00+00:00",
        "sent_message_text": RFQ_MESSAGE,
        "idempotency_key": "supplier-1-20260726-v1",
        "content": b"unaltered 1688 chat export",
        "filename": "1688-chat.png",
        "content_type": "image/png",
        "confirmed": True,
        "created_by": "operator-1",
    }
    values.update(overrides)
    return values


def accepted_dispatch(workspace, rfqs):
    captured = workspace.capture(**capture_values(rfqs))
    reviewed = workspace.review(
        evidence_id=captured["evidence"].id,
        accepted=True,
        authentic_platform_proof=True,
        supplier_identity_matches=True,
        frozen_message_matches=True,
        timestamp_and_conversation_match=True,
        rationale="Matched the original 1688 conversation and frozen RFQ.",
        reviewed_by="reviewer-1",
    )
    return reviewed


def test_dispatch_freezes_platform_proof_without_claiming_reply_or_quote():
    workspace, evidence, rfqs = make_workspace()

    first = workspace.capture(**capture_values(rfqs))
    replay = workspace.capture(**capture_values(rfqs))

    assert first["status"] == "pending"
    assert first["evidence"].source == DISPATCH_SOURCE
    assert first["evidence"].grade == EvidenceGrade.B
    assert replay["idempotent"] is True
    assert replay["evidence"].id == first["evidence"].id
    assert first["dispatch"]["rfq"]["evidence_id"] == rfqs.record.id
    assert (
        first["dispatch"]["supplier"]["supplier_ref"]
        == "河北测试起重机械有限公司"
    )
    assert first["dispatch"]["sent_message_sha256"]
    assert first["dispatch"]["proof"]["sha256"] == first["evidence"].sha256
    assert first["delivery_confirmed"] is False
    assert first["supplier_replied"] is False
    assert first["counts_as_supplier_quote"] is False
    assert first["automatic_supplier_contact"] is False
    assert evidence.target_evidence_ids(
        target_type="evidence",
        target_id=first["evidence"].id,
        relationship="rfq_dispatch_context_for",
    ) == [rfqs.record.id]
    assert evidence.target_evidence_ids(
        target_type="product",
        target_id=PRODUCT_ID,
        relationship="supplier_outreach_for",
    ) == [first["evidence"].id]


def test_dispatch_accepts_prelisting_rfq_without_inventing_ozon_offer():
    workspace, _, _ = make_workspace()
    rfqs = RfqPackages(
        workspace.evidence,
        offer_id=None,
        product_id="prd-prelisting",
    )
    workspace.rfq_packages = rfqs

    result = workspace.capture(**capture_values(rfqs))

    assert result["dispatch"]["rfq"]["offer_id"] is None
    assert result["counts_as_supplier_quote"] is False
    assert result["automatic_supplier_contact"] is False


def test_dispatch_idempotency_rejects_changed_fact_or_proof():
    workspace, _, rfqs = make_workspace()
    workspace.capture(**capture_values(rfqs))

    with pytest.raises(ValueError, match="idempotency conflict"):
        workspace.capture(
            **capture_values(
                rfqs,
                conversation_ref="different-conversation",
            )
        )
    with pytest.raises(ValueError, match="idempotency conflict"):
        workspace.capture(
            **capture_values(
                rfqs,
                content=b"different proof",
            )
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"sent_message_text": "edited RFQ"},
            "differs from the frozen RFQ",
        ),
        (
            {"supplier_locator": "https://example.com/forged"},
            "must use 1688.com",
        ),
        (
            {"sent_at": "2026-07-26T13:00:00+00:00"},
            "cannot be in the future",
        ),
        (
            {"sent_at": "2026-07-31T10:00:00+00:00"},
            "cannot be in the future",
        ),
        (
            {"sent_at": "2026-07-26T07:00:00+00:00"},
            "cannot predate",
        ),
    ],
)
def test_dispatch_fails_closed_on_invalid_send_claim(overrides, message):
    workspace, _, rfqs = make_workspace()

    with pytest.raises(ValueError, match=message):
        workspace.capture(**capture_values(rfqs, **overrides))


def test_dispatch_rejects_send_after_deadline_even_when_clock_is_later():
    workspace, _, rfqs = make_workspace()
    workspace.clock = lambda: datetime(2026, 8, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="after the RFQ response deadline"):
        workspace.capture(
            **capture_values(
                rfqs,
                sent_at="2026-07-31T10:00:00+00:00",
            )
        )


def test_dispatch_requires_independent_complete_review():
    workspace, _, rfqs = make_workspace()
    captured = workspace.capture(**capture_values(rfqs))
    review_values = {
        "evidence_id": captured["evidence"].id,
        "accepted": True,
        "authentic_platform_proof": True,
        "supplier_identity_matches": True,
        "frozen_message_matches": True,
        "timestamp_and_conversation_match": True,
        "rationale": "Matched the immutable RFQ and original platform trace.",
    }

    with pytest.raises(ValueError, match="cannot review their own"):
        workspace.review(**review_values, reviewed_by="operator-1")
    with pytest.raises(ValueError, match="all checks"):
        workspace.review(
            **{
                **review_values,
                "authentic_platform_proof": False,
            },
            reviewed_by="reviewer-1",
        )

    accepted = workspace.review(
        **review_values,
        reviewed_by="reviewer-1",
    )
    replay = workspace.review(
        **review_values,
        reviewed_by="reviewer-1",
    )

    assert accepted["status"] == "accepted"
    assert accepted["review"].grade == EvidenceGrade.A
    assert replay["idempotent"] is True
    assert replay["review"].id == accepted["review"].id


def test_only_accepted_matching_dispatch_can_anchor_supplier_response():
    workspace, _, rfqs = make_workspace()
    pending = workspace.capture(**capture_values(rfqs))
    with pytest.raises(ValueError, match="independently accepted"):
        workspace.require_for_response(
            pending["evidence"].id,
            product_id=PRODUCT_ID,
            supplier_ref="河北测试起重机械有限公司",
            supplier_platform="1688",
        )

    accepted = accepted_dispatch(workspace, rfqs)
    record = workspace.require_for_response(
        accepted["evidence"].id,
        product_id=PRODUCT_ID,
        supplier_ref="河北测试起重机械有限公司",
        supplier_platform="1688",
        rfq_package_evidence_id=rfqs.record.id,
    )
    assert record.id == accepted["evidence"].id

    with pytest.raises(ValueError, match="different product"):
        workspace.require_for_response(
            record.id,
            product_id="prd_other",
            supplier_ref="河北测试起重机械有限公司",
            supplier_platform="1688",
        )
    with pytest.raises(ValueError, match="identity differs"):
        workspace.require_for_response(
            record.id,
            product_id=PRODUCT_ID,
            supplier_ref="另一家供应商",
            supplier_platform="1688",
        )
    with pytest.raises(ValueError, match="platform differs"):
        workspace.require_for_response(
            record.id,
            product_id=PRODUCT_ID,
            supplier_ref="河北测试起重机械有限公司",
            supplier_platform="alibaba",
        )
    with pytest.raises(ValueError, match="RFQ differs"):
        workspace.require_for_response(
            record.id,
            product_id=PRODUCT_ID,
            supplier_ref="河北测试起重机械有限公司",
            supplier_platform="1688",
            rfq_package_evidence_id="evd_other_rfq",
        )
