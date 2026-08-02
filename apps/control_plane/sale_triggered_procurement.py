from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .facts import FactRecordRow
from .order_fact_semantics import (
    database_order_timestamp,
    is_explicit_currency,
    is_positive_decimal,
    is_positive_integer,
    order_timestamp,
)
from .ozon_contracts import CONTRACT_VERSION as OZON_CONTRACT_VERSION
from .sql_repository import ProductRow

PROCUREMENT_POLICY_VERSION = "sale-triggered-jit/1.1.0"
PROCUREMENT_TRIGGER_STATUSES = frozenset({"awaiting_packaging"})


class SaleTriggeredProcurementPolicy:
    """Project formal Ozon order facts into a no-write procurement review state."""

    def __init__(self, *, facts, evidence, repository, engine=None) -> None:
        self.facts = facts
        self.evidence = evidence
        self.repository = repository
        self.engine = engine

    @staticmethod
    def contract() -> dict[str, Any]:
        return {
            "version": PROCUREMENT_POLICY_VERSION,
            "mode": "sale_triggered_jit",
            "trigger_fact_type": "ozon_order",
            "trigger_statuses": sorted(PROCUREMENT_TRIGGER_STATUSES),
            "pre_order_purchase_quantity": 0,
            "supplier_order_created": False,
            "payment_created": False,
            "external_purchase_write": False,
            "automatic_procurement": False,
            "client_recalculation_allowed": False,
            "semantics": (
                "formal order may open an internal procurement review only"
            ),
        }

    def evaluate(
        self,
        *,
        store_ref: str,
        product_id: str | None,
        supply: dict[str, Any],
        economics: dict[str, Any],
        fresh: bool,
        as_of: datetime,
        scope_authority: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cutoff = order_timestamp(as_of)
        scope = self._scope(
            scope_authority,
            store_ref=store_ref,
        )
        result = {
            **self.contract(),
            "state": "waiting_for_ozon_order",
            "product_id": product_id,
            "store_ref": store_ref,
            "scope_mode": (
                "native_scoped" if scope is not None else "legacy_internal"
            ),
            "scope": scope,
            "formal_order_fact_count": 0,
            "current_order_fact_count": 0,
            "triggering_order_count": 0,
            "trigger_fact_id": None,
            "trigger_fact_ids": [],
            "trigger_evidence_id": None,
            "trigger_evidence_ids": [],
            "trigger_order_external_id": None,
            "trigger_order_external_ids": [],
            "recommended_review_quantity": 0,
            "source_gaps": [],
            "blockers": ["formal_ozon_order_fact_missing"],
            "owner": "procurement",
            "sla_hours": 4,
            "next_action": (
                "等待同店铺真实 Ozon 订单；出单前不向供应商下单或付款"
            ),
            "legacy_rows_inferred": False,
            "approval_created": False,
            "permit_created": False,
        }
        if not product_id:
            result["source_gaps"] = ["canonical_product_binding_missing"]
            return self._finish(result)
        expected_sku = self._product_sku(
            product_id=product_id,
            scope=scope,
            as_of=cutoff,
        )
        if expected_sku is None:
            result["source_gaps"] = [
                (
                    "scoped_canonical_product_missing"
                    if scope is not None
                    else "canonical_product_missing"
                )
            ]
            return self._finish(result)

        relevant = self._order_facts(
            product_id=product_id,
            scope=scope,
            as_of=cutoff,
        )
        result["formal_order_fact_count"] = len(relevant)
        if not relevant:
            return self._finish(result)

        current_by_external_id: dict[str, dict[str, Any]] = {}
        gaps: set[str] = set()
        for fact in relevant:
            payload = fact["payload"]
            external_id = str(payload.get("external_id") or "").strip()
            if not external_id:
                gaps.add("order_external_id_missing")
                continue
            previous = current_by_external_id.get(external_id)
            if previous is None or self._fact_order_key(fact) > (
                self._fact_order_key(previous)
            ):
                current_by_external_id[external_id] = fact
        current = sorted(
            current_by_external_id.values(),
            key=self._fact_order_key,
        )
        result["current_order_fact_count"] = len(current)
        accepted: list[dict[str, Any]] = []
        for fact in current:
            payload = fact["payload"]
            payload_store = str(payload.get("store_ref") or "").strip()
            if (
                (scope is None and payload_store != store_ref)
                or (
                    scope is not None
                    and payload_store
                    and payload_store != store_ref
                )
            ):
                gaps.add("order_store_scope_missing_or_mismatch")
                continue
            if payload.get("sku") != expected_sku:
                gaps.add("order_sku_mismatch")
                continue
            if (
                scope is not None
                and fact["contract_version"] != OZON_CONTRACT_VERSION
            ):
                gaps.add("order_contract_version_mismatch")
                continue
            try:
                verification = self.evidence.verify(fact["evidence_id"])
            except (KeyError, ValueError):
                gaps.add("order_evidence_invalid")
                continue
            if not verification.valid:
                gaps.add("order_evidence_invalid")
                continue
            if (
                scope is not None
                and verification.expected_sha256
                != fact["source_evidence_sha256"]
            ):
                gaps.add("order_evidence_invalid")
                continue
            status = str(payload.get("status") or "").strip().lower()
            if status not in PROCUREMENT_TRIGGER_STATUSES:
                gaps.add("order_status_not_procurement_trigger")
                continue
            if not is_positive_integer(payload.get("quantity")):
                gaps.add("order_quantity_invalid")
                continue
            if not is_positive_decimal(payload.get("gross_revenue")):
                gaps.add("order_revenue_not_positive")
                continue
            if not is_explicit_currency(payload.get("currency")):
                gaps.add("order_currency_missing_or_invalid")
                continue
            accepted.append(fact)

        if not accepted:
            result.update(
                {
                    "state": "blocked_order_authority",
                    "source_gaps": sorted(gaps),
                    "blockers": sorted(gaps),
                    "next_action": (
                        "修复正式订单的店铺/SKU/状态/Evidence 绑定；"
                        "不得用手工订单或页面观察触发采购"
                    ),
                }
            )
            return self._finish(result)

        trigger = max(accepted, key=self._fact_order_key)
        quantity = sum(
            int(Decimal(str(fact["payload"]["quantity"])))
            for fact in accepted
        )
        trigger_fact_ids = sorted(fact["id"] for fact in accepted)
        trigger_evidence_ids = sorted(
            {fact["evidence_id"] for fact in accepted}
        )
        trigger_order_external_ids = sorted(
            {
                str(fact["payload"]["external_id"])
                for fact in accepted
            }
        )
        supply_ready = bool(
            fresh
            and supply.get("checkout_verified") is True
            and supply.get("purchase_available") is True
        )
        downside = (economics.get("downside") or {}).get("cm3_cny")
        economics_ready = bool(
            economics.get("cost_evidence_complete") is True
            and downside is not None
            and Decimal(str(downside)) > 0
        )
        blockers = []
        if not supply_ready:
            blockers.append("current_supply_or_checkout_not_reverified")
        if not economics_ready:
            blockers.append("current_downside_profit_not_positive_or_complete")
        state = (
            "eligible_for_procurement_review"
            if not blockers
            else "order_received_cost_or_supply_escalation"
        )
        result.update(
            {
                "state": state,
                "triggering_order_count": len(accepted),
                "trigger_fact_id": trigger["id"],
                "trigger_fact_ids": trigger_fact_ids,
                "trigger_evidence_id": trigger["evidence_id"],
                "trigger_evidence_ids": trigger_evidence_ids,
                "trigger_order_external_id": trigger["payload"][
                    "external_id"
                ],
                "trigger_order_external_ids": trigger_order_external_ids,
                "recommended_review_quantity": quantity,
                "source_gaps": sorted(
                    gap
                    for gap in gaps
                    if gap != "order_status_not_procurement_trigger"
                ),
                "blockers": blockers,
                "next_action": (
                    "复核同款库存与成本后进入独立采购评审；"
                    "本状态不创建供应商订单或付款"
                    if not blockers
                    else "真实订单已到；立即人工处理供应/成本异常，禁止自动采购"
                ),
            }
        )
        return self._finish(result)

    def _product_sku(
        self,
        *,
        product_id: str,
        scope: dict[str, str] | None,
        as_of: datetime,
    ) -> str | None:
        if scope is None:
            try:
                return str(self.repository.get_product(product_id).sku)
            except KeyError:
                return None
        if self.engine is None:
            return None
        with Session(self.engine) as session:
            row = session.scalar(
                select(ProductRow).where(
                    ProductRow.id == product_id,
                    ProductRow.tenant_ref == scope["tenant_ref"],
                    ProductRow.entity_ref == scope["entity_ref"],
                    ProductRow.store_ref == scope["store_ref"],
                    ProductRow.scope_grant_authority_sha256
                    == scope["scope_grant_authority_sha256"],
                    ProductRow.scope_as_of <= as_of,
                    ProductRow.created_at <= as_of,
                )
            )
            return None if row is None else str(row.sku)

    def _order_facts(
        self,
        *,
        product_id: str,
        scope: dict[str, str] | None,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        if scope is None:
            return [
                self._legacy_fact(item)
                for item in self.facts.list(
                    fact_type="ozon_order",
                    limit=5000,
                )
                if item.product_id == product_id
                and item.resolution_status == "resolved"
                and order_timestamp(item.effective_at) <= as_of
                and order_timestamp(item.recorded_at) <= as_of
            ]
        if self.engine is None:
            return []
        query = (
            select(FactRecordRow)
            .where(
                FactRecordRow.tenant_ref == scope["tenant_ref"],
                FactRecordRow.entity_ref == scope["entity_ref"],
                FactRecordRow.store_ref == scope["store_ref"],
                FactRecordRow.scope_grant_authority_sha256
                == scope["scope_grant_authority_sha256"],
                FactRecordRow.fact_type == "ozon_order",
                FactRecordRow.product_id == product_id,
                FactRecordRow.resolution_status == "resolved",
                FactRecordRow.scope_as_of <= as_of,
                FactRecordRow.effective_at <= as_of,
                FactRecordRow.recorded_at <= as_of,
            )
            .order_by(
                FactRecordRow.effective_at,
                FactRecordRow.recorded_at,
                FactRecordRow.id,
            )
            .limit(5000)
        )
        with Session(self.engine) as session:
            return [
                self._scoped_fact(row)
                for row in session.scalars(query).all()
            ]

    @staticmethod
    def _legacy_fact(row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "payload": row.payload,
            "contract_version": getattr(
                row,
                "contract_version",
                "legacy",
            ),
            "effective_at": order_timestamp(row.effective_at),
            "recorded_at": order_timestamp(row.recorded_at),
            "evidence_id": row.evidence_id,
            "source_evidence_sha256": None,
        }

    @staticmethod
    def _scoped_fact(row: FactRecordRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "payload": row.payload_json,
            "contract_version": row.contract_version,
            "effective_at": database_order_timestamp(row.effective_at),
            "recorded_at": database_order_timestamp(row.recorded_at),
            "evidence_id": row.evidence_id,
            "source_evidence_sha256": row.source_evidence_sha256,
        }

    @staticmethod
    def _fact_order_key(row: dict[str, Any]) -> tuple[datetime, datetime, str]:
        return (
            order_timestamp(row["effective_at"]),
            order_timestamp(row["recorded_at"]),
            str(row["id"]),
        )

    @staticmethod
    def _scope(
        value: dict[str, Any] | None,
        *,
        store_ref: str,
    ) -> dict[str, str] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("procurement scope_authority must be an object")
        fields = (
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
        )
        scope = {
            field: str(value.get(field) or "").strip()
            for field in fields
        }
        if any(not scope[field] for field in fields):
            raise ValueError(
                "procurement scope_authority tuple is incomplete"
            )
        authority = scope["scope_grant_authority_sha256"]
        if len(authority) != 64 or any(
            character not in "0123456789abcdef" for character in authority
        ):
            raise ValueError(
                "procurement scope authority hash must be SHA-256"
            )
        if scope["store_ref"] != store_ref:
            raise ValueError("procurement scope store_ref mismatch")
        return scope

    @staticmethod
    def _finish(result: dict[str, Any]) -> dict[str, Any]:
        snapshot = {
            key: value
            for key, value in result.items()
            if key != "snapshot_sha256"
        }
        result["snapshot_sha256"] = hashlib.sha256(
            json.dumps(
                snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
        return result
