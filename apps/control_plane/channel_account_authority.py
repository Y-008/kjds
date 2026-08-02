from __future__ import annotations

import hashlib
import html
import json
import math
import re
import unicodedata
from contextlib import contextmanager
from datetime import UTC, datetime
from itertools import permutations
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import unquote

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .channel_account_runtime_identity import (
    ManagedSecretLocatorPolicy,
)
from .domain import new_id
from .evidence import (
    _RESERVED_CAPTURE_AUTHORITY,
    EvidenceGrade,
    parse_timestamp,
)
from .evidence_scope import DIRECT_CONTRACT
from .execution_plans import ExecutionPlanRow
from .limited_executor import (
    LimitedExecutionCommandRow,
    LimitedExecutionReceiptRow,
)
from .security import KillSwitchEventRow, Principal
from .sql_repository import ApprovalRow, Base

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "project" / "registries" / "channel_account_adapters.json"
)
SCOPE_REQUIRED_SQL = (
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND platform IS NOT NULL AND length(platform) > 0 "
    "AND account_ref IS NOT NULL AND length(account_ref) > 0 "
    "AND adapter_id IS NOT NULL AND length(adapter_id) > 0 "
    "AND adapter_version IS NOT NULL AND length(adapter_version) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND adapter_contract_sha256 IS NOT NULL "
    "AND length(adapter_contract_sha256) = 64 "
    "AND consent_evidence_sha256 IS NOT NULL "
    "AND length(consent_evidence_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND source_payload_sha256 IS NOT NULL "
    "AND length(source_payload_sha256) = 64 "
    "AND payload_sha256 IS NOT NULL AND length(payload_sha256) = 64 "
    "AND secret_reference_sha256 IS NOT NULL "
    "AND length(secret_reference_sha256) = 64 "
    "AND credential_fingerprint_sha256 IS NOT NULL "
    "AND length(credential_fingerprint_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
)
GOVERNED_EVENT_TYPES = (
    "'authorization_granted',"
    "'authorization_refreshed',"
    "'credential_rotated',"
    "'authorization_revoked',"
    "'external_verification_readback'"
)
GOVERNANCE_BINDING_SQL = (
    "("
    f"event_type NOT IN ({GOVERNED_EVENT_TYPES}) "
    "AND approval_id IS NULL AND command_id IS NULL "
    "AND receipt_id IS NULL AND permit_evidence_id IS NULL "
    "AND readback_evidence_id IS NULL AND kill_switch_sequence IS NULL "
    "AND kill_switch_state_id IS NULL "
    "AND kill_switch_evidence_id IS NULL "
    "AND compensation_plan_id IS NULL "
    "AND compensation_evidence_id IS NULL"
    ") OR ("
    f"event_type IN ({GOVERNED_EVENT_TYPES}) "
    "AND approval_id IS NOT NULL AND length(approval_id) > 0 "
    "AND command_id IS NOT NULL AND receipt_id IS NOT NULL "
    "AND permit_evidence_id IS NOT NULL AND readback_evidence_id IS NOT NULL "
    "AND kill_switch_sequence IS NOT NULL "
    "AND kill_switch_state_id IS NOT NULL "
    "AND kill_switch_evidence_id IS NOT NULL "
    "AND compensation_plan_id IS NOT NULL "
    "AND compensation_evidence_id IS NOT NULL"
    ")"
)


class ChannelAccountReviewDecisionRow(Base):
    """Append-only latest-decision authority for one SoD submission."""

    __tablename__ = "channel_account_review_decisions"
    __table_args__ = (
        UniqueConstraint(
            "submission_evidence_id",
            "sequence",
            name="uq_channel_account_review_decision_sequence",
        ),
        UniqueConstraint(
            "submission_evidence_id",
            "decision_sha256",
            name="uq_channel_account_review_decision_hash",
        ),
        CheckConstraint(
            "sequence > 0 AND length(decision_sha256) = 64",
            name="ck_channel_account_review_decision",
        ),
        Index(
            "ix_channel_account_review_decision_latest",
            "submission_evidence_id",
            "sequence",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    submission_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=False,
    )
    decision_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(240), nullable=False)
    decision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)


class ChannelAccountKillSwitchStateRow(Base):
    """Append-only exact-scope binding to canonical Kill Switch state."""

    __tablename__ = "channel_account_kill_switch_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_event_ref",
            name="uq_channel_account_kill_switch_source",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "action_id",
            "sequence",
            name="uq_channel_account_kill_switch_sequence",
        ),
        CheckConstraint(
            "sequence > 0 "
            "AND action_id IN ("
            "'channel_authorization_grant',"
            "'channel_authorization_refresh',"
            "'channel_credential_rotate',"
            "'channel_authorization_revoke',"
            "'channel_authorization_external_verify') "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND length(payload_sha256) = 64 "
            "AND length(evidence_sha256) = 64 "
            "AND effective_at <= scope_as_of "
            "AND scope_as_of <= recorded_at",
            name="ck_channel_account_kill_switch_authority",
        ),
        Index(
            "ix_channel_account_kill_switch_current",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "action_id",
            "effective_at",
            "sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_event_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kill_switch_sequence: Mapped[int] = mapped_column(ForeignKey("kill_switch_events.sequence"), nullable=False)
    writes_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    action_id: Mapped[str] = mapped_column(String(160), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(160), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelAccountAuthorizationEventRow(Base):
    """Append-only non-secret external account authorization observation."""

    __tablename__ = "channel_account_authorization_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_event_ref",
            name="uq_channel_account_authority_source_event",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "sequence",
            name="uq_channel_account_authority_sequence",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "command_id",
            name="uq_channel_account_authority_command",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "receipt_id",
            name="uq_channel_account_authority_receipt",
        ),
        CheckConstraint(
            SCOPE_REQUIRED_SQL,
            name="ck_channel_account_authority_scope_required",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_channel_account_authority_sequence",
        ),
        CheckConstraint(
            "authorization_source IN ('official', 'explicit_written_authorization')",
            name="ck_channel_account_authority_source",
        ),
        CheckConstraint(
            "event_type IN ("
            "'authorization_granted','authorization_refreshed',"
            "'credential_rotated','authorization_revoked',"
            "'authorization_expired','external_verification_readback',"
            "'health_observed','rate_limit_observed',"
            "'schema_drift_observed','unknown_outcome_observed') "
            "AND credential_kind IN ("
            "'api_key_ref','oauth_client_ref','service_account_ref') "
            "AND health_status IN ("
            "'healthy','degraded','unreachable','unknown') "
            "AND readback_outcome IN ("
            "'succeeded','failed','unknown','not_applicable') "
            "AND rate_limit_state IN ("
            "'available','limited','exhausted','unknown')",
            name="ck_channel_account_authority_enums",
        ),
        CheckConstraint(
            "effective_at <= verified_at "
            "AND effective_at < expires_at "
            "AND verified_at <= scope_as_of "
            "AND scope_as_of <= recorded_at "
            "AND secret_reference LIKE 'msl_%'",
            name="ck_channel_account_authority_time_locator",
        ),
        CheckConstraint(
            GOVERNANCE_BINDING_SQL,
            name="ck_channel_account_authority_governance",
        ),
        Index(
            "ix_channel_account_authority_scope_account",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "platform",
            "account_ref",
            "adapter_id",
            "effective_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_event_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    authorization_source: Mapped[str] = mapped_column(String(80), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(160), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(80), nullable=False)
    role_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    subaccount_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    credential_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    secret_reference: Mapped[str] = mapped_column(String(256), nullable=False)
    secret_reference_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    health_status: Mapped[str] = mapped_column(String(80), nullable=False)
    readback_outcome: Mapped[str] = mapped_column(String(80), nullable=False)
    rate_limit_state: Mapped[str] = mapped_column(String(80), nullable=False)
    external_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    consent_evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    adapter_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"), nullable=True)
    command_id: Mapped[str | None] = mapped_column(ForeignKey("limited_execution_commands.id"), nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(ForeignKey("limited_execution_receipts.id"), nullable=True)
    permit_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_records.id"), nullable=True)
    readback_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_records.id"), nullable=True)
    kill_switch_sequence: Mapped[int | None] = mapped_column(ForeignKey("kill_switch_events.sequence"), nullable=True)
    kill_switch_state_id: Mapped[str | None] = mapped_column(
        ForeignKey("channel_account_kill_switch_states.id"),
        nullable=True,
    )
    kill_switch_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_records.id"), nullable=True)
    compensation_plan_id: Mapped[str | None] = mapped_column(ForeignKey("governed_execution_plans.id"), nullable=True)
    compensation_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_records.id"), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelAccountAdapterRegistry:
    """Versioned allow-list for official or expressly authorized adapters."""

    REGISTRY_ID = "kjds-channel-account-adapters"

    def __init__(
        self,
        *,
        registry_path: Path | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.path = registry_path or REGISTRY_PATH
        raw = payload or json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("registry_id") != self.REGISTRY_ID:
            raise RuntimeError("Unknown channel account adapter registry")
        if not isinstance(raw.get("adapters"), list) or not raw["adapters"]:
            raise RuntimeError("Channel account adapter registry is empty")
        self.raw = raw
        self.registry_sha256 = self._hash(raw)
        self._adapters: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in raw["adapters"]:
            normalized = self._normalize(item)
            key = (
                normalized["platform"],
                normalized["adapter_id"],
                normalized["adapter_version"],
            )
            if key in self._adapters:
                raise RuntimeError("Duplicate channel account adapter contract")
            normalized["contract_sha256"] = self._hash(normalized)
            self._adapters[key] = normalized

    def resolve(
        self,
        *,
        platform: str,
        adapter_id: str,
        adapter_version: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        key = (
            str(platform).strip().lower(),
            str(adapter_id).strip(),
            str(adapter_version).strip(),
        )
        contract = self._adapters.get(key)
        if contract is None:
            raise ValueError("Channel account adapter is not registered")
        cutoff = self._aware(as_of)
        effective = parse_timestamp(
            contract["effective_from"],
            "adapter effective_from",
        )
        retired = (
            parse_timestamp(
                contract["effective_to"],
                "adapter effective_to",
            )
            if contract.get("effective_to")
            else None
        )
        if cutoff < effective or (retired is not None and cutoff > retired):
            raise ValueError("Channel account adapter is not effective at as_of")
        if contract["status"] != "production_bindable":
            raise ValueError("Channel account adapter is not production bindable")
        return dict(contract)

    def snapshot(self, *, as_of: datetime) -> dict[str, Any]:
        entries = []
        for contract in self._adapters.values():
            try:
                self.resolve(
                    platform=contract["platform"],
                    adapter_id=contract["adapter_id"],
                    adapter_version=contract["adapter_version"],
                    as_of=as_of,
                )
            except ValueError:
                continue
            entries.append(
                {
                    key: value
                    for key, value in contract.items()
                    if key
                    not in {
                        "credential_bootstrap",
                        "secret_material",
                    }
                }
            )
        payload = {
            "registry_id": self.REGISTRY_ID,
            "version": self.raw["version"],
            "registry_sha256": self.registry_sha256,
            "as_of": self._aware(as_of).isoformat(),
            "adapters": sorted(
                entries,
                key=lambda row: (
                    row["platform"],
                    row["adapter_id"],
                    row["adapter_version"],
                ),
            ),
            "plaintext_secret_allowed": False,
            "private_endpoint_allowed": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @classmethod
    def _normalize(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise RuntimeError("Adapter contract must be an object")
        normalized = {
            "platform": cls._required(value.get("platform"), "platform", 80).lower(),
            "adapter_id": cls._required(value.get("adapter_id"), "adapter_id", 160),
            "adapter_version": cls._required(
                value.get("adapter_version"),
                "adapter_version",
                80,
            ),
            "status": cls._required(value.get("status"), "status", 80),
            "effective_from": cls._required(
                value.get("effective_from"),
                "effective_from",
                80,
            ),
            "effective_to": (
                cls._required(
                    value.get("effective_to"),
                    "effective_to",
                    80,
                )
                if value.get("effective_to")
                else None
            ),
            "authorization_sources": cls._strings(
                value.get("authorization_sources"),
                "authorization_sources",
            ),
            "credential_kinds": cls._strings(
                value.get("credential_kinds"),
                "credential_kinds",
            ),
            "allowed_capabilities": cls._strings(
                value.get("allowed_capabilities"),
                "allowed_capabilities",
            ),
            "verification_ttl_hours": value.get("verification_ttl_hours"),
            "read_only": value.get("read_only"),
            "official_or_authorized_only": value.get("official_or_authorized_only"),
            "private_endpoint_allowed": value.get("private_endpoint_allowed"),
            "cookie_allowed": value.get("cookie_allowed"),
            "device_session_allowed": value.get("device_session_allowed"),
        }
        if (
            not isinstance(normalized["verification_ttl_hours"], int)
            or isinstance(normalized["verification_ttl_hours"], bool)
            or not 1 <= normalized["verification_ttl_hours"] <= 2160
            or normalized["read_only"] is not True
            or normalized["official_or_authorized_only"] is not True
            or normalized["private_endpoint_allowed"] is not False
            or normalized["cookie_allowed"] is not False
            or normalized["device_session_allowed"] is not False
        ):
            raise RuntimeError("Channel account adapter safety contract is invalid")
        if not set(normalized["authorization_sources"]).issubset({"official", "explicit_written_authorization"}):
            raise RuntimeError("Channel account adapter source is not authorized")
        if not set(normalized["credential_kinds"]).issubset(
            {
                "api_key_ref",
                "oauth_client_ref",
                "service_account_ref",
            }
        ):
            raise RuntimeError("Channel account credential kind is unsafe")
        return normalized

    @staticmethod
    def _strings(value: Any, field: str) -> list[str]:
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise RuntimeError(f"{field} must be non-empty strings")
        normalized = sorted({item.strip() for item in value})
        if len(normalized) != len(value):
            raise RuntimeError(f"{field} contains duplicates")
        return normalized

    @staticmethod
    def _required(value: Any, field: str, limit: int) -> str:
        result = str(value or "").strip()
        if not result or len(result) > limit:
            raise RuntimeError(f"{field} must be 1 to {limit} characters")
        return result

    @staticmethod
    def _aware(value: datetime | str) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

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


class ChannelAccountGovernanceEvidenceAuthority:
    """Server-owned SoD admission for high-risk authorization Evidence."""

    _review_locks_guard = Lock()
    _review_locks: dict[str, tuple[Lock, int]] = {}

    SUBMISSION_CONTRACT_ID = "kjds-channel-account-governance-submission-v1"
    REVIEW_CONTRACT_ID = "kjds-channel-account-sod-review-v1"
    PURPOSES = {
        "change_proposal": (
            "channel_account_change_proposal",
            "kjds-channel-account-change-proposal-v1",
        ),
        "consent": (
            "channel_account_authorization_consent",
            "kjds-channel-account-consent-evidence-v1",
        ),
        "lifecycle": (
            "channel_account_authorization_lifecycle",
            "kjds-channel-account-lifecycle-evidence-v1",
        ),
        "permit": (
            "channel_account_one_time_permit",
            "kjds-channel-account-one-time-permit-v1",
        ),
        "readback": (
            "channel_account_official_readback",
            "kjds-channel-account-readback-v1",
        ),
        "kill_switch": (
            "channel_account_kill_switch_release",
            "kjds-channel-account-kill-switch-evidence-v1",
        ),
        "compensation": (
            "channel_account_compensation_plan",
            "kjds-channel-account-compensation-evidence-v1",
        ),
    }
    SERVER_OWNED_FIELDS = frozenset(
        {
            "contract_id",
            "evidence_scope_contract_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "submitted_by",
            "reviewed_by",
            "review_sequence",
            "review_decision_sha256",
            "review_rationale",
            "review_rationale_sha256",
            "reviewed_submission_id",
            "reviewed_submission_sha256",
            "channel_account_review_contract_id",
            "canonical_payload_sha256",
            "event_payload_sha256",
            "kill_switch_state_payload_sha256",
        }
    )
    BOOLEAN_FIELDS = frozenset(
        {
            "revoked",
            "immutable",
            "singleuse",
            "officialorauthorized",
            "authorizationchanged",
            "writesenabled",
            "requiresfreshapproval",
            "automaticexecutionallowed",
        }
    )
    INTEGER_FIELDS = frozenset(
        {
            "sequence",
            "killswitchsequence",
        }
    )
    STRING_LIST_FIELDS = frozenset(
        {
            "allowedcapabilities",
            "capabilities",
            "requestedcapabilities",
        }
    )
    OBJECT_FIELDS = frozenset(
        {
            "authorization",
            "governance",
            "previousauthorization",
            "schema",
            "scope",
            "storeaccountbinding",
        }
    )
    OPTIONAL_STRING_FIELDS = frozenset(
        {
            "roleref",
            "subaccountref",
            "restoreauthoritysha256",
        }
    )
    DIGEST_FIELDS = frozenset(
        {
            "adaptercontractsha256",
            "authorizationhash",
            "consentevidencesha256",
            "credentialfingerprintsha256",
            "decisionhash",
            "inputsha256",
            "mutatedstatesha256",
            "outputsha256",
            "preconditionstatesha256",
            "requesthash",
            "restoreauthoritysha256",
            "resultingauthoritysha256",
            "scopegrantauthoritysha256",
            "secretreferencesha256",
        }
    )
    # Each governance purpose has its own closed schema.  Keeping these sets
    # separate is deliberate: a field valid for a readback must not become a
    # credential-smuggling channel in consent or Kill Switch Evidence.
    PURPOSE_SCHEMAS: dict[str, dict[str, frozenset[str]]] = {
        "change_proposal": {
            "semantic": frozenset(
                {
                    "platform",
                    "accountref",
                    "changekind",
                    "requestedcapabilities",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "platform",
                    "accountref",
                    "changekind",
                    "requestedcapabilities",
                }
            ),
        },
        "consent": {
            "semantic": frozenset(
                {
                    "status",
                    "revoked",
                    "immutable",
                    "authorizationsource",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "credentialkind",
                    "allowedcapabilities",
                    "roleref",
                    "subaccountref",
                    "consentowner",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "status",
                    "revoked",
                    "immutable",
                    "authorizationsource",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "credentialkind",
                    "allowedcapabilities",
                    "roleref",
                    "subaccountref",
                    "consentowner",
                    "secretreferencesha256",
                    "credentialfingerprintsha256",
                    "scope",
                    "tenantref",
                    "entityref",
                    "storeref",
                    "scopegrantauthoritysha256",
                    "asof",
                }
            ),
        },
        "lifecycle": {
            "semantic": frozenset(
                {
                    "sourceeventref",
                    "sequence",
                    "eventtype",
                    "status",
                    "authorizationsource",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "roleref",
                    "subaccountref",
                    "credentialkind",
                    "capabilities",
                    "secretreferencesha256",
                    "credentialfingerprintsha256",
                    "healthstatus",
                    "readbackoutcome",
                    "ratelimitstate",
                    "externalschemaversion",
                    "effectiveat",
                    "expiresat",
                    "verifiedat",
                    "revoked",
                    "immutable",
                    "consentevidenceid",
                    "consentevidencesha256",
                    "observationcontractid",
                    "observationschemaversion",
                    "approvalid",
                    "commandid",
                    "receiptid",
                    "permitevidenceid",
                    "readbackevidenceid",
                    "killswitchsequence",
                    "killswitchstateid",
                    "killswitchevidenceid",
                    "compensationplanid",
                    "compensationevidenceid",
                    "inputsha256",
                    "outputsha256",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "sourceeventref",
                    "sequence",
                    "eventtype",
                    "authorization",
                    "status",
                    "authorizationsource",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "roleref",
                    "subaccountref",
                    "credentialkind",
                    "capabilities",
                    "secretreferencesha256",
                    "credentialfingerprintsha256",
                    "healthstatus",
                    "readbackoutcome",
                    "ratelimitstate",
                    "externalschemaversion",
                    "effectiveat",
                    "expiresat",
                    "verifiedat",
                    "revoked",
                    "immutable",
                    "consentevidenceid",
                    "consentevidencesha256",
                    "observationcontractid",
                    "observationschemaversion",
                    "approvalid",
                    "commandid",
                    "receiptid",
                    "permitevidenceid",
                    "readbackevidenceid",
                    "killswitchsequence",
                    "killswitchstateid",
                    "killswitchevidenceid",
                    "compensationplanid",
                    "compensationevidenceid",
                    "inputsha256",
                    "outputsha256",
                    "scope",
                    "tenantref",
                    "entityref",
                    "storeref",
                    "scopegrantauthoritysha256",
                    "asof",
                    "schema",
                    "schemaversion",
                    "storeaccountbinding",
                }
            ),
        },
        "permit": {
            "semantic": frozenset(
                {
                    "status",
                    "revoked",
                    "singleuse",
                    "approvalid",
                    "commandid",
                    "executionplanid",
                    "actionid",
                    "eventtype",
                    "sourceeventref",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "inputsha256",
                    "decisionhash",
                    "authorizationhash",
                    "issuedat",
                    "expiresat",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "status",
                    "revoked",
                    "singleuse",
                    "approvalid",
                    "commandid",
                    "executionplanid",
                    "actionid",
                    "eventtype",
                    "sourceeventref",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "inputsha256",
                    "outputsha256",
                    "decisionhash",
                    "authorizationhash",
                    "issuedat",
                    "expiresat",
                    "scope",
                    "tenantref",
                    "entityref",
                    "storeref",
                    "scopegrantauthoritysha256",
                }
            ),
        },
        "readback": {
            "semantic": frozenset(
                {
                    "outcome",
                    "officialorauthorized",
                    "approvalid",
                    "permitevidenceid",
                    "commandid",
                    "receiptid",
                    "actionid",
                    "eventtype",
                    "sourceeventref",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "authorizationchanged",
                    "remoteoperationid",
                    "inputsha256",
                    "resultingauthoritysha256",
                    "requesthash",
                    "readbackat",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "outcome",
                    "officialorauthorized",
                    "approvalid",
                    "permitevidenceid",
                    "commandid",
                    "receiptid",
                    "actionid",
                    "eventtype",
                    "sourceeventref",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "authorizationchanged",
                    "remoteoperationid",
                    "inputsha256",
                    "outputsha256",
                    "resultingauthoritysha256",
                    "requesthash",
                    "readbackat",
                    "scope",
                    "tenantref",
                    "entityref",
                    "storeref",
                    "scopegrantauthoritysha256",
                }
            ),
        },
        "kill_switch": {
            "semantic": frozenset(
                {
                    "purpose",
                    "status",
                    "writesenabled",
                    "killswitchsequence",
                    "killswitchactorid",
                    "actionid",
                    "sourceeventref",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "immutable",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "purpose",
                    "status",
                    "writesenabled",
                    "sourceeventref",
                    "sequence",
                    "killswitchsequence",
                    "actionid",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "adaptercontractsha256",
                    "effectiveat",
                    "scope",
                    "tenantref",
                    "entityref",
                    "storeref",
                    "scopegrantauthoritysha256",
                    "asof",
                }
            ),
        },
        "compensation": {
            "semantic": frozenset(
                {
                    "purpose",
                    "status",
                    "compensationplanid",
                    "compensationapprovalid",
                    "commandid",
                    "receiptid",
                    "actionid",
                    "sourceeventref",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "owner",
                    "compensationmode",
                    "preconditionstatesha256",
                    "mutatedstatesha256",
                    "restoreauthoritysha256",
                    "requiresfreshapproval",
                    "automaticexecutionallowed",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "purpose",
                    "status",
                    "compensationplanid",
                    "compensationapprovalid",
                    "commandid",
                    "receiptid",
                    "actionid",
                    "sourceeventref",
                    "platform",
                    "accountref",
                    "adapterid",
                    "adapterversion",
                    "owner",
                    "compensationmode",
                    "preconditionstatesha256",
                    "mutatedstatesha256",
                    "restoreauthoritysha256",
                    "requiresfreshapproval",
                    "automaticexecutionallowed",
                    "scope",
                    "tenantref",
                    "entityref",
                    "storeref",
                    "scopegrantauthoritysha256",
                }
            ),
        },
    }
    PURPOSE_REQUIRED_FIELDS: dict[str, dict[str, frozenset[str]]] = {
        "change_proposal": {
            "semantic": frozenset({"changekind"}),
            "canonical": frozenset(
                {
                    "contractid",
                    "platform",
                    "accountref",
                    "changekind",
                    "requestedcapabilities",
                }
            ),
        },
        "consent": {
            "semantic": frozenset({"status", "revoked", "immutable"}),
            "canonical": frozenset(
                {"contractid", "status", "revoked", "immutable"}
            ),
        },
        "lifecycle": {
            "semantic": frozenset(
                {
                    "sourceeventref",
                    "sequence",
                    "eventtype",
                    "status",
                    "revoked",
                    "immutable",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "sourceeventref",
                    "sequence",
                    "eventtype",
                    "status",
                    "revoked",
                    "immutable",
                }
            ),
        },
        "permit": {
            "semantic": frozenset(
                {
                    "status",
                    "revoked",
                    "singleuse",
                    "approvalid",
                    "commandid",
                    "executionplanid",
                    "actionid",
                    "sourceeventref",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "status",
                    "revoked",
                    "singleuse",
                    "approvalid",
                    "commandid",
                    "executionplanid",
                    "actionid",
                    "sourceeventref",
                }
            ),
        },
        "readback": {
            "semantic": frozenset(
                {
                    "outcome",
                    "officialorauthorized",
                    "commandid",
                    "receiptid",
                    "actionid",
                    "sourceeventref",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "outcome",
                    "officialorauthorized",
                    "commandid",
                    "receiptid",
                    "actionid",
                    "sourceeventref",
                }
            ),
        },
        "kill_switch": {
            "semantic": frozenset(
                {
                    "purpose",
                    "status",
                    "writesenabled",
                    "killswitchsequence",
                    "actionid",
                    "sourceeventref",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "purpose",
                    "status",
                    "writesenabled",
                    "killswitchsequence",
                    "actionid",
                    "sourceeventref",
                }
            ),
        },
        "compensation": {
            "semantic": frozenset(
                {
                    "purpose",
                    "status",
                    "compensationplanid",
                    "compensationapprovalid",
                    "actionid",
                    "sourceeventref",
                    "compensationmode",
                    "requiresfreshapproval",
                    "automaticexecutionallowed",
                }
            ),
            "canonical": frozenset(
                {
                    "contractid",
                    "purpose",
                    "status",
                    "compensationplanid",
                    "compensationapprovalid",
                    "actionid",
                    "sourceeventref",
                    "compensationmode",
                    "requiresfreshapproval",
                    "automaticexecutionallowed",
                }
            ),
        },
    }
    PURPOSE_ENUM_FIELDS: dict[str, dict[str, frozenset[str]]] = {
        "change_proposal": {
            "changekind": frozenset(
                {"grant_read_capability", "revoke_capability", "rotate_authorization"}
            ),
        },
        "consent": {
            "status": frozenset({"authorized", "pending", "revoked"}),
        },
        "lifecycle": {
            "eventtype": frozenset(
                {
                    "authorization_granted",
                    "authorization_refreshed",
                    "credential_rotated",
                    "authorization_revoked",
                    "authorization_expired",
                    "external_verification_readback",
                    "health_observed",
                    "rate_limit_observed",
                    "schema_drift_observed",
                    "unknown_outcome_observed",
                }
            ),
            "status": frozenset(
                {"active", "authorized", "blocked", "expired", "revoked", "unknown"}
            ),
        },
        "permit": {"status": frozenset({"issued"})},
        "readback": {
            "outcome": frozenset(
                {"succeeded", "failed", "unknown", "not_applicable"}
            )
        },
        "kill_switch": {"status": frozenset({"engaged", "released"})},
        "compensation": {"status": frozenset({"blocked", "ready"})},
    }

    def __init__(self, *, evidence, scope_authority=None) -> None:
        self.evidence = evidence
        self.scope_authority = scope_authority

    def submit(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        purpose: str,
        effective_at: str,
        effective_until: str | None,
        idempotency_key: str,
        semantic_metadata: dict[str, Any],
        canonical_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not principal.has_any_role("operator", "admin"):
            raise PermissionError("Channel account Evidence submission requires operator")
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=parse_timestamp(effective_at, "effective_at"),
        )
        purpose = self._purpose(purpose)
        idempotency_key = self._required(
            idempotency_key,
            "idempotency_key",
            160,
        )
        self._reject_client_supplied_digest_fields(
            semantic_metadata,
            field="semantic_metadata",
        )
        self._reject_client_supplied_digest_fields(
            canonical_payload,
            field="canonical_payload",
        )
        metadata = self._semantic(
            semantic_metadata,
            allowed_fields=self.PURPOSE_SCHEMAS[purpose]["semantic"],
            field="semantic_metadata",
            reject_sibling_fragmentation=purpose != "change_proposal",
        )
        canonical_payload = self._semantic(
            canonical_payload,
            allowed_fields=self.PURPOSE_SCHEMAS[purpose]["canonical"],
            field="canonical_payload",
            reject_server_owned=False,
            reject_sibling_fragmentation=purpose != "change_proposal",
        )
        self._require_purpose_contract(
            purpose=purpose,
            semantic_metadata=metadata,
            canonical_payload=canonical_payload,
        )
        if purpose != "change_proposal":
            ChannelAccountAuthorizationAuthority._reject_sibling_fragmentation(
                {
                    "semantic_metadata": metadata,
                    "canonical_payload": canonical_payload,
                }
            )
        self._require_semantic_payload_binding(
            semantic_metadata=metadata,
            canonical_payload=canonical_payload,
        )
        content = ChannelAccountAuthorizationAuthority._canonical_bytes(canonical_payload)
        canonical_payload_sha256 = hashlib.sha256(content).hexdigest()
        record = self.evidence.capture(
            content=content,
            filename=f"channel-account-{purpose}.json",
            content_type="application/json",
            source="channel_account_governance_submission",
            source_ref=(
                "channel-account-submission://"
                f"{scope['tenant_ref']}/{scope['entity_ref']}/"
                f"{scope['store_ref']}/{purpose}/{idempotency_key}"
            ),
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=effective_until,
            created_by=principal.actor_id,
            metadata={
                "contract_id": self.SUBMISSION_CONTRACT_ID,
                "purpose": purpose,
                "semantic_metadata": metadata,
                "canonical_payload_sha256": (canonical_payload_sha256),
                **scope,
            },
            _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
        )
        return {
            "contract_id": self.SUBMISSION_CONTRACT_ID,
            "status": "submitted",
            "purpose": purpose,
            "evidence_id": record.id,
            "evidence_sha256": record.sha256,
            "submitted_by": principal.actor_id,
            "scope": scope,
        }

    def review(
        self,
        **values: Any,
    ) -> dict[str, Any]:
        submission_id = self._required(
            values.get("submission_evidence_id"),
            "submission_evidence_id",
            240,
        )
        with self._serialize_review(submission_id) as review_session:
            return self._review_serialized(
                _review_session=review_session,
                **values,
            )

    def require_reviewed(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        evidence_id: str,
        purpose: str | None = None,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Return a non-secret projection of one current canonical SoD review."""
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        evidence_id = self._required(evidence_id, "evidence_id", 240)
        record = self.evidence.get_metadata(evidence_id)
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        expected_purpose = self._purpose(purpose) if purpose is not None else None
        allowed_sources = {source for source, _contract in self.PURPOSES.values()}
        expected_source = self.PURPOSES[expected_purpose][0] if expected_purpose is not None else None
        if (
            record.source not in allowed_sources
            or (expected_source is not None and record.source != expected_source)
            or metadata.get("channel_account_review_contract_id") != self.REVIEW_CONTRACT_ID
            or any(
                metadata.get(key) != scope[key]
                for key in ("tenant_ref", "entity_ref", "store_ref")
            )
            or not str(metadata.get("submitted_by") or "").strip()
            or not str(metadata.get("reviewed_by") or "").strip()
            or metadata.get("submitted_by") == metadata.get("reviewed_by")
        ):
            raise ValueError("Channel account Evidence is not an independent canonical review")
        self.evidence.require_current([evidence_id], as_of=as_of)
        verification = self.evidence.verify(evidence_id)
        if not verification.valid:
            raise ValueError("Channel account reviewed Evidence integrity failed")
        content, content_record = self.evidence.content(evidence_id)
        if content_record.id != record.id:
            raise ValueError("Channel account reviewed Evidence content binding drift")
        try:
            canonical_payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Channel account reviewed Evidence payload is invalid") from exc
        if not isinstance(canonical_payload, dict):
            raise ValueError("Channel account reviewed Evidence payload must be an object")
        if expected_purpose is not None:
            expected_contract = self.PURPOSES[expected_purpose][1]
            if canonical_payload.get("contract_id") != expected_contract:
                raise ValueError("Channel account reviewed Evidence purpose contract is invalid")
        return {
            "evidence_id": record.id,
            "evidence_sha256": record.sha256,
            "source": record.source,
            "submitted_by": metadata["submitted_by"],
            "reviewed_by": metadata["reviewed_by"],
            "scope": scope,
            "purpose": expected_purpose,
            "canonical_payload": canonical_payload,
        }

    def _review_serialized(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        submission_evidence_id: str,
        accepted: bool,
        rationale: str,
        as_of: datetime,
        _review_session: Session,
    ) -> dict[str, Any]:
        if not principal.has_any_role(
            "reviewer",
            "compliance",
            "approver",
            "admin",
        ):
            raise PermissionError("Channel account Evidence review requires reviewer")
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        rationale = self._required(rationale, "rationale", 4000)
        ChannelAccountAuthorizationAuthority._reject_sensitive_metadata({"rationale": rationale})
        submission = self.evidence.get_metadata(submission_evidence_id)
        metadata = submission.metadata
        if any(
            metadata.get(key) != scope.get(key)
            for key in ("tenant_ref", "entity_ref", "store_ref")
        ):
            raise PermissionError("Channel account Evidence review exact scope is invalid")
        if (
            submission.source != "channel_account_governance_submission"
            or metadata.get("contract_id") != self.SUBMISSION_CONTRACT_ID
            or not submission.created_by
            or submission.created_by == principal.actor_id
        ):
            raise ValueError("Channel account Evidence review lacks independent submission authority")
        self.evidence.require_current(
            [submission_evidence_id],
            as_of=as_of,
        )
        purpose = self._purpose(str(metadata.get("purpose") or ""))
        content, content_record = self.evidence.content(submission_evidence_id)
        if content_record.id != submission.id:
            raise ValueError("Channel account submission content binding drift")
        semantic = self._semantic(
            metadata.get("semantic_metadata") or {},
            allowed_fields=self.PURPOSE_SCHEMAS[purpose]["semantic"],
            field="semantic_metadata",
            reject_sibling_fragmentation=purpose != "change_proposal",
        )
        try:
            canonical_payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Channel account canonical submission is not valid JSON") from exc
        canonical_payload = self._semantic(
            canonical_payload,
            allowed_fields=self.PURPOSE_SCHEMAS[purpose]["canonical"],
            field="canonical_payload",
            reject_server_owned=False,
            reject_sibling_fragmentation=purpose != "change_proposal",
        )
        self._require_semantic_payload_binding(
            semantic_metadata=semantic,
            canonical_payload=canonical_payload,
        )
        canonical_payload_sha256 = hashlib.sha256(content).hexdigest()
        if (
            metadata.get("canonical_payload_sha256") != canonical_payload_sha256
            or submission.sha256 != canonical_payload_sha256
        ):
            raise ValueError("Channel account canonical submission payload drift")
        review_sequence = self._next_review_sequence(
            submission.id,
            session=_review_session,
        )
        decision_payload = {
            "contract_id": self.REVIEW_CONTRACT_ID,
            "submission_evidence_id": submission.id,
            "submission_evidence_sha256": submission.sha256,
            "reviewed_by": principal.actor_id,
            "sequence": review_sequence,
            "accepted": accepted,
            "rationale_sha256": hashlib.sha256(rationale.encode()).hexdigest(),
            "as_of": self._aware(as_of).isoformat(),
            "scope": scope,
        }
        decision_sha256 = hashlib.sha256(
            ChannelAccountAuthorizationAuthority._canonical_bytes(decision_payload)
        ).hexdigest()
        review_source_ref = (
            "channel-account-review://"
            f"{scope['tenant_ref']}/{scope['entity_ref']}/"
            f"{scope['store_ref']}/{submission.id}/"
            f"{review_sequence}/{principal.actor_id}/"
            f"{decision_sha256}"
        )
        if not accepted:
            rejected = self.evidence.capture(
                content=(ChannelAccountAuthorizationAuthority._canonical_bytes(decision_payload)),
                filename="channel-account-rejected-review.json",
                content_type="application/json",
                source="channel_account_governance_review",
                source_ref=review_source_ref,
                grade=EvidenceGrade.A,
                effective_at=self._aware(as_of).isoformat(),
                effective_until=None,
                created_by=principal.actor_id,
                metadata={
                    "contract_id": self.REVIEW_CONTRACT_ID,
                    "status": "rejected",
                    "accepted": False,
                    "review_sequence": review_sequence,
                    "review_decision_sha256": decision_sha256,
                    "reviewed_submission_id": submission.id,
                    "reviewed_submission_sha256": submission.sha256,
                    "reviewed_by": principal.actor_id,
                    **scope,
                },
                _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
                _session=_review_session,
            )
            self._record_review_decision(
                submission=submission,
                decision_evidence_id=rejected.id,
                sequence=review_sequence,
                accepted=False,
                reviewer_id=principal.actor_id,
                decision_sha256=decision_sha256,
                decided_at=self._aware(as_of),
                scope=scope,
                session=_review_session,
            )
            return {
                "contract_id": self.REVIEW_CONTRACT_ID,
                "status": "rejected",
                "purpose": purpose,
                "evidence_id": rejected.id,
                "evidence_sha256": rejected.sha256,
                "submitted_by": submission.created_by,
                "reviewed_by": principal.actor_id,
                "review_sequence": review_sequence,
                "scope": scope,
            }
        source, contract_id = self.PURPOSES[purpose]
        server_hashes = {
            "canonical_payload_sha256": canonical_payload_sha256,
        }
        if purpose == "lifecycle":
            server_hashes["event_payload_sha256"] = canonical_payload_sha256
        if purpose == "kill_switch":
            server_hashes["kill_switch_state_payload_sha256"] = canonical_payload_sha256
        reviewed = self.evidence.capture(
            content=content,
            filename=submission.filename,
            content_type=submission.content_type,
            source=source,
            source_ref=review_source_ref,
            grade=EvidenceGrade.A,
            effective_at=self._aware(submission.effective_at).isoformat(),
            effective_until=(
                self._aware(submission.effective_until).isoformat() if submission.effective_until is not None else None
            ),
            created_by=submission.created_by,
            metadata={
                **semantic,
                **server_hashes,
                "contract_id": contract_id,
                "evidence_scope_contract_id": DIRECT_CONTRACT,
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "submitted_by": submission.created_by,
                "reviewed_by": principal.actor_id,
                "review_sequence": review_sequence,
                "reviewed_submission_id": submission.id,
                "reviewed_submission_sha256": submission.sha256,
                "channel_account_review_contract_id": (self.REVIEW_CONTRACT_ID),
                "review_decision_sha256": decision_sha256,
                "review_rationale_sha256": hashlib.sha256(rationale.encode()).hexdigest(),
            },
            _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
            _session=_review_session,
        )
        self._record_review_decision(
            submission=submission,
            decision_evidence_id=reviewed.id,
            sequence=review_sequence,
            accepted=True,
            reviewer_id=principal.actor_id,
            decision_sha256=decision_sha256,
            decided_at=self._aware(as_of),
            scope=scope,
            session=_review_session,
        )
        return {
            "contract_id": self.REVIEW_CONTRACT_ID,
            "status": "accepted",
            "purpose": purpose,
            "evidence_id": reviewed.id,
            "evidence_sha256": reviewed.sha256,
            "submitted_by": submission.created_by,
            "reviewed_by": principal.actor_id,
            "review_sequence": review_sequence,
            "scope": scope,
        }

    @contextmanager
    def _serialize_review(self, submission_evidence_id: str):
        """Serialize one submission review across threads and PostgreSQL workers."""

        with self._review_locks_guard:
            local_lock, users = self._review_locks.get(
                submission_evidence_id,
                (Lock(), 0),
            )
            self._review_locks[submission_evidence_id] = (local_lock, users + 1)
        try:
            with local_lock, Session(self.evidence.engine) as session, session.begin():
                if self.evidence.engine.dialect.name == "postgresql":
                    lock_key = f"channel-account-review:{submission_evidence_id}"
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                        {"lock_key": lock_key},
                    )
                yield session
        finally:
            with self._review_locks_guard:
                _, users = self._review_locks[submission_evidence_id]
                if users == 1:
                    self._review_locks.pop(submission_evidence_id, None)
                else:
                    self._review_locks[submission_evidence_id] = (
                        local_lock,
                        users - 1,
                    )

    def _next_review_sequence(
        self,
        submission_evidence_id: str,
        *,
        session: Session,
    ) -> int:
        latest = session.scalar(
            select(ChannelAccountReviewDecisionRow)
            .where(ChannelAccountReviewDecisionRow.submission_evidence_id == submission_evidence_id)
            .order_by(
                ChannelAccountReviewDecisionRow.sequence.desc(),
                ChannelAccountReviewDecisionRow.id.desc(),
            )
            .limit(1)
        )
        return 1 if latest is None else latest.sequence + 1

    def _record_review_decision(
        self,
        *,
        submission,
        decision_evidence_id: str,
        sequence: int,
        accepted: bool,
        reviewer_id: str,
        decision_sha256: str,
        decided_at: datetime,
        scope: dict[str, str],
        session: Session,
    ) -> None:
        row = ChannelAccountReviewDecisionRow(
            id=new_id("card"),
            submission_evidence_id=submission.id,
            decision_evidence_id=decision_evidence_id,
            sequence=sequence,
            accepted=accepted,
            reviewer_id=reviewer_id,
            decision_sha256=decision_sha256,
            decided_at=decided_at,
            recorded_at=datetime.now(UTC),
            tenant_ref=scope["tenant_ref"],
            entity_ref=scope["entity_ref"],
            store_ref=scope["store_ref"],
        )
        session.add(row)
        session.flush()

    @classmethod
    def _semantic(
        cls,
        value: Any,
        *,
        allowed_fields: frozenset[str],
        field: str,
        reject_server_owned: bool = True,
        reject_sibling_fragmentation: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{field} must be an object")
        normalized_server_fields = {
            ChannelAccountAuthorizationAuthority._normalized_key(key) for key in cls.SERVER_OWNED_FIELDS
        }
        normalized_keys = {ChannelAccountAuthorizationAuthority._normalized_key(str(key)) for key in value}
        if reject_server_owned and normalized_server_fields.intersection(normalized_keys):
            raise ValueError("Channel account review fields are server-owned")
        ChannelAccountAuthorizationAuthority._reject_sensitive_metadata(
            value,
            allowed_fields=allowed_fields,
        )
        cls._validate_typed_structure(value)
        if reject_sibling_fragmentation:
            ChannelAccountAuthorizationAuthority._reject_sibling_fragmentation(value)
        return value

    @classmethod
    def _reject_client_supplied_digest_fields(
        cls,
        value: Any,
        *,
        field: str,
        path: str = "root",
    ) -> None:
        """Keep digest authority server-derived while mutation intake is gated.

        A lowercase 64-hex value proves only shape.  It does not prove that the
        value was derived from a canonical fact, managed credential record, or
        governed command/receipt.  BAS-158 intentionally exposes no public
        mutation workflow, so the specialized intake must reject every
        client-controlled authority digest.  The capture path itself derives
        the immutable content hash after validating the closed payload.
        """

        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = ChannelAccountAuthorizationAuthority._normalized_key(
                    str(raw_key)
                )
                child_path = f"{path}.{raw_key}"
                if key in cls.DIGEST_FIELDS:
                    raise ValueError(
                        f"{field} digest fields require server-derived authority: "
                        f"{child_path}"
                    )
                cls._reject_client_supplied_digest_fields(
                    child,
                    field=field,
                    path=child_path,
                )
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                cls._reject_client_supplied_digest_fields(
                    child,
                    field=field,
                    path=f"{path}[{index}]",
                )

    @classmethod
    def _require_semantic_payload_binding(
        cls,
        *,
        semantic_metadata: dict[str, Any],
        canonical_payload: dict[str, Any],
    ) -> None:
        """Metadata is a server-verified projection of the immutable blob."""

        canonical = {
            ChannelAccountAuthorizationAuthority._normalized_key(str(key)): value
            for key, value in canonical_payload.items()
        }
        for raw_key, value in semantic_metadata.items():
            key = ChannelAccountAuthorizationAuthority._normalized_key(str(raw_key))
            if key not in canonical or canonical[key] != value:
                raise ValueError("Channel account semantic metadata must match the canonical payload")

    @classmethod
    def _require_purpose_contract(
        cls,
        *,
        purpose: str,
        semantic_metadata: dict[str, Any],
        canonical_payload: dict[str, Any],
    ) -> None:
        for kind, value in (
            ("semantic", semantic_metadata),
            ("canonical", canonical_payload),
        ):
            normalized = {
                ChannelAccountAuthorizationAuthority._normalized_key(str(key)): child
                for key, child in value.items()
            }
            missing = sorted(
                cls.PURPOSE_REQUIRED_FIELDS[purpose][kind] - set(normalized)
            )
            if missing:
                raise ValueError(
                    f"Channel account {purpose} {kind} payload is missing required fields: "
                    + ", ".join(missing)
                )
            for field, allowed in cls.PURPOSE_ENUM_FIELDS[purpose].items():
                if field in normalized and normalized[field] not in allowed:
                    raise ValueError(
                        f"Channel account {purpose} {field} is outside the closed enum"
                    )
            authorization_source = normalized.get("authorizationsource")
            if authorization_source is not None and authorization_source not in {
                "official",
                "explicit_written_authorization",
            }:
                raise ValueError(
                    "Channel account authorization source is not official or explicitly authorized"
                )
            credential_kind = normalized.get("credentialkind")
            if credential_kind is not None and credential_kind not in {
                "api_key_ref",
                "oauth_client_ref",
                "service_account_ref",
            }:
                raise ValueError("Channel account credential kind is unsafe")

    @classmethod
    def _validate_typed_structure(
        cls,
        value: dict[str, Any],
        *,
        path: str = "root",
    ) -> None:
        normalized_keys: set[str] = set()
        for raw_key, child in value.items():
            key = ChannelAccountAuthorizationAuthority._normalized_key(str(raw_key))
            if key in normalized_keys:
                raise ValueError("Normalized duplicate field is forbidden by the channel account Evidence schema")
            normalized_keys.add(key)
            field_path = f"{path}.{raw_key}"
            if key in cls.BOOLEAN_FIELDS:
                if not isinstance(child, bool):
                    raise ValueError(f"{field_path} must be a boolean")
                continue
            if key in cls.INTEGER_FIELDS:
                if isinstance(child, bool) or not isinstance(child, int) or child < 1:
                    raise ValueError(f"{field_path} must be a positive integer")
                continue
            if key in cls.STRING_LIST_FIELDS:
                if (
                    not isinstance(child, list)
                    or len(child) > 100
                    or not all(isinstance(item, str) and 0 < len(item.strip()) <= 240 for item in child)
                ):
                    raise ValueError(f"{field_path} must be a bounded string list")
                cls._scan_joined_string_fragments(child)
                continue
            if key in cls.OBJECT_FIELDS:
                raise ValueError(
                    f"{field_path} nested authority objects require a server-derived workflow"
                )
            if child is None and key in cls.OPTIONAL_STRING_FIELDS:
                continue
            if not isinstance(child, str) or not 0 < len(child.strip()) <= 4000:
                raise ValueError(f"{field_path} must be a bounded string")
            if key in cls.DIGEST_FIELDS and not re.fullmatch(
                r"[0-9a-f]{64}",
                child,
            ):
                raise ValueError(f"{field_path} must be lowercase SHA-256")

    @staticmethod
    def _scan_joined_string_fragments(values: list[str]) -> None:
        for joined in (
            "".join(values),
            " ".join(values),
            ":".join(values),
        ):
            ChannelAccountAuthorizationAuthority._reject_sensitive_metadata(
                {"joined_value": joined},
            )

    @classmethod
    def _purpose(cls, value: str) -> str:
        purpose = str(value or "").strip().lower()
        if purpose not in cls.PURPOSES:
            raise ValueError("Unsupported channel account Evidence purpose")
        return purpose

    def _scope(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, str]:
        if self.scope_authority is None:
            raise PermissionError(
                "Channel account Evidence canonical scope authority is unbound"
            )
        return self.scope_authority.resolve(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )

    @staticmethod
    def _required(value: Any, field: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > limit:
            raise ValueError(f"{field} must be 1 to {limit} characters")
        return normalized

    @staticmethod
    def _aware(value: datetime | str) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ChannelAccountAuthorizationAuthority:
    """Append-only authority; it records readbacks, never changes providers."""

    EVENT_CONTRACT_ID = "kjds-channel-account-authorization-event-v1"
    SOURCE_CONTRACT_ID = "kjds-channel-account-authority-source-v1"
    SOURCE_EVIDENCE_CONTRACT_ID = "kjds-channel-account-lifecycle-evidence-v1"
    CONSENT_EVIDENCE_CONTRACT_ID = "kjds-channel-account-consent-evidence-v1"
    PERMIT_CONTRACT_ID = "kjds-channel-account-one-time-permit-v1"
    READBACK_CONTRACT_ID = "kjds-channel-account-readback-v1"
    EVENT_TYPES = frozenset(
        {
            "authorization_granted",
            "authorization_refreshed",
            "credential_rotated",
            "authorization_revoked",
            "authorization_expired",
            "external_verification_readback",
            "health_observed",
            "rate_limit_observed",
            "schema_drift_observed",
            "unknown_outcome_observed",
        }
    )
    GOVERNED_EVENTS = frozenset(
        {
            "authorization_granted",
            "authorization_refreshed",
            "credential_rotated",
            "authorization_revoked",
            "external_verification_readback",
        }
    )
    ACTION_IDS = {
        "authorization_granted": "channel_authorization_grant",
        "authorization_refreshed": "channel_authorization_refresh",
        "credential_rotated": "channel_credential_rotate",
        "authorization_revoked": "channel_authorization_revoke",
        "external_verification_readback": ("channel_authorization_external_verify"),
    }
    HEALTH_STATES = frozenset({"healthy", "degraded", "unreachable", "unknown"})
    READBACK_OUTCOMES = frozenset({"succeeded", "failed", "unknown", "not_applicable"})
    RATE_LIMIT_STATES = frozenset({"available", "limited", "exhausted", "unknown"})
    SENSITIVE_KEY_FRAGMENTS = frozenset(
        {
            "accesstoken",
            "apikey",
            "authorizationheader",
            "bearer",
            "captcha",
            "clientsecret",
            "cookie",
            "cookies",
            "devicesession",
            "password",
            "refreshtoken",
            "secret",
            "session",
            "token",
        }
    )
    SAFE_SENSITIVE_DIGEST_KEYS = frozenset(
        {
            "consentevidencesha256",
            "credentialfingerprintsha256",
            "reviewedsubmissionsha256",
            "secretreferencesha256",
            "sourceevidencesha256",
        }
    )
    SENSITIVE_VALUE_RE = re.compile(
        r"(?i)(?:"
        r"(?:secret-ref|vault|kms)://|"
        r"^\s*(?:bearer|basic)\s+\S+|"
        r"(?:access[-_ ]?token|refresh[-_ ]?token|api[-_ ]?key|"
        r"client[-_ ]?secret|authorization[-_ ]?header|cookie|"
        r"device[-_ ]?session|password)\s*[:=]\s*\S+"
        r")"
    )
    PROVIDER_SECRET_RE = re.compile(
        r"(?i)(?:"
        r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9_-]{6,}\b|"
        r"\b(?:ghp|github_pat|xox[baprs]|AKIA)[A-Za-z0-9_-]{8,}\b|"
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
        r"[A-Za-z0-9_-]{8,}\b|"
        r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----|"
        r"<\s*jwt\s*>"
        r")"
    )
    MANAGED_LOCATOR_RE = re.compile(
        r"(?i)(?<![A-Za-z0-9])msl_[A-Za-z0-9]{24,96}(?![A-Za-z0-9])"
    )

    def __init__(
        self,
        *,
        engine,
        evidence,
        scoped_evidence,
        adapters: ChannelAccountAdapterRegistry,
        scope_authority=None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence
        self.adapters = adapters
        self.scope_authority = scope_authority

    def record_kill_switch_state(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        source_event_ref: str,
        sequence: int,
        kill_switch_sequence: int,
        writes_enabled: bool,
        action_id: str,
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        evidence_id: str,
        effective_at: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        if not principal.has_any_role("risk", "compliance", "admin"):
            raise PermissionError("Kill Switch state recording requires risk authority")
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        source_event_ref = self._required(
            source_event_ref,
            "source_event_ref",
            240,
        )
        sequence = self._positive_int_or_none(sequence, "sequence") or 0
        kill_switch_sequence = (
            self._positive_int_or_none(
                kill_switch_sequence,
                "kill_switch_sequence",
            )
            or 0
        )
        if not isinstance(writes_enabled, bool):
            raise ValueError("writes_enabled must be true or false")
        action_id = self._required(action_id, "action_id", 160)
        if action_id not in {*self.ACTION_IDS.values()}:
            raise ValueError("Kill Switch action is not a channel authorization action")
        platform = self._required(platform, "platform", 80).lower()
        account_ref = self._required(account_ref, "account_ref", 240)
        adapter_id = self._required(adapter_id, "adapter_id", 160)
        adapter_version = self._required(
            adapter_version,
            "adapter_version",
            80,
        )
        effective = parse_timestamp(effective_at, "effective_at")
        if effective > context["cutoff"]:
            raise ValueError("Kill Switch state cannot be effective in the future")
        evidence_id = self._required(evidence_id, "evidence_id", 240)
        replay = self._idempotent_kill_switch_replay(
            context=context,
            source_event_ref=source_event_ref,
            sequence=sequence,
            kill_switch_sequence=kill_switch_sequence,
            writes_enabled=writes_enabled,
            action_id=action_id,
            platform=platform,
            account_ref=account_ref,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            evidence_id=evidence_id,
            effective_at=effective,
        )
        if replay is not None:
            return replay
        adapter = self.adapters.resolve(
            platform=platform,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            as_of=context["cutoff"],
        )
        evidence = self._require_exact_evidence(
            evidence_id=evidence_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        self._require_reviewed_evidence(
            record=evidence,
            purpose="kill_switch",
            context=context,
        )
        payload = {
            "contract_id": ("kjds-channel-account-kill-switch-state-v1"),
            "schema_version": "1",
            "source_event_ref": source_event_ref,
            "sequence": sequence,
            "kill_switch_sequence": kill_switch_sequence,
            "writes_enabled": writes_enabled,
            "action_id": action_id,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "adapter_contract_sha256": adapter["contract_sha256"],
            "effective_at": effective.isoformat(),
            "scope": {
                **context["scope"],
                "as_of": context["cutoff"].isoformat(),
            },
        }
        canonical = self._canonical_bytes(payload)
        content, _ = self.evidence.content(evidence.id)
        payload_sha256 = hashlib.sha256(canonical).hexdigest()
        metadata = evidence.metadata
        if (
            content != canonical
            or evidence.sha256 != payload_sha256
            or metadata.get("kill_switch_state_payload_sha256") != payload_sha256
            or metadata.get("status") != ("released" if writes_enabled else "engaged")
        ):
            raise ValueError("Kill Switch state Evidence payload is invalid")
        try:
            with (
                Session(
                    self.engine,
                    expire_on_commit=False,
                ) as session,
                session.begin(),
            ):
                global_state = session.scalar(
                    select(KillSwitchEventRow)
                    .where(KillSwitchEventRow.created_at <= effective)
                    .order_by(KillSwitchEventRow.sequence.desc())
                    .limit(1)
                )
                if (
                    global_state is None
                    or global_state.sequence != kill_switch_sequence
                    or writes_enabled is global_state.engaged
                ):
                    raise ValueError("Kill Switch binding is not the canonical latest state")
                existing = session.scalar(
                    select(ChannelAccountKillSwitchStateRow).where(
                        ChannelAccountKillSwitchStateRow.tenant_ref == context["scope"]["tenant_ref"],
                        ChannelAccountKillSwitchStateRow.entity_ref == context["scope"]["entity_ref"],
                        ChannelAccountKillSwitchStateRow.store_ref == context["scope"]["store_ref"],
                        ChannelAccountKillSwitchStateRow.source_event_ref == source_event_ref,
                    )
                )
                if existing is not None:
                    if existing.payload_sha256 != payload_sha256:
                        raise ValueError("Kill Switch source conflicts with immutable state")
                    return self._kill_switch_state(existing, True)
                latest = session.scalar(
                    select(ChannelAccountKillSwitchStateRow)
                    .where(
                        ChannelAccountKillSwitchStateRow.tenant_ref == context["scope"]["tenant_ref"],
                        ChannelAccountKillSwitchStateRow.entity_ref == context["scope"]["entity_ref"],
                        ChannelAccountKillSwitchStateRow.store_ref == context["scope"]["store_ref"],
                        ChannelAccountKillSwitchStateRow.platform == platform,
                        ChannelAccountKillSwitchStateRow.account_ref == account_ref,
                        ChannelAccountKillSwitchStateRow.adapter_id == adapter_id,
                        ChannelAccountKillSwitchStateRow.action_id == action_id,
                    )
                    .order_by(
                        ChannelAccountKillSwitchStateRow.sequence.desc(),
                        ChannelAccountKillSwitchStateRow.id.desc(),
                    )
                    .limit(1)
                    .with_for_update()
                )
                expected = 1 if latest is None else latest.sequence + 1
                if sequence != expected:
                    raise ValueError(f"Kill Switch state sequence must be {expected}")
                if latest is not None and effective < self._aware(latest.effective_at):
                    raise ValueError("Kill Switch state time moved backwards")
                row = ChannelAccountKillSwitchStateRow(
                    id=new_id("caks"),
                    source_event_ref=source_event_ref,
                    sequence=sequence,
                    kill_switch_sequence=kill_switch_sequence,
                    writes_enabled=writes_enabled,
                    action_id=action_id,
                    platform=platform,
                    account_ref=account_ref,
                    adapter_id=adapter_id,
                    adapter_version=adapter_version,
                    evidence_id=evidence.id,
                    evidence_sha256=evidence.sha256,
                    payload_sha256=payload_sha256,
                    effective_at=effective,
                    recorded_at=datetime.now(UTC),
                    created_by=principal.actor_id,
                    scope_as_of=context["cutoff"],
                    **context["scope"],
                )
                session.add(row)
                session.flush()
                result = self._kill_switch_state(row, False)
            return result
        except IntegrityError as exc:
            concurrent_replay = self._idempotent_kill_switch_replay(
                context=context,
                source_event_ref=source_event_ref,
                sequence=sequence,
                kill_switch_sequence=kill_switch_sequence,
                writes_enabled=writes_enabled,
                action_id=action_id,
                platform=platform,
                account_ref=account_ref,
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                evidence_id=evidence_id,
                effective_at=effective,
            )
            if concurrent_replay is not None:
                return concurrent_replay
            raise ValueError("Concurrent Kill Switch state conflicts with immutable authority") from exc

    def _idempotent_kill_switch_replay(
        self,
        *,
        context: dict[str, Any],
        source_event_ref: str,
        sequence: int,
        kill_switch_sequence: int,
        writes_enabled: bool,
        action_id: str,
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        evidence_id: str,
        effective_at: datetime,
    ) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            existing = session.scalar(
                select(ChannelAccountKillSwitchStateRow).where(
                    ChannelAccountKillSwitchStateRow.tenant_ref == context["scope"]["tenant_ref"],
                    ChannelAccountKillSwitchStateRow.entity_ref == context["scope"]["entity_ref"],
                    ChannelAccountKillSwitchStateRow.store_ref == context["scope"]["store_ref"],
                    ChannelAccountKillSwitchStateRow.source_event_ref == source_event_ref,
                )
            )
        if existing is None:
            return None
        expected = {
            "sequence": sequence,
            "kill_switch_sequence": kill_switch_sequence,
            "writes_enabled": writes_enabled,
            "action_id": action_id,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "evidence_id": evidence_id,
            "effective_at": effective_at,
        }
        if any(
            (self._aware(getattr(existing, field)) if field == "effective_at" else getattr(existing, field)) != value
            for field, value in expected.items()
        ):
            raise ValueError("Kill Switch source conflicts with immutable state")
        return self._kill_switch_state(existing, True)

    def append_event(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        source_event_ref: str,
        sequence: int,
        event_type: str,
        authorization_source: str,
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        credential_kind: str,
        capabilities: list[str],
        secret_reference: str,
        credential_fingerprint_sha256: str,
        health_status: str,
        readback_outcome: str,
        rate_limit_state: str,
        external_schema_version: str,
        consent_evidence_id: str,
        evidence_id: str,
        effective_at: str,
        expires_at: str,
        verified_at: str,
        role_ref: str | None = None,
        subaccount_ref: str | None = None,
        approval_id: str | None = None,
        command_id: str | None = None,
        receipt_id: str | None = None,
        permit_evidence_id: str | None = None,
        readback_evidence_id: str | None = None,
        kill_switch_sequence: int | None = None,
        kill_switch_state_id: str | None = None,
        kill_switch_evidence_id: str | None = None,
        compensation_plan_id: str | None = None,
        compensation_evidence_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        if not principal.has_any_role("operator", "admin"):
            raise PermissionError("Channel account lifecycle append requires operator")
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        source_event_ref = self._required(source_event_ref, "source_event_ref", 240)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("sequence must be a positive integer")
        committed_replay = self._committed_event_replay_before_dependencies(
            context=context,
            source_event_ref=source_event_ref,
            sequence=sequence,
            event_type=event_type,
            authorization_source=authorization_source,
            platform=platform,
            account_ref=account_ref,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            credential_kind=credential_kind,
            capabilities=capabilities,
            secret_reference=secret_reference,
            credential_fingerprint_sha256=credential_fingerprint_sha256,
            health_status=health_status,
            readback_outcome=readback_outcome,
            rate_limit_state=rate_limit_state,
            external_schema_version=external_schema_version,
            consent_evidence_id=consent_evidence_id,
            evidence_id=evidence_id,
            effective_at=effective_at,
            expires_at=expires_at,
            verified_at=verified_at,
            role_ref=role_ref,
            subaccount_ref=subaccount_ref,
            approval_id=approval_id,
            command_id=command_id,
            receipt_id=receipt_id,
            permit_evidence_id=permit_evidence_id,
            readback_evidence_id=readback_evidence_id,
            kill_switch_sequence=kill_switch_sequence,
            kill_switch_state_id=kill_switch_state_id,
            kill_switch_evidence_id=kill_switch_evidence_id,
            compensation_plan_id=compensation_plan_id,
            compensation_evidence_id=compensation_evidence_id,
        )
        if committed_replay is not None:
            return committed_replay
        event_type = self._choice(event_type, "event_type", self.EVENT_TYPES)
        authorization_source = self._choice(
            authorization_source,
            "authorization_source",
            frozenset({"official", "explicit_written_authorization"}),
        )
        platform = self._required(platform, "platform", 80).lower()
        account_ref = self._required(account_ref, "account_ref", 240)
        adapter_id = self._required(adapter_id, "adapter_id", 160)
        adapter_version = self._required(adapter_version, "adapter_version", 80)
        contract = self.adapters.resolve(
            platform=platform,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            as_of=context["cutoff"],
        )
        if authorization_source not in contract["authorization_sources"]:
            raise ValueError("Authorization source is not allowed by adapter contract")
        credential_kind = self._required(credential_kind, "credential_kind", 80)
        if credential_kind not in contract["credential_kinds"]:
            raise ValueError("Credential kind is not allowed by adapter contract")
        capabilities = self._capabilities(
            capabilities,
            allowed=contract["allowed_capabilities"],
        )
        secret_reference = self._secret_reference(secret_reference)
        secret_reference_sha256 = self._hash_text(secret_reference)
        credential_fingerprint_sha256 = self._sha256_value(
            credential_fingerprint_sha256,
            "credential_fingerprint_sha256",
        )
        role_ref = self._optional(role_ref, "role_ref", 160)
        subaccount_ref = self._optional(subaccount_ref, "subaccount_ref", 240)
        health_status = self._choice(health_status, "health_status", self.HEALTH_STATES)
        readback_outcome = self._choice(
            readback_outcome,
            "readback_outcome",
            self.READBACK_OUTCOMES,
        )
        rate_limit_state = self._choice(
            rate_limit_state,
            "rate_limit_state",
            self.RATE_LIMIT_STATES,
        )
        external_schema_version = self._required(
            external_schema_version,
            "external_schema_version",
            80,
        )
        effective = parse_timestamp(effective_at, "effective_at")
        expires = parse_timestamp(expires_at, "expires_at")
        verified = parse_timestamp(verified_at, "verified_at")
        if effective > context["cutoff"] or verified > context["cutoff"] or expires <= effective:
            raise ValueError("Authorization event time boundary is invalid")
        governance = {
            "approval_id": self._optional(approval_id, "approval_id", 240),
            "command_id": self._optional(command_id, "command_id", 240),
            "receipt_id": self._optional(receipt_id, "receipt_id", 240),
            "permit_evidence_id": self._optional(permit_evidence_id, "permit_evidence_id", 240),
            "readback_evidence_id": self._optional(readback_evidence_id, "readback_evidence_id", 240),
            "kill_switch_sequence": self._positive_int_or_none(
                kill_switch_sequence,
                "kill_switch_sequence",
            ),
            "kill_switch_state_id": self._optional(
                kill_switch_state_id,
                "kill_switch_state_id",
                240,
            ),
            "kill_switch_evidence_id": self._optional(
                kill_switch_evidence_id,
                "kill_switch_evidence_id",
                240,
            ),
            "compensation_plan_id": self._optional(
                compensation_plan_id,
                "compensation_plan_id",
                240,
            ),
            "compensation_evidence_id": self._optional(
                compensation_evidence_id,
                "compensation_evidence_id",
                240,
            ),
        }
        if event_type in self.GOVERNED_EVENTS:
            if any(value is None for value in governance.values()):
                raise ValueError(
                    "Governed authorization events require Approval, "
                    "one-time command Permit, receipt Readback, "
                    "Kill Switch authority and Compensation plan"
                )
            if readback_outcome != "succeeded":
                raise ValueError("Governed authorization event requires succeeded readback")
        elif any(value is not None for value in governance.values()):
            raise ValueError("Governance bindings are only valid on governed events")
        replay = self._idempotent_event_replay(
            context=context,
            source_event_ref=source_event_ref,
            sequence=sequence,
            event_type=event_type,
            authorization_source=authorization_source,
            platform=platform,
            account_ref=account_ref,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            role_ref=role_ref,
            subaccount_ref=subaccount_ref,
            credential_kind=credential_kind,
            capabilities=capabilities,
            secret_reference_sha256=secret_reference_sha256,
            credential_fingerprint_sha256=(credential_fingerprint_sha256),
            health_status=health_status,
            readback_outcome=readback_outcome,
            rate_limit_state=rate_limit_state,
            external_schema_version=external_schema_version,
            consent_evidence_id=consent_evidence_id,
            evidence_id=evidence_id,
            governance=governance,
            effective_at=effective,
            expires_at=expires,
            verified_at=verified,
        )
        if replay is not None:
            return replay
        consent = self._require_consent_evidence(
            evidence_id=consent_evidence_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
            platform=platform,
            account_ref=account_ref,
            adapter=contract,
            authorization_source=authorization_source,
            credential_kind=credential_kind,
            capabilities=capabilities,
            role_ref=role_ref,
            subaccount_ref=subaccount_ref,
        )
        authorization_payload = self._authorization_payload(
            context=context,
            source_event_ref=source_event_ref,
            sequence=sequence,
            event_type=event_type,
            authorization_source=authorization_source,
            platform=platform,
            account_ref=account_ref,
            adapter=contract,
            credential_kind=credential_kind,
            capabilities=capabilities,
            role_ref=role_ref,
            subaccount_ref=subaccount_ref,
            secret_reference_sha256=secret_reference_sha256,
            credential_fingerprint_sha256=(credential_fingerprint_sha256),
            health_status=health_status,
            readback_outcome=readback_outcome,
            rate_limit_state=rate_limit_state,
            external_schema_version=external_schema_version,
            effective_at=effective,
            expires_at=expires,
            verified_at=verified,
            observation_as_of=context["cutoff"],
        )
        source = self._require_source_evidence(
            evidence_id=evidence_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
            source_event_ref=source_event_ref,
            sequence=sequence,
            event_type=event_type,
            platform=platform,
            account_ref=account_ref,
            adapter=contract,
            authorization_source=authorization_source,
            credential_kind=credential_kind,
            capabilities=capabilities,
            role_ref=role_ref,
            subaccount_ref=subaccount_ref,
            secret_reference_sha256=secret_reference_sha256,
            credential_fingerprint_sha256=(credential_fingerprint_sha256),
            health_status=health_status,
            readback_outcome=readback_outcome,
            rate_limit_state=rate_limit_state,
            external_schema_version=external_schema_version,
            effective_at=effective,
            expires_at=expires,
            verified_at=verified,
            observation_as_of=context["cutoff"],
            authorization_payload=authorization_payload,
            consent_evidence=consent,
            governance=governance,
        )
        if event_type in self.GOVERNED_EVENTS:
            self._require_governance(
                event_type=event_type,
                governance=governance,
                source_event_ref=source_event_ref,
                platform=platform,
                account_ref=account_ref,
                adapter=contract,
                effective_at=effective,
                context=context,
                principal=principal,
                entity_scope=entity_scope,
                source_evidence=source,
                authorization_payload=authorization_payload,
            )
        payload = {
            "contract_id": self.EVENT_CONTRACT_ID,
            "source_event_ref": source_event_ref,
            "sequence": sequence,
            "event_type": event_type,
            "authorization_source": authorization_source,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "adapter_contract_sha256": contract["contract_sha256"],
            "role_ref": role_ref,
            "subaccount_ref": subaccount_ref,
            "credential_kind": credential_kind,
            "capabilities": capabilities,
            "secret_reference_sha256": secret_reference_sha256,
            "credential_fingerprint_sha256": (credential_fingerprint_sha256),
            "health_status": health_status,
            "readback_outcome": readback_outcome,
            "rate_limit_state": rate_limit_state,
            "external_schema_version": external_schema_version,
            "consent_evidence_id": consent.id,
            "consent_evidence_sha256": consent.sha256,
            "evidence_id": source.id,
            "source_evidence_sha256": source.sha256,
            **governance,
            "effective_at": effective.isoformat(),
            "expires_at": expires.isoformat(),
            "verified_at": verified.isoformat(),
            "scope": context["scope"],
        }
        payload_sha256 = self._hash(payload)
        source_payload_sha256 = str(source.metadata.get("event_payload_sha256") or "").lower()
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(
                select(ChannelAccountAuthorizationEventRow).where(
                    ChannelAccountAuthorizationEventRow.tenant_ref == context["scope"]["tenant_ref"],
                    ChannelAccountAuthorizationEventRow.entity_ref == context["scope"]["entity_ref"],
                    ChannelAccountAuthorizationEventRow.store_ref == context["scope"]["store_ref"],
                    ChannelAccountAuthorizationEventRow.source_event_ref == source_event_ref,
                )
            )
            if existing is not None:
                if existing.payload_sha256 != payload_sha256:
                    raise ValueError("Authorization source event conflicts with immutable values")
                return self._event(existing, idempotent=True)
            latest = session.scalar(
                select(ChannelAccountAuthorizationEventRow)
                .where(
                    ChannelAccountAuthorizationEventRow.tenant_ref == context["scope"]["tenant_ref"],
                    ChannelAccountAuthorizationEventRow.entity_ref == context["scope"]["entity_ref"],
                    ChannelAccountAuthorizationEventRow.store_ref == context["scope"]["store_ref"],
                    ChannelAccountAuthorizationEventRow.platform == platform,
                    ChannelAccountAuthorizationEventRow.account_ref == account_ref,
                    ChannelAccountAuthorizationEventRow.adapter_id == adapter_id,
                )
                .order_by(
                    ChannelAccountAuthorizationEventRow.sequence.desc(),
                    ChannelAccountAuthorizationEventRow.id.desc(),
                )
                .limit(1)
                .with_for_update()
            )
            self._validate_transition(
                latest=latest,
                sequence=sequence,
                event_type=event_type,
                effective_at=effective,
                capabilities=capabilities,
                role_ref=role_ref,
                subaccount_ref=subaccount_ref,
                secret_reference_sha256=secret_reference_sha256,
                credential_fingerprint_sha256=(credential_fingerprint_sha256),
                adapter_version=adapter_version,
                external_schema_version=external_schema_version,
                scope_grant_authority_sha256=context["scope"]["scope_grant_authority_sha256"],
            )
            row = ChannelAccountAuthorizationEventRow(
                id=new_id("caev"),
                source_event_ref=source_event_ref,
                sequence=sequence,
                event_type=event_type,
                authorization_source=authorization_source,
                platform=platform,
                account_ref=account_ref,
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                role_ref=role_ref,
                subaccount_ref=subaccount_ref,
                credential_kind=credential_kind,
                capabilities_json=capabilities,
                secret_reference=secret_reference,
                secret_reference_sha256=secret_reference_sha256,
                credential_fingerprint_sha256=(credential_fingerprint_sha256),
                health_status=health_status,
                readback_outcome=readback_outcome,
                rate_limit_state=rate_limit_state,
                external_schema_version=external_schema_version,
                consent_evidence_id=consent.id,
                evidence_id=source.id,
                adapter_contract_sha256=contract["contract_sha256"],
                consent_evidence_sha256=consent.sha256,
                source_evidence_sha256=source.sha256,
                source_payload_sha256=source_payload_sha256,
                payload_sha256=payload_sha256,
                effective_at=effective,
                expires_at=expires,
                verified_at=verified,
                recorded_at=datetime.now(UTC),
                created_by=principal.actor_id,
                scope_as_of=context["cutoff"],
                **governance,
                **context["scope"],
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                concurrent_replay = self._idempotent_event_replay(
                    context=context,
                    source_event_ref=source_event_ref,
                    sequence=sequence,
                    event_type=event_type,
                    authorization_source=authorization_source,
                    platform=platform,
                    account_ref=account_ref,
                    adapter_id=adapter_id,
                    adapter_version=adapter_version,
                    role_ref=role_ref,
                    subaccount_ref=subaccount_ref,
                    credential_kind=credential_kind,
                    capabilities=capabilities,
                    secret_reference_sha256=secret_reference_sha256,
                    credential_fingerprint_sha256=(credential_fingerprint_sha256),
                    health_status=health_status,
                    readback_outcome=readback_outcome,
                    rate_limit_state=rate_limit_state,
                    external_schema_version=external_schema_version,
                    consent_evidence_id=consent_evidence_id,
                    evidence_id=evidence_id,
                    governance=governance,
                    effective_at=effective,
                    expires_at=expires,
                    verified_at=verified,
                )
                if concurrent_replay is not None:
                    return concurrent_replay
                raise ValueError("Concurrent channel account event conflict; retry") from exc
            return self._event(row, idempotent=False)

    def _committed_event_replay_before_dependencies(
        self,
        *,
        context: dict[str, Any],
        source_event_ref: str,
        sequence: int,
        event_type: str,
        authorization_source: str,
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        credential_kind: str,
        capabilities: list[str],
        secret_reference: str,
        credential_fingerprint_sha256: str,
        health_status: str,
        readback_outcome: str,
        rate_limit_state: str,
        external_schema_version: str,
        consent_evidence_id: str,
        evidence_id: str,
        effective_at: str,
        expires_at: str,
        verified_at: str,
        role_ref: str | None,
        subaccount_ref: str | None,
        approval_id: str | None,
        command_id: str | None,
        receipt_id: str | None,
        permit_evidence_id: str | None,
        readback_evidence_id: str | None,
        kill_switch_sequence: int | None,
        kill_switch_state_id: str | None,
        kill_switch_evidence_id: str | None,
        compensation_plan_id: str | None,
        compensation_evidence_id: str | None,
    ) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            existing = session.scalar(
                select(ChannelAccountAuthorizationEventRow).where(
                    ChannelAccountAuthorizationEventRow.tenant_ref == context["scope"]["tenant_ref"],
                    ChannelAccountAuthorizationEventRow.entity_ref == context["scope"]["entity_ref"],
                    ChannelAccountAuthorizationEventRow.store_ref == context["scope"]["store_ref"],
                    ChannelAccountAuthorizationEventRow.source_event_ref == source_event_ref,
                )
            )
        if existing is None:
            return None
        requested_capabilities = self._replay_capabilities(capabilities)
        requested = {
            "sequence": sequence,
            "event_type": self._choice(event_type, "event_type", self.EVENT_TYPES),
            "authorization_source": self._choice(
                authorization_source,
                "authorization_source",
                frozenset({"official", "explicit_written_authorization"}),
            ),
            "platform": self._required(platform, "platform", 80).lower(),
            "account_ref": self._required(account_ref, "account_ref", 240),
            "adapter_id": self._required(adapter_id, "adapter_id", 160),
            "adapter_version": self._required(adapter_version, "adapter_version", 80),
            "credential_kind": self._required(credential_kind, "credential_kind", 80),
            "capabilities_json": requested_capabilities,
            "secret_reference_sha256": self._hash_text(self._secret_reference(secret_reference)),
            "credential_fingerprint_sha256": self._sha256_value(
                credential_fingerprint_sha256,
                "credential_fingerprint_sha256",
            ),
            "health_status": self._choice(health_status, "health_status", self.HEALTH_STATES),
            "readback_outcome": self._choice(
                readback_outcome,
                "readback_outcome",
                self.READBACK_OUTCOMES,
            ),
            "rate_limit_state": self._choice(
                rate_limit_state,
                "rate_limit_state",
                self.RATE_LIMIT_STATES,
            ),
            "external_schema_version": self._required(external_schema_version, "external_schema_version", 80),
            "consent_evidence_id": self._required(consent_evidence_id, "consent_evidence_id", 240),
            "evidence_id": self._required(evidence_id, "evidence_id", 240),
            "effective_at": parse_timestamp(effective_at, "effective_at"),
            "expires_at": parse_timestamp(expires_at, "expires_at"),
            "verified_at": parse_timestamp(verified_at, "verified_at"),
            "role_ref": self._optional(role_ref, "role_ref", 160),
            "subaccount_ref": self._optional(subaccount_ref, "subaccount_ref", 240),
            "approval_id": self._optional(approval_id, "approval_id", 240),
            "command_id": self._optional(command_id, "command_id", 240),
            "receipt_id": self._optional(receipt_id, "receipt_id", 240),
            "permit_evidence_id": self._optional(permit_evidence_id, "permit_evidence_id", 240),
            "readback_evidence_id": self._optional(readback_evidence_id, "readback_evidence_id", 240),
            "kill_switch_sequence": self._positive_int_or_none(kill_switch_sequence, "kill_switch_sequence"),
            "kill_switch_state_id": self._optional(kill_switch_state_id, "kill_switch_state_id", 240),
            "kill_switch_evidence_id": self._optional(kill_switch_evidence_id, "kill_switch_evidence_id", 240),
            "compensation_plan_id": self._optional(compensation_plan_id, "compensation_plan_id", 240),
            "compensation_evidence_id": self._optional(
                compensation_evidence_id,
                "compensation_evidence_id",
                240,
            ),
        }
        for field, value in requested.items():
            actual = getattr(existing, field)
            if field in {"effective_at", "expires_at", "verified_at"}:
                actual = self._aware(actual)
            elif field == "capabilities_json":
                actual = sorted(actual)
            if actual != value:
                raise ValueError("Authorization source event conflicts with immutable values")
        return self._event(existing, idempotent=True)

    @classmethod
    def _replay_capabilities(cls, values: Any) -> list[str]:
        if (
            not isinstance(values, list)
            or not values
            or len(values) > 100
            or not all(isinstance(value, str) and 0 < len(value.strip()) <= 160 for value in values)
        ):
            raise ValueError("capabilities must be a bounded string list")
        normalized = sorted({value.strip() for value in values})
        if len(normalized) != len(values):
            raise ValueError("capabilities contain duplicates")
        return normalized

    def _idempotent_event_replay(
        self,
        *,
        context: dict[str, Any],
        source_event_ref: str,
        sequence: int,
        event_type: str,
        authorization_source: str,
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        role_ref: str | None,
        subaccount_ref: str | None,
        credential_kind: str,
        capabilities: list[str],
        secret_reference_sha256: str,
        credential_fingerprint_sha256: str,
        health_status: str,
        readback_outcome: str,
        rate_limit_state: str,
        external_schema_version: str,
        consent_evidence_id: str,
        evidence_id: str,
        governance: dict[str, Any],
        effective_at: datetime,
        expires_at: datetime,
        verified_at: datetime,
    ) -> dict[str, Any] | None:
        scope = context["scope"]
        with Session(self.engine) as session:
            existing = session.scalar(
                select(ChannelAccountAuthorizationEventRow).where(
                    ChannelAccountAuthorizationEventRow.tenant_ref == scope["tenant_ref"],
                    ChannelAccountAuthorizationEventRow.entity_ref == scope["entity_ref"],
                    ChannelAccountAuthorizationEventRow.store_ref == scope["store_ref"],
                    ChannelAccountAuthorizationEventRow.source_event_ref == source_event_ref,
                )
            )
        if existing is None:
            return None
        expected = {
            "sequence": sequence,
            "event_type": event_type,
            "authorization_source": authorization_source,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "role_ref": role_ref,
            "subaccount_ref": subaccount_ref,
            "credential_kind": credential_kind,
            "capabilities_json": sorted(capabilities),
            "secret_reference_sha256": secret_reference_sha256,
            "credential_fingerprint_sha256": (credential_fingerprint_sha256),
            "health_status": health_status,
            "readback_outcome": readback_outcome,
            "rate_limit_state": rate_limit_state,
            "external_schema_version": external_schema_version,
            "consent_evidence_id": consent_evidence_id,
            "evidence_id": evidence_id,
            "effective_at": self._aware(effective_at),
            "expires_at": self._aware(expires_at),
            "verified_at": self._aware(verified_at),
            "scope_grant_authority_sha256": scope["scope_grant_authority_sha256"],
            **governance,
        }
        for field, value in expected.items():
            actual = getattr(existing, field)
            if field in {
                "effective_at",
                "expires_at",
                "verified_at",
            }:
                actual = self._aware(actual)
            elif field == "capabilities_json":
                actual = sorted(actual)
            if actual != value:
                raise ValueError("Authorization source event conflicts with immutable values")
        return self._event(existing, idempotent=True)

    def read_scoped_sources(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
        platform: str | None = None,
        account_ref: str | None = None,
        adapter_id: str | None = None,
        max_events: int = 50_000,
    ) -> dict[str, Any]:
        context = self._read_context(
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            scope_grant_authority_sha256=(scope_grant_authority_sha256),
            as_of=as_of,
        )
        if not 1 <= max_events <= 100_000:
            raise ValueError("max_events must be between 1 and 100000")
        query = select(ChannelAccountAuthorizationEventRow).where(
            ChannelAccountAuthorizationEventRow.tenant_ref == context["scope"]["tenant_ref"],
            ChannelAccountAuthorizationEventRow.entity_ref == context["scope"]["entity_ref"],
            ChannelAccountAuthorizationEventRow.store_ref == context["scope"]["store_ref"],
            ChannelAccountAuthorizationEventRow.scope_grant_authority_sha256
            == context["scope"]["scope_grant_authority_sha256"],
            ChannelAccountAuthorizationEventRow.effective_at <= context["cutoff"],
            ChannelAccountAuthorizationEventRow.recorded_at <= context["cutoff"],
            ChannelAccountAuthorizationEventRow.scope_as_of <= context["cutoff"],
        )
        filters = {
            ChannelAccountAuthorizationEventRow.platform: platform,
            ChannelAccountAuthorizationEventRow.account_ref: account_ref,
            ChannelAccountAuthorizationEventRow.adapter_id: adapter_id,
        }
        for column, value in filters.items():
            normalized = str(value or "").strip()
            if normalized:
                query = query.where(column == normalized)
        query = query.order_by(
            ChannelAccountAuthorizationEventRow.platform,
            ChannelAccountAuthorizationEventRow.account_ref,
            ChannelAccountAuthorizationEventRow.adapter_id,
            ChannelAccountAuthorizationEventRow.sequence,
            ChannelAccountAuthorizationEventRow.id,
        ).limit(max_events + 1)
        with Session(self.engine) as session:
            rows = list(session.scalars(query).all())
        payload = {
            "contract_id": self.SOURCE_CONTRACT_ID,
            "status": "ready" if rows else "no_data",
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "events": [self._event_source(row) for row in rows[:max_events]],
            "truncated": len(rows) > max_events,
            "source_gaps": ([] if rows else ["channel_account_binding_missing"]),
            "control_envelope": {
                "append_only_authority": True,
                "secret_reference_returned": False,
                "plaintext_secret_stored": False,
                "cookie_allowed": False,
                "internal_token_allowed": False,
                "device_session_allowed": False,
                "private_endpoint_allowed": False,
                "captcha_bypass_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def validate_event(
        self,
        *,
        event: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, Any],
        as_of: datetime,
    ) -> list[str]:
        context = {
            "cutoff": self._aware(as_of),
            "scope": {
                key: scope[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                    "scope_grant_authority_sha256",
                )
            },
        }
        contract = self.adapters.resolve(
            platform=str(event.get("platform") or ""),
            adapter_id=str(event.get("adapter_id") or ""),
            adapter_version=str(event.get("adapter_version") or ""),
            as_of=context["cutoff"],
        )
        governance = {
            field: event.get(field)
            for field in (
                "approval_id",
                "command_id",
                "receipt_id",
                "permit_evidence_id",
                "readback_evidence_id",
                "kill_switch_sequence",
                "kill_switch_state_id",
                "kill_switch_evidence_id",
                "compensation_plan_id",
                "compensation_evidence_id",
            )
        }
        consent = self._require_consent_evidence(
            evidence_id=str(event.get("consent_evidence_id") or ""),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
            platform=str(event.get("platform") or ""),
            account_ref=str(event.get("account_ref") or ""),
            adapter=contract,
            authorization_source=str(event.get("authorization_source") or ""),
            credential_kind=str(event.get("credential_kind") or ""),
            capabilities=list(event.get("capabilities") or []),
            role_ref=event.get("role_ref"),
            subaccount_ref=event.get("subaccount_ref"),
        )
        authorization_payload = self._authorization_payload(
            context=context,
            source_event_ref=str(event.get("source_event_ref") or ""),
            sequence=int(event.get("sequence") or 0),
            event_type=str(event.get("event_type") or ""),
            authorization_source=str(event.get("authorization_source") or ""),
            platform=str(event.get("platform") or ""),
            account_ref=str(event.get("account_ref") or ""),
            adapter=contract,
            credential_kind=str(event.get("credential_kind") or ""),
            capabilities=list(event.get("capabilities") or []),
            role_ref=event.get("role_ref"),
            subaccount_ref=event.get("subaccount_ref"),
            secret_reference_sha256=str(event.get("secret_reference_sha256") or ""),
            credential_fingerprint_sha256=str(event.get("credential_fingerprint_sha256") or ""),
            health_status=str(event.get("health_status") or ""),
            readback_outcome=str(event.get("readback_outcome") or ""),
            rate_limit_state=str(event.get("rate_limit_state") or ""),
            external_schema_version=str(event.get("external_schema_version") or ""),
            effective_at=parse_timestamp(
                str(event.get("effective_at") or ""),
                "effective_at",
            ),
            expires_at=parse_timestamp(
                str(event.get("expires_at") or ""),
                "expires_at",
            ),
            verified_at=parse_timestamp(
                str(event.get("verified_at") or ""),
                "verified_at",
            ),
            observation_as_of=parse_timestamp(
                str(event.get("scope_as_of") or ""),
                "scope_as_of",
            ),
        )
        source = self._require_source_evidence(
            evidence_id=str(event.get("evidence_id") or ""),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
            source_event_ref=str(event.get("source_event_ref") or ""),
            sequence=int(event.get("sequence") or 0),
            event_type=str(event.get("event_type") or ""),
            platform=str(event.get("platform") or ""),
            account_ref=str(event.get("account_ref") or ""),
            adapter=contract,
            authorization_source=str(event.get("authorization_source") or ""),
            credential_kind=str(event.get("credential_kind") or ""),
            capabilities=list(event.get("capabilities") or []),
            role_ref=event.get("role_ref"),
            subaccount_ref=event.get("subaccount_ref"),
            secret_reference_sha256=str(event.get("secret_reference_sha256") or ""),
            credential_fingerprint_sha256=str(event.get("credential_fingerprint_sha256") or ""),
            health_status=str(event.get("health_status") or ""),
            readback_outcome=str(event.get("readback_outcome") or ""),
            rate_limit_state=str(event.get("rate_limit_state") or ""),
            external_schema_version=str(event.get("external_schema_version") or ""),
            effective_at=parse_timestamp(
                str(event.get("effective_at") or ""),
                "effective_at",
            ),
            expires_at=parse_timestamp(
                str(event.get("expires_at") or ""),
                "expires_at",
            ),
            verified_at=parse_timestamp(
                str(event.get("verified_at") or ""),
                "verified_at",
            ),
            observation_as_of=parse_timestamp(
                str(event.get("scope_as_of") or ""),
                "scope_as_of",
            ),
            authorization_payload=authorization_payload,
            consent_evidence=consent,
            governance=governance,
        )
        if event.get("event_type") in self.GOVERNED_EVENTS:
            self._require_governance(
                event_type=str(event["event_type"]),
                governance=governance,
                source_event_ref=str(event.get("source_event_ref") or ""),
                platform=str(event.get("platform") or ""),
                account_ref=str(event.get("account_ref") or ""),
                adapter=contract,
                effective_at=parse_timestamp(
                    str(event.get("effective_at") or ""),
                    "effective_at",
                ),
                context=context,
                principal=principal,
                entity_scope=entity_scope,
                source_evidence=source,
                exclude_source_event_ref=str(event.get("source_event_ref") or ""),
                authorization_payload=authorization_payload,
            )
        payload = {
            "contract_id": self.EVENT_CONTRACT_ID,
            **{
                field: event.get(field)
                for field in (
                    "source_event_ref",
                    "sequence",
                    "event_type",
                    "authorization_source",
                    "platform",
                    "account_ref",
                    "adapter_id",
                    "adapter_version",
                    "adapter_contract_sha256",
                    "role_ref",
                    "subaccount_ref",
                    "credential_kind",
                    "capabilities",
                    "secret_reference_sha256",
                    "credential_fingerprint_sha256",
                    "health_status",
                    "readback_outcome",
                    "rate_limit_state",
                    "external_schema_version",
                    "consent_evidence_id",
                    "consent_evidence_sha256",
                    "evidence_id",
                    "source_evidence_sha256",
                    "effective_at",
                    "expires_at",
                    "verified_at",
                )
            },
            **governance,
            "scope": context["scope"],
        }
        issues = []
        if contract["contract_sha256"] != event.get("adapter_contract_sha256"):
            issues.append("channel_account_adapter_contract_drift")
        if self._hash(payload) != event.get("payload_sha256"):
            issues.append("channel_account_payload_hash_drift")
        if source.sha256 != event.get("source_evidence_sha256"):
            issues.append("channel_account_source_evidence_hash_drift")
        if consent.sha256 != event.get("consent_evidence_sha256"):
            issues.append("channel_account_consent_evidence_hash_drift")
        if source.metadata.get("event_payload_sha256") != event.get("source_payload_sha256"):
            issues.append("channel_account_source_payload_hash_drift")
        return issues

    def _validate_transition(
        self,
        *,
        latest: ChannelAccountAuthorizationEventRow | None,
        sequence: int,
        event_type: str,
        effective_at: datetime,
        capabilities: list[str],
        role_ref: str | None,
        subaccount_ref: str | None,
        secret_reference_sha256: str,
        credential_fingerprint_sha256: str,
        adapter_version: str,
        external_schema_version: str,
        scope_grant_authority_sha256: str,
    ) -> None:
        expected = 1 if latest is None else latest.sequence + 1
        if sequence != expected:
            raise ValueError(f"Channel account sequence must be {expected}")
        if latest is None:
            if event_type != "authorization_granted":
                raise ValueError("First channel account event must be a grant")
            return
        latest_effective = self._aware(latest.effective_at)
        if effective_at < latest_effective:
            raise ValueError("Channel account event time moved backwards")
        scope_epoch_changed = latest.scope_grant_authority_sha256 != scope_grant_authority_sha256
        active = latest.event_type not in {
            "authorization_revoked",
            "authorization_expired",
            "unknown_outcome_observed",
            "schema_drift_observed",
        }
        if event_type == "authorization_granted" and active and not scope_epoch_changed:
            raise ValueError("Duplicate active authorization grant is not allowed")
        if not active and event_type != "authorization_granted":
            raise ValueError("Revoked, expired or unknown authority requires a new governed grant")
        if event_type != "authorization_granted":
            if adapter_version != latest.adapter_version:
                raise ValueError("Adapter version drift requires a new governed grant")
            if role_ref != latest.role_ref:
                raise ValueError("Role drift requires a new governed grant")
            if subaccount_ref != latest.subaccount_ref:
                raise ValueError("Subaccount drift requires a new governed grant")
            if not set(capabilities).issubset(set(latest.capabilities_json)):
                raise ValueError("Authorization capability scope expansion is forbidden")
            changed_reference = secret_reference_sha256 != latest.secret_reference_sha256
            changed_fingerprint = credential_fingerprint_sha256 != latest.credential_fingerprint_sha256
            if event_type == "credential_rotated":
                if not changed_reference or not changed_fingerprint:
                    raise ValueError("Credential rotation must change both reference and fingerprint")
            elif changed_reference or changed_fingerprint:
                raise ValueError("Secret reference or fingerprint changed outside credential rotation")
            if external_schema_version != latest.external_schema_version and event_type != "schema_drift_observed":
                raise ValueError("External schema drift requires an explicit blocked observation")

    def _require_consent_evidence(
        self,
        *,
        evidence_id: str,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        platform: str,
        account_ref: str,
        adapter: dict[str, Any],
        authorization_source: str,
        credential_kind: str,
        capabilities: list[str],
        role_ref: str | None,
        subaccount_ref: str | None,
    ):
        record = self._require_exact_evidence(
            evidence_id=evidence_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        self._require_reviewed_evidence(
            record=record,
            purpose="consent",
            context=context,
        )
        metadata = record.metadata
        self._reject_sensitive_metadata(metadata)
        if (
            metadata.get("contract_id") != self.CONSENT_EVIDENCE_CONTRACT_ID
            or metadata.get("status") != "authorized"
            or metadata.get("revoked") is not False
            or metadata.get("immutable") is not True
            or metadata.get("authorization_source") != authorization_source
            or metadata.get("platform") != platform
            or metadata.get("account_ref") != account_ref
            or metadata.get("adapter_id") != adapter["adapter_id"]
            or metadata.get("adapter_version") != adapter["adapter_version"]
            or metadata.get("credential_kind") != credential_kind
            or sorted(metadata.get("allowed_capabilities") or []) != capabilities
            or metadata.get("role_ref") != role_ref
            or metadata.get("subaccount_ref") != subaccount_ref
            or not str(metadata.get("consent_owner") or "").strip()
            or metadata.get("tenant_ref") != context["scope"]["tenant_ref"]
            or metadata.get("entity_ref") != context["scope"]["entity_ref"]
            or metadata.get("store_ref") != context["scope"]["store_ref"]
        ):
            raise ValueError("Channel account consent Evidence is invalid")
        return record

    def _require_source_evidence(
        self,
        *,
        evidence_id: str,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        source_event_ref: str,
        sequence: int,
        event_type: str,
        platform: str,
        account_ref: str,
        adapter: dict[str, Any],
        authorization_source: str,
        credential_kind: str,
        capabilities: list[str],
        role_ref: str | None,
        subaccount_ref: str | None,
        secret_reference_sha256: str,
        credential_fingerprint_sha256: str,
        health_status: str,
        readback_outcome: str,
        rate_limit_state: str,
        external_schema_version: str,
        effective_at: datetime,
        expires_at: datetime,
        verified_at: datetime,
        observation_as_of: datetime,
        authorization_payload: dict[str, Any],
        consent_evidence,
        governance: dict[str, Any],
    ):
        record = self._require_exact_evidence(
            evidence_id=evidence_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        self._require_reviewed_evidence(
            record=record,
            purpose="lifecycle",
            context=context,
        )
        metadata = record.metadata
        self._reject_sensitive_metadata(metadata)
        observation = self._observation_payload(
            context=context,
            source_event_ref=source_event_ref,
            sequence=sequence,
            event_type=event_type,
            authorization_source=authorization_source,
            platform=platform,
            account_ref=account_ref,
            adapter=adapter,
            credential_kind=credential_kind,
            capabilities=capabilities,
            role_ref=role_ref,
            subaccount_ref=subaccount_ref,
            secret_reference_sha256=secret_reference_sha256,
            credential_fingerprint_sha256=(credential_fingerprint_sha256),
            health_status=health_status,
            readback_outcome=readback_outcome,
            rate_limit_state=rate_limit_state,
            external_schema_version=external_schema_version,
            consent_evidence=consent_evidence,
            governance=governance,
            effective_at=effective_at,
            expires_at=expires_at,
            verified_at=verified_at,
            observation_as_of=observation_as_of,
            authorization_payload=authorization_payload,
        )
        canonical_content = self._canonical_bytes(observation)
        content, _ = self.evidence.content(record.id)
        observation_sha256 = hashlib.sha256(canonical_content).hexdigest()
        if (
            metadata.get("contract_id") != self.SOURCE_EVIDENCE_CONTRACT_ID
            or metadata.get("immutable") is not True
            or metadata.get("revoked") is not False
            or metadata.get("authorization_source") != authorization_source
            or metadata.get("source_event_ref") != source_event_ref
            or metadata.get("sequence") != sequence
            or metadata.get("event_type") != event_type
            or metadata.get("platform") != platform
            or metadata.get("account_ref") != account_ref
            or metadata.get("adapter_id") != adapter["adapter_id"]
            or metadata.get("adapter_version") != adapter["adapter_version"]
            or metadata.get("adapter_contract_sha256") != adapter["contract_sha256"]
            or metadata.get("credential_kind") != credential_kind
            or sorted(metadata.get("capabilities") or []) != capabilities
            or metadata.get("role_ref") != role_ref
            or metadata.get("subaccount_ref") != subaccount_ref
            or metadata.get("secret_reference_sha256") != secret_reference_sha256
            or metadata.get("credential_fingerprint_sha256") != credential_fingerprint_sha256
            or metadata.get("consent_evidence_id") != consent_evidence.id
            or metadata.get("consent_evidence_sha256") != consent_evidence.sha256
            or metadata.get("tenant_ref") != context["scope"]["tenant_ref"]
            or metadata.get("entity_ref") != context["scope"]["entity_ref"]
            or metadata.get("store_ref") != context["scope"]["store_ref"]
            or metadata.get("observation_contract_id") != observation["contract_id"]
            or metadata.get("observation_schema_version") != observation["schema_version"]
            or metadata.get("event_payload_sha256") != observation_sha256
            or record.sha256 != observation_sha256
            or content != canonical_content
        ):
            raise ValueError("Channel account lifecycle Evidence is invalid")
        for field, value in governance.items():
            if metadata.get(field) != value:
                raise ValueError("Channel account lifecycle governance binding drift")
        return record

    def _authorization_payload(
        self,
        *,
        context: dict[str, Any],
        source_event_ref: str,
        sequence: int,
        event_type: str,
        authorization_source: str,
        platform: str,
        account_ref: str,
        adapter: dict[str, Any],
        credential_kind: str,
        capabilities: list[str],
        role_ref: str | None,
        subaccount_ref: str | None,
        secret_reference_sha256: str,
        credential_fingerprint_sha256: str,
        health_status: str,
        readback_outcome: str,
        rate_limit_state: str,
        external_schema_version: str,
        effective_at: datetime,
        expires_at: datetime,
        verified_at: datetime,
        observation_as_of: datetime,
    ) -> dict[str, Any]:
        return {
            "contract_id": ("kjds-channel-account-canonical-authority-v1"),
            "schema_version": "1",
            "source_event_ref": source_event_ref,
            "sequence": sequence,
            "event_type": event_type,
            "authorization_source": authorization_source,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "adapter_contract_sha256": adapter["contract_sha256"],
            "role_ref": role_ref,
            "subaccount_ref": subaccount_ref,
            "credential_kind": credential_kind,
            "capabilities": sorted(capabilities),
            "secret_reference_sha256": secret_reference_sha256,
            "credential_fingerprint_sha256": (credential_fingerprint_sha256),
            "health_status": health_status,
            "readback_outcome": readback_outcome,
            "rate_limit_state": rate_limit_state,
            "external_schema_version": external_schema_version,
            "effective_at": self._aware(effective_at).isoformat(),
            "expires_at": self._aware(expires_at).isoformat(),
            "verified_at": self._aware(verified_at).isoformat(),
            "scope": {
                **context["scope"],
                "as_of": self._aware(observation_as_of).isoformat(),
            },
        }

    def _observation_payload(
        self,
        *,
        context: dict[str, Any],
        source_event_ref: str,
        sequence: int,
        event_type: str,
        authorization_source: str,
        platform: str,
        account_ref: str,
        adapter: dict[str, Any],
        credential_kind: str,
        capabilities: list[str],
        role_ref: str | None,
        subaccount_ref: str | None,
        secret_reference_sha256: str,
        credential_fingerprint_sha256: str,
        health_status: str,
        readback_outcome: str,
        rate_limit_state: str,
        external_schema_version: str,
        consent_evidence,
        governance: dict[str, Any],
        effective_at: datetime,
        expires_at: datetime,
        verified_at: datetime,
        observation_as_of: datetime,
        authorization_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "contract_id": ("kjds-channel-account-canonical-observation-v1"),
            "schema_version": "1",
            "source_event_ref": source_event_ref,
            "sequence": sequence,
            "event_type": event_type,
            "authorization_source": authorization_source,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "adapter_contract_sha256": adapter["contract_sha256"],
            "role_ref": role_ref,
            "subaccount_ref": subaccount_ref,
            "credential_kind": credential_kind,
            "capabilities": sorted(capabilities),
            "secret_reference_sha256": secret_reference_sha256,
            "credential_fingerprint_sha256": (credential_fingerprint_sha256),
            "health_status": health_status,
            "readback_outcome": readback_outcome,
            "rate_limit_state": rate_limit_state,
            "external_schema_version": external_schema_version,
            "consent_evidence_id": consent_evidence.id,
            "consent_evidence_sha256": consent_evidence.sha256,
            "governance": dict(governance),
            "effective_at": self._aware(effective_at).isoformat(),
            "expires_at": self._aware(expires_at).isoformat(),
            "verified_at": self._aware(verified_at).isoformat(),
            "scope": {
                **context["scope"],
                "as_of": self._aware(observation_as_of).isoformat(),
            },
            "authorization": authorization_payload,
        }

    def _require_governance(
        self,
        *,
        event_type: str,
        governance: dict[str, str | None],
        source_event_ref: str,
        platform: str,
        account_ref: str,
        adapter: dict[str, Any],
        effective_at: datetime,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        source_evidence,
        authorization_payload: dict[str, Any],
        exclude_source_event_ref: str | None = None,
    ) -> None:
        action_id = self.ACTION_IDS[event_type]
        scope = context["scope"]
        changes_authorization = event_type != "external_verification_readback"
        with Session(self.engine) as session:
            previous_row = self._previous_physical_authorization(
                session=session,
                scope=scope,
                platform=platform,
                account_ref=account_ref,
                adapter_id=adapter["adapter_id"],
                before_sequence=int(authorization_payload["sequence"]),
                exclude_source_event_ref=(
                    exclude_source_event_ref or source_event_ref
                ),
            )
            approval = session.get(ApprovalRow, str(governance["approval_id"]))
            command = session.get(
                LimitedExecutionCommandRow,
                str(governance["command_id"]),
            )
            receipt = session.get(
                LimitedExecutionReceiptRow,
                str(governance["receipt_id"]),
            )
            execution_plan = session.get(ExecutionPlanRow, command.plan_id) if command is not None else None
            kill_switch_state = session.scalar(
                select(ChannelAccountKillSwitchStateRow)
                .where(
                    ChannelAccountKillSwitchStateRow.tenant_ref == scope["tenant_ref"],
                    ChannelAccountKillSwitchStateRow.entity_ref == scope["entity_ref"],
                    ChannelAccountKillSwitchStateRow.store_ref == scope["store_ref"],
                    ChannelAccountKillSwitchStateRow.platform == platform,
                    ChannelAccountKillSwitchStateRow.account_ref == account_ref,
                    ChannelAccountKillSwitchStateRow.adapter_id == adapter["adapter_id"],
                    ChannelAccountKillSwitchStateRow.action_id == action_id,
                    ChannelAccountKillSwitchStateRow.effective_at <= effective_at,
                    ChannelAccountKillSwitchStateRow.recorded_at <= context["cutoff"],
                    ChannelAccountKillSwitchStateRow.scope_as_of <= context["cutoff"],
                )
                .order_by(
                    ChannelAccountKillSwitchStateRow.effective_at.desc(),
                    ChannelAccountKillSwitchStateRow.sequence.desc(),
                    ChannelAccountKillSwitchStateRow.id.desc(),
                )
                .limit(1)
            )
            kill_switch = (
                session.get(
                    KillSwitchEventRow,
                    kill_switch_state.kill_switch_sequence,
                )
                if kill_switch_state is not None
                else None
            )
            canonical_kill_switch = session.scalar(
                select(KillSwitchEventRow)
                .where(KillSwitchEventRow.created_at <= effective_at)
                .order_by(KillSwitchEventRow.sequence.desc())
                .limit(1)
            )
            compensation_plan = session.get(
                ExecutionPlanRow,
                str(governance["compensation_plan_id"]),
            )
            compensation_approval = (
                session.get(
                    ApprovalRow,
                    compensation_plan.approval_id,
                )
                if compensation_plan is not None
                else None
            )
        previous_state = self._previous_authorization_state(
            row=previous_row,
            scope=scope,
            platform=platform,
            account_ref=account_ref,
            adapter_id=adapter["adapter_id"],
        )
        input_sha256 = self._hash(previous_state)
        output_sha256 = self._hash(authorization_payload)
        previous_binding = self._previous_authorization_binding(previous_row)
        self._require_previous_authorization_binding(
            previous_row=previous_row,
            previous_state=previous_state,
            previous_binding=previous_binding,
            input_sha256=input_sha256,
        )
        expected_input = {
            "contract_id": ("kjds-channel-account-governed-input-v2"),
            "previous_authorization": previous_state,
            "previous_authorization_binding": previous_binding,
            "proposed_authorization_sha256": output_sha256,
        }
        payload = approval.payload_json if approval is not None else {}
        if (
            approval is None
            or approval.status != "approved"
            or not approval.decided_by
            or approval.requested_by == approval.decided_by
            or approval.action != action_id
            or approval.resource_type != "channel_account"
            or approval.resource_id != account_ref
            or payload.get("tenant_ref") != scope["tenant_ref"]
            or payload.get("entity_ref") != scope["entity_ref"]
            or payload.get("store_ref") != scope["store_ref"]
            or payload.get("platform") != platform
            or payload.get("account_ref") != account_ref
            or payload.get("adapter_id") != adapter["adapter_id"]
            or payload.get("adapter_version") != adapter["adapter_version"]
            or payload.get("event_type") != event_type
            or payload.get("source_event_ref") != source_event_ref
            or payload.get("scope_grant_authority_sha256") != scope["scope_grant_authority_sha256"]
            or payload.get("previous_authorization_binding") != previous_binding
            or payload.get("input_sha256") != input_sha256
            or payload.get("output_sha256") != output_sha256
        ):
            raise ValueError("Channel account independent Approval is invalid")
        if command is None:
            raise ValueError("Channel account one-time command Permit is invalid")
        target_binding = {key: value for key, value in expected_input.items() if key != "contract_id"}
        target_binding["input_sha256"] = input_sha256
        if (
            execution_plan is None
            or execution_plan.source_kind != "approved_channel_account_change"
            or execution_plan.source_id != source_event_ref
            or execution_plan.source_approval_id != approval.id
            or execution_plan.approval_id != approval.id
            or execution_plan.adapter_id != adapter["adapter_id"]
            or execution_plan.action_id != action_id
            or execution_plan.created_by != approval.requested_by
            or execution_plan.precondition_state_hash != input_sha256
            or not self._mapping_contains(
                execution_plan.target_json,
                target_binding,
            )
            or not self._mapping_contains(
                execution_plan.intended_patch_json,
                {
                    "output_sha256": output_sha256,
                    "authorization_changed": changes_authorization,
                },
            )
            or not execution_plan.rollback_patch_json
        ):
            raise ValueError("Channel account governed execution plan is invalid")
        decision_hash = str(payload.get("decision_hash") or "").lower()
        authorization_hash = str(payload.get("authorization_hash") or "").lower()
        if (
            command is None
            or command.plan_id != execution_plan.id
            or command.command_kind != "execute"
            or command.action_id != action_id
            or command.adapter_id != adapter["adapter_id"]
            or command.operation != f"channel_account.{event_type}"
            or command.expected_state_hash != input_sha256
            or command.status != "succeeded"
            or command.decision_hash != decision_hash
            or command.authorization_hash != authorization_hash
            or not self._valid_sha256(decision_hash)
            or not self._valid_sha256(authorization_hash)
            or not self._mapping_contains(
                command.target_json,
                target_binding,
            )
            or not self._mapping_contains(
                command.patch_json,
                {
                    "output_sha256": output_sha256,
                    "authorization_changed": changes_authorization,
                },
            )
            or not command.claimed_by
            or self._aware(command.created_at) > effective_at
            or self._aware(command.permit_expires_at) < effective_at
        ):
            raise ValueError("Channel account one-time command Permit is invalid")
        permit = self._require_exact_evidence(
            evidence_id=str(governance["permit_evidence_id"]),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        readback = self._require_exact_evidence(
            evidence_id=str(governance["readback_evidence_id"]),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        self._require_reviewed_evidence(
            record=permit,
            purpose="permit",
            context=context,
        )
        self._require_reviewed_evidence(
            record=readback,
            purpose="readback",
            context=context,
        )
        self._reject_sensitive_metadata(permit.metadata)
        self._reject_sensitive_metadata(readback.metadata)
        issued_at = parse_timestamp(
            str(permit.metadata.get("issued_at") or ""),
            "permit issued_at",
        )
        expires_at = parse_timestamp(
            str(permit.metadata.get("expires_at") or ""),
            "permit expires_at",
        )
        if (
            permit.metadata.get("contract_id") != self.PERMIT_CONTRACT_ID
            or permit.metadata.get("status") != "issued"
            or permit.metadata.get("revoked") is not False
            or permit.metadata.get("single_use") is not True
            or permit.metadata.get("approval_id") != governance["approval_id"]
            or permit.metadata.get("command_id") != governance["command_id"]
            or permit.metadata.get("execution_plan_id") != execution_plan.id
            or permit.metadata.get("action_id") != action_id
            or permit.metadata.get("event_type") != event_type
            or permit.metadata.get("source_event_ref") != source_event_ref
            or permit.metadata.get("platform") != platform
            or permit.metadata.get("account_ref") != account_ref
            or permit.metadata.get("adapter_id") != adapter["adapter_id"]
            or permit.metadata.get("adapter_version") != adapter["adapter_version"]
            or permit.metadata.get("input_sha256") != input_sha256
            or permit.metadata.get("decision_hash") != command.decision_hash
            or permit.metadata.get("authorization_hash") != command.authorization_hash
            or governance["permit_evidence_id"] not in execution_plan.evidence_json
            or issued_at > effective_at
            or expires_at < effective_at
            or expires_at != self._aware(command.permit_expires_at)
        ):
            raise ValueError("Channel account one-time Permit Evidence is invalid")
        readback_at = parse_timestamp(
            str(readback.metadata.get("readback_at") or ""),
            "readback_at",
        )
        expected_request_hash = self._hash(
            {
                "command_id": command.id,
                "outcome": receipt.outcome if receipt is not None else None,
                "remote_operation_id": (receipt.remote_operation_id if receipt is not None else None),
                "resulting_state_hash": (receipt.resulting_state_hash if receipt is not None else None),
                "mutation_applied": (receipt.mutation_applied if receipt is not None else None),
                "error_code": (receipt.error_code if receipt is not None else None),
                "error_detail": (receipt.error_detail if receipt is not None else None),
                "evidence_ids": (receipt.evidence_json if receipt is not None else []),
                "recorded_by": (receipt.recorded_by if receipt is not None else None),
            }
        )
        if (
            receipt is None
            or receipt.command_id != command.id
            or receipt.outcome != "succeeded"
            or receipt.mutation_applied is not changes_authorization
            or receipt.request_hash != expected_request_hash
            or receipt.resulting_state_hash != output_sha256
            or not str(receipt.remote_operation_id or "").strip()
            or receipt.recorded_by != command.claimed_by
            or self._aware(receipt.recorded_at) != effective_at
            or self._aware(receipt.recorded_at) > self._aware(command.permit_expires_at)
            or governance["readback_evidence_id"] not in receipt.evidence_json
        ):
            raise ValueError("Channel account immutable execution receipt is invalid")
        if (
            readback.metadata.get("contract_id") != self.READBACK_CONTRACT_ID
            or readback.metadata.get("outcome") != "succeeded"
            or readback.metadata.get("official_or_authorized") is not True
            or readback.metadata.get("approval_id") != governance["approval_id"]
            or readback.metadata.get("permit_evidence_id") != governance["permit_evidence_id"]
            or readback.metadata.get("command_id") != command.id
            or readback.metadata.get("receipt_id") != receipt.id
            or readback.metadata.get("action_id") != action_id
            or readback.metadata.get("event_type") != event_type
            or readback.metadata.get("source_event_ref") != source_event_ref
            or readback.metadata.get("platform") != platform
            or readback.metadata.get("account_ref") != account_ref
            or readback.metadata.get("adapter_id") != adapter["adapter_id"]
            or readback.metadata.get("adapter_version") != adapter["adapter_version"]
            or readback.metadata.get("authorization_changed") is not changes_authorization
            or readback.metadata.get("remote_operation_id") != receipt.remote_operation_id
            or readback.metadata.get("input_sha256") != input_sha256
            or readback.metadata.get("resulting_authority_sha256") != receipt.resulting_state_hash
            or readback.metadata.get("request_hash") != receipt.request_hash
            or readback_at != effective_at
        ):
            raise ValueError("Channel account official Readback Evidence is invalid")
        kill_evidence = self._require_exact_evidence(
            evidence_id=str(governance["kill_switch_evidence_id"]),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        compensation_evidence = self._require_exact_evidence(
            evidence_id=str(governance["compensation_evidence_id"]),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        self._require_reviewed_evidence(
            record=kill_evidence,
            purpose="kill_switch",
            context=context,
        )
        self._require_reviewed_evidence(
            record=compensation_evidence,
            purpose="compensation",
            context=context,
        )
        self._reject_sensitive_metadata(kill_evidence.metadata)
        self._reject_sensitive_metadata(compensation_evidence.metadata)
        expected_kill_payload = {
            "contract_id": ("kjds-channel-account-kill-switch-state-v1"),
            "schema_version": "1",
            "source_event_ref": (kill_switch_state.source_event_ref if kill_switch_state is not None else None),
            "sequence": (kill_switch_state.sequence if kill_switch_state is not None else None),
            "kill_switch_sequence": (kill_switch_state.kill_switch_sequence if kill_switch_state is not None else None),
            "writes_enabled": (kill_switch_state.writes_enabled if kill_switch_state is not None else None),
            "action_id": action_id,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "adapter_contract_sha256": (adapter["contract_sha256"]),
            "effective_at": (
                self._aware(kill_switch_state.effective_at).isoformat() if kill_switch_state is not None else None
            ),
            "scope": {
                "tenant_ref": (
                    kill_switch_state.tenant_ref
                    if kill_switch_state is not None
                    else None
                ),
                "entity_ref": (
                    kill_switch_state.entity_ref
                    if kill_switch_state is not None
                    else None
                ),
                "store_ref": (
                    kill_switch_state.store_ref
                    if kill_switch_state is not None
                    else None
                ),
                "scope_grant_authority_sha256": (
                    kill_switch_state.scope_grant_authority_sha256
                    if kill_switch_state is not None
                    else None
                ),
                "as_of": (
                    self._aware(kill_switch_state.scope_as_of).isoformat()
                    if kill_switch_state is not None
                    else None
                ),
            },
        }
        kill_payload_sha256 = self._hash(expected_kill_payload)
        kill_content, _ = self.evidence.content(kill_evidence.id)
        if (
            kill_switch_state is None
            or kill_switch_state.id != governance["kill_switch_state_id"]
            or kill_switch_state.kill_switch_sequence != governance["kill_switch_sequence"]
            or kill_switch_state.writes_enabled is not True
            or kill_switch_state.adapter_version != adapter["adapter_version"]
            or kill_switch_state.evidence_id != governance["kill_switch_evidence_id"]
            or kill_switch_state.evidence_sha256 != kill_evidence.sha256
            or kill_switch_state.payload_sha256 != kill_payload_sha256
            or kill_evidence.sha256 != kill_payload_sha256
            or kill_content != self._canonical_bytes(expected_kill_payload)
            or kill_switch is None
            or canonical_kill_switch is None
            or canonical_kill_switch.sequence != kill_switch.sequence
            or kill_switch.engaged is not False
            or not str(kill_switch.reason or "").strip()
            or kill_switch.actor_id
            in {
                approval.requested_by,
                principal.actor_id,
            }
            or self._aware(kill_switch.created_at) > effective_at
            or kill_evidence.metadata.get("purpose") != "channel_account_kill_switch_release"
            or kill_evidence.metadata.get("status") != "released"
            or kill_evidence.metadata.get("kill_switch_sequence") != kill_switch.sequence
            or kill_evidence.metadata.get("kill_switch_state_payload_sha256") != kill_payload_sha256
            or kill_evidence.metadata.get("kill_switch_actor_id") != kill_switch.actor_id
            or kill_evidence.metadata.get("action_id") != action_id
            or kill_evidence.metadata.get("source_event_ref") != kill_switch_state.source_event_ref
            or kill_evidence.metadata.get("adapter_id") != adapter["adapter_id"]
            or kill_evidence.metadata.get("adapter_version") != adapter["adapter_version"]
            or kill_evidence.metadata.get("account_ref") != account_ref
            or kill_evidence.metadata.get("store_ref") != scope["store_ref"]
        ):
            raise ValueError("Channel account Kill Switch authority is invalid")
        compensation_target = {
            **target_binding,
            "receipt_id": receipt.id,
            "output_sha256": output_sha256,
        }
        compensation_mode = "restore_previous_authority" if previous_row is not None else "disable_revoke_cleanup"
        restore_authority_sha256 = input_sha256 if previous_row is not None else None
        compensation_approval_payload = {
            "contract_id": ("kjds-channel-account-compensation-approval-v1"),
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "scope_grant_authority_sha256": scope["scope_grant_authority_sha256"],
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "source_event_ref": source_event_ref,
            "primary_approval_id": approval.id,
            "command_id": command.id,
            "receipt_id": receipt.id,
            "compensation_plan_id": (compensation_plan.id if compensation_plan is not None else None),
            "previous_authorization_binding": previous_binding,
            "precondition_state_sha256": input_sha256,
            "mutated_state_sha256": output_sha256,
            "restore_authority_sha256": restore_authority_sha256,
            "compensation_mode": compensation_mode,
            "requires_fresh_approval": True,
            "automatic_execution_allowed": False,
        }
        compensation_payload = {
            "contract_id": ("kjds-channel-account-compensation-payload-v2"),
            "compensation_plan_id": (compensation_plan.id if compensation_plan is not None else None),
            "compensation_mode": compensation_mode,
            "previous_authorization_binding": previous_binding,
            "precondition_state_sha256": input_sha256,
            "mutated_state_sha256": output_sha256,
            "restore_authority_sha256": (restore_authority_sha256),
            "scope": scope,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
        }
        stored_compensation_content, _ = self.evidence.content(compensation_evidence.id)
        expected_compensation_content = self._canonical_bytes(compensation_payload)
        if (
            compensation_plan is None
            or compensation_plan.id == execution_plan.id
            or compensation_plan.source_kind != "approved_channel_account_compensation"
            or compensation_plan.source_id != source_event_ref
            or compensation_plan.source_approval_id != approval.id
            or compensation_approval is None
            or compensation_approval.status != "approved"
            or not compensation_approval.decided_by
            or compensation_approval.requested_by == compensation_approval.decided_by
            or compensation_approval.action != "channel_authorization_compensate"
            or compensation_approval.resource_type != "channel_account"
            or compensation_approval.resource_id != account_ref
            or compensation_approval.payload_json != compensation_approval_payload
            or compensation_plan.approval_id != compensation_approval.id
            or compensation_plan.adapter_id != adapter["adapter_id"]
            or compensation_plan.action_id != "channel_authorization_compensate"
            or compensation_plan.precondition_state_hash != output_sha256
            or not self._mapping_contains(
                compensation_plan.target_json,
                compensation_target,
            )
            or not self._mapping_contains(
                compensation_plan.intended_patch_json,
                {
                    "compensation_mode": compensation_mode,
                    "restore_authority_sha256": (restore_authority_sha256),
                    "requires_fresh_approval": True,
                    "automatic_execution_allowed": False,
                },
            )
            or compensation_plan.created_by != compensation_approval.requested_by
            or compensation_approval.decided_by
            in {
                approval.requested_by,
                approval.decided_by,
                principal.actor_id,
            }
            or compensation_evidence.metadata.get("purpose") != "channel_account_compensation_plan"
            or compensation_evidence.metadata.get("status") != "ready"
            or compensation_evidence.metadata.get("compensation_plan_id") != compensation_plan.id
            or compensation_evidence.metadata.get("approval_id") != approval.id
            or compensation_evidence.metadata.get("compensation_approval_id") != compensation_approval.id
            or compensation_evidence.metadata.get("command_id") != command.id
            or compensation_evidence.metadata.get("receipt_id") != receipt.id
            or compensation_evidence.metadata.get("action_id") != action_id
            or compensation_evidence.metadata.get("source_event_ref") != source_event_ref
            or compensation_evidence.metadata.get("adapter_id") != adapter["adapter_id"]
            or compensation_evidence.metadata.get("adapter_version") != adapter["adapter_version"]
            or compensation_evidence.metadata.get("account_ref") != account_ref
            or compensation_evidence.metadata.get("store_ref") != scope["store_ref"]
            or not str(compensation_evidence.metadata.get("owner") or "").strip()
            or compensation_evidence.metadata.get("compensation_mode") != compensation_mode
            or compensation_evidence.metadata.get("precondition_state_sha256") != input_sha256
            or stored_compensation_content != expected_compensation_content
            or compensation_evidence.sha256 != hashlib.sha256(expected_compensation_content).hexdigest()
        ):
            raise ValueError("Channel account Compensation authority is invalid")
        source_metadata = source_evidence.metadata
        if (
            source_metadata.get("approval_id") != governance["approval_id"]
            or source_metadata.get("command_id") != governance["command_id"]
            or source_metadata.get("receipt_id") != governance["receipt_id"]
            or source_metadata.get("permit_evidence_id") != governance["permit_evidence_id"]
            or source_metadata.get("readback_evidence_id") != governance["readback_evidence_id"]
            or source_metadata.get("kill_switch_sequence") != governance["kill_switch_sequence"]
            or source_metadata.get("compensation_plan_id") != governance["compensation_plan_id"]
            or source_metadata.get("input_sha256") != input_sha256
            or source_metadata.get("output_sha256") != output_sha256
        ):
            raise ValueError("Authorization source Evidence governance chain drift")
        with Session(self.engine) as session:
            reused = session.scalar(
                select(ChannelAccountAuthorizationEventRow.id).where(
                    ChannelAccountAuthorizationEventRow.tenant_ref == scope["tenant_ref"],
                    ChannelAccountAuthorizationEventRow.entity_ref == scope["entity_ref"],
                    ChannelAccountAuthorizationEventRow.store_ref == scope["store_ref"],
                    ChannelAccountAuthorizationEventRow.source_event_ref
                    != (exclude_source_event_ref or source_event_ref),
                    (ChannelAccountAuthorizationEventRow.command_id == governance["command_id"])
                    | (ChannelAccountAuthorizationEventRow.receipt_id == governance["receipt_id"]),
                )
            )
        if reused is not None:
            raise ValueError("Channel account command Permit or receipt Readback was already consumed")

    @classmethod
    def _previous_authorization_state(
        cls,
        *,
        row: ChannelAccountAuthorizationEventRow | None,
        scope: dict[str, str],
        platform: str,
        account_ref: str,
        adapter_id: str,
    ) -> dict[str, Any]:
        if row is None:
            return {
                "contract_id": ("kjds-channel-account-authorization-precondition-v1"),
                "state": "absent",
                "scope": dict(scope),
                "platform": platform,
                "account_ref": account_ref,
                "adapter_id": adapter_id,
            }
        return {
            "contract_id": ("kjds-channel-account-authorization-precondition-v1"),
            "state": "present",
            "authorization_event": cls._event_source(row),
        }

    @staticmethod
    def _previous_authorization_binding(
        row: ChannelAccountAuthorizationEventRow | None,
    ) -> dict[str, Any]:
        if row is None:
            return {
                "state": "absent",
                "authorization_event_id": None,
                "physical_sequence": None,
                "scope_grant_authority_sha256": None,
                "payload_sha256": None,
            }
        return {
            "state": "present",
            "authorization_event_id": row.id,
            "physical_sequence": row.sequence,
            "scope_grant_authority_sha256": (
                row.scope_grant_authority_sha256
            ),
            "payload_sha256": row.payload_sha256,
        }

    @classmethod
    def _require_previous_authorization_binding(
        cls,
        *,
        previous_row: ChannelAccountAuthorizationEventRow | None,
        previous_state: dict[str, Any],
        previous_binding: dict[str, Any],
        input_sha256: str,
    ) -> None:
        """Reject an absent/current-epoch fiction or a stale restore target."""

        expected_binding = cls._previous_authorization_binding(previous_row)
        expected_input = cls._hash(previous_state)
        if previous_binding != expected_binding or input_sha256 != expected_input:
            raise ValueError(
                "Channel account Compensation previous authority binding is stale"
            )

    @staticmethod
    def _previous_physical_authorization(
        *,
        session: Session,
        scope: dict[str, str],
        platform: str,
        account_ref: str,
        adapter_id: str,
        before_sequence: int,
        exclude_source_event_ref: str,
    ) -> ChannelAccountAuthorizationEventRow | None:
        """Find physical predecessor across Scope Grant authorization epochs."""

        return session.scalar(
            select(ChannelAccountAuthorizationEventRow)
            .where(
                ChannelAccountAuthorizationEventRow.tenant_ref
                == scope["tenant_ref"],
                ChannelAccountAuthorizationEventRow.entity_ref
                == scope["entity_ref"],
                ChannelAccountAuthorizationEventRow.store_ref
                == scope["store_ref"],
                ChannelAccountAuthorizationEventRow.platform == platform,
                ChannelAccountAuthorizationEventRow.account_ref == account_ref,
                ChannelAccountAuthorizationEventRow.adapter_id == adapter_id,
                ChannelAccountAuthorizationEventRow.sequence < before_sequence,
                ChannelAccountAuthorizationEventRow.source_event_ref
                != exclude_source_event_ref,
            )
            .order_by(
                ChannelAccountAuthorizationEventRow.sequence.desc(),
                ChannelAccountAuthorizationEventRow.id.desc(),
            )
            .limit(1)
        )

    def _require_reviewed_evidence(
        self,
        *,
        record,
        purpose: str,
        context: dict[str, Any],
    ) -> None:
        source, contract_id = ChannelAccountGovernanceEvidenceAuthority.PURPOSES[purpose]
        metadata = record.metadata
        submission_id = str(metadata.get("reviewed_submission_id") or "").strip()
        submitted_by = str(metadata.get("submitted_by") or "").strip()
        reviewed_by = str(metadata.get("reviewed_by") or "").strip()
        if (
            record.source != source
            or metadata.get("contract_id") != contract_id
            or metadata.get("channel_account_review_contract_id")
            != ChannelAccountGovernanceEvidenceAuthority.REVIEW_CONTRACT_ID
            or metadata.get("evidence_scope_contract_id") != DIRECT_CONTRACT
            or not submission_id
            or not submitted_by
            or not reviewed_by
            or submitted_by == reviewed_by
            or record.created_by != submitted_by
            or any(metadata.get(key) != context["scope"][key] for key in ("tenant_ref", "entity_ref", "store_ref"))
        ):
            raise ValueError("Channel account Evidence lacks dedicated independent review")
        with Session(self.engine) as session:
            latest_decision = session.scalar(
                select(ChannelAccountReviewDecisionRow)
                .where(ChannelAccountReviewDecisionRow.submission_evidence_id == submission_id)
                .order_by(
                    ChannelAccountReviewDecisionRow.sequence.desc(),
                    ChannelAccountReviewDecisionRow.id.desc(),
                )
                .limit(1)
            )
        if (
            latest_decision is None
            or latest_decision.accepted is not True
            or latest_decision.decision_evidence_id != record.id
            or latest_decision.reviewer_id != reviewed_by
            or latest_decision.decision_sha256 != metadata.get("review_decision_sha256")
            or latest_decision.sequence != metadata.get("review_sequence")
            or any(
                getattr(latest_decision, key) != context["scope"][key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                )
            )
        ):
            raise ValueError("Channel account Evidence is not the latest accepted review decision")
        self.evidence.require_current(
            [submission_id],
            as_of=context["cutoff"],
        )
        submission = self.evidence.get(submission_id)
        submission_metadata = submission.metadata
        if (
            submission.source != "channel_account_governance_submission"
            or submission_metadata.get("contract_id")
            != ChannelAccountGovernanceEvidenceAuthority.SUBMISSION_CONTRACT_ID
            or submission_metadata.get("purpose") != purpose
            or submission.created_by != submitted_by
            or submission.sha256 != record.sha256
            or metadata.get("reviewed_submission_sha256") != submission.sha256
            or any(
                submission_metadata.get(key) != context["scope"][key]
                for key in ("tenant_ref", "entity_ref", "store_ref")
            )
        ):
            raise ValueError("Channel account reviewed Evidence submission binding drift")

    def _require_exact_evidence(
        self,
        *,
        evidence_id: str,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
    ):
        evidence_id = self._required(evidence_id, "evidence_id", 240)
        metadata_record = self.evidence.get_metadata(evidence_id)
        metadata = metadata_record.metadata or {}
        if any(
            metadata.get(field) != context["scope"][field]
            for field in (
                "tenant_ref",
                "entity_ref",
                "store_ref",
            )
        ):
            raise PermissionError(
                "Channel account Evidence is outside the exact scope"
            )
        projection = self.scoped_evidence.project_targets(
            evidence_ids=[evidence_id],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
        )
        target = next(
            (item for item in projection.get("records", []) if item.get("evidence_id", item.get("id")) == evidence_id),
            None,
        )
        if (
            projection.get("status") != "ready"
            or target is None
            or (target.get("status") or (target.get("scope_binding") or {}).get("status")) != "ready"
        ):
            raise ValueError("Channel account Evidence is not exact-scope ready")
        self.evidence.require_current([evidence_id], as_of=context["cutoff"])
        record = self.evidence.get(evidence_id)
        return record

    def _context(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: str | None,
    ) -> dict[str, Any]:
        cutoff = parse_timestamp(
            as_of or datetime.now(UTC).isoformat(),
            "as_of",
        )
        if self.scope_authority is None:
            raise PermissionError(
                "Channel account canonical mutation scope authority is unbound"
            )
        return {
            "cutoff": cutoff,
            "scope": self.scope_authority.resolve(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
            ),
        }

    @classmethod
    def _read_context(
        cls,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
    ) -> dict[str, Any]:
        authority = str(scope_grant_authority_sha256 or "").strip().lower()
        if not cls._valid_sha256(authority):
            raise ValueError("scope_grant_authority_sha256 must be SHA-256")
        return {
            "cutoff": parse_timestamp(as_of, "as_of"),
            "scope": {
                "tenant_ref": cls._required(tenant_ref, "tenant_ref", 160),
                "entity_ref": cls._required(entity_ref, "entity_ref", 160),
                "store_ref": cls._required(store_ref, "store_ref", 160),
                "scope_grant_authority_sha256": authority,
            },
        }

    @classmethod
    def _event(
        cls,
        row: ChannelAccountAuthorizationEventRow,
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {**cls._event_source(row), "idempotent": idempotent}

    @classmethod
    def _kill_switch_state(
        cls,
        row: ChannelAccountKillSwitchStateRow,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_event_ref": row.source_event_ref,
            "sequence": row.sequence,
            "kill_switch_sequence": row.kill_switch_sequence,
            "writes_enabled": row.writes_enabled,
            "action_id": row.action_id,
            "platform": row.platform,
            "account_ref": row.account_ref,
            "adapter_id": row.adapter_id,
            "adapter_version": row.adapter_version,
            "evidence_id": row.evidence_id,
            "evidence_sha256": row.evidence_sha256,
            "payload_sha256": row.payload_sha256,
            "effective_at": cls._aware(row.effective_at).isoformat(),
            "recorded_at": cls._aware(row.recorded_at).isoformat(),
            "scope_as_of": cls._aware(row.scope_as_of).isoformat(),
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": (row.scope_grant_authority_sha256),
            },
            "idempotent": idempotent,
        }

    @classmethod
    def _event_source(cls, row: ChannelAccountAuthorizationEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_event_ref": row.source_event_ref,
            "sequence": row.sequence,
            "event_type": row.event_type,
            "authorization_source": row.authorization_source,
            "platform": row.platform,
            "account_ref": row.account_ref,
            "adapter_id": row.adapter_id,
            "adapter_version": row.adapter_version,
            "adapter_contract_sha256": (row.adapter_contract_sha256),
            "role_ref": row.role_ref,
            "subaccount_ref": row.subaccount_ref,
            "credential_kind": row.credential_kind,
            "capabilities": sorted(row.capabilities_json),
            "secret_reference_present": True,
            "secret_reference_sha256": (row.secret_reference_sha256),
            "credential_fingerprint_sha256": (row.credential_fingerprint_sha256),
            "health_status": row.health_status,
            "readback_outcome": row.readback_outcome,
            "rate_limit_state": row.rate_limit_state,
            "external_schema_version": (row.external_schema_version),
            "consent_evidence_id": row.consent_evidence_id,
            "consent_evidence_sha256": (row.consent_evidence_sha256),
            "evidence_id": row.evidence_id,
            "source_evidence_sha256": (row.source_evidence_sha256),
            "source_payload_sha256": row.source_payload_sha256,
            "payload_sha256": row.payload_sha256,
            "approval_id": row.approval_id,
            "command_id": row.command_id,
            "receipt_id": row.receipt_id,
            "permit_evidence_id": row.permit_evidence_id,
            "readback_evidence_id": row.readback_evidence_id,
            "kill_switch_sequence": row.kill_switch_sequence,
            "kill_switch_state_id": row.kill_switch_state_id,
            "kill_switch_evidence_id": (row.kill_switch_evidence_id),
            "compensation_plan_id": row.compensation_plan_id,
            "compensation_evidence_id": (row.compensation_evidence_id),
            "effective_at": cls._aware(row.effective_at).isoformat(),
            "expires_at": cls._aware(row.expires_at).isoformat(),
            "verified_at": cls._aware(row.verified_at).isoformat(),
            "recorded_at": cls._aware(row.recorded_at).isoformat(),
            "created_by": row.created_by,
            "scope_as_of": cls._aware(row.scope_as_of).isoformat(),
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": (row.scope_grant_authority_sha256),
            },
        }

    @classmethod
    def _reject_sensitive_metadata(
        cls,
        value: Any,
        *,
        allowed_fields: frozenset[str] | None = None,
        parent_key: str = "",
    ) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = cls._normalized_key(str(key))
                if normalized not in cls.SAFE_SENSITIVE_DIGEST_KEYS and any(
                    fragment in normalized for fragment in cls.SENSITIVE_KEY_FRAGMENTS
                ):
                    raise ValueError("Credential material is forbidden in Evidence metadata")
                cls._reject_sensitive_metadata(
                    child,
                    allowed_fields=allowed_fields,
                    parent_key=normalized,
                )
                if allowed_fields is not None and normalized not in allowed_fields:
                    raise ValueError("Unknown field is forbidden by the channel account Evidence schema")
        elif isinstance(value, list):
            for child in value:
                cls._reject_sensitive_metadata(
                    child,
                    allowed_fields=allowed_fields,
                    parent_key=parent_key,
                )
            if value and all(isinstance(child, str) for child in value):
                for joined in (
                    "".join(value),
                    " ".join(value),
                    ":".join(value),
                ):
                    cls._reject_sensitive_metadata(
                        joined,
                        allowed_fields=allowed_fields,
                        parent_key=parent_key,
                    )
        elif isinstance(value, str):
            decoded = cls._decode_obfuscated_text(value)
            if (
                cls.SENSITIVE_VALUE_RE.search(decoded)
                or cls.PROVIDER_SECRET_RE.search(decoded)
                or cls.MANAGED_LOCATOR_RE.search(decoded)
                or ManagedSecretLocatorPolicy.PATTERN.fullmatch(decoded.strip())
                or (
                    not cls._server_derived_digest_key(parent_key)
                    and cls._contains_high_entropy_secret(decoded)
                )
            ):
                raise ValueError("Credential material is forbidden in Evidence metadata")

    @classmethod
    def _server_derived_digest_key(cls, normalized_key: str) -> bool:
        """Accept immutable lineage hashes, never caller-supplied digest claims.

        The dedicated submission service rejects every client-controlled digest
        field before capture. Stored canonical Evidence then carries hashes the
        server derived itself, so admission may recognize the normalized suffix.
        """

        return (
            normalized_key in cls.SAFE_SENSITIVE_DIGEST_KEYS
            or normalized_key.endswith("sha256")
            or normalized_key.endswith("hash")
        )

    @classmethod
    def _reject_sibling_fragmentation(
        cls,
        value: Any,
    ) -> None:
        """Reject credentials split across separately valid sibling fields."""

        fragments: list[str] = []

        def collect(node: Any, *, parent_key: str = "") -> None:
            if isinstance(node, dict):
                for raw_key, child in node.items():
                    collect(
                        child,
                        parent_key=cls._normalized_key(str(raw_key)),
                    )
                return
            if isinstance(node, list):
                for child in node:
                    collect(child, parent_key=parent_key)
                return
            if (
                isinstance(node, str)
                and not cls._server_derived_digest_key(parent_key)
            ):
                fragments.append(node)

        collect(value)
        # Duplicate semantic/canonical projections do not increase the search
        # space.  Eight unique fragments still permit an exhaustive bounded
        # permutation search (109,592 candidates), while larger free-form
        # payloads are not admitted by this read-only/gated workflow.
        fragments = list(dict.fromkeys(fragments))
        if len(fragments) > 8:
            raise ValueError(
                "Too many free-form string fields in channel account Evidence"
            )
        for width in range(2, len(fragments) + 1):
            for parts in permutations(fragments, width):
                joined = "".join(parts)
                if len(joined) > 4096:
                    raise ValueError(
                        "Channel account Evidence string fragments are too large"
                    )
                cls._reject_sensitive_metadata(
                    joined,
                    parent_key="fragmentedvalue",
                )

    @staticmethod
    def _looks_like_high_entropy_secret(value: str) -> bool:
        candidate = str(value or "").strip()
        if (
            len(candidate) < 32
            or len(candidate) > 4096
            or not re.fullmatch(
                r"[A-Za-z0-9+/=_-]+",
                candidate,
            )
        ):
            return False
        counts = {character: candidate.count(character) for character in set(candidate)}
        entropy = -sum((count / len(candidate)) * math.log2(count / len(candidate)) for count in counts.values())
        return entropy >= 4.25

    @classmethod
    def _contains_high_entropy_secret(cls, value: str) -> bool:
        if re.search(
            r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])",
            str(value or ""),
        ):
            return True
        return any(
            cls._looks_like_high_entropy_secret(candidate)
            for candidate in re.findall(
                r"[A-Za-z0-9+/=_-]{32,4096}",
                str(value or ""),
            )
        )

    @staticmethod
    def _unquote_repeated(value: str) -> str:
        result = str(value)
        for _ in range(12):
            decoded = unquote(result)
            if decoded == result:
                return result
            result = decoded
        if re.search(r"%[0-9a-fA-F]{2}", result):
            raise ValueError(
                "Excessively encoded value is forbidden in channel account Evidence"
            )
        return result

    @classmethod
    def _decode_obfuscated_text(cls, value: str) -> str:
        result = str(value)
        unicode_escape = re.compile(r"\\(?:u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2}))")
        for _ in range(12):
            decoded = unquote(result)
            decoded = html.unescape(decoded)
            decoded = unicode_escape.sub(
                lambda match: chr(
                    int(match.group(1) or match.group(2), 16)
                ),
                decoded,
            )
            decoded = unicodedata.normalize("NFKC", decoded)
            if decoded == result:
                return decoded
            result = decoded
        if (
            re.search(r"%[0-9a-fA-F]{2}", result)
            or "&" in html.unescape(result)
            or unicode_escape.search(result)
        ):
            raise ValueError(
                "Excessively encoded value is forbidden in channel account Evidence"
            )
        return result

    @classmethod
    def _normalized_key(cls, value: str) -> str:
        decoded = cls._decode_obfuscated_text(value).casefold()
        return re.sub(r"[^a-z0-9]", "", decoded)

    @classmethod
    def _secret_reference(cls, value: str) -> str:
        return ManagedSecretLocatorPolicy.validate(value)

    @classmethod
    def _capabilities(cls, values: list[str], *, allowed: list[str]) -> list[str]:
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value.strip() for value in values)
        ):
            raise ValueError("capabilities must be non-empty strings")
        normalized = sorted({value.strip() for value in values})
        if len(normalized) != len(values):
            raise ValueError("capabilities must not contain duplicates")
        if not set(normalized).issubset(set(allowed)):
            raise ValueError("Authorization capability is outside adapter contract")
        return normalized

    @classmethod
    def _choice(cls, value: str, field: str, allowed: frozenset[str]) -> str:
        normalized = cls._required(value, field, 80).lower()
        if normalized not in allowed:
            raise ValueError(f"{field} is unsupported")
        return normalized

    @classmethod
    def _optional(cls, value: str | None, field: str, limit: int) -> str | None:
        if value is None or not str(value).strip():
            return None
        return cls._required(value, field, limit)

    @staticmethod
    def _positive_int_or_none(
        value: int | None,
        field: str,
    ) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{field} must be a positive integer")
        return value

    @staticmethod
    def _mapping_contains(
        actual: dict[str, Any],
        expected: dict[str, Any],
    ) -> bool:
        return isinstance(actual, dict) and all(actual.get(key) == value for key, value in expected.items())

    @staticmethod
    def _required(value: Any, field: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > limit:
            raise ValueError(f"{field} must be 1 to {limit} characters")
        return normalized

    @classmethod
    def _sha256_value(cls, value: str, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if not cls._valid_sha256(normalized):
            raise ValueError(f"{field} must be SHA-256")
        return normalized

    @staticmethod
    def _valid_sha256(value: str) -> bool:
        normalized = str(value or "").strip().lower()
        return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _canonical_bytes(value: Any) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(ChannelAccountAuthorizationAuthority._canonical_bytes(value)).hexdigest()
