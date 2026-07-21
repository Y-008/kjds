import hashlib

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import ChargeType
from apps.control_plane.evidence import EvidenceGrade, EvidenceRecordRow, EvidenceService, LineageEdgeRow
from apps.control_plane.facts import FactPromotionService
from apps.control_plane.finance import FeeSignRule, FinanceService
from apps.control_plane.imports import OzonImportService
from apps.control_plane.ozon_finance_review import (
    AccrualAccountingClass,
    AccrualExpectedSign,
    OzonAccrualClassificationService,
    OzonFeeMappingApprovalService,
    OzonFinanceReportReviewService,
)
from apps.control_plane.sql_repository import Base


def make_finance_import():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    imports = OzonImportService(engine)
    reviews = OzonFinanceReportReviewService(engine=engine, evidence=evidence, imports=imports)
    finance = FinanceService(engine)
    mappings = OzonFeeMappingApprovalService(
        engine=engine,
        evidence=evidence,
        imports=imports,
        reviews=reviews,
        finance=finance,
    )
    facts = FactPromotionService(
        engine,
        finance_review_validator=reviews.require_accepted,
        fee_mapping_validator=mappings.require_mapped,
    )
    content = (
        b"operation_id;fee_type;amount;currency;effective_at\n"
        b"operation-2;delivery_service;100;RUB;2026-07-16T10:00:00+03:00\n"
    )
    digest = hashlib.sha256(content).hexdigest()
    source = evidence.capture(
        content=content,
        filename="transactions.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref=f"ozon-upload://sha256/{digest}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-16T10:00:00+03:00",
        effective_until=None,
        created_by="operator-1",
        metadata={
            "filename": "transactions.csv",
            "sha256": digest,
            "retention_class": "financial",
            "report_period_start": "2026-07-01",
            "report_period_end": "2026-07-31",
        },
    )
    imported = imports.import_file(filename="transactions.csv", content=content, evidence_id=source.id)
    evidence.link(
        evidence_id=source.id,
        target_type="import_job",
        target_id=imported.id,
        relationship="source_for",
        created_by="operator-1",
    )
    return evidence, reviews, mappings, facts, imported, source


def accepted_review(reviews, imported, *, reviewed_by="reviewer-1"):
    return reviews.review(
        import_id=imported.id,
        accepted=True,
        authentic_account_export=True,
        period_matches=True,
        not_public_sample=True,
        complete_export=True,
        rationale="Compared the original account export and reporting period.",
        reviewed_by=reviewed_by,
    )


def make_accrual_import(content: bytes | None = None):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    imports = OzonImportService(engine)
    reviews = OzonFinanceReportReviewService(engine=engine, evidence=evidence, imports=imports)
    classifications = OzonAccrualClassificationService(
        engine=engine,
        evidence=evidence,
        imports=imports,
        reviews=reviews,
    )
    facts = FactPromotionService(
        engine,
        finance_review_validator=reviews.require_accepted,
        accrual_classification_validator=classifications.require_classified,
    )
    finance = FinanceService(engine)
    content = content or (
        "id начисления;группа услуг;тип начисления;сумма итого, руб.;дата начисления\n"
        "accrual-1;Продажи;Продажа товара;1000;2026-07-16T10:00:00+03:00\n"
        "accrual-2;Комиссии;Вознаграждение за продажу;-150;2026-07-16T10:00:00+03:00\n"
    ).encode()
    digest = hashlib.sha256(content).hexdigest()
    source = evidence.capture(
        content=content,
        filename="Начисления.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref=f"ozon-upload://sha256/{digest}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-16T10:00:00+03:00",
        effective_until=None,
        created_by="operator-1",
        metadata={
            "filename": "Начисления.csv",
            "sha256": digest,
            "retention_class": "financial",
            "report_period_start": "2026-07-01",
            "report_period_end": "2026-07-31",
        },
    )
    imported = imports.import_file(filename="Начисления.csv", content=content, evidence_id=source.id)
    evidence.link(
        evidence_id=source.id,
        target_type="import_job",
        target_id=imported.id,
        relationship="source_for",
        created_by="operator-1",
    )
    return evidence, reviews, classifications, facts, finance, imported, source


def test_finance_import_cannot_promote_until_independently_accepted():
    _, reviews, mappings, facts, imported, _ = make_finance_import()

    with pytest.raises(ValueError, match="independent accepted"):
        facts.promote(imported.id, created_by="operator-1")

    accepted_review(reviews, imported)
    with pytest.raises(ValueError, match="approved fee mappings"):
        facts.promote(imported.id, created_by="operator-1")
    mappings.approve(
        import_id=imported.id,
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        rationale="Ozon delivery service is treated as a platform fee in the approved chart.",
        approved_by="reviewer-1",
    )
    promoted = facts.promote(imported.id, created_by="operator-1")

    assert promoted.promoted_count == 1
    assert reviews.status(imported.id)["status"] == "accepted"


def test_pending_finance_review_exposes_an_aggregate_only_verification_packet():
    _, reviews, _, _, imported, source = make_finance_import()

    status = reviews.status(imported.id)
    packet = status["review_packet"]

    assert status["status"] == "pending"
    assert packet["source"] == {
        "filename": source.filename,
        "sha256": source.sha256,
        "byte_size": source.byte_size,
        "content_type": source.content_type,
        "submitted_by": source.created_by,
        "recorded_at": source.recorded_at,
    }
    assert packet["import"]["row_count"] == 1
    assert packet["import"]["accepted_count"] == 1
    assert packet["import"]["rejected_count"] == 0
    assert packet["integrity"] == {
        "evidence_valid": True,
        "sha256_matches_import": True,
        "source_lineage_verified": True,
        "row_numbers_contiguous": True,
    }
    assert packet["aggregates"]["currency_totals"] == [
        {"currency": "RUB", "row_count": 1, "total_amount": "100"}
    ]
    assert packet["aggregates"]["accrual_pairs"] == []
    assert packet["boundaries"] == {
        "aggregate_only": True,
        "raw_rows_exposed": False,
        "automatic_acceptance": False,
        "automatic_classification": False,
        "automatic_finance_posting": False,
    }
    assert "payload_json" not in str(packet)


def test_pending_accrual_review_packet_reconciles_total_and_observed_pairs():
    _, reviews, _, _, _, imported, _ = make_accrual_import()

    packet = reviews.status(imported.id)["review_packet"]

    assert packet["aggregates"]["currency_totals"] == [
        {"currency": "RUB", "row_count": 2, "total_amount": "850"}
    ]
    assert packet["aggregates"]["earliest_effective_at"] == "2026-07-16T07:00:00+00:00"
    assert packet["aggregates"]["latest_effective_at"] == "2026-07-16T07:00:00+00:00"
    assert packet["aggregates"]["accrual_pairs"] == [
        {
            "accrual_group": "Комиссии",
            "accrual_type": "Вознаграждение за продажу",
            "row_count": 1,
            "currency_totals": [{"currency": "RUB", "total_amount": "-150"}],
        },
        {
            "accrual_group": "Продажи",
            "accrual_type": "Продажа товара",
            "row_count": 1,
            "currency_totals": [{"currency": "RUB", "total_amount": "1000"}],
        },
    ]


def test_uploader_cannot_review_and_acceptance_requires_all_checks():
    _, reviews, mappings, _, imported, _ = make_finance_import()

    with pytest.raises(ValueError, match="uploader"):
        accepted_review(reviews, imported, reviewed_by="operator-1")
    with pytest.raises(ValueError, match="all source checks"):
        reviews.review(
            import_id=imported.id,
            accepted=True,
            authentic_account_export=True,
            period_matches=True,
            not_public_sample=False,
            complete_export=True,
            rationale="The file is a public sample.",
            reviewed_by="reviewer-1",
        )
    accepted_review(reviews, imported)
    with pytest.raises(ValueError, match="uploader"):
        mappings.approve(
            import_id=imported.id,
            raw_code="delivery_service",
            canonical_type=ChargeType.PLATFORM_FEE,
            sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
            effective_from="2026-07-01T00:00:00+00:00",
            effective_until=None,
            rationale="Self approval is forbidden.",
            approved_by="operator-1",
        )
    with pytest.raises(ValueError, match="not observed"):
        mappings.approve(
            import_id=imported.id,
            raw_code="invented_fee",
            canonical_type=ChargeType.PLATFORM_FEE,
            sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
            effective_from="2026-07-01T00:00:00+00:00",
            effective_until=None,
            rationale="This code is not present.",
            approved_by="reviewer-1",
        )


def test_finance_review_requires_an_immutable_expected_period():
    evidence, reviews, _, _, imported, source = make_finance_import()
    with Session(evidence.engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, source.id)
        assert row is not None
        row.metadata_json = {key: value for key, value in row.metadata_json.items() if not key.startswith("report_period_")}

    with pytest.raises(ValueError, match="expected report period"):
        accepted_review(reviews, imported)


def test_fee_mapping_fails_closed_when_source_lineage_is_missing():
    evidence, reviews, mappings, _, imported, source = make_finance_import()
    accepted_review(reviews, imported)
    approved = mappings.approve(
        import_id=imported.id,
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        rationale="Ozon delivery service is treated as a platform fee in the approved chart.",
        approved_by="reviewer-1",
    )
    assert mappings.status(imported.id)["ready"] is True

    with Session(evidence.engine) as session, session.begin():
        session.execute(
            delete(LineageEdgeRow).where(
                LineageEdgeRow.from_id == approved["approval"].id,
                LineageEdgeRow.to_type == "evidence",
                LineageEdgeRow.to_id == source.id,
                LineageEdgeRow.relationship == "supports_fee_mapping",
            )
        )

    assert mappings.status(imported.id)["ready"] is False


def test_review_is_immutable_idempotent_and_any_rejection_blocks_promotion():
    _, reviews, _, facts, imported, _ = make_finance_import()
    first = accepted_review(reviews, imported)
    duplicate = accepted_review(reviews, imported)

    assert first["review"].id == duplicate["review"].id
    assert duplicate["idempotent"] is True
    with pytest.raises(ValueError, match="immutable"):
        reviews.review(
            import_id=imported.id,
            accepted=False,
            authentic_account_export=False,
            period_matches=False,
            not_public_sample=False,
            complete_export=False,
            rationale="Changed decision.",
            reviewed_by="reviewer-1",
        )

    reviews.review(
        import_id=imported.id,
        accepted=False,
        authentic_account_export=False,
        period_matches=True,
        not_public_sample=True,
        complete_export=True,
        rationale="Could not verify that the export came from the seller account.",
        reviewed_by="reviewer-2",
    )
    assert reviews.status(imported.id)["status"] == "rejected"
    with pytest.raises(ValueError, match="independent accepted"):
        facts.promote(imported.id, created_by="operator-1")


def test_finance_review_fails_closed_on_partial_source_lineage():
    evidence, reviews, _, _, imported, source = make_finance_import()
    other = evidence.capture(
        content=b"other source",
        filename="other.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref="ozon-upload://sha256/other",
        grade=EvidenceGrade.A,
        effective_at="2026-07-16T10:00:00+03:00",
        effective_until=None,
        created_by="operator-2",
        metadata={"sha256": "other"},
    )
    evidence.link(
        evidence_id=other.id,
        target_type="import_job",
        target_id=imported.id,
        relationship="source_for",
        created_by="operator-2",
    )

    assert source.id != other.id
    with pytest.raises(ValueError, match="missing or ambiguous"):
        accepted_review(reviews, imported)


def test_order_import_does_not_require_finance_review():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    imports = OzonImportService(engine)
    content = (
        b"order_id;sku;quantity;currency;price;effective_at\n"
        b"order-1;SKU-1;1;RUB;500;2026-07-16T10:00:00+03:00\n"
    )
    source = evidence.capture(
        content=content,
        filename="orders.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref="ozon-upload://orders",
        grade=EvidenceGrade.A,
        effective_at="2026-07-16T10:00:00+03:00",
        effective_until=None,
        created_by="operator-1",
    )
    imported = imports.import_file(filename="orders.csv", content=content, evidence_id=source.id)

    assert FactPromotionService(engine).promote(imported.id, created_by="operator-1").promoted_count == 1


def test_accrual_requires_observed_control_classifications_and_never_posts_finance_entries():
    _, reviews, classifications, facts, finance, imported, _ = make_accrual_import()
    accepted_review(reviews, imported)

    with pytest.raises(ValueError, match="approved control classifications"):
        facts.promote(imported.id, created_by="operator-1")
    with pytest.raises(ValueError, match="not observed"):
        classifications.approve(
            import_id=imported.id,
            accrual_group="Invented",
            accrual_type="Invented",
            accounting_class=AccrualAccountingClass.OTHER_REVIEW,
            expected_sign=AccrualExpectedSign.EITHER,
            effective_from="2026-07-01T00:00:00+00:00",
            effective_until=None,
            rationale="Must not classify a pair absent from the accepted export.",
            approved_by="reviewer-1",
        )

    sales = classifications.approve(
        import_id=imported.id,
        accrual_group="Продажи",
        accrual_type="Продажа товара",
        accounting_class=AccrualAccountingClass.SALES,
        expected_sign=AccrualExpectedSign.POSITIVE,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        rationale="Platform sales control row; order facts remain the revenue system of record.",
        approved_by="reviewer-1",
    )
    duplicate = classifications.approve(
        import_id=imported.id,
        accrual_group="Продажи",
        accrual_type="Продажа товара",
        accounting_class=AccrualAccountingClass.SALES,
        expected_sign=AccrualExpectedSign.POSITIVE,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        rationale="Platform sales control row; order facts remain the revenue system of record.",
        approved_by="reviewer-1",
    )
    assert duplicate["approval"].id == sales["approval"].id
    assert duplicate["idempotent"] is True
    assert classifications.status(imported.id)["ready"] is False

    classifications.approve(
        import_id=imported.id,
        accrual_group="Комиссии",
        accrual_type="Вознаграждение за продажу",
        accounting_class=AccrualAccountingClass.PLATFORM_FEE,
        expected_sign=AccrualExpectedSign.NEGATIVE,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        rationale="Platform commission control row; separate fee facts remain required for posting.",
        approved_by="reviewer-1",
    )
    status = classifications.status(imported.id)
    assert status["ready"] is True
    assert status["pairs"][0]["currency_totals"] == [{"currency": "RUB", "total_amount": "-150"}]
    assert status["pairs"][0]["observed_signs"] == ["negative"]
    assert status["pairs"][0]["expected_signs"] == ["negative"]
    assert status["posting_policy"] == "control_only_no_finance_entry"
    assert status["automatic_finance_posting"] is False
    assert status["order_revenue_replacement"] is False

    promoted = facts.promote(imported.id, created_by="operator-1")
    assert promoted.promoted_count == 2
    assert finance.list_entries() == []
    for fact in facts.list(fact_type="ozon_accrual"):
        with pytest.raises(ValueError, match="approved accounting classification"):
            finance.ingest_fact(fact.id, created_by="operator-1")


def test_accrual_classification_is_independent_and_interval_must_cover_observed_rows():
    _, reviews, classifications, _, _, imported, _ = make_accrual_import()
    accepted_review(reviews, imported)

    with pytest.raises(ValueError, match="uploader"):
        classifications.approve(
            import_id=imported.id,
            accrual_group="Продажи",
            accrual_type="Продажа товара",
            accounting_class=AccrualAccountingClass.SALES,
            expected_sign=AccrualExpectedSign.POSITIVE,
            effective_from="2026-07-01T00:00:00+00:00",
            effective_until=None,
            rationale="Self approval must be rejected.",
            approved_by="operator-1",
        )
    with pytest.raises(ValueError, match="does not cover"):
        classifications.approve(
            import_id=imported.id,
            accrual_group="Продажи",
            accrual_type="Продажа товара",
            accounting_class=AccrualAccountingClass.SALES,
            expected_sign=AccrualExpectedSign.POSITIVE,
            effective_from="2027-01-01T00:00:00+00:00",
            effective_until=None,
            rationale="Out-of-period classifications must not unlock the import.",
            approved_by="reviewer-1",
        )
    with pytest.raises(ValueError, match="expected sign"):
        classifications.approve(
            import_id=imported.id,
            accrual_group="Продажи",
            accrual_type="Продажа товара",
            accounting_class=AccrualAccountingClass.SALES,
            expected_sign=AccrualExpectedSign.NEGATIVE,
            effective_from="2026-07-01T00:00:00+00:00",
            effective_until=None,
            rationale="A negative-sign contract must not cover positive sales rows.",
            approved_by="reviewer-1",
        )


def test_accrual_classification_never_sums_different_currencies():
    content = (
        "id начисления;группа услуг;тип начисления;amount;currency;дата начисления\n"
        "accrual-1;Продажи;Продажа товара;100;RUB;2026-07-16T10:00:00+03:00\n"
        "accrual-2;Продажи;Продажа товара;2;USD;2026-07-16T10:00:00+03:00\n"
    ).encode()
    _, reviews, classifications, _, _, imported, _ = make_accrual_import(content)
    accepted_review(reviews, imported)

    status = classifications.status(imported.id)
    pair = status["pairs"][0]
    assert pair["currency"] is None
    assert pair["total_amount"] is None
    assert pair["currency_totals"] == [
        {"currency": "RUB", "total_amount": "100"},
        {"currency": "USD", "total_amount": "2"},
    ]
