from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .evidence import EvidenceGrade, EvidenceRecord, EvidenceService


class CandidateEvidenceAuthorityService:
    source = "candidate_evidence_authority_review"

    def __init__(self, *, evidence: EvidenceService, allowed_metrics: set[str]) -> None:
        self.evidence = evidence
        self.allowed_metrics = allowed_metrics

    def review(
        self,
        *,
        evidence_id: str,
        metric: str,
        approved_grade: EvidenceGrade,
        accepted: bool,
        authentic_original: bool,
        source_scope_matches: bool,
        authority_basis_verified: bool,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        metric = metric.strip()
        rationale = rationale.strip()
        if metric not in self.allowed_metrics:
            raise ValueError("Unsupported candidate evidence metric")
        if approved_grade not in {EvidenceGrade.A, EvidenceGrade.B}:
            raise ValueError("Candidate authority review may approve only A or B")
        if not rationale:
            raise ValueError("Candidate authority review requires a rationale")
        self.evidence.require_valid([evidence_id])
        original = self.evidence.get(evidence_id)
        if original.source == self.source:
            raise ValueError("Candidate authority attestations cannot review other attestations")
        if original.created_by == reviewed_by:
            raise ValueError("Candidate evidence uploader cannot review their own evidence")

        checks = {
            "authentic_original": authentic_original,
            "source_scope_matches": source_scope_matches,
            "authority_basis_verified": authority_basis_verified,
        }
        if accepted and not all(checks.values()):
            raise ValueError("Accepted candidate authority review requires all checks to pass")
        decision = "accepted" if accepted else "rejected"
        payload = {
            "decision": decision,
            "evidence_id": original.id,
            "evidence_sha256": original.sha256,
            "metric": metric,
            "approved_grade": approved_grade.value,
            "submitted_by": original.created_by,
            "reviewed_by": reviewed_by,
            "rationale": rationale,
            "checks": checks,
        }
        for prior in self._reviews(original, metric):
            if prior.created_by != reviewed_by:
                continue
            if all(prior.metadata.get(key) == value for key, value in payload.items()):
                return {"evidence": original, "review": prior, "idempotent": True}
            raise ValueError("Candidate authority review is immutable and cannot be overwritten")

        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        review = self.evidence.capture(
            content=content,
            filename=f"{original.id}-{metric}-authority-review.json",
            content_type="application/json",
            source=self.source,
            source_ref=f"candidate-evidence://{original.id}/{metric}/authority/{reviewed_by}",
            grade=EvidenceGrade.A,
            effective_at=datetime.now(UTC).isoformat(),
            effective_until=None,
            created_by=reviewed_by,
            metadata={"evidence_role": "authority_review_attestation", **payload},
        )
        edge = self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=original.id,
            relationship="candidate_authority_review",
            created_by=reviewed_by,
        )
        return {"evidence": original, "review": review, "lineage": edge, "idempotent": False}

    def status(self, evidence_id: str, metric: str) -> dict[str, Any]:
        metric = metric.strip()
        if metric not in self.allowed_metrics:
            raise ValueError("Unsupported candidate evidence metric")
        self.evidence.require_valid([evidence_id])
        original = self.evidence.get(evidence_id)
        reviews = self._reviews(original, metric)
        decisions = {item.metadata["decision"] for item in reviews}
        accepted_grades = sorted(
            {item.metadata["approved_grade"] for item in reviews if item.metadata["decision"] == "accepted"}
        )
        status = "rejected" if "rejected" in decisions else "accepted" if accepted_grades else "pending"
        return {
            "evidence_id": original.id,
            "metric": metric,
            "status": status,
            "accepted_grades": accepted_grades,
            "review_count": len(reviews),
        }

    def require_approved_grade(self, evidence_id: str, metric: str) -> EvidenceGrade:
        state = self.status(evidence_id, metric)
        if state["status"] != "accepted":
            raise ValueError("Candidate evidence requires an independent authority review")
        return EvidenceGrade.A if "A" in state["accepted_grades"] else EvidenceGrade.B

    def _reviews(self, original: EvidenceRecord, metric: str) -> list[EvidenceRecord]:
        review_ids = self.evidence.target_evidence_ids(
            target_type="evidence",
            target_id=original.id,
            relationship="candidate_authority_review",
        )
        reviews: list[EvidenceRecord] = []
        for review_id in review_ids:
            try:
                self.evidence.require_valid([review_id])
                review = self.evidence.get(review_id)
            except (KeyError, RuntimeError, ValueError):
                continue
            metadata = review.metadata
            checks = metadata.get("checks")
            if (
                review.source == self.source
                and metadata.get("evidence_role") == "authority_review_attestation"
                and metadata.get("evidence_id") == original.id
                and metadata.get("evidence_sha256") == original.sha256
                and metadata.get("metric") == metric
                and metadata.get("submitted_by") == original.created_by
                and metadata.get("reviewed_by") == review.created_by
                and review.created_by != original.created_by
                and metadata.get("decision") in {"accepted", "rejected"}
                and metadata.get("approved_grade") in {"A", "B"}
                and isinstance(metadata.get("rationale"), str)
                and metadata["rationale"].strip()
                and isinstance(checks, dict)
                and set(checks) == {"authentic_original", "source_scope_matches", "authority_basis_verified"}
                and all(isinstance(value, bool) for value in checks.values())
                and (metadata["decision"] != "accepted" or all(checks.values()))
            ):
                reviews.append(review)
        return reviews
