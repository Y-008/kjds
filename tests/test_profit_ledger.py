from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import Charge, ChargeType, Order, Product
from apps.control_plane.evidence import (
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.facts import FactRecordRow
from apps.control_plane.finance import (
    FinanceEntryKind,
    FinanceService,
    FxRateRow,
)
from apps.control_plane.profit_ledger import EROSION_CATEGORIES, ProfitLedgerService
from apps.control_plane.sql_repository import Base, SqlAlchemyRepository


class EmptySourcingStore:
    def list_listing_drafts(self, limit=5000):
        return []


def services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return (
        engine,
        SqlAlchemyRepository(engine),
        EvidenceService(engine),
        FinanceService(engine),
        ProfitLedgerService(engine=engine, sourcing_store=EmptySourcingStore()),
    )


def evidence(service, name):
    return service.capture(
        content=f"evidence:{name}".encode(),
        filename=f"{name}.txt",
        content_type="text/plain",
        source="test",
        source_ref=f"test://{name}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-01T00:00:00+00:00",
        effective_until=None,
        created_by="independent-source",
    )


def formal_order(engine, *, product_id, evidence_id, external_id="order-1", currency="CNY"):
    now = datetime(2026, 7, 26, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            FactRecordRow(
                id=f"fact-{external_id}",
                source="ozon",
                fact_type="ozon_order",
                natural_key=external_id,
                contract_version="ozon-v1",
                payload_json={
                    "external_id": external_id,
                    "sku": "SKU-1",
                    "quantity": "1",
                    "currency": currency,
                    "gross_revenue": "100",
                    "effective_at": now.isoformat(),
                },
                payload_hash="a" * 64,
                effective_at=now,
                recorded_at=now,
                evidence_id=evidence_id,
                import_row_id=f"row-{external_id}",
                product_id=product_id,
                resolution_status="resolved",
                created_by="promoter",
            )
        )


def test_profit_ledger_reconciles_only_explicit_order_legs_and_conserves_erosion():
    engine, repo, evidence_service, finance, ledger = services()
    source = evidence(evidence_service, "source")
    bank = evidence(evidence_service, "bank")
    product = repo.add_product(Product("SKU-1", "真实商品"))
    order = repo.add_order(
        Order(
            external_id="order-1",
            product_id=product.id,
            quantity=1,
            currency="CNY",
            gross_revenue=Decimal("100"),
            booked_fx_rate=Decimal("1"),
        )
    )
    for kind, amount in (
        (ChargeType.PRODUCT_COST, "30"),
        (ChargeType.PLATFORM_FEE, "10"),
        (ChargeType.RETURN, "5"),
    ):
        repo.add_charge(
            Charge(
                order_id=order.id,
                kind=kind,
                amount=Decimal(amount),
                currency="CNY",
                fx_rate=Decimal("1"),
                evidence_ref=source.id,
            )
        )
    formal_order(engine, product_id=product.id, evidence_id=source.id)
    common = {
        "reconciliation_key": "order-1",
        "currency": "CNY",
        "effective_at": "2026-07-26T00:00:00+00:00",
        "created_by": "finance-operator",
    }
    finance.record_entry(
        entry_kind=FinanceEntryKind.ORDER_RECEIVABLE,
        source="ozon",
        source_ref="order-1-receivable",
        amount=Decimal("100"),
        evidence_id=source.id,
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_SETTLEMENT,
        source="ozon",
        source_ref="order-1-settlement",
        amount=Decimal("55"),
        evidence_id=source.id,
        **common,
    )
    finance.record_entry(
        entry_kind=FinanceEntryKind.BANK_RECEIPT,
        source="bank",
        source_ref="order-1-bank",
        amount=Decimal("55"),
        evidence_id=bank.id,
        **common,
    )

    snapshot = ledger.snapshot()
    erosion = ledger.erosion()

    assert snapshot["status"] == "reconciled"
    assert snapshot["rows"][0]["actual_profit"] == "10"
    assert snapshot["rows"][0]["erosion"]["purchase"] == "30"
    assert snapshot["rows"][0]["erosion"]["commission"] == "10"
    assert snapshot["rows"][0]["erosion"]["returns"] == "5"
    assert snapshot["unallocated"] == []
    assert erosion["conserved"] is True
    assert erosion["conservation_delta"] == "0"
    assert Decimal(erosion["baseline"]) - sum(
        (Decimal(item["amount"]) for item in erosion["items"]), Decimal("0")
    ) == Decimal(erosion["result"])
    assert {item["category"] for item in erosion["items"]} == set(
        EROSION_CATEGORIES
    )


def test_unmatched_settlement_is_blocked_and_never_proportionally_allocated():
    _, _, evidence_service, finance, ledger = services()
    source = evidence(evidence_service, "unmatched")
    finance.record_entry(
        entry_kind=FinanceEntryKind.PLATFORM_SETTLEMENT,
        source="ozon",
        source_ref="settlement-unknown",
        reconciliation_key="unmatched-order",
        amount=Decimal("90"),
        currency="CNY",
        effective_at="2026-07-26T00:00:00+00:00",
        evidence_id=source.id,
        created_by="finance-operator",
    )

    snapshot = ledger.snapshot()

    assert snapshot["status"] == "blocked"
    assert snapshot["rows"] == []
    assert snapshot["unallocated"][0]["amount"] == "90"
    assert (
        snapshot["control_envelope"]["proportional_allocation_allowed"] is False
    )
    assert snapshot["unallocated"][0]["reason"] == "requires_explicit_order_binding"


def test_cross_currency_formal_order_without_effective_fx_is_blocked():
    engine, repo, evidence_service, _, ledger = services()
    source = evidence(evidence_service, "rub-order")
    product = repo.add_product(Product("SKU-1", "真实商品"))
    formal_order(
        engine,
        product_id=product.id,
        evidence_id=source.id,
        external_id="rub-order",
        currency="RUB",
    )

    snapshot = ledger.snapshot(order_id="rub-order")

    assert snapshot["status"] == "blocked"
    assert snapshot["rows"][0]["gross_revenue"] == "0"
    assert any(
        blocker.startswith("missing_fx:RUB/CNY")
        for blocker in snapshot["rows"][0]["blockers"]
    )


def test_expired_evidence_blocks_actual_profit_instead_of_degrading_silently():
    engine, repo, evidence_service, _, ledger = services()
    expired = evidence(evidence_service, "expired-order")
    with Session(engine) as session, session.begin():
        record = session.get(EvidenceRecordRow, expired.id)
        record.effective_until = datetime.now(UTC) - timedelta(days=1)
    product = repo.add_product(Product("SKU-EXPIRED", "过期凭证商品"))
    repo.add_order(
        Order(
            external_id="expired-order",
            product_id=product.id,
            quantity=1,
            currency="CNY",
            gross_revenue=Decimal("100"),
            booked_fx_rate=Decimal("1"),
        )
    )
    formal_order(
        engine,
        product_id=product.id,
        evidence_id=expired.id,
        external_id="expired-order",
    )

    snapshot = ledger.snapshot(order_id="expired-order")

    assert snapshot["status"] == "blocked"
    assert snapshot["rows"][0]["actual_profit"] is None
    assert f"invalid_evidence:{expired.id}" in snapshot["rows"][0]["blockers"]


def test_replayed_formal_order_facts_never_double_count_order_revenue():
    engine, repo, evidence_service, _, ledger = services()
    source = evidence(evidence_service, "replayed-order")
    product = repo.add_product(Product("SKU-REPLAY", "重放商品"))
    repo.add_order(
        Order(
            external_id="replayed-order",
            product_id=product.id,
            quantity=1,
            currency="CNY",
            gross_revenue=Decimal("100"),
            booked_fx_rate=Decimal("1"),
        )
    )
    formal_order(
        engine,
        product_id=product.id,
        evidence_id=source.id,
        external_id="replayed-order",
    )
    now = datetime(2026, 7, 26, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            FactRecordRow(
                id="fact-replayed-order-second-import",
                source="ozon",
                fact_type="ozon_order",
                natural_key="replayed-order",
                contract_version="ozon-v1",
                payload_json={
                    "external_id": "replayed-order",
                    "sku": "SKU-REPLAY",
                    "quantity": "1",
                    "currency": "CNY",
                    "gross_revenue": "100",
                    "effective_at": now.isoformat(),
                },
                payload_hash="b" * 64,
                effective_at=now,
                recorded_at=now,
                evidence_id=source.id,
                import_row_id="row-replayed-order-second-import",
                product_id=product.id,
                resolution_status="resolved",
                created_by="promoter",
            )
        )

    snapshot = ledger.snapshot(order_id="replayed-order")

    assert len(snapshot["rows"]) == 1
    assert snapshot["rows"][0]["gross_revenue"] == "100"


def test_fx_rate_selection_uses_only_rates_effective_on_accounting_date():
    engine, repo, evidence_service, _, ledger = services()
    source = evidence(evidence_service, "fx-effective-date")
    product = repo.add_product(Product("SKU-FX", "汇率日期商品"))
    formal_order(
        engine,
        product_id=product.id,
        evidence_id=source.id,
        external_id="fx-effective-order",
        currency="RUB",
    )
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                FxRateRow(
                    id="fx-before",
                    base_currency="RUB",
                    quote_currency="CNY",
                    rate=Decimal("0.10"),
                    version=1,
                    effective_at=datetime(2026, 7, 25, tzinfo=UTC),
                    source="bank",
                    evidence_id=source.id,
                    created_by="finance",
                    recorded_at=datetime(2026, 7, 25, tzinfo=UTC),
                ),
                FxRateRow(
                    id="fx-after",
                    base_currency="RUB",
                    quote_currency="CNY",
                    rate=Decimal("0.20"),
                    version=2,
                    effective_at=datetime(2026, 7, 27, tzinfo=UTC),
                    source="bank",
                    evidence_id=source.id,
                    created_by="finance",
                    recorded_at=datetime(2026, 7, 27, tzinfo=UTC),
                ),
            ]
        )

    snapshot = ledger.snapshot(order_id="fx-effective-order")

    assert snapshot["rows"][0]["gross_revenue"] == "10"
    assert not any(
        blocker.startswith("missing_fx:RUB/CNY")
        for blocker in snapshot["rows"][0]["blockers"]
    )
