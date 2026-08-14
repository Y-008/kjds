from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .security import Principal


class ScopedMarketplaceCatalogAuthority:
    """Project catalog current facts only after exact-scope Evidence authority."""

    CONTRACT_ID = "kjds-scoped-marketplace-catalog-v1"

    def __init__(self, *, catalog, scoped_evidence) -> None:
        self.catalog = catalog
        self.scoped_evidence = scoped_evidence

    def latest(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        limit: int = 100,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            return self._empty(context=context)
        raw = self.catalog.latest_items(
            store_ref=store_ref,
            limit=limit,
            as_of=context["cutoff"],
            tenant_ref=principal.tenant_ref,
            entity_ref=context["scope"]["entity_ref"],
        )
        return self._project(raw=raw, context=context)

    def require_import_evidence(
        self,
        *,
        evidence_ids: list[str],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Fail before catalog mutation unless every source is current and scoped."""
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            raise ValueError(
                "Marketplace catalog import requires one current entity scope grant"
            )
        normalized = sorted(
            {str(item).strip() for item in evidence_ids if str(item).strip()}
        )
        if not normalized or len(normalized) != len(evidence_ids):
            raise ValueError(
                "Marketplace catalog import requires unique Evidence references"
            )
        projection = self.scoped_evidence.project_targets(
            evidence_ids=normalized,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        target_records = {
            item["evidence_id"]: item
            for item in projection["records"]
            if item["evidence_id"] in normalized
        }
        if (
            projection["status"] != "ready"
            or projection["invalid_evidence_ids"]
            or set(target_records) != set(normalized)
            or any(
                item["scope_binding"]["status"] != "ready"
                for item in target_records.values()
            )
        ):
            raise ValueError(
                "Marketplace catalog import Evidence is not current and "
                "independently bound to the exact tenant/entity/store scope"
            )
        return {
            "status": "ready",
            "evidence_ids": normalized,
            "evidence_authority_sha256": projection[
                "binding_authority_sha256"
            ],
        }

    def require_current_item(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        offer_id: str,
        expected_item_hash: str,
    ) -> dict[str, Any]:
        projection = self.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            limit=1000,
        )
        if projection["scope"]["entity_ref"] is None:
            raise ValueError(
                "Marketplace catalog binding requires one current entity "
                "scope grant"
            )
        item = next(
            (
                candidate
                for candidate in projection["items"]
                if candidate["offer_id"] == offer_id
            ),
            None,
        )
        if item is None:
            raise KeyError(
                "Unknown current marketplace catalog item in authorized scope"
            )
        if item["item_hash"] != expected_item_hash:
            raise ValueError("Catalog item changed; refresh before continuing")
        return item

    def _project(
        self,
        *,
        raw: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if not raw:
            return self._catalog_result(
                context=context,
                status="no_data",
                items=[],
                queried=0,
                excluded={},
                ready_authorities=[],
                source_gaps=["catalog_not_available"],
                blockers=[],
            )
        evidence_ids = sorted(
            {
                str(item.get("source_evidence_id", "")).strip()
                for item in raw
                if str(item.get("source_evidence_id", "")).strip()
            }
        )
        projection = self.scoped_evidence.project_targets(
            evidence_ids=evidence_ids,
            principal=context["principal"],
            entity_scope=context["entity_scope"],
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
        )
        records = {
            item["evidence_id"]: item
            for item in projection["records"]
            if item["evidence_id"] in evidence_ids
        }
        invalid_ids = set(projection["invalid_evidence_ids"])
        native_authority_reasons: dict[str, list[str]] = {}
        native_snapshots = {
            str(item.get("snapshot_id")): item
            for item in raw
            if item.get("tenant_ref") is not None
        }
        for snapshot_id, sample in native_snapshots.items():
            reasons = self._native_authority_reasons(
                item=sample,
                context=context,
            )
            snapshot_evidence_ids = sorted(
                {
                    str(value).strip()
                    for value in sample.get("snapshot_evidence_ids", [])
                    if str(value).strip()
                }
            )
            if not snapshot_evidence_ids:
                reasons.append("catalog_native_evidence_set_missing")
            else:
                native_projection = self.scoped_evidence.project_targets(
                    evidence_ids=snapshot_evidence_ids,
                    principal=context["principal"],
                    entity_scope=context["entity_scope"],
                    store_ref=context["scope"]["store_ref"],
                    as_of=context["cutoff"],
                )
                projected_target_ids = {
                    row["evidence_id"]
                    for row in native_projection["records"]
                    if row["evidence_id"] in snapshot_evidence_ids
                }
                if (
                    native_projection["status"] != "ready"
                    or native_projection["invalid_evidence_ids"]
                    or projected_target_ids != set(snapshot_evidence_ids)
                ):
                    reasons.append(
                        "catalog_native_evidence_authority_invalid"
                    )
                elif (
                    native_projection["binding_authority_sha256"]
                    != sample.get("scope_evidence_authority_sha256")
                ):
                    reasons.append(
                        "catalog_native_evidence_authority_mismatch"
                    )
            native_authority_reasons[snapshot_id] = sorted(set(reasons))
        included: list[dict[str, Any]] = []
        excluded: dict[str, int] = {}
        ready_authorities: list[dict[str, Any]] = []
        for item in raw:
            evidence_id = str(item.get("source_evidence_id", "")).strip()
            record = records.get(evidence_id)
            native_reasons = native_authority_reasons.get(
                str(item.get("snapshot_id")),
                [],
            )
            if native_reasons:
                reasons = native_reasons
            elif not evidence_id:
                reasons = ["catalog_source_evidence_missing"]
            elif evidence_id in invalid_ids:
                reasons = ["evidence_integrity_invalid"]
            elif record is None:
                reasons = ["evidence_scope_projection_missing"]
            elif record["scope_binding"]["status"] != "ready":
                reasons = (
                    record["scope_binding"]["reasons"]
                    or [f"evidence_scope_{record['scope_binding']['status']}"]
                )
            else:
                reasons = []
            if reasons:
                for reason in sorted(set(reasons)):
                    excluded[reason] = excluded.get(reason, 0) + 1
                continue
            included.append(item)
            ready_authorities.append(
                {
                    "evidence_id": evidence_id,
                    "sha256": record["sha256"],
                    "scope_binding": record["scope_binding"],
                }
            )

        if projection["status"] == "blocked":
            status = "blocked"
        elif included and not excluded:
            status = "ready"
        elif included:
            status = "partial"
        elif any(
            token in reason
            for reason in excluded
            for token in ("mismatch", "conflict", "integrity")
        ):
            status = "blocked"
        else:
            status = "no_data"
        source_gaps = sorted(f"catalog_{reason}" for reason in excluded)
        if not source_gaps and not included:
            source_gaps = ["catalog_not_available"]
        blockers = [self._blocker(reason) for reason in sorted(excluded)]
        return self._catalog_result(
            context=context,
            status=status,
            items=included,
            queried=len(raw),
            excluded=excluded,
            ready_authorities=ready_authorities,
            source_gaps=source_gaps,
            blockers=blockers,
        )

    @staticmethod
    def _native_authority_reasons(
        *,
        item: dict[str, Any],
        context: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        scope = context["scope"]
        if item.get("tenant_ref") != scope["tenant_ref"]:
            reasons.append("catalog_native_tenant_scope_mismatch")
        if item.get("entity_ref") != scope["entity_ref"]:
            reasons.append("catalog_native_entity_scope_mismatch")
        if (
            item.get("scope_grant_authority_sha256")
            != scope["scope_grant_authority_sha256"]
        ):
            reasons.append("catalog_native_scope_grant_mismatch")
        try:
            scope_as_of = datetime.fromisoformat(
                str(item.get("scope_as_of")).replace("Z", "+00:00")
            )
        except ValueError:
            reasons.append("catalog_native_scope_as_of_invalid")
        else:
            if scope_as_of.tzinfo is None:
                reasons.append("catalog_native_scope_as_of_invalid")
            elif scope_as_of.astimezone(UTC) > context["cutoff"]:
                reasons.append("catalog_native_scope_as_of_future")
        if (
            item.get("adapter_id")
            != "ozon-seller-api-product-read-v1"
            or not item.get("adapter_version")
            or len(str(item.get("adapter_contract_sha256") or "")) != 64
            or item.get("source_grade") != "A"
            or item.get("semantic_authority")
            != "own_listing_catalog_fact"
        ):
            reasons.append("catalog_native_adapter_authority_invalid")
        return reasons

    def _empty(self, *, context: dict[str, Any]) -> dict[str, Any]:
        reason = str(context["reason"])
        return self._catalog_result(
            context=context,
            status=context["status"],
            items=[],
            queried=0,
            excluded={},
            ready_authorities=[],
            source_gaps=[f"catalog_{reason}"],
            blockers=[self._blocker(reason)],
            raw_read=False,
        )

    def _catalog_result(
        self,
        *,
        context: dict[str, Any],
        status: str,
        items: list[dict[str, Any]],
        queried: int,
        excluded: dict[str, int],
        ready_authorities: list[dict[str, Any]],
        source_gaps: list[str],
        blockers: list[dict[str, Any]],
        raw_read: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "items": items,
            "counts": {
                "queried_in_exact_store_scope": queried,
                "included": len(items),
                "excluded": queried - len(items),
                "bound_to_canonical_product": sum(
                    bool(item.get("canonical_product_id")) for item in items
                ),
            },
            "excluded": {
                "count": queried - len(items),
                "by_reason": excluded,
                "details_disclosed": False,
            },
            "evidence_authority_sha256": (
                self._hash(
                    sorted(
                        ready_authorities,
                        key=lambda item: item["evidence_id"],
                    )
                )
                if ready_authorities
                else None
            ),
            "source_gaps": source_gaps,
            "blockers": blockers,
            "source_classes": {
                "store_catalog": (
                    "evidence_bound_only" if raw_read else "not_read"
                ),
                "external_catalog": "excluded",
            },
            "control_envelope": {
                "read_only": True,
                "catalog_input_ready": status == "ready",
                "candidate_scoring_allowed": False,
                "content_draft_allowed": False,
                "pilot_approval_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
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
                "scope_grant_authority_sha256": entity_scope.get(
                    "authority_sha256"
                ),
            },
        }

    @staticmethod
    def _blocker(reason: str) -> dict[str, Any]:
        identity_reason = reason.startswith("entity_scope_")
        return {
            "code": reason,
            "severity": (
                "P0"
                if any(
                    token in reason
                    for token in ("mismatch", "conflict", "integrity")
                )
                else "P1"
            ),
            "owner": (
                "identity-governance"
                if identity_reason
                else "evidence-governance"
            ),
            "sla": "before catalog promotion or downstream candidate scoring",
            "next": (
                "Establish one current independently reviewed entity grant."
                if identity_reason
                else (
                    "Independently bind current immutable catalog source "
                    "Evidence to the exact operating scope."
                )
            ),
            "next_workspace": (
                "/commerce-os" if identity_reason else "/evidence"
            ),
        }

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
