import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.control_plane.domain import ChargeType
from apps.control_plane.finance import (
    FeeSignRule,
    FinanceEntryKind,
    FinanceEntryRow,
)
from tests.test_finance import capture_evidence, make_services

AS_OF = (datetime.now(UTC) + timedelta(hours=1)).isoformat()


def scope(entity_ref: str, authority: str) -> dict[str, str]:
    return {
        "tenant_ref": "tenant-a",
        "entity_ref": entity_ref,
        "store_ref": "ozon-primary",
        "scope_grant_authority_sha256": authority,
        "scope_as_of": AS_OF,
    }


def test_scoped_fee_mapping_and_fx_are_idempotent_and_entity_isolated():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"native profit authorities")
    scope_a = scope("entity-a", "a" * 64)
    scope_b = scope("entity-b", "b" * 64)

    mapping_a = finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=source.id,
        approved_by="mapping-approver",
        scope_authority=scope_a,
    )
    duplicate_a = finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=source.id,
        approved_by="mapping-approver",
        scope_authority=scope_a,
    )
    mapping_b = finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=source.id,
        approved_by="mapping-approver",
        scope_authority=scope_b,
    )
    rate_a = finance.add_fx_rate(
        base_currency="RUB",
        quote_currency="CNY",
        rate=Decimal("0.08"),
        effective_at="2026-07-01T00:00:00+00:00",
        source="bank-of-china",
        evidence_id=source.id,
        created_by="fx-operator",
        scope_authority=scope_a,
    )
    rate_b = finance.add_fx_rate(
        base_currency="RUB",
        quote_currency="CNY",
        rate=Decimal("0.09"),
        effective_at="2026-07-01T00:00:00+00:00",
        source="bank-of-china",
        evidence_id=source.id,
        created_by="fx-operator",
        scope_authority=scope_b,
    )

    assert duplicate_a.id == mapping_a.id
    assert mapping_b.id != mapping_a.id
    assert rate_b.id != rate_a.id
    assert finance.list_fee_mappings() == []
    assert finance.list_fx_rates() == []

    authority_a = finance.read_scoped_profit_authorities(
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="ozon-primary",
        scope_grant_authority_sha256="a" * 64,
        as_of=AS_OF,
    )
    authority_b = finance.read_scoped_profit_authorities(
        tenant_ref="tenant-a",
        entity_ref="entity-b",
        store_ref="ozon-primary",
        scope_grant_authority_sha256="b" * 64,
        as_of=AS_OF,
    )
    assert [item["id"] for item in authority_a["fee_mappings"]] == [
        mapping_a.id
    ]
    assert [
        Decimal(item["rate"]) for item in authority_a["fx_rates"]
    ] == [Decimal("0.08")]
    assert [item["id"] for item in authority_b["fee_mappings"]] == [
        mapping_b.id
    ]
    assert [
        Decimal(item["rate"]) for item in authority_b["fx_rates"]
    ] == [Decimal("0.09")]


def test_scoped_reconciliation_never_falls_back_to_legacy_fee_mapping():
    evidence, _, _, finance = make_services()
    platform = capture_evidence(evidence, b"platform")
    bank = capture_evidence(evidence, b"bank", name="bank.csv")
    finance.register_fee_mapping(
        provider="ozon",
        raw_code="delivery_service",
        canonical_type=ChargeType.PLATFORM_FEE,
        sign_rule=FeeSignRule.ABSOLUTE_OUTFLOW,
        effective_from="2026-07-01T00:00:00+00:00",
        effective_until=None,
        evidence_id=platform.id,
        approved_by="legacy-approver",
    )
    authority = scope("entity-a", "a" * 64)
    common = {
        "reconciliation_key": "order-scoped",
        "currency": "CNY",
        "effective_at": "2026-07-16T00:00:00+00:00",
        "created_by": "finance-operator",
        "scope_authority": authority,
    }
    finance.record_entry(
        entry_kind=FinanceEntryKind.ORDER_RECEIVABLE,
        source="ozon",
        source_ref="order",
        amount=Decimal("100"),
        evidence_id=platform.id,
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_FEE,
        source="ozon",
        source_ref="fee",
        raw_fee_code="delivery_service",
        amount=Decimal("10"),
        evidence_id=platform.id,
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_SETTLEMENT,
        source="ozon",
        source_ref="settlement",
        amount=Decimal("90"),
        evidence_id=platform.id,
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.BANK_RECEIPT,
        source="bank",
        source_ref="receipt",
        amount=Decimal("90"),
        evidence_id=bank.id,
        **common,
    )

    result = finance.reconcile(
        "order-scoped",
        quote_currency="CNY",
        fx_source="unused",
        tolerance_ratio=Decimal("0.003"),
        created_by="independent-reviewer",
        scope_authority=authority,
    )

    assert result["status"] == "blocked_unknown_fee"
    assert len(result["snapshot"]["unknown_fees"]) == 1
    assert result["snapshot"]["applied_fee_mappings"] == []


def test_bank_payment_requires_native_scope_supported_cost_and_outflow():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"bank payment")
    common = {
        "entry_kind": FinanceEntryKind.BANK_PAYMENT,
        "source": "bank",
        "source_ref": "payment-1",
        "reconciliation_key": "order-1",
        "currency": "CNY",
        "effective_at": "2026-07-16T00:00:00+00:00",
        "evidence_id": source.id,
        "created_by": "finance-operator",
        "profit_cost_type": ChargeType.PRODUCT_COST,
    }

    with pytest.raises(ValueError, match="native scope authority"):
        finance.record_entry(amount=Decimal("-20"), **common)
    with pytest.raises(ValueError, match="zero or an outflow"):
        finance.record_entry(
            amount=Decimal("20"),
            scope_authority=scope("entity-a", "a" * 64),
            **common,
        )
    with pytest.raises(ValueError, match="exact-scope fee mapping"):
        finance.record_entry(
            amount=Decimal("-10"),
            scope_authority=scope("entity-a", "a" * 64),
            **{
                **common,
                "profit_cost_type": ChargeType.PLATFORM_FEE,
            },
        )

    entry = finance.record_entry(
        amount=Decimal("-20"),
        scope_authority=scope("entity-a", "a" * 64),
        **common,
    )
    assert entry.profit_cost_type == ChargeType.PRODUCT_COST.value
    assert entry.scope["entity_ref"] == "entity-a"


def test_database_rejects_invalid_scoped_bank_payment_cost_type():
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"invalid bank payment")
    digest = hashlib.sha256(b"invalid bank payment").hexdigest()
    now = datetime.now(UTC)
    row = FinanceEntryRow(
        id="fin_invalid",
        entry_kind=FinanceEntryKind.BANK_PAYMENT.value,
        source="bank",
        source_ref="invalid",
        reconciliation_key="order-invalid",
        raw_fee_code=None,
        profit_cost_type="invented_cost",
        amount=Decimal("-1"),
        currency="CNY",
        effective_at=now,
        evidence_id=source.id,
        source_fact_id=None,
        review_required=False,
        created_by="test",
        recorded_at=now,
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="ozon-primary",
        scope_grant_authority_sha256="a" * 64,
        source_evidence_sha256=digest,
        scope_as_of=now,
    )
    with Session(finance.engine) as session, pytest.raises(IntegrityError):
        session.add(row)
        session.commit()
