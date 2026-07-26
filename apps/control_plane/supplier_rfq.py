from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .evidence import EvidenceGrade, EvidenceRecord

RFQ_CONTRACT_VERSION = "supplier-rfq-package-v1"
RFQ_SOURCE = "supplier_rfq_package"
RFQ_ROLE = "supplier_rfq_package"
RFQ_SOURCE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


def _required_text(value: Any, field: str, *, max_length: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"Supplier RFQ requires {field}")
    if len(normalized) > max_length:
        raise ValueError(f"Supplier RFQ {field} exceeds {max_length} characters")
    return normalized


def _optional_text(value: Any, field: str, *, max_length: int) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"Supplier RFQ {field} exceeds {max_length} characters")
    return normalized


def _text_list(
    values: list[str],
    field: str,
    *,
    min_items: int,
    max_items: int,
    item_max_length: int,
) -> list[str]:
    if len(values) > max_items:
        raise ValueError(
            f"Supplier RFQ {field} requires {min_items} to {max_items} unique items"
        )
    normalized = [
        _required_text(item, field, max_length=item_max_length)
        for item in values
    ]
    unique = list(dict.fromkeys(normalized))
    if len(unique) < min_items or len(unique) > max_items:
        raise ValueError(
            f"Supplier RFQ {field} requires {min_items} to {max_items} unique items"
        )
    return unique


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Supplier RFQ {field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Supplier RFQ {field} must include a timezone")
    return parsed.astimezone(UTC)


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _decimal_text(value: Any, divisor: Decimal) -> str | None:
    try:
        number = Decimal(str(value)) / divisor
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return format(number.normalize(), "f")


def _catalog_observation(item: dict[str, Any]) -> dict[str, Any]:
    dimensions = item.get("dimensions")
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    weight_divisor = {
        "g": Decimal("1000"),
        "kg": Decimal("1"),
    }.get(str(dimensions.get("weight_unit", "")).lower())
    dimension_divisor = {
        "mm": Decimal("10"),
        "cm": Decimal("1"),
    }.get(str(dimensions.get("dimension_unit", "")).lower())
    package_dimensions = None
    if dimension_divisor is not None:
        converted = {
            "length": _decimal_text(dimensions.get("depth"), dimension_divisor),
            "width": _decimal_text(dimensions.get("width"), dimension_divisor),
            "height": _decimal_text(dimensions.get("height"), dimension_divisor),
        }
        if all(value is not None for value in converted.values()):
            package_dimensions = converted
    return {
        "notice": "Seller 目录观察，仅作询价上下文；供应商必须重新确认",
        "catalog_title": item["name"],
        "marketplace_sku": item["marketplace_sku"],
        "observed_at": item["observed_at"],
        "source_evidence_id": item["source_evidence_id"],
        "item_hash": item["item_hash"],
        "package_weight_kg": (
            _decimal_text(dimensions.get("weight"), weight_divisor)
            if weight_divisor is not None
            else None
        ),
        "package_dimensions_cm": package_dimensions,
        "image_reference_count": len(item.get("image_references", [])),
        "video_reference_count": len(item.get("video_references", [])),
        "media_rights_status": item["media_rights_status"],
    }


class SupplierRfqWorkspace:
    """Build one immutable, comparable supplier request without sending it."""

    def __init__(
        self,
        *,
        marketplace_catalog,
        evidence,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.marketplace_catalog = marketplace_catalog
        self.evidence = evidence
        self.clock = clock or (lambda: datetime.now(UTC))

    def create(
        self,
        *,
        store_ref: str,
        offer_id: str,
        expected_item_hash: str,
        idempotency_key: str,
        quantity_breaks: list[int],
        required_specifications: list[dict[str, str]],
        destination: str,
        response_due_at: str,
        sample_required: bool,
        tax_invoice_required: bool,
        required_documents: list[str],
        packaging_requirements: list[str],
        operator_notes: str | None,
        confirmed: bool,
        created_by: str,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("Supplier RFQ creation requires explicit human confirmation")
        key = _required_text(
            idempotency_key,
            "idempotency_key",
            max_length=160,
        )
        if RFQ_SOURCE_REF_PATTERN.fullmatch(key) is None:
            raise ValueError("Supplier RFQ idempotency key contains unsupported characters")
        actor = _required_text(created_by, "created_by", max_length=160)
        destination_value = _required_text(
            destination,
            "destination",
            max_length=240,
        )
        notes = _optional_text(
            operator_notes,
            "operator_notes",
            max_length=2000,
        )
        if (
            not quantity_breaks
            or len(quantity_breaks) > 6
            or any(
                not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity < 1
                or quantity > 1_000_000
                for quantity in quantity_breaks
            )
        ):
            raise ValueError(
                "Supplier RFQ quantity breaks require 1 to 6 positive integers"
            )
        quantities = sorted(set(quantity_breaks))
        specifications = self._specifications(required_specifications)
        documents = _text_list(
            required_documents,
            "required_documents",
            min_items=1,
            max_items=20,
            item_max_length=240,
        )
        packaging = _text_list(
            packaging_requirements,
            "packaging_requirements",
            min_items=1,
            max_items=20,
            item_max_length=300,
        )
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("Supplier RFQ clock must include a timezone")
        now = now.astimezone(UTC)
        due = _timestamp(response_due_at, "response_due_at")
        if due <= now or due > now + timedelta(days=90):
            raise ValueError(
                "Supplier RFQ response due time must be within the next 90 days"
            )

        context = self.marketplace_catalog.require_bound_current_item(
            store_ref=store_ref,
            offer_id=offer_id,
            expected_item_hash=expected_item_hash,
        )
        product = context["product"]
        item = context["item"]
        binding = context["binding"]
        observation = _catalog_observation(item)
        response_checklist = self._response_checklist(specifications)
        buyer_requirement = {
            "quantity_breaks": quantities,
            "currency_requested": "CNY",
            "required_specifications": specifications,
            "destination": destination_value,
            "response_due_at": due.isoformat(),
            "sample_required": sample_required,
            "tax_invoice_required": tax_invoice_required,
            "required_documents": documents,
            "packaging_requirements": packaging,
            "operator_notes": notes,
        }
        message_text = self._message(
            key=key,
            product_name=product.name,
            buyer_requirement=buyer_requirement,
            response_checklist=response_checklist,
        )
        core = {
            "contract_version": RFQ_CONTRACT_VERSION,
            "product": {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
            },
            "listing": {
                "marketplace": "ozon",
                "store_ref": binding["store_ref"],
                "offer_id": binding["offer_id"],
                "marketplace_sku": binding["marketplace_sku"],
            },
            "catalog_observation": observation,
            "buyer_requirement": buyer_requirement,
            "message_text": message_text,
            "response_checklist": response_checklist,
            "unanswered_questions": response_checklist,
            "authority": {
                "status": "draft",
                "counts_as_supplier_quote": False,
                "formal_offer_eligible": False,
                "automatic_supplier_contact": False,
                "automatic_procurement": False,
                "automatic_payment": False,
                "automatic_listing": False,
                "automatic_marketplace_write": False,
            },
        }
        package = {**core, "package_hash": _canonical_hash(core)}
        source_ref = f"supplier-rfq://{product.id}/{key}"
        existing = self._find_source_ref(source_ref)
        if existing is not None:
            result = self.get(existing.id)
            if result["package"]["package_hash"] != package["package_hash"]:
                raise ValueError(
                    "Supplier RFQ idempotency conflict; changed request requires a new key"
                )
            self._link(
                package_record=existing,
                source_evidence_id=item["source_evidence_id"],
                product_id=product.id,
                created_by=actor,
            )
            return {**result, "idempotent": True}

        content = json.dumps(
            package,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        record = self.evidence.capture(
            content=content,
            filename=f"{key}-supplier-rfq-package.json",
            content_type="application/json",
            source=RFQ_SOURCE,
            source_ref=source_ref,
            grade=EvidenceGrade.C,
            effective_at=now.isoformat(),
            effective_until=None,
            created_by=actor,
            metadata={
                "evidence_role": RFQ_ROLE,
                "contract_version": RFQ_CONTRACT_VERSION,
                "product_id": product.id,
                "store_ref": binding["store_ref"],
                "offer_id": binding["offer_id"],
                "marketplace_sku": binding["marketplace_sku"],
                "source_evidence_id": item["source_evidence_id"],
                "source_item_hash": item["item_hash"],
                "idempotency_key": key,
                "package_hash": package["package_hash"],
                "status": "draft",
                "retention_class": "operational",
                "legal_hold": False,
                "counts_as_supplier_quote": False,
                "formal_offer_eligible": False,
                "automatic_supplier_contact": False,
                "automatic_procurement": False,
                "automatic_payment": False,
                "automatic_listing": False,
                "automatic_marketplace_write": False,
            },
        )
        self._link(
            package_record=record,
            source_evidence_id=item["source_evidence_id"],
            product_id=product.id,
            created_by=actor,
        )
        return {
            "evidence": record,
            "package": package,
            "idempotent": False,
        }

    def get(self, evidence_id: str) -> dict[str, Any]:
        self.evidence.require_valid([evidence_id])
        content, record = self.evidence.content(evidence_id)
        self._require_record(record)
        try:
            package = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Supplier RFQ package content is not valid JSON") from exc
        if not isinstance(package, dict):
            raise ValueError("Supplier RFQ package content must be an object")
        package_hash = package.get("package_hash")
        core = dict(package)
        core.pop("package_hash", None)
        if (
            package.get("contract_version") != RFQ_CONTRACT_VERSION
            or not isinstance(package_hash, str)
            or package_hash != _canonical_hash(core)
            or record.metadata.get("package_hash") != package_hash
            or record.metadata.get("product_id")
            != package.get("product", {}).get("id")
        ):
            raise ValueError("Supplier RFQ package contract or hash is invalid")
        return {
            "evidence": record,
            "package": package,
        }

    def list(
        self,
        *,
        product_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise ValueError("Supplier RFQ list limit must be 1 to 500")
        records = [
            record
            for record in self.evidence.list_by_source(
                RFQ_SOURCE,
                limit=2000 if product_id else limit,
            )
            if record.metadata.get("evidence_role") == RFQ_ROLE
            and (
                product_id is None
                or record.metadata.get("product_id") == product_id
            )
        ][:limit]
        return [self.get(record.id) for record in records]

    def require_for_product(
        self,
        evidence_id: str,
        *,
        product_id: str,
    ) -> EvidenceRecord:
        result = self.get(evidence_id)
        record = result["evidence"]
        if record.metadata["product_id"] != product_id:
            raise ValueError("Supplier RFQ package belongs to a different product")
        return record

    @staticmethod
    def _specifications(
        values: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not values or len(values) > 40:
            raise ValueError(
                "Supplier RFQ requires 1 to 40 specification requirements"
            )
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in values:
            if not isinstance(item, dict):
                raise ValueError("Supplier RFQ specifications must be objects")
            name = _required_text(
                item.get("name"),
                "specification name",
                max_length=100,
            )
            value = _required_text(
                item.get("required_value"),
                "specification required_value",
                max_length=500,
            )
            identity = name.casefold()
            if identity in seen:
                raise ValueError("Supplier RFQ specification names must be unique")
            seen.add(identity)
            normalized.append(
                {
                    "name": name,
                    "required_value": value,
                    "supplier_must_confirm": True,
                }
            )
        return sorted(normalized, key=lambda item: item["name"].casefold())

    @staticmethod
    def _response_checklist(
        specifications: list[dict[str, Any]],
    ) -> list[str]:
        return [
            "供应商公司全称、1688 店铺/主体和联系人",
            "逐项确认冻结规格；不符项必须写明差异",
            f"逐项规格：{'、'.join(item['name'] for item in specifications)}",
            "各数量阶梯含税/未税单价、币种、MOQ 和报价有效期",
            "样品价格、样品交期、批量交期和日产能",
            "单件净重、包装后毛重及外箱长宽高",
            "发往指定国内地址的物流费用与交付条件",
            "包装清单、备件、说明书、标签和条码方案",
            "营业执照、产地、检测/认证文件及可验证编号",
            "质保、验货标准、不良品和售后处理条款",
        ]

    @staticmethod
    def _message(
        *,
        key: str,
        product_name: str,
        buyer_requirement: dict[str, Any],
        response_checklist: list[str],
    ) -> str:
        specifications = "\n".join(
            f"- {item['name']}：{item['required_value']}（请确认/写明差异）"
            for item in buyer_requirement["required_specifications"]
        )
        documents = "\n".join(
            f"- {item}" for item in buyer_requirement["required_documents"]
        )
        packaging = "\n".join(
            f"- {item}" for item in buyer_requirement["packaging_requirements"]
        )
        checklist = "\n".join(
            f"{index}. {item}"
            for index, item in enumerate(response_checklist, start=1)
        )
        sample = "需要" if buyer_requirement["sample_required"] else "暂不要求"
        invoice = (
            "需要可核验的含税发票方案"
            if buyer_requirement["tax_invoice_required"]
            else "请分别说明含税与未税条件"
        )
        notes = buyer_requirement["operator_notes"] or "无"
        return (
            "您好，我们正在为俄罗斯 Ozon 店铺采购以下产品，请按同一冻结规格提供书面报价。\n\n"
            f"询价编号：{key}\n"
            f"产品上下文：{product_name}\n"
            f"报价数量阶梯：{', '.join(str(item) for item in buyer_requirement['quantity_breaks'])} 件\n"
            f"国内交付目的地：{buyer_requirement['destination']}\n"
            f"回复截止时间：{buyer_requirement['response_due_at']}\n"
            f"样品要求：{sample}\n"
            f"发票要求：{invoice}\n\n"
            "一、必须逐项确认的规格\n"
            f"{specifications}\n\n"
            "二、包装要求\n"
            f"{packaging}\n\n"
            "三、必须提供或说明的文件\n"
            f"{documents}\n\n"
            "四、请按以下清单完整回复\n"
            f"{checklist}\n\n"
            f"补充说明：{notes}\n\n"
            "本消息仅为询价，不代表下单、付款、独家承诺或采购批准。"
        )

    def _find_source_ref(self, source_ref: str) -> EvidenceRecord | None:
        return self.evidence.find_by_source_ref(
            source=RFQ_SOURCE,
            source_ref=source_ref,
        )

    @staticmethod
    def _require_record(record: EvidenceRecord) -> None:
        metadata = record.metadata
        if (
            record.source != RFQ_SOURCE
            or record.grade != EvidenceGrade.C
            or metadata.get("evidence_role") != RFQ_ROLE
            or metadata.get("contract_version") != RFQ_CONTRACT_VERSION
            or metadata.get("status") != "draft"
            or metadata.get("counts_as_supplier_quote") is not False
            or metadata.get("formal_offer_eligible") is not False
            or metadata.get("automatic_supplier_contact") is not False
        ):
            raise ValueError("Evidence is not a governed supplier RFQ package")

    def _link(
        self,
        *,
        package_record: EvidenceRecord,
        source_evidence_id: str,
        product_id: str,
        created_by: str,
    ) -> None:
        self.evidence.link(
            evidence_id=source_evidence_id,
            target_type="evidence",
            target_id=package_record.id,
            relationship="catalog_context_for",
            created_by=created_by,
        )
        self.evidence.link(
            evidence_id=package_record.id,
            target_type="product",
            target_id=product_id,
            relationship="rfq_package_for",
            created_by=created_by,
        )
