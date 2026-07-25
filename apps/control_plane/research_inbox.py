from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlparse

from .evidence import EvidenceGrade, EvidenceService


class ResearchInboxService:
    """Append-only intake for external market signals; never a business fact source."""

    EVIDENCE_ROLE = "research_signal"
    TARGET_TYPE = "candidate_research"
    RELATIONSHIP = "research_signal"
    LICENSE_STATES = {"verified", "requires_review", "restricted"}
    SENSITIVE_KEY_TOKENS = {
        "address",
        "api_key",
        "authorization",
        "client_secret",
        "cookie",
        "email",
        "password",
        "phone",
        "secret",
        "token",
    }
    CANDIDATE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")

    def __init__(self, *, evidence: EvidenceService) -> None:
        self.evidence = evidence

    def capture(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        provider: str,
        provider_record_id: str,
        source_url: str,
        observed_at: str,
        declared_grade: EvidenceGrade,
        license_status: str,
        raw_fields: dict[str, Any],
        candidate_refs: list[str],
        created_by: str,
    ) -> dict[str, Any]:
        provider = self._required(provider, "Research provider", 120)
        provider_record_id = self._required(provider_record_id, "Provider record ID", 500)
        source_url = self._source_url(source_url)
        license_status = license_status.strip().lower()
        if license_status not in self.LICENSE_STATES:
            raise ValueError("license_status must be verified, requires_review, or restricted")
        raw_fields = self._raw_fields(raw_fields)
        candidate_refs = self._candidate_refs(candidate_refs)
        captured_at = datetime.now(UTC).isoformat()
        digest = hashlib.sha256(content).hexdigest()
        record = self.evidence.find_by_source_hash(
            source=provider,
            source_ref=provider_record_id,
            sha256=digest,
        )
        duplicate = record is not None
        if record is None:
            record = self.evidence.capture(
                content=content,
                filename=filename,
                content_type=content_type,
                source=provider,
                source_ref=provider_record_id,
                grade=declared_grade,
                effective_at=observed_at,
                effective_until=None,
                created_by=created_by,
                metadata={
                    "evidence_role": self.EVIDENCE_ROLE,
                    "provider": provider,
                    "provider_record_id": provider_record_id,
                    "source_url": source_url,
                    "captured_at": captured_at,
                    "raw_fields": raw_fields,
                    "license_status": license_status,
                    "review_status": "pending_authority_review",
                    "declared_grade": declared_grade.value,
                    "promotion_status": "auxiliary_only",
                },
            )
        for candidate_ref in candidate_refs:
            self.evidence.link(
                evidence_id=record.id,
                target_type=self.TARGET_TYPE,
                target_id=candidate_ref,
                relationship=self.RELATIONSHIP,
                created_by=created_by,
            )
        return self._view(record, self._linked_candidates(record.id), duplicate=duplicate)

    def list(self, *, candidate_ref: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 100:
            raise ValueError("Research signal limit must be between 1 and 100")
        linked_ids: set[str] | None = None
        if candidate_ref is not None:
            normalized = self._candidate_refs([candidate_ref])
            linked_ids = set(
                self.evidence.target_evidence_ids(
                    target_type=self.TARGET_TYPE,
                    target_id=normalized[0],
                    relationship=self.RELATIONSHIP,
                )
            )
        # ponytail: scan the current 500-record Evidence window; add an indexed projection only when volume proves it.
        records = [
            record
            for record in self.evidence.list(500)
            if record.metadata.get("evidence_role") == self.EVIDENCE_ROLE
            and (linked_ids is None or record.id in linked_ids)
        ][:limit]
        return [self._view(record, self._linked_candidates(record.id)) for record in records]

    def _linked_candidates(self, evidence_id: str) -> list[str]:
        return sorted(
            edge.to_id
            for edge in self.evidence.lineage(evidence_id)
            if edge.from_id == evidence_id
            and edge.to_type == self.TARGET_TYPE
            and edge.relationship == self.RELATIONSHIP
        )

    def _view(self, record, candidate_refs: list[str], *, duplicate: bool = False) -> dict[str, Any]:
        verification = self.evidence.verify(record.id)
        return {
            "evidence": asdict(record),
            "candidate_refs": sorted(candidate_refs),
            "integrity_valid": verification.valid,
            "duplicate": duplicate,
            "decision_use": "auxiliary_only_pending_independent_authority_review",
            "automatic_listing": False,
            "automatic_procurement": False,
        }

    @classmethod
    def _candidate_refs(cls, values: list[str]) -> list[str]:
        result = sorted({str(value).strip() for value in values if str(value).strip()})
        if len(result) > 20:
            raise ValueError("A research signal may link to at most 20 candidates")
        if any(not cls.CANDIDATE_REF.fullmatch(value) for value in result):
            raise ValueError("Candidate reference contains unsupported characters or exceeds 120 characters")
        return result

    @classmethod
    def _raw_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("raw_fields must be a JSON object")
        if len(value) > 50:
            raise ValueError("raw_fields may contain at most 50 fields")
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key).strip()
            normalized = key.casefold().replace("-", "_").replace(".", "_")
            tokens = set(normalized.split("_"))
            if not key or len(key) > 120 or normalized in cls.SENSITIVE_KEY_TOKENS or tokens & cls.SENSITIVE_KEY_TOKENS:
                raise ValueError(f"Sensitive or invalid raw field is forbidden: {raw_key}")
            if not isinstance(item, (str, int, float, bool)) and item is not None:
                raise ValueError(f"Raw field values must be scalar JSON values: {raw_key}")
            if isinstance(item, str) and len(item) > 1000:
                raise ValueError(f"Raw field value exceeds 1000 characters: {raw_key}")
            result[key] = item
        if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) > 16_384:
            raise ValueError("raw_fields exceeds 16 KiB")
        return result

    @classmethod
    def _source_url(cls, value: str) -> str:
        value = cls._required(value, "Source URL", 2000)
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Source URL must be an http(s) URL without embedded credentials")
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
            normalized = key.casefold().replace("-", "_")
            if normalized in cls.SENSITIVE_KEY_TOKENS or set(normalized.split("_")) & cls.SENSITIVE_KEY_TOKENS:
                raise ValueError("Source URL must not contain credential query parameters")
        return value

    @staticmethod
    def _required(value: str, label: str, maximum: int) -> str:
        value = value.strip()
        if not value or len(value) > maximum:
            raise ValueError(f"{label} is required and must not exceed {maximum} characters")
        return value
