from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from typing import Any

from .security import Principal


class ScopedMarketplaceObservationAuthority:
    """Return only Evidence-bound observations for one operating scope."""

    CONTRACT_ID = "kjds-scoped-marketplace-observation-v1"

    def __init__(self, *, observations, scoped_evidence) -> None:
        self.observations = observations
        self.scoped_evidence = scoped_evidence

    def latest(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        marketplace: str | None = None,
        source_profile: str | None = None,
        target_product_id: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            return self._empty(
                context=context,
                marketplace=marketplace,
                pagination=None,
            )
        raw = self.observations.latest(
            marketplace=marketplace,
            source_profile=source_profile,
            target_product_id=target_product_id,
            limit=limit,
            store_refs={store_ref},
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            as_of=as_of,
        )
        return self._project(
            raw=raw,
            context=context,
            marketplace=marketplace,
            pagination=None,
        )

    def page(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        marketplace: str,
        cursor: str | None = None,
        page_size: int = 500,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            return self._empty(
                context=context,
                marketplace=marketplace,
                pagination={
                    "page_size": page_size,
                    "next_cursor": None,
                    "cursor_contract": (
                        "scoped_observed_at_desc_item_id_asc_v1"
                    ),
                },
            )
        raw_page = self.observations.page(
            marketplace=marketplace,
            cursor=cursor,
            page_size=page_size,
            store_refs={store_ref},
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            as_of=as_of,
        )
        projection = self._project(
            raw=raw_page["items"],
            context=context,
            marketplace=marketplace,
            pagination={
                "page_size": page_size,
                "next_cursor": None,
                "cursor_contract": (
                    "scoped_observed_at_desc_item_id_asc_v1"
                ),
            },
        )
        if (
            len(raw_page["items"]) == page_size
            and projection["items"]
        ):
            last = projection["items"][-1]
            projection["pagination"]["next_cursor"] = (
                urlsafe_b64encode(
                    self._canonical(
                        {
                            "observed_at": last["observed_at"],
                            "item_id": last["id"],
                        }
                    )
                ).decode()
            )
            projection["snapshot_sha256"] = self._hash(
                {
                    key: value
                    for key, value in projection.items()
                    if key != "snapshot_sha256"
                }
            )
        return projection

    def collect(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        marketplace: str,
        page_size: int = 500,
        max_rows: int = 50000,
    ) -> dict[str, Any]:
        """Collect a bounded current-fact input without exposing raw cursors."""
        if not 1 <= page_size <= 1000:
            raise ValueError("Observation page_size must be 1 to 1000")
        if not 1 <= max_rows <= 50000:
            raise ValueError("Observation max_rows must be 1 to 50000")
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        pagination = {
            "page_size": page_size,
            "pages_read": 0,
            "raw_rows_read": 0,
            "max_rows": max_rows,
            "truncated": False,
            "next_cursor": None,
            "cursor_disclosed": False,
            "cursor_contract": "internal_bounded_collection_v1",
        }
        if context["status"] != "ready":
            return self._empty(
                context=context,
                marketplace=marketplace,
                pagination=pagination,
            )
        cursor = None
        seen_cursors: set[str] = set()
        latest_by_fingerprint: dict[str, dict[str, Any]] = {}
        while pagination["raw_rows_read"] < max_rows:
            remaining = max_rows - pagination["raw_rows_read"]
            raw_page = self.observations.page(
                marketplace=marketplace,
                cursor=cursor,
                page_size=min(page_size, remaining),
                store_refs={store_ref},
                tenant_ref=context["scope"]["tenant_ref"],
                entity_ref=context["scope"]["entity_ref"],
                as_of=as_of,
            )
            pagination["pages_read"] += 1
            pagination["raw_rows_read"] += len(raw_page["items"])
            for item in raw_page["items"]:
                latest_by_fingerprint.setdefault(
                    item["fingerprint"],
                    item,
                )
            next_cursor = raw_page["next_cursor"]
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                raise RuntimeError("Observation cursor did not advance")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        if (
            pagination["raw_rows_read"] >= max_rows
            and cursor is not None
        ):
            pagination["truncated"] = True
        projection = self._project(
            raw=list(latest_by_fingerprint.values()),
            context=context,
            marketplace=marketplace,
            pagination=pagination,
        )
        if pagination["truncated"]:
            projection["source_gaps"] = sorted(
                {
                    *projection["source_gaps"],
                    "observation_scan_truncated",
                }
            )
            projection["blockers"].append(
                {
                    "code": "observation_scan_truncated",
                    "severity": "P1",
                    "owner": "market-data",
                    "sla": "before complete candidate ranking",
                    "next": (
                        "Run the next deterministic shard or increase the "
                        "bounded scan limit."
                    ),
                    "next_workspace": "/commerce-os",
                }
            )
            projection["control_envelope"][
                "observation_input_ready"
            ] = False
            projection["snapshot_sha256"] = self._hash(
                {
                    key: value
                    for key, value in projection.items()
                    if key != "snapshot_sha256"
                }
            )
        return projection

    def _project(
        self,
        *,
        raw: list[dict[str, Any]],
        context: dict[str, Any],
        marketplace: str | None,
        pagination: dict[str, Any] | None,
    ) -> dict[str, Any]:
        target_ids = sorted(
            {
                str(item.get("evidence_id", "")).strip()
                for item in raw
                if str(item.get("evidence_id", "")).strip()
            }
        )
        evidence_projection = self.scoped_evidence.project_targets(
            evidence_ids=target_ids,
            principal=context["principal"],
            entity_scope=context["entity_scope"],
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
        )
        records = {
            item["evidence_id"]: item
            for item in evidence_projection["records"]
            if item["evidence_id"] in target_ids
        }
        invalid_ids = set(evidence_projection["invalid_evidence_ids"])
        authority_reasons = sorted(
            {
                reason
                for reason in evidence_projection["source_gaps"]
                if reason.startswith("evidence_scope_conflict:")
            }
        )
        included: list[dict[str, Any]] = []
        excluded: dict[str, int] = {}
        ready_authorities: list[dict[str, Any]] = []
        for item in raw:
            evidence_id = str(item.get("evidence_id", "")).strip()
            record = records.get(evidence_id)
            reasons: list[str] = []
            if item.get("tenant_ref") is not None and (
                item.get("tenant_ref")
                != context["scope"]["tenant_ref"]
                or item.get("entity_ref")
                != context["scope"]["entity_ref"]
                or item.get("store_ref")
                != context["scope"]["store_ref"]
                or item.get("scope_grant_authority_sha256")
                != context["scope"]["scope_grant_authority_sha256"]
                or not item.get("adapter_contract_sha256")
            ):
                reasons = ["native_observation_scope_mismatch"]
            elif not evidence_id:
                reasons = ["observation_evidence_missing"]
            elif evidence_id in invalid_ids:
                reasons = ["evidence_integrity_invalid"]
            elif record is None:
                reasons = ["evidence_scope_projection_missing"]
            elif record["scope_binding"]["status"] != "ready":
                reasons = (
                    record["scope_binding"]["reasons"]
                    or [f"evidence_scope_{record['scope_binding']['status']}"]
                )
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

        excluded_count = sum(excluded.values())
        if evidence_projection["status"] == "blocked":
            status = "blocked"
        elif included and not excluded_count:
            status = "ready"
        elif included:
            status = "partial"
        elif any(
            "mismatch" in reason
            or "conflict" in reason
            or "integrity" in reason
            for reason in excluded
        ):
            status = "blocked"
        else:
            status = "no_data"
        source_gaps = sorted(
            {
                *(f"observation_{reason}" for reason in excluded),
                *(
                    f"observation_{reason}"
                    for reason in authority_reasons
                ),
            }
        )
        if not source_gaps and not included:
            source_gaps = ["observation_not_available"]
        blockers = [
            self._blocker(reason)
            for reason in sorted({*excluded, *authority_reasons})
        ]
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "marketplace": marketplace,
            "items": included,
            "counts": {
                "queried_in_exact_store_scope": len(raw),
                "included": len(included),
                "excluded": len(raw) - len(included),
            },
            "excluded": {
                "count": len(raw) - len(included),
                "by_reason": excluded,
                "details_disclosed": False,
            },
            "evidence_authority_sha256": (
                self._hash(sorted(
                    ready_authorities,
                    key=lambda item: item["evidence_id"],
                ))
                if ready_authorities
                else None
            ),
            "source_gaps": source_gaps,
            "blockers": blockers,
            "source_classes": {
                "store_scoped_observations": "evidence_bound_only",
                "shared_external_observations": (
                    "excluded_publication_authority_missing"
                ),
            },
            "pagination": pagination,
            "control_envelope": {
                "read_only": True,
                "research_only": True,
                "formal_fact_promoted": False,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "observation_input_ready": status == "ready",
                "candidate_scoring_allowed": False,
                "pilot_approval_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _empty(
        self,
        *,
        context: dict[str, Any],
        marketplace: str | None,
        pagination: dict[str, Any] | None,
    ) -> dict[str, Any]:
        reason = context["reason"]
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": context["status"],
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "marketplace": marketplace,
            "items": [],
            "counts": {
                "queried_in_exact_store_scope": 0,
                "included": 0,
                "excluded": 0,
            },
            "excluded": {
                "count": 0,
                "by_reason": {},
                "details_disclosed": False,
            },
            "evidence_authority_sha256": None,
            "source_gaps": [f"observation_{reason}"],
            "blockers": [self._blocker(reason)],
            "source_classes": {
                "store_scoped_observations": "not_read",
                "shared_external_observations": (
                    "excluded_publication_authority_missing"
                ),
            },
            "pagination": pagination,
            "control_envelope": {
                "read_only": True,
                "research_only": True,
                "formal_fact_promoted": False,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "candidate_scoring_allowed": False,
                "pilot_approval_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @classmethod
    def _context(
        cls,
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
        reason = entity_scope.get(
            "reason",
            "entity_scope_authority_missing",
        )
        return {
            "status": status,
            "reason": None if entity_ready else reason,
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
            "severity": "P0" if "mismatch" in reason or "integrity" in reason else "P1",
            "owner": (
                "identity-governance"
                if identity_reason
                else "evidence-governance"
            ),
            "sla": "before candidate scoring or Pilot approval",
            "next": (
                "Establish one current independently reviewed entity grant."
                if identity_reason
                else "Independently bind current immutable source Evidence to the exact operating scope."
            ),
            "next_workspace": (
                "/commerce-os" if identity_reason else "/evidence"
            ),
        }

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()
