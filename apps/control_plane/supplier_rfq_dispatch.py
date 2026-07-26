from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .evidence import EvidenceGrade, EvidenceRecord

DISPATCH_CONTRACT_VERSION = "supplier-rfq-dispatch-v1"
DISPATCH_SOURCE = "supplier_rfq_dispatch"
DISPATCH_ROLE = "supplier_rfq_dispatch"
DISPATCH_REVIEW_SOURCE = "supplier_rfq_dispatch_review"
DISPATCH_REVIEW_ROLE = "supplier_rfq_dispatch_attestation"
DISPATCH_REVIEW_RELATIONSHIP = "supplier_rfq_dispatch_review"
SUPPORTED_SUPPLIER_PLATFORMS = frozenset({"1688", "alibaba", "manual"})
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


def _required_text(value: Any, field: str, *, max_length: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"Supplier RFQ dispatch requires {field}")
    if len(normalized) > max_length:
        raise ValueError(
            f"Supplier RFQ dispatch {field} exceeds {max_length} characters"
        )
    return normalized


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"Supplier RFQ dispatch {field} must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(
            f"Supplier RFQ dispatch {field} must include a timezone"
        )
    return parsed.astimezone(UTC)


def _canonical_hash(value: dict[str, Any]) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(content).hexdigest()


def _supplier_locator(value: str, platform: str) -> str:
    locator = _required_text(value, "supplier_locator", max_length=1000)
    if platform == "manual":
        return locator
    parsed = urlparse(locator)
    hostname = (parsed.hostname or "").lower()
    expected_domain = "1688.com" if platform == "1688" else "alibaba.com"
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or (
            hostname != expected_domain
            and not hostname.endswith(f".{expected_domain}")
        )
    ):
        raise ValueError(
            f"Supplier RFQ dispatch {platform} locator must use {expected_domain}"
        )
    return locator


class SupplierRfqDispatchWorkspace:
    """Govern proof that one frozen RFQ was manually sent to one supplier."""

    def __init__(
        self,
        *,
        rfq_packages,
        evidence,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.rfq_packages = rfq_packages
        self.evidence = evidence
        self.clock = clock or (lambda: datetime.now(UTC))

    def capture(
        self,
        *,
        rfq_package_evidence_id: str,
        supplier_ref: str,
        supplier_platform: str,
        supplier_locator: str,
        conversation_ref: str,
        sent_at: str,
        sent_message_text: str,
        idempotency_key: str,
        content: bytes,
        filename: str,
        content_type: str,
        confirmed: bool,
        created_by: str,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError(
                "Supplier RFQ dispatch capture requires explicit human confirmation"
            )
        if not content:
            raise ValueError("Supplier RFQ dispatch proof cannot be empty")
        actor = _required_text(created_by, "created_by", max_length=160)
        supplier = _required_text(
            supplier_ref,
            "supplier_ref",
            max_length=240,
        )
        platform = _required_text(
            supplier_platform,
            "supplier_platform",
            max_length=40,
        ).lower()
        if platform not in SUPPORTED_SUPPLIER_PLATFORMS:
            raise ValueError("Unsupported supplier RFQ dispatch platform")
        locator = _supplier_locator(supplier_locator, platform)
        conversation = _required_text(
            conversation_ref,
            "conversation_ref",
            max_length=500,
        )
        key = _required_text(
            idempotency_key,
            "idempotency_key",
            max_length=160,
        )
        if IDEMPOTENCY_PATTERN.fullmatch(key) is None:
            raise ValueError(
                "Supplier RFQ dispatch idempotency key contains unsupported characters"
            )
        sent_message = _required_text(
            sent_message_text,
            "sent_message_text",
            max_length=30_000,
        )

        rfq = self.rfq_packages.get(rfq_package_evidence_id)
        rfq_record = rfq["evidence"]
        package = rfq["package"]
        frozen_message = package["message_text"]
        frozen_message_sha256 = hashlib.sha256(
            frozen_message.encode()
        ).hexdigest()
        sent_message_sha256 = hashlib.sha256(sent_message.encode()).hexdigest()
        if not hmac.compare_digest(
            frozen_message_sha256,
            sent_message_sha256,
        ):
            raise ValueError(
                "Supplier RFQ dispatch message differs from the frozen RFQ"
            )

        now = self.clock()
        if now.tzinfo is None:
            raise ValueError(
                "Supplier RFQ dispatch clock must include a timezone"
            )
        now = now.astimezone(UTC)
        sent = _timestamp(sent_at, "sent_at")
        rfq_created = _timestamp(rfq_record.effective_at, "RFQ effective_at")
        due = _timestamp(
            package["buyer_requirement"]["response_due_at"],
            "RFQ response_due_at",
        )
        if sent < rfq_created:
            raise ValueError(
                "Supplier RFQ dispatch cannot predate the frozen RFQ"
            )
        if sent > now:
            raise ValueError(
                "Supplier RFQ dispatch sent_at cannot be in the future"
            )
        if sent > due:
            raise ValueError(
                "Supplier RFQ dispatch cannot occur after the RFQ response deadline"
            )

        supplier_identity_hash = hashlib.sha256(
            f"{platform}|{supplier.casefold()}".encode()
        ).hexdigest()
        proof_sha256 = hashlib.sha256(content).hexdigest()
        dispatch = {
            "contract_version": DISPATCH_CONTRACT_VERSION,
            "rfq": {
                "evidence_id": rfq_record.id,
                "evidence_sha256": rfq_record.sha256,
                "package_hash": package["package_hash"],
                "product_id": package["product"]["id"],
                "product_sku": package["product"]["sku"],
                "offer_id": package["listing"]["offer_id"],
            },
            "supplier": {
                "supplier_ref": supplier,
                "supplier_platform": platform,
                "supplier_locator": locator,
                "supplier_identity_hash": supplier_identity_hash,
            },
            "conversation_ref": conversation,
            "sent_at": sent.isoformat(),
            "sent_message_sha256": sent_message_sha256,
            "proof": {
                "sha256": proof_sha256,
                "filename": _required_text(
                    filename,
                    "filename",
                    max_length=500,
                ),
                "content_type": _required_text(
                    content_type,
                    "content_type",
                    max_length=200,
                ),
            },
            "authority": {
                "status": "pending",
                "delivery_confirmed": False,
                "supplier_replied": False,
                "counts_as_supplier_quote": False,
                "automatic_supplier_contact": False,
                "automatic_procurement": False,
                "automatic_payment": False,
                "automatic_listing": False,
                "automatic_marketplace_write": False,
            },
        }
        dispatch_hash = _canonical_hash(dispatch)
        source_ref = (
            f"supplier-rfq-dispatch://{rfq_record.id}/"
            f"{supplier_identity_hash[:24]}/{key}"
        )
        existing = self.evidence.find_by_source_ref(
            source=DISPATCH_SOURCE,
            source_ref=source_ref,
        )
        if existing is not None:
            return self._replay(
                existing,
                dispatch_hash=dispatch_hash,
                proof_sha256=proof_sha256,
                rfq_record=rfq_record,
                product_id=package["product"]["id"],
                created_by=actor,
            )

        record = self.evidence.capture(
            content=content,
            filename=dispatch["proof"]["filename"],
            content_type=dispatch["proof"]["content_type"],
            source=DISPATCH_SOURCE,
            source_ref=source_ref,
            grade=EvidenceGrade.B,
            effective_at=sent.isoformat(),
            effective_until=None,
            created_by=actor,
            metadata={
                "evidence_role": DISPATCH_ROLE,
                "contract_version": DISPATCH_CONTRACT_VERSION,
                "dispatch": dispatch,
                "dispatch_hash": dispatch_hash,
                "retention_class": "operational",
                "legal_hold": False,
                "delivery_confirmed": False,
                "supplier_replied": False,
                "counts_as_supplier_quote": False,
                "automatic_supplier_contact": False,
                "automatic_procurement": False,
                "automatic_payment": False,
                "automatic_listing": False,
                "automatic_marketplace_write": False,
            },
        )
        if (
            record.metadata.get("dispatch_hash") != dispatch_hash
            or record.sha256 != proof_sha256
        ):
            raise ValueError(
                "Supplier RFQ dispatch idempotency conflict; "
                "changed proof requires a new key"
            )
        self._link(
            record=record,
            rfq_record=rfq_record,
            product_id=package["product"]["id"],
            created_by=actor,
        )
        return {**self.status(record.id), "idempotent": False}

    def review(
        self,
        *,
        evidence_id: str,
        accepted: bool,
        authentic_platform_proof: bool,
        supplier_identity_matches: bool,
        frozen_message_matches: bool,
        timestamp_and_conversation_match: bool,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        rationale_value = _required_text(
            rationale,
            "review rationale",
            max_length=2000,
        )
        original_result = self.get(evidence_id)
        original = original_result["evidence"]
        dispatch = original_result["dispatch"]
        reviewer = _required_text(
            reviewed_by,
            "reviewed_by",
            max_length=160,
        )
        if original.created_by == reviewer:
            raise ValueError(
                "Supplier RFQ dispatch uploader cannot review their own proof"
            )
        checks = {
            "authentic_platform_proof": authentic_platform_proof,
            "supplier_identity_matches": supplier_identity_matches,
            "frozen_message_matches": frozen_message_matches,
            "timestamp_and_conversation_match": (
                timestamp_and_conversation_match
            ),
        }
        if accepted and not all(checks.values()):
            raise ValueError(
                "Accepted supplier RFQ dispatch review requires all checks to pass"
            )
        payload = {
            "decision": "accepted" if accepted else "rejected",
            "evidence_id": original.id,
            "evidence_sha256": original.sha256,
            "dispatch_hash": original.metadata["dispatch_hash"],
            "rfq_package_evidence_id": dispatch["rfq"]["evidence_id"],
            "product_id": dispatch["rfq"]["product_id"],
            "supplier_ref": dispatch["supplier"]["supplier_ref"],
            "submitted_by": original.created_by,
            "reviewed_by": reviewer,
            "rationale": rationale_value,
            "checks": checks,
        }
        for prior in self._reviews(original):
            if prior.created_by != reviewer:
                continue
            if all(
                prior.metadata.get(key) == value
                for key, value in payload.items()
            ):
                return {
                    **self.status(original.id),
                    "review": prior,
                    "idempotent": True,
                }
            raise ValueError(
                "Supplier RFQ dispatch review is immutable and cannot be overwritten"
            )

        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        reviewed_at = self.clock()
        if reviewed_at.tzinfo is None:
            raise ValueError(
                "Supplier RFQ dispatch clock must include a timezone"
            )
        review = self.evidence.capture(
            content=content,
            filename=f"{original.id}-supplier-rfq-dispatch-review.json",
            content_type="application/json",
            source=DISPATCH_REVIEW_SOURCE,
            source_ref=(
                f"supplier-rfq-dispatch://{original.id}/authority/{reviewer}"
            ),
            grade=EvidenceGrade.A,
            effective_at=reviewed_at.astimezone(UTC).isoformat(),
            effective_until=None,
            created_by=reviewer,
            metadata={
                "evidence_role": DISPATCH_REVIEW_ROLE,
                **payload,
            },
        )
        lineage = self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=original.id,
            relationship=DISPATCH_REVIEW_RELATIONSHIP,
            created_by=reviewer,
        )
        return {
            **self.status(original.id),
            "review": review,
            "lineage": lineage,
            "idempotent": False,
        }

    def get(self, evidence_id: str) -> dict[str, Any]:
        self.evidence.require_valid([evidence_id])
        record = self.evidence.get(evidence_id)
        dispatch = self._require_source(record)
        return {
            "evidence": record,
            "dispatch": dispatch,
        }

    def status(self, evidence_id: str) -> dict[str, Any]:
        result = self.get(evidence_id)
        original = result["evidence"]
        reviews = self._reviews(original)
        decisions = {
            review.metadata["decision"]
            for review in reviews
        }
        status = (
            "rejected"
            if "rejected" in decisions
            else "accepted"
            if "accepted" in decisions
            else "pending"
        )
        return {
            **result,
            "status": status,
            "review_ids": [review.id for review in reviews],
            "review_count": len(reviews),
            "delivery_confirmed": False,
            "supplier_replied": False,
            "counts_as_supplier_quote": False,
            "automatic_supplier_contact": False,
            "automatic_procurement": False,
            "automatic_payment": False,
            "automatic_listing": False,
            "automatic_marketplace_write": False,
        }

    def list(
        self,
        *,
        product_id: str | None = None,
        rfq_package_evidence_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise ValueError(
                "Supplier RFQ dispatch list limit must be 1 to 500"
            )
        records = [
            record
            for record in self.evidence.list_by_source(
                DISPATCH_SOURCE,
                limit=2000
                if product_id or rfq_package_evidence_id
                else limit,
            )
            if record.metadata.get("evidence_role") == DISPATCH_ROLE
            and (
                product_id is None
                or record.metadata.get("dispatch", {})
                .get("rfq", {})
                .get("product_id")
                == product_id
            )
            and (
                rfq_package_evidence_id is None
                or record.metadata.get("dispatch", {})
                .get("rfq", {})
                .get("evidence_id")
                == rfq_package_evidence_id
            )
        ][:limit]
        return [self.status(record.id) for record in records]

    def require_for_response(
        self,
        evidence_id: str,
        *,
        product_id: str,
        supplier_ref: str,
        supplier_platform: str,
        rfq_package_evidence_id: str | None = None,
    ) -> EvidenceRecord:
        state = self.status(evidence_id)
        if state["status"] != "accepted":
            raise ValueError(
                "Supplier response requires an independently accepted "
                "RFQ dispatch proof"
            )
        dispatch = state["dispatch"]
        rfq = self.rfq_packages.get(dispatch["rfq"]["evidence_id"])
        if (
            rfq["evidence"].sha256
            != dispatch["rfq"]["evidence_sha256"]
            or rfq["package"]["package_hash"]
            != dispatch["rfq"]["package_hash"]
            or rfq["package"]["product"]["id"]
            != dispatch["rfq"]["product_id"]
        ):
            raise ValueError(
                "Supplier RFQ dispatch no longer matches its frozen RFQ"
            )
        if dispatch["rfq"]["product_id"] != product_id:
            raise ValueError(
                "Supplier RFQ dispatch belongs to a different product"
            )
        if (
            dispatch["supplier"]["supplier_ref"].casefold()
            != supplier_ref.strip().casefold()
        ):
            raise ValueError(
                "Supplier response identity differs from the RFQ dispatch"
            )
        if (
            dispatch["supplier"]["supplier_platform"]
            != supplier_platform.strip().lower()
        ):
            raise ValueError(
                "Supplier response platform differs from the RFQ dispatch"
            )
        if (
            rfq_package_evidence_id is not None
            and dispatch["rfq"]["evidence_id"]
            != rfq_package_evidence_id
        ):
            raise ValueError(
                "Supplier response RFQ differs from the dispatch proof"
            )
        return state["evidence"]

    def _replay(
        self,
        existing: EvidenceRecord,
        *,
        dispatch_hash: str,
        proof_sha256: str,
        rfq_record: EvidenceRecord,
        product_id: str,
        created_by: str,
    ) -> dict[str, Any]:
        state = self.status(existing.id)
        if (
            existing.metadata.get("dispatch_hash") != dispatch_hash
            or existing.sha256 != proof_sha256
        ):
            raise ValueError(
                "Supplier RFQ dispatch idempotency conflict; "
                "changed proof requires a new key"
            )
        self._link(
            record=existing,
            rfq_record=rfq_record,
            product_id=product_id,
            created_by=created_by,
        )
        return {**state, "idempotent": True}

    @staticmethod
    def _require_source(record: EvidenceRecord) -> dict[str, Any]:
        metadata = record.metadata
        dispatch = metadata.get("dispatch")
        if not isinstance(dispatch, dict):
            raise ValueError(
                "Evidence is not a governed supplier RFQ dispatch proof"
            )
        authority = dispatch.get("authority")
        proof = dispatch.get("proof")
        rfq = dispatch.get("rfq")
        supplier = dispatch.get("supplier")
        if (
            record.source != DISPATCH_SOURCE
            or record.grade != EvidenceGrade.B
            or metadata.get("evidence_role") != DISPATCH_ROLE
            or metadata.get("contract_version")
            != DISPATCH_CONTRACT_VERSION
            or dispatch.get("contract_version")
            != DISPATCH_CONTRACT_VERSION
            or not isinstance(authority, dict)
            or not isinstance(proof, dict)
            or not isinstance(rfq, dict)
            or not isinstance(supplier, dict)
            or proof.get("sha256") != record.sha256
            or metadata.get("dispatch_hash") != _canonical_hash(dispatch)
            or authority.get("status") != "pending"
            or any(
                authority.get(field) is not False
                for field in (
                    "delivery_confirmed",
                    "supplier_replied",
                    "counts_as_supplier_quote",
                    "automatic_supplier_contact",
                    "automatic_procurement",
                    "automatic_payment",
                    "automatic_listing",
                    "automatic_marketplace_write",
                )
            )
        ):
            raise ValueError(
                "Evidence is not a governed supplier RFQ dispatch proof"
            )
        return dispatch

    def _reviews(self, original: EvidenceRecord) -> list[EvidenceRecord]:
        review_ids = self.evidence.target_evidence_ids(
            target_type="evidence",
            target_id=original.id,
            relationship=DISPATCH_REVIEW_RELATIONSHIP,
        )
        reviews: list[EvidenceRecord] = []
        expected_checks = {
            "authentic_platform_proof",
            "supplier_identity_matches",
            "frozen_message_matches",
            "timestamp_and_conversation_match",
        }
        dispatch = original.metadata["dispatch"]
        for review_id in review_ids:
            try:
                self.evidence.require_valid([review_id])
                review = self.evidence.get(review_id)
            except (KeyError, RuntimeError, ValueError):
                continue
            metadata = review.metadata
            checks = metadata.get("checks")
            if (
                review.source == DISPATCH_REVIEW_SOURCE
                and review.grade == EvidenceGrade.A
                and metadata.get("evidence_role")
                == DISPATCH_REVIEW_ROLE
                and metadata.get("evidence_id") == original.id
                and metadata.get("evidence_sha256") == original.sha256
                and metadata.get("dispatch_hash")
                == original.metadata["dispatch_hash"]
                and metadata.get("rfq_package_evidence_id")
                == dispatch["rfq"]["evidence_id"]
                and metadata.get("product_id")
                == dispatch["rfq"]["product_id"]
                and metadata.get("supplier_ref")
                == dispatch["supplier"]["supplier_ref"]
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
                    or all(checks.values())
                )
            ):
                reviews.append(review)
        return reviews

    def _link(
        self,
        *,
        record: EvidenceRecord,
        rfq_record: EvidenceRecord,
        product_id: str,
        created_by: str,
    ) -> None:
        self.evidence.link(
            evidence_id=rfq_record.id,
            target_type="evidence",
            target_id=record.id,
            relationship="rfq_dispatch_context_for",
            created_by=created_by,
        )
        self.evidence.link(
            evidence_id=record.id,
            target_type="product",
            target_id=product_id,
            relationship="supplier_outreach_for",
            created_by=created_by,
        )
