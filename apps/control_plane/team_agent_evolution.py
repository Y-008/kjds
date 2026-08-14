from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecord,
    EvidenceRecordRow,
    EvidenceService,
)
from .loop_engineering import FrozenEvalSet, LoopEngineeringService
from .security import Principal
from .sql_repository import Base

CONTRACT_ID = "kjds-governed-team-agent-evolution-v1"
EVIDENCE_SOURCE = "governed-team-agent-evolution"
EVIDENCE_CONTRACT_ID = "kjds-governed-team-agent-evolution-evidence-v1"
ZERO_SHA256 = "0" * 64
STATES = (
    "observation",
    "skill_candidate",
    "evaluation",
    "shadow",
    "independent_review",
    "promoted",
    "active",
    "rolled_back",
    "retired",
)
LEARNING_INPUT_TYPES = frozenset(
    {
        "human_correction",
        "verified_failure",
        "evidence_backed_outcome",
        "policy_violation",
        "cost_or_latency_regression",
        "official_source_change",
    }
)
CROSS_TENANT_MODES = frozenset(
    {"same_tenant", "licensed_deidentified_nonreversible"}
)
INDEPENDENT_ROLES = frozenset({"reviewer", "risk", "compliance", "admin"})
PROMOTION_ROLES = frozenset({"risk", "approver", "admin"})
EVIDENCE_PURPOSES = frozenset(
    {
        "agent_run",
        "eval_set",
        "baseline",
        "shadow",
        "review",
        "risk_authority",
        "rollback",
        "license",
        "deidentification",
        "revocation",
        "retirement",
        "graph_observation",
        "event_audit",
    }
)


@dataclass(frozen=True, slots=True)
class SupportEvidenceContract:
    source: str
    contract_id: str
    grade: str


SUPPORT_EVIDENCE_CONTRACTS = {
    "agent_run": SupportEvidenceContract(
        "governed-agent-run-evidence",
        "kjds-governed-agent-run-evidence-v1",
        EvidenceGrade.B.value,
    ),
    "eval_set": SupportEvidenceContract(
        "team-agent-eval-set-authority",
        "kjds-team-agent-eval-set-authority-v1",
        EvidenceGrade.A.value,
    ),
    "baseline": SupportEvidenceContract(
        "team-agent-baseline-authority",
        "kjds-team-agent-baseline-authority-v1",
        EvidenceGrade.B.value,
    ),
    "shadow": SupportEvidenceContract(
        "team-agent-shadow-authority",
        "kjds-team-agent-shadow-authority-v1",
        EvidenceGrade.B.value,
    ),
    "review": SupportEvidenceContract(
        "team-agent-review-authority",
        "kjds-team-agent-review-authority-v1",
        EvidenceGrade.A.value,
    ),
    "risk_authority": SupportEvidenceContract(
        "team-agent-risk-authority",
        "kjds-team-agent-risk-authority-v1",
        EvidenceGrade.A.value,
    ),
    "rollback": SupportEvidenceContract(
        "team-agent-rollback-authority",
        "kjds-team-agent-rollback-authority-v1",
        EvidenceGrade.A.value,
    ),
    "license": SupportEvidenceContract(
        "team-agent-license-authority",
        "kjds-team-agent-license-authority-v1",
        EvidenceGrade.A.value,
    ),
    "deidentification": SupportEvidenceContract(
        "team-agent-deidentification-authority",
        "kjds-team-agent-deidentification-authority-v1",
        EvidenceGrade.A.value,
    ),
    "revocation": SupportEvidenceContract(
        "team-agent-revocation-authority",
        "kjds-team-agent-revocation-authority-v1",
        EvidenceGrade.A.value,
    ),
    "retirement": SupportEvidenceContract(
        "team-agent-retirement-authority",
        "kjds-team-agent-retirement-authority-v1",
        EvidenceGrade.A.value,
    ),
    "graph_observation": SupportEvidenceContract(
        "strategic-benchmark-observation",
        "kjds-team-agent-graph-observation-v1",
        EvidenceGrade.B.value,
    ),
}
REQUIRED_PURPOSES_BY_STATE = {
    "skill_candidate": frozenset({"agent_run", "eval_set", "rollback"}),
    "evaluation": frozenset({"agent_run", "eval_set", "baseline"}),
    "shadow": frozenset({"agent_run", "baseline", "shadow"}),
    "independent_review": frozenset({"review", "shadow"}),
    "promoted": frozenset({"baseline", "shadow", "review", "risk_authority"}),
    "active": frozenset({"baseline", "shadow", "review", "risk_authority"}),
    "rolled_back": frozenset({"rollback"}),
    "retired": frozenset({"retirement"}),
}
_HEX64 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}")
_SKILL_VERSION = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
)


class TeamAgentEvolutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TeamAgentEvolutionConflictError(RuntimeError):
    pass


class TeamAgentEvolutionIntegrityError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(payload).hexdigest()


_EVENT_HASH_FIELDS = (
    "candidate_ref",
    "tenant_ref",
    "entity_ref",
    "store_ref",
    "scope_authority_sha256",
    "ordinal",
    "from_state",
    "to_state",
    "actor_id",
    "actor_role",
    "risk_actor_id",
    "reason_code",
    "eval_baseline_passed",
    "negative_tests_passed",
    "scope_tests_passed",
    "shadow_passed",
    "external_write_observed",
    "zero_external_writes",
    "cost_usd",
    "latency_ms",
    "token_count",
    "risk_authority_sha256",
    "eval_set_id",
    "eval_set_version",
    "eval_set_sha256",
    "baseline_runtime_ref",
    "baseline_runtime_sha256",
    "candidate_runtime_ref",
    "candidate_runtime_sha256",
    "agent_run_ref",
    "agent_run_sha256",
    "eval_snapshot_sha256",
    "result_snapshot_sha256",
    "review_verdict",
    "rollback_target_candidate_ref",
    "rollback_target_skill_version",
    "rollback_target_content_sha256",
    "rollback_target_runtime_sha256",
    "rollback_target_sha256",
    "graph_snapshot_sha256",
    "graph_observation_type",
    "graph_observation_version",
    "graph_effective_from",
    "graph_effective_until",
    "graph_observation_only",
    "graph_gate_eligible",
    "prev_event_sha256",
    "request_sha256",
    "idempotency_sha256",
    "data_as_of",
    "occurred_at",
)
_EVENT_TIME_FIELDS = frozenset(
    {"graph_effective_from", "graph_effective_until", "data_as_of", "occurred_at"}
)
_EVENT_DECIMAL_FIELDS = frozenset({"cost_usd", "latency_ms"})


def _event_digest(payload: dict[str, Any]) -> str:
    values: list[str] = []
    for field in _EVENT_HASH_FIELDS:
        value = payload[field]
        if value is None:
            normalized = ""
        elif field in _EVENT_TIME_FIELDS:
            normalized = _utc(value).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
        elif field in _EVENT_DECIMAL_FIELDS:
            normalized = _decimal_text(value)
        elif isinstance(value, bool):
            normalized = "true" if value else "false"
        else:
            normalized = str(value)
        values.append(normalized)
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()


def _stable_ref(prefix: str, value: Any) -> str:
    return f"{prefix}_{_digest(value)[:32]}"


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise TeamAgentEvolutionError(
                "timestamp_invalid", "timestamp must be ISO-8601"
            ) from exc
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _identifier(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise TeamAgentEvolutionError("identifier_invalid", f"{field} is invalid")
    return normalized


def _sha(value: Any, field: str, *, allow_zero: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not _HEX64.fullmatch(normalized):
        raise TeamAgentEvolutionError(
            "sha256_invalid", f"{field} must be a lowercase SHA-256"
        )
    if normalized == ZERO_SHA256 and not allow_zero:
        raise TeamAgentEvolutionError("sha256_zero", f"{field} cannot be zero")
    return normalized


def _skill_version(value: Any) -> str:
    normalized = str(value or "").strip()
    if not _SKILL_VERSION.fullmatch(normalized):
        raise TeamAgentEvolutionError(
            "skill_version_invalid",
            "skill_version must be canonical major.minor.patch",
        )
    return normalized


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
        raise TeamAgentEvolutionError("metric_invalid", f"{field} must be finite")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TeamAgentEvolutionError("metric_invalid", f"{field} is invalid") from exc
    if not result.is_finite() or result < 0:
        raise TeamAgentEvolutionError(
            "metric_invalid", f"{field} must be finite and nonnegative"
        )
    return result


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TeamAgentEvolutionError(
            "metric_invalid", f"{field} must be a nonnegative integer"
        )
    return value


def _decimal_text(value: Any) -> str:
    return format(Decimal(str(value)).normalize(), "f")


@dataclass(frozen=True, slots=True)
class _Scope:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    authority_sha256: str
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class _Attestation:
    row: EvidenceRecordRow
    purpose: str
    claims: dict[str, Any]


class TeamAgentEvolutionCandidateRow(Base):
    __tablename__ = "team_agent_evolution_candidates"
    __table_args__ = (
        UniqueConstraint(
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_gta_candidate_exact_scope",
        ),
        UniqueConstraint(
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "skill_version",
            name="uq_gta_candidate_exact_version",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "skill_id",
            "skill_version",
            name="uq_gta_candidate_skill_version_scope",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "idempotency_sha256",
            name="uq_gta_candidate_scope_idempotency",
        ),
        CheckConstraint(
            "candidate_author_actor_id <> human_owner_actor_id",
            name="ck_gta_candidate_owner_sod",
        ),
        CheckConstraint(
            "cross_tenant_mode IN "
            "('same_tenant','licensed_deidentified_nonreversible')",
            name="ck_gta_candidate_cross_tenant_mode",
        ),
        ForeignKeyConstraint(
            [
                "predecessor_candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "predecessor_skill_version",
            ],
            [
                "team_agent_evolution_candidates.candidate_ref",
                "team_agent_evolution_candidates.tenant_ref",
                "team_agent_evolution_candidates.entity_ref",
                "team_agent_evolution_candidates.store_ref",
                "team_agent_evolution_candidates.scope_authority_sha256",
                "team_agent_evolution_candidates.skill_version",
            ],
            name="fk_gta_candidate_predecessor_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "supersedes_candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
            ],
            [
                "team_agent_evolution_candidates.candidate_ref",
                "team_agent_evolution_candidates.tenant_ref",
                "team_agent_evolution_candidates.entity_ref",
                "team_agent_evolution_candidates.store_ref",
                "team_agent_evolution_candidates.scope_authority_sha256",
            ],
            name="fk_gta_candidate_supersedes_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(predecessor_candidate_ref IS NULL "
            "AND predecessor_skill_version IS NULL "
            "AND supersedes_candidate_ref IS NULL "
            f"AND supersedes_sha256 = '{ZERO_SHA256}') OR "
            "(predecessor_candidate_ref IS NOT NULL "
            "AND predecessor_skill_version IS NOT NULL "
            "AND supersedes_candidate_ref = predecessor_candidate_ref "
            f"AND supersedes_sha256 <> '{ZERO_SHA256}' "
            "AND predecessor_candidate_ref <> candidate_ref "
            "AND predecessor_skill_version <> skill_version)",
            name="ck_gta_candidate_version_chain",
        ),
        Index(
            "uq_gta_candidate_single_successor",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "supersedes_candidate_ref",
            unique=True,
            sqlite_where=text("supersedes_candidate_ref IS NOT NULL"),
            postgresql_where=text("supersedes_candidate_ref IS NOT NULL"),
        ),
        Index(
            "ix_gta_candidate_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "created_at",
            "candidate_ref",
        ),
    )

    candidate_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_author_actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    human_owner_actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(160), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(100), nullable=False)
    predecessor_candidate_ref: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    predecessor_skill_version: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    supersedes_candidate_ref: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    supersedes_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    learning_input_type: Mapped[str] = mapped_column(String(40), nullable=False)
    agent_role_version_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    eval_set_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rollback_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cross_tenant_mode: Mapped[str] = mapped_column(String(48), nullable=False)
    license_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    deidentification_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    revocation_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TeamAgentEvolutionEventRow(Base):
    __tablename__ = "team_agent_evolution_events"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
            ],
            [
                "team_agent_evolution_candidates.candidate_ref",
                "team_agent_evolution_candidates.tenant_ref",
                "team_agent_evolution_candidates.entity_ref",
                "team_agent_evolution_candidates.store_ref",
                "team_agent_evolution_candidates.scope_authority_sha256",
            ],
            name="fk_gta_event_candidate_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "rollback_target_candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "rollback_target_skill_version",
            ],
            [
                "team_agent_evolution_candidates.candidate_ref",
                "team_agent_evolution_candidates.tenant_ref",
                "team_agent_evolution_candidates.entity_ref",
                "team_agent_evolution_candidates.store_ref",
                "team_agent_evolution_candidates.scope_authority_sha256",
                "team_agent_evolution_candidates.skill_version",
            ],
            name="fk_gta_event_rollback_target",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "event_ref",
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_gta_event_exact_scope",
        ),
        UniqueConstraint(
            "event_ref",
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "insert_xid",
            name="uq_gta_event_exact_insert",
        ),
        UniqueConstraint(
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "ordinal",
            name="uq_gta_event_candidate_ordinal",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "candidate_ref",
            "idempotency_sha256",
            name="uq_gta_event_scope_idempotency",
        ),
        UniqueConstraint(
            "candidate_ref",
            "event_sha256",
            name="uq_gta_event_hash_per_candidate",
        ),
        CheckConstraint("ordinal > 0", name="ck_gta_event_ordinal"),
        CheckConstraint("cost_usd >= 0", name="ck_gta_event_cost"),
        CheckConstraint("latency_ms >= 0", name="ck_gta_event_latency"),
        CheckConstraint("token_count >= 0", name="ck_gta_event_tokens"),
        CheckConstraint(
            "data_as_of <= occurred_at", name="ck_gta_event_data_as_of"
        ),
        CheckConstraint(
            "NOT external_write_observed", name="ck_gta_event_no_external_write"
        ),
        Index("ix_gta_event_candidate_ordinal", "candidate_ref", "ordinal"),
    )

    event_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    from_state: Mapped[str] = mapped_column(String(40), nullable=False)
    to_state: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_actor_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    eval_baseline_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    negative_tests_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scope_tests_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    shadow_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    external_write_observed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    zero_external_writes: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    latency_ms: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    token_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    risk_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    eval_set_id: Mapped[str] = mapped_column(String(160), nullable=False)
    eval_set_version: Mapped[str] = mapped_column(String(100), nullable=False)
    eval_set_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_runtime_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    baseline_runtime_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_runtime_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    candidate_runtime_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_run_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    agent_run_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    eval_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    rollback_target_candidate_ref: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    rollback_target_skill_version: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    rollback_target_content_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    rollback_target_runtime_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    rollback_target_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_observation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    graph_observation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    graph_effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    graph_effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    graph_observation_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    graph_gate_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    prev_event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data_as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    insert_xid: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=FetchedValue()
    )


class TeamAgentEvolutionEvidenceLinkRow(Base):
    __tablename__ = "team_agent_evolution_evidence_links"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "event_ref",
                "candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "event_insert_xid",
            ],
            [
                "team_agent_evolution_events.event_ref",
                "team_agent_evolution_events.candidate_ref",
                "team_agent_evolution_events.tenant_ref",
                "team_agent_evolution_events.entity_ref",
                "team_agent_evolution_events.store_ref",
                "team_agent_evolution_events.scope_authority_sha256",
                "team_agent_evolution_events.insert_xid",
            ],
            name="fk_gta_link_event_exact_insert",
            ondelete="RESTRICT",
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
            name="fk_gta_link_exact_evidence",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "event_ref", "ordinal", name="uq_gta_link_event_ordinal"
        ),
        UniqueConstraint(
            "event_ref", "evidence_id", name="uq_gta_link_event_evidence"
        ),
        CheckConstraint("ordinal > 0", name="ck_gta_link_ordinal"),
        Index("ix_gta_link_evidence_id", "evidence_id"),
    )

    link_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_insert_xid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_source_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(8), nullable=False)
    evidence_effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GovernedTeamAgentEvolutionWorkspace:
    """Append-only exact-scope TeamAgent candidate governance.

    `promoted` and `active` are governance states only.  This module has no
    runtime installer, canonical Graph writer, business Fact promoter, Permit,
    Outbox, or external connector.
    """

    def __init__(
        self,
        *,
        engine,
        evidence: EvidenceService,
        scope_grants,
        clock: Callable[[], datetime] | None = None,
        loop_engineering: LoopEngineeringService | None = None,
        agent_run_ledger: Any | None = None,
        eval_set_path: str | Path | None = None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scope_grants = scope_grants
        self.clock = clock or (lambda: datetime.now(UTC))
        self.loop = loop_engineering or LoopEngineeringService()
        if agent_run_ledger is None:
            from .agent_runtime_evidence import SqlAgentRuntimeEvidenceLedger

            agent_run_ledger = SqlAgentRuntimeEvidenceLedger(
                engine=engine,
                evidence=evidence,
            )
        self.agent_runs = agent_run_ledger
        self.evolution = self.loop.evolution_snapshot()
        default_eval = (
            Path(__file__).resolve().parents[2]
            / "tests"
            / "fixtures"
            / "team_agent_evolution"
            / "bas177_eval_set_v1.json"
        )
        self.eval_set: FrozenEvalSet = self.loop.load_frozen_eval_set(
            eval_set_path or default_eval
        )

    def create_candidate(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        human_owner_actor_id: str,
        skill_id: str,
        skill_version: str,
        learning_input_type: str,
        agent_role_version_sha256: str,
        skill_contract_sha256: str,
        eval_set_sha256: str,
        model_profile_sha256: str,
        tool_contract_sha256: str,
        policy_version_sha256: str,
        rollback_artifact_sha256: str,
        evidence_ids: Sequence[str],
        idempotency_key: str,
        cross_tenant_mode: str = "same_tenant",
        license_sha256: str = ZERO_SHA256,
        deidentification_sha256: str = ZERO_SHA256,
        revocation_contract_sha256: str = ZERO_SHA256,
        predecessor_candidate_ref: str | None = None,
        supersedes_sha256: str = ZERO_SHA256,
    ) -> dict[str, Any]:
        if not principal.has_any_role("operator", "monitor", "admin"):
            raise PermissionError("operator, monitor, or admin role required")
        scope = self._current_scope(principal=principal, store_ref=store_ref)
        cutoff = self._data_as_of(as_of, scope.checked_at)
        values = self._candidate_values(
            principal=principal,
            scope=scope,
            human_owner_actor_id=human_owner_actor_id,
            skill_id=skill_id,
            skill_version=skill_version,
            learning_input_type=learning_input_type,
            agent_role_version_sha256=agent_role_version_sha256,
            skill_contract_sha256=skill_contract_sha256,
            eval_set_sha256=eval_set_sha256,
            model_profile_sha256=model_profile_sha256,
            tool_contract_sha256=tool_contract_sha256,
            policy_version_sha256=policy_version_sha256,
            rollback_artifact_sha256=rollback_artifact_sha256,
            cross_tenant_mode=cross_tenant_mode,
            license_sha256=license_sha256,
            deidentification_sha256=deidentification_sha256,
            revocation_contract_sha256=revocation_contract_sha256,
        )
        idempotency_key = _identifier(idempotency_key, "idempotency_key")
        idempotency_sha256 = _digest(idempotency_key)
        predecessor = self._predecessor_relation(
            scope=scope,
            skill_id=values["skill_id"],
            skill_version=values["skill_version"],
            predecessor_candidate_ref=predecessor_candidate_ref,
            supersedes_sha256=supersedes_sha256,
        )
        values["content_sha256"] = _digest(
            {
                "candidate": {
                    key: value
                    for key, value in values.items()
                    if key != "content_sha256"
                },
                "predecessor": predecessor,
            }
        )
        candidate_ref = _stable_ref(
            "gtac",
            [self._scope_payload(scope), values["content_sha256"], idempotency_sha256],
        )
        create_purposes = REQUIRED_PURPOSES_BY_STATE["skill_candidate"]
        if values["cross_tenant_mode"] != "same_tenant":
            create_purposes = create_purposes | frozenset(
                {"license", "deidentification", "revocation"}
            )
        snapshot = self._evidence_snapshot(
            evidence_ids,
            scope=scope,
            data_as_of=cutoff,
            required_purposes=create_purposes,
        )
        request_sha256 = _digest(
            {
                **values,
                "candidate_ref": candidate_ref,
                "data_as_of": _iso(cutoff),
                "evidence": snapshot,
                "predecessor": predecessor,
            }
        )
        try:
            return self._create(
                principal=principal,
                scope=scope,
                cutoff=cutoff,
                values=values,
                candidate_ref=candidate_ref,
                request_sha256=request_sha256,
                idempotency_sha256=idempotency_sha256,
                evidence_ids=evidence_ids,
                predecessor=predecessor,
            )
        except IntegrityError as exc:
            return self._candidate_winner(
                principal=principal,
                scope=scope,
                idempotency_sha256=idempotency_sha256,
                request_sha256=request_sha256,
                cause=exc,
            )

    def transition(
        self,
        *,
        principal: Principal,
        store_ref: str,
        candidate_ref: str,
        as_of: datetime,
        expected_previous_state: str,
        to_state: str,
        reason_code: str,
        evidence_ids: Sequence[str],
        idempotency_key: str,
        eval_baseline_passed: bool = False,
        negative_tests_passed: bool = False,
        scope_tests_passed: bool = False,
        shadow_passed: bool = False,
        external_write_observed: bool = False,
        cost_usd: Any = "0",
        latency_ms: Any = "0",
        token_count: int = 0,
        risk_authority_sha256: str = ZERO_SHA256,
    ) -> dict[str, Any]:
        scope = self._current_scope(principal=principal, store_ref=store_ref)
        cutoff = self._data_as_of(as_of, scope.checked_at)
        candidate_ref = _identifier(candidate_ref, "candidate_ref")
        expected_previous_state = _identifier(
            expected_previous_state, "expected_previous_state"
        )
        to_state = _identifier(to_state, "to_state")
        reason_code = _identifier(reason_code, "reason_code")
        if external_write_observed is not False:
            raise TeamAgentEvolutionError(
                "external_write_observed", "Evolution requires zero external writes"
            )
        gates = {
            "eval_baseline_passed": self._boolean(
                eval_baseline_passed, "eval_baseline_passed"
            ),
            "negative_tests_passed": self._boolean(
                negative_tests_passed, "negative_tests_passed"
            ),
            "scope_tests_passed": self._boolean(
                scope_tests_passed, "scope_tests_passed"
            ),
            "shadow_passed": self._boolean(shadow_passed, "shadow_passed"),
        }
        metrics = {
            "cost_usd": _decimal(cost_usd, "cost_usd"),
            "latency_ms": _decimal(latency_ms, "latency_ms"),
            "token_count": _integer(token_count, "token_count"),
        }
        risk_authority_sha256 = _sha(
            risk_authority_sha256,
            "risk_authority_sha256",
            allow_zero=True,
        )
        required_purposes = REQUIRED_PURPOSES_BY_STATE.get(to_state)
        if required_purposes is None:
            raise TeamAgentEvolutionError("state_invalid", "Target state is invalid")
        with Session(self.engine) as session:
            candidate = session.scalar(
                self._candidate_scope_query(scope).where(
                    TeamAgentEvolutionCandidateRow.candidate_ref == candidate_ref
                )
            )
        if candidate is None:
            raise KeyError("TeamAgent evolution candidate not found")
        if candidate.cross_tenant_mode != "same_tenant":
            required_purposes = required_purposes | frozenset(
                {"license", "deidentification", "revocation"}
            )
        snapshot = self._evidence_snapshot(
            evidence_ids,
            scope=scope,
            data_as_of=cutoff,
            required_purposes=required_purposes,
        )
        actor_role = self._actor_role(principal, to_state)
        idempotency_sha256 = _digest(_identifier(idempotency_key, "idempotency_key"))
        request_sha256 = _digest(
            {
                "candidate_ref": candidate_ref,
                "scope": self._scope_payload(scope),
                "data_as_of": _iso(cutoff),
                "expected_previous_state": expected_previous_state,
                "to_state": to_state,
                "actor_id": principal.actor_id,
                "actor_role": actor_role,
                "reason_code": reason_code,
                **gates,
                "external_write_observed": False,
                "cost_usd": str(metrics["cost_usd"]),
                "latency_ms": str(metrics["latency_ms"]),
                "token_count": metrics["token_count"],
                "risk_authority_sha256": risk_authority_sha256,
                "evidence": snapshot,
            }
        )
        try:
            return self._transition(
                principal=principal,
                scope=scope,
                cutoff=cutoff,
                candidate_ref=candidate_ref,
                expected_previous_state=expected_previous_state,
                to_state=to_state,
                actor_role=actor_role,
                reason_code=reason_code,
                evidence_ids=evidence_ids,
                gates=gates,
                metrics=metrics,
                risk_authority_sha256=risk_authority_sha256,
                idempotency_sha256=idempotency_sha256,
                request_sha256=request_sha256,
            )
        except IntegrityError as exc:
            return self._event_winner(
                principal=principal,
                scope=scope,
                candidate_ref=candidate_ref,
                idempotency_sha256=idempotency_sha256,
                request_sha256=request_sha256,
                cause=exc,
            )

    def get_candidate(
        self,
        *,
        principal: Principal,
        store_ref: str,
        candidate_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        scope = self._current_scope(principal=principal, store_ref=store_ref)
        cutoff = self._data_as_of(as_of, scope.checked_at)
        with Session(self.engine) as session:
            row = session.scalar(
                self._candidate_scope_query(scope).where(
                    TeamAgentEvolutionCandidateRow.candidate_ref == candidate_ref,
                    TeamAgentEvolutionCandidateRow.created_at <= cutoff,
                )
            )
            if row is None:
                raise KeyError("TeamAgent evolution candidate not found")
            return self._projection(session, row, cutoff=cutoff, scope=scope)

    def list_candidates(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        state: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        scope = self._current_scope(principal=principal, store_ref=store_ref)
        cutoff = self._data_as_of(as_of, scope.checked_at)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise TeamAgentEvolutionError("limit_invalid", "limit must be 1..200")
        if state is not None and state not in STATES:
            raise TeamAgentEvolutionError("state_invalid", "State filter is invalid")
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    self._candidate_scope_query(scope)
                    .where(TeamAgentEvolutionCandidateRow.created_at <= cutoff)
                    .order_by(
                        TeamAgentEvolutionCandidateRow.created_at.desc(),
                        TeamAgentEvolutionCandidateRow.candidate_ref.desc(),
                    )
                )
            )
            items = [
                self._projection(session, row, cutoff=cutoff, scope=scope)
                for row in rows
            ]
        if state is not None:
            items = [item for item in items if item["state"] == state]
        return {
            "status": "ready" if items else "no_data",
            "items": items[:limit],
            "total": len(items),
            "observation_only": True,
            "runtime_activation_performed": False,
            "external_write_performed": False,
        }

    def graph_observation(
        self,
        *,
        principal: Principal,
        store_ref: str,
        candidate_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        candidate = self.get_candidate(
            principal=principal,
            store_ref=store_ref,
            candidate_ref=candidate_ref,
            as_of=as_of,
        )
        root_ref = _stable_ref(
            "gtao", [candidate_ref, candidate["content_sha256"]]
        )
        nodes: list[dict[str, Any]] = [
            {
                "node_ref": root_ref,
                "node_type": "SkillVersion",
                "version_sha256": candidate["skill_contract_sha256"],
                "source_sha256": candidate["content_sha256"],
                "effective_from": candidate["created_at"],
                "effective_until": None,
                "status": "observation",
            }
        ]
        edges: list[dict[str, Any]] = []
        events = candidate["events"]
        for index, event in enumerate(events):
            end = events[index + 1]["occurred_at"] if index + 1 < len(events) else None
            node_ref = _stable_ref("gtao", [candidate_ref, event["event_sha256"]])
            nodes.append(
                {
                    "node_ref": node_ref,
                    "node_type": "FailurePattern"
                    if event["to_state"] == "rolled_back"
                    else "Outcome",
                    "version_sha256": event["event_sha256"],
                    "source_sha256": event["evidence_snapshot_sha256"],
                    "effective_from": event["occurred_at"],
                    "effective_until": end,
                    "status": "observation",
                }
            )
            edges.append(
                {
                    "edge_ref": _stable_ref(
                        "gtaoe", [candidate_ref, event["event_sha256"]]
                    ),
                    "edge_type": "invalidated_by"
                    if event["to_state"] == "rolled_back"
                    else "supported_by",
                    "from_node_ref": root_ref,
                    "to_node_ref": node_ref,
                    "source_sha256": event["evidence_snapshot_sha256"],
                    "effective_from": event["occurred_at"],
                    "effective_until": end,
                    "status": "observation",
                }
            )
        return {
            "status": "ready",
            "contract_id": CONTRACT_ID,
            "candidate_ref": candidate_ref,
            "as_of": _iso(_utc(as_of)),
            "nodes": nodes,
            "edges": edges,
            "observation_only": True,
            "gate_eligible": False,
            "canonical_graph_remains_authority": True,
            "graph_write_performed": False,
            "formal_fact_created": False,
            "external_write_performed": False,
        }

    def _create(
        self,
        *,
        principal: Principal,
        scope: _Scope,
        cutoff: datetime,
        values: dict[str, str],
        candidate_ref: str,
        request_sha256: str,
        idempotency_sha256: str,
        evidence_ids: Sequence[str],
        predecessor: dict[str, str] | None,
    ) -> dict[str, Any]:
        with self.evidence.transaction() as session:
            scope = self._lock_and_revalidate_scope(
                session,
                principal=principal,
                scope=scope,
            )
            winner = session.scalar(
                self._candidate_idempotency_query(scope, idempotency_sha256)
                .with_for_update()
            )
            if winner is not None:
                self._same_request(winner.request_sha256, request_sha256)
                return self._projection(session, winner, scope=scope)
            create_purposes = REQUIRED_PURPOSES_BY_STATE["skill_candidate"]
            if values["cross_tenant_mode"] != "same_tenant":
                create_purposes = create_purposes | frozenset(
                    {"license", "deidentification", "revocation"}
                )
                scope = self._lock_cross_tenant_authority_subjects(
                    session,
                    principal=principal,
                    scope=scope,
                    evidence_ids=evidence_ids,
                )
            support = self._support_rows(
                session,
                evidence_ids,
                scope=scope,
                data_as_of=cutoff,
                required_purposes=create_purposes,
            )
            self._enforce_authority_signers(
                candidate_author_actor_id=values["candidate_author_actor_id"],
                human_owner_actor_id=values["human_owner_actor_id"],
                support=support,
            )
            self._candidate_evidence_gates(values=values, support=support)
            row = TeamAgentEvolutionCandidateRow(
                candidate_ref=candidate_ref,
                tenant_ref=scope.tenant_ref,
                entity_ref=scope.entity_ref,
                store_ref=scope.store_ref,
                scope_authority_sha256=scope.authority_sha256,
                candidate_author_actor_id=values["candidate_author_actor_id"],
                human_owner_actor_id=values["human_owner_actor_id"],
                skill_id=values["skill_id"],
                skill_version=values["skill_version"],
                predecessor_candidate_ref=(
                    predecessor["predecessor_candidate_ref"]
                    if predecessor is not None
                    else None
                ),
                predecessor_skill_version=(
                    predecessor["predecessor_skill_version"]
                    if predecessor is not None
                    else None
                ),
                supersedes_candidate_ref=(
                    predecessor["predecessor_candidate_ref"]
                    if predecessor is not None
                    else None
                ),
                supersedes_sha256=(
                    predecessor["supersedes_sha256"]
                    if predecessor is not None
                    else ZERO_SHA256
                ),
                learning_input_type=values["learning_input_type"],
                agent_role_version_sha256=values["agent_role_version_sha256"],
                skill_contract_sha256=values["skill_contract_sha256"],
                eval_set_sha256=values["eval_set_sha256"],
                model_profile_sha256=values["model_profile_sha256"],
                tool_contract_sha256=values["tool_contract_sha256"],
                policy_version_sha256=values["policy_version_sha256"],
                rollback_artifact_sha256=values["rollback_artifact_sha256"],
                cross_tenant_mode=values["cross_tenant_mode"],
                license_sha256=values["license_sha256"],
                deidentification_sha256=values["deidentification_sha256"],
                revocation_contract_sha256=values["revocation_contract_sha256"],
                request_sha256=request_sha256,
                idempotency_sha256=idempotency_sha256,
                content_sha256=values["content_sha256"],
                created_at=scope.checked_at,
            )
            session.add(row)
            session.flush()
            self._append_event(
                session,
                row=row,
                support=support,
                data_as_of=cutoff,
                from_state="observation",
                to_state="skill_candidate",
                actor_id=row.candidate_author_actor_id,
                actor_role="candidate_author",
                reason_code="candidate_created",
                gates=self._empty_gates(),
                cost_usd=Decimal("0"),
                latency_ms=Decimal("0"),
                token_count=0,
                risk_authority_sha256=ZERO_SHA256,
                request_sha256=request_sha256,
                idempotency_sha256=idempotency_sha256,
                occurred_at=scope.checked_at,
            )
            return self._projection(session, row, scope=scope)

    def _transition(
        self,
        *,
        principal: Principal,
        scope: _Scope,
        cutoff: datetime,
        candidate_ref: str,
        expected_previous_state: str,
        to_state: str,
        actor_role: str,
        reason_code: str,
        evidence_ids: Sequence[str],
        gates: dict[str, bool],
        metrics: dict[str, Any],
        risk_authority_sha256: str,
        idempotency_sha256: str,
        request_sha256: str,
    ) -> dict[str, Any]:
        with self.evidence.transaction() as session:
            scope = self._lock_and_revalidate_scope(
                session,
                principal=principal,
                scope=scope,
            )
            row = session.scalar(
                self._candidate_scope_query(scope)
                .where(TeamAgentEvolutionCandidateRow.candidate_ref == candidate_ref)
                .with_for_update()
            )
            if row is None:
                raise KeyError("TeamAgent evolution candidate not found")
            winner = session.scalar(
                self._event_idempotency_query(
                    scope, candidate_ref, idempotency_sha256
                ).with_for_update()
            )
            if winner is not None:
                self._same_request(winner.request_sha256, request_sha256)
                return self._projection(session, row, scope=scope)
            history = self._verified_history(session, row)
            current = history[-1][0].to_state
            if current != expected_previous_state:
                raise TeamAgentEvolutionConflictError(
                    "expected_previous_state differs from the immutable event head"
                )
            self.loop.require_evolution_transition(
                expected_previous_state=current,
                next_state=to_state,
            )
            required_purposes = REQUIRED_PURPOSES_BY_STATE[to_state]
            if row.cross_tenant_mode != "same_tenant":
                required_purposes = required_purposes | frozenset(
                    {"license", "deidentification", "revocation"}
                )
                scope = self._lock_cross_tenant_authority_subjects(
                    session,
                    principal=principal,
                    scope=scope,
                    evidence_ids=evidence_ids,
                )
            support = self._support_rows(
                session,
                evidence_ids,
                scope=scope,
                data_as_of=cutoff,
                required_purposes=required_purposes,
            )
            self._enforce_authority_signers(
                candidate_author_actor_id=row.candidate_author_actor_id,
                human_owner_actor_id=row.human_owner_actor_id,
                support=support,
            )
            self._enforce_sod(
                principal=principal,
                actor_role=actor_role,
                candidate=row,
                history=history,
                to_state=to_state,
                support=support,
            )
            self._transition_gates(
                principal=principal,
                candidate=row,
                history=history,
                from_state=current,
                to_state=to_state,
                gates=gates,
                risk_authority_sha256=risk_authority_sha256,
                support=support,
            )
            event_gates = self._project_event_gates(
                history=history,
                to_state=to_state,
            )
            self._append_event(
                session,
                row=row,
                support=support,
                data_as_of=cutoff,
                from_state=current,
                to_state=to_state,
                actor_id=principal.actor_id,
                actor_role=actor_role,
                reason_code=reason_code,
                gates=event_gates,
                cost_usd=metrics["cost_usd"],
                latency_ms=metrics["latency_ms"],
                token_count=metrics["token_count"],
                risk_authority_sha256=risk_authority_sha256,
                request_sha256=request_sha256,
                idempotency_sha256=idempotency_sha256,
                occurred_at=scope.checked_at,
            )
            return self._projection(session, row, scope=scope)

    def _append_event(
        self,
        session: Session,
        *,
        row: TeamAgentEvolutionCandidateRow,
        support: Sequence[_Attestation],
        data_as_of: datetime,
        from_state: str,
        to_state: str,
        actor_id: str,
        actor_role: str,
        reason_code: str,
        gates: dict[str, bool],
        cost_usd: Decimal,
        latency_ms: Decimal,
        token_count: int,
        risk_authority_sha256: str,
        request_sha256: str,
        idempotency_sha256: str,
        occurred_at: datetime,
    ) -> None:
        previous_rows = self._event_rows(session, row)
        ordinal = len(previous_rows) + 1
        previous_sha = previous_rows[-1].event_sha256 if previous_rows else ZERO_SHA256
        contract = self._event_contract_values(
            session=session,
            row=row,
            support=support,
            previous_rows=previous_rows,
            to_state=to_state,
            occurred_at=occurred_at,
        )
        payload = {
            "candidate_ref": row.candidate_ref,
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_authority_sha256": row.scope_authority_sha256,
            "ordinal": ordinal,
            "from_state": from_state,
            "to_state": to_state,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "reason_code": reason_code,
            **gates,
            "external_write_observed": False,
            "zero_external_writes": True,
            "cost_usd": _decimal_text(cost_usd),
            "latency_ms": _decimal_text(latency_ms),
            "token_count": token_count,
            "risk_authority_sha256": risk_authority_sha256,
            **self._event_contract_hash_payload(contract),
            "prev_event_sha256": previous_sha,
            "request_sha256": request_sha256,
            "idempotency_sha256": idempotency_sha256,
            "data_as_of": _iso(data_as_of),
            "occurred_at": _iso(occurred_at),
        }
        event_sha256 = _event_digest(payload)
        event_ref = _stable_ref(
            "gtae", [row.candidate_ref, ordinal, event_sha256]
        )
        event = TeamAgentEvolutionEventRow(
            event_ref=event_ref,
            candidate_ref=row.candidate_ref,
            tenant_ref=row.tenant_ref,
            entity_ref=row.entity_ref,
            store_ref=row.store_ref,
            scope_authority_sha256=row.scope_authority_sha256,
            ordinal=ordinal,
            from_state=from_state,
            to_state=to_state,
            actor_id=actor_id,
            actor_role=actor_role,
            risk_actor_id=contract["risk_actor_id"],
            reason_code=reason_code,
            eval_baseline_passed=gates["eval_baseline_passed"],
            negative_tests_passed=gates["negative_tests_passed"],
            scope_tests_passed=gates["scope_tests_passed"],
            shadow_passed=gates["shadow_passed"],
            external_write_observed=False,
            zero_external_writes=True,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            token_count=token_count,
            risk_authority_sha256=risk_authority_sha256,
            eval_set_id=contract["eval_set_id"],
            eval_set_version=contract["eval_set_version"],
            eval_set_sha256=contract["eval_set_sha256"],
            baseline_runtime_ref=contract["baseline_runtime_ref"],
            baseline_runtime_sha256=contract["baseline_runtime_sha256"],
            candidate_runtime_ref=contract["candidate_runtime_ref"],
            candidate_runtime_sha256=contract["candidate_runtime_sha256"],
            agent_run_ref=contract["agent_run_ref"],
            agent_run_sha256=contract["agent_run_sha256"],
            eval_snapshot_sha256=contract["eval_snapshot_sha256"],
            result_snapshot_sha256=contract["result_snapshot_sha256"],
            review_verdict=contract["review_verdict"],
            rollback_target_candidate_ref=contract[
                "rollback_target_candidate_ref"
            ],
            rollback_target_skill_version=contract[
                "rollback_target_skill_version"
            ],
            rollback_target_content_sha256=contract[
                "rollback_target_content_sha256"
            ],
            rollback_target_runtime_sha256=contract[
                "rollback_target_runtime_sha256"
            ],
            rollback_target_sha256=contract["rollback_target_sha256"],
            graph_snapshot_sha256=contract["graph_snapshot_sha256"],
            graph_observation_type=contract["graph_observation_type"],
            graph_observation_version=contract["graph_observation_version"],
            graph_effective_from=contract["graph_effective_from"],
            graph_effective_until=contract["graph_effective_until"],
            graph_observation_only=True,
            graph_gate_eligible=False,
            prev_event_sha256=previous_sha,
            event_sha256=event_sha256,
            request_sha256=request_sha256,
            idempotency_sha256=idempotency_sha256,
            data_as_of=data_as_of,
            occurred_at=occurred_at,
        )
        if session.bind is not None and session.bind.dialect.name != "postgresql":
            event.insert_xid = 0
        session.add(event)
        session.flush()
        support_snapshot = [
            {
                "sha256": item.row.blob_sha256,
                "source": item.row.source,
                "source_ref": item.row.source_ref,
                "grade": item.row.grade,
                "purpose": item.purpose,
                "claims_sha256": _digest(item.claims),
            }
            for item in sorted(support, key=lambda item: item.row.blob_sha256)
        ]
        receipt_payload = self._event_audit_payload(
            candidate=row,
            event=event,
            support_snapshot=support_snapshot,
        )
        receipt = self.evidence.capture_team_agent_evolution_event(
            content=_canonical(receipt_payload),
            source_ref=f"team-agent-evolution://{row.candidate_ref}/{event_ref}",
            effective_at=_iso(occurred_at),
            metadata={
                "contract_id": EVIDENCE_CONTRACT_ID,
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_authority_sha256": row.scope_authority_sha256,
                "candidate_ref": row.candidate_ref,
                "event_ref": event_ref,
                "event_sha256": event_sha256,
                "evolution_purpose": "event_audit",
                "supporting_evidence_sha256": _digest(support_snapshot),
                "retention_class": "security",
                "legal_hold": False,
            },
            session=session,
        )
        records: list[tuple[str, EvidenceRecordRow | EvidenceRecord]] = [
            (item.purpose, item.row) for item in support
        ]
        records.append(("event_audit", receipt))
        for link_ordinal, (purpose, record) in enumerate(records, start=1):
            is_row = isinstance(record, EvidenceRecordRow)
            evidence_sha256 = record.blob_sha256 if is_row else record.sha256
            grade = record.grade if is_row else record.grade.value
            session.add(
                TeamAgentEvolutionEvidenceLinkRow(
                    link_ref=_stable_ref(
                        "gtal", [event_ref, link_ordinal, record.id]
                    ),
                    event_ref=event_ref,
                    candidate_ref=row.candidate_ref,
                    tenant_ref=row.tenant_ref,
                    entity_ref=row.entity_ref,
                    store_ref=row.store_ref,
                    scope_authority_sha256=row.scope_authority_sha256,
                    event_insert_xid=event.insert_xid,
                    ordinal=link_ordinal,
                    purpose=purpose,
                    evidence_id=record.id,
                    evidence_sha256=evidence_sha256,
                    evidence_source=record.source,
                    evidence_source_ref=record.source_ref,
                    evidence_grade=grade,
                    evidence_effective_at=_utc(record.effective_at),
                    created_at=occurred_at,
                )
            )
        session.flush()

    @staticmethod
    def _event_audit_payload(
        *,
        candidate: TeamAgentEvolutionCandidateRow,
        event: TeamAgentEvolutionEventRow,
        support_snapshot: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        predecessor = (
            {
                "predecessor_candidate_ref": candidate.predecessor_candidate_ref,
                "predecessor_skill_version": candidate.predecessor_skill_version,
                "supersedes_sha256": candidate.supersedes_sha256,
            }
            if candidate.predecessor_candidate_ref is not None
            else None
        )
        normalized_support = sorted(
            (dict(item) for item in support_snapshot),
            key=lambda item: item["sha256"],
        )
        return {
            "contract_id": EVIDENCE_CONTRACT_ID,
            "candidate_ref": candidate.candidate_ref,
            "event_ref": event.event_ref,
            "event_sha256": event.event_sha256,
            "from_state": event.from_state,
            "to_state": event.to_state,
            "data_as_of": _iso(event.data_as_of),
            "supporting_evidence": normalized_support,
            "supporting_evidence_sha256": _digest(normalized_support),
            "payload_status": "hash_and_code_only",
            "observation_only": True,
            "runtime_activation_performed": False,
            "formal_fact_created": False,
            "external_write_performed": False,
            "predecessor": predecessor,
        }

    def _event_contract_values(
        self,
        *,
        session: Session,
        row: TeamAgentEvolutionCandidateRow,
        support: Sequence[_Attestation],
        previous_rows: Sequence[TeamAgentEvolutionEventRow],
        to_state: str,
        occurred_at: datetime,
    ) -> dict[str, Any]:
        claims = self._claims_by_purpose(support)
        previous = previous_rows[-1] if previous_rows else None
        runtime_sha256 = self._candidate_runtime_sha256(row)
        baseline = claims.get("baseline")
        run = claims.get("agent_run") or claims.get("shadow")
        agent_run_ref = (
            str(run["agent_run_ref"])
            if run is not None
            else (previous.agent_run_ref if previous is not None else None)
        )
        agent_run_sha256 = (
            str(run["snapshot_sha256"])
            if run is not None
            else (
                previous.agent_run_sha256
                if previous is not None
                else ZERO_SHA256
            )
        )
        snapshots = [
            str(item["snapshot_sha256"])
            for item in claims.values()
            if "snapshot_sha256" in item
        ]
        result_snapshot_sha256 = (
            _digest(sorted(snapshots))
            if snapshots
            else (
                previous.result_snapshot_sha256
                if previous is not None
                else ZERO_SHA256
            )
        )
        graph = claims.get("graph_observation")
        graph_snapshot_sha256 = (
            str(graph["graph_snapshot_sha256"])
            if graph is not None
            else (
                previous.graph_snapshot_sha256
                if previous is not None
                else ZERO_SHA256
            )
        )
        risk_actor_id = None
        if to_state == "active":
            risk_actor_id = self._attestation(support, "risk_authority").row.created_by
        review_verdict = {
            "independent_review": "approved",
            "promoted": "approved",
            "active": "approved",
            "rolled_back": "rolled_back",
            "retired": "retired",
        }.get(to_state, "not_reviewed")
        rollback = to_state == "rolled_back"
        rollback_claim = claims.get("rollback")
        rollback_target = (
            self._rollback_target_snapshot(
                session,
                candidate=row,
                claims=rollback_claim,
            )
            if rollback and rollback_claim is not None
            else None
        )
        baseline_runtime_ref = (
            str(baseline["baseline_runtime_ref"])
            if baseline is not None
            else (
                previous.baseline_runtime_ref
                if previous is not None
                else "baseline_unset"
            )
        )
        baseline_runtime_sha256 = (
            str(baseline["baseline_runtime_sha256"])
            if baseline is not None
            else (
                previous.baseline_runtime_sha256
                if previous is not None
                else ZERO_SHA256
            )
        )
        candidate_runtime_ref = (
            str(baseline["candidate_runtime_ref"])
            if baseline is not None
            else (
                previous.candidate_runtime_ref
                if previous is not None
                else _stable_ref("candidate", [row.candidate_ref, row.skill_version])
            )
        )
        graph_effective_from = (
            _utc(datetime.fromisoformat(str(graph["effective_from"])))
            if graph is not None
            else occurred_at
        )
        graph_effective_until = (
            _utc(datetime.fromisoformat(str(graph["effective_until"])))
            if graph is not None and graph["effective_until"] is not None
            else None
        )
        if graph_effective_from > _utc(occurred_at):
            raise TeamAgentEvolutionError(
                "graph_hindsight", "Graph Observation starts after the event clock"
            )
        return {
            "risk_actor_id": risk_actor_id,
            "eval_set_id": self.eval_set.eval_set_id,
            "eval_set_version": self.eval_set.version,
            "eval_set_sha256": row.eval_set_sha256,
            "baseline_runtime_ref": baseline_runtime_ref,
            "baseline_runtime_sha256": baseline_runtime_sha256,
            "candidate_runtime_ref": candidate_runtime_ref,
            "candidate_runtime_sha256": runtime_sha256,
            "agent_run_ref": agent_run_ref,
            "agent_run_sha256": agent_run_sha256,
            "eval_snapshot_sha256": row.eval_set_sha256,
            "result_snapshot_sha256": result_snapshot_sha256,
            "review_verdict": review_verdict,
            "rollback_target_candidate_ref": (
                rollback_target["candidate_ref"]
                if rollback_target is not None
                else None
            ),
            "rollback_target_skill_version": (
                rollback_target["skill_version"]
                if rollback_target is not None
                else None
            ),
            "rollback_target_content_sha256": (
                rollback_target["content_sha256"]
                if rollback_target is not None
                else ZERO_SHA256
            ),
            "rollback_target_runtime_sha256": (
                rollback_target["runtime_sha256"]
                if rollback_target is not None
                else ZERO_SHA256
            ),
            "rollback_target_sha256": (
                row.rollback_artifact_sha256 if rollback else ZERO_SHA256
            ),
            "graph_snapshot_sha256": graph_snapshot_sha256,
            "graph_observation_type": (
                str(graph["graph_type"]) if graph is not None else "none"
            ),
            "graph_observation_version": (
                str(graph["graph_version"]) if graph is not None else "none"
            ),
            "graph_effective_from": graph_effective_from,
            "graph_effective_until": graph_effective_until,
            "graph_observation_only": True,
            "graph_gate_eligible": False,
            "occurred_at": occurred_at,
        }

    @staticmethod
    def _event_contract_hash_payload(contract: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (_iso(value) if isinstance(value, datetime) else value)
            for key, value in contract.items()
            if key != "occurred_at"
        }

    def _candidate_values(
        self,
        *,
        principal: Principal,
        scope: _Scope,
        human_owner_actor_id: str,
        skill_id: str,
        skill_version: str,
        learning_input_type: str,
        agent_role_version_sha256: str,
        skill_contract_sha256: str,
        eval_set_sha256: str,
        model_profile_sha256: str,
        tool_contract_sha256: str,
        policy_version_sha256: str,
        rollback_artifact_sha256: str,
        cross_tenant_mode: str,
        license_sha256: str,
        deidentification_sha256: str,
        revocation_contract_sha256: str,
    ) -> dict[str, str]:
        owner = _identifier(human_owner_actor_id, "human_owner_actor_id")
        author = _identifier(principal.actor_id, "candidate_author_actor_id")
        if owner == author:
            raise TeamAgentEvolutionError(
                "owner_sod", "Human owner must differ from candidate author"
            )
        learning_input_type = _identifier(
            learning_input_type, "learning_input_type"
        )
        if learning_input_type not in LEARNING_INPUT_TYPES:
            raise TeamAgentEvolutionError(
                "learning_input_invalid", "Learning input type is not admitted"
            )
        cross_tenant_mode = _identifier(cross_tenant_mode, "cross_tenant_mode")
        if cross_tenant_mode not in CROSS_TENANT_MODES:
            raise TeamAgentEvolutionError(
                "cross_tenant_rejected", "Cross-tenant mode is not admitted"
            )
        required_hashes = {
            "agent_role_version_sha256": _sha(
                agent_role_version_sha256, "agent_role_version_sha256"
            ),
            "skill_contract_sha256": _sha(
                skill_contract_sha256, "skill_contract_sha256"
            ),
            "eval_set_sha256": _sha(eval_set_sha256, "eval_set_sha256"),
            "model_profile_sha256": _sha(
                model_profile_sha256, "model_profile_sha256"
            ),
            "tool_contract_sha256": _sha(
                tool_contract_sha256, "tool_contract_sha256"
            ),
            "policy_version_sha256": _sha(
                policy_version_sha256, "policy_version_sha256"
            ),
            "rollback_artifact_sha256": _sha(
                rollback_artifact_sha256, "rollback_artifact_sha256"
            ),
        }
        if required_hashes["eval_set_sha256"] != self.eval_set.sha256:
            raise TeamAgentEvolutionError(
                "eval_set_drift", "Candidate must bind the frozen BAS-177 eval set"
            )
        cross_hashes = {
            "license_sha256": _sha(
                license_sha256, "license_sha256", allow_zero=True
            ),
            "deidentification_sha256": _sha(
                deidentification_sha256,
                "deidentification_sha256",
                allow_zero=True,
            ),
            "revocation_contract_sha256": _sha(
                revocation_contract_sha256,
                "revocation_contract_sha256",
                allow_zero=True,
            ),
        }
        if cross_tenant_mode == "same_tenant":
            if any(value != ZERO_SHA256 for value in cross_hashes.values()):
                raise TeamAgentEvolutionError(
                    "cross_tenant_artifact_drift",
                    "Same-tenant mode cannot claim cross-tenant artifacts",
                )
        elif any(value == ZERO_SHA256 for value in cross_hashes.values()):
            raise TeamAgentEvolutionError(
                "cross_tenant_license_missing",
                "Licensed patterns require license, deidentification, "
                "nonreversible mode, and revocation contract hashes",
            )
        content = {
            "contract_id": CONTRACT_ID,
            **self._scope_payload(scope),
            "candidate_author_actor_id": author,
            "human_owner_actor_id": owner,
            "skill_id": _identifier(skill_id, "skill_id"),
            "skill_version": _skill_version(skill_version),
            "learning_input_type": learning_input_type,
            **required_hashes,
            "cross_tenant_mode": cross_tenant_mode,
            **cross_hashes,
        }
        return {**content, "content_sha256": _digest(content)}

    def _candidate_evidence_gates(
        self,
        *,
        values: dict[str, str],
        support: Sequence[_Attestation],
    ) -> None:
        claims = self._claims_by_purpose(support)
        runtime_sha256 = _digest(
            {
                "agent_role_version_sha256": values["agent_role_version_sha256"],
                "skill_contract_sha256": values["skill_contract_sha256"],
                "model_profile_sha256": values["model_profile_sha256"],
                "tool_contract_sha256": values["tool_contract_sha256"],
                "policy_version_sha256": values["policy_version_sha256"],
            }
        )
        if (
            claims["agent_run"]["runtime_sha256"] != runtime_sha256
            or claims["agent_run"]["zero_external_writes"] is not True
            or claims["eval_set"]["eval_set_sha256"] != values["eval_set_sha256"]
            or claims["rollback"]["rollback_artifact_sha256"]
            != values["rollback_artifact_sha256"]
        ):
            raise TeamAgentEvolutionError(
                "candidate_evidence_gate_failed",
                "Candidate runtime/eval/rollback Evidence does not match",
            )
        if values["cross_tenant_mode"] != "same_tenant" and (
            claims["license"]["current"] is not True
            or claims["deidentification"]["current"] is not True
            or claims["deidentification"]["nonreversible"] is not True
            or claims["revocation"]["current"] is not True
            or claims["revocation"]["revoked"] is not False
            or len(
                {
                    claims[purpose]["authority_subject_sha256"]
                    for purpose in ("license", "deidentification", "revocation")
                }
            )
            != 1
            or len(
                {
                    claims[purpose]["authority_epoch"]
                    for purpose in ("license", "deidentification", "revocation")
                }
            )
            != 1
            or claims["license"]["license_sha256"] != values["license_sha256"]
            or claims["deidentification"]["deidentification_sha256"]
            != values["deidentification_sha256"]
            or claims["revocation"]["revocation_contract_sha256"]
            != values["revocation_contract_sha256"]
        ):
            raise TeamAgentEvolutionError(
                "cross_tenant_gate_failed",
                "Licensed cross-tenant Evidence is incomplete",
            )

    def _current_scope(self, *, principal: Principal, store_ref: str) -> _Scope:
        checked_at = _utc(self.clock())
        current = self.scope_grants.current(
            principal=principal,
            store_ref=store_ref,
            as_of=checked_at,
        )
        if current.get("status") != "ready":
            raise PermissionError("Current exact-scope authority is not ready")
        tenant_ref = _identifier(current.get("tenant_ref"), "tenant_ref")
        entity_ref = _identifier(current.get("entity_ref"), "entity_ref")
        returned_store = _identifier(current.get("store_ref"), "store_ref")
        if tenant_ref != principal.tenant_ref or returned_store != store_ref:
            raise PermissionError("Scope authority returned a different exact scope")
        if not principal.can_access_store(store_ref):
            raise PermissionError("Principal cannot access store_ref")
        return _Scope(
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=returned_store,
            authority_sha256=_sha(
                current.get("authority_sha256"), "scope_authority_sha256"
            ),
            checked_at=checked_at,
        )

    def _lock_and_revalidate_scope(
        self,
        session: Session,
        *,
        principal: Principal,
        scope: _Scope,
    ) -> _Scope:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"
                ),
                {
                    "lock_key": "\x1f".join(
                        (scope.tenant_ref, scope.store_ref, principal.actor_id)
                    )
                },
            )
        current = self._current_scope(principal=principal, store_ref=scope.store_ref)
        if (
            current.tenant_ref != scope.tenant_ref
            or current.entity_ref != scope.entity_ref
            or current.store_ref != scope.store_ref
            or not hmac.compare_digest(
                current.authority_sha256,
                scope.authority_sha256,
            )
        ):
            raise PermissionError("Exact-scope authority changed before commit")
        return current

    def _lock_cross_tenant_authority_subjects(
        self,
        session: Session,
        *,
        principal: Principal,
        scope: _Scope,
        evidence_ids: Sequence[str],
    ) -> _Scope:
        rows = list(
            session.scalars(
                select(EvidenceRecordRow).where(
                    EvidenceRecordRow.id.in_(self._evidence_ids(evidence_ids))
                )
            )
        )
        subjects: set[str] = set()
        for row in rows:
            metadata = dict(row.metadata_json or {})
            if metadata.get("evolution_purpose") not in {
                "license",
                "deidentification",
                "revocation",
            }:
                continue
            if any(
                metadata.get(key) != value
                for key, value in self._scope_payload(scope).items()
            ):
                continue
            subjects.add(
                _sha(
                    metadata.get("authority_subject_sha256"),
                    "authority_subject_sha256",
                )
            )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            for subject_sha256 in sorted(subjects):
                session.execute(
                    text(
                        "SELECT pg_advisory_xact_lock("
                        "hashtextextended(:lock_key, 0))"
                    ),
                    {
                        "lock_key": "\x1f".join(
                            (
                                "team-agent-authority",
                                scope.tenant_ref,
                                scope.entity_ref,
                                scope.store_ref,
                                scope.authority_sha256,
                                subject_sha256,
                            )
                        )
                    },
                )
        return self._lock_and_revalidate_scope(
            session,
            principal=principal,
            scope=scope,
        )

    @staticmethod
    def _data_as_of(value: datetime, checked_at: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TeamAgentEvolutionError(
                "timestamp_invalid", "as_of must include timezone"
            )
        cutoff = _utc(value)
        if cutoff > checked_at:
            raise TeamAgentEvolutionError(
                "future_data_as_of", "Data as_of cannot exceed the server clock"
            )
        return cutoff

    @staticmethod
    def _scope_payload(scope: _Scope) -> dict[str, str]:
        return {
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "scope_authority_sha256": scope.authority_sha256,
        }

    def _evidence_snapshot(
        self,
        evidence_ids: Sequence[str],
        *,
        scope: _Scope,
        data_as_of: datetime,
        required_purposes: frozenset[str],
    ) -> list[dict[str, str]]:
        with Session(self.engine) as session:
            rows = self._support_rows(
                session,
                evidence_ids,
                scope=scope,
                data_as_of=data_as_of,
                required_purposes=required_purposes,
            )
            return [
                {
                    "sha256": item.row.blob_sha256,
                    "source": item.row.source,
                    "source_ref": item.row.source_ref,
                    "grade": item.row.grade,
                    "purpose": item.purpose,
                    "claims_sha256": _digest(item.claims),
                }
                for item in sorted(rows, key=lambda item: item.row.blob_sha256)
            ]

    def _support_rows(
        self,
        session: Session,
        evidence_ids: Sequence[str],
        *,
        scope: _Scope,
        data_as_of: datetime,
        required_purposes: frozenset[str],
    ) -> list[_Attestation]:
        normalized = self._evidence_ids(evidence_ids)
        attestations: list[_Attestation] = []
        for evidence_id in normalized:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise TeamAgentEvolutionError(
                    "evidence_missing", "Supporting Evidence is missing"
                )
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            if blob is None or not hmac.compare_digest(
                row.blob_sha256,
                hashlib.sha256(bytes(blob.content_bytes)).hexdigest(),
            ):
                raise TeamAgentEvolutionError(
                    "evidence_tampered", "Supporting Evidence integrity failed"
                )
            metadata = dict(row.metadata_json or {})
            expected = {
                "contract_id": EVIDENCE_CONTRACT_ID,
                **self._scope_payload(scope),
            }
            if any(metadata.get(key) != value for key, value in expected.items()):
                raise TeamAgentEvolutionError(
                    "evidence_scope_invalid",
                    "Supporting Evidence exact-scope binding failed",
                )
            try:
                payload = json.loads(bytes(blob.content_bytes))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TeamAgentEvolutionError(
                    "evidence_payload_invalid", "Evidence payload is not canonical JSON"
                ) from exc
            purpose = str(payload.get("purpose") or "")
            authority_contract = SUPPORT_EVIDENCE_CONTRACTS.get(purpose)
            if (
                authority_contract is None
                or
                payload.get("contract_id") != EVIDENCE_CONTRACT_ID
                or payload.get("source_contract_id")
                != authority_contract.contract_id
                or payload.get("scope") != self._scope_payload(scope)
                or purpose not in EVIDENCE_PURPOSES - {"event_audit"}
                or row.source != authority_contract.source
                or row.grade != authority_contract.grade
                or payload.get("source") != row.source
                or payload.get("source_ref") != row.source_ref
                or payload.get("grade") != row.grade
                or metadata.get("evolution_purpose") != purpose
                or metadata.get("source_contract_id")
                != authority_contract.contract_id
            ):
                raise TeamAgentEvolutionError(
                    "evidence_source_invalid",
                    "Evidence source/grade/ref/purpose binding failed",
                )
            claims = self._validated_claims(purpose, payload.get("claims"))
            if metadata.get("claims_sha256") != _digest(claims):
                raise TeamAgentEvolutionError(
                    "evidence_claims_invalid", "Evidence claims hash drifted"
                )
            effective_at = _utc(row.effective_at)
            effective_until = _utc(row.effective_until) if row.effective_until else None
            recorded_at = _utc(row.recorded_at)
            if effective_at > data_as_of or recorded_at > data_as_of:
                raise TeamAgentEvolutionError(
                    "evidence_hindsight",
                    "Supporting Evidence was unavailable at data as_of",
                )
            if effective_until is not None and scope.checked_at >= effective_until:
                raise TeamAgentEvolutionError(
                    "evidence_expired", "Supporting Evidence is not current"
                )
            if purpose in {"license", "deidentification", "revocation"}:
                self._require_latest_cross_tenant_authority(
                    session,
                    row=row,
                    claims=claims,
                    scope=scope,
                )
            self._verify_agent_run_receipts(
                purpose=purpose,
                claims=claims,
                scope=scope,
                data_as_of=data_as_of,
            )
            attestations.append(_Attestation(row=row, purpose=purpose, claims=claims))
        present = {item.purpose for item in attestations}
        if not required_purposes <= present:
            missing = sorted(required_purposes - present)
            raise TeamAgentEvolutionError(
                "evidence_gate_missing",
                f"Required Evidence purpose is missing: {','.join(missing)}",
            )
        for purpose in required_purposes:
            if sum(item.purpose == purpose for item in attestations) != 1:
                raise TeamAgentEvolutionError(
                    "evidence_cardinality",
                    f"Exactly one {purpose} Evidence is required",
                )
        disallowed = present - required_purposes - {"graph_observation"}
        if disallowed:
            raise TeamAgentEvolutionError(
                "evidence_purpose_unexpected",
                "Unexpected Evidence purpose: " + ",".join(sorted(disallowed)),
            )
        return attestations

    @staticmethod
    def _require_latest_cross_tenant_authority(
        session: Session,
        *,
        row: EvidenceRecordRow,
        claims: dict[str, Any],
        scope: _Scope,
    ) -> None:
        subject_sha256 = claims["authority_subject_sha256"]
        latest = session.scalar(
            select(EvidenceRecordRow)
            .where(
                EvidenceRecordRow.source == row.source,
                EvidenceRecordRow.metadata_json[
                    "authority_subject_sha256"
                ].as_string()
                == subject_sha256,
                EvidenceRecordRow.metadata_json["tenant_ref"].as_string()
                == scope.tenant_ref,
                EvidenceRecordRow.metadata_json["entity_ref"].as_string()
                == scope.entity_ref,
                EvidenceRecordRow.metadata_json["store_ref"].as_string()
                == scope.store_ref,
                EvidenceRecordRow.metadata_json[
                    "scope_authority_sha256"
                ].as_string()
                == scope.authority_sha256,
                EvidenceRecordRow.effective_at <= scope.checked_at,
                EvidenceRecordRow.recorded_at <= scope.checked_at,
            )
            .order_by(
                EvidenceRecordRow.metadata_json["authority_epoch"]
                .as_integer()
                .desc(),
                EvidenceRecordRow.effective_at.desc(),
                EvidenceRecordRow.recorded_at.desc(),
                EvidenceRecordRow.id.desc(),
            )
            .limit(1)
        )
        if latest is None or latest.id != row.id:
            raise TeamAgentEvolutionError(
                "authority_not_latest",
                "Cross-tenant authority Evidence is no longer the latest epoch",
            )

    def _verify_agent_run_receipts(
        self,
        *,
        purpose: str,
        claims: dict[str, Any],
        scope: _Scope,
        data_as_of: datetime,
    ) -> None:
        from .agent_runtime import AgentRunScopeContext, AgentRuntimePolicyError

        receipts: tuple[tuple[str, str], ...]
        if purpose in {"agent_run", "shadow"}:
            receipts = ((claims["agent_run_ref"], claims["snapshot_sha256"]),)
        elif purpose == "baseline":
            receipts = (
                (
                    claims["baseline_agent_run_ref"],
                    claims["baseline_agent_run_sha256"],
                ),
                (
                    claims["candidate_agent_run_ref"],
                    claims["candidate_agent_run_sha256"],
                ),
            )
        else:
            return
        context = AgentRunScopeContext(
            tenant_ref=scope.tenant_ref,
            entity_ref=scope.entity_ref,
            store_ref=scope.store_ref,
            authority_sha256=scope.authority_sha256,
            actor_id="team-agent-evolution-verifier",
            scope_as_of=data_as_of,
            evidence_refs=(),
        )
        for run_ref, expected_sha256 in receipts:
            try:
                detail = self.agent_runs.get_run(context=context, run_id=run_ref)
                last_event_at = _utc(datetime.fromisoformat(detail["last_event_at"]))
                evidence_refs = tuple(
                    item["evidence"] for item in detail.get("events", ())
                )
                self.evidence.require_current(
                    [item["evidence_id"] for item in evidence_refs],
                    as_of=data_as_of,
                )
                if any(
                    self.evidence.get(item["evidence_id"]).sha256
                    != item["evidence_sha256"]
                    for item in evidence_refs
                ):
                    raise ValueError("AgentRun Evidence hash drifted")
            except (AgentRuntimePolicyError, KeyError, RuntimeError, ValueError) as exc:
                raise TeamAgentEvolutionError(
                    "agent_run_receipt_invalid",
                    "AgentRun receipt is missing, stale, out of scope, or corrupted",
                ) from exc
            if (
                detail["status"] != "succeeded"
                or detail["payload_status"] != "not_retained"
                or detail["proposal_only"] is not True
                or detail["formal_fact"] is not False
                or detail["external_write_allowed"] is not False
                or last_event_at > data_as_of
                or not hmac.compare_digest(_digest(detail), expected_sha256)
            ):
                raise TeamAgentEvolutionError(
                    "agent_run_receipt_invalid",
                    "AgentRun receipt failed proposal-only/current/hash Gates",
                )

    @staticmethod
    def _evidence_ids(values: Sequence[str]) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise TeamAgentEvolutionError(
                "evidence_schema", "evidence_ids must be a sequence"
            )
        normalized = tuple(str(value).strip() for value in values)
        if not normalized or any(not value for value in normalized):
            raise TeamAgentEvolutionError(
                "evidence_required", "At least one Evidence record is required"
            )
        if len(normalized) != len(set(normalized)):
            raise TeamAgentEvolutionError(
                "evidence_duplicate", "Duplicate Evidence records are prohibited"
            )
        return normalized

    @staticmethod
    def _boolean(value: Any, field: str) -> bool:
        if not isinstance(value, bool):
            raise TeamAgentEvolutionError("boolean_invalid", f"{field} must be boolean")
        return value

    @staticmethod
    def _validated_claims(purpose: str, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TeamAgentEvolutionError(
                "evidence_claims_invalid", "Evidence claims must be an object"
            )
        schemas: dict[str, set[str]] = {
            "agent_run": {
                "agent_run_ref",
                "runtime_sha256",
                "snapshot_sha256",
                "zero_external_writes",
            },
            "eval_set": {"eval_set_sha256", "snapshot_sha256"},
            "baseline": {
                "baseline_agent_run_ref",
                "baseline_agent_run_sha256",
                "baseline_runtime_ref",
                "baseline_runtime_sha256",
                "candidate_agent_run_ref",
                "candidate_agent_run_sha256",
                "candidate_runtime_ref",
                "candidate_runtime_sha256",
                "baseline_snapshot_sha256",
                "candidate_snapshot_sha256",
                "eval_baseline_passed",
                "negative_tests_passed",
                "scope_tests_passed",
            },
            "shadow": {
                "agent_run_ref",
                "runtime_sha256",
                "snapshot_sha256",
                "shadow_passed",
                "zero_external_writes",
                "cost_usd",
                "latency_ms",
                "token_count",
            },
            "review": {"review_verdict", "snapshot_sha256"},
            "risk_authority": {
                "risk_authority_sha256",
                "current",
                "snapshot_sha256",
            },
            "rollback": {
                "rollback_target_ref",
                "rollback_version",
                "rollback_target_content_sha256",
                "rollback_target_runtime_sha256",
                "rollback_artifact_sha256",
                "snapshot_sha256",
            },
            "license": {
                "license_sha256",
                "authority_subject_sha256",
                "authority_epoch",
                "current",
                "snapshot_sha256",
            },
            "deidentification": {
                "deidentification_sha256",
                "authority_subject_sha256",
                "authority_epoch",
                "current",
                "nonreversible",
                "snapshot_sha256",
            },
            "revocation": {
                "revocation_contract_sha256",
                "authority_subject_sha256",
                "authority_epoch",
                "current",
                "revoked",
                "snapshot_sha256",
            },
            "retirement": {"retirement_sha256", "snapshot_sha256"},
            "graph_observation": {
                "graph_snapshot_sha256",
                "graph_type",
                "graph_version",
                "effective_from",
                "effective_until",
                "observation_only",
                "gate_eligible",
            },
        }
        expected = schemas.get(purpose)
        if expected is None or set(value) != expected:
            raise TeamAgentEvolutionError(
                "evidence_claims_invalid", f"{purpose} claims fields drifted"
            )
        result = dict(value)
        for key in tuple(result):
            if key.endswith("sha256"):
                result[key] = _sha(
                    result[key],
                    key,
                    allow_zero=(
                        purpose == "rollback"
                        and key
                        in {
                            "rollback_target_content_sha256",
                            "rollback_target_runtime_sha256",
                        }
                    ),
                )
        if "agent_run_ref" in result:
            result["agent_run_ref"] = _identifier(
                result["agent_run_ref"], "agent_run_ref"
            )
        for field in (
            "baseline_agent_run_ref",
            "baseline_runtime_ref",
            "candidate_agent_run_ref",
            "candidate_runtime_ref",
        ):
            if field in result:
                result[field] = _identifier(result[field], field)
        if purpose == "shadow":
            result["cost_usd"] = str(_decimal(result["cost_usd"], "cost_usd"))
            result["latency_ms"] = str(
                _decimal(result["latency_ms"], "latency_ms")
            )
            result["token_count"] = _integer(result["token_count"], "token_count")
        boolean_fields = {
            "zero_external_writes",
            "eval_baseline_passed",
            "negative_tests_passed",
            "scope_tests_passed",
            "shadow_passed",
            "current",
            "revoked",
            "nonreversible",
            "observation_only",
            "gate_eligible",
        }
        for key in boolean_fields.intersection(result):
            if not isinstance(result[key], bool):
                raise TeamAgentEvolutionError(
                    "evidence_claims_invalid", f"{key} must be boolean"
                )
        if "authority_epoch" in result:
            epoch = result["authority_epoch"]
            if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0:
                raise TeamAgentEvolutionError(
                    "authority_epoch_invalid",
                    "authority_epoch must be a positive integer",
                )
        if purpose == "review" and result["review_verdict"] not in {
            "approved",
            "rejected",
        }:
            raise TeamAgentEvolutionError(
                "review_verdict_invalid", "Review verdict is invalid"
            )
        if purpose == "rollback":
            result["rollback_target_ref"] = _identifier(
                result["rollback_target_ref"], "rollback_target_ref"
            )
            result["rollback_version"] = _identifier(
                result["rollback_version"], "rollback_version"
            )
        if purpose == "graph_observation":
            result["graph_type"] = _identifier(result["graph_type"], "graph_type")
            result["graph_version"] = _identifier(
                result["graph_version"], "graph_version"
            )
            try:
                start = _utc(datetime.fromisoformat(result["effective_from"]))
                end = _utc(datetime.fromisoformat(result["effective_until"]))
            except (TypeError, ValueError) as exc:
                raise TeamAgentEvolutionError(
                    "graph_interval_invalid", "Graph interval is invalid"
                ) from exc
            if end <= start:
                raise TeamAgentEvolutionError(
                    "graph_interval_invalid", "Graph interval must be positive"
                )
            if result["observation_only"] is not True or result["gate_eligible"] is not False:
                raise TeamAgentEvolutionError(
                    "graph_gate_prohibited",
                    "Graph projection must remain an ineligible Observation",
                )
            result["effective_from"] = _iso(start)
            result["effective_until"] = _iso(end)
        return result

    @staticmethod
    def _empty_gates() -> dict[str, bool]:
        return {
            "eval_baseline_passed": False,
            "negative_tests_passed": False,
            "scope_tests_passed": False,
            "shadow_passed": False,
        }

    @staticmethod
    def _project_event_gates(
        *,
        history: Sequence[
            tuple[TeamAgentEvolutionEventRow, list[TeamAgentEvolutionEvidenceLinkRow]]
        ],
        to_state: str,
    ) -> dict[str, bool]:
        if to_state in {"skill_candidate", "evaluation"}:
            return GovernedTeamAgentEvolutionWorkspace._empty_gates()
        if to_state == "shadow":
            return {
                "eval_baseline_passed": True,
                "negative_tests_passed": True,
                "scope_tests_passed": True,
                "shadow_passed": False,
            }
        if to_state in {"independent_review", "promoted", "active"}:
            return {
                "eval_baseline_passed": True,
                "negative_tests_passed": True,
                "scope_tests_passed": True,
                "shadow_passed": True,
            }
        if not history:
            raise TeamAgentEvolutionIntegrityError("Terminal Gate history is missing")
        previous = history[-1][0]
        return {
            "eval_baseline_passed": previous.eval_baseline_passed,
            "negative_tests_passed": previous.negative_tests_passed,
            "scope_tests_passed": previous.scope_tests_passed,
            "shadow_passed": previous.shadow_passed,
        }

    @staticmethod
    def _actor_role(principal: Principal, to_state: str) -> str:
        if to_state == "evaluation":
            admitted = frozenset({"monitor", "reviewer", "risk", "compliance", "admin"})
            governed_role = "evaluator"
        elif to_state == "shadow":
            admitted = INDEPENDENT_ROLES
            governed_role = "shadow_operator"
        elif to_state == "independent_review":
            admitted = INDEPENDENT_ROLES
            governed_role = "independent_reviewer"
        elif to_state == "promoted":
            admitted = PROMOTION_ROLES
            governed_role = "promoter"
        elif to_state == "active":
            admitted = PROMOTION_ROLES
            governed_role = "human_owner"
        elif to_state in {"rolled_back", "retired"}:
            if principal.has_any_role("risk"):
                return "risk"
            if principal.has_any_role("compliance", "admin"):
                return "compliance"
            admitted = frozenset({"approver"})
            governed_role = "human_owner"
        else:
            admitted = frozenset({"operator", "monitor", "admin"})
            governed_role = "candidate_author"
        if not principal.roles.intersection(admitted):
            raise PermissionError("Actor role is not admitted for this transition")
        return governed_role

    @staticmethod
    def _enforce_authority_signers(
        *,
        candidate_author_actor_id: str,
        human_owner_actor_id: str,
        support: Sequence[_Attestation],
    ) -> None:
        authority_purposes = {
            "eval_set",
            "baseline",
            "shadow",
            "review",
            "risk_authority",
            "rollback",
            "license",
            "deidentification",
            "revocation",
            "retirement",
        }
        forbidden = {candidate_author_actor_id, human_owner_actor_id}
        if any(
            item.purpose in authority_purposes
            and item.row.created_by in forbidden
            for item in support
        ):
            raise PermissionError(
                "Team-agent authority signer must differ from author and owner"
            )

    def _enforce_sod(
        self,
        *,
        principal: Principal,
        actor_role: str,
        candidate: TeamAgentEvolutionCandidateRow,
        history: Sequence[
            tuple[
                TeamAgentEvolutionEventRow,
                list[TeamAgentEvolutionEvidenceLinkRow],
            ]
        ],
        to_state: str,
        support: Sequence[_Attestation],
    ) -> None:
        actors = {event.to_state: event.actor_id for event, _ in history}
        author = candidate.candidate_author_actor_id
        owner = candidate.human_owner_actor_id
        actor = principal.actor_id
        evaluator = actors.get("evaluation")
        shadow = actors.get("shadow")
        reviewer = actors.get("independent_review")
        promoter = actors.get("promoted")
        if to_state == "evaluation" and actor in {author, owner}:
            raise PermissionError("Evaluator must differ from author and owner")
        if to_state == "shadow" and actor in {author, owner, evaluator}:
            raise PermissionError(
                "Shadow operator must differ from author, owner, and evaluator"
            )
        if to_state == "independent_review" and actor in {
            author,
            owner,
            evaluator,
            shadow,
        }:
            raise PermissionError(
                "Reviewer must differ from every prior Gate actor and owner"
            )
        if to_state == "promoted":
            risk_actor = self._attestation(support, "risk_authority").row.created_by
            if risk_actor in {author, owner, evaluator, shadow, reviewer}:
                raise PermissionError(
                    "Risk signer must differ from author, owner, and Gate actors"
                )
            if actor in {author, owner, evaluator, shadow, reviewer, risk_actor}:
                raise PermissionError(
                    "Promoter must differ from author, owner, Gate, and risk actors"
                )
        if to_state == "active":
            risk_actor = self._attestation(support, "risk_authority").row.created_by
            if actor != owner or risk_actor in {
                author,
                owner,
                evaluator,
                shadow,
                reviewer,
                promoter,
            }:
                raise PermissionError(
                    "Activation requires the owner and an independent risk actor"
                )
        if to_state in {"rolled_back", "retired"}:
            if actor_role == "human_owner" and actor != owner:
                raise PermissionError("Terminal owner action requires the human owner")
            if actor_role in {"risk", "compliance"} and actor in {author, owner}:
                raise PermissionError(
                    "Terminal risk/compliance actor must be independent"
                )

    def _transition_gates(
        self,
        *,
        principal: Principal,
        candidate: TeamAgentEvolutionCandidateRow,
        history: Sequence[
            tuple[TeamAgentEvolutionEventRow, list[TeamAgentEvolutionEvidenceLinkRow]]
        ],
        from_state: str,
        to_state: str,
        gates: dict[str, bool],
        risk_authority_sha256: str,
        support: Sequence[_Attestation],
    ) -> None:
        claims = self._claims_by_purpose(support)
        if (
            to_state
            in {"evaluation", "shadow", "independent_review", "promoted", "active"}
            and principal.actor_id == candidate.candidate_author_actor_id
        ):
            raise PermissionError(
                "Candidate author cannot verify, review, promote, or activate"
            )
        self._cross_tenant_gate(candidate, claims)
        candidate_runtime_sha256 = self._candidate_runtime_sha256(candidate)
        if to_state in {"evaluation", "shadow", "promoted", "active"}:
            eval_set = claims.get("eval_set")
            if eval_set is not None and eval_set["eval_set_sha256"] != candidate.eval_set_sha256:
                raise TeamAgentEvolutionError(
                    "eval_set_drift", "Frozen eval-set Evidence does not match candidate"
                )
            baseline = claims.get("baseline")
            if baseline is not None and baseline["candidate_runtime_sha256"] != candidate_runtime_sha256:
                raise TeamAgentEvolutionError(
                    "runtime_drift", "Candidate runtime hash differs from baseline Evidence"
                )
            agent_run = claims.get("agent_run")
            if agent_run is not None and (
                agent_run["runtime_sha256"] != candidate_runtime_sha256
                or agent_run["zero_external_writes"] is not True
            ):
                raise TeamAgentEvolutionError(
                    "agent_run_gate_failed", "AgentRun runtime/zero-write Gate failed"
                )
            if baseline is not None and agent_run is not None and (
                baseline["candidate_agent_run_ref"] != agent_run["agent_run_ref"]
                or baseline["candidate_agent_run_sha256"]
                != agent_run["snapshot_sha256"]
            ):
                raise TeamAgentEvolutionError(
                    "agent_run_receipt_drift",
                    "Baseline and candidate AgentRun receipts differ",
                )
        if from_state == "evaluation" and to_state == "shadow":
            baseline = claims["baseline"]
            evidence_gates = {
                key: baseline[key]
                for key in (
                    "eval_baseline_passed",
                    "negative_tests_passed",
                    "scope_tests_passed",
                )
            }
            if evidence_gates != {key: gates[key] for key in evidence_gates} or not all(
                evidence_gates.values()
            ):
                raise TeamAgentEvolutionError(
                    "eval_gate_failed",
                    "Evidence-backed baseline, negative, and scope Gates are required",
                )
            shadow = claims["shadow"]
            agent_run = claims["agent_run"]
            if (
                shadow["agent_run_ref"] != agent_run["agent_run_ref"]
                or shadow["snapshot_sha256"] != agent_run["snapshot_sha256"]
                or baseline["candidate_agent_run_ref"] != agent_run["agent_run_ref"]
                or baseline["candidate_agent_run_sha256"]
                != agent_run["snapshot_sha256"]
                or shadow["runtime_sha256"] != candidate_runtime_sha256
                or shadow["zero_external_writes"] is not True
                or shadow["shadow_passed"] is not True
            ):
                raise TeamAgentEvolutionError(
                    "shadow_gate_failed", "Evidence-backed zero-write shadow failed"
                )
            if not principal.roles.intersection(INDEPENDENT_ROLES):
                raise PermissionError("Independent evaluator role required")
        if from_state == "shadow" and to_state == "independent_review":
            shadow = claims["shadow"]
            review = claims["review"]
            review_attestation = self._attestation(support, "review")
            if (
                not gates["shadow_passed"]
                or shadow["shadow_passed"] is not True
                or shadow["zero_external_writes"] is not True
                or review["review_verdict"] != "approved"
                or review_attestation.row.created_by != principal.actor_id
            ):
                raise TeamAgentEvolutionError(
                    "review_gate_failed", "Evidence-backed shadow/review is required"
                )
            self._prior_eval(history)
            if not principal.roles.intersection(INDEPENDENT_ROLES):
                raise PermissionError("Independent reviewer role required")
            prior_gate_actors = {
                event.actor_id
                for event, _ in history
                if event.to_state in {"evaluation", "shadow"}
            }
            if principal.actor_id in prior_gate_actors:
                raise PermissionError("Reviewer must differ from prior Gate actors")
        if from_state == "independent_review" and to_state == "promoted":
            self._prior_eval(history)
            review = history[-1][0]
            review_attestation = self._attestation(support, "review")
            risk_attestation = self._attestation(support, "risk_authority")
            if (
                review.actor_id == candidate.candidate_author_actor_id
                or review.actor_role != "independent_reviewer"
                or not review.shadow_passed
                or claims["review"]["review_verdict"] != "approved"
                or review_attestation.row.created_by != review.actor_id
                or claims["risk_authority"]["current"] is not True
            ):
                raise TeamAgentEvolutionError(
                    "review_gate_failed", "Independent review Gate is incomplete"
                )
            if not principal.roles.intersection(PROMOTION_ROLES):
                raise PermissionError("Promotion authority required")
            forbidden = {
                candidate.candidate_author_actor_id,
                candidate.human_owner_actor_id,
                review.actor_id,
                risk_attestation.row.created_by,
            }
            if principal.actor_id in forbidden:
                raise PermissionError(
                    "Promoter must differ from author, reviewer, risk, and owner"
                )
        if from_state == "promoted" and to_state == "active":
            self._prior_eval(history)
            if principal.actor_id != candidate.human_owner_actor_id:
                raise PermissionError("Only the human owner may activate")
            if not principal.roles.intersection(PROMOTION_ROLES):
                raise PermissionError("Risk/approval authority required")
            _sha(risk_authority_sha256, "risk_authority_sha256")
            risk = claims["risk_authority"]
            review_actor = next(
                event.actor_id
                for event, _ in reversed(history)
                if event.to_state == "independent_review"
            )
            review_attestation = self._attestation(support, "review")
            risk_attestation = self._attestation(support, "risk_authority")
            if (
                risk["current"] is not True
                or risk["risk_authority_sha256"] != risk_authority_sha256
                or review_attestation.row.created_by != review_actor
                or risk_attestation.row.created_by
                in {candidate.candidate_author_actor_id, candidate.human_owner_actor_id}
            ):
                raise TeamAgentEvolutionError(
                    "risk_authority_invalid", "Current independent risk authority is required"
                )
        if to_state == "rolled_back":
            _sha(candidate.rollback_artifact_sha256, "rollback_artifact_sha256")
            rollback = claims["rollback"]
            if rollback["rollback_artifact_sha256"] != candidate.rollback_artifact_sha256:
                raise TeamAgentEvolutionError(
                    "rollback_artifact_drift", "Rollback artifact hash drifted"
                )
            owner = principal.actor_id == candidate.human_owner_actor_id
            independent_risk = principal.has_any_role("risk", "compliance", "admin")
            if not (owner or independent_risk):
                raise PermissionError("Rollback requires owner or independent risk/compliance")

    @staticmethod
    def _claims_by_purpose(
        support: Sequence[_Attestation],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in support:
            if item.purpose == "graph_observation":
                continue
            previous = result.get(item.purpose)
            if previous is not None and previous != item.claims:
                raise TeamAgentEvolutionError(
                    "evidence_claim_conflict",
                    f"Conflicting {item.purpose} Evidence claims",
                )
            result[item.purpose] = item.claims
        return result

    @staticmethod
    def _attestation(
        support: Sequence[_Attestation], purpose: str
    ) -> _Attestation:
        matches = [item for item in support if item.purpose == purpose]
        if len(matches) != 1:
            raise TeamAgentEvolutionError(
                "evidence_cardinality", f"Exactly one {purpose} Evidence is required"
            )
        return matches[0]

    @staticmethod
    def _candidate_runtime_sha256(candidate: TeamAgentEvolutionCandidateRow) -> str:
        return _digest(
            {
                "agent_role_version_sha256": candidate.agent_role_version_sha256,
                "skill_contract_sha256": candidate.skill_contract_sha256,
                "model_profile_sha256": candidate.model_profile_sha256,
                "tool_contract_sha256": candidate.tool_contract_sha256,
                "policy_version_sha256": candidate.policy_version_sha256,
            }
        )

    @staticmethod
    def _cross_tenant_gate(
        candidate: TeamAgentEvolutionCandidateRow,
        claims: dict[str, dict[str, Any]],
    ) -> None:
        if candidate.cross_tenant_mode == "same_tenant":
            return
        license_claim = claims.get("license")
        deidentification_claim = claims.get("deidentification")
        revocation_claim = claims.get("revocation")
        if (
            license_claim is None
            or deidentification_claim is None
            or revocation_claim is None
            or license_claim["current"] is not True
            or deidentification_claim["current"] is not True
            or deidentification_claim["nonreversible"] is not True
            or revocation_claim["current"] is not True
            or revocation_claim["revoked"] is not False
            or len(
                {
                    license_claim["authority_subject_sha256"],
                    deidentification_claim["authority_subject_sha256"],
                    revocation_claim["authority_subject_sha256"],
                }
            )
            != 1
            or len(
                {
                    license_claim["authority_epoch"],
                    deidentification_claim["authority_epoch"],
                    revocation_claim["authority_epoch"],
                }
            )
            != 1
            or license_claim["license_sha256"] != candidate.license_sha256
            or deidentification_claim["deidentification_sha256"]
            != candidate.deidentification_sha256
            or revocation_claim["revocation_contract_sha256"]
            != candidate.revocation_contract_sha256
        ):
            raise TeamAgentEvolutionError(
                "cross_tenant_gate_failed",
                "Licensed deidentified nonreversible pattern Gate is incomplete",
            )

    @staticmethod
    def _prior_eval(
        history: Sequence[
            tuple[TeamAgentEvolutionEventRow, list[TeamAgentEvolutionEvidenceLinkRow]]
        ],
    ) -> None:
        shadows = [event for event, _ in history if event.to_state == "shadow"]
        if not shadows:
            raise TeamAgentEvolutionError(
                "eval_history_missing", "Passed eval history is missing"
            )
        event = shadows[-1]
        if not (
            event.eval_baseline_passed
            and event.negative_tests_passed
            and event.scope_tests_passed
            and not event.external_write_observed
        ):
            raise TeamAgentEvolutionError(
                "eval_history_invalid", "Passed eval history is invalid"
            )

    def replay(
        self,
        *,
        principal: Principal,
        store_ref: str,
        candidate_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        result = self.get_candidate(
            principal=principal,
            store_ref=store_ref,
            candidate_ref=candidate_ref,
            as_of=as_of,
        )
        return {
            **result,
            "replay": True,
            "network_invoked": False,
            "runtime_activation_performed": False,
        }

    def _predecessor_relation(
        self,
        *,
        scope: _Scope,
        skill_id: str,
        skill_version: str,
        predecessor_candidate_ref: str | None,
        supersedes_sha256: str,
    ) -> dict[str, str] | None:
        if predecessor_candidate_ref is None:
            if _sha(supersedes_sha256, "supersedes_sha256", allow_zero=True) != ZERO_SHA256:
                raise TeamAgentEvolutionError(
                    "predecessor_missing", "supersedes hash requires predecessor"
                )
            return None
        predecessor_candidate_ref = _identifier(
            predecessor_candidate_ref, "predecessor_candidate_ref"
        )
        supersedes_sha256 = _sha(supersedes_sha256, "supersedes_sha256")
        with Session(self.engine) as session:
            row = session.scalar(
                self._candidate_scope_query(scope).where(
                    TeamAgentEvolutionCandidateRow.candidate_ref
                    == predecessor_candidate_ref
                )
            )
            if row is None:
                raise TeamAgentEvolutionError(
                    "predecessor_missing", "Predecessor is not visible in exact scope"
                )
            history = self._verified_history(session, row)
            if history[-1][0].to_state not in {"rolled_back", "retired"}:
                raise TeamAgentEvolutionError(
                    "predecessor_not_terminal",
                    "Only rolled-back or retired candidate may be superseded",
                )
            if (
                row.skill_id != skill_id
                or tuple(map(int, skill_version.split(".")))
                <= tuple(map(int, row.skill_version.split(".")))
                or row.content_sha256 != supersedes_sha256
            ):
                raise TeamAgentEvolutionError(
                    "supersedes_drift", "Predecessor skill/version/hash does not match"
                )
        return {
            "predecessor_candidate_ref": predecessor_candidate_ref,
            "predecessor_skill_version": row.skill_version,
            "supersedes_sha256": supersedes_sha256,
        }

    def _rollback_target_snapshot(
        self,
        session: Session,
        *,
        candidate: TeamAgentEvolutionCandidateRow,
        claims: dict[str, Any],
    ) -> dict[str, str]:
        target_ref = str(claims["rollback_target_ref"])
        if target_ref == candidate.candidate_ref:
            raise TeamAgentEvolutionError(
                "rollback_target_self",
                "Rollback target must differ from the current candidate",
            )
        target = session.scalar(
            select(TeamAgentEvolutionCandidateRow).where(
                TeamAgentEvolutionCandidateRow.candidate_ref == target_ref,
                TeamAgentEvolutionCandidateRow.tenant_ref == candidate.tenant_ref,
                TeamAgentEvolutionCandidateRow.entity_ref == candidate.entity_ref,
                TeamAgentEvolutionCandidateRow.store_ref == candidate.store_ref,
                TeamAgentEvolutionCandidateRow.scope_authority_sha256
                == candidate.scope_authority_sha256,
            )
        )
        if target is None:
            raise TeamAgentEvolutionError(
                "rollback_target_missing",
                "Rollback target is not visible in exact scope",
            )
        runtime_sha256 = self._candidate_runtime_sha256(target)
        if (
            target.skill_id != candidate.skill_id
            or target.skill_version != claims["rollback_version"]
            or target.content_sha256
            != claims["rollback_target_content_sha256"]
            or runtime_sha256 != claims["rollback_target_runtime_sha256"]
        ):
            raise TeamAgentEvolutionError(
                "rollback_target_drift",
                "Rollback target skill/version/content/runtime differs",
            )
        target_history = self._verified_history(session, target)
        if not any(
            event.to_state in {"promoted", "active"}
            and event.review_verdict == "approved"
            for event, _ in target_history
        ):
            raise TeamAgentEvolutionError(
                "rollback_target_unapproved",
                "Rollback target has no approved promoted/active snapshot",
            )
        return {
            "candidate_ref": target.candidate_ref,
            "skill_version": target.skill_version,
            "content_sha256": target.content_sha256,
            "runtime_sha256": runtime_sha256,
        }

    def _verified_history(
        self,
        session: Session,
        row: TeamAgentEvolutionCandidateRow,
        *,
        cutoff: datetime | None = None,
    ) -> list[
        tuple[TeamAgentEvolutionEventRow, list[TeamAgentEvolutionEvidenceLinkRow]]
    ]:
        self._verify_candidate(row)
        events = self._event_rows(session, row)
        if cutoff is not None:
            events = [event for event in events if _utc(event.occurred_at) <= cutoff]
        if not events:
            raise TeamAgentEvolutionIntegrityError("Candidate event history is empty")
        previous_sha = ZERO_SHA256
        previous_state = "observation"
        result: list[
            tuple[TeamAgentEvolutionEventRow, list[TeamAgentEvolutionEvidenceLinkRow]]
        ] = []
        for ordinal, event in enumerate(events, start=1):
            if (
                event.ordinal != ordinal
                or event.prev_event_sha256 != previous_sha
                or event.from_state != previous_state
                or not hmac.compare_digest(
                    event.event_sha256,
                    _event_digest(self._event_hash_payload(event)),
                )
            ):
                raise TeamAgentEvolutionIntegrityError(
                    "Evolution event state/hash chain is invalid"
                )
            try:
                self.loop.require_evolution_transition(
                    expected_previous_state=event.from_state,
                    next_state=event.to_state,
                )
            except ValueError as exc:
                raise TeamAgentEvolutionIntegrityError(
                    "Evolution event transition is invalid"
                ) from exc
            links = list(
                session.scalars(
                    select(TeamAgentEvolutionEvidenceLinkRow)
                    .where(
                        TeamAgentEvolutionEvidenceLinkRow.event_ref
                        == event.event_ref,
                        TeamAgentEvolutionEvidenceLinkRow.candidate_ref
                        == row.candidate_ref,
                        TeamAgentEvolutionEvidenceLinkRow.tenant_ref == row.tenant_ref,
                        TeamAgentEvolutionEvidenceLinkRow.entity_ref == row.entity_ref,
                        TeamAgentEvolutionEvidenceLinkRow.store_ref == row.store_ref,
                        TeamAgentEvolutionEvidenceLinkRow.scope_authority_sha256
                        == row.scope_authority_sha256,
                    )
                    .order_by(TeamAgentEvolutionEvidenceLinkRow.ordinal)
                )
            )
            self._verify_event_evidence(session, candidate=row, event=event, links=links)
            result.append((event, links))
            previous_sha = event.event_sha256
            previous_state = event.to_state
        return result

    def _verify_event_evidence(
        self,
        session: Session,
        *,
        candidate: TeamAgentEvolutionCandidateRow,
        event: TeamAgentEvolutionEventRow,
        links: Sequence[TeamAgentEvolutionEvidenceLinkRow],
    ) -> None:
        if len(links) < 2 or [link.ordinal for link in links] != list(
            range(1, len(links) + 1)
        ):
            raise TeamAgentEvolutionIntegrityError(
                "Event requires 1..N source Evidence plus one audit Evidence"
            )
        audit_links = [link for link in links if link.purpose == "event_audit"]
        if len(audit_links) != 1:
            raise TeamAgentEvolutionIntegrityError(
                "Event must have exactly one event_audit Evidence"
            )
        support_snapshot: list[dict[str, str]] = []
        support_claims: dict[str, list[dict[str, Any]]] = {}
        audit_metadata: dict[str, Any] | None = None
        audit_payload: dict[str, Any] | None = None
        for link in links:
            evidence = session.get(EvidenceRecordRow, link.evidence_id)
            if evidence is None:
                raise TeamAgentEvolutionIntegrityError("Linked Evidence is missing")
            blob = session.get(EvidenceBlobRow, evidence.blob_sha256)
            if blob is None or not hmac.compare_digest(
                evidence.blob_sha256,
                hashlib.sha256(bytes(blob.content_bytes)).hexdigest(),
            ):
                raise TeamAgentEvolutionIntegrityError("Linked Evidence was tampered")
            if not all(
                (
                    link.evidence_sha256 == evidence.blob_sha256,
                    link.evidence_source == evidence.source,
                    link.evidence_source_ref == evidence.source_ref,
                    link.evidence_grade == evidence.grade,
                    _utc(link.evidence_effective_at) == _utc(evidence.effective_at),
                )
            ):
                raise TeamAgentEvolutionIntegrityError(
                    "Linked Evidence source/grade/ref binding drifted"
                )
            metadata = dict(evidence.metadata_json or {})
            exact = {
                "tenant_ref": candidate.tenant_ref,
                "entity_ref": candidate.entity_ref,
                "store_ref": candidate.store_ref,
                "scope_authority_sha256": candidate.scope_authority_sha256,
            }
            if any(metadata.get(key) != value for key, value in exact.items()):
                raise TeamAgentEvolutionIntegrityError(
                    "Linked Evidence exact scope drifted"
                )
            if link.purpose == "event_audit":
                audit_metadata = metadata
                if (
                    evidence.source != EVIDENCE_SOURCE
                    or evidence.grade != EvidenceGrade.D.value
                    or evidence.source_ref
                    != f"team-agent-evolution://{candidate.candidate_ref}/{event.event_ref}"
                    or metadata.get("event_ref") != event.event_ref
                    or metadata.get("event_sha256") != event.event_sha256
                ):
                    raise TeamAgentEvolutionIntegrityError(
                        "event_audit Evidence contract drifted"
                    )
                try:
                    audit_payload = json.loads(bytes(blob.content_bytes))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise TeamAgentEvolutionIntegrityError(
                        "event_audit payload is invalid"
                    ) from exc
            else:
                try:
                    payload = json.loads(bytes(blob.content_bytes))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise TeamAgentEvolutionIntegrityError(
                        "Supporting Evidence payload is invalid"
                    ) from exc
                authority_contract = SUPPORT_EVIDENCE_CONTRACTS.get(link.purpose)
                if (
                    authority_contract is None
                    or evidence.source != authority_contract.source
                    or evidence.grade != authority_contract.grade
                    or payload.get("source_contract_id")
                    != authority_contract.contract_id
                    or metadata.get("source_contract_id")
                    != authority_contract.contract_id
                    or
                    payload.get("source") != evidence.source
                    or payload.get("source_ref") != evidence.source_ref
                    or payload.get("grade") != evidence.grade
                    or payload.get("purpose") != link.purpose
                    or _utc(evidence.effective_at) > _utc(event.occurred_at)
                    or _utc(evidence.recorded_at) > _utc(event.occurred_at)
                ):
                    raise TeamAgentEvolutionIntegrityError(
                        "Supporting Evidence temporal/source binding drifted"
                    )
                claims = self._validated_claims(link.purpose, payload.get("claims"))
                support_claims.setdefault(link.purpose, []).append(claims)
                support_snapshot.append(
                    {
                        "sha256": evidence.blob_sha256,
                        "source": evidence.source,
                        "source_ref": evidence.source_ref,
                        "grade": evidence.grade,
                        "purpose": link.purpose,
                        "claims_sha256": _digest(claims),
                    }
                )
        expected_snapshot = sorted(support_snapshot, key=lambda item: item["sha256"])
        if audit_payload is None or audit_metadata is None:
            raise TeamAgentEvolutionIntegrityError("event_audit Evidence is missing")
        required_purposes = set(REQUIRED_PURPOSES_BY_STATE[event.to_state])
        if candidate.cross_tenant_mode != "same_tenant":
            required_purposes.update(
                {"license", "deidentification", "revocation"}
            )
        for purpose in required_purposes:
            if len(support_claims.get(purpose, ())) != 1:
                raise TeamAgentEvolutionIntegrityError(
                    f"Event requires exactly one {purpose} Evidence"
                )
        unexpected = set(support_claims) - required_purposes - {"graph_observation"}
        if unexpected:
            raise TeamAgentEvolutionIntegrityError(
                "Unexpected event Evidence purpose: " + ",".join(sorted(unexpected))
            )
        self._verify_event_claim_bindings(
            candidate=candidate,
            event=event,
            claims={purpose: values[0] for purpose, values in support_claims.items()},
        )
        expected_audit_payload = self._event_audit_payload(
            candidate=candidate,
            event=event,
            support_snapshot=expected_snapshot,
        )
        if (
            audit_payload != expected_audit_payload
            or audit_metadata.get("supporting_evidence_sha256")
            != expected_audit_payload["supporting_evidence_sha256"]
        ):
            raise TeamAgentEvolutionIntegrityError(
                "event_audit canonical receipt drifted"
            )

    @staticmethod
    def _verify_event_claim_bindings(
        *,
        candidate: TeamAgentEvolutionCandidateRow,
        event: TeamAgentEvolutionEventRow,
        claims: dict[str, dict[str, Any]],
    ) -> None:
        runtime_sha256 = GovernedTeamAgentEvolutionWorkspace._candidate_runtime_sha256(
            candidate
        )
        agent_run = claims.get("agent_run")
        if agent_run is not None and (
            agent_run["runtime_sha256"] != runtime_sha256
            or agent_run["snapshot_sha256"] != event.agent_run_sha256
            or agent_run["agent_run_ref"] != event.agent_run_ref
            or agent_run["zero_external_writes"] is not True
        ):
            raise TeamAgentEvolutionIntegrityError(
                "AgentRun Evidence/event binding drifted"
            )
        eval_set = claims.get("eval_set")
        if eval_set is not None and (
            eval_set["eval_set_sha256"] != event.eval_set_sha256
            or eval_set["eval_set_sha256"] != candidate.eval_set_sha256
        ):
            raise TeamAgentEvolutionIntegrityError("Eval-set Evidence binding drifted")
        baseline = claims.get("baseline")
        if baseline is not None and (
            baseline["baseline_runtime_ref"] != event.baseline_runtime_ref
            or baseline["baseline_runtime_sha256"]
            != event.baseline_runtime_sha256
            or baseline["candidate_runtime_ref"] != event.candidate_runtime_ref
            or baseline["candidate_runtime_sha256"] != runtime_sha256
            or baseline["candidate_agent_run_ref"] != event.agent_run_ref
            or baseline["candidate_agent_run_sha256"] != event.agent_run_sha256
            or baseline["eval_baseline_passed"] is not True
            or baseline["negative_tests_passed"] is not True
            or baseline["scope_tests_passed"] is not True
        ):
            raise TeamAgentEvolutionIntegrityError("Baseline Evidence binding drifted")
        shadow = claims.get("shadow")
        if shadow is not None and (
            shadow["agent_run_ref"] != event.agent_run_ref
            or shadow["runtime_sha256"] != runtime_sha256
            or shadow["snapshot_sha256"] != event.agent_run_sha256
            or shadow["shadow_passed"] is not True
            or shadow["zero_external_writes"] is not True
        ):
            raise TeamAgentEvolutionIntegrityError("Shadow Evidence binding drifted")
        review = claims.get("review")
        if review is not None and review["review_verdict"] != event.review_verdict:
            raise TeamAgentEvolutionIntegrityError("Review Evidence binding drifted")
        risk = claims.get("risk_authority")
        if risk is not None and (
            risk["current"] is not True
            or (
                event.to_state == "active"
                and risk["risk_authority_sha256"]
                != event.risk_authority_sha256
            )
        ):
            raise TeamAgentEvolutionIntegrityError("Risk Evidence binding drifted")
        rollback = claims.get("rollback")
        if rollback is not None and (
            rollback["rollback_artifact_sha256"]
            != candidate.rollback_artifact_sha256
            or (
                event.to_state == "rolled_back"
                and (
                    rollback["rollback_target_ref"]
                    != event.rollback_target_candidate_ref
                    or rollback["rollback_version"]
                    != event.rollback_target_skill_version
                    or rollback["rollback_target_content_sha256"]
                    != event.rollback_target_content_sha256
                    or rollback["rollback_target_runtime_sha256"]
                    != event.rollback_target_runtime_sha256
                )
            )
        ):
            raise TeamAgentEvolutionIntegrityError("Rollback Evidence binding drifted")

    def _verify_current_cross_tenant_authority(
        self,
        session: Session,
        *,
        candidate: TeamAgentEvolutionCandidateRow,
        links: Sequence[TeamAgentEvolutionEvidenceLinkRow],
        scope: _Scope,
    ) -> None:
        if candidate.cross_tenant_mode == "same_tenant":
            return
        claims_by_purpose: dict[str, dict[str, Any]] = {}
        for purpose in ("license", "deidentification", "revocation"):
            matching = [link for link in links if link.purpose == purpose]
            if len(matching) != 1:
                raise TeamAgentEvolutionIntegrityError(
                    f"Current event requires exactly one {purpose} authority Evidence"
                )
            row = session.get(EvidenceRecordRow, matching[0].evidence_id)
            blob = session.get(EvidenceBlobRow, row.blob_sha256) if row else None
            if row is None or blob is None:
                raise TeamAgentEvolutionIntegrityError(
                    "Current cross-tenant authority Evidence is missing"
                )
            try:
                payload = json.loads(bytes(blob.content_bytes))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TeamAgentEvolutionIntegrityError(
                    "Current cross-tenant authority payload is invalid"
                ) from exc
            claims = self._validated_claims(purpose, payload.get("claims"))
            self._require_latest_cross_tenant_authority(
                session,
                row=row,
                claims=claims,
                scope=scope,
            )
            claims_by_purpose[purpose] = claims
        self._cross_tenant_gate(candidate, claims_by_purpose)

    @staticmethod
    def _verify_candidate(row: TeamAgentEvolutionCandidateRow) -> None:
        candidate = {
            "contract_id": CONTRACT_ID,
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_authority_sha256": row.scope_authority_sha256,
            "candidate_author_actor_id": row.candidate_author_actor_id,
            "human_owner_actor_id": row.human_owner_actor_id,
            "skill_id": row.skill_id,
            "skill_version": row.skill_version,
            "learning_input_type": row.learning_input_type,
            "agent_role_version_sha256": row.agent_role_version_sha256,
            "skill_contract_sha256": row.skill_contract_sha256,
            "eval_set_sha256": row.eval_set_sha256,
            "model_profile_sha256": row.model_profile_sha256,
            "tool_contract_sha256": row.tool_contract_sha256,
            "policy_version_sha256": row.policy_version_sha256,
            "rollback_artifact_sha256": row.rollback_artifact_sha256,
            "cross_tenant_mode": row.cross_tenant_mode,
            "license_sha256": row.license_sha256,
            "deidentification_sha256": row.deidentification_sha256,
            "revocation_contract_sha256": row.revocation_contract_sha256,
        }
        predecessor = (
            {
                "predecessor_candidate_ref": row.predecessor_candidate_ref,
                "predecessor_skill_version": row.predecessor_skill_version,
                "supersedes_sha256": row.supersedes_sha256,
            }
            if row.predecessor_candidate_ref is not None
            else None
        )
        content = {"candidate": candidate, "predecessor": predecessor}
        if not hmac.compare_digest(row.content_sha256, _digest(content)):
            raise TeamAgentEvolutionIntegrityError("Candidate content hash drifted")
        if row.candidate_author_actor_id == row.human_owner_actor_id:
            raise TeamAgentEvolutionIntegrityError("Candidate owner SoD drifted")

    def _projection(
        self,
        session: Session,
        row: TeamAgentEvolutionCandidateRow,
        *,
        cutoff: datetime | None = None,
        scope: _Scope,
    ) -> dict[str, Any]:
        history = self._verified_history(session, row, cutoff=cutoff)
        self._verify_current_cross_tenant_authority(
            session,
            candidate=row,
            links=history[-1][1],
            scope=scope,
        )
        events: list[dict[str, Any]] = []
        predecessor: dict[str, str] | None = None
        for event, links in history:
            source_projection = []
            graph_observations = []
            for link in links:
                if link.purpose == "event_audit":
                    evidence_snapshot_sha256 = link.evidence_sha256
                    evidence = session.get(EvidenceRecordRow, link.evidence_id)
                    blob = session.get(EvidenceBlobRow, evidence.blob_sha256)
                    audit_payload = json.loads(bytes(blob.content_bytes))
                    if predecessor is None and audit_payload.get("predecessor"):
                        predecessor = dict(audit_payload["predecessor"])
                    continue
                evidence = session.get(EvidenceRecordRow, link.evidence_id)
                blob = session.get(EvidenceBlobRow, evidence.blob_sha256)
                payload = json.loads(bytes(blob.content_bytes))
                source_projection.append(
                    {
                        "purpose": link.purpose,
                        "source": link.evidence_source,
                        "source_ref": link.evidence_source_ref,
                        "grade": link.evidence_grade,
                        "sha256": link.evidence_sha256,
                        "claims_sha256": _digest(payload["claims"]),
                    }
                )
                if link.purpose == "graph_observation":
                    graph_observations.append(dict(payload["claims"]))
            events.append(
                {
                    "event_ref": event.event_ref,
                    "ordinal": event.ordinal,
                    "from_state": event.from_state,
                    "to_state": event.to_state,
                    "actor_id": event.actor_id,
                    "actor_role": event.actor_role,
                    "risk_actor_id": event.risk_actor_id,
                    "reason_code": event.reason_code,
                    "eval_baseline_passed": event.eval_baseline_passed,
                    "negative_tests_passed": event.negative_tests_passed,
                    "scope_tests_passed": event.scope_tests_passed,
                    "shadow_passed": event.shadow_passed,
                    "external_write_observed": event.external_write_observed,
                    "cost_usd": _decimal_text(event.cost_usd),
                    "latency_ms": _decimal_text(event.latency_ms),
                    "token_count": event.token_count,
                    "risk_authority_sha256": event.risk_authority_sha256,
                    "event_sha256": event.event_sha256,
                    "evidence_snapshot_sha256": evidence_snapshot_sha256,
                    "source_evidence": sorted(
                        source_projection,
                        key=lambda item: (item["purpose"], item["sha256"]),
                    ),
                    "graph_observations": graph_observations,
                    "occurred_at": _iso(event.occurred_at),
                }
            )
        return {
            "contract_id": CONTRACT_ID,
            "candidate_ref": row.candidate_ref,
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_authority_sha256": row.scope_authority_sha256,
            "candidate_author_actor_id": row.candidate_author_actor_id,
            "human_owner_actor_id": row.human_owner_actor_id,
            "skill_id": row.skill_id,
            "skill_version": row.skill_version,
            "learning_input_type": row.learning_input_type,
            "agent_role_version_sha256": row.agent_role_version_sha256,
            "skill_contract_sha256": row.skill_contract_sha256,
            "eval_set_sha256": row.eval_set_sha256,
            "model_profile_sha256": row.model_profile_sha256,
            "tool_contract_sha256": row.tool_contract_sha256,
            "policy_version_sha256": row.policy_version_sha256,
            "rollback_artifact_sha256": row.rollback_artifact_sha256,
            "cross_tenant_mode": row.cross_tenant_mode,
            "license_sha256": row.license_sha256,
            "deidentification_sha256": row.deidentification_sha256,
            "revocation_contract_sha256": row.revocation_contract_sha256,
            "content_sha256": row.content_sha256,
            "supersedes_sha256": row.supersedes_sha256,
            "created_at": _iso(row.created_at),
            "predecessor": predecessor,
            "state": events[-1]["to_state"],
            "events": events,
            "observation_only": True,
            "runtime_activation_performed": False,
            "runtime_code_modified": False,
            "runtime_permission_modified": False,
            "formal_fact_created": False,
            "finance_entry_created": False,
            "approval_created": False,
            "permit_created": False,
            "pilot_created": False,
            "outbox_created": False,
            "graph_write_performed": False,
            "external_write_performed": False,
        }

    @staticmethod
    def _event_hash_payload(event: TeamAgentEvolutionEventRow) -> dict[str, Any]:
        return {
            "candidate_ref": event.candidate_ref,
            "tenant_ref": event.tenant_ref,
            "entity_ref": event.entity_ref,
            "store_ref": event.store_ref,
            "scope_authority_sha256": event.scope_authority_sha256,
            "ordinal": event.ordinal,
            "from_state": event.from_state,
            "to_state": event.to_state,
            "actor_id": event.actor_id,
            "actor_role": event.actor_role,
            "risk_actor_id": event.risk_actor_id,
            "reason_code": event.reason_code,
            "eval_baseline_passed": event.eval_baseline_passed,
            "negative_tests_passed": event.negative_tests_passed,
            "scope_tests_passed": event.scope_tests_passed,
            "shadow_passed": event.shadow_passed,
            "external_write_observed": event.external_write_observed,
            "zero_external_writes": event.zero_external_writes,
            "cost_usd": _decimal_text(event.cost_usd),
            "latency_ms": _decimal_text(event.latency_ms),
            "token_count": event.token_count,
            "risk_authority_sha256": event.risk_authority_sha256,
            "eval_set_id": event.eval_set_id,
            "eval_set_version": event.eval_set_version,
            "eval_set_sha256": event.eval_set_sha256,
            "baseline_runtime_ref": event.baseline_runtime_ref,
            "baseline_runtime_sha256": event.baseline_runtime_sha256,
            "candidate_runtime_ref": event.candidate_runtime_ref,
            "candidate_runtime_sha256": event.candidate_runtime_sha256,
            "agent_run_ref": event.agent_run_ref,
            "agent_run_sha256": event.agent_run_sha256,
            "eval_snapshot_sha256": event.eval_snapshot_sha256,
            "result_snapshot_sha256": event.result_snapshot_sha256,
            "review_verdict": event.review_verdict,
            "rollback_target_candidate_ref": event.rollback_target_candidate_ref,
            "rollback_target_skill_version": event.rollback_target_skill_version,
            "rollback_target_content_sha256": (
                event.rollback_target_content_sha256
            ),
            "rollback_target_runtime_sha256": (
                event.rollback_target_runtime_sha256
            ),
            "rollback_target_sha256": event.rollback_target_sha256,
            "graph_snapshot_sha256": event.graph_snapshot_sha256,
            "graph_observation_type": event.graph_observation_type,
            "graph_observation_version": event.graph_observation_version,
            "graph_effective_from": _iso(event.graph_effective_from),
            "graph_effective_until": (
                _iso(event.graph_effective_until)
                if event.graph_effective_until is not None
                else None
            ),
            "graph_observation_only": event.graph_observation_only,
            "graph_gate_eligible": event.graph_gate_eligible,
            "prev_event_sha256": event.prev_event_sha256,
            "request_sha256": event.request_sha256,
            "idempotency_sha256": event.idempotency_sha256,
            "data_as_of": _iso(event.data_as_of),
            "occurred_at": _iso(event.occurred_at),
        }

    @staticmethod
    def _event_rows(
        session: Session,
        row: TeamAgentEvolutionCandidateRow,
    ) -> list[TeamAgentEvolutionEventRow]:
        return list(
            session.scalars(
                select(TeamAgentEvolutionEventRow)
                .where(
                    TeamAgentEvolutionEventRow.candidate_ref == row.candidate_ref,
                    TeamAgentEvolutionEventRow.tenant_ref == row.tenant_ref,
                    TeamAgentEvolutionEventRow.entity_ref == row.entity_ref,
                    TeamAgentEvolutionEventRow.store_ref == row.store_ref,
                    TeamAgentEvolutionEventRow.scope_authority_sha256
                    == row.scope_authority_sha256,
                )
                .order_by(TeamAgentEvolutionEventRow.ordinal)
            )
        )

    @staticmethod
    def _candidate_scope_query(scope: _Scope):
        return select(TeamAgentEvolutionCandidateRow).where(
            TeamAgentEvolutionCandidateRow.tenant_ref == scope.tenant_ref,
            TeamAgentEvolutionCandidateRow.entity_ref == scope.entity_ref,
            TeamAgentEvolutionCandidateRow.store_ref == scope.store_ref,
            TeamAgentEvolutionCandidateRow.scope_authority_sha256
            == scope.authority_sha256,
        )

    @staticmethod
    def _candidate_idempotency_query(scope: _Scope, idempotency_sha256: str):
        return GovernedTeamAgentEvolutionWorkspace._candidate_scope_query(scope).where(
            TeamAgentEvolutionCandidateRow.idempotency_sha256
            == idempotency_sha256
        )
    @staticmethod
    def _event_idempotency_query(
        scope: _Scope,
        candidate_ref: str,
        idempotency_sha256: str,
    ):
        return select(TeamAgentEvolutionEventRow).where(
            TeamAgentEvolutionEventRow.candidate_ref == candidate_ref,
            TeamAgentEvolutionEventRow.tenant_ref == scope.tenant_ref,
            TeamAgentEvolutionEventRow.entity_ref == scope.entity_ref,
            TeamAgentEvolutionEventRow.store_ref == scope.store_ref,
            TeamAgentEvolutionEventRow.scope_authority_sha256
            == scope.authority_sha256,
            TeamAgentEvolutionEventRow.idempotency_sha256
            == idempotency_sha256,
        )

    @staticmethod
    def _same_request(existing: str, requested: str) -> None:
        if not hmac.compare_digest(existing, requested):
            raise TeamAgentEvolutionConflictError(
                "Idempotency key conflicts with immutable request content"
            )

    def _candidate_winner(
        self,
        *,
        principal: Principal,
        scope: _Scope,
        idempotency_sha256: str,
        request_sha256: str,
        cause: IntegrityError,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            scope = self._lock_and_revalidate_scope(
                session,
                principal=principal,
                scope=scope,
            )
            row = session.scalar(
                self._candidate_idempotency_query(scope, idempotency_sha256)
            )
            if row is None:
                raise cause
            self._same_request(row.request_sha256, request_sha256)
            return self._projection(session, row, scope=scope)

    def _event_winner(
        self,
        *,
        principal: Principal,
        scope: _Scope,
        candidate_ref: str,
        idempotency_sha256: str,
        request_sha256: str,
        cause: IntegrityError,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            scope = self._lock_and_revalidate_scope(
                session,
                principal=principal,
                scope=scope,
            )
            event = session.scalar(
                self._event_idempotency_query(
                    scope, candidate_ref, idempotency_sha256
                )
            )
            row = session.scalar(
                self._candidate_scope_query(scope).where(
                    TeamAgentEvolutionCandidateRow.candidate_ref == candidate_ref
                )
            )
            if event is None or row is None:
                raise cause
            self._same_request(event.request_sha256, request_sha256)
            return self._projection(session, row, scope=scope)


# Transitional internal name retained for existing Python-only callers.  The
# sole deep-module contract is GovernedTeamAgentEvolutionWorkspace.
GovernedTeamAgentEvolution = GovernedTeamAgentEvolutionWorkspace
