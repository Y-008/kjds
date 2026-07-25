from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from .action_policies import require_action_authorization
from .connectors import ConnectorRecord, ConnectorRegistry
from .evidence import EvidenceGrade
from .source_connector_adapters import (
    ASSET_MANIFEST_CONTRACT,
    SOURCE_LISTING_CONTRACT,
    SUPPLIER_MESSAGE_CONTRACT,
)

MARKET_SIGNAL_CONTRACT = "market-signal-snapshot-v1"
SUPPORTED_SNAPSHOT_CONTRACTS = frozenset(
    {
        SOURCE_LISTING_CONTRACT,
        MARKET_SIGNAL_CONTRACT,
        ASSET_MANIFEST_CONTRACT,
        SUPPLIER_MESSAGE_CONTRACT,
    }
)


class SourceAcquisitionService:
    """Run bounded read-only connectors and capture their output as research evidence."""

    MAX_CANDIDATES_PER_RUN = 20
    MAX_SUPPLIERS_PER_CANDIDATE = 5
    MAX_RECORDS_PER_RUN = 500

    def __init__(
        self,
        *,
        connectors: ConnectorRegistry,
        research_inbox,
        action_authorization,
        repository,
    ) -> None:
        self.connectors = connectors
        self.research_inbox = research_inbox
        self.action_authorization = action_authorization
        self.repository = repository

    def pull(
        self,
        *,
        connector_name: str,
        cursor: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        connector_name = self._required(connector_name, "Connector name", 120)
        connector = self.connectors.get(connector_name)
        require_action_authorization(
            self.action_authorization,
            self.repository,
            action="source_discover",
            subject_id=connector_name,
            actor_id=actor_id,
            occurred_at=datetime.now(UTC),
            phase="request",
        )
        records, next_cursor = connector.pull(cursor=cursor)
        self._validate_batch(records)
        captured = [self.capture_record(record, actor_id=actor_id) for record in records]
        return {
            "connector": connector_name,
            "record_count": len(records),
            "evidence_count": len({item["evidence"]["id"] for item in captured}),
            "duplicate_count": sum(bool(item["duplicate"]) for item in captured),
            "next_cursor": next_cursor,
            "records": captured,
            "guardrails": {
                "read_only_connector": True,
                "external_write_allowed": False,
                "automatic_fact_promotion": False,
                "automatic_supplier_offer": False,
                "automatic_procurement": False,
                "automatic_payment": False,
            },
        }

    def capture_record(self, record: ConnectorRecord, *, actor_id: str) -> dict[str, Any]:
        payload = self._validate_record(record)
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        contract_id = payload["contract_id"]
        provider_record_id = f"{contract_id}:{record.external_id}"
        filename_id = re.sub(r"[^A-Za-z0-9._-]+", "-", record.external_id).strip("-")[:100] or "record"
        candidate_ref = payload["candidate_ref"]
        result = self.research_inbox.capture(
            content=content,
            filename=f"{contract_id}-{filename_id}.json",
            content_type="application/json",
            provider=record.source,
            provider_record_id=provider_record_id,
            source_url=record.source_ref,
            observed_at=record.occurred_at,
            declared_grade=EvidenceGrade.C,
            license_status=str(payload.get("license_status", "requires_review")),
            raw_fields=self._raw_projection(payload),
            candidate_refs=[candidate_ref],
            created_by=actor_id,
        )
        return {
            **result,
            "contract_id": contract_id,
            "provider": record.source,
            "provider_record_id": provider_record_id,
        }

    def discoveries(self, *, candidate_ref: str, limit: int = 100) -> dict[str, Any]:
        candidate_ref = self._required(candidate_ref, "Candidate reference", 120)
        rows = self.research_inbox.list(candidate_ref=candidate_ref, limit=limit)
        items = [
            self._discovery_view(item)
            for item in rows
            if item["evidence"]["metadata"].get("raw_fields", {}).get("contract_id")
            in {
                SOURCE_LISTING_CONTRACT,
                ASSET_MANIFEST_CONTRACT,
                SUPPLIER_MESSAGE_CONTRACT,
            }
        ]
        return {
            "contract_id": "kjds-sourcing-discoveries-v1",
            "candidate_ref": candidate_ref,
            "count": len(items),
            "items": items,
            "decision_use": "research_only",
            "formal_offer_count": 0,
            "automatic_fact_promotion": False,
            "automatic_procurement": False,
            "external_write_allowed": False,
        }

    @classmethod
    def _validate_batch(cls, records: list[ConnectorRecord]) -> None:
        if len(records) > cls.MAX_RECORDS_PER_RUN:
            raise ValueError("Source acquisition run exceeds the record limit")
        candidates: set[str] = set()
        suppliers: dict[str, set[str]] = {}
        for record in records:
            if not isinstance(record, ConnectorRecord):
                raise ValueError("Connector returned an unsupported record")
            payload = record.payload
            candidate_ref = str(payload.get("candidate_ref", "")).strip()
            if not candidate_ref:
                raise ValueError("Connector record requires candidate_ref")
            candidates.add(candidate_ref)
            if record.record_type == SOURCE_LISTING_CONTRACT:
                # One candidate/Offer is the bounded acquisition unit. Search and
                # detail adapters may identify the same supplier differently, so
                # counting seller labels would double-count one Offer.
                supplier_key = str(payload.get("listing_id") or payload.get("seller_id") or "").strip()
                if not supplier_key:
                    raise ValueError("Source listing requires seller_id or listing_id")
                suppliers.setdefault(candidate_ref, set()).add(supplier_key)
        if len(candidates) > cls.MAX_CANDIDATES_PER_RUN:
            raise ValueError("Source acquisition run may contain at most 20 candidates")
        if any(len(values) > cls.MAX_SUPPLIERS_PER_CANDIDATE for values in suppliers.values()):
            raise ValueError("Source acquisition run may contain at most 5 suppliers per candidate")

    @classmethod
    def _validate_record(cls, record: ConnectorRecord) -> dict[str, Any]:
        if record.record_type not in SUPPORTED_SNAPSHOT_CONTRACTS:
            raise ValueError(f"Unsupported source snapshot contract: {record.record_type}")
        payload = record.payload
        if not isinstance(payload, dict):
            raise ValueError("Connector payload must be an object")
        if payload.get("contract_id") != record.record_type:
            raise ValueError("Connector record type and contract_id must match")
        for field in ("platform", "candidate_ref", "fact_status"):
            cls._required(cls._text(payload.get(field)), field, 120)
        if payload["fact_status"] != "research_signal":
            raise ValueError("Connector output must remain a research_signal")
        if record.record_type in {
            SOURCE_LISTING_CONTRACT,
            ASSET_MANIFEST_CONTRACT,
            SUPPLIER_MESSAGE_CONTRACT,
        }:
            cls._required(cls._text(payload.get("listing_id")), "listing_id", 120)
        if record.record_type == SOURCE_LISTING_CONTRACT:
            cls._required(cls._text(payload.get("title")), "title", 1000)
        if record.record_type == SUPPLIER_MESSAGE_CONTRACT:
            cls._required(cls._text(payload.get("message_id")), "message_id", 500)
        cls._required(record.source, "Connector source", 120)
        cls._required(record.external_id, "Connector external ID", 500)
        cls._required(record.source_ref, "Connector source URL", 2000)
        try:
            observed = datetime.fromisoformat(record.occurred_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Connector occurred_at must be ISO-8601") from exc
        if observed.tzinfo is None:
            raise ValueError("Connector occurred_at must include a timezone")
        try:
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Connector payload must be finite JSON") from exc
        return payload

    @staticmethod
    def _raw_projection(payload: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "contract_id",
            "platform",
            "listing_id",
            "seller_id",
            "title",
            "price_text",
            "moq_text",
            "seller_name",
            "origin_place",
            "member_id",
            "shop_id",
            "currency",
            "moq_value",
            "visible_attributes_text",
            "sales_text",
            "service_badges_text",
            "sku_combinations_text",
            "material_text",
            "net_weight_text",
            "gross_weight_text",
            "package_dimensions_text",
            "tier_pricing_text",
            "sample_price_text",
            "domestic_freight_text",
            "delivery_time_text",
            "current_stock_text",
            "compression_method_text",
            "uncompressed_dimensions_text",
            "compressed_dimensions_text",
            "recovery_result_text",
            "repeat_compression_text",
            "defect_handling_text",
            "return_terms_text",
            "quality_inspection_text",
            "packaging_oem_text",
            "asset_use_authorization_text",
            "unknown_fields_text",
            "supplier_company_name",
            "supplier_legal_entity",
            "supplier_business_model_text",
            "supplier_years_on_platform_text",
            "supplier_location",
            "supplier_staff_size_text",
            "supplier_response_rate_text",
            "supplier_return_rate_text",
            "search_keyword",
            "search_sort",
            "search_ads_excluded",
            "listed_piece_weight_text",
            "main_count",
            "sku_count",
            "detail_count",
            "video_count",
            "download_status",
            "rights_status",
            "message_id",
            "sender",
            "is_mine",
            "content_redacted",
            "read",
            "kind",
            "fact_status",
        )
        return {
            key: payload.get(key)
            for key in keys
            if key in payload and isinstance(payload.get(key), (str, int, float, bool))
        }

    @staticmethod
    def _discovery_view(item: dict[str, Any]) -> dict[str, Any]:
        evidence = item["evidence"]
        metadata = evidence["metadata"]
        fields = metadata.get("raw_fields", {})
        return {
            "evidence_id": evidence["id"],
            "sha256": evidence["sha256"],
            "provider": metadata.get("provider"),
            "provider_record_id": metadata.get("provider_record_id"),
            "source_url": metadata.get("source_url"),
            "observed_at": evidence["effective_at"],
            "captured_at": metadata.get("captured_at"),
            "contract_id": fields.get("contract_id"),
            "fields": fields,
            "license_status": metadata.get("license_status"),
            "review_status": metadata.get("review_status"),
            "integrity_valid": item["integrity_valid"],
            "decision_use": item["decision_use"],
        }

    @staticmethod
    def _required(value: str, label: str, maximum: int) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > maximum:
            raise ValueError(f"{label} is required and must not exceed {maximum} characters")
        return normalized

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""


class SkuWorkbenchService:
    """Project one candidate or Product across existing KJDS sources without owning facts."""

    CONTRACT_ID = "kjds-sku-workbench-v1"

    def __init__(
        self,
        *,
        repository,
        research_inbox,
        readiness,
        sourcing_store,
        procurement,
        sales_fulfillment=None,
    ) -> None:
        self.repository = repository
        self.research_inbox = research_inbox
        self.readiness = readiness
        self.sourcing_store = sourcing_store
        self.procurement = procurement
        self.sales_fulfillment = sales_fulfillment

    def snapshot(self, product_or_candidate_ref: str) -> dict[str, Any]:
        requested_ref = SourceAcquisitionService._required(
            product_or_candidate_ref,
            "Product or candidate reference",
            200,
        )
        products = self.repository.list_products()
        candidate_to_product = self._candidate_product_map()
        product = next(
            (item for item in products if requested_ref in {item.id, item.sku}),
            None,
        )
        candidate_ref = next(
            (
                candidate
                for candidate, product_id in candidate_to_product.items()
                if product and product_id == product.id
            ),
            requested_ref if requested_ref in candidate_to_product else requested_ref,
        )
        if product is None and requested_ref in candidate_to_product:
            product = next(
                (item for item in products if item.id == candidate_to_product[requested_ref]),
                None,
            )
        signals = self.research_inbox.list(candidate_ref=candidate_ref, limit=100)
        if product is None and not signals:
            raise KeyError(f"Unknown product or candidate: {requested_ref}")
        readiness = self.readiness.report()
        product_row = next(
            (row for row in readiness["products"] if product and row["product"]["id"] == product.id),
            None,
        )
        offers = [
            item for item in self.sourcing_store.list_offers(limit=500) if product and item.product_id == product.id
        ]
        offer_ids = {item.id for item in offers}
        scenarios = [item for item in self.sourcing_store.list_scenarios(limit=500) if item.offer_id in offer_ids]
        scenario_ids = {item.id for item in scenarios}
        approvals = [
            item
            for item in self.repository.list_approvals()
            if item.resource_id in {candidate_ref, *(offer_ids | scenario_ids)}
            or (product and item.payload.get("product_id") == product.id)
        ]
        sample_orders = [
            item for item in self.procurement.list_orders(limit=500) if product and item["product"]["id"] == product.id
        ]
        sales_fulfillment_plans = [
            item
            for item in (
                self.sales_fulfillment.list_plans(limit=500) if self.sales_fulfillment is not None else []
            )
            if product and item["product_id"] == product.id
        ]
        listing_drafts = [
            item
            for item in self.sourcing_store.list_listing_drafts(limit=500)
            if product and item.product_id == product.id
        ]
        grouped = self._signal_groups(signals)
        unknowns: list[str] = []
        if product is None:
            unknowns.append("candidate_product")
        if len({item.supplier_ref for item in offers}) < 3:
            unknowns.append("three_comparable_formal_quotes")
        if not scenarios:
            unknowns.append("ozon_ru_full_cost_scenario")
        elif not any(item.cost_complete for item in scenarios):
            unknowns.append("complete_15_item_cost_evidence")
        if not readiness["decision_scope_readiness"]["real_execution"]["ready"]:
            unknowns.append("ozon_28_day_real_execution_demand_evidence")
        if not product_row or not product_row["passports_ready"]:
            unknowns.append("approved_product_compliance_quality_passports")
        return {
            "contract_id": self.CONTRACT_ID,
            "requested_ref": requested_ref,
            "candidate_ref": candidate_ref,
            "product": asdict(product) if product else None,
            "readiness": product_row,
            "research": grouped,
            "formal_offers": [asdict(item) for item in offers],
            "profit_scenarios": [self._scenario_view(item) for item in scenarios],
            "approvals": [asdict(item) for item in approvals],
            "sample_orders": sample_orders,
            "sales_fulfillment_plans": sales_fulfillment_plans,
            "listing_drafts": [asdict(item) for item in listing_drafts],
            "unknowns": sorted(set(unknowns)),
            "guardrails": {
                "advisory_only": True,
                "automatic_fact_promotion": False,
                "automatic_supplier_contact": False,
                "automatic_procurement": False,
                "automatic_payment": False,
                "automatic_listing": False,
                "platform_write_allowed": False,
            },
        }

    def _candidate_product_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for event in self.repository.events_after(0):
            if event["type"] != "product.candidate_sourcing_workspace_created":
                continue
            candidate_ref = str(event["payload"].get("candidate_ref", "")).strip()
            if candidate_ref:
                result[candidate_ref] = event["aggregate_id"]
        return result

    @staticmethod
    def _signal_groups(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped = {
            "market_signals": [],
            "source_listings": [],
            "asset_manifests": [],
            "supplier_messages": [],
        }
        destinations = {
            SOURCE_LISTING_CONTRACT: "source_listings",
            ASSET_MANIFEST_CONTRACT: "asset_manifests",
            SUPPLIER_MESSAGE_CONTRACT: "supplier_messages",
        }
        for item in signals:
            fields = item["evidence"]["metadata"].get("raw_fields", {})
            destination = destinations.get(fields.get("contract_id"), "market_signals")
            grouped[destination].append(SourceAcquisitionService._discovery_view(item))
        return grouped

    @staticmethod
    def _scenario_view(item) -> dict[str, Any]:
        return {
            "id": item.id,
            "offer_id": item.offer_id,
            "template_id": item.template_id,
            "cm3_cny": str(item.cm3_cny),
            "cm3_rate": str(item.cm3_rate),
            "break_even_price_rub": str(item.break_even_price_rub),
            "cost_states": item.cost_states,
            "unknown_costs": item.unknown_costs,
            "cost_complete": item.cost_complete,
            "evidence": item.evidence,
        }
