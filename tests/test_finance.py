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
from apps.control_plane.sql_repository import Base


def make_services():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return EvidenceService(engine), OzonImportService(engine), FactPromotionService(engine), FinanceService(engine)


def capture_evidence(service: EvidenceService, content: bytes, *, name: str = "source.csv"):
    digest = hashlib.sha256(content).hexdigest()
    return service.capture(
        content=content,
        filename=name,
        content_type="text/csv",
        source="test",
        source_ref=f"test://{digest}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-01T00:00:00+00:00",
        effective_until=None,
        created_by="finance-reviewer",
    )


def test_fee_dictionary_fx_and_three_way_reconciliation_match_without_floats():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"finance evidence")
    mapping = finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=source.id,
        approved_by="finance-reviewer",
    )
    rate = finance.add_fx_rate(
        base_currency="RUB",
        quote_currency="CNY",
        rate=Decimal("0.08"),
        effective_at="2026-07-01T00:00:00+00:00",
        source="bank-of-china",
        evidence_id=source.id,
        created_by="finance-reviewer",
    )
    common = {
        "reconciliation_key": "order-1001",
        "currency": "RUB",
        "effective_at": "2026-07-16T10:00:00+03:00",
        "evidence_id": source.id,
        "created_by": "finance-reviewer",
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
        **common,
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

    duplicate_mapping = finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=source.id,
        approved_by="finance-reviewer",
    )
    duplicate_rate = finance.add_fx_rate(
        base_currency="RUB",
        quote_currency="CNY",
        rate=Decimal("0.08"),
        effective_at="2026-07-01T00:00:00+00:00",
        source="bank-of-china",
        evidence_id=source.id,
        created_by="finance-reviewer",
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
    source = capture_evidence(evidence, content, name="transactions.csv")
    imported = imports.import_file(filename="transactions.csv", content=content, evidence_id=source.id)
    promoted = facts.promote(imported.id, created_by="operator")
    fact = facts.list(fact_type="ozon_fee")[0]

    first = finance.ingest_fact(fact.id, created_by="finance-reviewer")
    second = finance.ingest_fact(fact.id, created_by="finance-reviewer")

    assert promoted.promoted_count == 1
    assert first.id == second.id
    assert first.entry_kind == "platform_fee"
    assert first.raw_fee_code == "delivery_service"
    assert first.evidence_id == source.id


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
