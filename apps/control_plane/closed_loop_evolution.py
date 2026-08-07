from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from base64 import urlsafe_b64encode
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .agent_runtime import RUNTIME_CONTRACT_ID, AgentRunScopeContext
from .agent_runtime_evidence import (
    AGENT_RUN_EVIDENCE_CONTRACT,
    AGENT_RUN_EVIDENCE_SOURCE,
    AgentRuntimeRunEnvelopeRow,
    AgentRuntimeRunEventRow,
    SqlAgentRuntimeEvidenceLedger,
)
from .ai_listing import AiListingRunRow as _AiListingRunRow  # noqa: F401
from .browser_capture_inbox import (
    BrowserCaptureSubmissionRow as _BrowserCaptureSubmissionRow,  # noqa: F401
)
from .evidence import (
    CLOSED_LOOP_AUTHORITY_CONTRACTS,
    CLOSED_LOOP_AUTHORITY_SCHEMA_MANIFESTS,
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
    _closed_loop_claims,
    _closed_loop_claims_sha256,
    _closed_loop_postgres_jsonb_sha256,
    _closed_loop_require_association_only,
)
from .security import Principal
from .sql_repository import Base

CONTRACT_ID = "kjds-governed-closed-loop-evolution-v1"
CONTRACT_VERSION = "1.0.0"
EVENT_CONTRACT_ID = "kjds-governed-closed-loop-evolution-event-v1"
EXPECTED_REGISTRY_CONTENT_SHA256 = "3b46a8730ab6cf32eed49793c5c4d04889dd412a048c226f2a13de96599b022d"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "docs/project/registries/closed_loop_evolution_contracts.json"
PURPOSES = ("experiment", "cost", "business_outcome")
EVENT_TYPES = (
    "bundle_recorded",
    "review_requested",
    "invalidated",
    "revoked",
    "superseded",
)
READ_ROLES = frozenset({"operator", "reviewer", "compliance", "monitor", "admin"})
WRITE_ROLES = frozenset({"operator", "compliance", "admin"})
REVIEW_ROLES = frozenset({"reviewer", "compliance", "admin"})
_ZERO_SHA256 = "0" * 64
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_OPAQUE_TOKEN = re.compile(r"^clh[sc]_[A-Za-z0-9_-]{32,96}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_AGENT_RUN_METADATA_KEYS = frozenset(
    {
        "contract_id",
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "authority_sha256",
        "run_id",
        "event_id",
        "event_type",
        "event_sha256",
        "retention_class",
        "legal_hold",
    }
)


@dataclass(frozen=True, slots=True)
class _AgentRunEventContract:
    event_keys: frozenset[str]
    event_types: frozenset[str]
    terminal_event_types: frozenset[str]
    unknown_reason_codes: frozenset[str]
    transitions: tuple[tuple[str | None, frozenset[str]], ...]
    safe_payload_keys: tuple[tuple[str, frozenset[str]], ...]

    def next_types(self, previous: str | None) -> frozenset[str]:
        return next(
            (admitted for source, admitted in self.transitions if source == previous),
            frozenset(),
        )

    def safe_keys(self, event_type: str) -> frozenset[str]:
        return next(
            (keys for candidate, keys in self.safe_payload_keys if candidate == event_type),
            frozenset(),
        )


_AGENT_RUN_EVENT_CONTRACT = _AgentRunEventContract(
    event_keys=frozenset(
        {
            "event_index",
            "event_type",
            "reason_code",
            "adapter_sha256",
            "provider_sha256",
            "model_sha256",
            "adapter_config_sha256",
            "output_sha256",
            "eval_sha256",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "latency_ms",
            "safe_payload",
            "previous_event_sha256",
            "occurred_at",
            "event_sha256",
        }
    ),
    event_types=frozenset(
        {
            "run_started",
            "route_selected",
            "attempt_started",
            "attempt_completed",
            "attempt_denied",
            "attempt_failed",
            "eval_completed",
            "run_succeeded",
            "run_failed",
            "run_denied",
            "unknown_outcome",
        }
    ),
    terminal_event_types=frozenset({"run_succeeded", "run_failed", "run_denied", "unknown_outcome"}),
    unknown_reason_codes=frozenset({"provider_outcome_not_persisted", "provider_outcome_not_terminal"}),
    transitions=(
        (None, frozenset({"run_started"})),
        ("run_started", frozenset({"route_selected", "run_denied"})),
        (
            "route_selected",
            frozenset({"attempt_started", "run_failed", "unknown_outcome"}),
        ),
        (
            "attempt_started",
            frozenset(
                {
                    "attempt_completed",
                    "attempt_denied",
                    "attempt_failed",
                    "unknown_outcome",
                }
            ),
        ),
        ("attempt_completed", frozenset({"eval_completed", "unknown_outcome"})),
        ("attempt_denied", frozenset({"run_denied", "unknown_outcome"})),
        (
            "attempt_failed",
            frozenset({"attempt_started", "run_failed", "unknown_outcome"}),
        ),
        ("eval_completed", frozenset({"run_succeeded", "unknown_outcome"})),
    ),
    safe_payload_keys=(
        ("run_started", frozenset()),
        ("route_selected", frozenset({"adapter_count", "adapter_config_sha256"})),
        ("attempt_started", frozenset({"attempt"})),
        ("attempt_completed", frozenset({"attempt"})),
        ("attempt_denied", frozenset({"attempt"})),
        ("attempt_failed", frozenset({"attempt"})),
        ("eval_completed", frozenset({"passed", "assertion_count"})),
        ("run_succeeded", frozenset({"attempt_count"})),
        ("run_failed", frozenset()),
        ("run_denied", frozenset()),
        ("unknown_outcome", frozenset()),
    ),
)
_SUPPORTING_PAYLOAD_KEYS = frozenset(
    {
        "contract_id",
        "purpose",
        "attestation_ref",
        "authority_receipt_id",
        "issuer_id",
        "issuer_contract_id",
        "issuer_contract_version",
        "issuer_contract_sha256",
        "schema_sha256",
        "issuer_actor_id",
        "exact_scope",
        "data_as_of",
        "effective_at",
        "effective_until",
        "recorded_at",
        "review_due_at",
        "claims",
        "claims_sha256",
        "attestation_sha256",
        "attestation_signature_sha256",
        "payload_status",
        "contains_customer_data",
        "external_write_allowed",
    }
)
_SUPPORTING_METADATA_KEYS = frozenset(
    {
        "contract_id",
        "closed_loop_purpose",
        "closed_loop_claims_sha256",
        "closed_loop_attestation_sha256",
        "closed_loop_attestation_signature_sha256",
        "closed_loop_attestation_ref",
        "closed_loop_authority_receipt_id",
        "closed_loop_issuer_id",
        "closed_loop_issuer_contract_id",
        "closed_loop_issuer_contract_version",
        "closed_loop_issuer_contract_sha256",
        "closed_loop_schema_sha256",
        "closed_loop_issuer_actor_id",
        "closed_loop_data_as_of",
        "closed_loop_recorded_at",
        "closed_loop_review_due_at",
        "closed_loop_claims",
        "closed_loop_scope_binding_sha256",
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "scope_grant_authority_sha256",
        "retention_class",
        "legal_hold",
    }
)
_SUPPORTING_SCOPE_KEYS = frozenset(
    {"tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"}
)
_SUPPORTING_ATTESTATION_KEYS = _SUPPORTING_PAYLOAD_KEYS - {
    "attestation_sha256",
    "attestation_signature_sha256",
    "payload_status",
    "contains_customer_data",
    "external_write_allowed",
}
_PUBLIC_AUTHORITY_CONTRACT_KEYS = frozenset(
    {
        "source",
        "contract_id",
        "issuer_id",
        "issuer_contract_id",
        "issuer_contract_version",
        "issuer_contract_sha256",
        "schema_sha256",
    }
)
_TRANSITIONS = {
    "bundle_recorded": frozenset({"review_requested", "invalidated", "revoked", "superseded"}),
    "review_requested": frozenset({"review_requested", "invalidated", "revoked", "superseded"}),
    "invalidated": frozenset(),
    "revoked": frozenset(),
    "superseded": frozenset(),
}


class ClosedLoopContractError(ValueError):
    """A frozen BAS-204 contract was violated."""


@dataclass(frozen=True)
class Bas177ClosedLoopObservation:
    """Opaque, observation-only handoff for the BAS-177 evolution boundary."""

    contract_id: str
    contract_version: str
    learning_input_type: str
    status: Literal["ready", "review_due", "invalidated"]
    reason_code: str
    opaque_scope_binding: str
    opaque_citation: str
    bundle_sha256: str
    event_chain_sha256: str
    supporting_evidence_sha256: str
    data_as_of: str
    latest_event_type: str
    latest_event_occurred_at: str
    latest_event_recorded_at: str
    invalidation_conditions: tuple[str, ...]
    causal_claim_allowed: Literal[False] = False
    learning_eligibility: Literal["observation_only"] = "observation_only"
    candidate_created: Literal[False] = False
    transition_allowed: Literal[False] = False
    promotion_allowed: Literal[False] = False
    writes: Literal[0] = 0
    content_sha256: str = ""
    seal_sha256: str = ""

    def payload(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "learning_input_type": self.learning_input_type,
            "status": self.status,
            "reason_code": self.reason_code,
            "opaque_scope_binding": self.opaque_scope_binding,
            "opaque_citation": self.opaque_citation,
            "bundle_sha256": self.bundle_sha256,
            "event_chain_sha256": self.event_chain_sha256,
            "supporting_evidence_sha256": self.supporting_evidence_sha256,
            "data_as_of": self.data_as_of,
            "latest_event_type": self.latest_event_type,
            "latest_event_occurred_at": self.latest_event_occurred_at,
            "latest_event_recorded_at": self.latest_event_recorded_at,
            "invalidation_conditions": list(self.invalidation_conditions),
            "causal_claim_allowed": False,
            "learning_eligibility": "observation_only",
            "candidate_created": False,
            "transition_allowed": False,
            "promotion_allowed": False,
            "writes": 0,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self.payload()
        payload["content_sha256"] = self.content_sha256
        payload["seal_sha256"] = self.seal_sha256
        return payload

    def verify(self, *, sealing_key: bytes) -> None:
        expected_seal = _handoff_seal(sealing_key, self.payload())
        try:
            reason_valid = _token(self.reason_code, "handoff reason_code") == self.reason_code
            data_as_of_valid = _iso(_aware(self.data_as_of, "data_as_of")) == self.data_as_of
            occurred = _aware(self.latest_event_occurred_at, "latest_event_occurred_at")
            recorded = _aware(self.latest_event_recorded_at, "latest_event_recorded_at")
            times_valid = (
                _iso(occurred) == self.latest_event_occurred_at
                and _iso(recorded) == self.latest_event_recorded_at
                and occurred <= recorded
            )
        except ClosedLoopContractError:
            reason_valid = data_as_of_valid = times_valid = False
        status_events = {
            "ready": {"bundle_recorded"},
            "review_due": {"bundle_recorded", "review_requested"},
            "invalidated": set(EVENT_TYPES),
        }
        status_reasons = {
            "ready": {"observational_association_only"},
            "review_due": {"review_due", "review_requested"},
            "invalidated": {
                "agent_run_terminal_not_current",
                "supporting_evidence_not_current",
                "supporting_evidence_expired",
                "invalidated",
                "revoked",
                "superseded",
            },
        }
        if (
            self.contract_id != "kjds-bas177-closed-loop-evolution-observation-v1"
            or self.contract_version != "1.0.0"
            or self.learning_input_type != "association_only_outcome"
            or self.status not in {"ready", "review_due", "invalidated"}
            or not reason_valid
            or not data_as_of_valid
            or not times_valid
            or self.latest_event_type not in status_events[self.status]
            or self.reason_code not in status_reasons[self.status]
            or (
                self.latest_event_type in {"invalidated", "revoked", "superseded"}
                and self.reason_code != self.latest_event_type
            )
            or (self.reason_code == "review_requested" and self.latest_event_type != "review_requested")
            or type(self.invalidation_conditions) is not tuple
            or self.invalidation_conditions
            != (
                "scope_authority_rotation",
                "supporting_evidence_expiry",
                "review_due",
                "contract_or_hash_drift",
            )
            or self.causal_claim_allowed
            or self.learning_eligibility != "observation_only"
            or self.candidate_created
            or self.transition_allowed
            or self.promotion_allowed
            or self.writes != 0
            or not _SHA256.fullmatch(self.bundle_sha256)
            or not _SHA256.fullmatch(self.event_chain_sha256)
            or not _SHA256.fullmatch(self.supporting_evidence_sha256)
            or not _OPAQUE_TOKEN.fullmatch(self.opaque_scope_binding)
            or not _OPAQUE_TOKEN.fullmatch(self.opaque_citation)
            or self.content_sha256 != _hash_json(self.payload())
            or not _SHA256.fullmatch(self.seal_sha256)
            or not hmac.compare_digest(self.seal_sha256, expected_seal)
        ):
            raise ClosedLoopContractError("BAS-177 handoff contract drifted")


class ClosedLoopEvidenceIssuerPort:
    """Narrow PostgreSQL port for a pre-registered authority receipt."""

    __slots__ = ("__engine",)

    def __init__(self, engine: Any) -> None:
        self.__engine = engine

    def issue_evidence(
        self,
        *,
        authority_receipt_id: str,
        evidence_id: str,
        content: bytes,
        filename: str,
        source: str,
        source_ref: str,
        effective_at: datetime,
        effective_until: datetime,
        metadata: Mapping[str, object],
        attestation_sha256: str,
        attestation_signature_sha256: str,
    ) -> str:
        try:
            with self.__engine.begin() as connection:
                identity = connection.execute(
                    text(
                        "SELECT current_user,session_user,rolsuper,rolinherit,"
                        "rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,"
                        "pg_has_role(session_user,'kjds_cloe_issuance_owner','SET'),"
                        "(SELECT count(*) FROM pg_auth_members m "
                        "JOIN pg_roles granted ON granted.oid=m.roleid "
                        "JOIN pg_roles member_role ON member_role.oid=m.member "
                        "WHERE granted.rolname IN "
                        "('kjds_cloe_issuance_owner','kjds_cloe_issuance_runtime',"
                        "'kjds_cloe_experiment_authority','kjds_cloe_cost_authority',"
                        "'kjds_cloe_outcome_authority','kjds_cloe_review_authority') "
                        "OR member_role.rolname IN "
                        "('kjds_cloe_issuance_owner','kjds_cloe_issuance_runtime',"
                        "'kjds_cloe_experiment_authority','kjds_cloe_cost_authority',"
                        "'kjds_cloe_outcome_authority','kjds_cloe_review_authority')) "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                ).one()
                if (
                    tuple(identity[:2]) != ("kjds_cloe_issuance_runtime",) * 2
                    or any(identity[2:8])
                    or identity[8] is not False
                    or identity[9] != 0
                ):
                    raise PermissionError("Closed-loop issuer runtime principal is invalid")
                returned = connection.scalar(
                    text(
                        "SELECT kjds_cloe_issue_evidence("
                        ":authority_receipt_id,:evidence_id,:content,:filename,"
                        ":source,:source_ref,:effective_at,:effective_until,"
                        "CAST(:metadata AS jsonb),:attestation_sha256,"
                        ":attestation_signature_sha256)"
                    ),
                    {
                        "authority_receipt_id": authority_receipt_id,
                        "evidence_id": evidence_id,
                        "content": content,
                        "filename": filename,
                        "source": source,
                        "source_ref": source_ref,
                        "effective_at": effective_at,
                        "effective_until": effective_until,
                        "metadata": json.dumps(
                            metadata,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ),
                        "attestation_sha256": attestation_sha256,
                        "attestation_signature_sha256": (attestation_signature_sha256),
                    },
                )
        except PermissionError:
            raise
        except Exception:
            raise PermissionError("Closed-loop Evidence issuance failed") from None
        if returned != evidence_id:
            raise PermissionError("Closed-loop issuer returned an invalid receipt")
        return returned

    def dispose(self) -> None:
        self.__engine.dispose()


class ClosedLoopEventEvidenceIssuerPort:
    """Same-transaction SECURITY DEFINER seam for module-owned Grade-D Evidence."""

    def issue_event_evidence(
        self,
        *,
        session: Session,
        evidence_id: str,
        content: bytes,
        filename: str,
        source_ref: str,
        effective_at: datetime,
        recorded_at: datetime,
        metadata: Mapping[str, object],
    ) -> str:
        try:
            identity = session.execute(
                text(
                    "SELECT current_user,session_user,rolsuper,rolcreaterole,"
                    "rolcreatedb,rolreplication,"
                    "has_table_privilege(session_user,"
                    "'closed_loop_outcome_bundles','INSERT') "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            ).one()
            if identity[0] != identity[1] or any(identity[2:6]) or identity[6] is not True:
                raise PermissionError("Closed-loop event runtime principal is invalid")
            returned = session.scalar(
                text(
                    "SELECT kjds_cloe_issue_event_evidence("
                    ":evidence_id,:content,:filename,:source_ref,:effective_at,"
                    ":recorded_at,CAST(:metadata AS jsonb))"
                ),
                {
                    "evidence_id": evidence_id,
                    "content": content,
                    "filename": filename,
                    "source_ref": source_ref,
                    "effective_at": effective_at,
                    "recorded_at": recorded_at,
                    "metadata": json.dumps(
                        metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                },
            )
        except PermissionError:
            raise
        except Exception:
            raise PermissionError("Closed-loop event Evidence issuance failed") from None
        if returned != evidence_id:
            raise PermissionError("Closed-loop event issuer returned an invalid receipt")
        return returned


class ClosedLoopAuthorityReceiptRegistrarPort:
    """Purpose-specific DB identity that registers one verified receipt."""

    __slots__ = ("__engine", "__purpose", "__role")

    _ROLES = {
        "experiment": "kjds_cloe_experiment_authority",
        "cost": "kjds_cloe_cost_authority",
        "business_outcome": "kjds_cloe_outcome_authority",
        "review_event": "kjds_cloe_review_authority",
    }

    def __init__(self, engine: Any, *, purpose: str) -> None:
        role = self._ROLES.get(purpose)
        if role is None:
            raise ValueError("Closed-loop registrar purpose is invalid")
        self.__engine = engine
        self.__purpose = purpose
        self.__role = role

    def register_authority_receipt(self, *, receipt: Mapping[str, object]) -> str:
        if receipt.get("purpose") != self.__purpose:
            raise PermissionError("Closed-loop registrar purpose drifted")
        try:
            with self.__engine.begin() as connection:
                identity = connection.execute(
                    text(
                        "SELECT current_user,session_user,rolsuper,rolinherit,"
                        "rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,"
                        "pg_has_role(session_user,'kjds_cloe_issuance_owner','SET'),"
                        "(SELECT count(*) FROM pg_auth_members m "
                        "JOIN pg_roles granted ON granted.oid=m.roleid "
                        "JOIN pg_roles member_role ON member_role.oid=m.member "
                        "WHERE granted.rolname IN "
                        "('kjds_cloe_issuance_owner','kjds_cloe_issuance_runtime',"
                        "'kjds_cloe_experiment_authority','kjds_cloe_cost_authority',"
                        "'kjds_cloe_outcome_authority','kjds_cloe_review_authority') "
                        "OR member_role.rolname IN "
                        "('kjds_cloe_issuance_owner','kjds_cloe_issuance_runtime',"
                        "'kjds_cloe_experiment_authority','kjds_cloe_cost_authority',"
                        "'kjds_cloe_outcome_authority','kjds_cloe_review_authority')) "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                ).one()
                if (
                    tuple(identity[:2]) != (self.__role,) * 2
                    or any(identity[2:8])
                    or identity[8] is not False
                    or identity[9] != 0
                ):
                    raise PermissionError("Closed-loop registrar principal is invalid")
                returned = connection.scalar(
                    text("SELECT kjds_cloe_register_authority_receipt(CAST(:receipt AS jsonb))"),
                    {
                        "receipt": json.dumps(
                            receipt,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                    },
                )
        except PermissionError:
            raise
        except Exception:
            raise PermissionError("Closed-loop authority registration failed") from None
        receipt_id = receipt.get("authority_receipt_id")
        if returned != receipt_id:
            raise PermissionError("Closed-loop registrar returned an invalid receipt")
        return returned

    def dispose(self) -> None:
        self.__engine.dispose()


class ClosedLoopAuthorityReceiptRow(Base):
    __tablename__ = "closed_loop_authority_receipts"
    __table_args__ = (
        UniqueConstraint("evidence_id", name="uq_cloe_authority_receipt_evidence"),
        CheckConstraint(
            "purpose IN ('experiment','cost','business_outcome','review_event') AND "
            "source IN ('closed-loop-experiment-receipt',"
            "'closed-loop-cost-receipt',"
            "'closed-loop-business-outcome-receipt',"
            "'closed-loop-review-authority-receipt') AND "
            "content_sha256 ~ '^[0-9a-f]{64}$' AND "
            "metadata_sha256 ~ '^[0-9a-f]{64}$' AND "
            "attestation_sha256 ~ '^[0-9a-f]{64}$' AND "
            "attestation_signature_sha256 ~ '^[0-9a-f]{64}$' AND "
            "issuer_contract_sha256 ~ '^[0-9a-f]{64}$' AND "
            "schema_sha256 ~ '^[0-9a-f]{64}$' AND "
            "scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND "
            "effective_at <= recorded_at AND recorded_at <= data_as_of AND "
            "data_as_of < review_due_at AND review_due_at <= effective_until",
            name="ck_cloe_authority_receipt",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "effective_at <= recorded_at AND recorded_at <= data_as_of AND "
            "data_as_of < review_due_at AND review_due_at <= effective_until",
            name="ck_cloe_authority_receipt_sqlite",
        ).ddl_if(dialect="sqlite"),
    )

    authority_receipt_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    attestation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    attestation_signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer_id: Mapped[str] = mapped_column(String(160), nullable=False)
    issuer_contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    issuer_contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    issuer_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer_actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ClosedLoopEvidenceIssuanceRow(Base):
    __tablename__ = "closed_loop_evidence_issuances"
    __table_args__ = (
        UniqueConstraint("authority_receipt_id", name="uq_cloe_issuance_authority_receipt"),
        ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_records.id"],
            name="fk_cloe_issuance_evidence",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$' AND "
            "attestation_sha256 ~ '^[0-9a-f]{64}$' AND "
            "attestation_signature_sha256 ~ '^[0-9a-f]{64}$' AND "
            "source IN ('closed-loop-experiment-receipt',"
            "'closed-loop-cost-receipt',"
            "'closed-loop-business-outcome-receipt',"
            "'closed-loop-review-authority-receipt')",
            name="ck_cloe_issuance",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["authority_receipt_id"],
            ["closed_loop_authority_receipts.authority_receipt_id"],
            name="fk_cloe_issuance_authority_receipt",
            ondelete="RESTRICT",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    authority_receipt_id: Mapped[str] = mapped_column(String(160), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    attestation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    attestation_signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ClosedLoopOutcomeBundleRow(Base):
    __tablename__ = "closed_loop_outcome_bundles"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_cloe_bundle_exact_scope",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "idempotency_sha256",
            name="uq_cloe_scope_idempotency",
        ),
        ForeignKeyConstraint(
            [
                "agent_run_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
            ],
            [
                "agent_runtime_run_envelopes.run_id",
                "agent_runtime_run_envelopes.tenant_ref",
                "agent_runtime_run_envelopes.entity_ref",
                "agent_runtime_run_envelopes.store_ref",
                "agent_runtime_run_envelopes.authority_sha256",
            ],
            name="fk_cloe_agent_run_exact_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "agent_run_ref",
                "agent_run_terminal_event_sha256",
            ],
            [
                "agent_runtime_run_events.run_id",
                "agent_runtime_run_events.event_sha256",
            ],
            name="fk_cloe_agent_run_terminal_receipt",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "sample_size > 0 AND minimum_sample_size > 0",
            name="ck_cloe_sample_sizes",
        ),
        CheckConstraint("cost_amount_minor_units >= 0", name="ck_cloe_cost_amount"),
        CheckConstraint(
            "experiment_confidence_level > 0 AND "
            "experiment_confidence_level <= 1 AND "
            "outcome_confidence_level > 0 AND outcome_confidence_level <= 1",
            name="ck_cloe_confidence_range",
        ),
        CheckConstraint(
            "lower(experiment_confidence_level::text) NOT IN "
            "('nan','infinity','-infinity') AND "
            "lower(outcome_confidence_level::text) NOT IN "
            "('nan','infinity','-infinity')",
            name="ck_cloe_confidence_finite",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "lower(outcome_value_decimal::text) NOT IN ('nan','infinity','-infinity')",
            name="ck_cloe_outcome_value_finite",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(metric_unit = 'minor_currency_units' AND "
            "metric_currency ~ '^[A-Z]{3}$' AND "
            "cost_currency = metric_currency) OR "
            "(metric_unit <> 'minor_currency_units' AND metric_currency IS NULL)",
            name="ck_cloe_metric_currency",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(metric_unit = 'minor_currency_units' AND "
            "length(metric_currency) = 3 AND cost_currency = metric_currency) OR "
            "(metric_unit <> 'minor_currency_units' AND metric_currency IS NULL)",
            name="ck_cloe_metric_currency_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "causal_claim_allowed IS FALSE",
            name="ck_cloe_association_only_v1",
        ),
        CheckConstraint(
            "effective_at <= data_as_of AND data_as_of <= authority_checked_at "
            "AND recorded_at = authority_checked_at "
            "AND authority_checked_at < review_due_at",
            name="ck_cloe_temporal_window",
        ),
        CheckConstraint(
            "actor_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$'",
            name="ck_cloe_bundle_actor",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "actor_id <> ''",
            name="ck_cloe_bundle_actor_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND "
            "registry_sha256 ~ '^[0-9a-f]{64}$' AND "
            "idempotency_sha256 ~ '^[0-9a-f]{64}$' AND "
            "request_sha256 ~ '^[0-9a-f]{64}$' AND "
            "bundle_sha256 ~ '^[0-9a-f]{64}$' AND "
            "agent_run_terminal_event_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_cloe_bundle_hashes",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_cloe_scope_recorded",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "recorded_at",
        ),
    )

    bundle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    agent_run_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_run_terminal_event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    registry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    bundle_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authority_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    experiment_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    experiment_method: Mapped[str] = mapped_column(String(80), nullable=False)
    treatment_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    control_ref: Mapped[str | None] = mapped_column(String(160))
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    experiment_confidence_level: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    experiment_independent_review_passed: Mapped[bool] = mapped_column(nullable=False)
    metric_id: Mapped[str] = mapped_column(String(160), nullable=False)
    metric_unit: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_currency: Mapped[str | None] = mapped_column(String(3))
    experiment_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    experiment_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cost_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    cost_amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cost_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cost_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cost_allocation_method: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    outcome_value_decimal: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    outcome_interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome_interval_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome_confidence_level: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    outcome_independent_review_passed: Mapped[bool] = mapped_column(nullable=False)
    causal_claim_allowed: Mapped[bool] = mapped_column(nullable=False)


class ClosedLoopOutcomeEvidenceLinkRow(Base):
    __tablename__ = "closed_loop_outcome_evidence_links"
    __table_args__ = (
        UniqueConstraint("bundle_id", "purpose", name="uq_cloe_link_purpose"),
        UniqueConstraint("evidence_id", name="uq_cloe_evidence_single_purpose"),
        CheckConstraint(
            "purpose IN ('experiment','cost','business_outcome')",
            name="ck_cloe_link_purpose",
        ),
        CheckConstraint(
            "scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND "
            "evidence_sha256 ~ '^[0-9a-f]{64}$' AND "
            "claims_sha256 ~ '^[0-9a-f]{64}$' AND "
            "link_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_cloe_link_hashes",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["bundle_id", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "closed_loop_outcome_bundles.bundle_id",
                "closed_loop_outcome_bundles.tenant_ref",
                "closed_loop_outcome_bundles.entity_ref",
                "closed_loop_outcome_bundles.store_ref",
                "closed_loop_outcome_bundles.scope_grant_authority_sha256",
            ],
            name="fk_cloe_link_exact_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "evidence_id",
                "evidence_sha256",
                "evidence_source",
                "evidence_source_ref",
                "evidence_grade",
                "evidence_effective_at",
            ],
            [
                "evidence_records.id",
                "evidence_records.blob_sha256",
                "evidence_records.source",
                "evidence_records.source_ref",
                "evidence_records.grade",
                "evidence_records.effective_at",
            ],
            name="fk_cloe_link_evidence_binding",
            ondelete="RESTRICT",
        ),
        Index("ix_cloe_link_bundle", "bundle_id", "purpose"),
    )

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    evidence_effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_effective_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issuer_actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    claims_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    link_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class ClosedLoopOutcomeEventRow(Base):
    __tablename__ = "closed_loop_outcome_events"
    __table_args__ = (
        UniqueConstraint("bundle_id", "event_index", name="uq_cloe_event_index"),
        UniqueConstraint("bundle_id", "idempotency_sha256", name="uq_cloe_event_idempotency"),
        ForeignKeyConstraint(
            ["bundle_id", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "closed_loop_outcome_bundles.bundle_id",
                "closed_loop_outcome_bundles.tenant_ref",
                "closed_loop_outcome_bundles.entity_ref",
                "closed_loop_outcome_bundles.store_ref",
                "closed_loop_outcome_bundles.scope_grant_authority_sha256",
            ],
            name="fk_cloe_event_exact_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "occurred_at <= recorded_at",
            name="ck_cloe_event_bitemporal",
        ),
        CheckConstraint(
            "actor_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$' AND "
            "reason_code ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$'",
            name="ck_cloe_event_tokens",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "actor_id <> '' AND reason_code <> ''",
            name="ck_cloe_event_tokens_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint("event_index > 0", name="ck_cloe_event_index"),
        CheckConstraint(
            "event_type IN ('bundle_recorded','review_requested','invalidated','revoked','superseded')",
            name="ck_cloe_event_type",
        ),
        CheckConstraint(
            "scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND "
            "idempotency_sha256 ~ '^[0-9a-f]{64}$' AND "
            "request_sha256 ~ '^[0-9a-f]{64}$' AND "
            "previous_event_sha256 ~ '^[0-9a-f]{64}$' AND "
            "event_sha256 ~ '^[0-9a-f]{64}$' AND "
            "evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_cloe_event_hashes",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(event_type='bundle_recorded' AND review_evidence_id IS NULL "
            "AND review_evidence_sha256 IS NULL AND review_evidence_source IS NULL "
            "AND review_evidence_source_ref IS NULL AND review_evidence_grade IS NULL "
            "AND review_evidence_effective_at IS NULL "
            "AND review_attestation_sha256 IS NULL AND replacement_bundle_id IS NULL) "
            "OR (event_type IN ('review_requested','invalidated','revoked') "
            "AND review_evidence_id IS NOT NULL "
            "AND review_attestation_sha256 IS NOT NULL "
            "AND replacement_bundle_id IS NULL) "
            "OR (event_type='superseded' AND review_evidence_id IS NOT NULL "
            "AND review_attestation_sha256 IS NOT NULL "
            "AND replacement_bundle_id IS NOT NULL)",
            name="ck_cloe_event_review_authority",
        ),
        ForeignKeyConstraint(
            [
                "evidence_id",
                "evidence_sha256",
                "evidence_source",
                "evidence_source_ref",
                "evidence_grade",
                "evidence_effective_at",
            ],
            [
                "evidence_records.id",
                "evidence_records.blob_sha256",
                "evidence_records.source",
                "evidence_records.source_ref",
                "evidence_records.grade",
                "evidence_records.effective_at",
            ],
            name="fk_cloe_event_evidence_binding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "review_evidence_id",
                "review_evidence_sha256",
                "review_evidence_source",
                "review_evidence_source_ref",
                "review_evidence_grade",
                "review_evidence_effective_at",
            ],
            [
                "evidence_records.id",
                "evidence_records.blob_sha256",
                "evidence_records.source",
                "evidence_records.source_ref",
                "evidence_records.grade",
                "evidence_records.effective_at",
            ],
            name="fk_cloe_event_review_evidence_binding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "replacement_bundle_id",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
            ],
            [
                "closed_loop_outcome_bundles.bundle_id",
                "closed_loop_outcome_bundles.tenant_ref",
                "closed_loop_outcome_bundles.entity_ref",
                "closed_loop_outcome_bundles.store_ref",
                "closed_loop_outcome_bundles.scope_grant_authority_sha256",
            ],
            name="fk_cloe_event_replacement_exact_scope",
            ondelete="RESTRICT",
        ),
        Index("ix_cloe_event_bundle", "bundle_id", "event_index"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    evidence_effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_evidence_id: Mapped[str | None] = mapped_column(String)
    review_evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    review_evidence_source: Mapped[str | None] = mapped_column(String(160))
    review_evidence_source_ref: Mapped[str | None] = mapped_column(Text)
    review_evidence_grade: Mapped[str | None] = mapped_column(String(1))
    review_evidence_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_attestation_sha256: Mapped[str | None] = mapped_column(String(64))
    replacement_bundle_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClosedLoopEvolutionRegistry:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = dict(payload)
        self.content_sha256 = _hash_json(self.payload)
        self._validate()

    @classmethod
    def load(cls, path: Path = REGISTRY_PATH) -> ClosedLoopEvolutionRegistry:
        registry = cls(json.loads(path.read_text(encoding="utf-8")))
        if registry.content_sha256 != EXPECTED_REGISTRY_CONTENT_SHA256:
            raise RuntimeError("Closed-loop registry content seal drifted")
        return registry

    def _validate(self) -> None:
        if (
            self.payload.get("contract_id") != CONTRACT_ID
            or self.payload.get("contract_version") != CONTRACT_VERSION
            or tuple(self.payload.get("purposes", ())) != PURPOSES
            or tuple(self.payload.get("event_types", ())) != EVENT_TYPES
        ):
            raise ClosedLoopContractError("Closed-loop registry identity drifted")
        contracts = self.payload.get("evidence_contracts")
        schema_manifests = self.payload.get("authority_claim_schemas")
        causal_policy = self.payload.get("causal_policy")
        if not isinstance(contracts, dict) or set(contracts) != set(PURPOSES):
            raise ClosedLoopContractError("Closed-loop Evidence contracts drifted")
        if schema_manifests != CLOSED_LOOP_AUTHORITY_SCHEMA_MANIFESTS:
            raise ClosedLoopContractError("Closed-loop claim schemas drifted")
        if (
            not isinstance(causal_policy, dict)
            or set(causal_policy) != set(self.payload.get("causal_methods", ()))
            or self.payload.get("causal_claims_enabled") is not False
            or self.payload.get("causal_status")
            != "association_only_until_estimator_ci_randomization_attrition_and_parallel_trends_authorities_are_registered"
        ):
            raise ClosedLoopContractError("Closed-loop causal policy drifted")
        for purpose in PURPOSES:
            expected = CLOSED_LOOP_AUTHORITY_CONTRACTS[purpose]
            contract = contracts[purpose]
            if (
                not isinstance(contract, dict)
                or set(contract) != _PUBLIC_AUTHORITY_CONTRACT_KEYS
                or any(
                    contract.get(field) != expected[field]
                    for field in _PUBLIC_AUTHORITY_CONTRACT_KEYS
                )
            ):
                raise ClosedLoopContractError("Closed-loop Evidence identity drifted")
            if expected["fields"] != frozenset(schema_manifests[purpose]["required_fields"]):
                raise ClosedLoopContractError("Closed-loop claim field seal drifted")
        review_contract = self.payload.get("review_authority_contract")
        expected_review = CLOSED_LOOP_AUTHORITY_CONTRACTS["review_event"]
        if (
            not isinstance(review_contract, dict)
            or set(review_contract) != _PUBLIC_AUTHORITY_CONTRACT_KEYS
            or any(
                review_contract.get(field) != expected_review[field]
                for field in _PUBLIC_AUTHORITY_CONTRACT_KEYS
            )
            or expected_review["fields"] != frozenset(schema_manifests["review_event"]["required_fields"])
        ):
            raise ClosedLoopContractError("Closed-loop review authority drifted")
        handoff = self.payload.get("bas177_handoff")
        if not isinstance(handoff, dict) or handoff != {
            "contract_id": "kjds-bas177-closed-loop-evolution-observation-v1",
            "contract_version": "1.0.0",
            "learning_input_type": "association_only_outcome",
            "statuses": ["ready", "review_due", "invalidated"],
            "opaque_scope_binding": True,
            "opaque_citation": True,
            "causal_claim_allowed": False,
            "learning_eligibility": "observation_only",
            "candidate_created": False,
            "transition_allowed": False,
            "promotion_allowed": False,
            "writes": 0,
            "content_sha256": "canonical_payload_sha256",
            "seal_sha256": "server_owned_hmac_sha256_over_full_payload",
        }:
            raise ClosedLoopContractError("BAS-177 handoff contract drifted")


class GovernedClosedLoopEvolutionWorkspace:
    """Append-only exact-scope Outcome bundle and BAS-177 handoff projection."""

    def __init__(
        self,
        *,
        engine: Any,
        evidence: EvidenceService,
        scope_grants: Any,
        registry: ClosedLoopEvolutionRegistry | None = None,
        clock: Callable[[], datetime] | None = None,
        handoff_sealing_key: bytes | None = None,
        agent_run_receipts: Any | None = None,
        event_evidence_issuer: Any | None = None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scope_grants = scope_grants
        self.registry = registry or ClosedLoopEvolutionRegistry.load()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.agent_run_receipts = agent_run_receipts or SqlAgentRuntimeEvidenceLedger(
            engine=engine,
            evidence=evidence,
        )
        self.event_evidence_issuer = event_evidence_issuer
        if engine.dialect.name == "postgresql" and not callable(
            getattr(event_evidence_issuer, "issue_event_evidence", None)
        ):
            raise RuntimeError("PostgreSQL closed-loop event Evidence issuer is required")
        configured_handoff_key = os.getenv("KJDS_STRATEGIC_BENCHMARK_SEALING_KEY", "").encode()
        secret = handoff_sealing_key or configured_handoff_key
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise RuntimeError("KJDS_STRATEGIC_BENCHMARK_SEALING_KEY must contain at least 32 bytes")
        self._handoff_key = hmac.new(
            secret,
            b"bas177-closed-loop-observation-v1",
            hashlib.sha256,
        ).digest()

    def record(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        agent_run_ref: str,
        experiment_evidence_ref: str,
        cost_evidence_ref: str,
        outcome_evidence_ref: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_role(principal, WRITE_ROLES)
        checked_at = _aware(self.clock(), "trusted clock")
        data_as_of = _aware(as_of, "as_of")
        if data_as_of > checked_at:
            raise ClosedLoopContractError("data as_of cannot be in the future")
        scope = self._scope(principal, store_ref, checked_at)
        actor_id = _token(principal.actor_id, "actor_id")
        refs = {
            "agent_run_ref": _token(agent_run_ref, "agent_run_ref"),
            "experiment": _token(experiment_evidence_ref, "experiment_evidence_ref"),
            "cost": _token(cost_evidence_ref, "cost_evidence_ref"),
            "business_outcome": _token(outcome_evidence_ref, "outcome_evidence_ref"),
        }
        if len(set(refs.values())) != len(refs):
            raise ClosedLoopContractError("Closed-loop authority references must differ")
        key = _token(idempotency_key, "idempotency_key")
        request = {
            "contract_id": CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "registry_sha256": self.registry.content_sha256,
            "scope": scope,
            "actor_id": actor_id,
            "data_as_of": _iso(data_as_of),
            "agent_run_ref": refs["agent_run_ref"],
            "experiment_evidence_ref": refs["experiment"],
            "cost_evidence_ref": refs["cost"],
            "outcome_evidence_ref": refs["business_outcome"],
            "idempotency_key": key,
        }
        request_sha256 = _jsonb_hash(request)
        idempotency_sha256 = _hash_text(key)
        try:
            with Session(self.engine) as session, session.begin():
                self._lock(session, scope, idempotency_sha256)
                winner = self._winner(session, scope, idempotency_sha256)
                if winner is not None:
                    final_checked_at = self._recheck_scope(
                        principal=principal,
                        store_ref=store_ref,
                        expected_scope=scope,
                    )
                    return self._winner_projection(session, winner, request_sha256, final_checked_at)
                run, terminal, agent_run_evidence_ids = self._agent_run(
                    session,
                    scope,
                    refs["agent_run_ref"],
                    checked_at,
                    data_as_of,
                )
                supporting = {
                    purpose: self._supporting(
                        session,
                        evidence_id=refs[purpose],
                        purpose=purpose,
                        scope=scope,
                        data_as_of=data_as_of,
                        checked_at=checked_at,
                    )
                    for purpose in PURPOSES
                }
                self._cross_validate(
                    supporting,
                    run_ref=run.run_id,
                    data_as_of=data_as_of,
                    terminal=terminal,
                    recorder_actor_id=actor_id,
                )
                experiment = supporting["experiment"]["claims"]
                cost = supporting["cost"]["claims"]
                outcome = supporting["business_outcome"]["claims"]
                effective_at = max(item["effective_at"] for item in supporting.values())
                review_due_at = min(item["review_due_at"] for item in supporting.values())
                # V1 receipts freeze the audit shape only. They do not yet bind
                # estimator/CI/randomization-integrity/attrition/parallel-trends
                # authority, so this ledger remains association-only.
                causal = False
                core = {
                    **request,
                    "agent_run_terminal_event_sha256": terminal.event_sha256,
                    "supporting": {
                        purpose: {
                            "evidence_id": item["row"].id,
                            "evidence_sha256": item["row"].blob_sha256,
                            "claims_sha256": item["claims_sha256"],
                            "issuer_actor_id": item["issuer_actor_id"],
                        }
                        for purpose, item in supporting.items()
                    },
                    "effective_at": _iso(effective_at),
                    "review_due_at": _iso(review_due_at),
                    "causal_claim_allowed": causal,
                }
                bundle_sha256 = _jsonb_hash(core)
                bundle_id = _stable_id("clob", bundle_sha256)
                row = ClosedLoopOutcomeBundleRow(
                    bundle_id=bundle_id,
                    tenant_ref=scope["tenant_ref"],
                    entity_ref=scope["entity_ref"],
                    store_ref=scope["store_ref"],
                    scope_grant_authority_sha256=scope["scope_grant_authority_sha256"],
                    actor_id=actor_id,
                    agent_run_ref=run.run_id,
                    agent_run_terminal_event_sha256=terminal.event_sha256,
                    contract_id=CONTRACT_ID,
                    contract_version=CONTRACT_VERSION,
                    registry_sha256=self.registry.content_sha256,
                    request_json=request,
                    bundle_json=core,
                    idempotency_sha256=idempotency_sha256,
                    request_sha256=request_sha256,
                    bundle_sha256=bundle_sha256,
                    data_as_of=data_as_of,
                    authority_checked_at=checked_at,
                    effective_at=effective_at,
                    review_due_at=review_due_at,
                    recorded_at=checked_at,
                    experiment_ref=experiment["experiment_ref"],
                    experiment_method=experiment["method"],
                    treatment_ref=experiment["treatment_ref"],
                    control_ref=experiment["control_ref"],
                    sample_size=experiment["sample_size"],
                    minimum_sample_size=experiment["minimum_sample_size"],
                    experiment_confidence_level=_decimal(
                        experiment["confidence_level_decimal"],
                        "experiment confidence",
                    ),
                    experiment_independent_review_passed=experiment["independent_review_passed"],
                    metric_id=experiment["metric_id"],
                    metric_unit=experiment["metric_unit"],
                    metric_currency=experiment["metric_currency"],
                    experiment_window_start=_aware(experiment["window_start"], "window_start"),
                    experiment_window_end=_aware(experiment["window_end"], "window_end"),
                    cost_ref=cost["cost_ref"],
                    cost_amount_minor_units=cost["amount_minor_units"],
                    cost_currency=cost["currency"],
                    cost_period_start=_aware(cost["period_start"], "period_start"),
                    cost_period_end=_aware(cost["period_end"], "period_end"),
                    cost_allocation_method=cost["allocation_method"],
                    outcome_ref=outcome["outcome_ref"],
                    outcome_value_decimal=_decimal(outcome["value_decimal"], "value_decimal"),
                    outcome_interval_start=_aware(outcome["interval_start"], "interval_start"),
                    outcome_interval_end=_aware(outcome["interval_end"], "interval_end"),
                    outcome_confidence_level=_decimal(
                        outcome["confidence_level_decimal"],
                        "outcome confidence",
                    ),
                    outcome_independent_review_passed=outcome["independent_review_passed"],
                    causal_claim_allowed=causal,
                )
                session.add(row)
                session.flush()
                for purpose, item in supporting.items():
                    evidence_row = item["row"]
                    link_sha = _link_hash(
                        bundle_id=bundle_id,
                        purpose=purpose,
                        evidence_id=evidence_row.id,
                        evidence_sha256=evidence_row.blob_sha256,
                        claims_sha256=item["claims_sha256"],
                        issuer_actor_id=item["issuer_actor_id"],
                        scope=scope,
                    )
                    session.add(
                        ClosedLoopOutcomeEvidenceLinkRow(
                            link_id=_stable_id("clol", link_sha),
                            bundle_id=bundle_id,
                            tenant_ref=row.tenant_ref,
                            entity_ref=row.entity_ref,
                            store_ref=row.store_ref,
                            scope_grant_authority_sha256=row.scope_grant_authority_sha256,
                            purpose=purpose,
                            evidence_id=evidence_row.id,
                            evidence_sha256=evidence_row.blob_sha256,
                            evidence_source=evidence_row.source,
                            evidence_source_ref=evidence_row.source_ref,
                            evidence_grade=evidence_row.grade,
                            evidence_effective_at=item["effective_at"],
                            evidence_effective_until=item["effective_until"],
                            evidence_recorded_at=item["recorded_at"],
                            evidence_review_due_at=item["review_due_at"],
                            issuer_actor_id=item["issuer_actor_id"],
                            claims_sha256=item["claims_sha256"],
                            link_sha256=link_sha,
                        )
                    )
                session.flush()
                self._append_event(
                    session,
                    row=row,
                    event_type="bundle_recorded",
                    reason_code="independent_authorities_verified",
                    actor_id=actor_id,
                    idempotency_key=key,
                    occurred_at=checked_at,
                )
                final_checked_at = self._recheck_scope(
                    principal=principal,
                    store_ref=store_ref,
                    expected_scope=scope,
                )
                self._reverify_agent_run_current(
                    session,
                    run_ref=run.run_id,
                    terminal_event_sha256=terminal.event_sha256,
                    evidence_ids=agent_run_evidence_ids,
                    scope=scope,
                    data_as_of=data_as_of,
                    checked_at=final_checked_at,
                )
                return self._project(
                    session,
                    row,
                    final_checked_at,
                    idempotent=False,
                    agent_run_preverified=True,
                )
        except IntegrityError:
            with Session(self.engine) as session:
                winner = self._winner(session, scope, idempotency_sha256)
                if winner is None:
                    raise
                final_checked_at = self._recheck_scope(
                    principal=principal,
                    store_ref=store_ref,
                    expected_scope=scope,
                )
                return self._winner_projection(session, winner, request_sha256, final_checked_at)

    def append_review_event(
        self,
        *,
        principal: Principal,
        store_ref: str,
        bundle_id: str,
        event_type: Literal["review_requested", "invalidated", "revoked", "superseded"],
        reason_code: str,
        review_evidence_ref: str,
        idempotency_key: str,
        replacement_bundle_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_role(principal, REVIEW_ROLES)
        if event_type not in EVENT_TYPES[1:]:
            raise ClosedLoopContractError("Unsupported closed-loop review event")
        checked_at = _aware(self.clock(), "trusted clock")
        scope = self._scope(principal, store_ref, checked_at)
        actor_id = _token(principal.actor_id, "actor_id")
        identifier = _token(bundle_id, "bundle_id")
        reason = _token(reason_code, "reason_code")
        review_ref = _token(review_evidence_ref, "review_evidence_ref")
        replacement = (
            _token(replacement_bundle_id, "replacement_bundle_id") if replacement_bundle_id is not None else None
        )
        if (event_type == "superseded") != (replacement is not None):
            raise ClosedLoopContractError("Supersession requires one replacement bundle")
        key = _token(idempotency_key, "idempotency_key")
        request = {
            "bundle_id": identifier,
            "event_type": event_type,
            "reason_code": reason,
            "actor_id": actor_id,
            "review_evidence_ref": review_ref,
            "replacement_bundle_id": replacement,
            "idempotency_key": key,
            "scope": scope,
        }
        request_sha = _jsonb_hash(request)
        with Session(self.engine) as session, session.begin():
            self._lock(session, scope, _hash_text(key))
            row = session.scalar(
                self._scope_query(scope).where(ClosedLoopOutcomeBundleRow.bundle_id == identifier).with_for_update()
            )
            if row is None:
                raise KeyError("Closed-loop bundle not found")
            existing = session.scalar(
                select(ClosedLoopOutcomeEventRow).where(
                    ClosedLoopOutcomeEventRow.bundle_id == identifier,
                    ClosedLoopOutcomeEventRow.idempotency_sha256 == _hash_text(key),
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha:
                    raise ClosedLoopContractError("Closed-loop event idempotency drifted")
                final_checked_at = self._recheck_scope(
                    principal=principal,
                    store_ref=store_ref,
                    expected_scope=scope,
                )
                return self._project(session, row, final_checked_at, idempotent=True)
            review = self._supporting(
                session,
                evidence_id=review_ref,
                purpose="review_event",
                scope=scope,
                data_as_of=checked_at,
                checked_at=checked_at,
            )
            review_claims = review["claims"]
            if (
                review_claims["bundle_id"] != identifier
                or review_claims["event_type"] != event_type
                or review_claims["reason_code"] != reason
                or review_claims["requested_by_actor_id"] != actor_id
                or review_claims["replacement_bundle_id"] != replacement
            ):
                raise ClosedLoopContractError("Closed-loop review authority binding drifted")
            supporting_issuers = set(
                session.scalars(
                    select(ClosedLoopOutcomeEvidenceLinkRow.issuer_actor_id).where(
                        ClosedLoopOutcomeEvidenceLinkRow.bundle_id == identifier
                    )
                )
            )
            if (
                review["issuer_actor_id"] in supporting_issuers
                or review["issuer_actor_id"] == row.actor_id
                or review["issuer_actor_id"] == actor_id
            ):
                raise ClosedLoopContractError("Closed-loop review authority must be independent")
            if replacement is not None:
                replacement_row = session.scalar(
                    self._scope_query(scope).where(ClosedLoopOutcomeBundleRow.bundle_id == replacement)
                )
                if replacement_row is None or replacement_row.bundle_id == row.bundle_id:
                    raise ClosedLoopContractError("Closed-loop replacement bundle is invalid")
                if self._project(session, replacement_row, checked_at, idempotent=True)["status"] != "current":
                    raise ClosedLoopContractError("Closed-loop replacement bundle is not current")
            _, current_terminal, agent_run_evidence_ids = self._agent_run(
                session,
                scope,
                row.agent_run_ref,
                checked_at,
                _stored_utc(row.data_as_of, "bundle.data_as_of"),
            )
            if current_terminal.event_sha256 != row.agent_run_terminal_event_sha256:
                raise ClosedLoopContractError("AgentRun terminal receipt binding drifted")
            self._append_event(
                session,
                row=row,
                event_type=event_type,
                reason_code=reason,
                actor_id=actor_id,
                idempotency_key=key,
                occurred_at=checked_at,
                request_sha256=request_sha,
                request_json=request,
                review=review,
                replacement_bundle_id=replacement,
            )
            final_checked_at = self._recheck_scope(
                principal=principal,
                store_ref=store_ref,
                expected_scope=scope,
            )
            self._reverify_agent_run_current(
                session,
                run_ref=row.agent_run_ref,
                terminal_event_sha256=row.agent_run_terminal_event_sha256,
                evidence_ids=agent_run_evidence_ids,
                scope=scope,
                data_as_of=_stored_utc(row.data_as_of, "bundle.data_as_of"),
                checked_at=final_checked_at,
            )
            return self._project(
                session,
                row,
                final_checked_at,
                idempotent=False,
                agent_run_preverified=True,
            )

    def get(self, *, principal: Principal, store_ref: str, bundle_id: str) -> dict[str, Any]:
        self._require_role(principal, READ_ROLES)
        checked_at = _aware(self.clock(), "trusted clock")
        scope = self._scope(principal, store_ref, checked_at)
        with Session(self.engine) as session:
            row = session.scalar(
                self._scope_query(scope).where(ClosedLoopOutcomeBundleRow.bundle_id == _token(bundle_id, "bundle_id"))
            )
            if row is None:
                raise KeyError("Closed-loop bundle not found")
            self._project(session, row, checked_at, idempotent=True)
            final_checked_at = self._recheck_scope(
                principal=principal,
                store_ref=store_ref,
                expected_scope=scope,
            )
            return self._project(session, row, final_checked_at, idempotent=True)

    def bas177_handoff(self, *, principal: Principal, store_ref: str, bundle_id: str) -> Bas177ClosedLoopObservation:
        """Return the only observation form that may cross into BAS-177."""
        projection = self.get(
            principal=principal,
            store_ref=store_ref,
            bundle_id=bundle_id,
        )
        status_map: dict[str, Literal["ready", "review_due", "invalidated"]] = {
            "current": "ready",
            "review_due": "review_due",
            "invalidated": "invalidated",
        }
        status = status_map.get(str(projection.get("status")))
        if status is None:
            raise ClosedLoopContractError("Closed-loop handoff status is invalid")
        scope = {
            field: projection.get(field)
            for field in (
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
            )
        }
        if any(not isinstance(value, str) for value in scope.values()):
            raise ClosedLoopContractError("Closed-loop handoff scope is invalid")
        evidence_summary = projection.get("supporting_evidence")
        if not isinstance(evidence_summary, list) or len(evidence_summary) != len(PURPOSES):
            raise ClosedLoopContractError("Closed-loop handoff Evidence is invalid")
        scope_binding = _opaque_token(
            self._handoff_key,
            domain=b"scope",
            payload=scope,
            prefix="clhs",
        )
        citation = _opaque_token(
            self._handoff_key,
            domain=b"citation",
            payload={
                "bundle_sha256": projection.get("bundle_sha256"),
                "event_chain_sha256": projection.get("event_chain_sha256"),
                "supporting_evidence": evidence_summary,
            },
            prefix="clhc",
        )
        observation = Bas177ClosedLoopObservation(
            contract_id="kjds-bas177-closed-loop-evolution-observation-v1",
            contract_version="1.0.0",
            learning_input_type="association_only_outcome",
            status=status,
            reason_code=_token(projection.get("reason_code"), "handoff reason_code"),
            opaque_scope_binding=scope_binding,
            opaque_citation=citation,
            bundle_sha256=_sha(projection.get("bundle_sha256"), "bundle_sha256"),
            event_chain_sha256=_sha(projection.get("event_chain_sha256"), "event_chain_sha256"),
            supporting_evidence_sha256=_hash_json(evidence_summary),
            data_as_of=_iso(_aware(projection.get("data_as_of"), "data_as_of")),
            latest_event_type=_token(projection.get("latest_event_type"), "latest_event_type"),
            latest_event_occurred_at=_iso(
                _aware(
                    projection.get("latest_event_occurred_at"),
                    "latest_event_occurred_at",
                )
            ),
            latest_event_recorded_at=_iso(
                _aware(
                    projection.get("latest_event_recorded_at"),
                    "latest_event_recorded_at",
                )
            ),
            invalidation_conditions=(
                "scope_authority_rotation",
                "supporting_evidence_expiry",
                "review_due",
                "contract_or_hash_drift",
            ),
        )
        payload = observation.payload()
        sealed = replace(
            observation,
            content_sha256=_hash_json(payload),
            seal_sha256=_handoff_seal(self._handoff_key, payload),
        )
        sealed.verify(sealing_key=self._handoff_key)
        return sealed

    def verify_bas177_handoff(self, observation: Bas177ClosedLoopObservation) -> None:
        observation.verify(sealing_key=self._handoff_key)

    def list_current(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        limit: int = 50,
    ) -> dict[str, Any]:
        self._require_role(principal, READ_ROLES)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ClosedLoopContractError("limit must be between 1 and 100")
        checked_at = _aware(self.clock(), "trusted clock")
        cutoff = _aware(as_of, "as_of")
        if cutoff > checked_at:
            raise ClosedLoopContractError("as_of cannot be in the future")
        scope = self._scope(principal, store_ref, checked_at)
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    self._scope_query(scope)
                    .where(
                        ClosedLoopOutcomeBundleRow.data_as_of <= cutoff,
                        ClosedLoopOutcomeBundleRow.recorded_at <= cutoff,
                    )
                    .order_by(
                        ClosedLoopOutcomeBundleRow.recorded_at.desc(),
                        ClosedLoopOutcomeBundleRow.bundle_id.desc(),
                    )
                    .limit(limit)
                )
            )
            _ = [
                self._project(
                    session,
                    row,
                    checked_at,
                    idempotent=True,
                    transaction_cutoff=cutoff,
                )
                for row in rows
            ]
            final_checked_at = self._recheck_scope(
                principal=principal,
                store_ref=store_ref,
                expected_scope=scope,
            )
            items = [
                self._project(
                    session,
                    row,
                    final_checked_at,
                    idempotent=True,
                    transaction_cutoff=cutoff,
                )
                for row in rows
            ]
        return {
            "contract_id": CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "registry_sha256": self.registry.content_sha256,
            "items": items,
            "count": len(items),
            "external_write": False,
        }

    def _scope(self, principal: Principal, store_ref: str, checked_at: datetime) -> dict[str, str]:
        store = _token(store_ref, "store_ref")
        if not principal.can_access_store(store):
            raise KeyError("Closed-loop exact scope unavailable")
        try:
            authority = self.scope_grants.current(
                principal=principal,
                store_ref=store,
                as_of=checked_at,
            )
        except (KeyError, PermissionError, ValueError, RuntimeError, TypeError):
            raise KeyError("Closed-loop exact scope unavailable") from None
        raw = {
            "tenant_ref": authority.get("tenant_ref"),
            "entity_ref": authority.get("entity_ref"),
            "store_ref": authority.get("store_ref"),
            "scope_grant_authority_sha256": authority.get("authority_sha256"),
        }
        if authority.get("status") != "ready" or any(not isinstance(value, str) for value in raw.values()):
            raise KeyError("Closed-loop exact scope unavailable")
        scope = {
            "tenant_ref": _token(raw["tenant_ref"], "tenant_ref"),
            "entity_ref": _token(raw["entity_ref"], "entity_ref"),
            "store_ref": _token(raw["store_ref"], "store_ref"),
            "scope_grant_authority_sha256": _sha(raw["scope_grant_authority_sha256"], "authority_sha256"),
        }
        if scope["tenant_ref"] != principal.tenant_ref or scope["store_ref"] != store:
            raise KeyError("Closed-loop exact scope unavailable")
        return scope

    @staticmethod
    def _scope_query(scope: Mapping[str, str]):
        return select(ClosedLoopOutcomeBundleRow).where(
            ClosedLoopOutcomeBundleRow.tenant_ref == scope["tenant_ref"],
            ClosedLoopOutcomeBundleRow.entity_ref == scope["entity_ref"],
            ClosedLoopOutcomeBundleRow.store_ref == scope["store_ref"],
            ClosedLoopOutcomeBundleRow.scope_grant_authority_sha256 == scope["scope_grant_authority_sha256"],
        )

    @staticmethod
    def _winner(
        session: Session, scope: Mapping[str, str], idempotency_sha256: str
    ) -> ClosedLoopOutcomeBundleRow | None:
        return session.scalar(
            select(ClosedLoopOutcomeBundleRow).where(
                ClosedLoopOutcomeBundleRow.tenant_ref == scope["tenant_ref"],
                ClosedLoopOutcomeBundleRow.entity_ref == scope["entity_ref"],
                ClosedLoopOutcomeBundleRow.store_ref == scope["store_ref"],
                ClosedLoopOutcomeBundleRow.scope_grant_authority_sha256 == scope["scope_grant_authority_sha256"],
                ClosedLoopOutcomeBundleRow.idempotency_sha256 == idempotency_sha256,
            )
        )

    @staticmethod
    def _lock(session: Session, scope: Mapping[str, str], key: str) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(hashtext('kjds-cloe-0096-lifecycle'))"))
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": _hash_text("|".join((*scope.values(), key)))},
            )

    def _agent_run(
        self,
        session: Session,
        scope: Mapping[str, str],
        run_ref: str,
        checked_at: datetime,
        data_as_of: datetime,
    ) -> tuple[
        AgentRuntimeRunEnvelopeRow,
        AgentRuntimeRunEventRow,
        tuple[str, ...],
    ]:
        run = session.scalar(
            select(AgentRuntimeRunEnvelopeRow).where(
                AgentRuntimeRunEnvelopeRow.run_id == run_ref,
                AgentRuntimeRunEnvelopeRow.tenant_ref == scope["tenant_ref"],
                AgentRuntimeRunEnvelopeRow.entity_ref == scope["entity_ref"],
                AgentRuntimeRunEnvelopeRow.store_ref == scope["store_ref"],
                AgentRuntimeRunEnvelopeRow.authority_sha256 == scope["scope_grant_authority_sha256"],
            )
        )
        run_events = list(
            session.scalars(
                select(AgentRuntimeRunEventRow)
                .where(AgentRuntimeRunEventRow.run_id == run_ref)
                .order_by(AgentRuntimeRunEventRow.event_index.desc())
            )
        )
        terminal = run_events[0] if run_events else None
        if run is None or terminal is None or terminal.event_type != "run_succeeded":
            raise ClosedLoopContractError("AgentRun outcome is not terminal success")
        context = AgentRunScopeContext(
            tenant_ref=scope["tenant_ref"],
            entity_ref=scope["entity_ref"],
            store_ref=scope["store_ref"],
            authority_sha256=scope["scope_grant_authority_sha256"],
            actor_id=run.actor_id,
            scope_as_of=checked_at,
            evidence_refs=(),
        )
        try:
            projection = self.agent_run_receipts.get_run(
                context=context,
                run_id=run_ref,
            )
            receipt = self.agent_run_receipts.replay(
                context=context,
                run_id=run_ref,
            )
        except Exception:
            raise ClosedLoopContractError("AgentRun governed receipt is invalid") from None
        events = projection.get("events")
        latest = events[-1] if isinstance(events, list) and events else None
        if (
            projection.get("contract_id") != "kjds-governed-agent-run-audit-v1"
            or projection.get("run_id") != run_ref
            or projection.get("status") != "succeeded"
            or projection.get("proposal_only") is not True
            or projection.get("formal_fact") is not False
            or projection.get("external_write_allowed") is not False
            or not isinstance(latest, dict)
            or latest.get("event_sha256") != terminal.event_sha256
            or receipt.contract_id != RUNTIME_CONTRACT_ID
            or receipt.run_id != run_ref
            or receipt.status != "succeeded"
            or receipt.event_count != len(events)
            or receipt.proposal_only is not True
            or receipt.formal_fact is not False
            or receipt.external_write_allowed is not False
        ):
            raise ClosedLoopContractError("AgentRun governed receipt drifted")
        ordered_rows = list(reversed(run_events))
        if len(events) != len(ordered_rows):
            raise ClosedLoopContractError("AgentRun event conservation drifted")
        current_evidence_ids: list[str] = []
        validated_events: list[dict[str, object]] = []
        for projected_event, event_row in zip(events, ordered_rows, strict=True):
            evidence_ref = projected_event.get("evidence") if isinstance(projected_event, dict) else None
            evidence_row = session.get(EvidenceRecordRow, event_row.evidence_id)
            evidence_blob = session.get(EvidenceBlobRow, evidence_row.blob_sha256) if evidence_row is not None else None
            try:
                evidence_payload = (
                    json.loads(bytes(evidence_blob.content_bytes).decode("utf-8"))
                    if evidence_blob is not None
                    else None
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                evidence_payload = None
            projected_payload = (
                {key: projected_event[key] for key in _AGENT_RUN_EVENT_CONTRACT.event_keys}
                if isinstance(projected_event, dict)
                and set(projected_event) == _AGENT_RUN_EVENT_CONTRACT.event_keys | {"evidence"}
                else None
            )
            row_payload = _agent_run_event_row_payload(event_row)
            if projected_payload is None or projected_payload != row_payload:
                raise ClosedLoopContractError("AgentRun event projection drifted")
            validated = _validate_agent_run_event_contract(
                projected_payload,
                previous=validated_events[-1] if validated_events else None,
                prior_events=validated_events,
                max_attempts=run.max_attempts,
            )
            expected_evidence_payload = {
                "contract_id": AGENT_RUN_EVIDENCE_CONTRACT,
                "run_id": run_ref,
                "event_id": event_row.event_id,
                **validated,
                "payload_status": "not_retained",
                "proposal_only": True,
                "formal_fact": False,
                "external_write_allowed": False,
            }
            metadata = evidence_row.metadata_json if evidence_row is not None else {}
            if (
                not isinstance(evidence_ref, dict)
                or set(evidence_ref) != {"evidence_id", "evidence_sha256"}
                or evidence_ref.get("evidence_id") != event_row.evidence_id
                or evidence_ref.get("evidence_sha256") != event_row.evidence_sha256
                or evidence_row is None
                or evidence_blob is None
                or evidence_payload != expected_evidence_payload
                or bytes(evidence_blob.content_bytes) != _agent_run_canonical(expected_evidence_payload)
                or hashlib.sha256(bytes(evidence_blob.content_bytes)).hexdigest() != evidence_blob.sha256
                or evidence_row.blob_sha256 != event_row.evidence_sha256
                or event_row.event_id != _agent_run_event_id(run_ref, event_row.event_sha256)
                or evidence_row.filename != f"{event_row.event_id}.json"
                or evidence_row.content_type != "application/json"
                or evidence_row.source != AGENT_RUN_EVIDENCE_SOURCE
                or evidence_row.grade != EvidenceGrade.B.value
                or evidence_row.source_ref != f"agent-run://{run_ref}/{event_row.event_id}"
                or evidence_row.created_by != "kjds-agent-runtime"
                or evidence_row.effective_until is not None
                or event_row.tenant_ref != scope["tenant_ref"]
                or event_row.entity_ref != scope["entity_ref"]
                or event_row.store_ref != scope["store_ref"]
                or event_row.authority_sha256 != scope["scope_grant_authority_sha256"]
                or not isinstance(metadata, dict)
                or set(metadata) != _AGENT_RUN_METADATA_KEYS
                or metadata.get("contract_id") != AGENT_RUN_EVIDENCE_CONTRACT
                or metadata.get("tenant_ref") != scope["tenant_ref"]
                or metadata.get("entity_ref") != scope["entity_ref"]
                or metadata.get("store_ref") != scope["store_ref"]
                or metadata.get("authority_sha256") != scope["scope_grant_authority_sha256"]
                or metadata.get("run_id") != run_ref
                or metadata.get("event_id") != event_row.event_id
                or metadata.get("event_type") != event_row.event_type
                or metadata.get("event_sha256") != event_row.event_sha256
                or metadata.get("retention_class") != "security"
                or metadata.get("legal_hold") is not False
                or _stored_utc(event_row.occurred_at, "event.occurred_at") > data_as_of
                or _stored_utc(event_row.recorded_at, "event.recorded_at") > data_as_of
                or _stored_utc(event_row.occurred_at, "event.occurred_at")
                > _stored_utc(event_row.recorded_at, "event.recorded_at")
                or _stored_utc(evidence_row.effective_at, "evidence.effective_at") > data_as_of
                or _stored_utc(evidence_row.recorded_at, "evidence.recorded_at") > data_as_of
                or _stored_utc(evidence_row.effective_at, "evidence.effective_at")
                != _stored_utc(event_row.occurred_at, "event.occurred_at")
                or _stored_utc(evidence_row.effective_at, "evidence.effective_at")
                > _stored_utc(evidence_row.recorded_at, "evidence.recorded_at")
            ):
                raise ClosedLoopContractError("AgentRun event Evidence drifted")
            current_evidence_ids.append(event_row.evidence_id)
            validated_events.append(validated)
        try:
            self.evidence.require_current_in_session(
                current_evidence_ids,
                as_of=checked_at,
                session=session,
            )
        except Exception:
            raise ClosedLoopContractError("AgentRun event Evidence is not current") from None
        evidence_row = session.get(EvidenceRecordRow, terminal.evidence_id)
        if (
            evidence_row is None
            or evidence_row.blob_sha256 != terminal.evidence_sha256
            or evidence_row.source != AGENT_RUN_EVIDENCE_SOURCE
            or evidence_row.metadata_json.get("event_sha256") != terminal.event_sha256
        ):
            raise ClosedLoopContractError("AgentRun terminal receipt binding drifted")
        return run, terminal, tuple(current_evidence_ids)

    def _reverify_agent_run_current(
        self,
        session: Session,
        *,
        run_ref: str,
        terminal_event_sha256: str,
        evidence_ids: Sequence[str],
        scope: Mapping[str, str],
        data_as_of: datetime,
        checked_at: datetime,
    ) -> None:
        run = session.scalar(
            select(AgentRuntimeRunEnvelopeRow).where(
                AgentRuntimeRunEnvelopeRow.run_id == run_ref,
                AgentRuntimeRunEnvelopeRow.tenant_ref == scope["tenant_ref"],
                AgentRuntimeRunEnvelopeRow.entity_ref == scope["entity_ref"],
                AgentRuntimeRunEnvelopeRow.store_ref == scope["store_ref"],
                AgentRuntimeRunEnvelopeRow.authority_sha256 == scope["scope_grant_authority_sha256"],
            )
        )
        rows = list(
            session.scalars(
                select(AgentRuntimeRunEventRow)
                .where(AgentRuntimeRunEventRow.run_id == run_ref)
                .order_by(AgentRuntimeRunEventRow.event_index)
            )
        )
        if (
            run is None
            or tuple(row.evidence_id for row in rows) != tuple(evidence_ids)
            or not rows
            or rows[-1].event_type != "run_succeeded"
            or rows[-1].event_sha256 != terminal_event_sha256
        ):
            raise ClosedLoopContractError("AgentRun event snapshot drifted")
        validated_events: list[dict[str, object]] = []
        for row in rows:
            payload = _validate_agent_run_event_contract(
                _agent_run_event_row_payload(row),
                previous=validated_events[-1] if validated_events else None,
                prior_events=validated_events,
                max_attempts=run.max_attempts,
            )
            evidence_row = session.get(EvidenceRecordRow, row.evidence_id)
            evidence_blob = session.get(EvidenceBlobRow, evidence_row.blob_sha256) if evidence_row is not None else None
            try:
                evidence_payload = (
                    json.loads(bytes(evidence_blob.content_bytes).decode("utf-8"))
                    if evidence_blob is not None
                    else None
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                evidence_payload = None
            expected_payload = {
                "contract_id": AGENT_RUN_EVIDENCE_CONTRACT,
                "run_id": run_ref,
                "event_id": row.event_id,
                **payload,
                "payload_status": "not_retained",
                "proposal_only": True,
                "formal_fact": False,
                "external_write_allowed": False,
            }
            metadata = evidence_row.metadata_json if evidence_row is not None else {}
            if (
                evidence_row is None
                or evidence_blob is None
                or evidence_payload != expected_payload
                or bytes(evidence_blob.content_bytes) != _agent_run_canonical(expected_payload)
                or hashlib.sha256(bytes(evidence_blob.content_bytes)).hexdigest() != evidence_blob.sha256
                or evidence_row.blob_sha256 != row.evidence_sha256
                or row.event_id != _agent_run_event_id(run_ref, row.event_sha256)
                or evidence_row.filename != f"{row.event_id}.json"
                or evidence_row.content_type != "application/json"
                or evidence_row.source != AGENT_RUN_EVIDENCE_SOURCE
                or evidence_row.grade != EvidenceGrade.B.value
                or evidence_row.source_ref != f"agent-run://{run_ref}/{row.event_id}"
                or evidence_row.created_by != "kjds-agent-runtime"
                or evidence_row.effective_until is not None
                or row.tenant_ref != scope["tenant_ref"]
                or row.entity_ref != scope["entity_ref"]
                or row.store_ref != scope["store_ref"]
                or row.authority_sha256 != scope["scope_grant_authority_sha256"]
                or not isinstance(metadata, dict)
                or set(metadata) != _AGENT_RUN_METADATA_KEYS
                or metadata.get("contract_id") != AGENT_RUN_EVIDENCE_CONTRACT
                or metadata.get("tenant_ref") != scope["tenant_ref"]
                or metadata.get("entity_ref") != scope["entity_ref"]
                or metadata.get("store_ref") != scope["store_ref"]
                or metadata.get("authority_sha256") != scope["scope_grant_authority_sha256"]
                or metadata.get("run_id") != run_ref
                or metadata.get("event_id") != row.event_id
                or metadata.get("event_type") != row.event_type
                or metadata.get("event_sha256") != row.event_sha256
                or metadata.get("retention_class") != "security"
                or metadata.get("legal_hold") is not False
                or _stored_utc(row.occurred_at, "event.occurred_at") > data_as_of
                or _stored_utc(row.recorded_at, "event.recorded_at") > data_as_of
                or _stored_utc(evidence_row.effective_at, "evidence.effective_at")
                != _stored_utc(row.occurred_at, "event.occurred_at")
                or _stored_utc(evidence_row.recorded_at, "evidence.recorded_at") > data_as_of
            ):
                raise ClosedLoopContractError("AgentRun event Evidence drifted")
            validated_events.append(payload)
        try:
            self.evidence.require_current_in_session(
                list(evidence_ids),
                as_of=checked_at,
                session=session,
            )
        except Exception:
            raise ClosedLoopContractError("AgentRun event Evidence is not current") from None

    def _supporting_binding(
        self,
        session: Session,
        *,
        evidence_id: str,
        purpose: str,
        scope: Mapping[str, str],
        data_as_of: datetime,
    ) -> dict[str, Any]:
        row = session.get(EvidenceRecordRow, evidence_id)
        blob = session.get(EvidenceBlobRow, row.blob_sha256) if row is not None else None
        if row is None or blob is None:
            raise ClosedLoopContractError("Supporting Evidence is missing")
        _, integrity = self.evidence.inspect_integrity_in_session(evidence_id, session=session)
        if not integrity.valid:
            raise ClosedLoopContractError("Supporting Evidence integrity drifted")
        try:
            payload = json.loads(bytes(blob.content_bytes).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ClosedLoopContractError("Supporting Evidence payload is invalid") from None
        if not isinstance(payload, dict):
            raise ClosedLoopContractError("Supporting Evidence payload is invalid")
        return _validate_supporting_projection(
            row=row,
            blob=blob,
            payload=payload,
            purpose=purpose,
            scope=scope,
            data_as_of=data_as_of,
        )

    def _supporting(
        self,
        session: Session,
        *,
        evidence_id: str,
        purpose: str,
        scope: Mapping[str, str],
        data_as_of: datetime,
        checked_at: datetime,
    ) -> dict[str, Any]:
        self.evidence.require_current_in_session([evidence_id], as_of=checked_at, session=session)
        binding = self._supporting_binding(
            session,
            evidence_id=evidence_id,
            purpose=purpose,
            scope=scope,
            data_as_of=data_as_of,
        )
        if not data_as_of <= checked_at < binding["review_due_at"]:
            raise ClosedLoopContractError("Supporting Evidence temporal binding drifted")
        return binding

    def _recheck_scope(
        self,
        *,
        principal: Principal,
        store_ref: str,
        expected_scope: Mapping[str, str],
    ) -> datetime:
        checked_at = _aware(self.clock(), "trusted clock")
        if self._scope(principal, store_ref, checked_at) != dict(expected_scope):
            raise ClosedLoopContractError("Closed-loop scope authority changed during the operation")
        return checked_at

    def _cross_validate(
        self,
        items: Mapping[str, Mapping[str, Any]],
        *,
        run_ref: str,
        data_as_of: datetime,
        terminal: AgentRuntimeRunEventRow,
        recorder_actor_id: str,
    ) -> None:
        issuer_actor_ids = {item["issuer_actor_id"] for item in items.values()}
        if (
            len({item["row"].id for item in items.values()}) != 3
            or len(issuer_actor_ids) != 3
            or recorder_actor_id in issuer_actor_ids
        ):
            raise ClosedLoopContractError("Closed-loop authorities must be independent")
        experiment = items["experiment"]["claims"]
        cost = items["cost"]["claims"]
        outcome = items["business_outcome"]["claims"]
        try:
            _closed_loop_require_association_only("experiment", experiment)
            _closed_loop_require_association_only("cost", cost)
            _closed_loop_require_association_only("business_outcome", outcome)
        except PermissionError:
            raise ClosedLoopContractError("Independent receipts cannot assert causality") from None
        if (
            {item["data_as_of"] for item in items.values()} != {data_as_of}
            or _stored_utc(terminal.occurred_at, "terminal.occurred_at") > data_as_of
            or experiment["agent_run_ref"] != run_ref
            or cost["agent_run_ref"] != run_ref
            or outcome["agent_run_ref"] != run_ref
            or cost["experiment_ref"] != experiment["experiment_ref"]
            or cost["outcome_ref"] != outcome["outcome_ref"]
        ):
            raise ClosedLoopContractError("AgentRun and authority receipts do not bind")
        for time_field in ("window_end",):
            if _aware(experiment[time_field], time_field) > _aware(
                items["experiment"]["row"].metadata_json["closed_loop_data_as_of"],
                "data_as_of",
            ):
                raise ClosedLoopContractError("Experiment window exceeds data as_of")
        if _aware(cost["period_end"], "period_end") > _aware(
            items["cost"]["row"].metadata_json["closed_loop_data_as_of"],
            "data_as_of",
        ):
            raise ClosedLoopContractError("Cost period exceeds data as_of")
        if _aware(outcome["interval_end"], "interval_end") > _aware(
            items["business_outcome"]["row"].metadata_json["closed_loop_data_as_of"],
            "data_as_of",
        ):
            raise ClosedLoopContractError("Outcome interval exceeds data as_of")
        if (
            outcome["experiment_ref"] != experiment["experiment_ref"]
            or outcome["method"] != experiment["method"]
            or outcome["metric_id"] != experiment["metric_id"]
            or outcome["metric_unit"] != experiment["metric_unit"]
            or outcome["metric_currency"] != experiment["metric_currency"]
            or (
                experiment["metric_unit"] == "minor_currency_units"
                and experiment["metric_currency"] != cost["currency"]
            )
            or outcome["sample_size"] != experiment["sample_size"]
            or not _CURRENCY.fullmatch(cost["currency"])
        ):
            raise ClosedLoopContractError("Independent receipts do not bind")

    def _append_event(
        self,
        session: Session,
        *,
        row: ClosedLoopOutcomeBundleRow,
        event_type: str,
        reason_code: str,
        actor_id: str,
        idempotency_key: str,
        occurred_at: datetime,
        request_sha256: str | None = None,
        request_json: Mapping[str, object] | None = None,
        review: Mapping[str, Any] | None = None,
        replacement_bundle_id: str | None = None,
    ) -> ClosedLoopOutcomeEventRow:
        events = list(
            session.scalars(
                select(ClosedLoopOutcomeEventRow)
                .where(ClosedLoopOutcomeEventRow.bundle_id == row.bundle_id)
                .order_by(ClosedLoopOutcomeEventRow.event_index)
                .with_for_update()
            )
        )
        self._verify_events(session, row, events)
        previous_type = events[-1].event_type if events else None
        if (
            previous_type is None
            and event_type != "bundle_recorded"
            or previous_type is not None
            and event_type not in _TRANSITIONS[previous_type]
        ):
            raise ClosedLoopContractError("Closed-loop event transition is invalid")
        event_index = len(events) + 1
        previous_hash = events[-1].event_sha256 if events else _ZERO_SHA256
        request = dict(
            request_json
            or {
                "bundle_id": row.bundle_id,
                "event_type": event_type,
                "reason_code": reason_code,
                "actor_id": actor_id,
                "review_evidence_ref": None,
                "replacement_bundle_id": None,
                "idempotency_key": idempotency_key,
                "scope": {
                    "tenant_ref": row.tenant_ref,
                    "entity_ref": row.entity_ref,
                    "store_ref": row.store_ref,
                    "scope_grant_authority_sha256": (row.scope_grant_authority_sha256),
                },
            }
        )
        request_hash = request_sha256 or _jsonb_hash(request)
        if request_hash != _jsonb_hash(request):
            raise ClosedLoopContractError("Closed-loop event request hash drifted")
        event_core = {
            "bundle_id": row.bundle_id,
            "event_index": event_index,
            "event_type": event_type,
            "reason_code": reason_code,
            "actor_id": actor_id,
            "request_sha256": request_hash,
            "previous_event_sha256": previous_hash,
            "occurred_at": _iso(occurred_at),
        }
        event_sha = _event_hash(event_core)
        event_id = _stable_id("cloev", event_sha)
        payload = {
            "contract_id": EVENT_CONTRACT_ID,
            **event_core,
            "event_sha256": event_sha,
            "review_evidence_ref": request["review_evidence_ref"],
            "replacement_bundle_id": replacement_bundle_id,
            "payload_status": "hash_and_code_only",
            "candidate_created": False,
            "transition_allowed": False,
            "promotion_allowed": False,
            "external_write_allowed": False,
        }
        content = _canonical_json(payload)
        source_ref = f"closed-loop-evolution://{row.bundle_id}/{event_id}"
        metadata = {
            "contract_id": EVENT_CONTRACT_ID,
            "bundle_id": row.bundle_id,
            "event_id": event_id,
            "event_type": event_type,
            "event_sha256": event_sha,
            "review_evidence_ref": request["review_evidence_ref"],
            "replacement_bundle_id": replacement_bundle_id,
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
            "retention_class": "compliance",
            "legal_hold": False,
        }
        if self.engine.dialect.name == "postgresql":
            evidence_id = _stable_id("evd", hashlib.sha256(content).hexdigest())
            returned_id = self.event_evidence_issuer.issue_event_evidence(
                session=session,
                evidence_id=evidence_id,
                content=content,
                filename=f"{event_id}.json",
                source_ref=source_ref,
                effective_at=occurred_at,
                recorded_at=occurred_at,
                metadata=metadata,
            )
            evidence_row = session.get(EvidenceRecordRow, returned_id)
            if (
                evidence_row is None
                or evidence_row.blob_sha256 != hashlib.sha256(content).hexdigest()
                or evidence_row.source != "governed-closed-loop-evolution"
                or evidence_row.source_ref != source_ref
                or evidence_row.grade != EvidenceGrade.D.value
                or evidence_row.metadata_json != metadata
            ):
                raise ClosedLoopContractError("Closed-loop event issuer receipt drifted")
            event_evidence_id = evidence_row.id
            event_evidence_sha256 = evidence_row.blob_sha256
            event_evidence_source = evidence_row.source
            event_evidence_source_ref = evidence_row.source_ref
            event_evidence_grade = evidence_row.grade
            event_evidence_effective_at = _stored_utc(evidence_row.effective_at, "evidence_effective_at")
            event_evidence_recorded_at = _stored_utc(evidence_row.recorded_at, "evidence_recorded_at")
        else:
            evidence = self.evidence.capture_closed_loop_evolution_event(
                content=content,
                source_ref=source_ref,
                effective_at=_iso(occurred_at),
                recorded_at=_iso(occurred_at),
                metadata=metadata,
                session=session,
            )
            event_evidence_id = evidence.id
            event_evidence_sha256 = evidence.sha256
            event_evidence_source = evidence.source
            event_evidence_source_ref = evidence.source_ref
            event_evidence_grade = evidence.grade.value
            event_evidence_effective_at = _stored_utc(evidence.effective_at, "evidence_effective_at")
            event_evidence_recorded_at = _stored_utc(evidence.recorded_at, "evidence_recorded_at")
        event_row = ClosedLoopOutcomeEventRow(
            event_id=event_id,
            bundle_id=row.bundle_id,
            tenant_ref=row.tenant_ref,
            entity_ref=row.entity_ref,
            store_ref=row.store_ref,
            scope_grant_authority_sha256=row.scope_grant_authority_sha256,
            event_index=event_index,
            event_type=event_type,
            reason_code=reason_code,
            actor_id=actor_id,
            request_json=request,
            idempotency_sha256=_hash_text(idempotency_key),
            request_sha256=request_hash,
            previous_event_sha256=previous_hash,
            event_sha256=event_sha,
            evidence_id=event_evidence_id,
            evidence_sha256=event_evidence_sha256,
            evidence_source=event_evidence_source,
            evidence_source_ref=event_evidence_source_ref,
            evidence_grade=event_evidence_grade,
            evidence_effective_at=event_evidence_effective_at,
            review_evidence_id=(review["row"].id if review is not None else None),
            review_evidence_sha256=(review["row"].blob_sha256 if review is not None else None),
            review_evidence_source=(review["row"].source if review is not None else None),
            review_evidence_source_ref=(review["row"].source_ref if review is not None else None),
            review_evidence_grade=(review["row"].grade if review is not None else None),
            review_evidence_effective_at=(review["effective_at"] if review is not None else None),
            review_attestation_sha256=(
                review["row"].metadata_json.get("closed_loop_attestation_sha256") if review is not None else None
            ),
            replacement_bundle_id=replacement_bundle_id,
            occurred_at=occurred_at,
            recorded_at=event_evidence_recorded_at,
        )
        session.add(event_row)
        session.flush()
        return event_row

    def _verify_events(
        self,
        session: Session,
        row: ClosedLoopOutcomeBundleRow,
        events: Sequence[ClosedLoopOutcomeEventRow],
    ) -> None:
        previous = _ZERO_SHA256
        previous_type: str | None = None
        previous_occurred: datetime | None = None
        previous_recorded: datetime | None = None
        supporting_issuers = set(
            session.scalars(
                select(ClosedLoopOutcomeEvidenceLinkRow.issuer_actor_id).where(
                    ClosedLoopOutcomeEvidenceLinkRow.bundle_id == row.bundle_id
                )
            )
        )
        scope = {
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
        }
        for index, event in enumerate(events, start=1):
            occurred_at = _stored_utc(event.occurred_at, "event.occurred_at")
            recorded_at = _stored_utc(event.recorded_at, "event.recorded_at")
            core = {
                "bundle_id": event.bundle_id,
                "event_index": event.event_index,
                "event_type": event.event_type,
                "reason_code": event.reason_code,
                "actor_id": event.actor_id,
                "request_sha256": event.request_sha256,
                "previous_event_sha256": event.previous_event_sha256,
                "occurred_at": _iso(occurred_at),
            }
            evidence = session.get(EvidenceRecordRow, event.evidence_id)
            blob = session.get(EvidenceBlobRow, evidence.blob_sha256) if evidence is not None else None
            try:
                event_payload = json.loads(bytes(blob.content_bytes).decode("utf-8")) if blob is not None else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                event_payload = None
            request = event.request_json
            idempotency_key = (
                _token(request.get("idempotency_key"), "event idempotency_key") if isinstance(request, dict) else None
            )
            expected_request = {
                "bundle_id": event.bundle_id,
                "event_type": event.event_type,
                "reason_code": event.reason_code,
                "actor_id": event.actor_id,
                "review_evidence_ref": event.review_evidence_id,
                "replacement_bundle_id": event.replacement_bundle_id,
                "idempotency_key": idempotency_key,
                "scope": scope,
            }
            expected_payload = {
                "contract_id": EVENT_CONTRACT_ID,
                **core,
                "event_sha256": event.event_sha256,
                "review_evidence_ref": event.review_evidence_id,
                "replacement_bundle_id": event.replacement_bundle_id,
                "payload_status": "hash_and_code_only",
                "candidate_created": False,
                "transition_allowed": False,
                "promotion_allowed": False,
                "external_write_allowed": False,
            }
            integrity_valid = False
            if evidence is not None:
                _, integrity = self.evidence.inspect_integrity_in_session(evidence.id, session=session)
                integrity_valid = integrity.valid
            if (
                event.bundle_id != row.bundle_id
                or event.tenant_ref != row.tenant_ref
                or event.entity_ref != row.entity_ref
                or event.store_ref != row.store_ref
                or event.scope_grant_authority_sha256 != row.scope_grant_authority_sha256
                or event.event_id != _stable_id("cloev", event.event_sha256)
                or event.event_index != index
                or event.previous_event_sha256 != previous
                or _event_hash(core) != event.event_sha256
                or request != expected_request
                or _jsonb_hash(expected_request) != event.request_sha256
                or event.idempotency_sha256 != _hash_text(idempotency_key)
                or not integrity_valid
                or evidence is None
                or blob is None
                or event_payload != expected_payload
                or bytes(blob.content_bytes) != _canonical_json(expected_payload)
                or evidence.blob_sha256 != event.evidence_sha256
                or evidence.source != "governed-closed-loop-evolution"
                or event.evidence_source != evidence.source
                or evidence.grade != EvidenceGrade.D.value
                or event.evidence_grade != evidence.grade
                or evidence.source_ref != event.evidence_source_ref
                or evidence.source_ref != f"closed-loop-evolution://{event.bundle_id}/{event.event_id}"
                or _stored_utc(evidence.effective_at, "event Evidence effective_at") != occurred_at
                or _stored_utc(evidence.recorded_at, "event Evidence recorded_at") != recorded_at
                or _stored_utc(event.evidence_effective_at, "event evidence_effective_at") != occurred_at
                or occurred_at > recorded_at
                or previous_occurred is not None
                and occurred_at < previous_occurred
                or previous_recorded is not None
                and recorded_at < previous_recorded
                or evidence.metadata_json.get("contract_id") != EVENT_CONTRACT_ID
                or evidence.metadata_json.get("bundle_id") != event.bundle_id
                or evidence.metadata_json.get("event_id") != event.event_id
                or evidence.metadata_json.get("event_type") != event.event_type
                or evidence.metadata_json.get("event_sha256") != event.event_sha256
                or evidence.metadata_json.get("review_evidence_ref") != event.review_evidence_id
                or evidence.metadata_json.get("replacement_bundle_id") != event.replacement_bundle_id
                or evidence.metadata_json.get("tenant_ref") != event.tenant_ref
                or evidence.metadata_json.get("entity_ref") != event.entity_ref
                or evidence.metadata_json.get("store_ref") != event.store_ref
                or evidence.metadata_json.get("scope_grant_authority_sha256") != event.scope_grant_authority_sha256
                or previous_type is None
                and event.event_type != "bundle_recorded"
                or previous_type is not None
                and event.event_type not in _TRANSITIONS[previous_type]
            ):
                raise ClosedLoopContractError("Closed-loop event chain is invalid")
            try:
                self.evidence.require_current_in_session([event.evidence_id], as_of=recorded_at, session=session)
            except Exception:
                raise ClosedLoopContractError("Closed-loop event Evidence is not current") from None
            if event.event_type == "bundle_recorded":
                if (
                    event.actor_id != row.actor_id
                    or event.reason_code != "independent_authorities_verified"
                    or event.idempotency_sha256 != row.idempotency_sha256
                    or request.get("idempotency_key") != row.request_json.get("idempotency_key")
                    or occurred_at != _stored_utc(row.recorded_at, "bundle.recorded_at")
                    or recorded_at != _stored_utc(row.recorded_at, "bundle.recorded_at")
                    or recorded_at != _stored_utc(row.authority_checked_at, "bundle.authority_checked_at")
                    or any(
                        value is not None
                        for value in (
                            event.review_evidence_id,
                            event.review_evidence_sha256,
                            event.review_evidence_source,
                            event.review_evidence_source_ref,
                            event.review_evidence_grade,
                            event.review_evidence_effective_at,
                            event.review_attestation_sha256,
                            event.replacement_bundle_id,
                        )
                    )
                ):
                    raise ClosedLoopContractError("Closed-loop event chain is invalid")
            else:
                if event.review_evidence_id is None:
                    raise ClosedLoopContractError("Closed-loop review Evidence is missing")
                review = self._supporting_binding(
                    session,
                    evidence_id=event.review_evidence_id,
                    purpose="review_event",
                    scope=scope,
                    data_as_of=occurred_at,
                )
                claims = review["claims"]
                if (
                    event.review_evidence_sha256 != review["row"].blob_sha256
                    or event.review_evidence_source != review["row"].source
                    or event.review_evidence_source_ref != review["row"].source_ref
                    or event.review_evidence_grade != review["row"].grade
                    or _stored_utc(
                        event.review_evidence_effective_at,
                        "review_evidence_effective_at",
                    )
                    != review["effective_at"]
                    or event.review_attestation_sha256
                    != review["row"].metadata_json.get("closed_loop_attestation_sha256")
                    or claims
                    != {
                        "bundle_id": event.bundle_id,
                        "event_type": event.event_type,
                        "reason_code": event.reason_code,
                        "replacement_bundle_id": event.replacement_bundle_id,
                        "requested_by_actor_id": event.actor_id,
                    }
                    or review["issuer_actor_id"] == event.actor_id
                    or review["issuer_actor_id"] == row.actor_id
                    or review["issuer_actor_id"] in supporting_issuers
                ):
                    raise ClosedLoopContractError("Closed-loop review authority binding drifted")
                try:
                    self.evidence.require_current_in_session(
                        [event.review_evidence_id],
                        as_of=occurred_at,
                        session=session,
                    )
                except Exception:
                    raise ClosedLoopContractError("Closed-loop review Evidence was not current at the event") from None
            previous = event.event_sha256
            previous_type = event.event_type
            previous_occurred = occurred_at
            previous_recorded = recorded_at

    def _verify_root_binding(
        self,
        *,
        row: ClosedLoopOutcomeBundleRow,
        links: Sequence[ClosedLoopOutcomeEvidenceLinkRow],
        bindings: Mapping[str, Mapping[str, Any]],
    ) -> None:
        if not isinstance(row.request_json, dict) or not isinstance(row.bundle_json, dict):
            raise ClosedLoopContractError("Closed-loop root canonical payload drifted")
        link_by_purpose = {link.purpose: link for link in links}
        if set(link_by_purpose) != set(PURPOSES) or set(bindings) != set(PURPOSES):
            raise ClosedLoopContractError("Closed-loop root canonical payload drifted")
        scope = {
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
        }
        idempotency_key = _token(row.request_json.get("idempotency_key"), "idempotency_key")
        expected_request = {
            "contract_id": CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "registry_sha256": self.registry.content_sha256,
            "scope": scope,
            "actor_id": row.actor_id,
            "data_as_of": _iso(_stored_utc(row.data_as_of, "data_as_of")),
            "agent_run_ref": row.agent_run_ref,
            "experiment_evidence_ref": link_by_purpose["experiment"].evidence_id,
            "cost_evidence_ref": link_by_purpose["cost"].evidence_id,
            "outcome_evidence_ref": link_by_purpose["business_outcome"].evidence_id,
            "idempotency_key": idempotency_key,
        }
        supporting = {
            purpose: {
                "evidence_id": link_by_purpose[purpose].evidence_id,
                "evidence_sha256": link_by_purpose[purpose].evidence_sha256,
                "claims_sha256": link_by_purpose[purpose].claims_sha256,
                "issuer_actor_id": link_by_purpose[purpose].issuer_actor_id,
            }
            for purpose in PURPOSES
        }
        expected_effective_at = max(binding["effective_at"] for binding in bindings.values())
        expected_review_due_at = min(binding["review_due_at"] for binding in bindings.values())
        expected_bundle = {
            **expected_request,
            "agent_run_terminal_event_sha256": row.agent_run_terminal_event_sha256,
            "supporting": supporting,
            "effective_at": _iso(expected_effective_at),
            "review_due_at": _iso(expected_review_due_at),
            "causal_claim_allowed": False,
        }
        experiment = bindings["experiment"]["claims"]
        cost = bindings["cost"]["claims"]
        outcome = bindings["business_outcome"]["claims"]
        if (
            row.request_json != expected_request
            or row.request_sha256 != _jsonb_hash(expected_request)
            or row.idempotency_sha256 != _hash_text(idempotency_key)
            or row.bundle_json != expected_bundle
            or row.bundle_sha256 != _jsonb_hash(expected_bundle)
            or row.bundle_id != _stable_id("clob", row.bundle_sha256)
            or _stored_utc(row.effective_at, "effective_at") != expected_effective_at
            or _stored_utc(row.review_due_at, "review_due_at") != expected_review_due_at
            or _stored_utc(row.recorded_at, "recorded_at")
            != _stored_utc(row.authority_checked_at, "authority_checked_at")
            or row.experiment_ref != experiment["experiment_ref"]
            or row.experiment_method != experiment["method"]
            or row.treatment_ref != experiment["treatment_ref"]
            or row.control_ref != experiment["control_ref"]
            or row.sample_size != experiment["sample_size"]
            or row.minimum_sample_size != experiment["minimum_sample_size"]
            or row.experiment_confidence_level
            != _decimal(
                experiment["confidence_level_decimal"],
                "experiment confidence",
            )
            or row.experiment_independent_review_passed is not experiment["independent_review_passed"]
            or row.metric_id != experiment["metric_id"]
            or row.metric_unit != experiment["metric_unit"]
            or row.metric_currency != experiment["metric_currency"]
            or _stored_utc(row.experiment_window_start, "experiment_window_start")
            != _aware(experiment["window_start"], "window_start")
            or _stored_utc(row.experiment_window_end, "experiment_window_end")
            != _aware(experiment["window_end"], "window_end")
            or row.cost_ref != cost["cost_ref"]
            or row.cost_amount_minor_units != cost["amount_minor_units"]
            or row.cost_currency != cost["currency"]
            or _stored_utc(row.cost_period_start, "cost_period_start") != _aware(cost["period_start"], "period_start")
            or _stored_utc(row.cost_period_end, "cost_period_end") != _aware(cost["period_end"], "period_end")
            or row.cost_allocation_method != cost["allocation_method"]
            or row.outcome_ref != outcome["outcome_ref"]
            or row.outcome_value_decimal != _decimal(outcome["value_decimal"], "outcome value")
            or _stored_utc(row.outcome_interval_start, "outcome_interval_start")
            != _aware(outcome["interval_start"], "interval_start")
            or _stored_utc(row.outcome_interval_end, "outcome_interval_end")
            != _aware(outcome["interval_end"], "interval_end")
            or row.outcome_confidence_level
            != _decimal(
                outcome["confidence_level_decimal"],
                "outcome confidence",
            )
            or row.outcome_independent_review_passed is not outcome["independent_review_passed"]
            or row.causal_claim_allowed is not False
            or outcome["experiment_ref"] != experiment["experiment_ref"]
            or outcome["method"] != experiment["method"]
            or outcome["metric_id"] != experiment["metric_id"]
            or outcome["metric_unit"] != experiment["metric_unit"]
            or outcome["metric_currency"] != experiment["metric_currency"]
            or outcome["sample_size"] != experiment["sample_size"]
            or cost["agent_run_ref"] != row.agent_run_ref
            or experiment["agent_run_ref"] != row.agent_run_ref
            or outcome["agent_run_ref"] != row.agent_run_ref
            or cost["experiment_ref"] != experiment["experiment_ref"]
            or cost["outcome_ref"] != outcome["outcome_ref"]
        ):
            raise ClosedLoopContractError("Closed-loop root canonical payload drifted")

    def _verify_bundle(
        self,
        session: Session,
        row: ClosedLoopOutcomeBundleRow,
        checked_at: datetime,
        transaction_cutoff: datetime | None = None,
        *,
        agent_run_preverified: bool = False,
    ) -> tuple[
        list[ClosedLoopOutcomeEvidenceLinkRow],
        list[ClosedLoopOutcomeEventRow],
        bool,
        bool,
    ]:
        if (
            row.contract_id != CONTRACT_ID
            or row.contract_version != CONTRACT_VERSION
            or row.registry_sha256 != self.registry.content_sha256
        ):
            raise ClosedLoopContractError("Closed-loop bundle contract drifted")
        links = list(
            session.scalars(
                select(ClosedLoopOutcomeEvidenceLinkRow)
                .where(ClosedLoopOutcomeEvidenceLinkRow.bundle_id == row.bundle_id)
                .order_by(ClosedLoopOutcomeEvidenceLinkRow.purpose)
            )
        )
        if (
            len(links) != 3
            or {link.purpose for link in links} != set(PURPOSES)
            or len({link.evidence_id for link in links}) != 3
            or len({link.issuer_actor_id for link in links}) != 3
        ):
            raise ClosedLoopContractError("Closed-loop Evidence conservation failed")
        scope = {
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
        }
        bindings: dict[str, dict[str, Any]] = {}
        for link in links:
            evidence_record, verification = self.evidence.inspect_integrity_in_session(
                link.evidence_id, session=session
            )
            evidence = session.get(EvidenceRecordRow, link.evidence_id)
            binding = self._supporting_binding(
                session,
                evidence_id=link.evidence_id,
                purpose=link.purpose,
                scope=scope,
                data_as_of=_stored_utc(row.data_as_of, "bundle.data_as_of"),
            )
            expected_link_sha256 = _link_hash(
                bundle_id=row.bundle_id,
                purpose=link.purpose,
                evidence_id=link.evidence_id,
                evidence_sha256=link.evidence_sha256,
                claims_sha256=link.claims_sha256,
                issuer_actor_id=link.issuer_actor_id,
                scope=scope,
            )
            if (
                not verification.valid
                or evidence is None
                or link.bundle_id != row.bundle_id
                or link.tenant_ref != row.tenant_ref
                or link.entity_ref != row.entity_ref
                or link.store_ref != row.store_ref
                or link.scope_grant_authority_sha256 != row.scope_grant_authority_sha256
                or evidence.blob_sha256 != link.evidence_sha256
                or evidence.source != link.evidence_source
                or evidence.source_ref != link.evidence_source_ref
                or evidence.grade != link.evidence_grade
                or evidence_record.sha256 != link.evidence_sha256
                or link.evidence_source != CLOSED_LOOP_AUTHORITY_CONTRACTS[link.purpose]["source"]
                or link.evidence_grade != EvidenceGrade.A.value
                or _stored_utc(evidence.effective_at, "evidence.effective_at")
                != _stored_utc(link.evidence_effective_at, "link.effective_at")
                or _stored_utc(evidence.effective_until, "evidence.effective_until")
                != _stored_utc(link.evidence_effective_until, "link.effective_until")
                or _stored_utc(link.evidence_recorded_at, "link.recorded_at") != binding["recorded_at"]
                or _stored_utc(link.evidence_review_due_at, "link.review_due_at") != binding["review_due_at"]
                or link.claims_sha256 != binding["claims_sha256"]
                or link.issuer_actor_id != binding["issuer_actor_id"]
                or link.link_sha256 != expected_link_sha256
                or link.link_id != _stable_id("clol", expected_link_sha256)
            ):
                raise ClosedLoopContractError("Closed-loop supporting Evidence drifted")
            bindings[link.purpose] = binding
        self._verify_root_binding(row=row, links=links, bindings=bindings)
        supporting_current = True
        try:
            self.evidence.require_current_in_session(
                [link.evidence_id for link in links],
                as_of=checked_at,
                session=session,
            )
        except Exception:
            supporting_current = False
        all_events = list(
            session.scalars(
                select(ClosedLoopOutcomeEventRow)
                .where(ClosedLoopOutcomeEventRow.bundle_id == row.bundle_id)
                .order_by(ClosedLoopOutcomeEventRow.event_index)
            )
        )
        if not all_events:
            raise ClosedLoopContractError("Closed-loop event conservation failed")
        cutoff = transaction_cutoff or checked_at
        events = [
            event
            for event in all_events
            if _stored_utc(event.recorded_at, "event.recorded_at") <= cutoff
            and _stored_utc(event.occurred_at, "event.occurred_at") <= cutoff
        ]
        if not events:
            raise ClosedLoopContractError("Closed-loop projection has no event at the transaction cutoff")
        self._verify_events(session, row, events)
        agent_run_current = agent_run_preverified
        if not agent_run_preverified:
            try:
                _, terminal, _ = self._agent_run(
                    session,
                    {
                        "tenant_ref": row.tenant_ref,
                        "entity_ref": row.entity_ref,
                        "store_ref": row.store_ref,
                        "scope_grant_authority_sha256": (row.scope_grant_authority_sha256),
                    },
                    row.agent_run_ref,
                    checked_at,
                    _stored_utc(row.data_as_of, "bundle.data_as_of"),
                )
                agent_run_current = terminal.event_sha256 == row.agent_run_terminal_event_sha256
            except Exception:
                agent_run_current = False
        return links, events, agent_run_current, supporting_current

    def _winner_projection(
        self,
        session: Session,
        row: ClosedLoopOutcomeBundleRow,
        request_sha256: str,
        checked_at: datetime,
    ) -> dict[str, Any]:
        if row.request_sha256 != request_sha256:
            raise ClosedLoopContractError("Closed-loop idempotency payload drifted")
        return self._project(session, row, checked_at, idempotent=True)

    def _project(
        self,
        session: Session,
        row: ClosedLoopOutcomeBundleRow,
        checked_at: datetime,
        *,
        idempotent: bool,
        transaction_cutoff: datetime | None = None,
        agent_run_preverified: bool = False,
    ) -> dict[str, Any]:
        links, events, agent_run_current, supporting_current = self._verify_bundle(
            session,
            row,
            checked_at,
            transaction_cutoff,
            agent_run_preverified=agent_run_preverified,
        )
        latest = events[-1]
        if not agent_run_current:
            status = "invalidated"
            reason = "agent_run_terminal_not_current"
        elif not supporting_current:
            status = "invalidated"
            reason = "supporting_evidence_not_current"
        elif latest.event_type in {"invalidated", "revoked", "superseded"}:
            status = "invalidated"
            reason = latest.event_type
        elif any(checked_at >= _stored_utc(link.evidence_effective_until, "effective_until") for link in links):
            status = "invalidated"
            reason = "supporting_evidence_expired"
        elif checked_at >= min(_stored_utc(link.evidence_review_due_at, "review_due_at") for link in links):
            status = "review_due"
            reason = "review_due"
        elif latest.event_type == "review_requested":
            status = "review_due"
            reason = "review_requested"
        else:
            status = "current"
            reason = (
                "independent_outcome_receipts_current" if row.causal_claim_allowed else "observational_association_only"
            )
        evidence_summary = [
            {
                "purpose": link.purpose,
                "evidence_sha256": link.evidence_sha256,
                "claims_sha256": link.claims_sha256,
            }
            for link in links
        ]
        return {
            "contract_id": CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "registry_sha256": self.registry.content_sha256,
            "bundle_id": row.bundle_id,
            "status": status,
            "reason_code": reason,
            "idempotent": idempotent,
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
            "agent_run_ref": row.agent_run_ref,
            "agent_run_terminal_event_sha256": row.agent_run_terminal_event_sha256,
            "bundle_sha256": row.bundle_sha256,
            "event_chain_sha256": latest.event_sha256,
            "event_count": len(events),
            "latest_event_type": latest.event_type,
            "latest_event_occurred_at": _iso(_stored_utc(latest.occurred_at, "latest event occurred_at")),
            "latest_event_recorded_at": _iso(_stored_utc(latest.recorded_at, "latest event recorded_at")),
            "data_as_of": _iso(_stored_utc(row.data_as_of, "data_as_of")),
            "recorded_at": _iso(_stored_utc(row.recorded_at, "recorded_at")),
            "effective_at": _iso(_stored_utc(row.effective_at, "effective_at")),
            "review_due_at": _iso(_stored_utc(row.review_due_at, "review_due_at")),
            "experiment": {
                "experiment_ref": row.experiment_ref,
                "method": row.experiment_method,
                "metric_id": row.metric_id,
                "metric_unit": row.metric_unit,
                "metric_currency": row.metric_currency,
                "sample_size": row.sample_size,
                "minimum_sample_size": row.minimum_sample_size,
                "confidence_level_decimal": _decimal_text(
                    row.experiment_confidence_level
                ),
                "independent_review_passed": (row.experiment_independent_review_passed),
            },
            "cost": {
                "cost_ref": row.cost_ref,
                "amount_minor_units": row.cost_amount_minor_units,
                "currency": row.cost_currency,
                "allocation_method": row.cost_allocation_method,
            },
            "business_outcome": {
                "outcome_ref": row.outcome_ref,
                "metric_id": row.metric_id,
                "metric_unit": row.metric_unit,
                "metric_currency": row.metric_currency,
                "value_decimal": _decimal_text(row.outcome_value_decimal),
                "confidence_level_decimal": _decimal_text(
                    row.outcome_confidence_level
                ),
                "independent_review_passed": (row.outcome_independent_review_passed),
                "causal_claim_allowed": row.causal_claim_allowed,
            },
            "supporting_evidence": evidence_summary,
            "candidate_created": False,
            "transition_allowed": False,
            "promotion_allowed": False,
            "external_write_allowed": False,
            "writes": {
                "fact": 0,
                "finance_entry": 0,
                "approval": 0,
                "permit": 0,
                "pilot": 0,
                "outbox": 0,
                "external": 0,
            },
        }

    @staticmethod
    def _require_role(principal: Principal, admitted: frozenset[str]) -> None:
        if not principal.roles.intersection(admitted):
            raise PermissionError("Closed-loop role is not admitted")


class Bas177ClosedLoopObservationPort:
    """Read-only BAS-177 seam; it has no candidate or transition operations."""

    def __init__(self, *, workspace: GovernedClosedLoopEvolutionWorkspace) -> None:
        self._workspace = workspace

    def read(self, *, principal: Principal, store_ref: str, bundle_id: str) -> Bas177ClosedLoopObservation:
        return self._workspace.bas177_handoff(
            principal=principal,
            store_ref=store_ref,
            bundle_id=bundle_id,
        )

    def verify(self, observation: Bas177ClosedLoopObservation) -> None:
        self._workspace.verify_bas177_handoff(observation)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"Unsupported canonical value: {type(value).__name__}")


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _agent_run_canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ClosedLoopContractError("AgentRun event payload is not canonical") from None


def _agent_run_event_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_agent_run_canonical(value)).hexdigest()


def _agent_run_event_id(run_id: str, event_sha256: str) -> str:
    digest = _agent_run_event_hash({"run_id": run_id, "event_sha256": event_sha256})
    return f"agev_{digest[:24]}"


def _agent_run_decimal_string(value: object, field: str) -> str:
    parsed = _decimal(value, field)
    if parsed < 0 or -parsed.as_tuple().exponent > 18:
        raise ClosedLoopContractError(f"{field} must be a non-negative decimal")
    rendered = format(parsed, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _agent_run_event_row_payload(row: AgentRuntimeRunEventRow) -> dict[str, object]:
    return {
        "event_index": row.event_index,
        "event_type": row.event_type,
        "reason_code": row.reason_code,
        "adapter_sha256": row.adapter_sha256,
        "provider_sha256": row.provider_sha256,
        "model_sha256": row.model_sha256,
        "adapter_config_sha256": row.adapter_config_sha256,
        "output_sha256": row.output_sha256,
        "eval_sha256": row.eval_sha256,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cost_usd": _agent_run_decimal_string(row.cost_usd, "event.cost_usd"),
        "latency_ms": row.latency_ms,
        "safe_payload": dict(row.safe_payload_json),
        "previous_event_sha256": row.previous_event_sha256,
        "occurred_at": _stored_utc(row.occurred_at, "event.occurred_at").isoformat(),
        "event_sha256": row.event_sha256,
    }


def _validate_agent_run_event_contract(
    event: Mapping[str, object],
    *,
    previous: Mapping[str, object] | None,
    prior_events: Sequence[Mapping[str, object]],
    max_attempts: int,
) -> dict[str, object]:
    contract = _AGENT_RUN_EVENT_CONTRACT
    if set(event) != contract.event_keys:
        raise ClosedLoopContractError("AgentRun event keys drifted")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ClosedLoopContractError("AgentRun max_attempts is invalid")
    if max_attempts < 1 or max_attempts > 8:
        raise ClosedLoopContractError("AgentRun max_attempts is outside the contract")
    payload = dict(event)
    event_index = payload["event_index"]
    event_type = payload["event_type"]
    if (
        isinstance(event_index, bool)
        or not isinstance(event_index, int)
        or event_index != len(prior_events) + 1
        or not isinstance(event_type, str)
        or event_type not in contract.event_types
    ):
        raise ClosedLoopContractError("AgentRun event identity drifted")
    previous_type = None if previous is None else previous.get("event_type")
    if event_type not in contract.next_types(previous_type if isinstance(previous_type, str) else None):
        raise ClosedLoopContractError("AgentRun event transition drifted")
    expected_previous = _ZERO_SHA256 if previous is None else previous.get("event_sha256")
    if payload["previous_event_sha256"] != expected_previous:
        raise ClosedLoopContractError("AgentRun event chain drifted")

    reason_code = payload["reason_code"]
    if reason_code is not None and (
        not isinstance(reason_code, str) or _token(reason_code, "event.reason_code") != reason_code
    ):
        raise ClosedLoopContractError("AgentRun event reason drifted")
    for field in (
        "adapter_sha256",
        "provider_sha256",
        "model_sha256",
        "adapter_config_sha256",
        "output_sha256",
        "eval_sha256",
    ):
        value = payload[field]
        if value is not None:
            _sha(value, f"event.{field}")
    for field in ("input_tokens", "output_tokens", "latency_ms"):
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ClosedLoopContractError(f"AgentRun {field} is invalid")
    if (
        not isinstance(payload["cost_usd"], str)
        or _agent_run_decimal_string(payload["cost_usd"], "event.cost_usd") != payload["cost_usd"]
    ):
        raise ClosedLoopContractError("AgentRun cost_usd is not canonical")
    safe_payload = payload["safe_payload"]
    if not isinstance(safe_payload, dict):
        raise ClosedLoopContractError("AgentRun safe_payload must be an object")
    occurred_at = _aware(payload["occurred_at"], "event.occurred_at")
    if occurred_at.isoformat() != payload["occurred_at"]:
        raise ClosedLoopContractError("AgentRun occurred_at is not canonical UTC")
    if previous is not None and occurred_at < _aware(previous["occurred_at"], "previous.occurred_at"):
        raise ClosedLoopContractError("AgentRun event time moved backwards")
    declared_hash = _sha(payload["event_sha256"], "event.event_sha256")
    hash_input = {key: value for key, value in payload.items() if key != "event_sha256"}
    if _agent_run_event_hash(hash_input) != declared_hash:
        raise ClosedLoopContractError("AgentRun event hash drifted")

    identity_fields = (
        "adapter_sha256",
        "provider_sha256",
        "model_sha256",
        "adapter_config_sha256",
    )
    resource_fields = ("input_tokens", "output_tokens", "latency_ms")

    def require_null(*fields: str) -> None:
        if any(payload[field] is not None for field in fields):
            raise ClosedLoopContractError("AgentRun event null matrix drifted")

    def require_hashes(*fields: str) -> None:
        if any(not isinstance(payload[field], str) for field in fields):
            raise ClosedLoopContractError("AgentRun event hash presence drifted")

    def require_zero_resources() -> None:
        if any(payload[field] != 0 for field in resource_fields) or payload["cost_usd"] != "0":
            raise ClosedLoopContractError("AgentRun event resources drifted")

    attempt_events = [item for item in prior_events if item.get("event_type") == "attempt_started"]
    route = next(
        (item for item in prior_events if item.get("event_type") == "route_selected"),
        None,
    )
    if event_type == "run_started":
        if reason_code is not None or set(safe_payload) != contract.safe_keys(event_type):
            raise ClosedLoopContractError("AgentRun start payload drifted")
        require_null(*identity_fields, "output_sha256", "eval_sha256")
        require_zero_resources()
    elif event_type == "route_selected":
        if reason_code is not None or set(safe_payload) != contract.safe_keys(event_type):
            raise ClosedLoopContractError("AgentRun route payload drifted")
        count = safe_payload.get("adapter_count")
        configs = safe_payload.get("adapter_config_sha256")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
            or count > max_attempts
            or not isinstance(configs, list)
            or len(configs) != count
        ):
            raise ClosedLoopContractError("AgentRun route cardinality drifted")
        for config in configs:
            _sha(config, "route.adapter_config_sha256")
        require_null(*identity_fields, "output_sha256", "eval_sha256")
        require_zero_resources()
    elif event_type == "attempt_started":
        if reason_code is not None or set(safe_payload) != contract.safe_keys(event_type):
            raise ClosedLoopContractError("AgentRun attempt start payload drifted")
        attempt = safe_payload.get("attempt")
        if (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt != len(attempt_events) + 1
            or attempt > max_attempts
            or route is None
        ):
            raise ClosedLoopContractError("AgentRun attempt ordinal drifted")
        configs = route.get("safe_payload")
        if (
            not isinstance(configs, dict)
            or not isinstance(configs.get("adapter_config_sha256"), list)
            or configs["adapter_config_sha256"][attempt - 1] != payload["adapter_config_sha256"]
        ):
            raise ClosedLoopContractError("AgentRun attempt route binding drifted")
        require_hashes(*identity_fields)
        require_null("output_sha256", "eval_sha256")
        require_zero_resources()
    elif event_type in {"attempt_completed", "attempt_denied", "attempt_failed"}:
        if set(safe_payload) != contract.safe_keys(event_type) or previous is None:
            raise ClosedLoopContractError("AgentRun attempt result payload drifted")
        attempt = safe_payload.get("attempt")
        if (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt != previous.get("safe_payload", {}).get("attempt")
        ):
            raise ClosedLoopContractError("AgentRun attempt result ordinal drifted")
        require_hashes(*identity_fields)
        for field in ("adapter_sha256", "provider_sha256", "adapter_config_sha256"):
            if payload[field] != previous.get(field):
                raise ClosedLoopContractError("AgentRun attempt identity drifted")
        if event_type == "attempt_completed":
            if reason_code is not None:
                raise ClosedLoopContractError("AgentRun completion reason drifted")
            require_hashes("output_sha256")
        else:
            if reason_code is None:
                raise ClosedLoopContractError("AgentRun attempt reason is missing")
            require_null("output_sha256")
        require_null("eval_sha256")
    elif event_type == "eval_completed":
        if (
            reason_code is not None
            or set(safe_payload) != contract.safe_keys(event_type)
            or not isinstance(safe_payload.get("passed"), bool)
            or isinstance(safe_payload.get("assertion_count"), bool)
            or not isinstance(safe_payload.get("assertion_count"), int)
            or safe_payload["assertion_count"] < 0
            or previous is None
        ):
            raise ClosedLoopContractError("AgentRun evaluation payload drifted")
        require_hashes(*identity_fields, "output_sha256", "eval_sha256")
        for field in (*identity_fields, "output_sha256"):
            if payload[field] != previous.get(field):
                raise ClosedLoopContractError("AgentRun evaluation binding drifted")
        require_zero_resources()
    elif event_type == "run_succeeded":
        if (
            reason_code is not None
            or set(safe_payload) != contract.safe_keys(event_type)
            or previous is None
        ):
            raise ClosedLoopContractError("AgentRun success payload drifted")
        require_null(*identity_fields)
        require_hashes("output_sha256", "eval_sha256")
        attempt_count = safe_payload.get("attempt_count")
        if (
            isinstance(attempt_count, bool)
            or not isinstance(attempt_count, int)
            or attempt_count != len(attempt_events)
            or not attempt_events
            or payload["output_sha256"] != previous.get("output_sha256")
            or payload["eval_sha256"] != previous.get("eval_sha256")
        ):
            raise ClosedLoopContractError("AgentRun success binding drifted")
        terminal_attempts = [
            item
            for item in prior_events
            if item.get("event_type") in {"attempt_completed", "attempt_denied", "attempt_failed"}
        ]
        if len(terminal_attempts) != len(attempt_events):
            raise ClosedLoopContractError("AgentRun attempt conservation drifted")
        for field in ("input_tokens", "output_tokens", "latency_ms"):
            if payload[field] != sum(int(item[field]) for item in terminal_attempts):
                raise ClosedLoopContractError("AgentRun success resources drifted")
        if _decimal(payload["cost_usd"], "run.cost_usd") != sum(
            (_decimal(item["cost_usd"], "attempt.cost_usd") for item in terminal_attempts),
            Decimal("0"),
        ):
            raise ClosedLoopContractError("AgentRun success cost drifted")
    elif event_type == "run_failed":
        if reason_code != "all_adapters_failed" or set(safe_payload) != contract.safe_keys(event_type):
            raise ClosedLoopContractError("AgentRun failure payload drifted")
        require_null(*identity_fields, "output_sha256", "eval_sha256")
        if any(payload[field] != 0 for field in resource_fields):
            raise ClosedLoopContractError("AgentRun failure resources drifted")
        terminal_attempts = [
            item
            for item in prior_events
            if item.get("event_type") in {"attempt_completed", "attempt_denied", "attempt_failed"}
        ]
        if _decimal(payload["cost_usd"], "run.cost_usd") != sum(
            (_decimal(item["cost_usd"], "attempt.cost_usd") for item in terminal_attempts),
            Decimal("0"),
        ):
            raise ClosedLoopContractError("AgentRun failure cost drifted")
    elif event_type == "run_denied":
        if reason_code is None or set(safe_payload) != contract.safe_keys(event_type):
            raise ClosedLoopContractError("AgentRun denial payload drifted")
        require_null(*identity_fields, "output_sha256", "eval_sha256")
        require_zero_resources()
        if (
            previous is not None
            and previous.get("event_type") == "attempt_denied"
            and reason_code != previous.get("reason_code")
        ):
            raise ClosedLoopContractError("AgentRun denial reason drifted")
    else:
        if (
            reason_code not in contract.unknown_reason_codes
            or set(safe_payload) != contract.safe_keys(event_type)
        ):
            raise ClosedLoopContractError("AgentRun unknown outcome payload drifted")
        require_null(*identity_fields, "output_sha256", "eval_sha256")
        require_zero_resources()
    return payload


def _validate_supporting_projection(
    *,
    row: EvidenceRecordRow,
    blob: EvidenceBlobRow,
    payload: Mapping[str, object],
    purpose: str,
    scope: Mapping[str, str],
    data_as_of: datetime,
) -> dict[str, Any]:
    contract = CLOSED_LOOP_AUTHORITY_CONTRACTS[purpose]
    metadata = row.metadata_json
    exact_scope = payload.get("exact_scope")
    claims = payload.get("claims")
    if (
        set(payload) != _SUPPORTING_PAYLOAD_KEYS
        or not isinstance(metadata, dict)
        or set(metadata) != _SUPPORTING_METADATA_KEYS
        or not isinstance(exact_scope, dict)
        or set(exact_scope) != _SUPPORTING_SCOPE_KEYS
        or set(scope) != _SUPPORTING_SCOPE_KEYS
        or exact_scope != dict(scope)
        or not isinstance(claims, dict)
        or set(claims) != contract["fields"]
    ):
        raise ClosedLoopContractError("Supporting Evidence schema drifted")
    try:
        _closed_loop_require_association_only(purpose, claims)
    except PermissionError:
        raise ClosedLoopContractError(
            "Supporting Evidence causal claim is not admitted"
        ) from None
    try:
        normalized_claims = _closed_loop_claims(purpose, dict(claims))
    except (KeyError, PermissionError, TypeError, ValueError):
        raise ClosedLoopContractError("Supporting Evidence claims are invalid") from None
    if normalized_claims != claims:
        raise ClosedLoopContractError("Supporting Evidence claims are not canonical")

    content = bytes(blob.content_bytes)
    content_sha256 = hashlib.sha256(content).hexdigest()
    claims_sha256 = _claims_hash(claims)
    scope_binding_sha256 = _hash_json(scope)
    issuer_actor_id = _token(payload.get("issuer_actor_id"), "issuer_actor_id")
    authority_receipt_id = _token(
        payload.get("authority_receipt_id"), "authority_receipt_id"
    )
    attestation_ref = _token(payload.get("attestation_ref"), "attestation_ref")
    attestation_signature_sha256 = _sha(
        payload.get("attestation_signature_sha256"),
        "attestation_signature_sha256",
    )
    attestation_envelope = {
        key: payload[key] for key in _SUPPORTING_ATTESTATION_KEYS
    }
    attestation_sha256 = _hash_json(attestation_envelope)

    def canonical_time(field: str) -> datetime:
        value = payload.get(field)
        parsed = _aware(value, field)
        if not isinstance(value, str) or parsed.isoformat() != value:
            raise ClosedLoopContractError(
                f"Supporting Evidence {field} is not canonical UTC"
            )
        return parsed

    receipt_data_as_of = canonical_time("data_as_of")
    effective_at = canonical_time("effective_at")
    effective_until = canonical_time("effective_until")
    recorded_at = canonical_time("recorded_at")
    review_due_at = canonical_time("review_due_at")
    expected_source_ref = (
        f"{contract['source']}://{scope_binding_sha256}/"
        f"{claims_sha256}/{content_sha256}"
    )
    expected_metadata = {
        "contract_id": contract["contract_id"],
        "closed_loop_purpose": purpose,
        "closed_loop_claims_sha256": claims_sha256,
        "closed_loop_attestation_sha256": attestation_sha256,
        "closed_loop_attestation_signature_sha256": attestation_signature_sha256,
        "closed_loop_attestation_ref": attestation_ref,
        "closed_loop_authority_receipt_id": authority_receipt_id,
        "closed_loop_issuer_id": contract["issuer_id"],
        "closed_loop_issuer_contract_id": contract["issuer_contract_id"],
        "closed_loop_issuer_contract_version": contract["issuer_contract_version"],
        "closed_loop_issuer_contract_sha256": contract["issuer_contract_sha256"],
        "closed_loop_schema_sha256": contract["schema_sha256"],
        "closed_loop_issuer_actor_id": issuer_actor_id,
        "closed_loop_data_as_of": payload["data_as_of"],
        "closed_loop_recorded_at": payload["recorded_at"],
        "closed_loop_review_due_at": payload["review_due_at"],
        "closed_loop_claims": claims,
        "closed_loop_scope_binding_sha256": scope_binding_sha256,
        **dict(scope),
        "retention_class": "compliance",
        "legal_hold": False,
    }
    if (
        _canonical_json(payload) != content
        or blob.sha256 != content_sha256
        or blob.byte_size != len(content)
        or row.blob_sha256 != content_sha256
        or row.filename != f"{purpose}-{content_sha256}.json"
        or row.content_type != "application/json"
        or row.source != contract["source"]
        or row.source_ref != expected_source_ref
        or row.grade != EvidenceGrade.A.value
        or row.created_by != issuer_actor_id
        or metadata != expected_metadata
        or payload.get("contract_id") != contract["contract_id"]
        or payload.get("purpose") != purpose
        or payload.get("issuer_id") != contract["issuer_id"]
        or payload.get("issuer_contract_id") != contract["issuer_contract_id"]
        or payload.get("issuer_contract_version")
        != contract["issuer_contract_version"]
        or payload.get("issuer_contract_sha256")
        != contract["issuer_contract_sha256"]
        or payload.get("schema_sha256") != contract["schema_sha256"]
        or payload.get("claims_sha256") != claims_sha256
        or payload.get("attestation_sha256") != attestation_sha256
        or payload.get("payload_status") != "authority_projection_only"
        or payload.get("contains_customer_data") is not False
        or payload.get("external_write_allowed") is not False
        or _stored_utc(row.effective_at, "row.effective_at") != effective_at
        or _stored_utc(row.effective_until, "row.effective_until")
        != effective_until
        or _stored_utc(row.recorded_at, "row.recorded_at") != recorded_at
        or not (
            receipt_data_as_of == data_as_of
            and effective_at <= recorded_at <= data_as_of < review_due_at
            and review_due_at <= effective_until
        )
    ):
        raise ClosedLoopContractError("Supporting Evidence projection drifted")
    return {
        "row": row,
        "claims": claims,
        "claims_sha256": claims_sha256,
        "issuer_actor_id": issuer_actor_id,
        "effective_at": effective_at,
        "effective_until": effective_until,
        "recorded_at": recorded_at,
        "review_due_at": review_due_at,
        "data_as_of": receipt_data_as_of,
    }


def _jsonb_hash(value: object) -> str:
    return _closed_loop_postgres_jsonb_sha256(value)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _handoff_seal(key: bytes, payload: Mapping[str, object]) -> str:
    return hmac.new(
        key,
        b"bas177-closed-loop-full-payload-v1\x1f" + _canonical_json(payload),
        hashlib.sha256,
    ).hexdigest()


def _opaque_token(key: bytes, *, domain: bytes, payload: Mapping[str, object], prefix: str) -> str:
    encoded = _canonical_json(payload)
    digest = (
        urlsafe_b64encode(hmac.new(key, domain + b"\x1f" + encoded, hashlib.sha256).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    token = f"{prefix}_{digest}"
    if _OPAQUE_TOKEN.fullmatch(token) is None:
        raise ClosedLoopContractError("Closed-loop opaque token is invalid")
    return token


def _claims_hash(value: Mapping[str, object]) -> str:
    return _closed_loop_claims_sha256(value)


def _link_hash(
    *,
    bundle_id: str,
    purpose: str,
    evidence_id: str,
    evidence_sha256: str,
    claims_sha256: str,
    issuer_actor_id: str,
    scope: Mapping[str, str],
) -> str:
    return _hash_text(
        "\x1f".join(
            (
                bundle_id,
                purpose,
                evidence_id,
                evidence_sha256,
                claims_sha256,
                issuer_actor_id,
                scope["tenant_ref"],
                scope["entity_ref"],
                scope["store_ref"],
                scope["scope_grant_authority_sha256"],
            )
        )
    )


def _event_hash(core: Mapping[str, object]) -> str:
    return _hash_text(
        "\x1f".join(
            str(core[field])
            for field in (
                "bundle_id",
                "event_index",
                "event_type",
                "reason_code",
                "actor_id",
                "request_sha256",
                "previous_event_sha256",
                "occurred_at",
            )
        )
    )


def _stable_id(prefix: str, digest: str) -> str:
    return f"{prefix}_{digest[:40]}"


def _aware(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ClosedLoopContractError(f"{field} must be ISO-8601") from None
    else:
        raise ClosedLoopContractError(f"{field} must be a timestamp")
    if parsed.tzinfo is None:
        raise ClosedLoopContractError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat()


def _stored_utc(value: object, field: str) -> datetime:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return _aware(value, field)


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value.strip()):
        raise ClosedLoopContractError(f"{field} is invalid")
    return value.strip()


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ClosedLoopContractError(f"{field} must be lowercase SHA-256")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ClosedLoopContractError(f"{field} must be finite")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ClosedLoopContractError(f"{field} must be finite") from None
    if not parsed.is_finite():
        raise ClosedLoopContractError(f"{field} must be finite")
    return parsed


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ClosedLoopContractError("Stored decimal must be finite")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", ""} else rendered


__all__ = [
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "EVENT_CONTRACT_ID",
    "ClosedLoopContractError",
    "ClosedLoopEvidenceIssuerPort",
    "ClosedLoopEventEvidenceIssuerPort",
    "ClosedLoopAuthorityReceiptRegistrarPort",
    "ClosedLoopAuthorityReceiptRow",
    "ClosedLoopEvidenceIssuanceRow",
    "ClosedLoopEvolutionRegistry",
    "ClosedLoopOutcomeBundleRow",
    "ClosedLoopOutcomeEvidenceLinkRow",
    "ClosedLoopOutcomeEventRow",
    "Bas177ClosedLoopObservation",
    "Bas177ClosedLoopObservationPort",
    "GovernedClosedLoopEvolutionWorkspace",
]
