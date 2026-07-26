from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .evidence import EvidenceGrade, EvidenceRecord, EvidenceService

QUOTE_DOCUMENT_KINDS = frozenset(
    {"public_display_price", "supplier_confirmed_quote", "proforma_invoice"}
)
CONFIRMABLE_QUOTE_DOCUMENT_KINDS = frozenset(
    {"supplier_confirmed_quote", "proforma_invoice"}
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


class SupplierQuoteAuthorityService:
    source = "supplier_quote_source"
    review_source = "supplier_quote_authority_review"
    relationship = "supplier_quote_authority_review"

    def __init__(self, *, evidence: EvidenceService) -> None:
        self.evidence = evidence

    def capture(
        self,
        *,
        product_id: str,
        document_kind: str,
        offer_data: dict[str, Any],
        content: bytes,
        filename: str,
        content_type: str,
        effective_at: str,
        effective_until: str | None,
        created_by: str,
        rfq_package_evidence_id: str | None = None,
    ) -> EvidenceRecord:
        document_kind = document_kind.strip()
        if document_kind not in QUOTE_DOCUMENT_KINDS:
            raise ValueError("Unsupported supplier quote document kind")
        if (
            document_kind in CONFIRMABLE_QUOTE_DOCUMENT_KINDS
            and not effective_until
        ):
            raise ValueError("Confirmable supplier quotes require an effective-until timestamp")
        supplier_ref = str(offer_data.get("supplier_ref", "")).strip()
        external_id = str(offer_data.get("external_id", "")).strip()
        if not supplier_ref or not external_id:
            raise ValueError("Supplier quote source requires supplier and snapshot references")
        normalized_offer = _json_value(offer_data)
        digest_source = (
            f"supplier-quote://{product_id}/{external_id}/{document_kind}"
        )
        return self.evidence.capture(
            content=content,
            filename=filename,
            content_type=content_type,
            source=self.source,
            source_ref=digest_source,
            grade=EvidenceGrade.B,
            effective_at=effective_at,
            effective_until=effective_until,
            created_by=created_by,
            metadata={
                "evidence_role": "supplier_quote_source",
                "product_id": product_id,
                "supplier_ref": supplier_ref,
                "document_kind": document_kind,
                "offer_data": normalized_offer,
                "rfq_package_evidence_id": rfq_package_evidence_id,
                "formal_offer_eligible": (
                    document_kind in CONFIRMABLE_QUOTE_DOCUMENT_KINDS
                ),
                "automatic_supplier_contact": False,
                "automatic_procurement": False,
                "automatic_listing": False,
            },
        )

    def review(
        self,
        *,
        evidence_id: str,
        accepted: bool,
        authentic_original: bool,
        supplier_identity_matches: bool,
        product_spec_matches: bool,
        amount_currency_moq_matches: bool,
        validity_and_delivery_terms_present: bool,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        rationale = rationale.strip()
        if not rationale:
            raise ValueError("Supplier quote authority review requires a rationale")
        self.evidence.require_current([evidence_id])
        original = self.evidence.get(evidence_id)
        self._require_source(original)
        if original.created_by == reviewed_by:
            raise ValueError("Supplier quote uploader cannot review their own evidence")
        if (
            accepted
            and original.metadata["document_kind"]
            not in CONFIRMABLE_QUOTE_DOCUMENT_KINDS
        ):
            raise ValueError("Public display prices cannot become confirmed supplier quotes")

        checks = {
            "authentic_original": authentic_original,
            "supplier_identity_matches": supplier_identity_matches,
            "product_spec_matches": product_spec_matches,
            "amount_currency_moq_matches": amount_currency_moq_matches,
            "validity_and_delivery_terms_present": validity_and_delivery_terms_present,
        }
        if accepted and not all(checks.values()):
            raise ValueError("Accepted supplier quote review requires all checks to pass")
        payload = {
            "decision": "accepted" if accepted else "rejected",
            "evidence_id": original.id,
            "evidence_sha256": original.sha256,
            "product_id": original.metadata["product_id"],
            "supplier_ref": original.metadata["supplier_ref"],
            "document_kind": original.metadata["document_kind"],
            "offer_data": original.metadata["offer_data"],
            "submitted_by": original.created_by,
            "reviewed_by": reviewed_by,
            "rationale": rationale,
            "checks": checks,
        }
        for prior in self._reviews(original):
            if prior.created_by != reviewed_by:
                continue
            if all(prior.metadata.get(key) == value for key, value in payload.items()):
                return {
                    "evidence": original,
                    "review": prior,
                    "idempotent": True,
                }
            raise ValueError("Supplier quote review is immutable and cannot be overwritten")

        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        review = self.evidence.capture(
            content=content,
            filename=f"{original.id}-supplier-quote-authority-review.json",
            content_type="application/json",
            source=self.review_source,
            source_ref=f"supplier-quote://{original.id}/authority/{reviewed_by}",
            grade=EvidenceGrade.A,
            effective_at=datetime.now(UTC).isoformat(),
            effective_until=self._timezone_timestamp(original.effective_until),
            created_by=reviewed_by,
            metadata={
                "evidence_role": "supplier_quote_authority_attestation",
                **payload,
            },
        )
        lineage = self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=original.id,
            relationship=self.relationship,
            created_by=reviewed_by,
        )
        return {
            "evidence": original,
            "review": review,
            "lineage": lineage,
            "idempotent": False,
        }

    def status(self, evidence_id: str) -> dict[str, Any]:
        self.evidence.require_valid([evidence_id])
        original = self.evidence.get(evidence_id)
        self._require_source(original)
        reviews = self._reviews(original)
        decisions = {item.metadata["decision"] for item in reviews}
        status = (
            "rejected"
            if "rejected" in decisions
            else "accepted"
            if "accepted" in decisions
            else "research_only"
            if original.metadata["document_kind"] == "public_display_price"
            else "pending"
        )
        return {
            "evidence": original,
            "status": status,
            "review_ids": [item.id for item in reviews],
            "review_count": len(reviews),
            "formal_offer_eligible": (
                original.metadata["document_kind"]
                in CONFIRMABLE_QUOTE_DOCUMENT_KINDS
            ),
            "automatic_supplier_contact": False,
            "automatic_procurement": False,
            "automatic_listing": False,
        }

    def list(self, *, product_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        records = [
            record
            for record in self.evidence.list_by_source(
                self.source,
                limit=2000 if product_id else limit,
            )
            if record.metadata.get("evidence_role") == "supplier_quote_source"
            and (
                product_id is None
                or record.metadata.get("product_id") == product_id
            )
        ][:limit]
        return [self.status(record.id) for record in records]

    def require_accepted(self, evidence_id: str) -> EvidenceRecord:
        self.evidence.require_current([evidence_id])
        state = self.status(evidence_id)
        if state["status"] != "accepted":
            raise ValueError("Supplier quote requires an independent accepted review")
        return state["evidence"]

    @staticmethod
    def offer_data(original: EvidenceRecord) -> dict[str, Any]:
        raw = original.metadata.get("offer_data")
        if not isinstance(raw, dict):
            raise ValueError("Supplier quote source is missing frozen offer terms")
        return dict(raw)

    def _require_source(self, original: EvidenceRecord) -> None:
        metadata = original.metadata
        if (
            original.source != self.source
            or original.grade != EvidenceGrade.B
            or metadata.get("evidence_role") != "supplier_quote_source"
            or metadata.get("document_kind") not in QUOTE_DOCUMENT_KINDS
            or not isinstance(metadata.get("offer_data"), dict)
            or metadata.get("product_id")
            != metadata["offer_data"].get("product_id")
        ):
            raise ValueError("Evidence is not a governed supplier quote source")

    @staticmethod
    def _timezone_timestamp(value: str | None) -> str | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()

    def _reviews(self, original: EvidenceRecord) -> list[EvidenceRecord]:
        review_ids = self.evidence.target_evidence_ids(
            target_type="evidence",
            target_id=original.id,
            relationship=self.relationship,
        )
        reviews: list[EvidenceRecord] = []
        expected_checks = {
            "authentic_original",
            "supplier_identity_matches",
            "product_spec_matches",
            "amount_currency_moq_matches",
            "validity_and_delivery_terms_present",
        }
        for review_id in review_ids:
            try:
                self.evidence.require_valid([review_id])
                review = self.evidence.get(review_id)
            except (KeyError, RuntimeError, ValueError):
                continue
            metadata = review.metadata
            checks = metadata.get("checks")
            if (
                review.source == self.review_source
                and review.grade == EvidenceGrade.A
                and metadata.get("evidence_role")
                == "supplier_quote_authority_attestation"
                and metadata.get("evidence_id") == original.id
                and metadata.get("evidence_sha256") == original.sha256
                and metadata.get("product_id") == original.metadata["product_id"]
                and metadata.get("supplier_ref")
                == original.metadata["supplier_ref"]
                and metadata.get("document_kind")
                == original.metadata["document_kind"]
                and metadata.get("offer_data") == original.metadata["offer_data"]
                and metadata.get("submitted_by") == original.created_by
                and metadata.get("reviewed_by") == review.created_by
                and review.created_by != original.created_by
                and metadata.get("decision") in {"accepted", "rejected"}
                and isinstance(metadata.get("rationale"), str)
                and metadata["rationale"].strip()
                and isinstance(checks, dict)
                and set(checks) == expected_checks
                and all(isinstance(value, bool) for value in checks.values())
                and (
                    metadata["decision"] != "accepted"
                    or (
                        original.metadata["document_kind"]
                        in CONFIRMABLE_QUOTE_DOCUMENT_KINDS
                        and all(checks.values())
                    )
                )
            ):
                reviews.append(review)
        return reviews
