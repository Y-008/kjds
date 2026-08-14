from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .marketplace_observation import exact_candidate_key
from .marketplace_sources import SUPPLIER_MARKETPLACES, is_supplier_marketplace
from .security import Principal


def _merge_supplier_projections(
    projections: list[dict[str, Any]],
) -> dict[str, Any]:
    items = [
        item
        for projection in projections
        for item in projection.get("items", [])
    ]
    blockers = [
        blocker
        for projection in projections
        for blocker in projection.get("blockers", [])
    ]
    source_gaps = sorted(
        {
            gap
            for projection in projections
            for gap in projection.get("source_gaps", [])
        }
    )
    statuses = {projection.get("status") for projection in projections}
    snapshots = {
        marketplace: projection.get("snapshot_sha256")
        for marketplace, projection in zip(
            sorted(SUPPLIER_MARKETPLACES), projections, strict=True
        )
    }
    return {
        "status": (
            "ready"
            if items
            else "blocked" if "blocked" in statuses else "no_data"
        ),
        "items": items,
        "source_gaps": source_gaps,
        "blockers": blockers,
        "pagination": {
            "truncated": any(
                projection.get("pagination", {}).get("truncated", False)
                for projection in projections
            )
        },
        "snapshot_sha256": hashlib.sha256(
            json.dumps(snapshots, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


class ScopedBatchOpportunityAuthority:
    """Run research screening only from scoped, replayable input authorities."""

    CONTRACT_ID = "kjds-scoped-batch-opportunity-v1"

    def __init__(
        self,
        *,
        batch,
        scoped_observations,
        scoped_catalog,
        scoped_evidence,
        rules,
        scoped_product_content=None,
    ) -> None:
        self.batch = batch
        self.scoped_observations = scoped_observations
        self.scoped_catalog = scoped_catalog
        self.scoped_evidence = scoped_evidence
        self.scoped_product_content = scoped_product_content
        self.rules = rules

    def prepare(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        policy_id: str,
        idempotency_key: str,
        candidate_limit: int,
        pilot_limit: int,
        target_purchase_quantity: int,
        max_age_hours: int,
        max_inventory_cash_cny,
        cm3_floor_cny,
        actor_id: str,
        full_evaluate_limit: int,
        scan_page_size: int,
        scan_shard_count: int,
        scan_shard_index: int,
        max_batch_inventory_cash_cny,
        evidence_class: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            return self._empty(context=context)
        inputs = self._inputs(
            context=context,
            candidate_limit=candidate_limit,
            scan_page_size=scan_page_size,
        )
        if inputs["status"] in {"blocked", "no_data"}:
            return self._input_result(context=context, inputs=inputs)

        run = self.batch.prepare(
            store_ref=store_ref,
            policy_id=policy_id,
            idempotency_key=idempotency_key,
            candidate_limit=candidate_limit,
            pilot_limit=pilot_limit,
            target_purchase_quantity=target_purchase_quantity,
            max_age_hours=max_age_hours,
            max_inventory_cash_cny=max_inventory_cash_cny,
            cm3_floor_cny=cm3_floor_cny,
            actor_id=actor_id,
            as_of=context["cutoff"].isoformat(),
            full_evaluate_limit=full_evaluate_limit,
            scan_page_size=scan_page_size,
            scan_shard_count=scan_shard_count,
            scan_shard_index=scan_shard_index,
            max_batch_inventory_cash_cny=max_batch_inventory_cash_cny,
            evidence_class=evidence_class,
            scope_authority={
                **context["scope"],
                "scope_grant_authority_sha256": context["scope"][
                    "scope_grant_authority_sha256"
                ],
                "scope_evidence_authority_sha256": inputs[
                    "scope_evidence_authority_sha256"
                ],
                "scoped_observation_snapshot_sha256": inputs[
                    "observation_snapshot_sha256"
                ],
                "scoped_catalog_snapshot_sha256": inputs[
                    "catalog_snapshot_sha256"
                ],
                "scoped_economics_snapshot_sha256": inputs[
                    "economics_snapshot_sha256"
                ],
                "scoped_product_content_snapshot_sha256": inputs[
                    "product_content_snapshot_sha256"
                ],
            },
            scoped_observations=inputs["observations"],
            scoped_catalog=inputs["catalog"],
            scoped_fx_rates=inputs["fx_rates"],
            scoped_product_content=inputs["product_content"],
        )
        return self._run_result(
            context=context,
            inputs=inputs,
            run=run,
        )

    def latest(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            return self._empty(context=context)
        try:
            run = self.batch.latest_scoped(
                tenant_ref=context["scope"]["tenant_ref"],
                entity_ref=context["scope"]["entity_ref"],
                store_ref=store_ref,
                scope_grant_authority_sha256=context["scope"][
                    "scope_grant_authority_sha256"
                ],
                as_of=context["cutoff"],
            )
        except (KeyError, RuntimeError, ValueError):
            return self._blocked_run(context=context)
        if run is None:
            return self._no_run(context=context)
        stored_scope = run.get("scope") or {}
        input_authority = stored_scope.get(
            "scope_evidence_authority_sha256"
        )
        if not self._valid_hash(input_authority):
            return self._blocked_run(context=context)
        return self._run_result(
            context=context,
            inputs={
                "status": "stored",
                "source_gaps": [],
                "blockers": [],
                "scope_evidence_authority_sha256": input_authority,
                "observation_snapshot_sha256": stored_scope.get(
                    "scoped_observation_snapshot_sha256"
                ),
                "catalog_snapshot_sha256": stored_scope.get(
                    "scoped_catalog_snapshot_sha256"
                ),
                "economics_snapshot_sha256": stored_scope.get(
                    "scoped_economics_snapshot_sha256"
                ),
                "product_content_snapshot_sha256": stored_scope.get(
                    "scoped_product_content_snapshot_sha256"
                ),
            },
            run=run,
        )

    def latest_scoped(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Compatibility name for scoped read-model composers."""
        return self.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )

    def market_radar(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        timezone: str = "UTC",
        display_currency: str = "CNY",
        source_grades: tuple[str, ...] = ("A", "B", "C"),
        max_age_hours: int = 168,
        target_purchase_quantity: int = 3,
        page_size: int = 500,
        max_rows: int = 50000,
    ) -> dict[str, Any]:
        """Project exact identity cohorts without scoring or promoting facts."""
        query = self._market_radar_query(
            timezone=timezone,
            display_currency=display_currency,
            source_grades=source_grades,
            max_age_hours=max_age_hours,
            target_purchase_quantity=target_purchase_quantity,
            page_size=page_size,
            max_rows=max_rows,
        )
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            return self._empty_market_radar(
                context=context,
                query=query,
            )
        ozon = self.scoped_observations.collect(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            marketplace="ozon",
            page_size=query["page_size"],
            max_rows=query["max_rows"],
        )
        suppliers = _merge_supplier_projections(
            [
                self.scoped_observations.collect(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=context["cutoff"],
                    marketplace=marketplace,
                    page_size=query["page_size"],
                    max_rows=query["max_rows"],
                )
                for marketplace in sorted(SUPPLIER_MARKETPLACES)
            ]
        )
        catalog = self.scoped_catalog.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            limit=min(query["max_rows"], 1000),
        )
        projections = (ozon, suppliers, catalog)
        source_gaps = {
            gap
            for projection in projections
            for gap in projection.get("source_gaps", [])
        }
        blockers = [
            blocker
            for projection in projections
            for blocker in projection.get("blockers", [])
        ]
        if ozon.get("pagination", {}).get("truncated"):
            source_gaps.add("market_radar_ozon_scan_truncated")
        if suppliers.get("pagination", {}).get("truncated"):
            source_gaps.add("market_radar_supplier_scan_truncated")
        return self._market_radar_result(
            context=context,
            query=query,
            ozon=ozon,
            suppliers=suppliers,
            catalog=catalog,
            source_gaps=source_gaps,
            blockers=blockers,
        )

    def _market_radar_result(
        self,
        *,
        context: dict[str, Any],
        query: dict[str, Any],
        ozon: dict[str, Any],
        suppliers: dict[str, Any],
        catalog: dict[str, Any],
        source_gaps: set[str],
        blockers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cutoff = context["cutoff"]
        max_age = timedelta(hours=query["max_age_hours"])
        accepted_grades = set(query["source_grades"])
        observed = [*ozon.get("items", []), *suppliers.get("items", [])]
        eligible: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        stale_count = 0
        disallowed_grade_count = 0
        for item in observed:
            grade = str(item.get("source_grade") or "").strip().upper()
            observed_at = self._timestamp(item["observed_at"])
            age = cutoff - observed_at
            reasons: list[str] = []
            if grade not in accepted_grades:
                reasons.append("source_grade_not_accepted")
                disallowed_grade_count += 1
            if age < timedelta(0) or age > max_age:
                reasons.append("observation_stale")
                stale_count += 1
            expected_candidate_key = exact_candidate_key(
                item.get("product_identity"),
                item.get("variant_key"),
            )
            if expected_candidate_key is None:
                reasons.append("exact_identity_or_variant_unresolved")
            elif item.get("candidate_key") != expected_candidate_key:
                reasons.append("candidate_key_identity_variant_mismatch")
            if reasons:
                unresolved.append(
                    {
                        "item_id": item.get("id"),
                        "marketplace": item.get("marketplace"),
                        "reasons": sorted(set(reasons)),
                        "evidence_id": item.get("evidence_id"),
                        "details_disclosed": False,
                    }
                )
                continue
            eligible.append(item)

        if disallowed_grade_count:
            source_gaps.add("market_radar_source_grade_not_accepted")
        if stale_count:
            source_gaps.add("market_radar_observation_stale")
        if unresolved:
            source_gaps.add("market_radar_identity_rows_unresolved")
        for currency in sorted(
            {
                str(item.get("currency") or "").strip().upper()
                for item in eligible
                if str(item.get("currency") or "").strip().upper()
                != query["display_currency"]
            }
        ):
            source_gaps.add(
                "market_radar_fx_not_applied:"
                f"{currency}/{query['display_currency']}"
            )

        own_offer_ids = {
            str(item.get("offer_id") or "").strip()
            for item in catalog.get("items", [])
            if str(item.get("offer_id") or "").strip()
        }
        own_product_ids = {
            str(item.get("canonical_product_id") or "").strip()
            for item in catalog.get("items", [])
            if str(item.get("canonical_product_id") or "").strip()
        }

        def is_own(item: dict[str, Any]) -> bool:
            offer_refs = {
                str(item.get("external_item_id") or "").strip(),
                str(item.get("target_offer_id") or "").strip(),
            }
            product_ref = str(item.get("target_product_id") or "").strip()
            return bool(
                own_offer_ids.intersection(offer_refs)
                or (product_ref and product_ref in own_product_ids)
            )

        by_candidate: dict[str, list[dict[str, Any]]] = {}
        for item in eligible:
            by_candidate.setdefault(item["candidate_key"], []).append(item)
        cohorts: list[dict[str, Any]] = []
        for candidate_key, items in sorted(by_candidate.items()):
            ordered = sorted(
                items,
                key=lambda item: (
                    item["marketplace"],
                    item["observed_at"],
                    item["fingerprint"],
                ),
            )
            ozon_rows = [
                item for item in ordered
                if item["marketplace"] == "ozon"
            ]
            own_rows = [item for item in ozon_rows if is_own(item)]
            competitor_rows = [
                item for item in ozon_rows if not is_own(item)
            ]
            supplier_rows = [
                item for item in ordered
                if is_supplier_marketplace(item["marketplace"])
            ]
            comparable_supplier_rows = [
                item
                for item in supplier_rows
                if item.get("price_kind") == "observed_checkout_price"
                and item.get("checkout_verified") is True
                and item.get("purchase_available") is True
                and item.get("observed_quantity")
                == query["target_purchase_quantity"]
                and int(item.get("min_order_quantity") or 1)
                <= query["target_purchase_quantity"]
            ]
            representative = ordered[0]
            evidence_ids = sorted(
                {
                    str(item["evidence_id"])
                    for item in ordered
                    if item.get("evidence_id")
                }
            )
            grades = self._count_values(
                str(item.get("source_grade") or "ungraded")
                for item in ordered
            )
            semantic_authorities = sorted(
                {
                    str(item.get("semantic_authority") or "legacy_observation")
                    for item in ordered
                }
            )
            cohorts.append(
                {
                    "candidate_key": candidate_key,
                    "product_identity": representative[
                        "product_identity"
                    ],
                    "variant_key": representative["variant_key"],
                    "counts": {
                        "observation_rows": len(ordered),
                        "own_listing_rows": len(own_rows),
                        "competitor_listing_rows": len(competitor_rows),
                        "unique_competitor_sellers": len(
                            {
                                item["supplier_ref"]
                                for item in competitor_rows
                                if item.get("supplier_ref")
                            }
                        ),
                        "supplier_option_rows": len(supplier_rows),
                        "unique_supplier_identities": len(
                            {
                                item["supplier_ref"]
                                for item in supplier_rows
                                if item.get("supplier_ref")
                            }
                        ),
                        "checkout_comparable_at_target": len(
                            comparable_supplier_rows
                        ),
                    },
                    "own_listing_current_facts": [
                        self._radar_item(item) for item in own_rows
                    ],
                    "competitor_price_bands": (
                        self.batch.market_price_bands(competitor_rows)
                    ),
                    "supplier_price_bands_at_target": (
                        self.batch.market_price_bands(
                            comparable_supplier_rows
                        )
                    ),
                    "supplier_alternative_rows": (
                        len(supplier_rows)
                        - len(comparable_supplier_rows)
                    ),
                    "target_purchase_quantity": query[
                        "target_purchase_quantity"
                    ],
                    "source_grade_counts": grades,
                    "semantic_authorities": semantic_authorities,
                    "freshness": {
                        "oldest_observed_at": min(
                            item["observed_at"] for item in ordered
                        ),
                        "newest_observed_at": max(
                            item["observed_at"] for item in ordered
                        ),
                        "max_age_hours": query["max_age_hours"],
                        "status": "fresh",
                    },
                    "evidence_ids": evidence_ids,
                    "sales_is_actual": False,
                    "supplier_offer_created": False,
                    "actual_cost_created": False,
                }
            )

        counts = {
            "observed_listings": len(observed),
            "evidence_bound_rows": len(observed),
            "eligible_exact_rows": len(eligible),
            "unique_exact_identities": len(cohorts),
            "own_listing_rows": sum(
                item["counts"]["own_listing_rows"] for item in cohorts
            ),
            "competitor_listing_rows": sum(
                item["counts"]["competitor_listing_rows"]
                for item in cohorts
            ),
            "unique_competitor_sellers": len(
                {
                    item["supplier_ref"]
                    for item in eligible
                    if item["marketplace"] == "ozon"
                    and not is_own(item)
                    and item.get("supplier_ref")
                }
            ),
            "supplier_option_rows": sum(
                item["counts"]["supplier_option_rows"]
                for item in cohorts
            ),
            "unique_supplier_identities": len(
                {
                    item["supplier_ref"]
                    for item in eligible
                    if is_supplier_marketplace(item["marketplace"])
                    and item.get("supplier_ref")
                }
            ),
            "checkout_comparable_at_target": sum(
                item["counts"]["checkout_comparable_at_target"]
                for item in cohorts
            ),
            "unresolved_or_filtered_rows": len(unresolved),
            "stale_rows": stale_count,
            "disallowed_grade_rows": disallowed_grade_count,
        }
        upstream_blocked = any(
            projection.get("status") == "blocked"
            for projection in (ozon, suppliers, catalog)
        )
        truncated = any(
            projection.get("pagination", {}).get("truncated")
            for projection in (ozon, suppliers)
        )
        if upstream_blocked:
            status = "blocked"
        elif not cohorts:
            status = "no_data"
        elif (
            unresolved
            or truncated
            or catalog.get("status") != "ready"
            or not any(
                cohort["counts"]["competitor_listing_rows"]
                for cohort in cohorts
            )
            or not any(
                cohort["counts"]["supplier_option_rows"]
                for cohort in cohorts
            )
        ):
            status = "partial"
        else:
            status = "ready"
        if status == "partial":
            blockers.append(
                self._blocker(
                    "market_radar_partial_coverage",
                    owner="market-data",
                )
            )
        payload = {
            "contract_id": "kjds-scoped-market-radar-v1",
            "status": status,
            "as_of": cutoff.isoformat(),
            "scope": context["scope"],
            "query": query,
            "counts": counts,
            "cohorts": cohorts,
            "unresolved": {
                "count": len(unresolved),
                "details_disclosed": False,
                "by_reason": self._count_values(
                    reason
                    for item in unresolved
                    for reason in item["reasons"]
                ),
            },
            "source_gaps": sorted(source_gaps),
            "blockers": blockers,
            "source_snapshots": {
                "ozon_observation_sha256": ozon.get(
                    "snapshot_sha256"
                ),
                "supplier_observation_sha256": suppliers.get(
                    "snapshot_sha256"
                ),
                "catalog_sha256": catalog.get("snapshot_sha256"),
            },
            "control_envelope": {
                "read_only": True,
                "research_only": True,
                "client_calculation_allowed": False,
                "candidate_scoring_performed": False,
                "sales_inferred": False,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "formal_cm3_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _empty_market_radar(
        self,
        *,
        context: dict[str, Any],
        query: dict[str, Any],
    ) -> dict[str, Any]:
        reason = str(context["reason"])
        payload = {
            "contract_id": "kjds-scoped-market-radar-v1",
            "status": context["status"],
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "query": query,
            "counts": {
                "observed_listings": 0,
                "evidence_bound_rows": 0,
                "eligible_exact_rows": 0,
                "unique_exact_identities": 0,
                "own_listing_rows": 0,
                "competitor_listing_rows": 0,
                "unique_competitor_sellers": 0,
                "supplier_option_rows": 0,
                "unique_supplier_identities": 0,
                "checkout_comparable_at_target": 0,
                "unresolved_or_filtered_rows": 0,
                "stale_rows": 0,
                "disallowed_grade_rows": 0,
            },
            "cohorts": [],
            "unresolved": {
                "count": 0,
                "details_disclosed": False,
                "by_reason": {},
            },
            "source_gaps": [reason],
            "blockers": [
                self._blocker(reason, owner="identity-governance")
            ],
            "source_snapshots": {},
            "control_envelope": {
                **self._closed_control(input_read=False),
                "client_calculation_allowed": False,
                "sales_inferred": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @staticmethod
    def _market_radar_query(
        *,
        timezone: str,
        display_currency: str,
        source_grades: tuple[str, ...],
        max_age_hours: int,
        target_purchase_quantity: int,
        page_size: int,
        max_rows: int,
    ) -> dict[str, Any]:
        normalized_timezone = str(timezone).strip()
        try:
            ZoneInfo(normalized_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Market Radar timezone is invalid") from exc
        currency = str(display_currency).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(
                "Market Radar display_currency must be ISO-4217"
            )
        grades = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in source_grades
                    if str(item).strip()
                }
            )
        )
        if not grades or any(item not in {"A", "B", "C", "D"} for item in grades):
            raise ValueError(
                "Market Radar source grades must be A, B, C or D"
            )
        if not 1 <= max_age_hours <= 24 * 365:
            raise ValueError(
                "Market Radar max_age_hours must be 1 to 8760"
            )
        if not 1 <= target_purchase_quantity <= 10000:
            raise ValueError(
                "Market Radar target_purchase_quantity must be 1 to 10000"
            )
        if not 1 <= page_size <= 1000:
            raise ValueError(
                "Market Radar page_size must be 1 to 1000"
            )
        if not 1 <= max_rows <= 50000:
            raise ValueError(
                "Market Radar max_rows must be 1 to 50000"
            )
        return {
            "timezone": normalized_timezone,
            "display_currency": currency,
            "source_grades": list(grades),
            "max_age_hours": max_age_hours,
            "target_purchase_quantity": target_purchase_quantity,
            "page_size": page_size,
            "max_rows": max_rows,
            "currency_conversion_performed": False,
        }

    @staticmethod
    def _radar_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "item_id": item["id"],
            "external_item_id": item.get("external_item_id"),
            "target_product_id": item.get("target_product_id"),
            "target_offer_id": item.get("target_offer_id"),
            "currency": item["currency"],
            "unit_price": item.get(
                "unit_price", item.get("displayed_price")
            ),
            "observed_at": item["observed_at"],
            "evidence_id": item["evidence_id"],
            "source_grade": item.get("source_grade"),
            "semantic_authority": item.get("semantic_authority"),
            "is_actual_sale_or_settlement": False,
        }

    @staticmethod
    def _count_values(values) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            key = str(value)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def _inputs(
        self,
        *,
        context: dict[str, Any],
        candidate_limit: int,
        scan_page_size: int,
    ) -> dict[str, Any]:
        max_rows = min(50000, max(candidate_limit * 2, scan_page_size))
        ozon = self.scoped_observations.collect(
            principal=context["principal"],
            entity_scope=context["entity_scope"],
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
            marketplace="ozon",
            page_size=scan_page_size,
            max_rows=max_rows,
        )
        suppliers = _merge_supplier_projections(
            [
                self.scoped_observations.collect(
                    principal=context["principal"],
                    entity_scope=context["entity_scope"],
                    store_ref=context["scope"]["store_ref"],
                    as_of=context["cutoff"],
                    marketplace=marketplace,
                    page_size=scan_page_size,
                    max_rows=max_rows,
                )
                for marketplace in sorted(SUPPLIER_MARKETPLACES)
            ]
        )
        catalog = self.scoped_catalog.latest(
            principal=context["principal"],
            entity_scope=context["entity_scope"],
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
            limit=min(candidate_limit, 1000),
        )
        product_content = (
            self.scoped_product_content.project_catalog(
                principal=context["principal"],
                entity_scope=context["entity_scope"],
                store_ref=context["scope"]["store_ref"],
                as_of=context["cutoff"],
                catalog_projection=catalog,
            )
            if self.scoped_product_content is not None
            else {
                "status": "no_data",
                "products": [],
                "source_gaps": [
                    "scoped_product_content_authority_not_configured"
                ],
                "blockers": [],
                "snapshot_sha256": self._hash(
                    {
                        "status": "no_data",
                        "as_of": context["cutoff"].isoformat(),
                        "scope": context["scope"],
                    }
                ),
            }
        )
        observations = [*ozon["items"], *suppliers["items"]]
        source_gaps = sorted(
            {
                *ozon["source_gaps"],
                *suppliers["source_gaps"],
                *catalog["source_gaps"],
                *product_content["source_gaps"],
            }
        )
        blockers = [
            *ozon["blockers"],
            *suppliers["blockers"],
            *catalog["blockers"],
            *product_content["blockers"],
        ]
        if ozon["pagination"].get("truncated"):
            source_gaps.append("ozon_observation_scan_truncated")
        if suppliers["pagination"].get("truncated"):
            source_gaps.append("supplier_observation_scan_truncated")
        if not ozon["items"]:
            source_gaps.append("scoped_ozon_observation_missing")
        if not suppliers["items"]:
            source_gaps.append("scoped_supplier_observation_missing")
        if not observations:
            return {
                "status": (
                    "blocked"
                    if (
                        ozon["status"] == "blocked"
                        or suppliers["status"] == "blocked"
                        or catalog["status"] == "blocked"
                    )
                    else "no_data"
                ),
                "observations": [],
                "catalog": catalog["items"],
                "product_content": {},
                "source_gaps": sorted(set(source_gaps)),
                "blockers": blockers,
                "scope_evidence_authority_sha256": None,
                "observation_snapshot_sha256": self._hash(
                    {
                        "ozon": ozon["snapshot_sha256"],
                        "suppliers": suppliers["snapshot_sha256"],
                    }
                ),
                "catalog_snapshot_sha256": catalog["snapshot_sha256"],
                "product_content_snapshot_sha256": product_content[
                    "snapshot_sha256"
                ],
            }
        fx_rates, fx_gaps = self._fx_rates(
            observations=observations,
            as_of=context["cutoff"],
        )
        source_gaps.extend(fx_gaps)
        evidence_ids = sorted(
            {
                *self._evidence_ids(observations),
                *(
                    str(rate["evidence_id"])
                    for rate in fx_rates.values()
                ),
            }
        )
        evidence_projection = self.scoped_evidence.project_targets(
            evidence_ids=evidence_ids,
            principal=context["principal"],
            entity_scope=context["entity_scope"],
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
        )
        target_records = {
            item["evidence_id"]: item
            for item in evidence_projection["records"]
            if item["evidence_id"] in evidence_ids
        }
        evidence_ready = (
            evidence_projection["status"] == "ready"
            and not evidence_projection["invalid_evidence_ids"]
            and set(target_records) == set(evidence_ids)
            and all(
                item["scope_binding"]["status"] == "ready"
                for item in target_records.values()
            )
        )
        if not evidence_ready:
            source_gaps.append("scoped_batch_component_evidence_not_ready")
            blockers.extend(evidence_projection["blockers"])
        if (
            ozon["status"] == "blocked"
            or suppliers["status"] == "blocked"
            or catalog["status"] == "blocked"
            or not evidence_ready
        ):
            status = "blocked"
        elif (
            not ozon["items"]
            or not suppliers["items"]
            or fx_gaps
        ):
            status = "no_data"
        else:
            status = "ready"
        observation_hash = self._hash(
            {
                "ozon": ozon["snapshot_sha256"],
                "suppliers": suppliers["snapshot_sha256"],
            }
        )
        evidence_hash = (
            evidence_projection["binding_authority_sha256"]
            if evidence_ready
            else None
        )
        economics_hash = self._hash(
            {
                currency: rate
                for currency, rate in sorted(fx_rates.items())
            }
        )
        scope_evidence_hash = (
            self._hash(
                {
                    "observation": observation_hash,
                    "catalog": catalog["snapshot_sha256"],
                    "economics": economics_hash,
                    "product_content": product_content[
                        "snapshot_sha256"
                    ],
                    "evidence": evidence_hash,
                }
            )
            if evidence_hash
            else None
        )
        return {
            "status": status,
            "observations": observations,
            "catalog": catalog["items"],
            "fx_rates": fx_rates,
            "product_content": {
                item["product"]["id"]: item
                for item in product_content["products"]
            },
            "source_gaps": sorted(set(source_gaps)),
            "blockers": blockers,
            "scope_evidence_authority_sha256": scope_evidence_hash,
            "observation_snapshot_sha256": observation_hash,
            "catalog_snapshot_sha256": catalog["snapshot_sha256"],
            "economics_snapshot_sha256": economics_hash,
            "product_content_snapshot_sha256": product_content[
                "snapshot_sha256"
            ],
            "counts": {
                "ozon_observations": len(ozon["items"]),
                "supplier_observations": len(suppliers["items"]),
                "catalog_items": len(catalog["items"]),
                "scoped_evidence": len(evidence_ids),
                "fx_rates": len(fx_rates),
                "product_content_products": len(
                    product_content["products"]
                ),
            },
        }

    def _fx_rates(
        self,
        *,
        observations: list[dict[str, Any]],
        as_of: datetime,
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        currencies = sorted(
            {
                str(item.get("currency") or "").strip().upper()
                for item in observations
                if str(item.get("currency") or "").strip().upper()
                not in {"", "CNY"}
            }
        )
        selected: dict[str, dict[str, Any]] = {}
        gaps: list[str] = []
        for currency in currencies:
            eligible = [
                rate
                for rate in self.batch.finance.list_fx_rates(
                    base_currency=currency
                )
                if rate.quote_currency == "CNY"
                and self._timestamp(rate.effective_at) <= as_of
                and self._timestamp(rate.recorded_at) <= as_of
            ]
            if not eligible:
                gaps.append(f"scoped_fx_rate_missing:{currency}/CNY")
                continue
            rate = max(
                eligible,
                key=lambda item: (
                    self._timestamp(item.effective_at),
                    item.version,
                    self._timestamp(item.recorded_at),
                    item.id,
                ),
            )
            selected[currency] = {
                "id": rate.id,
                "base_currency": rate.base_currency,
                "quote_currency": rate.quote_currency,
                "rate": rate.rate,
                "version": rate.version,
                "effective_at": rate.effective_at,
                "source": rate.source,
                "evidence_id": rate.evidence_id,
                "recorded_at": rate.recorded_at,
            }
        return selected, gaps

    def _run_result(
        self,
        *,
        context: dict[str, Any],
        inputs: dict[str, Any],
        run: dict[str, Any],
    ) -> dict[str, Any]:
        rule_snapshot = run.get("ozon_global_cn_rule_registry") or {}
        rule_gaps = [
            f"rule_source_evidence_gap:{item}"
            for item in rule_snapshot.get("source_evidence_gaps", [])
        ]
        source_gaps = sorted(
            {
                *inputs.get("source_gaps", []),
                *rule_gaps,
                *(
                    f"candidate_blocker:{item}"
                    for item in run.get("blockers", [])
                ),
            }
        )
        candidates = run.get("candidates", [])
        status = (
            "ready_with_constraints"
            if candidates
            else "no_data"
        )
        payload = {
            **run,
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "scope": run.get("scope") or {
                **context["scope"],
                "scope_evidence_authority_sha256": inputs.get(
                    "scope_evidence_authority_sha256"
                ),
            },
            "source_gaps": source_gaps,
            "blockers": [
                *inputs.get("blockers", []),
                *[
                    self._blocker(
                        item,
                        owner="candidate-economics",
                    )
                    for item in run.get("blockers", [])
                ],
            ],
            "control_envelope": {
                "read_only": False,
                "internal_research_run_created": True,
                "candidate_scoring_allowed": True,
                "research_only": True,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "formal_cm3_created": False,
                "approval_created": False,
                "permit_created": False,
                "pilot_started": False,
                "external_write_allowed": False,
            },
        }
        payload["scoped_snapshot_sha256"] = self._hash(
            {
                key: value
                for key, value in payload.items()
                if key != "scoped_snapshot_sha256"
            }
        )
        return payload

    def _input_result(
        self,
        *,
        context: dict[str, Any],
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": inputs["status"],
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "counts": inputs.get(
                "counts",
                {
                    "ozon_observations": 0,
                    "supplier_observations": 0,
                    "catalog_items": len(inputs.get("catalog", [])),
                    "scoped_evidence": 0,
                    "fx_rates": 0,
                    "product_content_products": 0,
                },
            ),
            "candidates": [],
            "source_gaps": inputs["source_gaps"],
            "blockers": inputs["blockers"],
            "control_envelope": self._closed_control(
                input_read=True,
            ),
        }
        payload["scoped_snapshot_sha256"] = self._hash(payload)
        return payload

    def _empty(self, *, context: dict[str, Any]) -> dict[str, Any]:
        reason = str(context["reason"])
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": context["status"],
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "counts": {
                "ozon_observations": 0,
                "supplier_observations": 0,
                "catalog_items": 0,
                "scoped_evidence": 0,
                "fx_rates": 0,
            },
            "candidates": [],
            "source_gaps": [reason],
            "blockers": [self._blocker(reason, owner="identity-governance")],
            "control_envelope": self._closed_control(
                input_read=False,
            ),
        }
        payload["scoped_snapshot_sha256"] = self._hash(payload)
        return payload

    def _no_run(self, *, context: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": "no_data",
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "counts": {},
            "candidates": [],
            "source_gaps": ["scoped_batch_run_not_available"],
            "blockers": [],
            "control_envelope": self._closed_control(
                input_read=False,
            ),
        }
        payload["scoped_snapshot_sha256"] = self._hash(payload)
        return payload

    def _blocked_run(self, *, context: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": "blocked",
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "counts": {},
            "candidates": [],
            "source_gaps": ["scoped_batch_run_integrity_failed"],
            "blockers": [
                self._blocker(
                    "scoped_batch_run_integrity_failed",
                    owner="evidence-governance",
                )
            ],
            "control_envelope": self._closed_control(
                input_read=False,
            ),
        }
        payload["scoped_snapshot_sha256"] = self._hash(payload)
        return payload

    @staticmethod
    def _context(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        cutoff = as_of.astimezone(UTC)
        entity_ready = (
            entity_scope.get("status") == "ready"
            and bool(entity_scope.get("entity_ref"))
            and ScopedBatchOpportunityAuthority._valid_hash(
                entity_scope.get("authority_sha256")
            )
        )
        status = (
            "ready"
            if entity_ready
            else "blocked"
            if entity_scope.get("status") == "blocked"
            else "no_data"
        )
        return {
            "status": status,
            "reason": (
                None
                if entity_ready
                else entity_scope.get(
                    "reason",
                    "entity_scope_authority_missing",
                )
            ),
            "cutoff": cutoff,
            "principal": principal,
            "entity_scope": entity_scope,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (
                    str(entity_scope["entity_ref"])
                    if entity_ready
                    else None
                ),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    entity_scope.get("authority_sha256")
                    if entity_ready
                    else None
                ),
            },
        }

    @classmethod
    def _evidence_ids(cls, value: Any) -> set[str]:
        result: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("evidence_id") and isinstance(child, str):
                    normalized = child.strip()
                    if normalized:
                        result.add(normalized)
                else:
                    result.update(cls._evidence_ids(child))
        elif isinstance(value, list):
            for child in value:
                result.update(cls._evidence_ids(child))
        return result

    @staticmethod
    def _closed_control(*, input_read: bool) -> dict[str, Any]:
        return {
            "read_only": True,
            "scoped_input_read": input_read,
            "internal_research_run_created": False,
            "candidate_scoring_allowed": False,
            "research_only": True,
            "supplier_offer_created": False,
            "actual_cost_created": False,
            "formal_cm3_created": False,
            "approval_created": False,
            "permit_created": False,
            "pilot_started": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _blocker(code: str, *, owner: str) -> dict[str, Any]:
        return {
            "code": code,
            "severity": (
                "P0"
                if any(
                    token in code
                    for token in ("integrity", "mismatch", "conflict")
                )
                else "P1"
            ),
            "owner": owner,
            "sla": "before candidate scoring or approval allocation",
            "next": (
                "Bind current source and cost Evidence to the exact "
                "tenant/entity/store, then rerun the deterministic scan."
            ),
            "next_workspace": "/commerce-os",
        }

    @staticmethod
    def _valid_hash(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(
                character in "0123456789abcdef"
                for character in value
            )
        )

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            raise ValueError("Scoped authority timestamps require timezone")
        return parsed.astimezone(UTC)

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
