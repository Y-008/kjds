import hashlib
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import ChargeType
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.facts import FactPromotionService
from apps.control_plane.finance import (
    CashPlanStatus,
    FeeSignRule,
    FinanceEntryKind,
    FinanceService,
)
from apps.control_plane.imports import OzonImportService
from apps.control_plane.ozon_finance_review import (
    AccrualAccountingClass,
    AccrualExpectedSign,
    OzonAccrualClassificationService,
    OzonFeeMappingApprovalService,
    OzonFinanceReportReviewService,
)
from apps.control_plane.sql_repository import Base


def make_services():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return EvidenceService(engine), OzonImportService(engine), FactPromotionService(engine), FinanceService(engine)


def capture_evidence(
    service: EvidenceService,
    content: bytes,
    *,
    name: str = "source.csv",
    source: str = "test",
    created_by: str = "source-uploader",
):
    digest = hashlib.sha256(content).hexdigest()
    return service.capture(
        content=content,
        filename=name,
        content_type="text/csv",
        source=source,
        source_ref=f"{source}://{digest}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-01T00:00:00+00:00",
        effective_until=None,
        created_by=created_by,
    )


def record_reconciliation_legs(
    finance: FinanceService,
    *,
    key: str,
    platform_evidence_id: str,
    bank_evidence_id: str,
    created_by: str,
):
    common = {
        "reconciliation_key": key,
        "currency": "CNY",
        "effective_at": "2026-07-16T00:00:00+00:00",
        "created_by": created_by,
    }
    finance.record_entry(
        entry_kind=FinanceEntryKind.ORDER_RECEIVABLE,
        source="ozon",
        source_ref=f"{key}-order",
        amount=Decimal("100"),
        evidence_id=platform_evidence_id,
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_SETTLEMENT,
        source="ozon",
        source_ref=f"{key}-settlement",
        amount=Decimal("100"),
        evidence_id=platform_evidence_id,
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.BANK_RECEIPT,
        source="bank",
        source_ref=f"{key}-bank",
        amount=Decimal("100"),
        evidence_id=bank_evidence_id,
        **common,
    )


def test_fee_dictionary_fx_and_three_way_reconciliation_match_without_floats():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"finance evidence")
    bank_source = capture_evidence(evidence, b"bank evidence", name="bank.csv")
    mapping = finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=source.id,
        approved_by="mapping-approver",
    )
    rate = finance.add_fx_rate(
        base_currency="RUB",
        quote_currency="CNY",
        rate=Decimal("0.08"),
        effective_at="2026-07-01T00:00:00+00:00",
        source="bank-of-china",
        evidence_id=source.id,
        created_by="fx-operator",
    )
    common = {
        "reconciliation_key": "order-1001",
        "currency": "RUB",
        "effective_at": "2026-07-16T10:00:00+03:00",
        "evidence_id": source.id,
        "created_by": "finance-operator",
    }
    finance.record_entry(
        entry_kind=FinanceEntryKind.ORDER_RECEIVABLE,
        source="test",
        source_ref="order-1001",
        amount=Decimal("1000"),
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_FEE,
        source="test",
        source_ref="fee-1001",
        raw_fee_code="delivery_service",
        amount=Decimal("100"),
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_SETTLEMENT,
        source="test",
        source_ref="settlement-1001",
        amount=Decimal("900"),
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.BANK_RECEIPT,
        source="test",
        source_ref="bank-1001",
        amount=Decimal("900"),
        **{**common, "evidence_id": bank_source.id},
    )

    result = finance.reconcile(
        "order-1001",
        quote_currency="CNY",
        fx_source="bank-of-china",
        tolerance_ratio=Decimal("0.003"),
        created_by="finance-reviewer",
    )

    assert result["status"] == "matched"
    assert Decimal(result["snapshot"]["expected_settlement"]) == Decimal("72")
    assert Decimal(result["snapshot"]["platform_settlement"]) == Decimal("72")
    assert Decimal(result["snapshot"]["bank_receipt"]) == Decimal("72")
    assert result["snapshot"]["unknown_fees"] == []
    assert len(result["snapshot"]["applied_fx"]) == 4
    assert result["snapshot"]["evidence_conflicts"] == []
    assert result["snapshot"]["self_review_dependencies"] == []

    duplicate_mapping = finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=source.id,
        approved_by="mapping-approver",
    )
    duplicate_rate = finance.add_fx_rate(
        base_currency="RUB",
        quote_currency="CNY",
        rate=Decimal("0.08"),
        effective_at="2026-07-01T00:00:00+00:00",
        source="bank-of-china",
        evidence_id=source.id,
        created_by="fx-operator",
    )
    corrected_mapping = finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.PRESERVE,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=source.id,
        approved_by="finance-reviewer",
    )
    assert duplicate_mapping.id == mapping.id
    assert duplicate_rate.id == rate.id
    assert corrected_mapping.version == 2


def test_reconciliation_blocks_reviewer_who_created_finance_entries():
    evidence, _, _, finance = make_services()
    platform_source = capture_evidence(evidence, b"platform source")
    bank_source = capture_evidence(evidence, b"bank source")
    record_reconciliation_legs(
        finance,
        key="self-review",
        platform_evidence_id=platform_source.id,
        bank_evidence_id=bank_source.id,
        created_by="finance-reviewer",
    )

    result = finance.reconcile(
        "self-review",
        quote_currency="CNY",
        fx_source="unused",
        tolerance_ratio=Decimal("0.003"),
        created_by="finance-reviewer",
    )

    assert result["status"] == "blocked_self_review"
    assert {item["type"] for item in result["snapshot"]["self_review_dependencies"]} == {"finance_entry"}


def test_reconciliation_blocks_evidence_uploader_from_reviewing_own_source():
    evidence, _, _, finance = make_services()
    platform_source = capture_evidence(evidence, b"platform source", created_by="finance-reviewer")
    bank_source = capture_evidence(evidence, b"bank source")
    record_reconciliation_legs(
        finance,
        key="uploader-self-review",
        platform_evidence_id=platform_source.id,
        bank_evidence_id=bank_source.id,
        created_by="finance-operator",
    )

    result = finance.reconcile(
        "uploader-self-review",
        quote_currency="CNY",
        fx_source="unused",
        tolerance_ratio=Decimal("0.003"),
        created_by="finance-reviewer",
    )

    assert result["status"] == "blocked_self_review"
    assert result["snapshot"]["self_review_dependencies"] == [{"type": "evidence", "id": platform_source.id}]


def test_reconciliation_requires_bank_evidence_independent_from_platform_evidence():
    evidence, _, _, finance = make_services()
    shared_source = capture_evidence(evidence, b"shared source")
    recaptured_bank_source = capture_evidence(evidence, b"shared source", source="bank")
    assert recaptured_bank_source.id != shared_source.id
    record_reconciliation_legs(
        finance,
        key="shared-evidence",
        platform_evidence_id=shared_source.id,
        bank_evidence_id=recaptured_bank_source.id,
        created_by="finance-operator",
    )

    result = finance.reconcile(
        "shared-evidence",
        quote_currency="CNY",
        fx_source="unused",
        tolerance_ratio=Decimal("0.003"),
        created_by="independent-reviewer",
    )

    assert result["status"] == "blocked_evidence_independence"
    assert result["snapshot"]["evidence_conflicts"] == [
        {
            "blob_sha256": shared_source.sha256,
            "bank_evidence_ids": [recaptured_bank_source.id],
            "platform_evidence_ids": [shared_source.id],
        }
    ]


def test_finance_entry_idempotency_rejects_conflicting_payload():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"idempotency")
    values = {
        "entry_kind": FinanceEntryKind.BANK_RECEIPT,
        "source": "bank",
        "source_ref": "line-1",
        "reconciliation_key": "settlement-1",
        "currency": "CNY",
        "effective_at": "2026-07-16T00:00:00+00:00",
        "evidence_id": source.id,
        "created_by": "finance-reviewer",
    }
    finance.record_entry(amount=Decimal("100"), **values)

    with pytest.raises(ValueError, match="idempotency key conflicts"):
        finance.record_entry(amount=Decimal("101"), **values)


def test_unknown_fee_is_isolated_instead_of_being_hidden_in_other():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"unknown fee")
    common = {
        "reconciliation_key": "order-unknown",
        "currency": "CNY",
        "effective_at": "2026-07-16T00:00:00+00:00",
        "evidence_id": source.id,
        "created_by": "finance-reviewer",
    }
    finance.record_entry(
        entry_kind=FinanceEntryKind.ORDER_RECEIVABLE,
        source="test",
        source_ref="unknown-order",
        amount=Decimal("100"),
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_FEE,
        source="test",
        source_ref="unknown-fee",
        raw_fee_code="unmapped-raw-code",
        amount=Decimal("10"),
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_SETTLEMENT,
        source="test",
        source_ref="unknown-settlement",
        amount=Decimal("90"),
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.BANK_RECEIPT,
        source="test",
        source_ref="unknown-bank",
        amount=Decimal("90"),
        **common,
    )

    result = finance.reconcile(
        "order-unknown",
        quote_currency="CNY",
        fx_source="unused",
        tolerance_ratio=Decimal("0.003"),
        created_by="finance-reviewer",
    )

    assert result["status"] == "blocked_unknown_fee"
    assert result["snapshot"]["unknown_fees"] == [
        {"entry_id": finance.list_entries(entry_kind=FinanceEntryKind.PLATFORM_FEE)[0].id, "raw_fee_code": "unmapped-raw-code", "amount": "10.000000000000"}
    ]


def test_formal_ozon_fee_fact_can_be_ingested_once_into_finance_ledger():
    evidence, imports, facts, finance = make_services()
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
        effective_at="2026-07-01T00:00:00+00:00",
        effective_until=None,
        created_by="operator",
        metadata={
            "sha256": digest,
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
        created_by="operator",
    )
    reviews = OzonFinanceReportReviewService(engine=facts.engine, evidence=evidence, imports=imports)
    reviews.review(
        import_id=imported.id,
        accepted=True,
        authentic_account_export=True,
        period_matches=True,
        not_public_sample=True,
        complete_export=True,
        rationale="Verified against the original account export.",
        reviewed_by="finance-reviewer",
    )
    mappings = OzonFeeMappingApprovalService(
        engine=facts.engine,
        evidence=evidence,
        imports=imports,
        reviews=reviews,
        finance=finance,
    )
    mappings.approve(
        import_id=imported.id,
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        rationale="Verified delivery service fee classification.",
        approved_by="finance-reviewer",
    )
    facts = FactPromotionService(
        facts.engine,
        finance_review_validator=reviews.require_accepted,
        fee_mapping_validator=mappings.require_mapped,
    )
    promoted = facts.promote(imported.id, created_by="operator")
    fact = facts.list(fact_type="ozon_fee")[0]

    first = finance.ingest_fact(fact.id, created_by="finance-reviewer")
    second = finance.ingest_fact(fact.id, created_by="finance-reviewer")

    assert promoted.promoted_count == 1
    assert first.id == second.id
    assert first.entry_kind == "platform_fee"
    assert first.raw_fee_code == "delivery_service"
    assert first.evidence_id == source.id


def test_official_accrual_fact_stays_out_of_finance_until_accounting_classification_is_approved():
    evidence, imports, facts, finance = make_services()
    content = (
        "ID начисления;Дата начисления;Группа услуг;Тип начисления;Сумма итого, руб.\n"
        "operation-1;2025-10-04T00:00:00+03:00;Продажи;Выручка;6512\n"
    ).encode()
    digest = hashlib.sha256(content).hexdigest()
    source = evidence.capture(
        content=content,
        filename="Отчет по начислениям_01.10.2025-31.10.2025.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref=f"ozon-upload://sha256/{digest}",
        grade=EvidenceGrade.A,
        effective_at="2025-10-01T00:00:00+00:00",
        effective_until=None,
        created_by="operator",
        metadata={
            "sha256": digest,
            "report_period_start": "2025-10-01",
            "report_period_end": "2025-10-31",
        },
    )
    imported = imports.import_file(
        filename="Отчет по начислениям_01.10.2025-31.10.2025.csv",
        content=content,
        evidence_id=source.id,
    )
    evidence.link(
        evidence_id=source.id,
        target_type="import_job",
        target_id=imported.id,
        relationship="source_for",
        created_by="operator",
    )
    reviews = OzonFinanceReportReviewService(engine=facts.engine, evidence=evidence, imports=imports)
    reviews.review(
        import_id=imported.id,
        accepted=True,
        authentic_account_export=True,
        period_matches=True,
        not_public_sample=True,
        complete_export=True,
        rationale="Compared against the original account export.",
        reviewed_by="finance-reviewer",
    )
    classifications = OzonAccrualClassificationService(
        engine=facts.engine,
        evidence=evidence,
        imports=imports,
        reviews=reviews,
    )
    classifications.approve(
        import_id=imported.id,
        accrual_group="Продажи",
        accrual_type="Выручка",
        accounting_class=AccrualAccountingClass.SALES,
        expected_sign=AccrualExpectedSign.POSITIVE,
        effective_from="2025-10-01T00:00:00+00:00",
        effective_until=None,
        rationale="Platform control revenue does not replace order revenue facts.",
        approved_by="finance-reviewer",
    )
    controlled_facts = FactPromotionService(
        facts.engine,
        finance_review_validator=reviews.require_accepted,
        accrual_classification_validator=classifications.require_classified,
    )
    promoted = controlled_facts.promote(imported.id, created_by="operator")
    fact = controlled_facts.list(fact_type="ozon_accrual")[0]

    assert promoted.promoted_count == 1
    with pytest.raises(ValueError, match="approved accounting classification"):
        finance.ingest_fact(fact.id, created_by="finance-reviewer")


def test_thirteen_week_cash_forecast_separates_committed_and_probability_weighted_items():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"cash plan")
    finance.add_fx_rate(
        base_currency="RUB",
        quote_currency="CNY",
        rate=Decimal("0.08"),
        effective_at="2026-07-01T00:00:00+00:00",
        source="bank-of-china",
        evidence_id=source.id,
        created_by="finance-reviewer",
    )
    finance.add_cash_plan_item(
        source="purchase-plan",
        source_ref="purchase-1",
        category="inventory",
        amount=Decimal("-1000"),
        currency="RUB",
        expected_at="2026-07-17T00:00:00+00:00",
        probability=Decimal("1"),
        status=CashPlanStatus.COMMITTED,
        evidence_id=source.id,
        created_by="finance-reviewer",
    )
    finance.add_cash_plan_item(
        source="sales-plan",
        source_ref="sales-1",
        category="settlement",
        amount=Decimal("2000"),
        currency="RUB",
        expected_at="2026-07-24T00:00:00+00:00",
        probability=Decimal("0.5"),
        status=CashPlanStatus.SCENARIO,
        evidence_id=source.id,
        created_by="finance-reviewer",
    )

    result = finance.cash_forecast(
        start_at="2026-07-16T00:00:00+00:00",
        opening_balance=Decimal("100"),
        quote_currency="CNY",
        fx_source="bank-of-china",
    )

    assert result["status"] == "ready"
    assert Decimal(result["weeks"][0]["committed_closing_balance"]) == Decimal("20")
    assert Decimal(result["weeks"][0]["probability_weighted_closing_balance"]) == Decimal("20")
    assert Decimal(result["weeks"][1]["committed_closing_balance"]) == Decimal("20")
    assert Decimal(result["weeks"][1]["probability_weighted_closing_balance"]) == Decimal("100")
    assert len(result["weeks"]) == 13


def test_finance_rejects_non_finite_values_before_persistence():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"finite finance inputs")

    with pytest.raises(ValueError, match="FX rate must be finite"):
        finance.add_fx_rate(
            base_currency="RUB",
            quote_currency="CNY",
            rate=Decimal("NaN"),
            effective_at="2026-07-01T00:00:00+00:00",
            source="bank-of-china",
            evidence_id=source.id,
            created_by="finance-reviewer",
        )
    with pytest.raises(ValueError, match="Finance entry amount must be finite"):
        finance.record_entry(
            entry_kind=FinanceEntryKind.BANK_RECEIPT,
            source="bank",
            source_ref="unsafe-amount",
            reconciliation_key="unsafe",
            amount=Decimal("Infinity"),
            currency="CNY",
            effective_at="2026-07-16T00:00:00+00:00",
            evidence_id=source.id,
            created_by="finance-reviewer",
        )
    with pytest.raises(ValueError, match="Reconciliation tolerance must be finite"):
        finance.reconcile(
            "unsafe",
            quote_currency="CNY",
            fx_source="bank-of-china",
            tolerance_ratio=Decimal("NaN"),
            created_by="finance-reviewer",
        )
    with pytest.raises(ValueError, match="Cash plan probability must be finite"):
        finance.add_cash_plan_item(
            source="plan",
            source_ref="unsafe-probability",
            category="inventory",
            amount=Decimal("1"),
            currency="CNY",
            expected_at="2026-07-17T00:00:00+00:00",
            probability=Decimal("NaN"),
            status=CashPlanStatus.SCENARIO,
            evidence_id=source.id,
            created_by="finance-reviewer",
        )
    with pytest.raises(ValueError, match="Opening balance must be finite"):
        finance.cash_forecast(
            start_at="2026-07-16T00:00:00+00:00",
            opening_balance=Decimal("-Infinity"),
            quote_currency="CNY",
            fx_source="bank-of-china",
        )
