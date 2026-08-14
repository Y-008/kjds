from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from .sourcing import ListingDraft, ProfitInputs, ProfitScenario, SourcePlatform, SupplierOffer


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class SqlSourcingStore:
    def __init__(self, engine) -> None:
        self.engine = engine

    def save_offer(self, offer: SupplierOffer) -> SupplierOffer:
        statement = text("""
            INSERT INTO source_offers (
                id, product_id, supplier_ref, platform, external_id, source_url, title, currency, unit_price_decimal,
                source_to_cny_rate_decimal, min_order_quantity, weight_kg_decimal,
                length_cm_decimal, width_cm_decimal, height_cm_decimal,
                domestic_logistics_per_unit_decimal, evidence_ref, attributes_json,
                media_json, captured_at
            ) VALUES (
                :id, :product_id, :supplier_ref, :platform, :external_id, :source_url, :title, :currency, :unit_price,
                :source_to_cny_rate, :moq, :weight_kg, :length_cm, :width_cm, :height_cm,
                :domestic_logistics, :evidence_ref, CAST(:attributes AS jsonb),
                CAST(:media AS jsonb), :captured_at
            )
            ON CONFLICT (platform, external_id) DO NOTHING
            RETURNING id
        """)
        import json

        params = {
            "id": offer.id,
            "product_id": offer.product_id,
            "supplier_ref": offer.supplier_ref,
            "platform": offer.platform.value,
            "external_id": offer.external_id,
            "source_url": offer.source_url,
            "title": offer.title,
            "currency": offer.currency,
            "unit_price": offer.unit_price,
            "source_to_cny_rate": offer.source_to_cny_rate,
            "moq": offer.min_order_quantity,
            "weight_kg": offer.weight_kg,
            "length_cm": offer.length_cm,
            "width_cm": offer.width_cm,
            "height_cm": offer.height_cm,
            "domestic_logistics": offer.domestic_logistics_per_unit,
            "evidence_ref": offer.evidence_ref,
            "attributes": json.dumps(offer.attributes),
            "media": json.dumps(offer.media),
            "captured_at": datetime.fromisoformat(offer.captured_at),
        }
        with self.engine.begin() as connection:
            inserted_id = connection.execute(statement, params).scalar_one_or_none()
            if inserted_id is not None:
                offer.id = inserted_id
                return offer
            row = (
                connection.execute(
                    text("SELECT * FROM source_offers WHERE platform=:platform AND external_id=:external_id"),
                    {"platform": offer.platform.value, "external_id": offer.external_id},
                )
                .mappings()
                .one()
            )
            existing = self._offer(row)
            if self._offer_payload(existing) != self._offer_payload(offer):
                raise ValueError(
                    "Supplier offer idempotency conflict; capture changed terms under a new external snapshot ID"
                )
            return existing

    @staticmethod
    def _offer_payload(offer: SupplierOffer) -> tuple:
        return (
            offer.product_id,
            offer.supplier_ref,
            offer.platform,
            offer.external_id,
            offer.source_url,
            offer.title,
            offer.currency,
            offer.unit_price,
            offer.source_to_cny_rate,
            offer.min_order_quantity,
            offer.weight_kg,
            offer.length_cm,
            offer.width_cm,
            offer.height_cm,
            offer.domestic_logistics_per_unit,
            offer.evidence_ref,
            offer.attributes,
            offer.media,
        )

    def get_offer(self, offer_id: str) -> SupplierOffer:
        with self.engine.connect() as connection:
            row = (
                connection.execute(text("SELECT * FROM source_offers WHERE id=:id"), {"id": offer_id})
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError(f"Unknown supplier offer: {offer_id}")
        return self._offer(row)

    def list_offers(self, limit: int = 100) -> list[SupplierOffer]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("SELECT * FROM source_offers ORDER BY captured_at DESC LIMIT :limit"), {"limit": limit}
                )
                .mappings()
                .all()
            )
        return [self._offer(row) for row in rows]

    @staticmethod
    def _offer(row) -> SupplierOffer:
        return SupplierOffer(
            product_id=row["product_id"],
            supplier_ref=row["supplier_ref"],
            platform=SourcePlatform(row["platform"]),
            external_id=row["external_id"],
            source_url=row["source_url"],
            title=row["title"],
            currency=row["currency"],
            unit_price=Decimal(row["unit_price_decimal"]),
            source_to_cny_rate=Decimal(row["source_to_cny_rate_decimal"]),
            min_order_quantity=row["min_order_quantity"],
            weight_kg=Decimal(row["weight_kg_decimal"]),
            length_cm=Decimal(row["length_cm_decimal"]),
            width_cm=Decimal(row["width_cm_decimal"]),
            height_cm=Decimal(row["height_cm_decimal"]),
            domestic_logistics_per_unit=Decimal(row["domestic_logistics_per_unit_decimal"]),
            evidence_ref=row["evidence_ref"],
            attributes=row["attributes_json"] or {},
            media=row["media_json"] or [],
            id=row["id"],
            captured_at=_iso(row["captured_at"]),
        )

    def save_scenario(self, scenario: ProfitScenario) -> ProfitScenario:
        import json

        payload = {
            "values": {key: str(value) for key, value in asdict(scenario.inputs).items()},
            "template_id": scenario.template_id,
            "cost_states": scenario.cost_states,
        }
        with self.engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO profit_scenarios (
                    id, offer_id, target_platform, inputs_json, revenue_cny_decimal,
                    purchase_cny_decimal, domestic_logistics_cny_decimal,
                    international_logistics_cny_decimal, packaging_cny_decimal,
                    warehousing_cny_decimal, customs_cny_decimal, tax_cny_decimal,
                    last_mile_cny_decimal, platform_fee_cny_decimal,
                    advertising_cny_decimal, return_reserve_cny_decimal, other_cost_cny_decimal,
                    fx_cost_cny_decimal, capital_cost_cny_decimal, aftersales_cny_decimal,
                    loss_reserve_cny_decimal,
                    total_cost_cny_decimal, cm3_cny_decimal, cm3_rate_decimal,
                    break_even_price_rub_decimal, evidence_json, cost_evidence_json,
                    logistics_calculation_id, created_at
                ) VALUES (
                    :id, :offer_id, :target, CAST(:inputs AS jsonb), :revenue, :purchase,
                    :domestic, :international, :packaging, :warehousing, :customs, :tax,
                    :last_mile, :platform_fee, :advertising, :returns, :other, :fx_cost,
                    :capital_cost, :aftersales, :loss_reserve, :total, :cm3,
                    :cm3_rate, :break_even, CAST(:evidence AS jsonb),
                    CAST(:cost_evidence AS jsonb), :logistics_calculation_id, :created_at
                )
            """),
                {
                    "id": scenario.id,
                    "offer_id": scenario.offer_id,
                    "target": scenario.target_platform,
                    "inputs": json.dumps(payload),
                    "revenue": scenario.revenue_cny,
                    "purchase": scenario.purchase_cny,
                    "domestic": scenario.domestic_logistics_cny,
                    "international": scenario.international_logistics_cny,
                    "packaging": scenario.packaging_cny,
                    "warehousing": scenario.warehousing_cny,
                    "customs": scenario.customs_cny,
                    "tax": scenario.tax_cny,
                    "last_mile": scenario.last_mile_cny,
                    "platform_fee": scenario.platform_fee_cny,
                    "advertising": scenario.advertising_cny,
                    "returns": scenario.return_reserve_cny,
                    "other": scenario.other_cost_cny,
                    "fx_cost": scenario.fx_cost_cny,
                    "capital_cost": scenario.capital_cost_cny,
                    "aftersales": scenario.aftersales_cny,
                    "loss_reserve": scenario.loss_reserve_cny,
                    "total": scenario.total_cost_cny,
                    "cm3": scenario.cm3_cny,
                    "cm3_rate": scenario.cm3_rate,
                    "break_even": scenario.break_even_price_rub,
                    "evidence": json.dumps(scenario.evidence),
                    "cost_evidence": json.dumps(scenario.cost_evidence),
                    "logistics_calculation_id": scenario.logistics_calculation_id,
                    "created_at": datetime.fromisoformat(scenario.created_at),
                },
            )
        return scenario

    def get_scenario(self, scenario_id: str) -> ProfitScenario:
        with self.engine.connect() as connection:
            row = (
                connection.execute(text("SELECT * FROM profit_scenarios WHERE id=:id"), {"id": scenario_id})
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError(f"Unknown profit scenario: {scenario_id}")
        return self._scenario(row)

    @staticmethod
    def _scenario(row) -> ProfitScenario:
        stored_inputs = row["inputs_json"] or {}
        # Legacy rows used a flat numeric object. Keep reading them without a migration.
        if "values" in stored_inputs:
            raw_values = stored_inputs["values"]
            template_id = stored_inputs.get("template_id", "ozon-ru-full-cost-v1")
            cost_states = stored_inputs.get("cost_states", {})
            logistics_calculation_id = row.get(
                "logistics_calculation_id"
            ) or stored_inputs.get("logistics_calculation_id")
        else:
            raw_values = stored_inputs
            template_id = "ozon-ru-full-cost-v1"
            cost_states = {
                key: "estimate"
                for key in (row["cost_evidence_json"] or {})
            }
            logistics_calculation_id = row.get("logistics_calculation_id")
        inputs = {key: Decimal(value) for key, value in raw_values.items()}
        return ProfitScenario(
            offer_id=row["offer_id"],
            target_platform=row["target_platform"],
            inputs=ProfitInputs(**inputs),
            revenue_cny=Decimal(row["revenue_cny_decimal"]),
            purchase_cny=Decimal(row["purchase_cny_decimal"]),
            domestic_logistics_cny=Decimal(row["domestic_logistics_cny_decimal"]),
            international_logistics_cny=Decimal(row["international_logistics_cny_decimal"]),
            packaging_cny=Decimal(row["packaging_cny_decimal"]),
            warehousing_cny=Decimal(row["warehousing_cny_decimal"]),
            customs_cny=Decimal(row["customs_cny_decimal"]),
            tax_cny=Decimal(row["tax_cny_decimal"]),
            last_mile_cny=Decimal(row["last_mile_cny_decimal"]),
            platform_fee_cny=Decimal(row["platform_fee_cny_decimal"]),
            advertising_cny=Decimal(row["advertising_cny_decimal"]),
            return_reserve_cny=Decimal(row["return_reserve_cny_decimal"]),
            fx_cost_cny=Decimal(row["fx_cost_cny_decimal"]),
            capital_cost_cny=Decimal(row["capital_cost_cny_decimal"]),
            aftersales_cny=Decimal(row["aftersales_cny_decimal"]),
            loss_reserve_cny=Decimal(row["loss_reserve_cny_decimal"]),
            other_cost_cny=Decimal(row["other_cost_cny_decimal"]),
            total_cost_cny=Decimal(row["total_cost_cny_decimal"]),
            cm3_cny=Decimal(row["cm3_cny_decimal"]),
            cm3_rate=Decimal(row["cm3_rate_decimal"]),
            break_even_price_rub=Decimal(row["break_even_price_rub_decimal"]),
            evidence=row["evidence_json"],
            cost_evidence=row["cost_evidence_json"] or {},
            template_id=template_id,
            cost_states=cost_states,
            logistics_calculation_id=logistics_calculation_id,
            id=row["id"],
            created_at=_iso(row["created_at"]),
        )

    def list_scenarios(self, limit: int = 1000) -> list[ProfitScenario]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("SELECT * FROM profit_scenarios ORDER BY created_at DESC LIMIT :limit"),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
        return [self._scenario(row) for row in rows]

    def save_listing_draft(self, draft: ListingDraft) -> ListingDraft:
        import json

        with self.engine.begin() as connection:
            inserted_id = connection.execute(
                text("""
                INSERT INTO listing_drafts (
                    id, product_id, offer_id, scenario_id, target_platform, listing_json,
                    requested_by, status, approval_id, created_at,
                    tenant_ref, entity_ref, store_ref,
                    scope_grant_authority_sha256,
                    scoped_product_content_sha256, approval_plan_sha256,
                    evidence_ids_json, scope_as_of
                ) VALUES (
                    :id, :product_id, :offer_id, :scenario_id, :target, CAST(:listing AS jsonb),
                    :requested_by, :status, :approval_id, :created_at,
                    :tenant_ref, :entity_ref, :store_ref,
                    :scope_grant_authority_sha256,
                    :scoped_product_content_sha256, :approval_plan_sha256,
                    CAST(:evidence_ids AS jsonb), :scope_as_of
                )
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            """),
                {
                    "id": draft.id,
                    "product_id": draft.product_id,
                    "offer_id": draft.offer_id,
                    "scenario_id": draft.scenario_id,
                    "target": draft.target_platform,
                    "listing": json.dumps(draft.listing_data),
                    "requested_by": draft.requested_by,
                    "status": draft.status,
                    "approval_id": draft.approval_id,
                    "created_at": datetime.fromisoformat(draft.created_at),
                    "tenant_ref": draft.tenant_ref,
                    "entity_ref": draft.entity_ref,
                    "store_ref": draft.store_ref,
                    "scope_grant_authority_sha256": (
                        draft.scope_grant_authority_sha256
                    ),
                    "scoped_product_content_sha256": (
                        draft.scoped_product_content_sha256
                    ),
                    "approval_plan_sha256": draft.approval_plan_sha256,
                    "evidence_ids": json.dumps(draft.evidence_ids),
                    "scope_as_of": (
                        datetime.fromisoformat(draft.scope_as_of)
                        if draft.scope_as_of
                        else None
                    ),
                },
            ).scalar_one_or_none()
        return draft if inserted_id is not None else self.get_listing_draft(draft.id)

    def list_listing_drafts(self, limit: int = 100) -> list[ListingDraft]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("SELECT * FROM listing_drafts ORDER BY created_at DESC LIMIT :limit"), {"limit": limit}
                )
                .mappings()
                .all()
            )
        return [self._listing_draft(row) for row in rows]

    def get_listing_draft(self, draft_id: str) -> ListingDraft:
        with self.engine.connect() as connection:
            row = (
                connection.execute(text("SELECT * FROM listing_drafts WHERE id=:id"), {"id": draft_id})
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError(f"Unknown listing draft: {draft_id}")
        return self._listing_draft(row)

    @staticmethod
    def _listing_draft(row) -> ListingDraft:
        return ListingDraft(
            product_id=row["product_id"],
            offer_id=row["offer_id"],
            scenario_id=row["scenario_id"],
            target_platform=row["target_platform"],
            listing_data=row["listing_json"],
            requested_by=row["requested_by"],
            status=row["status"],
            approval_id=row["approval_id"],
            id=row["id"],
            created_at=_iso(row["created_at"]),
            tenant_ref=row.get("tenant_ref"),
            entity_ref=row.get("entity_ref"),
            store_ref=row.get("store_ref"),
            scope_grant_authority_sha256=row.get(
                "scope_grant_authority_sha256"
            ),
            scoped_product_content_sha256=row.get(
                "scoped_product_content_sha256"
            ),
            approval_plan_sha256=row.get("approval_plan_sha256"),
            evidence_ids=row.get("evidence_ids_json") or [],
            scope_as_of=(
                _iso(row["scope_as_of"]) if row.get("scope_as_of") else None
            ),
        )

    def list_listing_drafts_scoped(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
        limit: int = 100,
    ) -> list[ListingDraft]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM listing_drafts
                        WHERE tenant_ref=:tenant_ref
                          AND entity_ref=:entity_ref
                          AND store_ref=:store_ref
                          AND created_at <= :as_of
                          AND scope_as_of <= :as_of
                        ORDER BY created_at DESC, id
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_ref": tenant_ref,
                        "entity_ref": entity_ref,
                        "store_ref": store_ref,
                        "as_of": as_of,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
        return [self._listing_draft(row) for row in rows]

    def get_listing_draft_scoped(
        self,
        *,
        draft_id: str,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> ListingDraft:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM listing_drafts
                        WHERE id=:id
                          AND tenant_ref=:tenant_ref
                          AND entity_ref=:entity_ref
                          AND store_ref=:store_ref
                          AND created_at <= :as_of
                          AND scope_as_of <= :as_of
                        """
                    ),
                    {
                        "id": draft_id,
                        "tenant_ref": tenant_ref,
                        "entity_ref": entity_ref,
                        "store_ref": store_ref,
                        "as_of": as_of,
                    },
                )
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError(
                "Unknown listing draft in authorized operating scope"
            )
        return self._listing_draft(row)

    def attach_listing_approval(self, draft: ListingDraft) -> ListingDraft:
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE listing_drafts SET approval_id=:approval_id, status=:status WHERE id=:id"),
                {"approval_id": draft.approval_id, "status": draft.status, "id": draft.id},
            )
        return draft
