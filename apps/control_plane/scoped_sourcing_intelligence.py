from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .security import Principal
from .sourcing import REQUIRED_COST_EVIDENCE_KEYS


class ScopedSourcingIntelligenceWorkspace:
    """Project one governed sourcing view without creating a new truth store."""

    CONTRACT_ID = (
        "kjds-native-exact-scope-sourcing-intelligence-workspace-v1"
    )
    ARTIFACT_CONTRACT_ID = "kjds-sourcing-research-artifact-v1"
    PIM_CONTRACT_ID = "kjds-native-exact-scope-pim-workspace-v1"
    RADAR_CONTRACT_ID = "kjds-scoped-market-radar-v1"
    BATCH_CONTRACT_ID = "kjds-scoped-batch-opportunity-v1"
    EVIDENCE_CONTRACT_ID = "kjds-scoped-evidence-authority-v1"
    UPSTREAM_STATUSES = frozenset(
        {
            "ready",
            "partial",
            "no_data",
            "blocked",
            "ready_with_constraints",
        }
    )
    READINESS_FILTERS = frozenset(
        {
            "research",
            "rfq",
            "three_quotes",
            "downside",
            "blocked",
        }
    )

    def __init__(
        self,
        *,
        pim,
        scoped_batch,
        scoped_evidence,
        supplier_rfq,
        supplier_rfq_dispatch,
        supplier_quote_authority,
    ) -> None:
        self.pim = pim
        self.scoped_batch = scoped_batch
        self.scoped_evidence = scoped_evidence
        self.supplier_rfq = supplier_rfq
        self.supplier_rfq_dispatch = supplier_rfq_dispatch
        self.supplier_quote_authority = supplier_quote_authority

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        page_size: int = 50,
        cursor: str | None = None,
        query: str | None = None,
        readiness: str | None = None,
        target_purchase_quantity: int = 3,
        max_age_hours: int = 168,
        source_grades: tuple[str, ...] = ("A", "B", "C"),
        timezone: str = "UTC",
        display_currency: str = "CNY",
    ) -> dict[str, Any]:
        if not 1 <= page_size <= 200:
            raise ValueError(
                "Sourcing Intelligence page_size must be between 1 and 200"
            )
        if readiness not in {None, *self.READINESS_FILTERS}:
            raise ValueError("Sourcing Intelligence readiness filter is invalid")
        if not 1 <= target_purchase_quantity <= 1_000_000:
            raise ValueError("target_purchase_quantity is invalid")
        if not 1 <= max_age_hours <= 24 * 365:
            raise ValueError("max_age_hours is invalid")
        grades = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in source_grades
                    if str(item).strip()
                }
            )
        )
        if not grades or not set(grades) <= {"A", "B", "C", "D"}:
            raise ValueError("source_grades are invalid")
        normalized_query = str(query or "").strip().casefold()
        normalized_cursor = str(cursor or "").strip() or None
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        query_contract = {
            "page_size": page_size,
            "cursor": normalized_cursor,
            "next_cursor": None,
            "search": normalized_query or None,
            "readiness": readiness,
            "target_purchase_quantity": target_purchase_quantity,
            "max_age_hours": max_age_hours,
            "source_grades": list(grades),
            "timezone": str(timezone).strip(),
            "display_currency": str(display_currency).strip().upper(),
        }
        if context["status"] != "ready":
            return self._result(
                context=context,
                query=query_contract,
                status=context["status"],
                work_items=[],
                total_items=0,
                counts=self._empty_counts(),
                gaps=[f"sourcing_{context['reason']}"],
                blockers=[self._blocker(str(context["reason"]))],
                input_read=False,
            )

        pim = self._collect_pim(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            context=context,
        )
        pim_conflicts = self._upstream_conflicts(
            projection=pim,
            contract_id=self.PIM_CONTRACT_ID,
            context=context,
            source="pim",
            snapshot_field="snapshot_sha256",
        )
        if pim_conflicts or pim["status"] == "blocked":
            return self._blocked_upstream(
                context=context,
                query=query_contract,
                gaps=[*pim_conflicts, *pim.get("source_gaps", [])],
                blockers=pim.get("blockers", []),
            )

        radar = self.scoped_batch.market_radar(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            timezone=query_contract["timezone"],
            display_currency=query_contract["display_currency"],
            source_grades=grades,
            max_age_hours=max_age_hours,
            target_purchase_quantity=target_purchase_quantity,
        )
        radar_conflicts = self._upstream_conflicts(
            projection=radar,
            contract_id=self.RADAR_CONTRACT_ID,
            context=context,
            source="market_radar",
            snapshot_field="snapshot_sha256",
        )
        if radar_conflicts or radar["status"] == "blocked":
            return self._blocked_upstream(
                context=context,
                query=query_contract,
                gaps=[*radar_conflicts, *radar.get("source_gaps", [])],
                blockers=radar.get("blockers", []),
            )

        batch = self.scoped_batch.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        batch_conflicts = self._upstream_conflicts(
            projection=batch,
            contract_id=self.BATCH_CONTRACT_ID,
            context=context,
            source="batch_opportunity",
            snapshot_field="scoped_snapshot_sha256",
            allow_extended_scope=True,
        )
        if batch_conflicts or batch["status"] == "blocked":
            return self._blocked_upstream(
                context=context,
                query=query_contract,
                gaps=[*batch_conflicts, *batch.get("source_gaps", [])],
                blockers=batch.get("blockers", []),
            )

        raw = self._raw_artifacts()
        if raw["status"] == "blocked":
            return self._blocked_upstream(
                context=context,
                query=query_contract,
                gaps=raw["source_gaps"],
                blockers=raw["blockers"],
            )
        evidence_projection = self._scope_artifacts(
            raw=raw,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        if evidence_projection["status"] == "blocked":
            return self._blocked_upstream(
                context=context,
                query=query_contract,
                gaps=evidence_projection["source_gaps"],
                blockers=evidence_projection["blockers"],
            )

        product_groups = {
            item["product"]["id"]: item
            for item in pim["product_groups"]
        }
        artifact_product_ids = {
            str(item.get("product_id") or "").strip()
            for collection in (
                evidence_projection["rfq_packages"],
                evidence_projection["dispatches"],
                evidence_projection["quotes"],
            )
            for item in collection
            if str(item.get("product_id") or "").strip()
        }
        outside_pim = sorted(artifact_product_ids - set(product_groups))
        if outside_pim:
            return self._blocked_upstream(
                context=context,
                query=query_contract,
                gaps=["sourcing_artifact_product_not_in_exact_pim"],
                blockers=[
                    self._blocker(
                        "sourcing_artifact_product_not_in_exact_pim",
                        owner="pim-governance",
                    )
                ],
            )

        work_items = self._work_items(
            products=product_groups,
            cohorts=radar.get("cohorts", []),
            candidates=batch.get("candidates", []),
            rfq_packages=evidence_projection["rfq_packages"],
            dispatches=evidence_projection["dispatches"],
            quotes=evidence_projection["quotes"],
        )
        if normalized_query:
            work_items = [
                item
                for item in work_items
                if normalized_query in self._search_text(item)
            ]
        if readiness:
            work_items = [
                item
                for item in work_items
                if self._matches_readiness(item, readiness)
            ]
        work_items.sort(key=lambda item: item["work_item_key"])
        total_items = len(work_items)
        total_counts = self._counts(
            work_items=work_items,
            radar=radar,
            pim=pim,
            rfq_packages=evidence_projection["rfq_packages"],
            dispatches=evidence_projection["dispatches"],
            quotes=evidence_projection["quotes"],
        )
        if normalized_cursor:
            cursor_key = self._decode_cursor(normalized_cursor)
            work_items = [
                item
                for item in work_items
                if item["work_item_key"] > cursor_key
            ]
        page = work_items[:page_size]
        next_cursor = (
            self._encode_cursor(page[-1]["work_item_key"])
            if page and len(work_items) > page_size
            else None
        )
        query_contract["next_cursor"] = next_cursor
        gaps = sorted(
            {
                *pim.get("source_gaps", []),
                *radar.get("source_gaps", []),
                *batch.get("source_gaps", []),
                *evidence_projection["source_gaps"],
            }
        )
        blockers = [
            *pim.get("blockers", []),
            *radar.get("blockers", []),
            *batch.get("blockers", []),
            *evidence_projection["blockers"],
        ]
        status = (
            "no_data"
            if total_items == 0
            else "partial"
            if gaps
            or any(
                item["readiness"]["status"] != "ready" for item in work_items
            )
            else "ready"
        )
        return self._result(
            context=context,
            query=query_contract,
            status=status,
            work_items=page,
            total_items=total_items,
            counts=total_counts,
            gaps=gaps,
            blockers=blockers,
            upstream={
                "pim_snapshot_sha256": pim["snapshot_sha256"],
                "market_radar_snapshot_sha256": radar["snapshot_sha256"],
                "batch_opportunity_snapshot_sha256": batch[
                    "scoped_snapshot_sha256"
                ],
                "artifact_evidence_authority_sha256": evidence_projection[
                    "binding_authority_sha256"
                ],
            },
        )

    def _collect_pim(self, **values: Any) -> dict[str, Any]:
        context = values.pop("context")
        cursor = None
        groups: list[dict[str, Any]] = []
        unbound: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        for _ in range(5):
            page = self.pim.project(
                **values,
                page_size=200,
                cursor=cursor,
            )
            conflicts = self._upstream_conflicts(
                projection=page,
                contract_id=self.PIM_CONTRACT_ID,
                context=context,
                source="pim",
                snapshot_field="snapshot_sha256",
            )
            if conflicts:
                return {
                    **page,
                    "status": "blocked",
                    "product_groups": [],
                    "unbound_listings": [],
                    "source_gaps": [
                        *page.get("source_gaps", []),
                        *conflicts,
                    ],
                    "blockers": [
                        *page.get("blockers", []),
                        *(self._blocker(item) for item in conflicts),
                    ],
                }
            pages.append(page)
            groups.extend(page["product_groups"])
            unbound = page["unbound_listings"]
            cursor = page["query"]["next_cursor"]
            if not cursor:
                break
        else:
            page = pages[-1]
            return {
                **page,
                "status": "blocked",
                "product_groups": [],
                "unbound_listings": [],
                "source_gaps": [
                    *page.get("source_gaps", []),
                    "pim_scan_truncated",
                ],
                "blockers": [
                    *page.get("blockers", []),
                    self._blocker("pim_scan_truncated"),
                ],
            }
        first = pages[0]
        combined = {
            **first,
            "product_groups": groups,
            "unbound_listings": unbound,
            "query": {**first["query"], "cursor": None, "next_cursor": None},
            "counts": {
                **first["counts"],
                "page_product_groups": len(groups),
            },
            "page_snapshot_sha256": [
                item["snapshot_sha256"] for item in pages
            ],
        }
        combined["snapshot_sha256"] = self._hash(combined)
        return combined

    def _raw_artifacts(self) -> dict[str, Any]:
        try:
            rfq_packages = self.supplier_rfq.list(limit=500)
            dispatches = self.supplier_rfq_dispatch.list(limit=500)
            quotes = self.supplier_quote_authority.list(limit=500)
        except (KeyError, RuntimeError, ValueError):
            return {
                "status": "blocked",
                "rfq_packages": [],
                "dispatches": [],
                "quotes": [],
                "source_gaps": ["sourcing_artifact_integrity_failed"],
                "blockers": [
                    self._blocker(
                        "sourcing_artifact_integrity_failed",
                        owner="evidence-governance",
                    )
                ],
            }
        return {
            "status": "ready",
            "rfq_packages": rfq_packages,
            "dispatches": dispatches,
            "quotes": quotes,
            "source_gaps": [],
            "blockers": [],
        }

    def _scope_artifacts(
        self,
        *,
        raw: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        evidence_ids = sorted(
            {
                evidence_id
                for collection in (
                    raw["rfq_packages"],
                    raw["dispatches"],
                    raw["quotes"],
                )
                for row in collection
                if (evidence_id := self._evidence_id(row))
            }
        )
        if not evidence_ids:
            return {
                "status": "no_data",
                "rfq_packages": [],
                "dispatches": [],
                "quotes": [],
                "source_gaps": [],
                "blockers": [],
                "binding_authority_sha256": None,
            }
        projection = self.scoped_evidence.project_targets(
            evidence_ids=evidence_ids,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        conflicts: list[str] = []
        if projection.get("contract_id") != self.EVIDENCE_CONTRACT_ID:
            conflicts.append("sourcing_evidence_contract_conflict")
        if projection.get("status") not in {"ready", "partial", "blocked"}:
            conflicts.append("sourcing_evidence_status_conflict")
        if len(str(projection.get("binding_authority_sha256") or "")) != 64:
            conflicts.append("sourcing_evidence_authority_invalid")
        records = {
            item["evidence_id"]: item
            for item in projection.get("records", [])
        }
        if any(
            evidence_id not in records
            or records[evidence_id].get("scope_binding", {}).get("status")
            != "ready"
            for evidence_id in evidence_ids
        ):
            conflicts.append("sourcing_evidence_not_exact_scope")
        if projection.get("invalid_evidence_ids"):
            conflicts.append("sourcing_evidence_integrity_failed")
        if conflicts or projection.get("status") != "ready":
            return {
                "status": "blocked",
                "rfq_packages": [],
                "dispatches": [],
                "quotes": [],
                "source_gaps": sorted(
                    {
                        *conflicts,
                        *projection.get("source_gaps", []),
                    }
                ),
                "blockers": [
                    *projection.get("blockers", []),
                    *(self._blocker(item) for item in conflicts),
                ],
                "binding_authority_sha256": None,
            }
        return {
            "status": "ready",
            "rfq_packages": [
                self._rfq_package(item) for item in raw["rfq_packages"]
            ],
            "dispatches": [
                self._dispatch(item) for item in raw["dispatches"]
            ],
            "quotes": [self._quote(item) for item in raw["quotes"]],
            "source_gaps": [],
            "blockers": [],
            "binding_authority_sha256": projection[
                "binding_authority_sha256"
            ],
        }

    def _work_items(
        self,
        *,
        products: dict[str, dict[str, Any]],
        cohorts: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        rfq_packages: list[dict[str, Any]],
        dispatches: list[dict[str, Any]],
        quotes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cohort_by_key = {
            item["candidate_key"]: item for item in cohorts
        }
        candidate_by_key = {
            item["candidate_key"]: item for item in candidates
        }
        product_candidate_keys: dict[str, set[str]] = {
            product_id: set() for product_id in products
        }
        for cohort in cohorts:
            for row in cohort.get("own_listing_current_facts", []):
                product_id = str(
                    row.get("target_product_id") or ""
                ).strip()
                if product_id in products:
                    product_candidate_keys[product_id].add(
                        cohort["candidate_key"]
                    )
        for candidate in candidates:
            product_id = str(
                candidate.get("canonical_product_id") or ""
            ).strip()
            if product_id in products:
                product_candidate_keys[product_id].add(
                    candidate["candidate_key"]
                )
        product_by_offer = {
            listing["offer_id"]: product_id
            for product_id, product in products.items()
            for listing in product.get("listings", [])
        }
        for cohort in cohorts:
            for row in cohort.get("own_listing_current_facts", []):
                offer_id = str(
                    row.get("target_offer_id")
                    or row.get("external_item_id")
                    or ""
                ).strip()
                product_id = product_by_offer.get(offer_id)
                if product_id:
                    product_candidate_keys[product_id].add(
                        cohort["candidate_key"]
                    )

        all_keys = set(cohort_by_key) | set(candidate_by_key)
        work: list[dict[str, Any]] = []
        for candidate_key in sorted(all_keys):
            product_ids = sorted(
                product_id
                for product_id, keys in product_candidate_keys.items()
                if candidate_key in keys
            )
            work.append(
                self._work_item(
                    work_item_key=f"candidate:{candidate_key}",
                    candidate_key=candidate_key,
                    product_ids=product_ids,
                    products=products,
                    cohort=cohort_by_key.get(candidate_key),
                    candidate=candidate_by_key.get(candidate_key),
                    rfq_packages=rfq_packages,
                    dispatches=dispatches,
                    quotes=quotes,
                )
            )
        associated_products = {
            product_id
            for item in work
            for product_id in item["canonical_product_ids"]
        }
        for product_id in sorted(set(products) - associated_products):
            work.append(
                self._work_item(
                    work_item_key=f"product:{product_id}",
                    candidate_key=None,
                    product_ids=[product_id],
                    products=products,
                    cohort=None,
                    candidate=None,
                    rfq_packages=rfq_packages,
                    dispatches=dispatches,
                    quotes=quotes,
                )
            )
        return work

    def _work_item(
        self,
        *,
        work_item_key: str,
        candidate_key: str | None,
        product_ids: list[str],
        products: dict[str, dict[str, Any]],
        cohort: dict[str, Any] | None,
        candidate: dict[str, Any] | None,
        rfq_packages: list[dict[str, Any]],
        dispatches: list[dict[str, Any]],
        quotes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        product_rows = [
            self._product(products[product_id]) for product_id in product_ids
        ]
        product_rfq = [
            item for item in rfq_packages
            if item["product_id"] in product_ids
        ]
        product_dispatches = [
            item for item in dispatches
            if item["product_id"] in product_ids
        ]
        product_quotes = [
            item for item in quotes if item["product_id"] in product_ids
        ]
        accepted_suppliers = sorted(
            {
                item["supplier_ref"]
                for item in product_quotes
                if item["status"] == "accepted" and item["supplier_ref"]
            }
        )
        downside = (
            candidate.get("economics", {}).get("downside")
            if candidate
            else None
        )
        components = (
            downside.get("components", [])
            if isinstance(downside, dict)
            else []
        )
        component_names = {
            str(item.get("name") or "") for item in components
            if isinstance(item, dict)
        }
        downside_ready = bool(
            candidate
            and candidate.get("economics", {}).get(
                "cost_evidence_complete"
            )
            is True
            and len(components) == 15
            and component_names == REQUIRED_COST_EVIDENCE_KEYS
            and downside.get("cm3_cny") is not None
        )
        market_counts = cohort.get("counts", {}) if cohort else {}
        research_ready = bool(
            cohort
            and market_counts.get("competitor_listing_rows", 0) > 0
            and market_counts.get("supplier_option_rows", 0) > 0
        )
        rfq_ready = bool(product_rfq)
        three_quotes_ready = len(accepted_suppliers) >= 3
        blocked = bool(
            any(item.get("readiness_status") == "blocked" for item in product_rows)
            or (candidate and candidate.get("invalid_evidence_ids"))
        )
        status = (
            "blocked"
            if blocked
            else "ready"
            if research_ready and three_quotes_ready and downside_ready
            else "partial"
        )
        owner = (
            "evidence-governance"
            if blocked
            else "supplier-sourcing"
            if research_ready and not three_quotes_ready
            else "market-intelligence"
        )
        next_action = (
            "Repair blocked Evidence or Product authority and rerun."
            if blocked
            else "Collect and independently accept three exact-product quotes."
            if not three_quotes_ready
            else "Complete evidence-backed fifteen-component downside CM3."
            if not downside_ready
            else "Prepare an internal candidate decision packet for review."
        )
        core = {
            "work_item_key": work_item_key,
            "candidate_key": candidate_key,
            "product_identity": (
                cohort.get("product_identity")
                if cohort
                else candidate.get("identity_match", {}).get(
                    "product_identity"
                )
                if candidate
                else None
            ),
            "variant_key": cohort.get("variant_key") if cohort else None,
            "canonical_product_ids": product_ids,
            "canonical_products": product_rows,
            "market_research": (
                {
                    "counts": cohort["counts"],
                    "competitor_price_bands": cohort[
                        "competitor_price_bands"
                    ],
                    "supplier_price_bands_at_target": cohort[
                        "supplier_price_bands_at_target"
                    ],
                    "target_purchase_quantity": cohort[
                        "target_purchase_quantity"
                    ],
                    "source_grade_counts": cohort["source_grade_counts"],
                    "freshness": cohort["freshness"],
                    "evidence_ids": cohort["evidence_ids"],
                    "sales_is_actual": False,
                }
                if cohort
                else None
            ),
            "rfq_and_quotes": {
                "rfq_packages": product_rfq,
                "dispatch_proofs": product_dispatches,
                "quotes": product_quotes,
                "accepted_unique_suppliers": accepted_suppliers,
                "rfq_draft_ready": rfq_ready,
                "three_accepted_quotes_ready": three_quotes_ready,
                "automatic_supplier_contact": False,
            },
            "economics": {
                "authority": "observed_cost_research_screening",
                "native_candidate_present": candidate is not None,
                "cost_evidence_complete": (
                    candidate.get("economics", {}).get(
                        "cost_evidence_complete"
                    )
                    if candidate
                    else False
                ),
                "fifteen_component_downside_ready": downside_ready,
                "downside": downside,
                "formal_cm3": None,
                "actual_cash_cm3": None,
            },
            "candidate": (
                {
                    "fingerprint": candidate.get("fingerprint"),
                    "state": candidate.get("state"),
                    "strategy": candidate.get("strategy"),
                    "blockers": candidate.get("blockers", []),
                    "next_action": candidate.get("next_action"),
                    "evidence_ids": candidate.get("evidence_ids", []),
                    "eligible_for_approval": candidate.get(
                        "eligible_for_approval", False
                    ),
                    "pilot_ready": candidate.get("pilot_ready", False),
                }
                if candidate
                else None
            ),
            "readiness": {
                "status": status,
                "market_research_ready": research_ready,
                "canonical_product_bound": bool(product_ids),
                "rfq_draft_ready": rfq_ready,
                "three_accepted_quotes_ready": three_quotes_ready,
                "fifteen_component_downside_ready": downside_ready,
            },
            "owner": owner,
            "sla": "before supplier decision, PO or Listing approval",
            "next": next_action,
            "next_workspace": (
                "/pim" if not product_ids else "/sourcing-intelligence"
            ),
        }
        core["item_snapshot_sha256"] = self._hash(core)
        return core

    @staticmethod
    def _product(item: dict[str, Any]) -> dict[str, Any]:
        product = item["product"]
        return {
            "id": product["id"],
            "sku": product["sku"],
            "name": product["name"],
            "readiness_status": item["readiness"]["status"],
            "listing_count": len(item.get("listings", [])),
            "passport_count": len(item.get("passports", [])),
            "owner": item["owner"],
            "snapshot_sha256": item["group_snapshot_sha256"],
        }

    @classmethod
    def _rfq_package(cls, row: dict[str, Any]) -> dict[str, Any]:
        evidence = row["evidence"]
        package = row["package"]
        product = package.get("product", {})
        listing = package.get("listing", {})
        requirement = package.get("buyer_requirement", {})
        return {
            "evidence_id": evidence.id,
            "evidence_sha256": evidence.sha256,
            "product_id": str(product.get("id") or ""),
            "offer_id": listing.get("offer_id"),
            "status": package.get("authority", {}).get("status", "draft"),
            "package_hash": package.get("package_hash"),
            "quantity_breaks": requirement.get("quantity_breaks", []),
            "response_due_at": requirement.get("response_due_at"),
            "unanswered_question_count": len(
                package.get("unanswered_questions", [])
            ),
            "counts_as_supplier_quote": False,
            "automatic_supplier_contact": False,
        }

    @classmethod
    def _dispatch(cls, row: dict[str, Any]) -> dict[str, Any]:
        evidence = row["evidence"]
        dispatch = row["dispatch"]
        rfq = dispatch.get("rfq", {})
        supplier = dispatch.get("supplier", {})
        return {
            "evidence_id": evidence.id,
            "evidence_sha256": evidence.sha256,
            "product_id": str(rfq.get("product_id") or ""),
            "rfq_package_evidence_id": rfq.get("evidence_id"),
            "supplier_ref": supplier.get("supplier_ref"),
            "supplier_platform": supplier.get("platform"),
            "status": row.get("status", "pending"),
            "delivery_confirmed": row.get("delivery_confirmed", False),
            "counts_as_supplier_quote": False,
            "automatic_supplier_contact": False,
        }

    @classmethod
    def _quote(cls, row: dict[str, Any]) -> dict[str, Any]:
        evidence = row["evidence"]
        metadata = (
            evidence.metadata if isinstance(evidence.metadata, dict) else {}
        )
        offer = metadata.get("offer_data", {})
        if not isinstance(offer, dict):
            offer = {}
        return {
            "evidence_id": evidence.id,
            "evidence_sha256": evidence.sha256,
            "product_id": str(metadata.get("product_id") or ""),
            "supplier_ref": str(metadata.get("supplier_ref") or ""),
            "document_kind": metadata.get("document_kind"),
            "status": row.get("status"),
            "formal_offer_eligible": row.get(
                "formal_offer_eligible", False
            ),
            "currency": offer.get("currency"),
            "unit_price": (
                offer.get("unit_price")
                or offer.get("unit_price_decimal")
            ),
            "min_order_quantity": offer.get("min_order_quantity"),
            "effective_at": evidence.effective_at,
            "effective_until": evidence.effective_until,
            "automatic_procurement": False,
        }

    @staticmethod
    def _evidence_id(row: dict[str, Any]) -> str | None:
        evidence = row.get("evidence")
        value = str(getattr(evidence, "id", "") or "").strip()
        return value or None

    @classmethod
    def _counts(
        cls,
        *,
        work_items: list[dict[str, Any]],
        radar: dict[str, Any],
        pim: dict[str, Any],
        rfq_packages: list[dict[str, Any]],
        dispatches: list[dict[str, Any]],
        quotes: list[dict[str, Any]],
    ) -> dict[str, int]:
        radar_counts = radar.get("counts", {})
        return {
            "total_work_items": len(work_items),
            "page_work_items": len(work_items),
            "canonical_products": pim.get("counts", {}).get(
                "total_product_groups", 0
            ),
            "exact_research_cohorts": radar_counts.get(
                "unique_exact_identities", 0
            ),
            "competitor_listing_rows": radar_counts.get(
                "competitor_listing_rows", 0
            ),
            "supplier_option_rows": radar_counts.get(
                "supplier_option_rows", 0
            ),
            "unique_supplier_identities": radar_counts.get(
                "unique_supplier_identities", 0
            ),
            "checkout_comparable_at_target": radar_counts.get(
                "checkout_comparable_at_target", 0
            ),
            "native_candidates": sum(
                item["candidate"] is not None for item in work_items
            ),
            "fifteen_component_downside_ready": sum(
                item["readiness"]["fifteen_component_downside_ready"]
                for item in work_items
            ),
            "rfq_packages": len(rfq_packages),
            "rfq_dispatch_proofs": len(dispatches),
            "quote_evidence": len(quotes),
            "accepted_quotes": sum(
                item["status"] == "accepted" for item in quotes
            ),
            "products_with_three_accepted_quotes": len(
                {
                    product_id
                    for product_id in {
                        item["product_id"] for item in quotes
                    }
                    if len(
                        {
                            item["supplier_ref"]
                            for item in quotes
                            if item["product_id"] == product_id
                            and item["status"] == "accepted"
                        }
                    )
                    >= 3
                }
            ),
        }

    @classmethod
    def _empty_counts(cls) -> dict[str, int]:
        return {
            key: 0
            for key in (
                "total_work_items",
                "page_work_items",
                "canonical_products",
                "exact_research_cohorts",
                "competitor_listing_rows",
                "supplier_option_rows",
                "unique_supplier_identities",
                "checkout_comparable_at_target",
                "native_candidates",
                "fifteen_component_downside_ready",
                "rfq_packages",
                "rfq_dispatch_proofs",
                "quote_evidence",
                "accepted_quotes",
                "products_with_three_accepted_quotes",
            )
        }

    def _result(
        self,
        *,
        context: dict[str, Any],
        query: dict[str, Any],
        status: str,
        work_items: list[dict[str, Any]],
        total_items: int,
        counts: dict[str, int],
        gaps: list[str],
        blockers: list[dict[str, Any]],
        input_read: bool = True,
        upstream: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        blocker_map = {
            (
                str(item.get("code")),
                str(item.get("owner")),
            ): item
            for item in blockers
            if isinstance(item, dict) and item.get("code")
        }
        core = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "query": query,
            "counts": {
                **counts,
                "total_work_items": total_items,
                "page_work_items": len(work_items),
            },
            "work_items": work_items,
            "source_gaps": sorted(set(gaps)),
            "blockers": [
                blocker_map[key] for key in sorted(blocker_map)
            ],
            "upstream_authority": upstream or {},
            "authority_levels": {
                "observation": "research_only",
                "supplier_quote": "requires_independent_acceptance",
                "downside_cm3": "screening_estimate",
                "formal_cm3": "no_data",
                "actual_cash_cm3": "no_data",
            },
            "control_envelope": {
                "read_only": True,
                "scoped_input_read": input_read,
                "client_recalculation_allowed": False,
                "internal_task_suggestion_allowed": True,
                "supplier_contacted": False,
                "rfq_dispatched": False,
                "quote_accepted": False,
                "supplier_offer_created": False,
                "purchase_order_created": False,
                "payment_created": False,
                "product_created": False,
                "listing_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        input_hash = self._hash(core)
        suggestions = [
            {
                "work_item_key": item["work_item_key"],
                "status": item["readiness"]["status"],
                "owner": item["owner"],
                "next": item["next"],
            }
            for item in work_items
            if item["readiness"]["status"] != "ready"
        ]
        core["agent_artifact"] = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "input_snapshot_sha256": input_hash,
            "artifact_sha256": self._hash(
                {
                    "contract_id": self.ARTIFACT_CONTRACT_ID,
                    "input_snapshot_sha256": input_hash,
                    "suggestions": suggestions,
                }
            ),
            "authority": "decision_support_and_internal_task_suggestion_only",
            "suggestions": suggestions,
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "supplier_contact_allowed": False,
            "external_write_allowed": False,
        }
        core["snapshot_sha256"] = self._hash(core)
        return core

    def _blocked_upstream(
        self,
        *,
        context: dict[str, Any],
        query: dict[str, Any],
        gaps: list[str],
        blockers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._result(
            context=context,
            query=query,
            status="blocked",
            work_items=[],
            total_items=0,
            counts=self._empty_counts(),
            gaps=gaps,
            blockers=[
                *blockers,
                *(
                    self._blocker(item)
                    for item in gaps
                    if not any(
                        blocker.get("code") == item
                        for blocker in blockers
                        if isinstance(blocker, dict)
                    )
                ),
            ],
        )

    @classmethod
    def _upstream_conflicts(
        cls,
        *,
        projection: dict[str, Any],
        contract_id: str,
        context: dict[str, Any],
        source: str,
        snapshot_field: str,
        allow_extended_scope: bool = False,
    ) -> list[str]:
        conflicts: list[str] = []
        if projection.get("contract_id") != contract_id:
            conflicts.append(f"{source}_contract_conflict")
        if projection.get("status") not in cls.UPSTREAM_STATUSES:
            conflicts.append(f"{source}_status_conflict")
        scope = projection.get("scope")
        expected = context["scope"]
        if (
            not isinstance(scope, dict)
            or any(scope.get(key) != value for key, value in expected.items())
            or (not allow_extended_scope and scope != expected)
        ):
            conflicts.append(f"{source}_scope_conflict")
        if projection.get("as_of") != context["cutoff"].isoformat():
            conflicts.append(f"{source}_as_of_conflict")
        if len(str(projection.get(snapshot_field) or "")) != 64:
            conflicts.append(f"{source}_snapshot_integrity_invalid")
        for field in ("source_gaps", "blockers"):
            if not isinstance(projection.get(field), list):
                conflicts.append(f"{source}_{field}_contract_conflict")
        return sorted(set(conflicts))

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
        authority = str(
            entity_scope.get("authority_sha256") or ""
        ).strip()
        entity = str(entity_scope.get("entity_ref") or "").strip()
        ready = (
            entity_scope.get("status") == "ready"
            and bool(entity)
            and len(authority) == 64
        )
        invalid_ready = (
            entity_scope.get("status") == "ready" and not ready
        )
        return {
            "status": (
                "ready"
                if ready
                else "blocked"
                if entity_scope.get("status") == "blocked" or invalid_ready
                else "no_data"
            ),
            "reason": (
                None
                if ready
                else "entity_scope_authority_invalid"
                if invalid_ready
                else entity_scope.get(
                    "reason", "entity_scope_authority_missing"
                )
            ),
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity if ready else None,
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    authority if ready else None
                ),
            },
        }

    @staticmethod
    def _blocker(
        code: str,
        *,
        owner: str = "sourcing-governance",
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": (
                "P0"
                if "conflict" in code
                or "integrity" in code
                or "invalid" in code
                else "P1"
            ),
            "owner": owner,
            "sla": "before supplier decision, PO or Listing approval",
            "next": (
                "Repair the exact-scope Evidence authority and rerun "
                "Sourcing Intelligence."
            ),
            "next_workspace": "/authority-intake",
        }

    @staticmethod
    def _search_text(item: dict[str, Any]) -> str:
        return json.dumps(
            {
                "candidate_key": item.get("candidate_key"),
                "identity": item.get("product_identity"),
                "products": item.get("canonical_products"),
                "suppliers": item.get("rfq_and_quotes", {}).get(
                    "accepted_unique_suppliers"
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).casefold()

    @staticmethod
    def _matches_readiness(
        item: dict[str, Any], readiness: str
    ) -> bool:
        values = item["readiness"]
        return {
            "research": values["market_research_ready"],
            "rfq": values["rfq_draft_ready"],
            "three_quotes": values["three_accepted_quotes_ready"],
            "downside": values["fifteen_component_downside_ready"],
            "blocked": values["status"] == "blocked",
        }[readiness]

    @staticmethod
    def _encode_cursor(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode()

    @staticmethod
    def _decode_cursor(value: str) -> str:
        try:
            decoded = base64.urlsafe_b64decode(value.encode()).decode()
            if not decoded or not (
                decoded.startswith("candidate:")
                or decoded.startswith("product:")
            ):
                raise ValueError
            return decoded
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise ValueError(
                "Sourcing Intelligence cursor is invalid"
            ) from exc

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
