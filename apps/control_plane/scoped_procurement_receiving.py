from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import ApprovalStatus
from .procurement import (
    ALLOWED_TRANSITIONS,
    EVENT_STATE,
    REQUIRED_EVENT_FACTS,
)
from .security import Principal
from .sql_repository import ProductRow


class ScopedProcurementReceivingWorkspace:
    """Project exact-scope procurement and receiving without creating truth."""

    CONTRACT_ID = (
        "kjds-native-exact-scope-procurement-receiving-workspace-v1"
    )
    SOURCE_CONTRACT_ID = "kjds-scoped-procurement-read-source-v1"
    ARTIFACT_CONTRACT_ID = "kjds-procurement-steward-artifact-v1"
    STAGES = frozenset(
        {
            "approved_to_order",
            "order_confirmed",
            "shipped",
            "received",
            "inspected",
            "golden_sample_approved",
            "sample_rejected",
            "rework_required",
            "cancelled",
            "blocked",
        }
    )

    def __init__(
        self,
        *,
        engine,
        procurement,
        repository,
        sourcing_store,
        evidence,
        scoped_evidence,
    ) -> None:
        self.engine = engine
        self.procurement = procurement
        self.repository = repository
        self.sourcing_store = sourcing_store
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence

    def project(
        self,
        *,
        store_ref: str = "ozon-primary",
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        as_of: str | None = None,
        query: str | None = None,
        stage: str | None = None,
        page_size: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            store_ref=store_ref,
            principal=principal,
            entity_scope=entity_scope,
            as_of=as_of,
        )
        normalized_query = self._query(query)
        normalized_stage = self._stage(stage)
        normalized_page_size = self._page_size(page_size)
        normalized_cursor = str(cursor or "").strip() or None
        filters = {
            "query": normalized_query or None,
            "stage": normalized_stage,
        }
        if context["status"] != "ready":
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status=context["status"],
                reason=context["reason"],
            )

        source = self.procurement.read_scoped_sources(
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            store_ref=context["scope"]["store_ref"],
            scope_grant_authority_sha256=context["scope"][
                "scope_grant_authority_sha256"
            ],
            as_of=context["cutoff"].isoformat(),
        )
        source_issues = self._source_issues(source, context=context)
        if source_issues:
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status="blocked",
                reason=source_issues[0],
                extra_gaps=source_issues[1:],
                scoped_input_read=True,
                source_snapshot_sha256=source.get("snapshot_sha256"),
            )

        orders = source["orders"]
        products = self._read_products(
            product_ids={
                str(item.get("product_id") or "").strip()
                for item in orders
                if item.get("product_id")
            },
            context=context,
        )
        product_issues = self._product_source_issues(
            products,
            context=context,
        )
        if product_issues:
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status="blocked",
                reason=product_issues[0],
                extra_gaps=product_issues[1:],
                scoped_input_read=True,
                source_snapshot_sha256=self._hash(
                    {
                        "procurement": source.get("snapshot_sha256"),
                        "products": products.get("snapshot_sha256"),
                    }
                ),
            )

        products_by_id = {
            item["id"]: item for item in products["items"]
        }
        events_by_order: dict[str, list[dict[str, Any]]] = defaultdict(
            list
        )
        unknown_event_count = 0
        order_ids = {str(item.get("id")) for item in orders}
        for event in source["events"]:
            order_id = str(event.get("purchase_order_id") or "")
            if order_id not in order_ids:
                unknown_event_count += 1
                continue
            events_by_order[order_id].append(event)

        excluded_reasons: Counter[str] = Counter()
        if unknown_event_count:
            excluded_reasons["procurement_event_order_scope_conflict"] += (
                unknown_event_count
            )
        rows: list[dict[str, Any]] = []
        evidence_cache: dict[tuple[str, str], list[str]] = {}
        for order in orders:
            row, issues = self._project_order(
                order=order,
                events=events_by_order.get(str(order.get("id")), []),
                product=products_by_id.get(
                    str(order.get("product_id") or "")
                ),
                context=context,
                evidence_cache=evidence_cache,
            )
            if issues:
                excluded_reasons.update(set(issues))
                continue
            if row is None:
                excluded_reasons["procurement_projection_failed_closed"] += 1
                continue
            if normalized_query and not self._matches_query(
                row,
                normalized_query,
            ):
                continue
            if normalized_stage and row["stage"] != normalized_stage:
                continue
            rows.append(row)

        rows.sort(
            key=lambda item: (
                item["created_at"],
                item["purchase_order_id"],
            ),
            reverse=True,
        )
        counts = self._counts(rows)
        page, next_cursor = self._paginate(
            rows,
            page_size=normalized_page_size,
            cursor=normalized_cursor,
        )
        source_gaps: list[str] = []
        if excluded_reasons:
            source_gaps.extend(sorted(excluded_reasons))
        if not orders:
            source_gaps.append(
                "scoped_procurement_order_evidence_missing"
            )
        source_gaps.extend(
            [
                "supplier_invoice_authority_not_implemented",
                "supplier_payment_authority_not_implemented",
            ]
        )
        status = (
            "no_data"
            if not orders
            else "blocked"
            if excluded_reasons and not rows
            else "partial"
            if excluded_reasons
            else "ready"
        )
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=normalized_page_size,
            total_filtered=len(rows),
            next_cursor=next_cursor,
            orders=page,
            total_counts=counts,
            excluded={
                "count": sum(excluded_reasons.values()),
                "reason_counts": dict(sorted(excluded_reasons.items())),
                "business_values_exposed": False,
            },
            source_gaps=source_gaps,
            source_snapshot_sha256=self._hash(
                {
                    "procurement": source.get("snapshot_sha256"),
                    "products": products.get("snapshot_sha256"),
                }
            ),
        )

    def _project_order(
        self,
        *,
        order: dict[str, Any],
        events: list[dict[str, Any]],
        product: dict[str, Any] | None,
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        issues = self._order_issues(
            order,
            product=product,
            context=context,
            evidence_cache=evidence_cache,
        )
        approval = None
        offer = None
        scenario = None
        if not issues:
            try:
                approval = self.repository.get_approval_at(
                    str(order["approval_id"]),
                    as_of=context["cutoff"],
                )
                offer = self.sourcing_store.get_offer(
                    str(order["offer_id"])
                )
                scenario = self.sourcing_store.get_scenario(
                    str(order["scenario_id"])
                )
            except (KeyError, RuntimeError, ValueError):
                issues.append("procurement_decision_basis_missing")
        if not issues:
            issues.extend(
                self._basis_issues(
                    order=order,
                    approval=approval,
                    offer=offer,
                    scenario=scenario,
                    context=context,
                    evidence_cache=evidence_cache,
                )
            )

        timeline, stage, timeline_issues = self._project_timeline(
            events=events,
            order=order,
            context=context,
            evidence_cache=evidence_cache,
        )
        issues.extend(timeline_issues)
        if issues:
            return None, sorted(set(issues))

        quantity = int(order["quantity"])
        unit_price = self._decimal(
            order["unit_price"],
            "unit_price",
            positive=True,
        )
        order_value = unit_price * quantity
        latest_event = timeline[-1] if timeline else None
        receipt = self._receipt_summary(
            timeline=timeline,
            quantity=quantity,
        )
        return (
            {
                "purchase_order_id": str(order["id"]),
                "product": product,
                "supplier_ref": str(order["supplier_ref"]),
                "quantity": quantity,
                "currency": str(order["currency"]).upper(),
                "unit_price": self._decimal_text(unit_price),
                "order_value": self._decimal_text(order_value),
                "created_at": self._timestamp(
                    order["created_at"],
                    "created_at",
                ).isoformat(),
                "stage": stage,
                "latest_effective_at": (
                    latest_event["effective_at"]
                    if latest_event
                    else str(order["created_at"])
                ),
                "next_events": sorted(ALLOWED_TRANSITIONS[stage]),
                "timeline": timeline,
                "receipt": receipt,
                "decision_basis": {
                    "approval_id": str(order["approval_id"]),
                    "approval_status": approval.status.value,
                    "independent_approval": (
                        approval.requested_by != approval.decided_by
                    ),
                    "offer_id": str(order["offer_id"]),
                    "scenario_id": str(order["scenario_id"]),
                    "expected_cm3_cny": self._decimal_text(
                        scenario.cm3_cny
                    ),
                    "cost_evidence_complete": scenario.cost_complete,
                    "authority_evidence_id": str(
                        order["authority_evidence_id"]
                    ),
                },
                "financial_authority": self._financial_authority(),
                "owner": self._owner(stage),
                "sla": self._sla(stage),
                "next": self._next(stage),
                "next_workspace": "/procurement",
                "readiness": {
                    "procurement_basis_verified": True,
                    "receiving_timeline_verified": True,
                    "ap_invoice_verified": False,
                    "supplier_payment_verified": False,
                },
            },
            [],
        )

    def _order_issues(
        self,
        order: dict[str, Any],
        *,
        product: dict[str, Any] | None,
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> list[str]:
        issues: list[str] = []
        required = (
            "id",
            "approval_id",
            "product_id",
            "offer_id",
            "scenario_id",
            "supplier_ref",
            "authority_evidence_id",
        )
        if any(not str(order.get(field) or "").strip() for field in required):
            issues.append("procurement_order_identity_incomplete")
        try:
            quantity = int(order.get("quantity"))
            if quantity < 1:
                raise ValueError
        except (TypeError, ValueError):
            issues.append("procurement_order_quantity_invalid")
        try:
            self._decimal(
                order.get("unit_price"),
                "unit_price",
                positive=True,
            )
        except ValueError:
            issues.append("procurement_order_unit_price_invalid")
        if not self._currency(order.get("currency")):
            issues.append("procurement_order_currency_invalid")
        issues.extend(
            self._temporal_issues(
                order,
                fields=("created_at", "scope_as_of"),
                context=context,
                prefix="procurement_order",
            )
        )
        issues.extend(
            self._evidence_issues(
                evidence_id=order.get("authority_evidence_id"),
                source_sha256=order.get("source_evidence_sha256"),
                context=context,
                prefix="procurement_order",
                evidence_cache=evidence_cache,
            )
        )
        if product is None:
            issues.append("procurement_product_scope_missing")
        elif product.get("id") != order.get("product_id"):
            issues.append("procurement_product_scope_conflict")
        return sorted(set(issues))

    def _basis_issues(
        self,
        *,
        order: dict[str, Any],
        approval,
        offer,
        scenario,
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> list[str]:
        issues: list[str] = []
        payload = approval.payload if isinstance(approval.payload, dict) else {}
        expected_payload = {
            "product_id": order["product_id"],
            "offer_id": order["offer_id"],
            "scenario_id": order["scenario_id"],
            "quantity": order["quantity"],
        }
        if (
            approval.status != ApprovalStatus.APPROVED
            or approval.action != "procurement.place_order"
            or approval.resource_type != "profit_scenario"
            or approval.resource_id != order["scenario_id"]
        ):
            issues.append("procurement_approval_invalid")
        if not approval.decided_by or approval.requested_by == approval.decided_by:
            issues.append("procurement_approval_independence_invalid")
        for field, expected in expected_payload.items():
            if str(payload.get(field)) != str(expected):
                issues.append(
                    f"procurement_approval_{field}_conflict"
                )
        try:
            approval_created = self._timestamp(
                approval.created_at,
                "approval.created_at",
            )
            if approval_created > context["cutoff"]:
                issues.append("procurement_approval_future")
        except ValueError:
            issues.append("procurement_approval_timestamp_invalid")

        if (
            offer.id != order["offer_id"]
            or offer.product_id != order["product_id"]
            or offer.supplier_ref != order["supplier_ref"]
            or offer.currency != str(order["currency"]).upper()
            or offer.unit_price
            != self._decimal(
                order["unit_price"],
                "unit_price",
                positive=True,
            )
        ):
            issues.append("procurement_offer_basis_conflict")
        if int(order["quantity"]) < offer.min_order_quantity:
            issues.append("procurement_offer_moq_conflict")
        try:
            if (
                self._timestamp(offer.captured_at, "offer.captured_at")
                > context["cutoff"]
            ):
                issues.append("procurement_offer_future")
        except ValueError:
            issues.append("procurement_offer_timestamp_invalid")
        issues.extend(
            self._evidence_issues(
                evidence_id=offer.evidence_ref,
                source_sha256=None,
                context=context,
                prefix="procurement_offer",
                evidence_cache=evidence_cache,
                accept_record_hash=True,
            )
        )

        if scenario.id != order["scenario_id"] or scenario.offer_id != offer.id:
            issues.append("procurement_profit_scenario_conflict")
        if scenario.cm3_cny <= 0:
            issues.append("procurement_profit_scenario_not_positive")
        if not scenario.cost_complete:
            issues.append("procurement_profit_scenario_cost_incomplete")
        try:
            if (
                self._timestamp(
                    scenario.created_at,
                    "scenario.created_at",
                )
                > context["cutoff"]
            ):
                issues.append("procurement_profit_scenario_future")
        except ValueError:
            issues.append("procurement_profit_scenario_timestamp_invalid")
        scenario_evidence = [
            *scenario.evidence,
            *scenario.cost_evidence.values(),
        ]
        if not scenario_evidence:
            issues.append("procurement_profit_scenario_evidence_missing")
        for evidence_id in sorted(set(scenario_evidence)):
            issues.extend(
                self._evidence_issues(
                    evidence_id=evidence_id,
                    source_sha256=None,
                    context=context,
                    prefix="procurement_profit_scenario",
                    evidence_cache=evidence_cache,
                    accept_record_hash=True,
                )
            )
        return sorted(set(issues))

    def _project_timeline(
        self,
        *,
        events: list[dict[str, Any]],
        order: dict[str, Any],
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> tuple[list[dict[str, Any]], str, list[str]]:
        timeline: list[dict[str, Any]] = []
        issues: list[str] = []
        state = "approved_to_order"
        ordered = sorted(
            events,
            key=lambda item: (
                int(item.get("sequence") or 0),
                str(item.get("effective_at") or ""),
                str(item.get("id") or ""),
            ),
        )
        seen_sequences: set[int] = set()
        seen_authorities: set[tuple[str, str]] = set()
        received_quantity: int | None = None
        damaged_quantity: int | None = None
        for position, event in enumerate(ordered, start=1):
            try:
                sequence = int(event.get("sequence"))
            except (TypeError, ValueError):
                issues.append("procurement_event_sequence_invalid")
                continue
            if sequence != position or sequence in seen_sequences:
                issues.append("procurement_event_sequence_conflict")
            seen_sequences.add(sequence)
            event_type = str(event.get("event_type") or "").strip()
            evidence_id = str(event.get("evidence_id") or "").strip()
            authority_key = (event_type, evidence_id)
            if authority_key in seen_authorities:
                issues.append("procurement_event_authority_duplicate")
            seen_authorities.add(authority_key)
            if (
                event_type not in EVENT_STATE
                or event_type not in ALLOWED_TRANSITIONS.get(state, set())
            ):
                issues.append("procurement_event_transition_invalid")
            facts = event.get("facts")
            if not isinstance(facts, dict):
                issues.append("procurement_event_facts_invalid")
                facts = {}
            missing = sorted(
                field
                for field in REQUIRED_EVENT_FACTS.get(event_type, set())
                if facts.get(field) in (None, "")
            )
            if missing:
                issues.append("procurement_event_required_facts_missing")
            issues.extend(
                self._temporal_issues(
                    event,
                    fields=(
                        "effective_at",
                        "recorded_at",
                        "scope_as_of",
                    ),
                    context=context,
                    prefix="procurement_event",
                )
            )
            issues.extend(
                self._evidence_issues(
                    evidence_id=evidence_id,
                    source_sha256=event.get(
                        "source_evidence_sha256"
                    ),
                    context=context,
                    prefix="procurement_event",
                    evidence_cache=evidence_cache,
                )
            )
            quantity_issues, received_quantity, damaged_quantity = (
                self._quantity_issues(
                    event_type=event_type,
                    facts=facts,
                    ordered_quantity=int(order["quantity"]),
                    received_quantity=received_quantity,
                    damaged_quantity=damaged_quantity,
                )
            )
            issues.extend(quantity_issues)
            if event_type in EVENT_STATE:
                state = EVENT_STATE[event_type]
            timeline.append(
                {
                    "event_id": str(event.get("id") or ""),
                    "sequence": sequence,
                    "event_type": event_type,
                    "stage": state,
                    "effective_at": str(
                        event.get("effective_at") or ""
                    ),
                    "recorded_at": str(
                        event.get("recorded_at") or ""
                    ),
                    "facts": facts,
                    "evidence_id": evidence_id,
                }
            )
        return timeline, state, sorted(set(issues))

    @staticmethod
    def _quantity_issues(
        *,
        event_type: str,
        facts: dict[str, Any],
        ordered_quantity: int,
        received_quantity: int | None,
        damaged_quantity: int | None,
    ) -> tuple[list[str], int | None, int | None]:
        issues: list[str] = []
        try:
            if event_type == "received":
                received_quantity = int(facts["received_quantity"])
                damaged_quantity = int(facts["damaged_quantity"])
                if (
                    received_quantity < 0
                    or received_quantity > ordered_quantity
                    or damaged_quantity < 0
                    or damaged_quantity > received_quantity
                ):
                    issues.append(
                        "procurement_receipt_quantity_not_conserved"
                    )
            elif event_type == "inspection_completed":
                inspected = int(facts["inspected_quantity"])
                passed = int(facts["passed_quantity"])
                defects = int(facts["defect_count"])
                if (
                    received_quantity is None
                    or damaged_quantity is None
                    or inspected < 1
                    or inspected > received_quantity
                    or passed < 0
                    or defects < 0
                    or passed + defects != inspected
                ):
                    issues.append(
                        "procurement_inspection_quantity_not_conserved"
                    )
        except (KeyError, TypeError, ValueError):
            issues.append("procurement_event_quantity_invalid")
        return issues, received_quantity, damaged_quantity

    def _evidence_issues(
        self,
        *,
        evidence_id: Any,
        source_sha256: Any,
        context: dict[str, Any],
        prefix: str,
        evidence_cache: dict[tuple[str, str], list[str]],
        accept_record_hash: bool = False,
    ) -> list[str]:
        evidence_ref = str(evidence_id or "").strip()
        source_hash = str(source_sha256 or "").strip().lower()
        cache_key = (
            evidence_ref,
            source_hash if not accept_record_hash else "*",
        )
        if cache_key in evidence_cache:
            return evidence_cache[cache_key]
        issues: list[str] = []
        if not evidence_ref or (
            not accept_record_hash and not self._sha256(source_hash)
        ):
            issues.append(f"{prefix}_evidence_authority_missing")
        if issues:
            evidence_cache[cache_key] = issues
            return issues
        try:
            verification = self.evidence.verify(evidence_ref)
            if (
                not verification.valid
                or (
                    not accept_record_hash
                    and verification.expected_sha256 != source_hash
                )
            ):
                issues.append(f"{prefix}_evidence_invalid")
            projection = self.scoped_evidence.project_targets(
                evidence_ids=[evidence_ref],
                principal=context["principal"],
                entity_scope=context["entity_scope"],
                store_ref=context["scope"]["store_ref"],
                as_of=context["cutoff"],
            )
            target = next(
                (
                    item
                    for item in projection.get("records", [])
                    if item.get("id") == evidence_ref
                ),
                None,
            )
            if (
                projection.get("status") != "ready"
                or target is None
                or target.get("status") != "ready"
            ):
                issues.append(f"{prefix}_evidence_scope_invalid")
        except (KeyError, RuntimeError, ValueError):
            issues.append(f"{prefix}_evidence_invalid")
        result = sorted(set(issues))
        evidence_cache[cache_key] = result
        return result

    def _read_products(
        self,
        *,
        product_ids: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if not product_ids:
            payload = {
                "contract_id": "kjds-scoped-procurement-products-v1",
                "as_of": context["cutoff"].isoformat(),
                "scope": context["scope"],
                "items": [],
            }
            payload["snapshot_sha256"] = self._hash(payload)
            return payload
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ProductRow)
                    .where(
                        ProductRow.id.in_(sorted(product_ids)),
                        ProductRow.tenant_ref
                        == context["scope"]["tenant_ref"],
                        ProductRow.entity_ref
                        == context["scope"]["entity_ref"],
                        ProductRow.store_ref
                        == context["scope"]["store_ref"],
                        ProductRow.scope_grant_authority_sha256
                        == context["scope"][
                            "scope_grant_authority_sha256"
                        ],
                        ProductRow.created_at <= context["cutoff"],
                        ProductRow.scope_as_of <= context["cutoff"],
                    )
                    .order_by(ProductRow.created_at, ProductRow.id)
                ).all()
            )
        payload = {
            "contract_id": "kjds-scoped-procurement-products-v1",
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "items": [
                {
                    "id": row.id,
                    "sku": row.sku,
                    "name": row.name,
                    "market": row.market,
                    "channel": row.channel,
                    "status": row.status,
                    "created_at": self._aware(
                        row.created_at
                    ).isoformat(),
                    "scope_as_of": self._aware(
                        row.scope_as_of
                    ).isoformat(),
                }
                for row in rows
            ],
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _source_issues(
        self,
        source: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if source.get("contract_id") != self.SOURCE_CONTRACT_ID:
            issues.append("procurement_source_contract_conflict")
        if source.get("as_of") != context["cutoff"].isoformat():
            issues.append("procurement_source_as_of_conflict")
        source_scope = source.get("scope") or {}
        for field in (
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
        ):
            if source_scope.get(field) != context["scope"].get(field):
                issues.append(f"procurement_source_{field}_conflict")
        if not isinstance(source.get("orders"), list) or not isinstance(
            source.get("events"),
            list,
        ):
            issues.append("procurement_source_payload_invalid")
        if any((source.get("truncated") or {}).values()):
            issues.append("procurement_source_truncated")
        if not self._valid_snapshot(source):
            issues.append("procurement_source_snapshot_hash_drift")
        return sorted(set(issues))

    def _product_source_issues(
        self,
        products: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if products.get("as_of") != context["cutoff"].isoformat():
            issues.append("procurement_product_source_as_of_conflict")
        if products.get("scope") != context["scope"]:
            issues.append("procurement_product_source_scope_conflict")
        if not self._valid_snapshot(products):
            issues.append("procurement_product_source_hash_drift")
        return issues

    def _payload(
        self,
        *,
        context: dict[str, Any],
        status: str,
        filters: dict[str, Any],
        page_size: int,
        total_filtered: int,
        next_cursor: str | None,
        orders: list[dict[str, Any]],
        total_counts: dict[str, int],
        excluded: dict[str, Any],
        source_gaps: list[str],
        source_snapshot_sha256: str | None,
        scoped_input_read: bool = True,
    ) -> dict[str, Any]:
        gaps = sorted(set(source_gaps))
        core = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "filters": filters,
            "counts": {
                **total_counts,
                "filtered": total_filtered,
                "page": len(orders),
            },
            "pagination": {
                "page_size": page_size,
                "next_cursor": next_cursor,
            },
            "orders": orders,
            "excluded": excluded,
            "source_gaps": gaps,
            "blockers": self._blockers(gaps),
            "financial_authority": self._financial_authority(),
            "owner": "procurement-control",
            "sla": "before supplier order, receiving acceptance or payment",
            "next": (
                "Bind exact scoped procurement and receiving Evidence; "
                "implement separate AP invoice and supplier payment authority."
            ),
            "next_workspace": "/procurement",
            "upstream": {
                "source_snapshot_sha256": source_snapshot_sha256,
            },
            "control_envelope": {
                "read_only": True,
                "scoped_input_read": scoped_input_read,
                "client_recalculation_allowed": False,
                "legacy_procurement_rows_admitted": False,
                "product_created": False,
                "supplier_contacted": False,
                "purchase_order_created": False,
                "receipt_confirmed": False,
                "inspection_record_created": False,
                "approval_created": False,
                "permit_created": False,
                "invoice_created": False,
                "payment_initiated": False,
                "external_write_allowed": False,
            },
        }
        input_hash = self._hash(core)
        artifact = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "version": "1",
            "scope": context["scope"],
            "as_of": context["cutoff"].isoformat(),
            "input_snapshot_sha256": input_hash,
            "suggestions": [
                {
                    "type": "internal_task_suggestion",
                    "code": gap,
                    "owner": "procurement-control",
                    "next_workspace": "/procurement",
                }
                for gap in gaps
            ],
            "authority": (
                "decision_support_and_internal_task_suggestion_only"
            ),
            "owner": "procurement-control",
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "purchase_order_creation_allowed": False,
            "receipt_confirmation_allowed": False,
            "payment_allowed": False,
            "external_write_allowed": False,
        }
        core["agent_artifact"] = {
            **artifact,
            "artifact_sha256": self._hash(artifact),
        }
        core["snapshot_sha256"] = self._hash(core)
        return core

    def _empty(
        self,
        *,
        context: dict[str, Any],
        filters: dict[str, Any],
        page_size: int,
        status: str,
        reason: str,
        extra_gaps: list[str] | None = None,
        scoped_input_read: bool = False,
        source_snapshot_sha256: str | None = None,
    ) -> dict[str, Any]:
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=page_size,
            total_filtered=0,
            next_cursor=None,
            orders=[],
            total_counts=self._counts([]),
            excluded={
                "count": 0,
                "reason_counts": {},
                "business_values_exposed": False,
            },
            source_gaps=[
                reason,
                *(extra_gaps or []),
                "supplier_invoice_authority_not_implemented",
                "supplier_payment_authority_not_implemented",
            ],
            source_snapshot_sha256=source_snapshot_sha256,
            scoped_input_read=scoped_input_read,
        )

    @classmethod
    def _context(
        cls,
        *,
        store_ref: str,
        principal: Principal | None,
        entity_scope: dict[str, Any] | None,
        as_of: str | None,
    ) -> dict[str, Any]:
        store = str(store_ref or "").strip()
        if not store or len(store) > 160:
            raise ValueError("store_ref must be 1 to 160 characters")
        cutoff = cls._timestamp(
            as_of or datetime.now(UTC).isoformat(),
            "as_of",
        )
        if principal is not None and not principal.can_access_store(store):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        scope = entity_scope or {
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        }
        authority = str(scope.get("authority_sha256") or "").strip()
        ready = bool(
            principal is not None
            and scope.get("status") == "ready"
            and str(scope.get("entity_ref") or "").strip()
            and cls._sha256(authority)
        )
        malformed_ready = bool(
            scope.get("status") == "ready" and not ready
        )
        return {
            "status": (
                "ready"
                if ready
                else "blocked"
                if malformed_ready
                else "no_data"
            ),
            "reason": (
                "procurement_scope_authority_invalid"
                if malformed_ready
                else str(
                    scope.get("reason")
                    or (
                        "procurement_scope_principal_missing"
                        if principal is None
                        else "entity_scope_authority_missing"
                    )
                )
            ),
            "cutoff": cutoff,
            "principal": principal,
            "entity_scope": scope,
            "scope": {
                "tenant_ref": (
                    principal.tenant_ref if principal is not None else None
                ),
                "entity_ref": (
                    str(scope.get("entity_ref"))
                    if scope.get("entity_ref")
                    else None
                ),
                "store_ref": store,
                "scope_grant_authority_sha256": (
                    authority if ready else None
                ),
            },
        }

    @staticmethod
    def _financial_authority() -> dict[str, Any]:
        return {
            "status": "gated",
            "accounts_payable_invoice_authority_available": False,
            "supplier_payment_authority_available": False,
            "invoice_or_payment_claim_allowed": False,
            "reason": (
                "No exact-scope AP invoice or supplier payment authority "
                "has been implemented."
            ),
        }

    @staticmethod
    def _receipt_summary(
        *,
        timeline: list[dict[str, Any]],
        quantity: int,
    ) -> dict[str, Any]:
        received = next(
            (
                item
                for item in reversed(timeline)
                if item["event_type"] == "received"
            ),
            None,
        )
        inspected = next(
            (
                item
                for item in reversed(timeline)
                if item["event_type"] == "inspection_completed"
            ),
            None,
        )
        return {
            "ordered_quantity": quantity,
            "received_quantity": (
                int(received["facts"]["received_quantity"])
                if received
                else None
            ),
            "damaged_quantity": (
                int(received["facts"]["damaged_quantity"])
                if received
                else None
            ),
            "inspected_quantity": (
                int(inspected["facts"]["inspected_quantity"])
                if inspected
                else None
            ),
            "passed_quantity": (
                int(inspected["facts"]["passed_quantity"])
                if inspected
                else None
            ),
            "defect_count": (
                int(inspected["facts"]["defect_count"])
                if inspected
                else None
            ),
            "quantity_conserved": True,
        }

    @classmethod
    def _counts(cls, rows: list[dict[str, Any]]) -> dict[str, int]:
        result = {stage: 0 for stage in sorted(cls.STAGES)}
        for row in rows:
            result[row["stage"]] += 1
        return {"total": len(rows), **result}

    @classmethod
    def _paginate(
        cls,
        rows: list[dict[str, Any]],
        *,
        page_size: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        start = 0
        if cursor:
            decoded = cls._decode_cursor(cursor)
            for index, row in enumerate(rows):
                if cls._cursor_key(row) == decoded:
                    start = index + 1
                    break
            else:
                raise ValueError("cursor is stale or outside the result set")
        page = rows[start : start + page_size]
        next_cursor = (
            cls._encode_cursor(cls._cursor_key(page[-1]))
            if page and start + page_size < len(rows)
            else None
        )
        return page, next_cursor

    @staticmethod
    def _matches_query(row: dict[str, Any], query: str) -> bool:
        product = row.get("product") or {}
        haystack = " ".join(
            (
                str(row.get("purchase_order_id") or ""),
                str(row.get("supplier_ref") or ""),
                str(product.get("sku") or ""),
                str(product.get("name") or ""),
            )
        ).lower()
        return query in haystack

    @staticmethod
    def _blockers(gaps: list[str]) -> list[dict[str, str]]:
        return [
            {
                "code": gap,
                "severity": "P0",
                "owner": "procurement-control",
                "next_action": (
                    "Bind fresh exact-scope Evidence and repair the "
                    "procurement or receiving authority before acting."
                ),
                "workspace": "/procurement",
            }
            for gap in sorted(set(gaps))
        ]

    @staticmethod
    def _owner(stage: str) -> str:
        if stage in {"received", "inspected", "rework_required"}:
            return "quality-receiving"
        if stage in {"golden_sample_approved", "sample_rejected"}:
            return "product-owner"
        return "procurement-control"

    @staticmethod
    def _sla(stage: str) -> str:
        return {
            "approved_to_order": "before supplier order request",
            "order_confirmed": "before promised delivery time",
            "shipped": "before carrier delivery window",
            "received": "within 24 hours of physical receipt",
            "inspected": "before golden-sample disposition",
            "rework_required": "before accepting revised sample",
            "golden_sample_approved": "before listing release",
            "sample_rejected": "before replacement supplier review",
            "cancelled": "before closing procurement evidence",
        }[stage]

    @staticmethod
    def _next(stage: str) -> str:
        return {
            "approved_to_order": "Confirm the supplier order with Evidence.",
            "order_confirmed": "Capture shipment and carrier Evidence.",
            "shipped": "Receive and count physical units.",
            "received": "Complete evidence-backed inspection.",
            "inspected": "Record independent sample disposition.",
            "rework_required": "Inspect the revised sample.",
            "golden_sample_approved": "Continue to controlled listing readiness.",
            "sample_rejected": "Review an evidence-backed replacement supplier.",
            "cancelled": "Close the internal procurement follow-up.",
        }[stage]

    @staticmethod
    def _temporal_issues(
        item: dict[str, Any],
        *,
        fields: tuple[str, ...],
        context: dict[str, Any],
        prefix: str,
    ) -> list[str]:
        issues: list[str] = []
        for field in fields:
            try:
                value = ScopedProcurementReceivingWorkspace._timestamp(
                    item.get(field),
                    field,
                )
                if value > context["cutoff"]:
                    issues.append(f"{prefix}_{field}_future")
            except ValueError:
                issues.append(f"{prefix}_{field}_invalid")
        return issues

    @staticmethod
    def _query(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) > 160:
            raise ValueError("query must be at most 160 characters")
        return normalized

    @classmethod
    def _stage(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        if normalized not in cls.STAGES - {"blocked"}:
            raise ValueError("stage is not supported")
        return normalized

    @staticmethod
    def _page_size(value: int) -> int:
        if value < 1 or value > 100:
            raise ValueError("page_size must be between 1 and 100")
        return value

    @staticmethod
    def _currency(value: Any) -> bool:
        normalized = str(value or "").strip().upper()
        return (
            len(normalized) == 3
            and normalized.isascii()
            and normalized.isalpha()
        )

    @staticmethod
    def _decimal(
        value: Any,
        field: str,
        *,
        positive: bool,
    ) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field} must be decimal") from exc
        if not parsed.is_finite() or (positive and parsed <= 0):
            raise ValueError(f"{field} is invalid")
        return parsed

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        normalized = value.normalize()
        return format(normalized, "f")

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field} must be an ISO-8601 timestamp"
            ) from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _aware(value: datetime | None) -> datetime:
        if value is None:
            raise ValueError("Scoped product timestamp is missing")
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )

    @classmethod
    def _valid_snapshot(cls, value: dict[str, Any]) -> bool:
        claimed = str(value.get("snapshot_sha256") or "")
        if not cls._sha256(claimed):
            return False
        return cls._hash(
            {
                key: item
                for key, item in value.items()
                if key != "snapshot_sha256"
            }
        ) == claimed

    @staticmethod
    def _cursor_key(item: dict[str, Any]) -> str:
        return json.dumps(
            [item["created_at"], item["purchase_order_id"]],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _encode_cursor(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> str:
        try:
            padding = "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(value + padding).decode()
            parsed = json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("cursor is invalid") from exc
        if (
            not isinstance(parsed, list)
            or len(parsed) != 2
            or not all(isinstance(item, str) for item in parsed)
        ):
            raise ValueError("cursor is invalid")
        return json.dumps(
            parsed,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
