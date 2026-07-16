from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import Product
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.facts import FactPromotionService
from apps.control_plane.imports import OzonImportService
from apps.control_plane.sql_repository import Base, ProductRow


def make_services():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return (
        engine,
        EvidenceService(engine),
        OzonImportService(engine),
        FactPromotionService(engine),
    )


def source_evidence(service: EvidenceService, content: bytes):
    return service.capture(
        content=content,
        filename="orders.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref="ozon-upload://orders-2026-07-16",
        grade=EvidenceGrade.A,
        effective_at="2026-07-16T10:00:00+03:00",
        effective_until=None,
        created_by="operator-1",
    )


def test_accepted_staging_row_promotes_to_immutable_formal_fact():
    engine, evidence, imports, facts = make_services()
    product = Product(sku="SKU-1", name="Test item")
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id=product.id,
                sku=product.sku,
                name=product.name,
                market=product.market,
                channel=product.channel,
                status=product.status.value,
                created_at=datetime.fromisoformat(product.created_at),
            )
        )
    content = (
        "номер заказа;артикул;количество;валюта;цена;дата заказа\n1001;SKU-1;2;RUB;1299,50;2026-07-16T10:00:00+03:00\n"
    ).encode()
    source = source_evidence(evidence, content)
    imported = imports.import_file(filename="orders.csv", content=content, evidence_id=source.id)

    first = facts.promote(imported.id, created_by="operator-1")
    second = facts.promote(imported.id, created_by="operator-1")
    promoted = facts.list(fact_type="ozon_order")

    assert first.promoted_count == 1
    assert first.blocked_count == 0
    assert second.duplicate_count == 1
    assert len(promoted) == 1
    assert promoted[0].product_id == product.id
    assert promoted[0].resolution_status == "resolved"
    assert promoted[0].payload["gross_revenue"] == "1299.50"
    assert promoted[0].evidence_id == source.id


def test_promotion_fails_closed_without_source_evidence():
    _, _, imports, facts = make_services()
    content = (
        "номер заказа;артикул;количество;валюта;цена;дата заказа\n1002;SKU-2;1;RUB;500;2026-07-16T11:00:00+03:00\n"
    ).encode()
    imported = imports.import_file(filename="orders.csv", content=content)
    with pytest.raises(ValueError, match="source evidence"):
        facts.promote(imported.id, created_by="operator-1")


def test_rejected_import_cannot_be_promoted():
    _, evidence, imports, facts = make_services()
    content = "номер заказа;артикул\n1003;SKU-3\n".encode()
    source = source_evidence(evidence, content)
    imported = imports.import_file(filename="orders.csv", content=content, evidence_id=source.id)

    assert imported.status == "rejected"
    with pytest.raises(ValueError, match="Rejected import"):
        facts.promote(imported.id, created_by="operator-1")
