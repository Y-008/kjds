from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .security import Principal


class ScopedPimWorkspace:
    """Compose exact-scope Catalog and Product Content behind one PIM seam."""

    CONTRACT_ID = "kjds-native-exact-scope-pim-workspace-v1"
    ARTIFACT_CONTRACT_ID = "kjds-pim-steward-artifact-v1"
    CATALOG_CONTRACT_ID = "kjds-scoped-marketplace-catalog-v1"
    PRODUCT_CONTENT_CONTRACT_ID = "kjds-scoped-product-content-v1"
    UPSTREAM_STATUSES = frozenset({"ready", "partial", "no_data", "blocked"})

    def __init__(self, *, catalog, product_content) -> None:
        self.catalog = catalog
        self.product_content = product_content

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
    ) -> dict[str, Any]:
        if not 1 <= page_size <= 200:
            raise ValueError("PIM page_size must be between 1 and 200")
        if readiness not in {None, "ready", "incomplete", "blocked"}:
            raise ValueError("PIM readiness filter is invalid")
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        normalized_query = str(query or "").strip().casefold()
        normalized_cursor = str(cursor or "").strip() or None
        if context["status"] != "ready":
            return self._result(
                context=context,
                status=context["status"],
                groups=[],
                unbound=[],
                total_groups=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                readiness=readiness,
                gaps=[f"pim_{context['reason']}"],
                blockers=[self._blocker(str(context["reason"]))],
                raw_read=False,
            )

        catalog = self.catalog.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            limit=1000,
        )
        content = self.product_content.project_catalog(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            catalog_projection=catalog,
        )
        upstream_conflicts = [
            *self._upstream_conflicts(
                projection=catalog,
                contract_id=self.CATALOG_CONTRACT_ID,
                context=context,
                source="catalog",
            ),
            *self._upstream_conflicts(
                projection=content,
                contract_id=self.PRODUCT_CONTENT_CONTRACT_ID,
                context=context,
                source="product_content",
            ),
        ]
        if upstream_conflicts:
            return self._result(
                context=context,
                status="blocked",
                groups=[],
                unbound=[],
                total_groups=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                readiness=readiness,
                gaps=upstream_conflicts,
                blockers=[
                    self._blocker(reason) for reason in upstream_conflicts
                ],
            )
        if "blocked" in {catalog["status"], content["status"]}:
            return self._result(
                context=context,
                status="blocked",
                groups=[],
                unbound=[],
                total_groups=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                readiness=readiness,
                gaps=[*catalog["source_gaps"], *content["source_gaps"]],
                blockers=[*catalog["blockers"], *content["blockers"]],
            )

        listings_by_product: dict[str, list[dict[str, Any]]] = {}
        unbound: list[dict[str, Any]] = []
        for item in catalog["items"]:
            listing = self._listing(item)
            product_id = str(item.get("canonical_product_id") or "").strip()
            if product_id:
                listings_by_product.setdefault(product_id, []).append(listing)
            else:
                unbound.append(listing)
        groups = [
            self._group(product, listings_by_product.pop(product["product"]["id"], []))
            for product in content["products"]
        ]
        for _product_id, listings in listings_by_product.items():
            unbound.extend(
                {**listing, "binding_issue": "canonical_product_not_in_scope"}
                for listing in listings
            )
        groups.sort(key=lambda item: (item["product"]["sku"], item["product"]["id"]))
        unbound.sort(key=lambda item: (item["offer_id"], item["item_hash"]))
        if normalized_query:
            groups = [
                item
                for item in groups
                if normalized_query
                in " ".join(
                    [
                        str(item["product"].get("sku", "")),
                        str(item["product"].get("name", "")),
                        *(str(row["offer_id"]) for row in item["listings"]),
                    ]
                ).casefold()
            ]
            unbound = [
                item
                for item in unbound
                if normalized_query
                in " ".join(
                    [
                        str(item.get("offer_id", "")),
                        str(item.get("marketplace_sku", "")),
                    ]
                ).casefold()
            ]
        if readiness:
            groups = [
                item for item in groups if item["readiness"]["status"] == readiness
            ]
        total_groups = len(groups)
        total_counts = {
            "bound_listings": sum(len(item["listings"]) for item in groups),
            "ready": sum(
                item["readiness"]["status"] == "ready" for item in groups
            ),
            "incomplete": sum(
                item["readiness"]["status"] == "incomplete" for item in groups
            ),
            "blocked": sum(
                item["readiness"]["status"] == "blocked" for item in groups
            ),
        }
        if normalized_cursor:
            cursor_key = self._decode_cursor(normalized_cursor)
            groups = [
                item
                for item in groups
                if (item["product"]["sku"], item["product"]["id"]) > cursor_key
            ]
        page = groups[:page_size]
        next_cursor = (
            self._encode_cursor(
                (page[-1]["product"]["sku"], page[-1]["product"]["id"])
            )
            if len(groups) > page_size and page
            else None
        )
        gaps = {*catalog["source_gaps"], *content["source_gaps"]}
        if unbound:
            gaps.add("marketplace_listings_unbound")
        gaps = sorted(gaps)
        status = (
            "no_data"
            if total_groups == 0 and not unbound
            else "partial"
            if gaps or total_counts["ready"] != total_groups
            else "ready"
        )
        return self._result(
            context=context,
            status=status,
            groups=page,
            unbound=unbound,
            total_groups=total_groups,
            page_size=page_size,
            cursor=normalized_cursor,
            next_cursor=next_cursor,
            query=normalized_query,
            readiness=readiness,
            gaps=gaps,
            blockers=[*catalog["blockers"], *content["blockers"]],
            total_counts=total_counts,
            upstream={
                "catalog_snapshot_sha256": catalog["snapshot_sha256"],
                "product_content_snapshot_sha256": content["snapshot_sha256"],
            },
        )

    def _group(
        self, product: dict[str, Any], listings: list[dict[str, Any]]
    ) -> dict[str, Any]:
        readiness = product["readiness"]
        blocked = bool(product["blockers"])
        ready = bool(
            listings
            and readiness["product_identity_ready"]
            and readiness["passport_approved"]
            and readiness["media_qa_ready"]
        )
        status = "blocked" if blocked else "ready" if ready else "incomplete"
        result = {
            **product,
            "listings": sorted(
                listings, key=lambda item: (item["offer_id"], item["item_hash"])
            ),
            "readiness": {
                **readiness,
                "marketplace_binding_ready": bool(listings),
                "pre_listing_stage": (
                    "listing_approval_review"
                    if ready
                    else "media_qa"
                    if readiness["passport_approved"]
                    else "passport"
                ),
                "status": status,
            },
            "owner": (
                "evidence-governance"
                if blocked
                else "content-governance"
                if readiness["passport_approved"]
                else "pim-governance"
            ),
            "sla": "before Listing approval request",
            "next": (
                "Repair the blocked scoped authority and rerun PIM."
                if blocked
                else "Complete media QA with immutable Evidence."
                if readiness["passport_approved"]
                else "Complete and independently approve all three Passports."
            ),
            "next_workspace": "/commerce-os",
        }
        result["group_snapshot_sha256"] = self._hash(result)
        return result

    @staticmethod
    def _listing(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "offer_id": str(item.get("offer_id") or ""),
            "marketplace_sku": item.get("marketplace_sku") or item.get("sku"),
            "listing_status": item.get("status"),
            "platform_statuses": item.get("statuses"),
            "item_hash": item.get("item_hash"),
            "source_evidence_id": item.get("source_evidence_id"),
            "canonical_product_id": item.get("canonical_product_id"),
            "observed_fields": {
                "title": item.get("name"),
                "description": None,
                "category_id": None,
                "attributes": item.get("attributes"),
                "images": item.get("image_references"),
            },
            "binding_issue": (
                None
                if item.get("canonical_product_id")
                else "canonical_product_binding_missing"
            ),
        }

    def _result(
        self,
        *,
        context: dict[str, Any],
        status: str,
        groups: list[dict[str, Any]],
        unbound: list[dict[str, Any]],
        total_groups: int,
        page_size: int,
        cursor: str | None,
        next_cursor: str | None,
        query: str,
        readiness: str | None,
        gaps: list[str],
        blockers: list[dict[str, Any]],
        raw_read: bool = True,
        upstream: dict[str, Any] | None = None,
        total_counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        blockers_by_key = {
            (item["code"], item["owner"]): item for item in blockers
        }
        counts = total_counts or {
            "bound_listings": sum(len(item["listings"]) for item in groups),
            "ready": sum(
                item["readiness"]["status"] == "ready" for item in groups
            ),
            "incomplete": sum(
                item["readiness"]["status"] == "incomplete" for item in groups
            ),
            "blocked": sum(
                item["readiness"]["status"] == "blocked" for item in groups
            ),
        }
        core = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "query": {
                "page_size": page_size,
                "cursor": cursor,
                "next_cursor": next_cursor,
                "search": query or None,
                "readiness": readiness,
            },
            "counts": {
                "total_product_groups": total_groups,
                "page_product_groups": len(groups),
                "bound_listings": counts["bound_listings"],
                "unbound_listings": len(unbound),
                "ready": counts["ready"],
                "incomplete": counts["incomplete"],
                "blocked": counts["blocked"],
            },
            "product_groups": groups,
            "unbound_listings": unbound,
            "source_gaps": sorted(set(gaps)),
            "blockers": [blockers_by_key[key] for key in sorted(blockers_by_key)],
            "upstream_authority": upstream or {},
            "control_envelope": {
                "read_only": True,
                "scoped_input_read": raw_read,
                "client_recalculation_allowed": False,
                "product_created": False,
                "passport_created": False,
                "listing_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        input_hash = self._hash(core)
        core["agent_artifact"] = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "artifact_sha256": self._hash(
                {
                    "contract_id": self.ARTIFACT_CONTRACT_ID,
                    "input_snapshot_sha256": input_hash,
                    "suggestions": [
                        {
                            "product_id": item["product"]["id"],
                            "status": item["readiness"]["status"],
                            "owner": item["owner"],
                            "next": item["next"],
                        }
                        for item in groups
                        if item["readiness"]["status"] != "ready"
                    ],
                }
            ),
            "input_snapshot_sha256": input_hash,
            "authority": "decision_support_and_internal_task_suggestion_only",
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "external_write_allowed": False,
        }
        core["snapshot_sha256"] = self._hash(core)
        return core

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
            raise PermissionError("Authenticated identity is not authorized for store_ref")
        cutoff = as_of.astimezone(UTC)
        authority_sha256 = str(
            entity_scope.get("authority_sha256") or ""
        ).strip()
        entity_present = bool(entity_scope.get("entity_ref"))
        ready = (
            entity_scope.get("status") == "ready"
            and entity_present
            and len(authority_sha256) == 64
        )
        invalid_ready_authority = (
            entity_scope.get("status") == "ready"
            and (not entity_present or len(authority_sha256) != 64)
        )
        return {
            "status": (
                "ready"
                if ready
                else "blocked"
                if entity_scope.get("status") == "blocked"
                or invalid_ready_authority
                else "no_data"
            ),
            "reason": (
                None
                if ready
                else "entity_scope_authority_invalid"
                if invalid_ready_authority
                else entity_scope.get(
                    "reason", "entity_scope_authority_missing"
                )
            ),
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": str(entity_scope["entity_ref"]) if ready else None,
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    authority_sha256 if ready else None
                ),
            },
        }

    @classmethod
    def _upstream_conflicts(
        cls,
        *,
        projection: dict[str, Any],
        contract_id: str,
        context: dict[str, Any],
        source: str,
    ) -> list[str]:
        conflicts: list[str] = []
        if projection.get("contract_id") != contract_id:
            conflicts.append(f"{source}_contract_conflict")
        if projection.get("status") not in cls.UPSTREAM_STATUSES:
            conflicts.append(f"{source}_status_conflict")
        if projection.get("scope") != context["scope"]:
            conflicts.append(f"{source}_scope_conflict")
        if projection.get("as_of") != context["cutoff"].isoformat():
            conflicts.append(f"{source}_as_of_conflict")
        if len(str(projection.get("snapshot_sha256") or "")) != 64:
            conflicts.append(f"{source}_snapshot_integrity_invalid")
        for field in ("source_gaps", "blockers"):
            if not isinstance(projection.get(field), list):
                conflicts.append(f"{source}_{field}_contract_conflict")
        return sorted(set(conflicts))

    @staticmethod
    def _blocker(code: str) -> dict[str, Any]:
        return {
            "code": code,
            "severity": "P0" if "conflict" in code or "integrity" in code else "P1",
            "owner": "identity-governance" if "entity_scope" in code else "pim-governance",
            "sla": "before any Product, content or Listing decision",
            "next": "Repair exact-scope authority and rerun the PIM projection.",
            "next_workspace": "/authority-intake",
        }

    @staticmethod
    def _encode_cursor(value: tuple[str, str]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).decode()

    @staticmethod
    def _decode_cursor(value: str) -> tuple[str, str]:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(value.encode()))
            if (
                not isinstance(decoded, list)
                or len(decoded) != 2
                or not all(isinstance(item, str) for item in decoded)
            ):
                raise ValueError
            return decoded[0], decoded[1]
        except (ValueError, binascii.Error, json.JSONDecodeError) as exc:
            raise ValueError("PIM cursor is invalid") from exc

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
