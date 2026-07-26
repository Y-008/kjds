from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import Product, ProductStatus
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base
from apps.control_plane.supplier_rfq import (
    RFQ_CONTRACT_VERSION,
    RFQ_SOURCE,
    SupplierRfqWorkspace,
)


class CatalogStub:
    def __init__(self, *, product, item, binding):
        self.product = product
        self.item = item
        self.binding = binding
        self.calls = []

    def require_bound_current_item(
        self,
        *,
        store_ref: str,
        offer_id: str,
        expected_item_hash: str,
    ):
        self.calls.append(
            {
                "store_ref": store_ref,
                "offer_id": offer_id,
                "expected_item_hash": expected_item_hash,
            }
        )
        if expected_item_hash != self.item["item_hash"]:
            raise ValueError("Catalog item changed; refresh before continuing")
        return {
            "product": self.product,
            "item": self.item,
            "binding": self.binding,
        }


def make_workspace():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    source = evidence.capture(
        content=b'{"catalog":"verified"}',
        filename="catalog.json",
        content_type="application/json",
        source="ozon_read_only_pilot",
        source_ref="ozon://store-main/offer-1",
        grade=EvidenceGrade.A,
        effective_at="2026-07-24T00:00:00Z",
        effective_until=None,
        created_by="pilot-reader",
        metadata={"contract_version": "ozon-product-read-v1"},
    )
    product = Product(
        id="prd-existing-1",
        sku="ozon:store-main:offer-1",
        name="Portable electric hoist 500 kg",
        market="RU",
        channel="OZON",
        status=ProductStatus.ACTIVE,
    )
    item = {
        "offer_id": "offer-1",
        "marketplace_sku": "sku-1",
        "name": product.name,
        "dimensions": {
            "weight": 11999,
            "weight_unit": "g",
            "depth": 379,
            "width": 319,
            "height": 249,
            "dimension_unit": "mm",
        },
        "image_references": ["image-1", "image-2"],
        "video_references": ["video-1"],
        "media_rights_status": "unverified_external_reference",
        "source_evidence_id": source.id,
        "observed_at": "2026-07-24T00:00:00+00:00",
        "item_hash": "a" * 64,
    }
    binding = {
        "marketplace": "ozon",
        "store_ref": "store-main",
        "offer_id": "offer-1",
        "marketplace_sku": "sku-1",
        "product_id": product.id,
        "source_evidence_id": source.id,
        "item_hash": item["item_hash"],
        "bound_by": "operator-1",
        "bound_at": "2026-07-25T00:00:00+00:00",
    }
    catalog = CatalogStub(product=product, item=item, binding=binding)
    workspace = SupplierRfqWorkspace(
        marketplace_catalog=catalog,
        evidence=evidence,
        clock=lambda: datetime(2026, 7, 26, tzinfo=UTC),
    )
    return workspace, evidence, source, product


def request_payload():
    return {
        "store_ref": "store-main",
        "offer_id": "offer-1",
        "expected_item_hash": "a" * 64,
        "idempotency_key": "hoist-500kg-rfq-v1",
        "quantity_breaks": [100, 1, 10, 50, 10],
        "required_specifications": [
            {"name": "额定载重", "required_value": "500 kg"},
            {"name": "钢丝绳长度", "required_value": "7.6 m"},
            {"name": "电压与频率", "required_value": "220V±10%，50Hz"},
            {
                "name": "控制方式",
                "required_value": "手动、5m 有线控制、2.4GHz 无线遥控",
            },
        ],
        "destination": "河北省保定市指定集货仓",
        "response_due_at": "2026-07-30T18:00:00+08:00",
        "sample_required": True,
        "tax_invoice_required": True,
        "required_documents": [
            "营业执照与生产主体",
            "产品检测报告及认证文件",
            "中文和俄文说明书样本",
        ],
        "packaging_requirements": [
            "逐件说明包装清单、净重、毛重和外箱尺寸",
            "提供运输跌落保护和防潮方案",
        ],
        "operator_notes": "500 kg 必须是本次报价档位，不接受低载重引流价。",
        "confirmed": True,
        "created_by": "operator-1",
    }


def test_rfq_package_freezes_comparable_request_without_supplier_contact():
    workspace, evidence, source, product = make_workspace()

    result = workspace.create(**request_payload())

    record = result["evidence"]
    package = result["package"]
    assert result["idempotent"] is False
    assert record.source == RFQ_SOURCE
    assert record.grade == EvidenceGrade.C
    assert package["contract_version"] == RFQ_CONTRACT_VERSION
    assert package["product"]["id"] == product.id
    assert package["buyer_requirement"]["quantity_breaks"] == [1, 10, 50, 100]
    assert package["catalog_observation"]["package_weight_kg"] == "11.999"
    assert package["catalog_observation"]["package_dimensions_cm"] == {
        "length": "37.9",
        "width": "31.9",
        "height": "24.9",
    }
    assert "500 kg" in package["message_text"]
    assert "不代表下单" in package["message_text"]
    assert package["authority"] == {
        "status": "draft",
        "counts_as_supplier_quote": False,
        "formal_offer_eligible": False,
        "automatic_supplier_contact": False,
        "automatic_procurement": False,
        "automatic_payment": False,
        "automatic_listing": False,
        "automatic_marketplace_write": False,
    }
    assert evidence.target_evidence_ids(
        target_type="evidence",
        target_id=record.id,
        relationship="catalog_context_for",
    ) == [source.id]
    assert evidence.target_evidence_ids(
        target_type="product",
        target_id=product.id,
        relationship="rfq_package_for",
    ) == [record.id]
    assert workspace.list(product_id=product.id)[0]["package"] == package


def test_rfq_package_is_idempotent_and_changed_payload_requires_new_key():
    workspace, _, _, _ = make_workspace()
    first = workspace.create(**request_payload())
    replay = workspace.create(**request_payload())
    changed = request_payload()
    changed["quantity_breaks"] = [1, 20, 100]

    assert replay["evidence"].id == first["evidence"].id
    assert replay["idempotent"] is True
    with pytest.raises(ValueError, match="idempotency conflict"):
        workspace.create(**changed)


def test_rfq_package_rejects_stale_catalog_and_invalid_request_contract():
    workspace, _, _, _ = make_workspace()
    stale = request_payload()
    stale["expected_item_hash"] = "b" * 64
    with pytest.raises(ValueError, match="changed"):
        workspace.create(**stale)

    duplicate_spec = request_payload()
    duplicate_spec["required_specifications"].append(
        {"name": "额定载重", "required_value": "300 kg"}
    )
    with pytest.raises(ValueError, match="names must be unique"):
        workspace.create(**duplicate_spec)

    expired = request_payload()
    expired["response_due_at"] = "2026-07-25T00:00:00Z"
    with pytest.raises(ValueError, match="next 90 days"):
        workspace.create(**expired)


def test_rfq_package_product_handoff_is_strict():
    workspace, _, _, product = make_workspace()
    result = workspace.create(**request_payload())

    assert (
        workspace.require_for_product(
            result["evidence"].id,
            product_id=product.id,
        ).id
        == result["evidence"].id
    )
    with pytest.raises(ValueError, match="different product"):
        workspace.require_for_product(
            result["evidence"].id,
            product_id="prd-other",
        )
