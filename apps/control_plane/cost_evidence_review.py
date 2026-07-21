from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .evidence import EvidenceGrade, EvidenceRecord, EvidenceService

ACTUAL_COST_AUTHORITIES: dict[str, frozenset[str]] = {
    "product_cost": frozenset({"supplier_invoice_payment"}),
    "domestic_logistics": frozenset({"domestic_carrier_final_bill"}),
    "international_logistics": frozenset({"crossborder_carrier_final_bill"}),
    "packaging": frozenset({"packaging_supplier_invoice_payment"}),
    "warehousing": frozenset({"warehouse_final_bill"}),
    "customs": frozenset({"customs_declaration_payment"}),
    "tax": frozenset({"tax_return_notice_payment"}),
    "last_mile": frozenset({"last_mile_final_bill"}),
    "platform_fee": frozenset({"ozon_transaction_settlement"}),
    "advertising": frozenset({"ozon_advertising_report"}),
    "return": frozenset({"ozon_return_refund_report"}),
    "fx": frozenset({"booked_conversion_rate_fee"}),
    "capital_cost": frozenset({"approved_finance_policy_and_actual_days"}),
    "aftersales": frozenset({"aftersales_case_or_service_bill"}),
    "loss": frozenset({"inventory_adjustment_or_inspection"}),
}

ACTUAL_COST_AUTHORITY_LABELS: dict[str, str] = {
    "supplier_invoice_payment": "供应商发票与付款记录",
    "domestic_carrier_final_bill": "国内承运商最终账单",
    "crossborder_carrier_final_bill": "跨境承运商最终账单",
    "packaging_supplier_invoice_payment": "包材供应商发票与付款记录",
    "warehouse_final_bill": "仓储服务最终账单",
    "customs_declaration_payment": "报关单与关税缴款记录",
    "tax_return_notice_payment": "纳税申报、通知与缴款记录",
    "last_mile_final_bill": "尾程履约最终账单",
    "ozon_transaction_settlement": "Ozon 交易结算原件",
    "ozon_advertising_report": "Ozon 广告账户报表",
    "ozon_return_refund_report": "Ozon 退货退款报表",
    "booked_conversion_rate_fee": "银行或支付机构实际换汇与费用记录",
    "approved_finance_policy_and_actual_days": "已批准资金政策与实际占用天数",
    "aftersales_case_or_service_bill": "售后案例或服务账单",
    "inventory_adjustment_or_inspection": "库存调整或验货记录",
}


class CostEvidenceAuthorityService:
    source = "cost_actual_authority_review"
    relationship = "cost_actual_authority_review"

    def __init__(self, *, evidence: EvidenceService) -> None:
        self.evidence = evidence

    def review(
        self,
        *,
        evidence_id: str,
        cost_type: str,
        authority_id: str,
        accepted: bool,
        authentic_original: bool,
        cost_scope_matches: bool,
        charging_party_matches: bool,
        amount_currency_period_matches: bool,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        cost_type = cost_type.strip()
        authority_id = authority_id.strip()
        rationale = rationale.strip()
        self._validate_scope(cost_type, authority_id)
        if not rationale:
            raise ValueError("Cost authority review requires a rationale")
        self.evidence.require_valid([evidence_id])
        original = self.evidence.get(evidence_id)
        if original.source == self.source:
            raise ValueError("Cost authority attestations cannot review other attestations")
        if original.created_by == reviewed_by:
            raise ValueError("Cost evidence uploader cannot review their own evidence")

        checks = {
            "authentic_original": authentic_original,
            "cost_scope_matches": cost_scope_matches,
            "charging_party_matches": charging_party_matches,
            "amount_currency_period_matches": amount_currency_period_matches,
        }
        if accepted and not all(checks.values()):
            raise ValueError("Accepted cost authority review requires all checks to pass")
        payload = {
            "decision": "accepted" if accepted else "rejected",
            "evidence_id": original.id,
            "evidence_sha256": original.sha256,
            "cost_type": cost_type,
            "authority_id": authority_id,
            "submitted_by": original.created_by,
            "reviewed_by": reviewed_by,
            "rationale": rationale,
            "checks": checks,
        }
        for prior in self._reviews(original, cost_type):
            if prior.created_by != reviewed_by:
                continue
            if all(prior.metadata.get(key) == value for key, value in payload.items()):
                return {"evidence": original, "review": prior, "idempotent": True}
            raise ValueError("Cost authority review is immutable and cannot be overwritten")

        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        review = self.evidence.capture(
            content=content,
            filename=f"{original.id}-{cost_type}-actual-authority-review.json",
            content_type="application/json",
            source=self.source,
            source_ref=f"cost-evidence://{original.id}/{cost_type}/authority/{reviewed_by}",
            grade=EvidenceGrade.A,
            effective_at=datetime.now(UTC).isoformat(),
            effective_until=None,
            created_by=reviewed_by,
            metadata={"evidence_role": "cost_actual_authority_attestation", **payload},
        )
        edge = self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=original.id,
            relationship=self.relationship,
            created_by=reviewed_by,
        )
        return {"evidence": original, "review": review, "lineage": edge, "idempotent": False}

    def status(self, evidence_id: str, cost_type: str) -> dict[str, Any]:
        cost_type = cost_type.strip()
        if cost_type not in ACTUAL_COST_AUTHORITIES:
            raise ValueError("Unsupported cost type")
        self.evidence.require_valid([evidence_id])
        original = self.evidence.get(evidence_id)
        reviews = self._reviews(original, cost_type)
        decisions = {item.metadata["decision"] for item in reviews}
        accepted_authorities = sorted(
            {
                item.metadata["authority_id"]
                for item in reviews
                if item.metadata["decision"] == "accepted"
            }
        )
        status = "rejected" if "rejected" in decisions else "accepted" if accepted_authorities else "pending"
        return {
            "evidence_id": original.id,
            "cost_type": cost_type,
            "status": status,
            "accepted_authorities": accepted_authorities,
            "review_ids": [item.id for item in reviews],
            "review_count": len(reviews),
        }

    def require_actual(self, evidence_id: str, cost_type: str) -> dict[str, Any]:
        state = self.status(evidence_id, cost_type)
        if state["status"] != "accepted":
            raise ValueError("Actual cost evidence requires an independent authority review")
        return state

    @staticmethod
    def _validate_scope(cost_type: str, authority_id: str) -> None:
        allowed = ACTUAL_COST_AUTHORITIES.get(cost_type)
        if allowed is None:
            raise ValueError("Unsupported cost type")
        if authority_id not in allowed:
            raise ValueError("Authority is not allowed for this cost type")

    def _reviews(self, original: EvidenceRecord, cost_type: str) -> list[EvidenceRecord]:
        review_ids = self.evidence.target_evidence_ids(
            target_type="evidence",
            target_id=original.id,
            relationship=self.relationship,
        )
        reviews: list[EvidenceRecord] = []
        for review_id in review_ids:
            try:
                self.evidence.require_valid([review_id])
                review = self.evidence.get(review_id)
            except (KeyError, RuntimeError, ValueError):
                continue
            metadata = review.metadata
            checks = metadata.get("checks")
            authority_id = metadata.get("authority_id")
            if (
                review.source == self.source
                and metadata.get("evidence_role") == "cost_actual_authority_attestation"
                and metadata.get("evidence_id") == original.id
                and metadata.get("evidence_sha256") == original.sha256
                and metadata.get("cost_type") == cost_type
                and authority_id in ACTUAL_COST_AUTHORITIES[cost_type]
                and metadata.get("submitted_by") == original.created_by
                and metadata.get("reviewed_by") == review.created_by
                and review.created_by != original.created_by
                and metadata.get("decision") in {"accepted", "rejected"}
                and isinstance(metadata.get("rationale"), str)
                and metadata["rationale"].strip()
                and isinstance(checks, dict)
                and set(checks)
                == {
                    "authentic_original",
                    "cost_scope_matches",
                    "charging_party_matches",
                    "amount_currency_period_matches",
                }
                and all(isinstance(value, bool) for value in checks.values())
                and (metadata["decision"] != "accepted" or all(checks.values()))
            ):
                reviews.append(review)
        return reviews
