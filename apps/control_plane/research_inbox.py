from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlparse

from .evidence import (
    RESEARCH_CAPTURE_CONTRACT_ID,
    RESEARCH_SIGNAL_EVIDENCE_ROLE,
    EvidenceGrade,
    EvidenceService,
    parse_timestamp,
)


class ResearchInboxService:
    """Append-only intake for external market signals; never a business fact source."""

    EVIDENCE_ROLE = RESEARCH_SIGNAL_EVIDENCE_ROLE
    CAPTURE_CONTRACT_ID = RESEARCH_CAPTURE_CONTRACT_ID
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
    SCOPE_FIELDS = (
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "scope_grant_authority_sha256",
    )
    METADATA_FIELDS = frozenset(
        {
            "evidence_role",
            "provider",
            "provider_record_id",
            "source_url",
            "captured_at",
            "raw_fields",
            "license_status",
            "review_status",
            "declared_grade",
            "promotion_status",
            "research_capture_contract_id",
            "research_capture_request_sha256",
            "research_scope_binding_sha256",
            *SCOPE_FIELDS,
        }
    )
    PUBLIC_METADATA_FIELDS = (
        "evidence_role",
        "provider",
        "provider_record_id",
        "source_url",
        "captured_at",
        "raw_fields",
        "license_status",
        "review_status",
        "declared_grade",
        "promotion_status",
    )
    INTERNAL_METADATA_FIELDS = METADATA_FIELDS.difference(PUBLIC_METADATA_FIELDS)
    PUBLIC_EVIDENCE_FIELDS = (
        "id",
        "sha256",
        "byte_size",
        "filename",
        "content_type",
        "source",
        "source_ref",
        "grade",
        "effective_at",
        "effective_until",
        "recorded_at",
        "created_by",
    )

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
        scope: Mapping[str, str],
        authority_subject_actor_id: str,
        authority_guard: Callable[[], Mapping[str, str] | None],
    ) -> dict[str, Any]:
        filename = self._required(filename, "Research filename", 500)
        content_type = content_type.strip() or "application/octet-stream"
        if len(content_type) > 255:
            raise ValueError("Research content type exceeds 255 characters")
        provider = self._required(provider, "Research provider", 120)
        provider_record_id = self._required(provider_record_id, "Provider record ID", 500)
        source_url = self._source_url(source_url)
        observed_at = parse_timestamp(observed_at, "observed_at").isoformat()
        license_status = license_status.strip().lower()
        if license_status not in self.LICENSE_STATES:
            raise ValueError("license_status must be verified, requires_review, or restricted")
        raw_fields = self._raw_fields(raw_fields)
        candidate_refs = self._candidate_refs(candidate_refs)
        exact_scope = self._scope(scope)
        scope_binding_sha256 = self._scope_binding_sha256(exact_scope)
        governed_source_ref = self._governed_source_ref(
            provider_record_id=provider_record_id,
            exact_scope=exact_scope,
        )
        request_sha256 = self._capture_request_sha256(
            content_sha256=hashlib.sha256(content).hexdigest(),
            filename=filename,
            content_type=content_type,
            provider=provider,
            provider_record_id=provider_record_id,
            source_url=source_url,
            observed_at=observed_at,
            declared_grade=declared_grade.value,
            license_status=license_status,
            raw_fields=raw_fields,
            exact_scope=exact_scope,
        )
        captured_at = datetime.now(UTC).isoformat()
        metadata = {
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
            "research_capture_contract_id": self.CAPTURE_CONTRACT_ID,
            "research_capture_request_sha256": request_sha256,
            "research_scope_binding_sha256": scope_binding_sha256,
            **exact_scope,
        }
        with self.evidence.transaction() as session:
            self.evidence.lock_scope_authority_in_session(
                tenant_ref=exact_scope["tenant_ref"],
                store_ref=exact_scope["store_ref"],
                subject_actor_id=authority_subject_actor_id,
                session=session,
            )
            self._require_current_authority(authority_guard, exact_scope)
            record = self.evidence.find_by_source_ref_in_session(
                source=provider,
                source_ref=governed_source_ref,
                session=session,
            )
            if record is None:
                record = self.evidence.capture_research_signal_evidence(
                    content=content,
                    filename=filename,
                    content_type=content_type,
                    source=provider,
                    source_ref=governed_source_ref,
                    grade=declared_grade,
                    effective_at=observed_at,
                    recorded_at=captured_at,
                    created_by=created_by,
                    metadata=metadata,
                    session=session,
                )
            self._require_capture_binding(
                record=record,
                provider=provider,
                provider_record_id=provider_record_id,
                exact_scope=exact_scope,
                expected_request_sha256=request_sha256,
            )
            existing_candidates = self.evidence.linked_target_ids_in_session(
                evidence_id=record.id,
                target_type=self.TARGET_TYPE,
                relationship=self.RELATIONSHIP,
                session=session,
            )
            if len(set(existing_candidates).union(candidate_refs)) > 20:
                raise ValueError(
                    "A research signal may link to at most 20 candidates"
                )
            for candidate_ref in candidate_refs:
                self.evidence.link_in_session(
                    evidence_id=record.id,
                    target_type=self.TARGET_TYPE,
                    target_id=candidate_ref,
                    relationship=self.RELATIONSHIP,
                    created_by=created_by,
                    session=session,
                )
            self._require_current_authority(authority_guard, exact_scope)
        return self._view(record, self._linked_candidates(record.id))

    def list(
        self,
        *,
        scope: Mapping[str, str],
        candidate_ref: str | None = None,
        limit: int = 100,
        cursor_recorded_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 100:
            raise ValueError("Research signal limit must be between 1 and 100")
        exact_scope = self._scope(scope)
        lineage_target: dict[str, str] | None = None
        if candidate_ref is not None:
            normalized = self._candidate_refs([candidate_ref])
            if not normalized:
                raise ValueError("Candidate reference is required")
            lineage_target = {
                "target_type": self.TARGET_TYPE,
                "target_id": normalized[0],
                "relationship": self.RELATIONSHIP,
            }
        records = self.evidence.list_for_governance(
            closed_loop_scopes=(),
            limit=limit,
            cursor_recorded_at=cursor_recorded_at,
            cursor_id=cursor_id,
            evidence_role=self.EVIDENCE_ROLE,
            exact_scope=exact_scope,
            lineage_target=lineage_target,
            metadata_equals={
                "research_capture_contract_id": self.CAPTURE_CONTRACT_ID,
            },
        )
        return [self._view(record, self._linked_candidates(record.id)) for record in records]

    def _require_capture_binding(
        self,
        *,
        record,
        provider: str,
        provider_record_id: str,
        exact_scope: Mapping[str, str],
        expected_request_sha256: str,
    ) -> None:
        expected_source_ref = self._governed_source_ref(
            provider_record_id=provider_record_id,
            exact_scope=exact_scope,
        )
        expected_metadata = {
            "evidence_role": self.EVIDENCE_ROLE,
            "provider": provider,
            "provider_record_id": provider_record_id,
            "review_status": "pending_authority_review",
            "promotion_status": "auxiliary_only",
            "research_capture_contract_id": self.CAPTURE_CONTRACT_ID,
            "research_capture_request_sha256": expected_request_sha256,
            "research_scope_binding_sha256": self._scope_binding_sha256(
                exact_scope
            ),
            **exact_scope,
        }
        try:
            stored_scope = self._scope(
                {field: record.metadata.get(field) for field in self.SCOPE_FIELDS}
            )
            stored_raw_fields = record.metadata.get("raw_fields")
            if not isinstance(stored_raw_fields, dict):
                raise ValueError("Research raw fields drifted")
            normalized_raw_fields = self._raw_fields(stored_raw_fields)
            if normalized_raw_fields != stored_raw_fields:
                raise ValueError("Research raw fields drifted")
            captured_at_raw = record.metadata.get("captured_at")
            recorded_at_raw = record.recorded_at
            if not isinstance(captured_at_raw, str) or not isinstance(
                recorded_at_raw, str
            ):
                raise ValueError("Research capture time drifted")
            captured_at = parse_timestamp(captured_at_raw, "captured_at")
            recorded_at = parse_timestamp(recorded_at_raw, "recorded_at")
            if (
                captured_at.isoformat() != captured_at_raw
                or recorded_at.isoformat() != recorded_at_raw
                or captured_at != recorded_at
            ):
                raise ValueError("Research capture time drifted")
            stored_request_sha256 = self._capture_request_sha256(
                content_sha256=record.sha256,
                filename=record.filename,
                content_type=record.content_type,
                provider=record.source,
                provider_record_id=str(
                    record.metadata.get("provider_record_id") or ""
                ),
                source_url=str(record.metadata.get("source_url") or ""),
                observed_at=record.effective_at,
                declared_grade=record.grade.value,
                license_status=str(record.metadata.get("license_status") or ""),
                raw_fields=normalized_raw_fields,
                exact_scope=stored_scope,
            )
        except (TypeError, ValueError):
            raise ValueError(
                "Research Evidence immutable request binding drifted"
            ) from None
        if (
            record.source != provider
            or record.source_ref != expected_source_ref
            or record.effective_until is not None
            or record.metadata.get("declared_grade") != record.grade.value
            or stored_request_sha256 != expected_request_sha256
            or any(
                record.metadata.get(key) != value
                for key, value in expected_metadata.items()
            )
        ):
            raise ValueError("Research Evidence immutable scope binding drifted")

    def _require_current_authority(
        self,
        authority_guard: Callable[[], Mapping[str, str] | None],
        exact_scope: Mapping[str, str],
    ) -> None:
        current = authority_guard()
        if current is None:
            raise ValueError("Research Evidence scope authority is no longer current")
        try:
            normalized = self._scope(current)
        except ValueError:
            raise ValueError(
                "Research Evidence scope authority is no longer current"
            ) from None
        if normalized != dict(exact_scope):
            raise ValueError("Research Evidence scope authority is no longer current")

    def _require_listable_record(self, record) -> None:
        metadata = record.metadata
        if not isinstance(metadata, dict) or set(metadata) != self.METADATA_FIELDS:
            raise ValueError("Research Evidence metadata contract drifted")
        string_fields = self.METADATA_FIELDS - {"raw_fields"}
        if any(not isinstance(metadata[field], str) for field in string_fields):
            raise ValueError("Research Evidence metadata contract drifted")
        try:
            captured_at = parse_timestamp(metadata["captured_at"], "captured_at")
            if captured_at.isoformat() != metadata["captured_at"]:
                raise ValueError("Research captured_at is not canonical")
            exact_scope = self._scope(
                {field: metadata[field] for field in self.SCOPE_FIELDS}
            )
            self._require_capture_binding(
                record=record,
                provider=metadata["provider"],
                provider_record_id=metadata["provider_record_id"],
                exact_scope=exact_scope,
                expected_request_sha256=metadata[
                    "research_capture_request_sha256"
                ],
            )
        except (TypeError, ValueError):
            raise ValueError("Research Evidence metadata contract drifted") from None

    @classmethod
    def _capture_request_sha256(
        cls,
        *,
        content_sha256: str,
        filename: str,
        content_type: str,
        provider: str,
        provider_record_id: str,
        source_url: str,
        observed_at: str,
        declared_grade: str,
        license_status: str,
        raw_fields: Mapping[str, Any],
        exact_scope: Mapping[str, str],
    ) -> str:
        payload = {
            "contract_id": cls.CAPTURE_CONTRACT_ID,
            "content_sha256": content_sha256,
            "filename": filename,
            "content_type": content_type,
            "provider": provider,
            "provider_record_id": provider_record_id,
            "source_url": source_url,
            "observed_at": observed_at,
            "declared_grade": declared_grade,
            "license_status": license_status,
            "raw_fields": dict(raw_fields),
            "scope": dict(exact_scope),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def _scope(cls, value: Mapping[str, str]) -> dict[str, str]:
        if not isinstance(value, Mapping) or set(value) != set(cls.SCOPE_FIELDS):
            raise ValueError("Research Evidence requires an exact four-field scope")
        if any(not isinstance(value[field], str) for field in cls.SCOPE_FIELDS):
            raise ValueError("Research Evidence exact scope is invalid")
        result = {field: value[field].strip() for field in cls.SCOPE_FIELDS}
        if any(not item for item in result.values()) or not re.fullmatch(
            r"[0-9a-f]{64}",
            result["scope_grant_authority_sha256"],
        ):
            raise ValueError("Research Evidence exact scope is invalid")
        return result

    @staticmethod
    def _scope_binding_sha256(exact_scope: Mapping[str, str]) -> str:
        canonical = json.dumps(
            dict(exact_scope),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def _governed_source_ref(
        cls,
        *,
        provider_record_id: str,
        exact_scope: Mapping[str, str],
    ) -> str:
        canonical = json.dumps(
            {
                "provider_record_id": provider_record_id,
                "scope": dict(exact_scope),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"research-signal://{hashlib.sha256(canonical).hexdigest()}"

    def _linked_candidates(self, evidence_id: str) -> list[str]:
        return sorted(
            edge.to_id
            for edge in self.evidence.lineage(evidence_id)
            if edge.from_id == evidence_id
            and edge.to_type == self.TARGET_TYPE
            and edge.relationship == self.RELATIONSHIP
        )

    def _view(self, record, candidate_refs: list[str]) -> dict[str, Any]:
        self._require_listable_record(record)
        verification = self.evidence.verify(record.id)
        public_metadata = {
            field: record.metadata[field] for field in self.PUBLIC_METADATA_FIELDS
        }
        public_evidence = {
            field: getattr(record, field) for field in self.PUBLIC_EVIDENCE_FIELDS
        }
        # The stored source_ref is scope-bound; preserve the prior public provider-record contract.
        public_evidence["source_ref"] = public_metadata["provider_record_id"]
        public_evidence["metadata"] = public_metadata
        return {
            "evidence": public_evidence,
            "candidate_refs": sorted(candidate_refs),
            "integrity_valid": verification.valid,
            "decision_use": "auxiliary_only_pending_independent_authority_review",
            "automatic_listing": False,
            "automatic_procurement": False,
        }

    @classmethod
    def _candidate_refs(cls, values: list[str]) -> list[str]:
        if any(not isinstance(value, str) for value in values):
            raise ValueError("Candidate reference must be a string")
        result = sorted({value.strip() for value in values if value.strip()})
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
            if (
                not key
                or len(key) > 120
                or normalized in cls.SENSITIVE_KEY_TOKENS
                or normalized in cls.INTERNAL_METADATA_FIELDS
                or tokens & cls.SENSITIVE_KEY_TOKENS
            ):
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
