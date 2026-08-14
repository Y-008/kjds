from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import unquote, urlparse


class AutomatedCommerceLoop:
    """Compile capture, profit, Listing and supplier truth into one interface.

    The module owns no business records.  It advances the existing AI Listing
    pipeline and projects exact links across its existing authoritative stores.
    """

    CONTRACT_ID = "kjds-automated-commerce-loop-v1"
    CATALOG_CONTRACT_ID = "kjds-scoped-marketplace-catalog-v1"
    SOURCING_CONTRACT_ID = (
        "kjds-native-exact-scope-sourcing-intelligence-workspace-v1"
    )
    # The projection points back to the existing dashboard seam.  This keeps
    # RFQ creation, dispatch evidence and quote review in the one authoritative
    # workspace instead of introducing a second sender or task ledger.
    RFQ_WORKSPACE_HREF = "/#sourcing"
    _STORE_URL_KEYS = (
        "supplier_store_url",
        "store_url",
        "shop_url",
    )
    _OZON_SKU = re.compile(r"(?<!\d)(\d{6,20})(?!\d)")
    _SHA256 = re.compile(r"[0-9a-f]{64}")
    _REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,119}")
    _SOURCING_STATUSES = frozenset(
        {"ready", "partial", "no_data", "blocked", "ready_with_constraints"}
    )
    _CATALOG_STATUSES = frozenset({"ready", "partial", "no_data", "blocked"})
    _SOURCING_AUTHORITY_KEYS = frozenset(
        {
            "pim_snapshot_sha256",
            "market_radar_snapshot_sha256",
            "batch_opportunity_snapshot_sha256",
            "artifact_evidence_authority_sha256",
        }
    )

    def __init__(
        self,
        *,
        ai_listing,
        repository,
        sourcing_store,
        scoped_catalog,
        sourcing_intelligence=None,
    ) -> None:
        self.ai_listing = ai_listing
        self.repository = repository
        self.sourcing_store = sourcing_store
        self.scoped_catalog = scoped_catalog
        self.sourcing_intelligence = sourcing_intelligence

    def start(
        self,
        *,
        capture_submission_id: str,
        selected_variant_key: str,
        store_ref: str,
        as_of: datetime,
        idempotency_key: str,
        principal,
        entity_scope: dict[str, Any],
        requested_mode: str = "manual_each_action",
    ) -> dict[str, Any]:
        """Manually create one internal dry-run; automatic runtime is not connected."""

        self._scope_context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if requested_mode != "manual_each_action":
            raise PermissionError(
                "Automated commerce runtime is not connected; only manual internal dry-run is admitted"
            )

        created = self.ai_listing.create(
            capture_submission_id=capture_submission_id,
            store_ref=store_ref,
            selected_variant_key=selected_variant_key,
            target_marketplace="ozon",
            target_locale="ru-RU",
            mode="internal_dry_run",
            as_of=as_of,
            idempotency_key=idempotency_key,
            principal=principal,
            entity_scope=entity_scope,
        )
        if not isinstance(created, Mapping) or not str(created.get("id") or ""):
            raise RuntimeError("AI Listing create projection is invalid")
        run = self.ai_listing.process(
            created["id"],
            worker_id=f"automated-commerce:{principal.actor_id}",
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        if (
            not isinstance(run, Mapping)
            or not str(run.get("status") or "")
            or "id" not in run
        ):
            raise RuntimeError("AI Listing process projection is invalid")
        return {
            "contract_id": self.CONTRACT_ID,
            "status": run["status"],
            "run": run,
            "next_action": run.get("next_action"),
            "automation_control": {
                "requested_mode": requested_mode,
                "effective_mode": "manual_each_action",
                "grant_ready": False,
                "runtime_execution_enabled": False,
                "preference_is_grant": False,
            },
            "control_envelope": self._control_envelope(),
        }

    def workspace(
        self,
        *,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        listing_ref: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Project automatic Listing progress and exact supplier linkback."""

        cutoff, expected_scope = self._scope_context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        limit = min(max(int(limit), 1), 200)
        try:
            catalog = self.scoped_catalog.latest(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                limit=1000,
            )
            self._validate_catalog_projection(
                catalog,
                expected_scope=expected_scope,
                cutoff=cutoff,
            )
        except (KeyError, RuntimeError, TypeError, ValueError):
            return self._blocked_workspace(
                cutoff=cutoff,
                scope=expected_scope,
                listing_ref=listing_ref,
                reason="marketplace_catalog_projection_invalid",
            )
        drafts = self.sourcing_store.list_listing_drafts_scoped(
            tenant_ref=principal.tenant_ref,
            entity_ref=str(entity_scope.get("entity_ref") or ""),
            store_ref=store_ref,
            as_of=cutoff,
            limit=1000,
        )
        if not isinstance(drafts, list):
            return self._blocked_workspace(
                cutoff=cutoff,
                scope=expected_scope,
                listing_ref=listing_ref,
                reason="listing_draft_projection_invalid",
            )
        try:
            drafts = self._latest_drafts(drafts)
        except (AttributeError, TypeError, ValueError):
            return self._blocked_workspace(
                cutoff=cutoff,
                scope=expected_scope,
                listing_ref=listing_ref,
                reason="listing_draft_projection_invalid",
            )
        run_projection = self.ai_listing.list(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            limit=200,
        )
        if (
            not isinstance(run_projection, Mapping)
            or not isinstance(run_projection.get("items"), list)
            or any(not isinstance(item, Mapping) for item in run_projection["items"])
        ):
            return self._blocked_workspace(
                cutoff=cutoff,
                scope=expected_scope,
                listing_ref=listing_ref,
                reason="ai_listing_projection_invalid",
            )
        runs = run_projection["items"]
        catalog_items = list(catalog.get("items") or [])
        lookup = self._resolve_lookup(
            listing_ref=listing_ref,
            catalog_items=catalog_items,
        )
        projected_catalog_items = catalog_items
        if lookup["requested"]:
            product_ids = set(lookup["product_ids"])
            drafts = [draft for draft in drafts if draft.product_id in product_ids]
            if lookup["kind"] == "marketplace_sku":
                projected_catalog_items = [
                    item
                    for item in catalog_items
                    if str(item.get("marketplace_sku") or "").strip()
                    == lookup["normalized_value"]
                ]
            elif lookup["kind"] == "seller_offer_id":
                projected_catalog_items = [
                    item
                    for item in catalog_items
                    if str(item.get("offer_id") or "").strip()
                    == lookup["normalized_value"]
                ]

        sourcing_projection = self._sourcing_projection(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            expected_scope=expected_scope,
        )
        items = [
            self._item(
                draft=draft,
                catalog_items=projected_catalog_items,
                runs=runs,
                sourcing_projection=sourcing_projection,
            )
            for draft in drafts[:limit]
        ]
        source_gaps = sorted(
            {
                *catalog.get("source_gaps", []),
                *lookup["reasons"],
                *(
                    ["listing_source_binding_not_found"]
                    if lookup["requested"] and not items
                    else []
                ),
                *[
                    reason
                    for item in items
                    for reason in item["source_gaps"]
                ],
            }
        )
        status = (
            "not_found"
            if lookup["requested"] and not items
            else "no_data"
            if not items
            else "blocked"
            if all(item["status"] == "blocked" for item in items)
            else "partial"
            if source_gaps or any(item["status"] != "ready" for item in items)
            else "ready"
        )
        result = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": cutoff.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": str(entity_scope.get("entity_ref") or ""),
                "store_ref": store_ref,
            },
            "lookup": lookup,
            "items": items,
            "counts": {
                "items": len(items),
                "profit_recommended": sum(
                    item["profit_recommendation"]["verdict"] == "recommended"
                    for item in items
                ),
                "awaiting_profit_evidence": sum(
                    item["profit_recommendation"]["verdict"]
                    == "awaiting_evidence"
                    for item in items
                ),
                "purchase_links_ready": sum(
                    bool(item["sourcing"]["purchase_url"]) for item in items
                ),
                "platform_links_observed": sum(
                    bool(item["listing"]["listing_url"]) for item in items
                ),
                "rfq_drafts_ready": sum(
                    bool(
                        (item["rfq"].get("rfq_and_quotes") or {}).get(
                            "rfq_draft_ready"
                        )
                    )
                    for item in items
                ),
                "three_accepted_quotes_ready": sum(
                    bool(
                        (item["rfq"].get("rfq_and_quotes") or {}).get(
                            "three_accepted_quotes_ready"
                        )
                    )
                    for item in items
                ),
                "rfq_blocked": sum(
                    item["rfq"]["status"] == "blocked" for item in items
                ),
            },
            "source_gaps": source_gaps,
            "blockers": [self._blocker(reason) for reason in source_gaps],
            "control_envelope": self._control_envelope(),
        }
        result["snapshot_sha256"] = self._hash(result)
        return result

    def _item(
        self,
        *,
        draft,
        catalog_items: list[dict[str, Any]],
        runs: list[dict[str, Any]],
        sourcing_projection: dict[str, Any],
    ) -> dict[str, Any]:
        reasons: list[str] = []
        try:
            product = self.repository.get_product(draft.product_id)
        except KeyError:
            product = None
            reasons.append("canonical_product_not_found")
        try:
            offer = self.sourcing_store.get_offer(draft.offer_id)
        except KeyError:
            offer = None
            reasons.append("supplier_offer_not_found")
        try:
            scenario = self.sourcing_store.get_scenario(draft.scenario_id)
        except KeyError:
            scenario = None
            reasons.append("profit_scenario_not_found")
        if offer is not None and offer.product_id != draft.product_id:
            reasons.append("supplier_offer_product_mismatch")
        if scenario is not None and scenario.offer_id != draft.offer_id:
            reasons.append("profit_scenario_supplier_offer_mismatch")

        observed = [
            item
            for item in catalog_items
            if str(item.get("canonical_product_id") or "") == draft.product_id
        ]
        observed.sort(
            key=lambda item: (
                str(item.get("observed_at") or ""),
                str(item.get("offer_id") or ""),
            ),
            reverse=True,
        )
        if len({str(item.get("offer_id") or "") for item in observed}) > 1:
            reasons.append("multiple_current_marketplace_listings_for_product")
        listing = observed[0] if observed else None
        marketplace_sku = (
            str(listing.get("marketplace_sku") or "").strip()
            if listing
            else ""
        )
        listing_url = self._ozon_listing_url(marketplace_sku)
        if listing is not None and not listing_url:
            reasons.append("platform_listing_url_not_derivable")
        elif listing is None:
            reasons.append("platform_listing_not_observed")

        run = self._run_for_draft(draft=draft, runs=runs)
        profit = self._profit_recommendation(scenario)
        rfq = self._rfq_for_product(
            product_id=draft.product_id,
            sourcing_projection=sourcing_projection,
        )
        reasons.extend(rfq.get("source_gaps", []))
        if profit["verdict"] == "awaiting_evidence":
            reasons.append("formal_profit_evidence_incomplete")
        source_url = offer.source_url if offer is not None else None
        store_url = self._supplier_store_url(offer.attributes if offer else {})
        item = {
            "status": (
                "blocked"
                if self._has_blocking_reason(reasons)
                or rfq["status"] == "blocked"
                else "partial"
                if reasons or rfq["status"] != "ready"
                else "ready"
            ),
            "identity": {
                "product_id": draft.product_id,
                "kjds_sku": product.sku if product else None,
                "product_name": product.name if product else None,
                "listing_draft_id": draft.id,
                "supplier_offer_id": draft.offer_id,
                "profit_scenario_id": draft.scenario_id,
            },
            "listing": {
                "marketplace": "ozon",
                "seller_offer_id": (
                    str(listing.get("offer_id") or "") if listing else None
                ),
                "marketplace_sku": marketplace_sku or None,
                "listing_url": listing_url,
                "observed_at": listing.get("observed_at") if listing else None,
                "source_evidence_id": listing.get("source_evidence_id") if listing else None,
                "binding_status": "observed" if listing else "awaiting_catalog_readback",
            },
            "sourcing": {
                "platform": str(offer.platform) if offer else None,
                "supplier_ref": offer.supplier_ref if offer else None,
                "supplier_external_item_id": offer.external_id if offer else None,
                "purchase_url": source_url,
                "supplier_store_url": store_url,
                "seller_action": "open_purchase_url_and_buy_manually" if source_url else "resolve_formal_supplier_offer",
                "automatic_order": False,
                "automatic_payment": False,
                "evidence_ref": offer.evidence_ref if offer else None,
            },
            "profit_recommendation": profit,
            "rfq": rfq,
            "automation": {
                "run_id": run.get("id") if run else None,
                "status": run.get("status") if run else "not_started",
                "current_stage": run.get("current_stage") if run else None,
                "next_action": run.get("next_action") if run else None,
                "external_publish_automatic": False,
            },
            "source_gaps": sorted(set(reasons)),
        }
        item["item_sha256"] = self._hash(item)
        return item

    def _sourcing_projection(
        self,
        *,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        expected_scope: dict[str, Any],
    ) -> dict[str, Any]:
        """Read the existing scoped RFQ/quote projection, never raw lists."""

        if self.sourcing_intelligence is None:
            return {
                "status": "not_configured",
                "work_items": [],
                "source_gaps": ["sourcing_intelligence_not_configured"],
                "authority": {},
            }
        work_items: list[dict[str, Any]] = []
        source_gaps: set[str] = set()
        page_snapshots: list[str] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        authority: dict[str, Any] | None = None
        expected_total: int | None = None
        status = "no_data"
        while True:
            try:
                projection = self.sourcing_intelligence.project(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of,
                    page_size=200,
                    cursor=cursor,
                    target_purchase_quantity=1,
                )
            except (KeyError, RuntimeError, TypeError, ValueError):
                return {
                    "status": "blocked",
                    "work_items": [],
                    "source_gaps": [
                        "sourcing_intelligence_projection_failed"
                    ],
                    "authority": {},
                }
            if not isinstance(projection, dict):
                return {
                    "status": "blocked",
                    "work_items": [],
                    "source_gaps": [
                        "sourcing_intelligence_projection_invalid"
                    ],
                    "authority": {},
                }
            try:
                page_contract = self._validate_sourcing_page(
                    projection,
                    expected_scope=expected_scope,
                    cutoff=as_of,
                    requested_cursor=cursor,
                )
            except (KeyError, TypeError, ValueError):
                return {
                    "status": "blocked",
                    "work_items": [],
                    "source_gaps": [
                        "sourcing_intelligence_projection_invalid"
                    ],
                    "authority": {},
                }
            page_items = projection.get("work_items")
            query = projection.get("query") or {}
            if not isinstance(page_items, list) or not isinstance(query, dict):
                return {
                    "status": "blocked",
                    "work_items": [],
                    "source_gaps": [
                        "sourcing_intelligence_projection_invalid"
                    ],
                    "authority": {},
                }
            if any(not isinstance(item, dict) for item in page_items):
                return {
                    "status": "blocked",
                    "work_items": [],
                    "source_gaps": [
                        "sourcing_intelligence_projection_invalid"
                    ],
                    "authority": {},
                }
            page_authority = {
                "contract_id": projection.get("contract_id"),
                "status": projection.get("status"),
                "as_of": projection.get("as_of"),
                "scope": projection.get("scope"),
                "upstream_authority": projection.get("upstream_authority") or {},
            }
            if authority is None:
                authority = page_authority
                status = str(projection.get("status") or "no_data")
                expected_total = page_contract["total_work_items"]
            elif page_authority != authority:
                return {
                    "status": "blocked",
                    "work_items": [],
                    "source_gaps": [
                        "sourcing_intelligence_page_authority_mismatch"
                    ],
                    "authority": {},
                }
            elif page_contract["total_work_items"] != expected_total:
                return {
                    "status": "blocked",
                    "work_items": [],
                    "source_gaps": [
                        "sourcing_intelligence_page_count_mismatch"
                    ],
                    "authority": {},
                }
            work_items.extend(page_items)
            source_gaps.update(
                str(item)
                for item in (projection.get("source_gaps") or [])
                if str(item).strip()
            )
            page_snapshot = str(projection.get("snapshot_sha256") or "").strip()
            if page_snapshot:
                page_snapshots.append(page_snapshot)
            next_cursor = str(query.get("next_cursor") or "").strip() or None
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                return {
                    "status": "blocked",
                    "work_items": [],
                    "source_gaps": [
                        "sourcing_intelligence_pagination_cycle"
                    ],
                    "authority": {},
                }
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        if len(work_items) != (expected_total or 0):
            return {
                "status": "blocked",
                "work_items": [],
                "source_gaps": [
                    "sourcing_intelligence_pagination_incomplete"
                ],
                "authority": {},
            }

        keys = [str(item.get("work_item_key") or "") for item in work_items]
        if any(not key for key in keys) or len(set(keys)) != len(keys):
            return {
                "status": "blocked",
                "work_items": [],
                "source_gaps": [
                    "sourcing_intelligence_work_item_identity_invalid"
                ],
                "authority": {},
            }
        return {
            "status": status,
            "work_items": work_items,
            "source_gaps": sorted(source_gaps),
            "authority": {
                **(authority or {}),
                "page_snapshot_sha256": page_snapshots,
            },
        }

    @classmethod
    def _scope_context(
        cls,
        *,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> tuple[datetime, dict[str, Any]]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = str(entity_scope.get("authority_sha256") or "").strip()
        if (
            entity_scope.get("status") != "ready"
            or not entity_ref
            or not cls._SHA256.fullmatch(authority)
        ):
            raise ValueError("entity_scope current authority is not ready")
        cutoff = as_of.astimezone(UTC)
        return cutoff, {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": authority,
        }

    @classmethod
    def _validate_catalog_projection(
        cls,
        projection: Any,
        *,
        expected_scope: dict[str, Any],
        cutoff: datetime,
    ) -> None:
        if not isinstance(projection, Mapping):
            raise ValueError("catalog projection must be an object")
        cls._validate_projection_identity(
            projection,
            contract_id=cls.CATALOG_CONTRACT_ID,
            expected_scope=expected_scope,
            cutoff=cutoff,
        )
        items = projection.get("items")
        counts = projection.get("counts")
        excluded = projection.get("excluded")
        control = projection.get("control_envelope")
        if (
            projection.get("status") not in cls._CATALOG_STATUSES
            or
            not isinstance(items, list)
            or any(not isinstance(item, Mapping) for item in items)
            or not isinstance(counts, Mapping)
            or not isinstance(excluded, Mapping)
            or not isinstance(control, Mapping)
        ):
            raise ValueError("catalog projection shape drifted")
        cls._validate_reason_codes(
            projection.get("source_gaps"), label="catalog source_gaps"
        )
        blockers = projection.get("blockers")
        if not isinstance(blockers, list) or any(
            not isinstance(item, Mapping) for item in blockers
        ):
            raise ValueError("catalog blockers shape drifted")
        for item in items:
            if any(
                value is not None and not isinstance(value, str)
                for value in (
                    item.get("offer_id"),
                    item.get("marketplace_sku"),
                    item.get("canonical_product_id"),
                    item.get("observed_at"),
                    item.get("source_evidence_id"),
                )
            ):
                raise ValueError("catalog item identity drifted")
        identity_bindings: dict[tuple[str, str], str] = {}
        for item in items:
            identity = (
                str(item.get("offer_id") or "").strip(),
                str(item.get("marketplace_sku") or "").strip(),
            )
            product_id = str(item.get("canonical_product_id") or "").strip()
            if not any(identity):
                continue
            prior = identity_bindings.setdefault(identity, product_id)
            if prior != product_id:
                raise ValueError("catalog identity maps to multiple products")
        numeric = {
            key: cls._nonnegative_int(counts.get(key), f"catalog counts.{key}")
            for key in (
                "queried_in_exact_store_scope",
                "included",
                "excluded",
                "bound_to_canonical_product",
            )
        }
        if (
            numeric["included"] != len(items)
            or numeric["queried_in_exact_store_scope"]
            != numeric["included"] + numeric["excluded"]
            or numeric["bound_to_canonical_product"]
            != sum(bool(item.get("canonical_product_id")) for item in items)
            or cls._nonnegative_int(excluded.get("count"), "catalog excluded.count")
            != numeric["excluded"]
        ):
            raise ValueError("catalog count conservation failed")
        by_reason = excluded.get("by_reason")
        if not isinstance(by_reason, Mapping) or any(
            not isinstance(key, str)
            or cls._nonnegative_int(value, "catalog excluded.by_reason") < 0
            for key, value in by_reason.items()
        ):
            raise ValueError("catalog exclusion reasons drifted")
        if sum(by_reason.values()) != numeric["excluded"]:
            raise ValueError("catalog exclusion reason count drifted")
        if control.get("read_only") is not True or control.get(
            "external_write_allowed"
        ) is not False:
            raise ValueError("catalog control envelope drifted")

    @classmethod
    def _validate_sourcing_page(
        cls,
        projection: Mapping[str, Any],
        *,
        expected_scope: dict[str, Any],
        cutoff: datetime,
        requested_cursor: str | None,
    ) -> dict[str, int]:
        cls._validate_projection_identity(
            projection,
            contract_id=cls.SOURCING_CONTRACT_ID,
            expected_scope=expected_scope,
            cutoff=cutoff,
        )
        status = projection.get("status")
        query = projection.get("query")
        counts = projection.get("counts")
        items = projection.get("work_items")
        control = projection.get("control_envelope")
        if (
            status not in cls._SOURCING_STATUSES
            or not isinstance(query, Mapping)
            or not isinstance(counts, Mapping)
            or not isinstance(items, list)
            or any(not isinstance(item, Mapping) for item in items)
            or not isinstance(control, Mapping)
        ):
            raise ValueError("sourcing projection shape drifted")
        cls._validate_reason_codes(
            projection.get("source_gaps"), label="sourcing source_gaps"
        )
        upstream_authority = projection.get("upstream_authority")
        if (
            not isinstance(upstream_authority, Mapping)
            or set(upstream_authority) != cls._SOURCING_AUTHORITY_KEYS
            or any(
                not isinstance(value, str) or not cls._SHA256.fullmatch(value)
                for value in upstream_authority.values()
            )
        ):
            raise ValueError("sourcing upstream authority drifted")
        if (
            query.get("cursor") != requested_cursor
            or query.get("page_size") != 200
            or query.get("target_purchase_quantity") != 1
        ):
            raise ValueError("sourcing query contract drifted")
        total = cls._nonnegative_int(
            counts.get("total_work_items"), "sourcing total_work_items"
        )
        page = cls._nonnegative_int(
            counts.get("page_work_items"), "sourcing page_work_items"
        )
        if page != len(items) or total < page:
            raise ValueError("sourcing count conservation failed")
        for item in items:
            cls._validate_sourcing_work_item(item)
        if control.get("read_only") is not True or any(
            control.get(key) is not False
            for key in (
                "supplier_contacted",
                "rfq_dispatched",
                "quote_accepted",
                "purchase_order_created",
                "payment_created",
                "approval_created",
                "permit_created",
                "external_write_allowed",
            )
        ):
            raise ValueError("sourcing control envelope drifted")
        return {"total_work_items": total, "page_work_items": page}

    @classmethod
    def _validate_sourcing_work_item(cls, item: Mapping[str, Any]) -> None:
        work_item_key = item.get("work_item_key")
        product_ids = item.get("canonical_product_ids")
        readiness = item.get("readiness")
        rfq = item.get("rfq_and_quotes")
        if (
            not isinstance(work_item_key, str)
            or not work_item_key.strip()
            or not isinstance(product_ids, list)
            or not product_ids
            or any(not isinstance(value, str) or not value.strip() for value in product_ids)
            or len(set(product_ids)) != len(product_ids)
            or not isinstance(readiness, Mapping)
            or readiness.get("status") not in cls._SOURCING_STATUSES
            or not isinstance(rfq, Mapping)
        ):
            raise ValueError("sourcing work item shape drifted")
        for key in (
            "rfq_packages",
            "dispatch_proofs",
            "quotes",
            "accepted_unique_suppliers",
        ):
            if not isinstance(rfq.get(key, []), list):
                raise ValueError("sourcing RFQ collection drifted")
        for key in ("rfq_draft_ready", "three_accepted_quotes_ready"):
            if key in readiness and not isinstance(readiness[key], bool):
                raise ValueError("sourcing readiness truth drifted")
            if key in rfq and not isinstance(rfq[key], bool):
                raise ValueError("sourcing RFQ truth drifted")
        cls._validate_reason_codes(
            item.get("source_gaps", []), label="sourcing work item source_gaps"
        )

    @classmethod
    def _validate_reason_codes(cls, value: Any, *, label: str) -> None:
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not cls._REASON_CODE.fullmatch(item)
            for item in value
        ):
            raise ValueError(f"{label} must contain reason codes")

    @classmethod
    def _validate_projection_identity(
        cls,
        projection: Mapping[str, Any],
        *,
        contract_id: str,
        expected_scope: dict[str, Any],
        cutoff: datetime,
    ) -> None:
        if (
            projection.get("contract_id") != contract_id
            or projection.get("as_of") != cutoff.isoformat()
            or projection.get("scope") != expected_scope
        ):
            raise ValueError("projection authority identity drifted")
        snapshot = str(projection.get("snapshot_sha256") or "")
        if not cls._SHA256.fullmatch(snapshot):
            raise ValueError("projection snapshot is invalid")
        unsigned = dict(projection)
        unsigned.pop("snapshot_sha256", None)
        if snapshot != cls._hash(unsigned):
            raise ValueError("projection snapshot does not match payload")

    @staticmethod
    def _nonnegative_int(value: Any, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label} must be a non-negative integer")
        return value

    @classmethod
    def _blocked_workspace(
        cls,
        *,
        cutoff: datetime,
        scope: dict[str, Any],
        listing_ref: str | None,
        reason: str,
    ) -> dict[str, Any]:
        result = {
            "contract_id": cls.CONTRACT_ID,
            "status": "blocked",
            "as_of": cutoff.isoformat(),
            "scope": scope,
            "lookup": {
                "requested": bool(str(listing_ref or "").strip()),
                "input": None,
                "kind": None,
                "normalized_value": None,
                "product_ids": [],
                "matched_catalog_items": 0,
                "reasons": [reason],
            },
            "items": [],
            "counts": {
                "items": 0,
                "profit_recommended": 0,
                "awaiting_profit_evidence": 0,
                "purchase_links_ready": 0,
                "platform_links_observed": 0,
                "rfq_drafts_ready": 0,
                "three_accepted_quotes_ready": 0,
                "rfq_blocked": 0,
            },
            "source_gaps": [reason],
            "blockers": [cls._blocker(reason)],
            "control_envelope": cls._control_envelope(),
        }
        result["snapshot_sha256"] = cls._hash(result)
        return result

    @classmethod
    def _rfq_for_product(
        cls,
        *,
        product_id: str,
        sourcing_projection: dict[str, Any],
    ) -> dict[str, Any]:
        matches = [
            item
            for item in sourcing_projection.get("work_items", [])
            if product_id in (item.get("canonical_product_ids") or [])
        ]
        if len(matches) > 1:
            return {
                "status": "blocked",
                "work_item_key": None,
                "rfq_and_quotes": None,
                "next": "Resolve multiple scoped sourcing work items for this Product.",
                "next_workspace": cls.RFQ_WORKSPACE_HREF,
                "source_gaps": ["multiple_sourcing_work_items_for_product"],
                "external_contact_allowed": False,
                "projection_authority": sourcing_projection.get("authority") or {},
            }
        if not matches:
            status = sourcing_projection.get("status") or "no_data"
            return {
                "status": status,
                "work_item_key": None,
                "rfq_and_quotes": None,
                "next": (
                    "Create or locate the existing scoped RFQ package before supplier review."
                    if status == "no_data"
                    else "Resolve the scoped sourcing projection before supplier review."
                ),
                "next_workspace": cls.RFQ_WORKSPACE_HREF,
                "source_gaps": sorted(
                    set(sourcing_projection.get("source_gaps") or [])
                    | {"rfq_product_work_item_not_found"}
                ),
                "external_contact_allowed": False,
                "projection_authority": sourcing_projection.get("authority") or {},
            }
        item = matches[0]
        readiness = item.get("readiness") or {}
        rfq_and_quotes = item.get("rfq_and_quotes") or {}
        gaps = sorted(
            set(sourcing_projection.get("source_gaps") or [])
            | set(item.get("source_gaps") or [])
        )
        upstream_status = str(sourcing_projection.get("status") or "no_data")
        item_status = str(readiness.get("status") or "partial")
        effective_status = (
            item_status
            if upstream_status == "ready" and not gaps
            else "blocked"
            if upstream_status == "blocked"
            else "partial"
        )
        safe_rfq = dict(rfq_and_quotes)
        if effective_status in {"blocked", "no_data"}:
            safe_rfq["rfq_draft_ready"] = False
            safe_rfq["three_accepted_quotes_ready"] = False
        return {
            "status": effective_status,
            "work_item_key": item.get("work_item_key"),
            "rfq_and_quotes": safe_rfq,
            "next": item.get("next"),
            "next_workspace": cls.RFQ_WORKSPACE_HREF,
            "source_gaps": gaps,
            "external_contact_allowed": False,
            "projection_authority": sourcing_projection.get("authority") or {},
        }

    @classmethod
    def _resolve_lookup(
        cls,
        *,
        listing_ref: str | None,
        catalog_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raw = str(listing_ref or "").strip()
        if not raw:
            return {
                "requested": False,
                "input": None,
                "kind": None,
                "normalized_value": None,
                "product_ids": [],
                "matched_catalog_items": 0,
                "reasons": [],
            }
        kind, value, reasons = cls._listing_identity(raw)
        matches: list[dict[str, Any]] = []
        if not reasons and kind == "marketplace_sku":
            matches = [
                item
                for item in catalog_items
                if str(item.get("marketplace_sku") or "").strip() == value
            ]
        elif not reasons and kind == "seller_offer_id":
            matches = [
                item
                for item in catalog_items
                if str(item.get("offer_id") or "").strip() == value
            ]
        product_ids = sorted(
            {
                str(item.get("canonical_product_id") or "").strip()
                for item in matches
                if str(item.get("canonical_product_id") or "").strip()
            }
        )
        if matches and not product_ids:
            reasons.append("marketplace_listing_canonical_product_unbound")
        if len(product_ids) > 1:
            reasons.append("listing_identity_maps_to_multiple_products")
            product_ids = []
        if not matches and not product_ids and not reasons:
            reasons.append("marketplace_listing_identity_not_found")
        return {
            "requested": True,
            "input": raw,
            "kind": kind,
            "normalized_value": value,
            "product_ids": product_ids,
            "matched_catalog_items": len(matches),
            "reasons": sorted(set(reasons)),
        }

    @classmethod
    def _listing_identity(cls, raw: str) -> tuple[str | None, str | None, list[str]]:
        if raw.startswith(("http://", "https://")):
            parsed = urlparse(raw)
            host = (parsed.hostname or "").lower().rstrip(".")
            if host != "ozon.ru" and not host.endswith(".ozon.ru"):
                return None, None, ["listing_url_marketplace_not_supported"]
            path = unquote(parsed.path)
            values = cls._OZON_SKU.findall(path)
            if not values:
                return None, None, ["ozon_listing_url_sku_not_found"]
            return "marketplace_sku", values[-1], []
        if raw.isdigit():
            if not 6 <= len(raw) <= 20:
                return None, None, ["marketplace_sku_invalid"]
            return "marketplace_sku", raw, []
        if len(raw) > 200:
            return None, None, ["seller_offer_id_invalid"]
        return "seller_offer_id", raw, []

    @staticmethod
    def _latest_drafts(drafts: list[Any]) -> list[Any]:
        latest: dict[str, Any] = {}
        for draft in sorted(
            drafts,
            key=lambda item: (str(item.created_at), str(item.id)),
            reverse=True,
        ):
            latest.setdefault(draft.product_id, draft)
        return list(latest.values())

    @staticmethod
    def _run_for_draft(*, draft, runs: list[dict[str, Any]]) -> dict[str, Any] | None:
        matches = [
            run
            for run in runs
            if run.get("internal_refs", {}).get("listing_draft_id") == draft.id
            or run.get("bindings", {}).get("product_id") == draft.product_id
        ]
        return matches[0] if matches else None

    @staticmethod
    def _profit_recommendation(scenario) -> dict[str, Any]:
        if scenario is None:
            return {
                "verdict": "awaiting_evidence",
                "decision_method": "evidence_bound_decimal_profit_v1",
                "cm3_cny": None,
                "cm3_rate": None,
                "break_even_price_rub": None,
                "missing_cost_evidence": ["profit_scenario"],
                "unknown_costs": ["profit_scenario"],
                "evidence_ids": [],
                "ai_may_override": False,
            }
        try:
            cm3 = Decimal(str(scenario.cm3_cny))
            cm3_rate = Decimal(str(scenario.cm3_rate))
            break_even = Decimal(str(scenario.break_even_price_rub))
            missing = scenario.missing_cost_evidence
            unknown = scenario.unknown_costs
            evidence = scenario.evidence
            complete = scenario.cost_complete is True
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return AutomatedCommerceLoop._profit_recommendation(None)
        if (
            not all(value.is_finite() for value in (cm3, cm3_rate, break_even))
            or not isinstance(missing, list)
            or not isinstance(unknown, list)
            or not isinstance(evidence, list)
            or any(not isinstance(item, str) or not item.strip() for item in evidence)
            or any(not isinstance(item, str) or not item.strip() for item in missing)
            or any(not isinstance(item, str) or not item.strip() for item in unknown)
        ):
            return AutomatedCommerceLoop._profit_recommendation(None)
        evidence_complete = complete and not missing and not unknown and bool(evidence)
        verdict = (
            "awaiting_evidence"
            if not evidence_complete
            else "recommended"
            if cm3 > Decimal("0")
            else "not_recommended"
        )
        return {
            "verdict": verdict,
            "decision_method": "evidence_bound_decimal_profit_v1",
            "cm3_cny": str(cm3) if evidence_complete else None,
            "cm3_rate": str(cm3_rate) if evidence_complete else None,
            "break_even_price_rub": str(break_even) if evidence_complete else None,
            "missing_cost_evidence": list(missing),
            "unknown_costs": list(unknown),
            "evidence_ids": sorted(evidence),
            "explanation": {"release_ready": evidence_complete},
            "ai_may_override": False,
        }

    @classmethod
    def _supplier_store_url(cls, attributes: dict[str, Any]) -> str | None:
        if not isinstance(attributes, dict):
            return None
        for key in cls._STORE_URL_KEYS:
            value = str(attributes.get(key) or "").strip()
            if value.startswith(("http://", "https://")):
                return value
        return None

    @staticmethod
    def _ozon_listing_url(marketplace_sku: str) -> str | None:
        return (
            f"https://www.ozon.ru/product/{marketplace_sku}/"
            if marketplace_sku.isdigit() and 6 <= len(marketplace_sku) <= 20
            else None
        )

    @staticmethod
    def _blocker(reason: str) -> dict[str, str]:
        return {"code": reason, "severity": "blocking", "owner": "commerce-operations"}

    @staticmethod
    def _has_blocking_reason(reasons: list[str]) -> bool:
        return any(
            "mismatch" in reason
            or reason == "multiple_current_marketplace_listings_for_product"
            for reason in reasons
        )

    @staticmethod
    def _control_envelope() -> dict[str, Any]:
        return {
            "automatic_capture_intake": True,
            "manual_internal_listing_progress": True,
            "automatic_internal_listing_progress": False,
            "automation_runtime_connected": False,
            "grant_ready": False,
            "runtime_execution_enabled": False,
            "preference_is_grant": False,
            "profit_requires_formal_evidence": True,
            "external_publish_requires_existing_approval_permit_readback": True,
            "automatic_supplier_order": False,
            "automatic_payment": False,
            "source_of_truth_duplicated": False,
        }

    @staticmethod
    def _hash(value: Any) -> str:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
