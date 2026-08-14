"""Generic governed exact-scope Evidence binding (BAS-104/105 enabler).

Old business Evidence (captured before an entity scope grant existed) is
immutable and can only gain an exact scope through an independent grade-A
``kjds-evidence-scope-binding-v1`` binding record (ADR-0034 / BAS-108).  This
service is the production path for that contract with strict separation of
duties: operator submits the binding request, an independent reviewer accepts
it, and a distinct compliance recorder writes the binding Evidence and its
lineage.  ``ScopedEvidenceAuthority`` then projects the target as scope-ready.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .evidence import EvidenceGrade, EvidenceService
from .evidence_scope import BINDING_CONTRACT, ScopedEvidenceAuthority
from .security import Principal

BINDING_CONTRACT_ID = "kjds-evidence-scope-binding-v1"
BINDING_SUBMISSION_SOURCE = "evidence_scope_binding_submission"
BINDING_SOURCE = "evidence_scope_binding"
BINDING_REVIEW_SOURCE = "evidence_scope_binding_review"
BINDING_SUBMISSION_CONTRACT = "kjds-evidence-scope-binding-submission-v1"
BINDING_REVIEW_CONTRACT = "kjds-evidence-scope-binding-review-v1"
BINDING_RELATIONSHIP = "evidence_scope_binding"
BINDING_REVIEW_RELATIONSHIP = "evidence_scope_binding_review"


class EvidenceScopeBindingService:
    """Record independent exact-scope bindings for immutable business Evidence."""

    def __init__(
        self,
        *,
        evidence: EvidenceService,
        scoped_evidence: ScopedEvidenceAuthority,
    ) -> None:
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence

    def submit_binding(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        target_evidence_id: str,
        idempotency_key: str,
        effective_at: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if not principal.has_any_role("operator", "admin"):
            raise PermissionError("Scope binding submission requires operator")
        scope = self._ready_scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        target_evidence_id = self._required(
            target_evidence_id, "target_evidence_id", 240
        )
        idempotency_key = self._required(
            idempotency_key, "idempotency_key", 300
        )
        bound_at = self._parse(effective_at, "effective_at")
        if bound_at > as_of:
            raise ValueError("effective_at cannot be in the future")
        self.evidence.require_current([target_evidence_id], as_of=bound_at)
        target = self.evidence.get(target_evidence_id)
        if target.created_by == principal.actor_id:
            raise PermissionError(
                "Scope binding submitter must be independent of the target evidence creator"
            )
        payload = {
            "contract_id": BINDING_SUBMISSION_CONTRACT,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "submitted_by": principal.actor_id,
            "effective_at": bound_at.isoformat(),
        }
        content = self._canonical_bytes(payload)
        source_ref = (
            f"evidence-scope-binding-submission://{scope['tenant_ref']}/"
            f"{principal.actor_id}/{idempotency_key}"
        )
        existing = self.evidence.find_by_source_ref(
            source=BINDING_SUBMISSION_SOURCE,
            source_ref=source_ref,
        )
        if existing is not None:
            self._require_replay(
                existing=existing,
                content=content,
                effective_at=bound_at,
                created_by=principal.actor_id,
            )
            return self._submission_projection(
                existing, idempotent=True
            )
        submission = self.evidence.capture(
            content=content,
            filename=f"{target.id}-scope-binding-submission.json",
            content_type="application/json",
            source=BINDING_SUBMISSION_SOURCE,
            source_ref=source_ref,
            grade=EvidenceGrade.A,
            effective_at=bound_at.isoformat(),
            effective_until=None,
            created_by=principal.actor_id,
            metadata={
                **payload,
                "contract_id": BINDING_SUBMISSION_CONTRACT,
                "retention_class": "compliance",
                "legal_hold": False,
            },
        )
        return self._submission_projection(submission, idempotent=False)

    def review_binding(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        submission_evidence_id: str,
        accepted: bool,
        rationale: str,
        effective_at: str,
        idempotency_key: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if not principal.has_any_role(
            "reviewer",
            "compliance",
            "risk",
            "admin",
        ):
            raise PermissionError("Scope binding review requires a reviewer role")
        scope = self._ready_scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        submission_evidence_id = self._required(
            submission_evidence_id, "submission_evidence_id", 240
        )
        rationale = self._required(rationale, "rationale", 5000)
        idempotency_key = self._required(
            idempotency_key, "idempotency_key", 300
        )
        bound_at = self._parse(effective_at, "effective_at")
        self.evidence.require_current(
            [submission_evidence_id], as_of=bound_at
        )
        submission = self.evidence.get(submission_evidence_id)
        submission_metadata = submission.metadata
        if (
            submission.source != BINDING_SUBMISSION_SOURCE
            or submission_metadata.get("contract_id")
            != BINDING_SUBMISSION_CONTRACT
            or submission.created_by == principal.actor_id
            or any(
                submission_metadata.get(key) != scope[key]
                for key in ("tenant_ref", "entity_ref", "store_ref")
            )
        ):
            raise ValueError(
                "Scope binding review requires an independent exact-scope submission"
            )
        target = self.evidence.get(
            submission_metadata.get("target_evidence_id")
        )
        if target.created_by == principal.actor_id:
            raise PermissionError(
                "Scope binding reviewer must be independent of the target evidence creator"
            )
        payload = {
            "contract_id": BINDING_REVIEW_CONTRACT,
            "submission_evidence_id": submission.id,
            "submission_evidence_sha256": submission.sha256,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "reviewed_by": principal.actor_id,
            "accepted": accepted,
            "rationale": rationale,
            "effective_at": bound_at.isoformat(),
        }
        content = self._canonical_bytes(payload)
        source_ref = (
            f"evidence-scope-binding-review://{scope['tenant_ref']}/"
            f"{principal.actor_id}/{idempotency_key}"
        )
        existing = self.evidence.find_by_source_ref(
            source=BINDING_REVIEW_SOURCE,
            source_ref=source_ref,
        )
        if existing is not None:
            self._require_replay(
                existing=existing,
                content=content,
                effective_at=bound_at,
                created_by=principal.actor_id,
            )
            return self._review_projection(
                submission=submission,
                review=existing,
                idempotent=True,
            )
        review = self.evidence.capture(
            content=content,
            filename=f"{submission.id}-scope-binding-review.json",
            content_type="application/json",
            source=BINDING_REVIEW_SOURCE,
            source_ref=source_ref,
            grade=EvidenceGrade.A,
            effective_at=bound_at.isoformat(),
            effective_until=None,
            created_by=principal.actor_id,
            metadata={
                **payload,
                "contract_id": BINDING_REVIEW_CONTRACT,
                "retention_class": "compliance",
                "legal_hold": False,
            },
        )
        self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=submission.id,
            relationship=BINDING_REVIEW_RELATIONSHIP,
            created_by=principal.actor_id,
        )
        return self._review_projection(
            submission=submission,
            review=review,
            idempotent=False,
        )

    def record_binding(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        submission_evidence_id: str,
        review_evidence_id: str,
        effective_at: str,
        idempotency_key: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if not principal.has_any_role("compliance", "admin"):
            raise PermissionError("Scope binding recording requires compliance")
        scope = self._ready_scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        submission_evidence_id = self._required(
            submission_evidence_id, "submission_evidence_id", 240
        )
        review_evidence_id = self._required(
            review_evidence_id, "review_evidence_id", 240
        )
        idempotency_key = self._required(
            idempotency_key, "idempotency_key", 300
        )
        bound_at = self._parse(effective_at, "effective_at")
        self.evidence.require_current(
            [submission_evidence_id, review_evidence_id],
            as_of=bound_at,
        )
        submission = self.evidence.get(submission_evidence_id)
        review = self.evidence.get(review_evidence_id)
        submission_metadata = submission.metadata
        review_metadata = review.metadata
        target = self.evidence.get(
            submission_metadata.get("target_evidence_id")
        )
        if (
            submission.source != BINDING_SUBMISSION_SOURCE
            or submission_metadata.get("contract_id")
            != BINDING_SUBMISSION_CONTRACT
            or review.source != BINDING_REVIEW_SOURCE
            or review_metadata.get("contract_id") != BINDING_REVIEW_CONTRACT
            or review_metadata.get("submission_evidence_id")
            != submission.id
            or review_metadata.get("submission_evidence_sha256")
            != submission.sha256
            or review_metadata.get("accepted") is not True
            or not str(review_metadata.get("rationale") or "").strip()
            or any(
                review_metadata.get(key) != scope[key]
                for key in ("tenant_ref", "entity_ref", "store_ref")
            )
            or review.created_by == submission.created_by
            or review.created_by == target.created_by
            or principal.actor_id
            in {submission.created_by, review.created_by, target.created_by}
        ):
            raise ValueError(
                "Scope binding record requires an accepted independent review"
            )
        payload = {
            "evidence_scope_contract_id": BINDING_CONTRACT,
            "contract_id": BINDING_CONTRACT_ID,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "reviewed_by": review.created_by,
            "review_evidence_id": review.id,
            "review_evidence_sha256": review.sha256,
            "recorded_by": principal.actor_id,
            "effective_at": bound_at.isoformat(),
        }
        content = self._canonical_bytes(payload)
        source_ref = (
            f"evidence-scope-binding://{scope['tenant_ref']}/"
            f"{principal.actor_id}/{idempotency_key}"
        )
        existing = self.evidence.find_by_source_ref(
            source=BINDING_SOURCE,
            source_ref=source_ref,
        )
        if existing is not None:
            self._require_replay(
                existing=existing,
                content=content,
                effective_at=bound_at,
                created_by=principal.actor_id,
            )
            return self._binding_projection(
                target=target,
                review=review,
                binding=existing,
                idempotent=True,
            )
        self._require_unbound(
            target=target,
            scope=scope,
            principal=principal,
            as_of=bound_at,
        )
        metadata = {
            **payload,
            "retention_class": "compliance",
            "legal_hold": False,
        }
        binding = self.evidence.capture(
            content=content,
            filename=f"{target.id}-scope-binding.json",
            content_type="application/json",
            source=BINDING_SOURCE,
            source_ref=source_ref,
            grade=EvidenceGrade.A,
            effective_at=bound_at.isoformat(),
            effective_until=None,
            created_by=principal.actor_id,
            metadata=metadata,
        )
        self.evidence.link(
            evidence_id=binding.id,
            target_type="evidence",
            target_id=target.id,
            relationship=BINDING_RELATIONSHIP,
            created_by=principal.actor_id,
        )
        self.evidence.link(
            evidence_id=binding.id,
            target_type="evidence",
            target_id=review.id,
            relationship=BINDING_REVIEW_RELATIONSHIP,
            created_by=principal.actor_id,
        )
        return self._binding_projection(
            target=target,
            review=review,
            binding=binding,
            idempotent=False,
        )

    def _require_unbound(
        self,
        *,
        target,
        scope: dict[str, str],
        principal: Principal,
        as_of: datetime,
    ) -> None:
        projection = self.scoped_evidence.project_targets(
            evidence_ids=[target.id],
            principal=principal,
            entity_scope={
                "status": "ready",
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "authority_sha256": "0" * 64,
            },
            store_ref=scope["store_ref"],
            as_of=as_of,
        )
        for record in projection.get("records", []):
            if (
                record.get("evidence_id") == target.id
                and (record.get("scope_binding") or {}).get("status")
                == "ready"
            ):
                raise ValueError(
                    "Target Evidence already has an exact-scope binding"
                )

    def _ready_scope(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, str]:
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        if (
            entity_scope.get("status") != "ready"
            or not entity_scope.get("entity_ref")
        ):
            raise ValueError(
                "Scope binding requires one current entity scope grant"
            )
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": str(entity_scope["entity_ref"]),
            "store_ref": store_ref,
        }

    def _submission_projection(
        self,
        submission,
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {
            "contract_id": BINDING_SUBMISSION_CONTRACT,
            "submission_evidence_id": submission.id,
            "submission_evidence_sha256": submission.sha256,
            "target_evidence_id": submission.metadata.get(
                "target_evidence_id"
            ),
            "status": "pending_independent_review",
            "idempotent": idempotent,
            "binding_recorded": False,
        }

    def _review_projection(
        self,
        *,
        submission,
        review,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {
            "contract_id": BINDING_REVIEW_CONTRACT,
            "submission_evidence_id": submission.id,
            "review_evidence_id": review.id,
            "review_evidence_sha256": review.sha256,
            "reviewed_by": review.metadata.get("reviewed_by"),
            "accepted": review.metadata.get("accepted"),
            "status": (
                "accepted" if review.metadata.get("accepted") else "rejected"
            ),
            "idempotent": idempotent,
            "binding_recorded": False,
        }

    def _binding_projection(
        self,
        *,
        target,
        review,
        binding,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {
            "contract_id": BINDING_CONTRACT_ID,
            "binding_evidence_id": binding.id,
            "binding_evidence_sha256": binding.sha256,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "review_evidence_id": review.id,
            "reviewed_by": binding.metadata.get("reviewed_by"),
            "recorded_by": binding.metadata.get("recorded_by"),
            "tenant_ref": binding.metadata.get("tenant_ref"),
            "entity_ref": binding.metadata.get("entity_ref"),
            "store_ref": binding.metadata.get("store_ref"),
            "binding_recorded": True,
            "idempotent": idempotent,
        }

    @staticmethod
    def _required(value: Any, name: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > limit:
            raise ValueError(f"{name} is required")
        return normalized

    @staticmethod
    def _parse(value: str, name: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _canonical_bytes(value: dict[str, Any]) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def _require_replay(
        self,
        *,
        existing,
        content: bytes,
        effective_at: datetime,
        created_by: str,
    ) -> None:
        if (
            existing.sha256 != hashlib.sha256(content).hexdigest()
            or existing.created_by != created_by
            or self._parse(existing.effective_at, "effective_at")
            != effective_at
        ):
            raise ValueError(
                "Scope binding replay conflicts with immutable values"
            )
