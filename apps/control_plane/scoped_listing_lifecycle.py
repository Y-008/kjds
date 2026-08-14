from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .domain import ApprovalStatus
from .evidence import EvidenceGrade
from .security import Principal
from .sourcing import listing_snapshot_sha256


class ScopedListingLifecycleWorkspace:
    """Project exact-scope Listing changes and governed lifecycle state."""

    CONTRACT_ID = "kjds-native-exact-scope-listing-lifecycle-v1"
    ARTIFACT_CONTRACT_ID = "kjds-listing-steward-artifact-v1"
    PIM_CONTRACT_ID = "kjds-native-exact-scope-pim-workspace-v1"
    REVIEW_SOURCE = "listing_russian_native_review"
    REVIEW_RELATIONSHIP = "listing_russian_native_review"
    REVIEW_ROLE = "listing_russian_native_review_attestation"
    REVIEW_CHECKS = frozenset(
        {
            "native_russian_verified",
            "listing_snapshot_reviewed",
            "terminology_accepted",
            "claims_grounded",
            "ozon_policy_checked",
        }
    )
    DIFF_FIELDS = (
        "title",
        "description",
        "category_id",
        "attributes",
        "images",
    )
    STAGES = frozenset(
        {
            "draft_pending_review",
            "review_rejected",
            "approval_pending",
            "approval_rejected",
            "approved",
            "plan_created",
            "plan_approval_pending",
            "dry_run_failed",
            "dry_run_verified_external_gate",
            "blocked",
        }
    )
    MAX_DRAFTS = 1000
    MAX_PIM_GROUPS = 200

    def __init__(
        self,
        *,
        pim,
        listing_store,
        scoped_evidence,
        evidence,
        approval_repository,
        execution_plans,
    ) -> None:
        self.pim = pim
        self.listing_store = listing_store
        self.scoped_evidence = scoped_evidence
        self.evidence = evidence
        self.approval_repository = approval_repository
        self.execution_plans = execution_plans

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
        stage: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= page_size <= 200:
            raise ValueError(
                "Listing lifecycle page_size must be between 1 and 200"
            )
        if stage is not None and stage not in self.STAGES:
            raise ValueError("Listing lifecycle stage filter is invalid")
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
                items=[],
                total_items=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                stage=stage,
                source_gaps=[
                    f"listing_lifecycle_{context['reason']}"
                ],
                blockers=[
                    self._blocker(str(context["reason"]))
                ],
                raw_read=False,
            )

        pim = self.pim.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            page_size=self.MAX_PIM_GROUPS,
        )
        conflicts = self._pim_conflicts(
            projection=pim,
            context=context,
        )
        if pim.get("query", {}).get("next_cursor"):
            conflicts.append("pim_projection_truncated")
        if conflicts or pim.get("status") == "blocked":
            gaps = sorted(
                {
                    *conflicts,
                    *self._strings(pim.get("source_gaps")),
                }
            )
            return self._result(
                context=context,
                status="blocked",
                items=[],
                total_items=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                stage=stage,
                source_gaps=gaps,
                blockers=[
                    *[
                        self._blocker(reason)
                        for reason in conflicts
                    ],
                    *self._blockers(pim.get("blockers")),
                ],
                upstream={
                    "pim_snapshot_sha256": pim.get(
                        "snapshot_sha256"
                    ),
                },
            )

        drafts = self.listing_store.list_listing_drafts_scoped(
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
            limit=self.MAX_DRAFTS + 1,
        )
        if len(drafts) > self.MAX_DRAFTS:
            return self._result(
                context=context,
                status="blocked",
                items=[],
                total_items=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                stage=stage,
                source_gaps=["listing_draft_projection_truncated"],
                blockers=[
                    self._blocker(
                        "listing_draft_projection_truncated"
                    )
                ],
                upstream={
                    "pim_snapshot_sha256": pim[
                        "snapshot_sha256"
                    ],
                },
            )

        selected, superseded = self._latest_drafts(drafts)
        plan_rows = self.execution_plans.list_for_listing_drafts(
            draft_ids=[draft.id for draft in selected],
            as_of=context["cutoff"],
        )
        plans_by_draft: dict[str, list[dict[str, Any]]] = {}
        for plan in plan_rows:
            plans_by_draft.setdefault(
                str(plan["source_id"]), []
            ).append(plan)
        pim_groups = {
            str(item["product"]["id"]): item
            for item in pim.get("product_groups", [])
        }
        items = [
            self._item(
                draft=draft,
                context=context,
                pim_group=pim_groups.get(draft.product_id),
                plans=plans_by_draft.get(draft.id, []),
            )
            for draft in selected
        ]
        items.sort(key=self._sort_key)
        if normalized_query:
            items = [
                item
                for item in items
                if normalized_query
                in " ".join(
                    [
                        item["identity"]["product_id"],
                        item["identity"]["sku"],
                        item["identity"]["product_name"],
                        item["identity"]["offer_id"],
                        item["identity"]["draft_id"],
                    ]
                ).casefold()
            ]
        if stage:
            items = [
                item
                for item in items
                if item["lifecycle"]["stage"] == stage
            ]
        counts = self._counts(items, superseded=superseded)
        total_items = len(items)
        if normalized_cursor:
            cursor_key = self._decode_cursor(normalized_cursor)
            items = [
                item
                for item in items
                if self._sort_key(item) > cursor_key
            ]
        page = items[:page_size]
        next_cursor = (
            self._encode_cursor(self._sort_key(page[-1]))
            if page and len(items) > page_size
            else None
        )
        source_gaps = sorted(
            {
                *self._strings(pim.get("source_gaps")),
                *(
                    ["listing_drafts_not_available"]
                    if not selected
                    else []
                ),
                *(
                    ["superseded_listing_drafts_present"]
                    if superseded
                    else []
                ),
                *[
                    gap
                    for item in page
                    for gap in item["source_gaps"]
                ],
            }
        )
        blockers = [
            *self._blockers(pim.get("blockers")),
            *[
                blocker
                for item in page
                for blocker in item["blockers"]
            ],
        ]
        status = (
            "no_data"
            if not selected and pim.get("status") == "no_data"
            else "blocked"
            if page and all(
                item["lifecycle"]["stage"] == "blocked"
                for item in page
            )
            else "partial"
            if source_gaps
            or any(
                item["lifecycle"]["stage"]
                != "dry_run_verified_external_gate"
                for item in page
            )
            else "ready"
        )
        return self._result(
            context=context,
            status=status,
            items=page,
            total_items=total_items,
            page_size=page_size,
            cursor=normalized_cursor,
            next_cursor=next_cursor,
            query=normalized_query,
            stage=stage,
            source_gaps=source_gaps,
            blockers=blockers,
            counts=counts,
            upstream={
                "pim_snapshot_sha256": pim[
                    "snapshot_sha256"
                ],
            },
        )

    def _item(
        self,
        *,
        draft,
        context: dict[str, Any],
        pim_group: dict[str, Any] | None,
        plans: list[dict[str, Any]],
    ) -> dict[str, Any]:
        reasons = self._draft_reasons(
            draft=draft,
            context=context,
            pim_group=pim_group,
        )
        desired: dict[str, Any] | None = None
        observed: dict[str, Any] | None = None
        review = {
            "status": "pending",
            "review_id": None,
            "review_sha256": None,
            "reviewed_by": None,
        }
        approval = {
            "status": "pending",
            "approval_id": draft.approval_id,
            "decided_by": None,
            "independent": False,
        }
        plan = None
        evidence_authority_sha256 = None
        if not reasons:
            desired, desired_reasons = self._desired(draft.listing_data)
            reasons.extend(desired_reasons)
        if not reasons:
            evidence_projection = self.scoped_evidence.project_targets(
                evidence_ids=list(draft.evidence_ids),
                principal=context["principal"],
                entity_scope=context["entity_scope"],
                store_ref=context["scope"]["store_ref"],
                as_of=context["cutoff"],
            )
            reasons.extend(
                self._evidence_reasons(
                    projection=evidence_projection,
                    expected_ids=draft.evidence_ids,
                )
            )
            evidence_authority_sha256 = (
                evidence_projection.get(
                    "binding_authority_sha256"
                )
            )
        if not reasons:
            observed = self._observed(
                group=pim_group,
                offer_id=draft.offer_id,
            )
            review, review_reasons = self._review(
                draft=draft,
                as_of=context["cutoff"],
            )
            reasons.extend(review_reasons)
        if not reasons and draft.approval_id:
            approval, approval_reasons = self._approval(
                draft=draft,
                as_of=context["cutoff"],
            )
            reasons.extend(approval_reasons)
        if not reasons and plans:
            plan, plan_reasons = self._plan(
                draft=draft,
                plans=plans,
                context=context,
            )
            reasons.extend(plan_reasons)

        blocked = bool(reasons)
        diffs = (
            []
            if blocked or desired is None
            else self._diff(
                observed=observed,
                desired=desired,
            )
        )
        lifecycle = self._lifecycle(
            blocked=blocked,
            review=review,
            approval=approval,
            plan=plan,
        )
        product = (
            pim_group.get("product", {})
            if pim_group
            else {}
        )
        item = {
            "identity": {
                "product_id": draft.product_id,
                "sku": str(product.get("sku") or ""),
                "product_name": str(
                    product.get("name") or ""
                ),
                "offer_id": draft.offer_id,
                "draft_id": draft.id,
                "target_platform": draft.target_platform,
            },
            "authority": {
                "scope_grant_authority_sha256": (
                    draft.scope_grant_authority_sha256
                ),
                "frozen_product_snapshot_sha256": (
                    draft.scoped_product_content_sha256
                ),
                "current_product_snapshot_sha256": (
                    pim_group.get("snapshot_sha256")
                    if pim_group
                    else None
                ),
                "approval_plan_sha256": (
                    draft.approval_plan_sha256
                ),
                "listing_snapshot_sha256": (
                    listing_snapshot_sha256(draft)
                ),
                "evidence_ids": sorted(draft.evidence_ids),
                "evidence_authority_sha256": (
                    evidence_authority_sha256
                ),
            },
            "observed_platform_listing": (
                None if blocked else observed
            ),
            "desired_listing_draft": (
                None if blocked else desired
            ),
            "field_diffs": diffs,
            "review": review,
            "approval": approval,
            "execution_plan": plan,
            "readback": {
                "status": "not_available",
                "receipt_id": None,
                "matches_approved_snapshot": None,
            },
            "lifecycle": lifecycle,
            "source_gaps": sorted(
                {
                    *reasons,
                    *(
                        ["platform_listing_not_observed"]
                        if not blocked and observed is None
                        else []
                    ),
                    "platform_readback_not_available",
                }
            ),
            "blockers": [
                self._blocker(reason) for reason in reasons
            ],
            "owner": lifecycle["owner"],
            "sla": "before any Listing Approval, Permit or publish decision",
            "next": lifecycle["next"],
            "next_workspace": lifecycle["next_workspace"],
        }
        item["item_sha256"] = self._hash(item)
        return item

    def _draft_reasons(
        self,
        *,
        draft,
        context: dict[str, Any],
        pim_group: dict[str, Any] | None,
    ) -> list[str]:
        reasons: list[str] = []
        if draft.tenant_ref != context["scope"]["tenant_ref"]:
            reasons.append("listing_draft_tenant_scope_mismatch")
        if draft.entity_ref != context["scope"]["entity_ref"]:
            reasons.append("listing_draft_entity_scope_mismatch")
        if draft.store_ref != context["scope"]["store_ref"]:
            reasons.append("listing_draft_store_scope_mismatch")
        if (
            draft.scope_grant_authority_sha256
            != context["scope"][
                "scope_grant_authority_sha256"
            ]
        ):
            reasons.append(
                "listing_draft_scope_authority_mismatch"
            )
        if str(draft.target_platform).strip().upper() != "OZON":
            reasons.append("listing_draft_platform_invalid")
        try:
            created_at = self._time(draft.created_at)
            scope_as_of = self._time(draft.scope_as_of)
        except ValueError:
            reasons.append("listing_draft_timestamp_invalid")
        else:
            if created_at > context["cutoff"]:
                reasons.append("listing_draft_created_in_future")
            if scope_as_of > context["cutoff"]:
                reasons.append("listing_draft_scope_as_of_future")
        if pim_group is None:
            reasons.append("listing_product_not_in_current_pim")
        elif (
            draft.scoped_product_content_sha256
            != pim_group.get("snapshot_sha256")
        ):
            reasons.append(
                "listing_product_snapshot_drift"
            )
        if (
            not isinstance(draft.approval_plan_sha256, str)
            or len(draft.approval_plan_sha256) != 64
        ):
            reasons.append("listing_approval_plan_hash_invalid")
        evidence_ids = [
            str(item).strip() for item in draft.evidence_ids
        ]
        if (
            not evidence_ids
            or any(not item for item in evidence_ids)
            or len(evidence_ids) != len(set(evidence_ids))
        ):
            reasons.append(
                "listing_draft_evidence_set_invalid"
            )
        return sorted(set(reasons))

    @classmethod
    def _desired(
        cls, raw: Any
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if not isinstance(raw, dict):
            return None, ["listing_desired_payload_invalid"]
        missing = [
            field for field in cls.DIFF_FIELDS if field not in raw
        ]
        if missing:
            return None, [
                "listing_desired_fields_missing"
            ]
        if not isinstance(raw["title"], str) or not raw[
            "title"
        ].strip():
            return None, ["listing_desired_title_invalid"]
        if not isinstance(raw["description"], str) or not raw[
            "description"
        ].strip():
            return None, ["listing_desired_description_invalid"]
        if not isinstance(raw["category_id"], (str, int)):
            return None, ["listing_desired_category_invalid"]
        if not isinstance(raw["attributes"], (dict, list)):
            return None, ["listing_desired_attributes_invalid"]
        if (
            not isinstance(raw["images"], list)
            or not raw["images"]
            or any(
                not isinstance(item, str) or not item.strip()
                for item in raw["images"]
            )
        ):
            return None, ["listing_desired_images_invalid"]
        return {
            "title": raw["title"].strip(),
            "description": raw["description"].strip(),
            "category_id": str(raw["category_id"]).strip(),
            "attributes": raw["attributes"],
            "images": [item.strip() for item in raw["images"]],
        }, []

    @staticmethod
    def _observed(
        *,
        group: dict[str, Any] | None,
        offer_id: str,
    ) -> dict[str, Any] | None:
        if group is None:
            return None
        listing = next(
            (
                item
                for item in group.get("listings", [])
                if str(item.get("offer_id") or "") == offer_id
            ),
            None,
        )
        if listing is None:
            return None
        fields = listing.get("observed_fields")
        if not isinstance(fields, dict):
            fields = {}
        return {
            "offer_id": offer_id,
            "marketplace_sku": listing.get(
                "marketplace_sku"
            ),
            "listing_status": listing.get(
                "listing_status"
            )
            or listing.get("platform_statuses"),
            "item_hash": listing.get("item_hash"),
            "source_evidence_id": listing.get(
                "source_evidence_id"
            ),
            "fields": {
                field: fields.get(field)
                for field in ScopedListingLifecycleWorkspace.DIFF_FIELDS
            },
        }

    def _review(
        self,
        *,
        draft,
        as_of: datetime,
    ) -> tuple[dict[str, Any], list[str]]:
        review_ids = self.evidence.target_evidence_ids(
            target_type="listing_draft",
            target_id=draft.id,
            relationship=self.REVIEW_RELATIONSHIP,
        )
        records = []
        for evidence_id in review_ids:
            try:
                record = self.evidence.get(evidence_id)
                recorded_at = self._time(record.recorded_at)
                effective_at = self._time(record.effective_at)
            except (KeyError, RuntimeError, ValueError):
                return self._pending_review(), [
                    "listing_review_evidence_invalid"
                ]
            if recorded_at > as_of or effective_at > as_of:
                continue
            try:
                self.evidence.require_current(
                    [record.id], as_of=as_of
                )
            except (KeyError, RuntimeError, ValueError):
                return self._pending_review(), [
                    "listing_review_evidence_invalid"
                ]
            reasons = self._review_reasons(
                record=record,
                draft=draft,
            )
            if reasons:
                return self._pending_review(), reasons
            records.append(record)
        if not records:
            return self._pending_review(), []
        latest = sorted(
            records,
            key=lambda item: (
                self._time(item.effective_at),
                self._time(item.recorded_at),
                item.id,
            ),
        )[-1]
        return {
            "status": latest.metadata["decision"],
            "review_id": latest.id,
            "review_sha256": latest.sha256,
            "reviewed_by": latest.created_by,
        }, []

    def _review_reasons(
        self, *, record, draft
    ) -> list[str]:
        metadata = record.metadata
        checks = metadata.get("checks")
        decision = metadata.get("decision")
        valid = (
            record.source == self.REVIEW_SOURCE
            and record.grade == EvidenceGrade.A
            and metadata.get("evidence_role")
            == self.REVIEW_ROLE
            and metadata.get("draft_id") == draft.id
            and metadata.get("listing_snapshot_sha256")
            == listing_snapshot_sha256(draft)
            and metadata.get("submitted_by")
            == draft.requested_by
            and metadata.get("reviewed_by")
            == record.created_by
            and record.created_by != draft.requested_by
            and decision in {"accepted", "rejected"}
            and isinstance(metadata.get("rationale"), str)
            and bool(metadata["rationale"].strip())
            and isinstance(checks, dict)
            and set(checks) == self.REVIEW_CHECKS
            and all(
                isinstance(value, bool)
                for value in checks.values()
            )
            and (
                decision != "accepted"
                or all(checks.values())
            )
        )
        return [] if valid else [
            "listing_review_contract_invalid"
        ]

    def _approval(
        self,
        *,
        draft,
        as_of: datetime,
    ) -> tuple[dict[str, Any], list[str]]:
        try:
            approval = self.approval_repository.get_approval_at(
                draft.approval_id,
                as_of=as_of,
            )
        except (KeyError, RuntimeError, ValueError):
            return {
                "status": "blocked",
                "approval_id": draft.approval_id,
                "decided_by": None,
                "independent": False,
            }, ["listing_approval_authority_invalid"]
        reasons = []
        if (
            approval.action != "listing.publish"
            or approval.resource_type != "listing_draft"
            or approval.resource_id != draft.id
            or approval.requested_by != draft.requested_by
            or approval.payload.get("draft_id") != draft.id
            or approval.payload.get("listing_snapshot_sha256")
            != listing_snapshot_sha256(draft)
        ):
            reasons.append("listing_approval_snapshot_mismatch")
        if (
            approval.status == ApprovalStatus.APPROVED
            and (
                not approval.decided_by
                or approval.decided_by
                == approval.requested_by
            )
        ):
            reasons.append(
                "listing_approval_independence_invalid"
            )
        return {
            "status": approval.status.value,
            "approval_id": approval.id,
            "decided_by": approval.decided_by,
            "independent": bool(
                approval.decided_by
                and approval.decided_by
                != approval.requested_by
            ),
        }, sorted(set(reasons))

    def _plan(
        self,
        *,
        draft,
        plans: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        ordered = sorted(
            plans,
            key=lambda item: (
                self._time(item["created_at"]),
                item["id"],
            ),
        )
        latest = ordered[-1]
        reasons = []
        if (
            latest.get("source_kind")
            != "approved_listing_draft"
            or latest.get("source_id") != draft.id
            or latest.get("source_snapshot_hash")
            != listing_snapshot_sha256(draft)
            or latest.get("action_id")
            != "listing_publish"
        ):
            reasons.append("listing_execution_plan_source_mismatch")
        evidence_ids = latest.get("evidence_ids")
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or len(evidence_ids) != len(set(evidence_ids))
        ):
            reasons.append(
                "listing_execution_plan_evidence_invalid"
            )
        elif not reasons:
            projection = self.scoped_evidence.project_targets(
                evidence_ids=evidence_ids,
                principal=context["principal"],
                entity_scope=context["entity_scope"],
                store_ref=context["scope"]["store_ref"],
                as_of=context["cutoff"],
            )
            reasons.extend(
                self._evidence_reasons(
                    projection=projection,
                    expected_ids=evidence_ids,
                )
            )
        approval_status = "pending"
        try:
            plan_approval = (
                self.approval_repository.get_approval_at(
                    latest["approval_id"],
                    as_of=context["cutoff"],
                )
            )
        except (KeyError, RuntimeError, ValueError):
            reasons.append(
                "listing_plan_approval_authority_invalid"
            )
        else:
            approval_status = plan_approval.status.value
            if (
                plan_approval.resource_type
                != "governed_execution_plan"
                or plan_approval.resource_id != latest["id"]
            ):
                reasons.append(
                    "listing_plan_approval_target_mismatch"
                )
            if (
                plan_approval.status
                == ApprovalStatus.APPROVED
                and (
                    not plan_approval.decided_by
                    or plan_approval.decided_by
                    == plan_approval.requested_by
                )
            ):
                reasons.append(
                    "listing_plan_approval_independence_invalid"
                )
        dry_run = latest.get("dry_run")
        return {
            "plan_id": latest["id"],
            "plan_sha256": latest.get("request_hash"),
            "approval_id": latest["approval_id"],
            "approval_status": approval_status,
            "dry_run": dry_run,
            "permit_created": False,
            "external_execution_ready": False,
        }, sorted(set(reasons))

    @classmethod
    def _diff(
        cls,
        *,
        observed: dict[str, Any] | None,
        desired: dict[str, Any],
    ) -> list[dict[str, Any]]:
        observed_fields = (
            observed.get("fields", {}) if observed else {}
        )
        result = []
        for field in cls.DIFF_FIELDS:
            observed_present = (
                field in observed_fields
                and observed_fields[field] is not None
            )
            desired_present = (
                field in desired and desired[field] is not None
            )
            observed_value = observed_fields.get(field)
            desired_value = desired.get(field)
            state = (
                "source_missing"
                if not observed_present and desired_present
                else "desired_missing"
                if observed_present and not desired_present
                else "same"
                if cls._canonical(observed_value)
                == cls._canonical(desired_value)
                else "changed"
            )
            result.append(
                {
                    "field": field,
                    "state": state,
                    "observed_value": observed_value,
                    "desired_value": desired_value,
                }
            )
        return result

    @staticmethod
    def _lifecycle(
        *,
        blocked: bool,
        review: dict[str, Any],
        approval: dict[str, Any],
        plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if blocked:
            stage = "blocked"
        elif review["status"] == "pending":
            stage = "draft_pending_review"
        elif review["status"] == "rejected":
            stage = "review_rejected"
        elif approval["status"] == "pending":
            stage = "approval_pending"
        elif approval["status"] == "rejected":
            stage = "approval_rejected"
        elif plan is None:
            stage = "approved"
        elif plan["approval_status"] != "approved":
            stage = "plan_approval_pending"
        elif plan["dry_run"] is None:
            stage = "plan_created"
        elif plan["dry_run"].get("passed") is not True:
            stage = "dry_run_failed"
        else:
            stage = "dry_run_verified_external_gate"
        lookup = {
            "blocked": (
                "listing-governance",
                "Repair the failed exact-scope authority before any decision.",
                "/authority-intake",
            ),
            "draft_pending_review": (
                "content-governance",
                "Complete an independent Russian-native Listing review.",
                "/listings",
            ),
            "review_rejected": (
                "content-governance",
                "Revise the draft from the rejected review; do not reuse it.",
                "/listings",
            ),
            "approval_pending": (
                "business-approver",
                "Independently decide the frozen Listing snapshot.",
                "/listings",
            ),
            "approval_rejected": (
                "listing-owner",
                "Create a new corrected draft; the rejected snapshot is immutable.",
                "/pim",
            ),
            "approved": (
                "execution-planning",
                "Prepare a governed execution plan without issuing a Permit.",
                "/listings",
            ),
            "plan_approval_pending": (
                "risk-approver",
                "Independently review the execution plan and risk envelope.",
                "/listings",
            ),
            "plan_created": (
                "execution-verifier",
                "Run the deterministic dry run and verify every precondition.",
                "/listings",
            ),
            "dry_run_failed": (
                "execution-verifier",
                "Repair dry-run failures; no Permit may be issued.",
                "/listings",
            ),
            "dry_run_verified_external_gate": (
                "release-authority",
                "Keep publish gated until release, one-time Permit and readback.",
                "/commerce-os",
            ),
        }
        owner, next_action, workspace = lookup[stage]
        return {
            "stage": stage,
            "owner": owner,
            "next": next_action,
            "next_workspace": workspace,
            "external_write_allowed": False,
        }

    def _result(
        self,
        *,
        context: dict[str, Any],
        status: str,
        items: list[dict[str, Any]],
        total_items: int,
        page_size: int,
        cursor: str | None,
        next_cursor: str | None,
        query: str,
        stage: str | None,
        source_gaps: list[str],
        blockers: list[dict[str, Any]],
        raw_read: bool = True,
        counts: dict[str, int] | None = None,
        upstream: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        blocker_map = {
            (item["code"], item["owner"]): item
            for item in blockers
        }
        resolved_counts = counts or {
            "total": total_items,
            "blocked": 0,
            "changed": 0,
            "source_missing": 0,
            "approval_pending": 0,
            "dry_run_verified": 0,
            "superseded": 0,
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
                "stage": stage,
            },
            "counts": {
                **resolved_counts,
                "page": len(items),
                "total": total_items,
            },
            "items": items,
            "source_gaps": sorted(set(source_gaps)),
            "blockers": [
                blocker_map[key]
                for key in sorted(blocker_map)
            ],
            "upstream_authority": upstream or {},
            "control_envelope": {
                "read_only": True,
                "scoped_input_read": raw_read,
                "client_recalculation_allowed": False,
                "draft_created": False,
                "review_created": False,
                "approval_created": False,
                "execution_plan_created": False,
                "permit_created": False,
                "platform_task_created": False,
                "readback_created": False,
                "self_approval_allowed": False,
                "permit_issue_allowed": False,
                "external_write_allowed": False,
            },
        }
        input_hash = self._hash(core)
        suggestions = [
            {
                "draft_id": item["identity"]["draft_id"],
                "stage": item["lifecycle"]["stage"],
                "owner": item["owner"],
                "next": item["next"],
            }
            for item in items
            if item["lifecycle"]["stage"]
            != "dry_run_verified_external_gate"
        ]
        core["agent_artifact"] = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "artifact_sha256": self._hash(
                {
                    "contract_id": self.ARTIFACT_CONTRACT_ID,
                    "input_snapshot_sha256": input_hash,
                    "suggestions": suggestions,
                }
            ),
            "input_snapshot_sha256": input_hash,
            "authority": (
                "decision_support_and_internal_task_suggestion_only"
            ),
            "suggestions": suggestions,
            "draft_create_allowed": False,
            "approval_create_allowed": False,
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "publish_allowed": False,
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
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
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
        invalid_ready = (
            entity_scope.get("status") == "ready"
            and (
                not entity_present
                or len(authority_sha256) != 64
            )
        )
        return {
            "status": (
                "ready"
                if ready
                else "blocked"
                if entity_scope.get("status") == "blocked"
                or invalid_ready
                else "no_data"
            ),
            "reason": (
                None
                if ready
                else "entity_scope_authority_invalid"
                if invalid_ready
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
                    if ready
                    else None
                ),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    authority_sha256 if ready else None
                ),
            },
        }

    @classmethod
    def _pim_conflicts(
        cls,
        *,
        projection: dict[str, Any],
        context: dict[str, Any],
    ) -> list[str]:
        conflicts = []
        if projection.get("contract_id") != cls.PIM_CONTRACT_ID:
            conflicts.append("pim_contract_conflict")
        if projection.get("scope") != context["scope"]:
            conflicts.append("pim_scope_conflict")
        if projection.get("as_of") != context["cutoff"].isoformat():
            conflicts.append("pim_as_of_conflict")
        if len(str(projection.get("snapshot_sha256") or "")) != 64:
            conflicts.append("pim_snapshot_integrity_invalid")
        if projection.get("status") not in {
            "ready",
            "partial",
            "no_data",
            "blocked",
        }:
            conflicts.append("pim_status_conflict")
        return sorted(set(conflicts))

    @staticmethod
    def _latest_drafts(drafts) -> tuple[list[Any], int]:
        grouped: dict[tuple[str, str, str], list[Any]] = {}
        for draft in drafts:
            grouped.setdefault(
                (
                    draft.product_id,
                    str(draft.target_platform).upper(),
                    draft.offer_id,
                ),
                [],
            ).append(draft)
        selected = []
        superseded = 0
        for values in grouped.values():
            ordered = sorted(
                values,
                key=lambda item: (
                    ScopedListingLifecycleWorkspace._time(
                        item.created_at
                    ),
                    item.id,
                ),
            )
            selected.append(ordered[-1])
            superseded += len(ordered) - 1
        return selected, superseded

    @staticmethod
    def _counts(
        items: list[dict[str, Any]], *, superseded: int
    ) -> dict[str, int]:
        return {
            "total": len(items),
            "blocked": sum(
                item["lifecycle"]["stage"] == "blocked"
                for item in items
            ),
            "changed": sum(
                any(
                    diff["state"] == "changed"
                    for diff in item["field_diffs"]
                )
                for item in items
            ),
            "source_missing": sum(
                any(
                    diff["state"] == "source_missing"
                    for diff in item["field_diffs"]
                )
                for item in items
            ),
            "approval_pending": sum(
                item["lifecycle"]["stage"]
                == "approval_pending"
                for item in items
            ),
            "dry_run_verified": sum(
                item["lifecycle"]["stage"]
                == "dry_run_verified_external_gate"
                for item in items
            ),
            "superseded": superseded,
        }

    @staticmethod
    def _evidence_reasons(
        *,
        projection: dict[str, Any],
        expected_ids: list[str],
    ) -> list[str]:
        expected = set(expected_ids)
        records = {
            item.get("evidence_id"): item
            for item in projection.get("records", [])
            if item.get("evidence_id") in expected
        }
        if (
            projection.get("status") != "ready"
            or projection.get("invalid_evidence_ids")
            or set(records) != expected
            or any(
                item.get("scope_binding", {}).get("status")
                != "ready"
                for item in records.values()
            )
        ):
            return ["listing_evidence_authority_invalid"]
        return []

    @staticmethod
    def _pending_review() -> dict[str, Any]:
        return {
            "status": "pending",
            "review_id": None,
            "review_sha256": None,
            "reviewed_by": None,
        }

    @staticmethod
    def _blocker(code: str) -> dict[str, Any]:
        return {
            "code": code,
            "severity": (
                "P0"
                if any(
                    token in code
                    for token in (
                        "invalid",
                        "mismatch",
                        "drift",
                        "conflict",
                        "future",
                        "truncated",
                    )
                )
                else "P1"
            ),
            "owner": (
                "identity-governance"
                if "entity_scope" in code
                else "evidence-governance"
                if "evidence" in code or "review" in code
                else "listing-governance"
            ),
            "sla": "before any Listing Approval, Permit or publish decision",
            "next": (
                "Repair exact-scope authority and rerun the Listing lifecycle projection."
            ),
            "next_workspace": (
                "/authority-intake"
                if "scope" in code or "evidence" in code
                else "/pim"
            ),
        }

    @staticmethod
    def _blockers(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            item for item in value if isinstance(item, dict)
        ]

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            str(item)
            for item in value
            if isinstance(item, str) and item
        ]

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (
            item["identity"]["sku"],
            item["identity"]["offer_id"],
            item["identity"]["draft_id"],
        )

    @staticmethod
    def _encode_cursor(value: tuple[str, str, str]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(
                value, separators=(",", ":")
            ).encode()
        ).decode()

    @staticmethod
    def _decode_cursor(
        value: str,
    ) -> tuple[str, str, str]:
        try:
            decoded = json.loads(
                base64.urlsafe_b64decode(value.encode())
            )
            if (
                not isinstance(decoded, list)
                or len(decoded) != 3
                or not all(
                    isinstance(item, str)
                    for item in decoded
                )
            ):
                raise ValueError
            return decoded[0], decoded[1], decoded[2]
        except (
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "Listing lifecycle cursor is invalid"
            ) from exc

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @staticmethod
    def _time(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        else:
            raise ValueError("timestamp is invalid")
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include timezone")
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
            ).encode()
        ).hexdigest()
