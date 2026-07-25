from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .evidence import EvidenceGrade, EvidenceRecord, EvidenceService
from .sourcing import listing_snapshot_sha256


class ListingExecutionAuthorityService:
    """Persist and resolve independent attestations required for Listing execution."""

    listing_source = "listing_russian_native_review"
    listing_relationship = "listing_russian_native_review"
    identity_source = "ozon_execution_identity_authority_review"
    identity_relationship = "ozon_execution_identity_authority_review"
    identity_target_type = "ozon_execution_identity"
    identity_gate_id = "OZN-001"
    listing_checks = frozenset(
        {
            "native_russian_verified",
            "listing_snapshot_reviewed",
            "terminology_accepted",
            "claims_grounded",
            "ozon_policy_checked",
        }
    )
    identity_checks = frozenset(
        {
            "inventory_complete",
            "credential_material_absent",
            "owner_verified",
            "caller_system_verified",
            "scope_minimized",
            "dedicated_executor",
        }
    )

    def __init__(self, *, evidence: EvidenceService, sourcing) -> None:
        self.evidence = evidence
        self.sourcing = sourcing

    def review_listing(
        self,
        draft_id: str,
        *,
        accepted: bool,
        native_russian_verified: bool,
        listing_snapshot_reviewed: bool,
        terminology_accepted: bool,
        claims_grounded: bool,
        ozon_policy_checked: bool,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        draft_id = self._required(draft_id, "Listing draft")
        rationale = self._required(rationale, "Russian native review rationale")
        reviewed_by = self._required(reviewed_by, "Russian native reviewer")
        draft = self.sourcing.store.get_listing_draft(draft_id)
        if reviewed_by == draft.requested_by:
            raise ValueError("Listing requester cannot perform the Russian native review")
        checks = {
            "native_russian_verified": native_russian_verified,
            "listing_snapshot_reviewed": listing_snapshot_reviewed,
            "terminology_accepted": terminology_accepted,
            "claims_grounded": claims_grounded,
            "ozon_policy_checked": ozon_policy_checked,
        }
        self._accepted_checks(accepted, checks, self.listing_checks, "Russian native review")
        snapshot_hash = listing_snapshot_sha256(draft)
        payload = {
            "decision": "accepted" if accepted else "rejected",
            "draft_id": draft.id,
            "listing_snapshot_sha256": snapshot_hash,
            "submitted_by": draft.requested_by,
            "reviewed_by": reviewed_by,
            "rationale": rationale,
            "checks": checks,
        }
        for prior in self._listing_reviews(draft.id, snapshot_hash):
            if prior.created_by != reviewed_by:
                continue
            if all(prior.metadata.get(key) == value for key, value in payload.items()):
                return {"draft": draft, "review": prior, "idempotent": True}
            raise ValueError("Russian native review is immutable and cannot be overwritten")

        review = self._capture(
            payload,
            filename=f"{draft.id}-{snapshot_hash}-russian-native-review.json",
            source=self.listing_source,
            source_ref=f"listing://{draft.id}/snapshot/{snapshot_hash}/russian-review/{reviewed_by}",
            reviewed_by=reviewed_by,
            evidence_role="listing_russian_native_review_attestation",
        )
        edge = self.evidence.link(
            evidence_id=review.id,
            target_type="listing_draft",
            target_id=draft.id,
            relationship=self.listing_relationship,
            created_by=reviewed_by,
        )
        return {
            "draft": draft,
            "review": review,
            "lineage": edge,
            "idempotent": False,
        }

    def listing_status(self, draft) -> dict[str, Any]:
        snapshot_hash = listing_snapshot_sha256(draft)
        reviews = self._listing_reviews(draft.id, snapshot_hash)
        decisions = {item.metadata["decision"] for item in reviews}
        status = (
            "rejected"
            if "rejected" in decisions
            else "accepted"
            if "accepted" in decisions
            else "pending"
        )
        return {
            "draft_id": draft.id,
            "listing_snapshot_sha256": snapshot_hash,
            "status": status,
            "review_ids": [item.id for item in reviews],
        }

    def require_listing_review(self, draft) -> dict[str, Any]:
        state = self.listing_status(draft)
        if state["status"] != "accepted":
            raise ValueError("Listing requires an accepted Russian native review")
        return state

    def review_execution_identity(
        self,
        evidence_id: str,
        *,
        identity_ref: str,
        accepted: bool,
        inventory_complete: bool,
        credential_material_absent: bool,
        owner_verified: bool,
        caller_system_verified: bool,
        scope_minimized: bool,
        dedicated_executor: bool,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        identity_ref = self._required(identity_ref, "Ozon execution identity reference")
        rationale = self._required(rationale, "Ozon execution identity review rationale")
        reviewed_by = self._required(reviewed_by, "Ozon execution identity reviewer")
        self.evidence.require_current([evidence_id])
        original = self.evidence.get(evidence_id)
        if original.grade != EvidenceGrade.A:
            raise ValueError("Execution identity inventory requires Grade A evidence")
        if original.source == self.identity_source:
            raise ValueError("Execution identity attestations cannot review other attestations")
        if original.created_by == reviewed_by:
            raise ValueError("Execution identity inventory uploader cannot review their own evidence")
        gate_evidence_ids = self.evidence.target_evidence_ids(
            target_type="gate_requirement",
            target_id=self.identity_gate_id,
        )
        if original.id not in gate_evidence_ids:
            raise ValueError("Execution identity inventory must satisfy OZN-001")
        checks = {
            "inventory_complete": inventory_complete,
            "credential_material_absent": credential_material_absent,
            "owner_verified": owner_verified,
            "caller_system_verified": caller_system_verified,
            "scope_minimized": scope_minimized,
            "dedicated_executor": dedicated_executor,
        }
        self._accepted_checks(accepted, checks, self.identity_checks, "Execution identity review")
        payload = {
            "decision": "accepted" if accepted else "rejected",
            "evidence_id": original.id,
            "evidence_sha256": original.sha256,
            "identity_ref": identity_ref,
            "submitted_by": original.created_by,
            "reviewed_by": reviewed_by,
            "rationale": rationale,
            "checks": checks,
        }
        for prior in self._identity_reviews(identity_ref):
            if (
                prior.metadata.get("evidence_id") != original.id
                or prior.created_by != reviewed_by
            ):
                continue
            if all(prior.metadata.get(key) == value for key, value in payload.items()):
                return {"evidence": original, "review": prior, "idempotent": True}
            raise ValueError("Execution identity review is immutable and cannot be overwritten")

        review = self._capture(
            payload,
            filename=f"{original.id}-{identity_ref}-execution-identity-review.json",
            source=self.identity_source,
            source_ref=f"ozon-identity://{identity_ref}/inventory/{original.id}/review/{reviewed_by}",
            reviewed_by=reviewed_by,
            evidence_role="ozon_execution_identity_authority_attestation",
        )
        original_edge = self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=original.id,
            relationship=self.identity_relationship,
            created_by=reviewed_by,
        )
        identity_edge = self.evidence.link(
            evidence_id=review.id,
            target_type=self.identity_target_type,
            target_id=identity_ref,
            relationship=self.identity_relationship,
            created_by=reviewed_by,
        )
        return {
            "evidence": original,
            "review": review,
            "lineage": [original_edge, identity_edge],
            "idempotent": False,
        }

    def identity_status(self, identity_ref: str) -> dict[str, Any]:
        identity_ref = self._required(identity_ref, "Ozon execution identity reference")
        reviews = self._identity_reviews(identity_ref)
        decisions = {item.metadata["decision"] for item in reviews}
        accepted = [item for item in reviews if item.metadata["decision"] == "accepted"]
        status = (
            "rejected"
            if "rejected" in decisions
            else "accepted"
            if accepted
            else "pending"
        )
        return {
            "identity_ref": identity_ref,
            "status": status,
            "evidence_ids": sorted(
                {
                    *(item.id for item in reviews),
                    *(item.metadata["evidence_id"] for item in reviews),
                }
            ),
            "review_ids": [item.id for item in reviews],
        }

    def require_execution_identity(self, identity_ref: str) -> dict[str, Any]:
        state = self.identity_status(identity_ref)
        if state["status"] != "accepted":
            raise ValueError("Ozon execution identity requires an independent authority review")
        return state

    def _listing_reviews(self, draft_id: str, snapshot_hash: str) -> list[EvidenceRecord]:
        review_ids = self.evidence.target_evidence_ids(
            target_type="listing_draft",
            target_id=draft_id,
            relationship=self.listing_relationship,
        )
        reviews: list[EvidenceRecord] = []
        for review_id in review_ids:
            try:
                self.evidence.require_current([review_id])
                review = self.evidence.get(review_id)
            except (KeyError, RuntimeError, ValueError):
                continue
            metadata = review.metadata
            checks = metadata.get("checks")
            if (
                review.source == self.listing_source
                and review.grade == EvidenceGrade.A
                and metadata.get("evidence_role")
                == "listing_russian_native_review_attestation"
                and metadata.get("draft_id") == draft_id
                and metadata.get("listing_snapshot_sha256") == snapshot_hash
                and metadata.get("reviewed_by") == review.created_by
                and metadata.get("submitted_by") != review.created_by
                and metadata.get("decision") in {"accepted", "rejected"}
                and isinstance(metadata.get("rationale"), str)
                and metadata["rationale"].strip()
                and self._valid_checks(
                    metadata["decision"], checks, self.listing_checks
                )
            ):
                reviews.append(review)
        return reviews

    def _identity_reviews(self, identity_ref: str) -> list[EvidenceRecord]:
        review_ids = self.evidence.target_evidence_ids(
            target_type=self.identity_target_type,
            target_id=identity_ref,
            relationship=self.identity_relationship,
        )
        gate_evidence_ids = set(
            self.evidence.target_evidence_ids(
                target_type="gate_requirement",
                target_id=self.identity_gate_id,
            )
        )
        reviews: list[EvidenceRecord] = []
        for review_id in review_ids:
            try:
                self.evidence.require_current([review_id])
                review = self.evidence.get(review_id)
                original_id = review.metadata.get("evidence_id")
                self.evidence.require_current([original_id])
                original = self.evidence.get(original_id)
            except (KeyError, RuntimeError, TypeError, ValueError):
                continue
            metadata = review.metadata
            checks = metadata.get("checks")
            original_review_ids = self.evidence.target_evidence_ids(
                target_type="evidence",
                target_id=original.id,
                relationship=self.identity_relationship,
            )
            if (
                review.source == self.identity_source
                and review.grade == EvidenceGrade.A
                and review.id in original_review_ids
                and original.id in gate_evidence_ids
                and original.grade == EvidenceGrade.A
                and metadata.get("evidence_role")
                == "ozon_execution_identity_authority_attestation"
                and metadata.get("evidence_sha256") == original.sha256
                and metadata.get("identity_ref") == identity_ref
                and metadata.get("submitted_by") == original.created_by
                and metadata.get("reviewed_by") == review.created_by
                and review.created_by != original.created_by
                and metadata.get("decision") in {"accepted", "rejected"}
                and isinstance(metadata.get("rationale"), str)
                and metadata["rationale"].strip()
                and self._valid_checks(
                    metadata["decision"], checks, self.identity_checks
                )
            ):
                reviews.append(review)
        return reviews

    def _capture(
        self,
        payload: dict[str, Any],
        *,
        filename: str,
        source: str,
        source_ref: str,
        reviewed_by: str,
        evidence_role: str,
    ) -> EvidenceRecord:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self.evidence.capture(
            content=content,
            filename=filename,
            content_type="application/json",
            source=source,
            source_ref=source_ref,
            grade=EvidenceGrade.A,
            effective_at=datetime.now(UTC).isoformat(),
            effective_until=None,
            created_by=reviewed_by,
            metadata={"evidence_role": evidence_role, **payload},
        )

    @staticmethod
    def _accepted_checks(
        accepted: bool,
        checks: dict[str, bool],
        expected: frozenset[str],
        name: str,
    ) -> None:
        if set(checks) != expected or any(
            not isinstance(value, bool) for value in checks.values()
        ):
            raise ValueError(f"{name} checks are invalid")
        if accepted and not all(checks.values()):
            raise ValueError(f"Accepted {name.lower()} requires all checks to pass")

    @staticmethod
    def _valid_checks(
        decision: str,
        checks: Any,
        expected: frozenset[str],
    ) -> bool:
        return (
            isinstance(checks, dict)
            and set(checks) == expected
            and all(isinstance(value, bool) for value in checks.values())
            and (decision != "accepted" or all(checks.values()))
        )

    @staticmethod
    def _required(value: str, name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} is required")
        return normalized
