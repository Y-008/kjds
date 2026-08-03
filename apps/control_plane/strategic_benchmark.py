from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    and_,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade
from .security import Principal
from .sql_repository import Base

CONTRACT_ID = "kjds-strategic-benchmark-kernel-v1"
REGISTRY_SCHEMA = "kjds-strategic-benchmark-contracts-v1"
EVIDENCE_SOURCE = "strategic-benchmark-snapshot"
MAX_GROUPS = 50
MAX_OBSERVATIONS_PER_GROUP = 100
MAX_EVIDENCE_PER_OBSERVATION = 20
MAX_SNAPSHOT_EVIDENCE = MAX_GROUPS * MAX_OBSERVATIONS_PER_GROUP
DECIMAL_SCALE = Decimal("0.000000000001")
MAX_VALUE = Decimal("99999999999999999999999999.999999999999")

ELIGIBLE_SOURCE_KINDS = frozenset(
    {
        "official_first_party",
        "audited_filing",
        "licensed_primary",
        "independently_reviewed_internal",
        "terms_permitted_public_measurement",
    }
)
INELIGIBLE_SOURCE_KINDS = frozenset(
    {"marketing_claim", "model_output", "synthetic_demo"}
)
SOURCE_KINDS = ELIGIBLE_SOURCE_KINDS | INELIGIBLE_SOURCE_KINDS
SUBJECT_CLASSES = frozenset({"kjds_current", "peer", "frontier_candidate"})
GRADE_ORDER = {"UNKNOWN": 0, "D": 1, "C": 2, "B": 3, "A": 4}

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|"
    r"session[_-]?cookie|authorization\s*:\s*bearer|private[_-]?key)"
)


@dataclass(frozen=True, slots=True)
class MetricSpec:
    domain: str
    metric_id: str
    direction: str
    unit: str
    minimum_source_grade: str
    freshness_days: int
    minimum_confidence_bps: int
    minimum_sample_size: int


def _load_registry() -> tuple[dict[str, Any], str]:
    path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "project"
        / "registries"
        / "strategic_benchmark_contracts.json"
    )
    raw = path.read_bytes()
    registry = json.loads(raw)
    if registry.get("schema_version") != REGISTRY_SCHEMA:
        raise RuntimeError("Strategic benchmark registry schema mismatch")
    if registry.get("top1_semantics", {}).get("global_top1_allowed") is not False:
        raise RuntimeError("Strategic benchmark registry must prohibit global Top1")
    return registry, hashlib.sha256(raw).hexdigest()


BENCHMARK_REGISTRY, BENCHMARK_REGISTRY_SHA256 = _load_registry()
OBSERVATION_CONTRACT = BENCHMARK_REGISTRY["observation_evidence_contract"]
ELIGIBILITY_POLICY = BENCHMARK_REGISTRY["eligibility_policy"]
OBSERVATION_REQUIRED_FIELDS = frozenset(
    OBSERVATION_CONTRACT["required_payload_fields"]
)
SOURCE_CONTRACTS = {
    (item["id"], item["version"]): item
    for item in OBSERVATION_CONTRACT["source_contracts"]
}
METRIC_POLICY_OVERRIDES = ELIGIBILITY_POLICY.get("metric_overrides", {})
METRIC_SPECS = {
    (domain["id"], metric["id"]): MetricSpec(
        domain=domain["id"],
        metric_id=metric["id"],
        direction=metric["direction"],
        unit=metric["unit"],
        minimum_source_grade=METRIC_POLICY_OVERRIDES.get(
            f"{domain['id']}.{metric['id']}", {}
        ).get("minimum_source_grade", metric["minimum_source_grade"]),
        freshness_days=int(metric["freshness_days"]),
        minimum_confidence_bps=int(
            METRIC_POLICY_OVERRIDES.get(
                f"{domain['id']}.{metric['id']}", {}
            ).get(
                "minimum_confidence_bps",
                ELIGIBILITY_POLICY["minimum_confidence_bps"],
            )
        ),
        minimum_sample_size=int(
            METRIC_POLICY_OVERRIDES.get(
                f"{domain['id']}.{metric['id']}", {}
            ).get(
                "minimum_sample_size",
                ELIGIBILITY_POLICY["minimum_sample_size"],
            )
        ),
    )
    for domain in BENCHMARK_REGISTRY["domains"]
    for metric in domain["metrics"]
}


class StrategicBenchmarkConflictError(RuntimeError):
    pass


class StrategicBenchmarkSnapshotRow(Base):
    __tablename__ = "strategic_benchmark_snapshots"
    __table_args__ = (
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
            name="fk_strategic_benchmark_snapshot_exact_evidence",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "idempotency_sha256",
            name="uq_strategic_benchmark_scope_idempotency",
        ),
        UniqueConstraint(
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_strategic_benchmark_snapshot_exact_scope",
        ),
        UniqueConstraint(
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "as_of",
            "registry_sha256",
            name="uq_strategic_benchmark_snapshot_exact_context",
        ),
        CheckConstraint(
            "group_count > 0 AND observation_count > 0",
            name="ck_strategic_benchmark_snapshot_counts",
        ),
        CheckConstraint(
            "length(scope_authority_sha256) = 64 "
            "AND length(registry_sha256) = 64 "
            "AND length(evidence_sha256) = 64 "
            "AND length(request_sha256) = 64 "
            "AND length(idempotency_sha256) = 64",
            name="ck_strategic_benchmark_snapshot_hashes",
        ),
        CheckConstraint(
            "evidence_source = 'strategic-benchmark-snapshot' "
            "AND evidence_source_ref = 'strategic-benchmark-snapshot://' || snapshot_ref "
            "AND evidence_grade = 'D' AND evidence_effective_at = as_of",
            name="ck_strategic_benchmark_snapshot_evidence_contract",
        ),
        Index(
            "ix_strategic_benchmark_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "created_at",
            "snapshot_ref",
        ),
        Index("ix_strategic_benchmark_snapshot_evidence", "evidence_id"),
    )

    snapshot_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registry_schema: Mapped[str] = mapped_column(String(100), nullable=False)
    registry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    group_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_source_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(8), nullable=False)
    evidence_effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategicBenchmarkGroupRow(Base):
    __tablename__ = "strategic_benchmark_groups"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "snapshot_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "as_of",
                "registry_sha256",
            ],
            [
                "strategic_benchmark_snapshots.snapshot_ref",
                "strategic_benchmark_snapshots.tenant_ref",
                "strategic_benchmark_snapshots.entity_ref",
                "strategic_benchmark_snapshots.store_ref",
                "strategic_benchmark_snapshots.scope_authority_sha256",
                "strategic_benchmark_snapshots.as_of",
                "strategic_benchmark_snapshots.registry_sha256",
            ],
            name="fk_strategic_benchmark_group_exact_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "group_ref",
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_strategic_benchmark_group_exact_scope",
        ),
        UniqueConstraint(
            "group_ref",
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "window_start",
            "window_end",
            name="uq_strategic_benchmark_group_exact_window",
        ),
        UniqueConstraint(
            "snapshot_ref",
            "domain",
            "metric_id",
            "cohort_ref",
            "market",
            name="uq_strategic_benchmark_group_comparison_key",
        ),
        UniqueConstraint(
            "snapshot_ref", "ordinal", name="uq_strategic_benchmark_group_ordinal"
        ),
        UniqueConstraint(
            "snapshot_ref", "group_sha256", name="uq_strategic_benchmark_group_hash"
        ),
        CheckConstraint(
            "direction IN ('higher_is_better','lower_is_better')",
            name="ck_strategic_benchmark_direction",
        ),
        CheckConstraint(
            "minimum_source_grade IN ('A','B')",
            name="ck_strategic_benchmark_minimum_grade",
        ),
        CheckConstraint(
            "comparison_state IN ('comparable','partial','not_comparable',"
            "'no_data','stale','invalidated')",
            name="ck_strategic_benchmark_comparison_state",
        ),
        CheckConstraint(
            "leader_label IS NULL OR leader_label IN "
            "('metric_leader','frontier_candidate','best_feasible_for_kjds')",
            name="ck_strategic_benchmark_leader_label",
        ),
        CheckConstraint(
            "source_kind IN ('official_first_party','audited_filing',"
            "'licensed_primary','independently_reviewed_internal',"
            "'terms_permitted_public_measurement','marketing_claim',"
            "'model_output','synthetic_demo')",
            name="ck_strategic_benchmark_source_kind",
        ),
        CheckConstraint(
            "((comparison_state IN ('no_data','stale','invalidated','not_comparable') "
            "AND leader_count = 0 AND leader_label IS NULL) OR "
            "(comparison_state = 'partial' AND leader_count = 0 "
            "AND leader_label IS NULL) OR "
            "(comparison_state = 'comparable' AND "
            "((leader_label = 'metric_leader' AND leader_count = 1) OR "
            "(leader_label IN ('frontier_candidate','best_feasible_for_kjds') "
            "AND leader_count > 0))))",
            name="ck_strategic_benchmark_leader_consistency",
        ),
        CheckConstraint(
            "window_start < window_end AND window_end <= as_of",
            name="ck_strategic_benchmark_window",
        ),
        CheckConstraint(
            "observation_count > 0 AND comparable_count >= 0 "
            "AND ineligible_count >= 0 "
            "AND comparable_count + ineligible_count = observation_count "
            "AND leader_count >= 0 AND leader_count <= comparable_count",
            name="ck_strategic_benchmark_group_counts",
        ),
        CheckConstraint(
            "length(scope_authority_sha256) = 64 "
            "AND length(registry_sha256) = 64 "
            "AND length(methodology_sha256) = 64 "
            "AND length(sample_definition_sha256) = 64 "
            "AND length(source_contract_sha256) = 64 "
            "AND length(group_sha256) = 64 AND length(result_sha256) = 64",
            name="ck_strategic_benchmark_group_hashes",
        ),
        CheckConstraint(
            "length(trim(methodology_id)) > 0 "
            "AND length(trim(methodology_version)) > 0 "
            "AND length(trim(source_contract_id)) > 0 "
            "AND length(trim(source_contract_version)) > 0 "
            "AND length(trim(reason_code)) > 0",
            name="ck_strategic_benchmark_group_nonempty_contract",
        ),
        Index(
            "ix_strategic_benchmark_dimension",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "domain",
            "metric_id",
            "cohort_ref",
            "market",
            "as_of",
        ),
        Index(
            "ix_strategic_benchmark_scope_metric_snapshot",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "domain",
            "metric_id",
            "snapshot_ref",
        ),
    )

    group_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    domain: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_id: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    minimum_source_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    freshness_days: Mapped[int] = mapped_column(Integer, nullable=False)
    cohort_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    market: Mapped[str] = mapped_column(String(160), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    methodology_id: Mapped[str] = mapped_column(String(160), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(80), nullable=False)
    methodology_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_contract_version: Mapped[str] = mapped_column(String(80), nullable=False)
    source_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    comparison_state: Mapped[str] = mapped_column(String(24), nullable=False)
    leader_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    leader_observation_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    comparable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ineligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    leader_count: Mapped[int] = mapped_column(Integer, nullable=False)
    group_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategicBenchmarkObservationRow(Base):
    __tablename__ = "strategic_benchmark_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "group_ref",
                "snapshot_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "window_start",
                "window_end",
            ],
            [
                "strategic_benchmark_groups.group_ref",
                "strategic_benchmark_groups.snapshot_ref",
                "strategic_benchmark_groups.tenant_ref",
                "strategic_benchmark_groups.entity_ref",
                "strategic_benchmark_groups.store_ref",
                "strategic_benchmark_groups.scope_authority_sha256",
                "strategic_benchmark_groups.window_start",
                "strategic_benchmark_groups.window_end",
            ],
            name="fk_strategic_benchmark_observation_exact_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "group_ref", "ordinal", name="uq_strategic_benchmark_observation_ordinal"
        ),
        UniqueConstraint(
            "group_ref",
            "subject_token_sha256",
            name="uq_strategic_benchmark_observation_subject",
        ),
        UniqueConstraint(
            "observation_ref",
            "group_ref",
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_strategic_benchmark_observation_exact_scope",
        ),
        CheckConstraint(
            "subject_class IN ('kjds_current','peer','frontier_candidate')",
            name="ck_strategic_benchmark_subject_class",
        ),
        CheckConstraint(
            "value >= 0 AND uncertainty_lower >= 0 AND uncertainty_upper >= 0 "
            "AND uncertainty_lower <= value AND value <= uncertainty_upper",
            name="ck_strategic_benchmark_observation_values",
        ),
        CheckConstraint(
            "confidence_bps >= 0 AND confidence_bps <= 10000 AND sample_size > 0",
            name="ck_strategic_benchmark_observation_quality",
        ),
        CheckConstraint(
            "source_grade IN ('A','B','C','D','UNKNOWN')",
            name="ck_strategic_benchmark_observation_grade",
        ),
        CheckConstraint(
            "eligibility_state IN ('eligible','ineligible_grade','stale',"
            "'invalidated_source','ineligible_confidence','ineligible_sample')",
            name="ck_strategic_benchmark_observation_state",
        ),
        CheckConstraint(
            "window_start <= observed_at AND observed_at < window_end "
            "AND freshness_due_at >= observed_at",
            name="ck_strategic_benchmark_observation_time",
        ),
        CheckConstraint(
            "evidence_link_count > 0",
            name="ck_strategic_benchmark_observation_evidence_count",
        ),
        CheckConstraint(
            "length(scope_authority_sha256) = 64 "
            "AND length(subject_token_sha256) = 64 "
            "AND length(evidence_snapshot_sha256) = 64 "
            "AND length(observation_sha256) = 64",
            name="ck_strategic_benchmark_observation_hashes",
        ),
        Index(
            "ix_strategic_benchmark_observation_subject",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "subject_token_sha256",
            "observed_at",
        ),
    )

    observation_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_class: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    uncertainty_lower: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    uncertainty_upper: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_grade: Mapped[str] = mapped_column(String(8), nullable=False)
    citation_token_hashes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    freshness_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligibility_state: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_link_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategicBenchmarkLeaderRow(Base):
    __tablename__ = "strategic_benchmark_leaders"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "observation_ref",
                "group_ref",
                "snapshot_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
            ],
            [
                "strategic_benchmark_observations.observation_ref",
                "strategic_benchmark_observations.group_ref",
                "strategic_benchmark_observations.snapshot_ref",
                "strategic_benchmark_observations.tenant_ref",
                "strategic_benchmark_observations.entity_ref",
                "strategic_benchmark_observations.store_ref",
                "strategic_benchmark_observations.scope_authority_sha256",
            ],
            name="fk_strategic_benchmark_leader_exact_observation",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "group_ref",
            "observation_ref",
            name="uq_strategic_benchmark_leader_observation",
        ),
        UniqueConstraint(
            "group_ref",
            "ordinal",
            name="uq_strategic_benchmark_leader_ordinal",
        ),
        Index("ix_strategic_benchmark_leader_observation", "observation_ref"),
    )

    leader_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    observation_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    group_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategicBenchmarkEvidenceLinkRow(Base):
    __tablename__ = "strategic_benchmark_evidence_links"
    __table_args__ = (
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
            name="fk_strategic_benchmark_link_exact_evidence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "observation_ref",
                "group_ref",
                "snapshot_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
            ],
            [
                "strategic_benchmark_observations.observation_ref",
                "strategic_benchmark_observations.group_ref",
                "strategic_benchmark_observations.snapshot_ref",
                "strategic_benchmark_observations.tenant_ref",
                "strategic_benchmark_observations.entity_ref",
                "strategic_benchmark_observations.store_ref",
                "strategic_benchmark_observations.scope_authority_sha256",
            ],
            name="fk_strategic_benchmark_evidence_link_exact_observation",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "observation_ref",
            "evidence_id",
            name="uq_strategic_benchmark_observation_evidence_link",
        ),
        UniqueConstraint(
            "observation_ref",
            "ordinal",
            name="uq_strategic_benchmark_evidence_link_ordinal",
        ),
        UniqueConstraint(
            "snapshot_ref",
            "citation_token_sha256",
            name="uq_strategic_benchmark_citation_token",
        ),
        CheckConstraint(
            "evidence_source = 'strategic-benchmark-observation' "
            "AND evidence_source_ref = "
            "'strategic-benchmark-observation://sha256/' || evidence_sha256",
            name="ck_strategic_benchmark_link_evidence_contract",
        ),
        CheckConstraint(
            "evidence_grade IN ('A','B','C','D','UNKNOWN')",
            name="ck_strategic_benchmark_link_grade",
        ),
        CheckConstraint(
            "length(scope_authority_sha256) = 64 "
            "AND length(evidence_sha256) = 64 "
            "AND length(citation_token_sha256) = 64",
            name="ck_strategic_benchmark_link_hashes",
        ),
        Index("ix_strategic_benchmark_evidence_link_evidence", "evidence_id"),
    )

    link_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    observation_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    group_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_source_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(8), nullable=False)
    evidence_effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    citation_token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategicBenchmarkKernel:
    """Persist immutable, evidence-backed, dimension-specific comparisons."""

    CONTRACT_ID = CONTRACT_ID

    def __init__(
        self,
        *,
        engine,
        evidence,
        scope_grants,
        scoped_evidence,
        clock=None,
        sealing_key: bytes | None = None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scope_grants = scope_grants
        self.scoped_evidence = scoped_evidence
        self.clock = clock or (lambda: datetime.now(UTC))
        configured_key = os.getenv(
            "KJDS_STRATEGIC_BENCHMARK_SEALING_KEY", ""
        ).encode()
        secret = sealing_key or configured_key
        if len(secret) < 32:
            raise RuntimeError(
                "KJDS_STRATEGIC_BENCHMARK_SEALING_KEY must contain at least 32 bytes"
            )
        self._cursor_aead = AESGCM(
            hmac.new(secret, b"cursor-sealing-v2", hashlib.sha256).digest()
        )
        self._subject_token_key = hmac.new(
            secret, b"subject-token-v2", hashlib.sha256
        ).digest()
        self._citation_token_key = hmac.new(
            secret, b"citation-token-v2", hashlib.sha256
        ).digest()

    def build_snapshot(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        idempotency_key: str,
        evidence_refs: list[str],
    ) -> dict[str, Any]:
        self._require_role(principal, "operator", "admin")
        now = self._aware(self.clock(), "clock")
        cutoff = self._aware(as_of, "as_of")
        if cutoff > now:
            raise ValueError("as_of cannot be in the future")
        scope = self._scope(principal, store_ref, cutoff)
        key = self._token(idempotency_key, "idempotency_key")
        evidence_ids = self._snapshot_evidence_refs(evidence_refs)
        snapshot_ref = f"sbs_{self._hash({'scope': scope, 'key': key})[:32]}"
        groups = self._groups_from_evidence(
            evidence_ids=evidence_ids,
            principal=principal,
            scope=scope,
            as_of=cutoff,
            snapshot_ref=snapshot_ref,
        )
        idempotency_sha256 = self._hash(
            {
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "scope_authority_sha256": scope["scope_authority_sha256"],
                "idempotency_key": key,
            }
        )
        request_sha256 = self._hash(
            {
                "contract_id": CONTRACT_ID,
                "registry_sha256": BENCHMARK_REGISTRY_SHA256,
                "scope": scope,
                "as_of": cutoff,
                "evidence_refs": evidence_ids,
                "groups": groups,
            }
        )

        with Session(self.engine) as session:
            existing = self._find_by_idempotency(
                session,
                scope=scope,
                idempotency_sha256=idempotency_sha256,
            )
            if existing is not None:
                self._require_same_request(existing, request_sha256)
                return self._project(
                    session, existing, as_of=cutoff, include_groups=True, replay=True
                )

        observation_count = sum(len(group["observations"]) for group in groups)
        manifest = self._manifest(
            snapshot_ref=snapshot_ref,
            scope=scope,
            as_of=cutoff,
            groups=groups,
            request_sha256=request_sha256,
        )
        eligible_due = [
            observation["freshness_due_at"]
            for group in groups
            for observation in group["observations"]
            if observation["eligibility_state"] == "eligible"
        ]
        effective_until = min(eligible_due) if eligible_due else cutoff + timedelta(seconds=1)
        evidence_source_ref = f"strategic-benchmark-snapshot://{snapshot_ref}"

        try:
            with Session(self.engine) as session, session.begin():
                existing = self._find_by_idempotency(
                    session,
                    scope=scope,
                    idempotency_sha256=idempotency_sha256,
                )
                if existing is not None:
                    self._require_same_request(existing, request_sha256)
                    return self._project(
                        session,
                        existing,
                        as_of=cutoff,
                        include_groups=True,
                        replay=True,
                    )
                evidence = self.evidence.capture(
                    content=self._canonical(manifest),
                    filename=f"{snapshot_ref}.json",
                    content_type="application/json",
                    source=EVIDENCE_SOURCE,
                    source_ref=evidence_source_ref,
                    grade=EvidenceGrade.D,
                    effective_at=cutoff.isoformat(),
                    effective_until=effective_until.isoformat(),
                    created_by=principal.actor_id,
                    metadata={
                        "contract_id": CONTRACT_ID,
                        "registry_schema": REGISTRY_SCHEMA,
                        "registry_sha256": BENCHMARK_REGISTRY_SHA256,
                        "tenant_ref": scope["tenant_ref"],
                        "entity_ref": scope["entity_ref"],
                        "store_ref": scope["store_ref"],
                        "scope_authority_sha256": scope["scope_authority_sha256"],
                        "request_sha256": request_sha256,
                        "derived_projection": True,
                        "global_top1_claim": False,
                        "formal_fact": False,
                        "external_write_allowed": False,
                        "retention_class": "operational",
                    },
                    _session=session,
                )
                values = {
                    "snapshot_ref": snapshot_ref,
                    "tenant_ref": scope["tenant_ref"],
                    "entity_ref": scope["entity_ref"],
                    "store_ref": scope["store_ref"],
                    "scope_authority_sha256": scope["scope_authority_sha256"],
                    "registry_schema": REGISTRY_SCHEMA,
                    "registry_sha256": BENCHMARK_REGISTRY_SHA256,
                    "as_of": cutoff,
                    "group_count": len(groups),
                    "observation_count": observation_count,
                    "evidence_id": evidence.id,
                    "evidence_sha256": evidence.sha256,
                    "evidence_source": EVIDENCE_SOURCE,
                    "evidence_source_ref": evidence_source_ref,
                    "evidence_grade": EvidenceGrade.D.value,
                    "evidence_effective_at": cutoff,
                    "request_sha256": request_sha256,
                    "idempotency_sha256": idempotency_sha256,
                    "created_by": principal.actor_id,
                    "created_at": now,
                }
                if self.engine.dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert as pg_insert

                    inserted = session.scalar(
                        pg_insert(StrategicBenchmarkSnapshotRow)
                        .values(**values)
                        .on_conflict_do_nothing(
                            constraint="uq_strategic_benchmark_scope_idempotency"
                        )
                        .returning(StrategicBenchmarkSnapshotRow.snapshot_ref)
                    )
                    if inserted is None:
                        winner = self._find_by_idempotency(
                            session,
                            scope=scope,
                            idempotency_sha256=idempotency_sha256,
                        )
                        if winner is None:
                            raise RuntimeError("benchmark idempotency winner missing")
                        self._require_same_request(winner, request_sha256)
                        return self._project(
                            session,
                            winner,
                            as_of=cutoff,
                            include_groups=True,
                            replay=True,
                        )
                    snapshot = session.get(StrategicBenchmarkSnapshotRow, snapshot_ref)
                    if snapshot is None:
                        raise RuntimeError("benchmark snapshot insert not visible")
                else:
                    snapshot = StrategicBenchmarkSnapshotRow(**values)
                    session.add(snapshot)
                    session.flush()
                self._persist_groups(
                    session,
                    snapshot=snapshot,
                    scope=scope,
                    groups=groups,
                    created_at=now,
                )
                session.flush()
                return self._project(
                    session,
                    snapshot,
                    as_of=cutoff,
                    include_groups=True,
                    replay=False,
                )
        except IntegrityError:
            with Session(self.engine) as session:
                winner = self._find_by_idempotency(
                    session,
                    scope=scope,
                    idempotency_sha256=idempotency_sha256,
                )
                if winner is None:
                    raise
                self._require_same_request(winner, request_sha256)
                return self._project(
                    session, winner, as_of=cutoff, include_groups=True, replay=True
                )
    def get(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        snapshot_ref: str,
    ) -> dict[str, Any]:
        self._require_role(
            principal, "operator", "reviewer", "compliance", "monitor", "admin"
        )
        cutoff = self._aware(as_of, "as_of")
        scope = self._scope(principal, store_ref, cutoff)
        with Session(self.engine) as session:
            row = self._find(
                session,
                scope=scope,
                snapshot_ref=self._snapshot_ref(snapshot_ref),
                as_of=cutoff,
            )
            return self._project(
                session, row, as_of=cutoff, include_groups=True, replay=False
            )

    def list(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        domain: str | None = None,
        metric_id: str | None = None,
        comparison_state: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._require_role(
            principal, "operator", "reviewer", "compliance", "monitor", "admin"
        )
        cutoff = self._aware(as_of, "as_of")
        scope = self._scope(principal, store_ref, cutoff)
        if isinstance(limit, bool) or not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        filters = {
            "domain": self._token(domain, "domain") if domain is not None else None,
            "metric_id": (
                self._token(metric_id, "metric_id") if metric_id is not None else None
            ),
            "comparison_state": comparison_state,
        }
        if comparison_state is not None and comparison_state not in {
            "comparable",
            "partial",
            "not_comparable",
            "no_data",
            "stale",
            "invalidated",
        }:
            raise ValueError("comparison_state is invalid")
        cursor_position = (
            self._decode_cursor(
                cursor,
                scope=scope,
                as_of=cutoff,
                filters=filters,
            )
            if cursor
            else None
        )
        with Session(self.engine) as session:
            query = select(StrategicBenchmarkSnapshotRow).where(
                StrategicBenchmarkSnapshotRow.tenant_ref == scope["tenant_ref"],
                StrategicBenchmarkSnapshotRow.entity_ref == scope["entity_ref"],
                StrategicBenchmarkSnapshotRow.store_ref == scope["store_ref"],
                StrategicBenchmarkSnapshotRow.scope_authority_sha256
                == scope["scope_authority_sha256"],
                StrategicBenchmarkSnapshotRow.as_of <= cutoff,
            )
            if cursor_position is not None:
                last_created, last_ref = cursor_position
                query = query.where(
                    or_(
                        StrategicBenchmarkSnapshotRow.created_at > last_created,
                        and_(
                            StrategicBenchmarkSnapshotRow.created_at == last_created,
                            StrategicBenchmarkSnapshotRow.snapshot_ref > last_ref,
                        ),
                    )
                )
            if any(value is not None for value in filters.values()):
                group_filter = select(StrategicBenchmarkGroupRow.snapshot_ref).where(
                    StrategicBenchmarkGroupRow.tenant_ref == scope["tenant_ref"],
                    StrategicBenchmarkGroupRow.entity_ref == scope["entity_ref"],
                    StrategicBenchmarkGroupRow.store_ref == scope["store_ref"],
                    StrategicBenchmarkGroupRow.scope_authority_sha256
                    == scope["scope_authority_sha256"],
                )
                if filters["domain"]:
                    group_filter = group_filter.where(
                        StrategicBenchmarkGroupRow.domain == filters["domain"]
                    )
                if filters["metric_id"]:
                    group_filter = group_filter.where(
                        StrategicBenchmarkGroupRow.metric_id == filters["metric_id"]
                    )
                if filters["comparison_state"]:
                    group_filter = group_filter.where(
                        StrategicBenchmarkGroupRow.comparison_state
                        == filters["comparison_state"]
                    )
                query = query.where(
                    StrategicBenchmarkSnapshotRow.snapshot_ref.in_(group_filter)
                )
            rows = list(
                session.scalars(
                    query.order_by(
                        StrategicBenchmarkSnapshotRow.created_at,
                        StrategicBenchmarkSnapshotRow.snapshot_ref,
                    ).limit(int(limit) + 1)
                )
            )
            has_more = len(rows) > int(limit)
            rows = rows[: int(limit)]
            next_cursor = None
            if rows and has_more:
                next_cursor = self._encode_cursor(
                    scope=scope,
                    as_of=cutoff,
                    filters=filters,
                    last_created=self._database_time(rows[-1].created_at),
                    last_ref=rows[-1].snapshot_ref,
                )
            return {
                "contract_id": CONTRACT_ID,
                "items": [
                    self._project(
                        session,
                        row,
                        as_of=cutoff,
                        include_groups=False,
                        replay=False,
                    )["snapshot"]
                    for row in rows
                ],
                "next_cursor": next_cursor,
            }
    def compare(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        snapshot_ref: str,
        baseline_snapshot_ref: str,
    ) -> dict[str, Any]:
        self._require_role(
            principal, "operator", "reviewer", "compliance", "monitor", "admin"
        )
        cutoff = self._aware(as_of, "as_of")
        scope = self._scope(principal, store_ref, cutoff)
        with Session(self.engine) as session:
            current = self._find(
                session,
                scope=scope,
                snapshot_ref=self._snapshot_ref(snapshot_ref),
                as_of=cutoff,
            )
            baseline = self._find(
                session,
                scope=scope,
                snapshot_ref=self._snapshot_ref(baseline_snapshot_ref),
                as_of=cutoff,
            )
            if current.snapshot_ref == baseline.snapshot_ref:
                raise ValueError("baseline_snapshot_ref must differ from snapshot_ref")
            current_groups = self._groups(
                session,
                current.snapshot_ref,
                authority_sha256=scope["scope_authority_sha256"],
            )
            baseline_groups = self._groups(
                session,
                baseline.snapshot_ref,
                authority_sha256=scope["scope_authority_sha256"],
            )
            self._group_index(baseline_groups)
            self._group_index(current_groups)
            baseline_index = self._group_identity_index(baseline_groups)
            self._group_identity_index(current_groups)
            comparisons = []
            for group in current_groups:
                prior = baseline_index.get(self._comparison_identity(group))
                comparisons.append(
                    self._compare_group(
                        session,
                        current=group,
                        baseline=prior,
                        as_of=cutoff,
                    )
                )
            return {
                "contract_id": CONTRACT_ID,
                "snapshot_ref": current.snapshot_ref,
                "baseline_snapshot_ref": baseline.snapshot_ref,
                "as_of": cutoff.isoformat(),
                "comparisons": comparisons,
                "global_top1_claim": False,
                "formal_fact_created": False,
                "finance_entry_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            }

    def _groups_from_evidence(
        self,
        *,
        evidence_ids: list[str],
        principal: Principal,
        scope: dict[str, str],
        as_of: datetime,
        snapshot_ref: str,
    ) -> list[dict[str, Any]]:
        projected = self.scoped_evidence.project_targets(
            evidence_ids=evidence_ids,
            principal=principal,
            entity_scope={"status": "ready", "entity_ref": scope["entity_ref"]},
            store_ref=scope["store_ref"],
            as_of=as_of,
        )
        if projected.get("status") != "ready":
            raise ValueError("benchmark evidence is not current exact-scope ready")
        projected_by_id = {
            str(item.get("evidence_id")): item
            for item in projected.get("records", [])
            if str(item.get("evidence_id")) in evidence_ids
        }
        if set(projected_by_id) != set(evidence_ids):
            raise ValueError("benchmark evidence target projection is incomplete")

        payload_keys = set(OBSERVATION_REQUIRED_FIELDS)
        grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
        records: dict[str, dict[str, Any]] = {}
        for evidence_id in evidence_ids:
            record = self.evidence.get_metadata(evidence_id)
            verification = self.evidence.verify(evidence_id)
            if not verification.valid:
                raise ValueError("benchmark evidence integrity verification failed")
            if record.source != OBSERVATION_CONTRACT["evidence_source"]:
                raise ValueError("benchmark evidence source is not registered")
            if record.content_type != OBSERVATION_CONTRACT["content_type"]:
                raise ValueError("benchmark evidence content type is invalid")
            expected_source_ref = (
                OBSERVATION_CONTRACT["content_addressed_source_ref_prefix"]
                + record.sha256
            )
            if record.source_ref != expected_source_ref:
                raise ValueError("benchmark evidence source_ref is not content addressed")
            projection = projected_by_id[evidence_id]
            projection_grade = str(projection.get("grade", "UNKNOWN"))
            record_grade = getattr(record.grade, "value", str(record.grade))
            if (
                projection.get("sha256") != record.sha256
                or projection_grade != record_grade
            ):
                raise ValueError("benchmark evidence projection binding drift")
            metadata = record.metadata
            expected_metadata = {
                "benchmark_schema_id": OBSERVATION_CONTRACT["schema_id"],
                "benchmark_schema_version": OBSERVATION_CONTRACT["schema_version"],
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "scope_authority_sha256": scope["scope_authority_sha256"],
            }
            if any(metadata.get(key) != value for key, value in expected_metadata.items()):
                raise ValueError("benchmark evidence metadata exact-scope binding drift")
            record_time = self._persisted_timestamp(
                record.recorded_at, "evidence.recorded_at"
            )
            if record_time > as_of:
                raise ValueError("benchmark evidence recorded_at is after as_of")
            record_effective_at = self._persisted_timestamp(
                record.effective_at, "evidence.effective_at"
            )
            if record_effective_at > as_of:
                raise ValueError("benchmark evidence effective_at is after as_of")
            if record.effective_until is not None and self._persisted_timestamp(
                record.effective_until, "evidence.effective_until"
            ) < as_of:
                raise ValueError("benchmark evidence is stale at as_of")
            content, content_record = self.evidence.content(evidence_id)
            if content_record.sha256 != record.sha256:
                raise ValueError("benchmark evidence content binding drift")
            try:
                payload = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("benchmark evidence payload must be canonical JSON") from exc
            self._exact_keys(payload, payload_keys, "benchmark evidence payload")
            if (
                payload["schema_id"] != OBSERVATION_CONTRACT["schema_id"]
                or payload["schema_version"] != OBSERVATION_CONTRACT["schema_version"]
            ):
                raise ValueError("benchmark evidence payload schema is not registered")
            expected_payload_scope = {
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "scope_authority_sha256": scope["scope_authority_sha256"],
            }
            if any(
                payload.get(field) != expected
                for field, expected in expected_payload_scope.items()
            ):
                raise ValueError("benchmark evidence payload exact-scope binding drift")
            source_contract_key = (
                self._token(payload["source_contract_id"], "source_contract_id"),
                self._token(
                    payload["source_contract_version"],
                    "source_contract_version",
                ),
            )
            source_contract = SOURCE_CONTRACTS.get(source_contract_key)
            if source_contract is None:
                raise ValueError("benchmark source contract is not registered")
            if (
                metadata.get("source_contract_id") != source_contract_key[0]
                or metadata.get("source_contract_version") != source_contract_key[1]
            ):
                raise ValueError("benchmark source contract metadata drift")
            subject_class = self._choice(
                payload["subject_class"], "subject_class", SUBJECT_CLASSES
            )
            if subject_class not in source_contract["subject_classes"]:
                raise ValueError("benchmark subject class is not admitted by source contract")
            if (
                payload["methodology_id"]
                != ELIGIBILITY_POLICY["methodology_id"]
                or payload["methodology_version"]
                != ELIGIBILITY_POLICY["methodology_version"]
            ):
                raise ValueError("benchmark methodology is not registered")
            if not all(
                isinstance(payload[field], str)
                for field in ("value", "uncertainty_lower", "uncertainty_upper")
            ):
                raise ValueError("benchmark numeric evidence fields must be decimal strings")
            payload_recorded_at = self._timestamp(
                payload["recorded_at"], "payload.recorded_at"
            )
            if payload_recorded_at > as_of or payload_recorded_at > record_time:
                raise ValueError("benchmark payload recorded_at violates historical cutoff")
            window_start = self._timestamp(payload["window_start"], "window_start")
            window_end = self._timestamp(payload["window_end"], "window_end")
            observed_at = self._timestamp(payload["observed_at"], "observed_at")
            key = (
                self._token(payload["domain"], "domain"),
                self._token(payload["metric_id"], "metric_id"),
                self._token(payload["cohort_ref"], "cohort_ref"),
                self._token(payload["market"], "market"),
                window_start,
                window_end,
                ELIGIBILITY_POLICY["methodology_id"],
                ELIGIBILITY_POLICY["methodology_version"],
                source_contract_key[0],
                source_contract_key[1],
                source_contract["source_kind"],
            )
            entry = grouped.setdefault(
                key,
                {
                    "domain": key[0],
                    "metric_id": key[1],
                    "cohort_ref": key[2],
                    "market": key[3],
                    "window_start": window_start,
                    "window_end": window_end,
                    "methodology_id": key[6],
                    "methodology_version": key[7],
                    "sample_definition": (
                        "Frozen exact-scope structured Evidence cohort under "
                        + ELIGIBILITY_POLICY["contract_id"]
                    ),
                    "source_contract_id": key[8],
                    "source_contract_version": key[9],
                    "source_kind": key[10],
                    "observations": [],
                },
            )
            entry["observations"].append(
                {
                    "subject_ref": payload["subject_ref"],
                    "subject_class": subject_class,
                    "value": payload["value"],
                    "uncertainty_lower": payload["uncertainty_lower"],
                    "uncertainty_upper": payload["uncertainty_upper"],
                    "confidence_bps": payload["confidence_bps"],
                    "sample_size": payload["sample_size"],
                    "observed_at": observed_at,
                    "evidence_refs": [evidence_id],
                }
            )
            records[evidence_id] = {
                "id": evidence_id,
                "sha256": record.sha256,
                "source": record.source,
                "source_ref": record.source_ref,
                "grade": record_grade,
                "effective_at": self._persisted_timestamp(
                    record.effective_at, "evidence.effective_at"
                ),
            }

        normalized = self._normalize_groups(
            list(grouped.values()),
            principal=principal,
            scope=scope,
            as_of=as_of,
            snapshot_ref=snapshot_ref,
        )
        for group in normalized:
            for observation in group["observations"]:
                observation["evidence_records"] = [
                    records[evidence_id]
                    for evidence_id in observation["evidence_refs"]
                ]
        return normalized

    def _normalize_groups(
        self,
        groups: Any,
        *,
        principal: Principal,
        scope: dict[str, str],
        as_of: datetime,
        snapshot_ref: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_GROUPS:
            raise ValueError(f"groups must contain 1 to {MAX_GROUPS} items")
        normalized = [
            self._normalize_group(
                raw,
                principal=principal,
                scope=scope,
                as_of=as_of,
                snapshot_ref=snapshot_ref,
            )
            for raw in groups
        ]
        normalized.sort(
            key=lambda item: (
                item["domain"],
                item["metric_id"],
                item["cohort_ref"],
                item["market"],
                item["window_start"],
                item["window_end"],
            )
        )
        hashes = [group["group_sha256"] for group in normalized]
        if len(hashes) != len(set(hashes)):
            raise ValueError("duplicate benchmark groups are not allowed")
        identities = [
            (
                group["domain"],
                group["metric_id"],
                group["cohort_ref"],
                group["market"],
            )
            for group in normalized
        ]
        if len(identities) != len(set(identities)):
            raise StrategicBenchmarkConflictError(
                "duplicate strategic benchmark comparison identity"
            )
        return normalized

    def _normalize_group(
        self,
        raw: Any,
        *,
        principal: Principal,
        scope: dict[str, str],
        as_of: datetime,
        snapshot_ref: str,
    ) -> dict[str, Any]:
        expected = {
            "domain",
            "metric_id",
            "cohort_ref",
            "market",
            "window_start",
            "window_end",
            "methodology_id",
            "methodology_version",
            "sample_definition",
            "source_contract_id",
            "source_contract_version",
            "source_kind",
            "observations",
        }
        self._exact_keys(raw, expected, "group")
        domain = self._token(raw["domain"], "domain")
        metric_id = self._token(raw["metric_id"], "metric_id")
        spec = METRIC_SPECS.get((domain, metric_id))
        if spec is None:
            raise ValueError("domain and metric_id are not registered")
        window_start = self._aware(raw["window_start"], "window_start")
        window_end = self._aware(raw["window_end"], "window_end")
        if window_start >= window_end or window_end > as_of:
            raise ValueError("window must be ordered and end no later than as_of")
        sample_definition = self._safe_text(
            raw["sample_definition"], "sample_definition", 500
        )
        source_kind = self._choice(raw["source_kind"], "source_kind", SOURCE_KINDS)
        dimensions = {
            "domain": domain,
            "metric_id": metric_id,
            "direction": spec.direction,
            "unit": spec.unit,
            "minimum_source_grade": spec.minimum_source_grade,
            "freshness_days": spec.freshness_days,
            "cohort_ref": self._token(raw["cohort_ref"], "cohort_ref"),
            "market": self._token(raw["market"], "market"),
            "window_start": window_start,
            "window_end": window_end,
            "as_of": as_of,
            "methodology_id": self._token(
                raw["methodology_id"], "methodology_id"
            ),
            "methodology_version": self._token(
                raw["methodology_version"], "methodology_version"
            ),
            "sample_definition_sha256": self._text_hash(sample_definition),
            "source_contract_id": self._token(
                raw["source_contract_id"], "source_contract_id"
            ),
            "source_contract_version": self._token(
                raw["source_contract_version"], "source_contract_version"
            ),
            "source_kind": source_kind,
        }
        if (
            dimensions["methodology_id"] != ELIGIBILITY_POLICY["methodology_id"]
            or dimensions["methodology_version"]
            != ELIGIBILITY_POLICY["methodology_version"]
        ):
            raise ValueError("benchmark methodology is not registered")
        dimensions["methodology_sha256"] = self._hash(
            {
                "eligibility_policy": ELIGIBILITY_POLICY,
                "sample_definition_sha256": dimensions[
                    "sample_definition_sha256"
                ],
            }
        )
        source_contract = SOURCE_CONTRACTS.get(
            (
                dimensions["source_contract_id"],
                dimensions["source_contract_version"],
            )
        )
        if source_contract is None or source_contract["source_kind"] != source_kind:
            raise ValueError("benchmark source contract is not registered")
        dimensions["source_contract_sha256"] = self._hash(source_contract)
        group_sha256 = self._hash(dimensions)
        observations = self._normalize_observations(
            raw["observations"],
            spec=spec,
            dimensions=dimensions,
            principal=principal,
            scope=scope,
            as_of=as_of,
            snapshot_ref=snapshot_ref,
        )
        result = self._leader_result(observations, spec=spec, source_kind=source_kind)
        return {
            **dimensions,
            "group_sha256": group_sha256,
            "observations": observations,
            **result,
        }

    def _normalize_observations(
        self,
        raw: Any,
        *,
        spec: MetricSpec,
        dimensions: dict[str, Any],
        principal: Principal,
        scope: dict[str, str],
        as_of: datetime,
        snapshot_ref: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_OBSERVATIONS_PER_GROUP:
            raise ValueError(
                f"observations must contain 1 to {MAX_OBSERVATIONS_PER_GROUP} items"
            )
        normalized = [
            self._normalize_observation(
                item,
                spec=spec,
                dimensions=dimensions,
                principal=principal,
                scope=scope,
                as_of=as_of,
                snapshot_ref=snapshot_ref,
            )
            for item in raw
        ]
        normalized.sort(key=lambda item: item["subject_token_sha256"])
        subjects = [item["subject_token_sha256"] for item in normalized]
        if len(subjects) != len(set(subjects)):
            raise ValueError("subject_ref must be unique within a benchmark group")
        return normalized

    def _normalize_observation(
        self,
        raw: Any,
        *,
        spec: MetricSpec,
        dimensions: dict[str, Any],
        principal: Principal,
        scope: dict[str, str],
        as_of: datetime,
        snapshot_ref: str,
    ) -> dict[str, Any]:
        expected = {
            "subject_ref",
            "subject_class",
            "value",
            "uncertainty_lower",
            "uncertainty_upper",
            "confidence_bps",
            "sample_size",
            "observed_at",
            "evidence_refs",
        }
        self._exact_keys(raw, expected, "observation")
        value = self._decimal(raw["value"], "value")
        lower = self._decimal(raw["uncertainty_lower"], "uncertainty_lower")
        upper = self._decimal(raw["uncertainty_upper"], "uncertainty_upper")
        if not lower <= value <= upper:
            raise ValueError("uncertainty_lower <= value <= uncertainty_upper is required")
        if spec.unit in {"ratio", "cohort_ratio"} and upper > 1:
            raise ValueError("ratio observations must be between 0 and 1")
        if spec.unit in {"count", "accounts"} and value != value.to_integral_value():
            raise ValueError("count point estimates must be integral")
        observed_at = self._aware(raw["observed_at"], "observed_at")
        if not dimensions["window_start"] <= observed_at < dimensions["window_end"]:
            raise ValueError("observed_at must be inside the benchmark window")
        evidence_ids = self._evidence_refs(raw["evidence_refs"])
        projected = self.scoped_evidence.project_targets(
            evidence_ids=evidence_ids,
            principal=principal,
            entity_scope={"status": "ready", "entity_ref": scope["entity_ref"]},
            store_ref=scope["store_ref"],
            as_of=as_of,
        )
        if projected.get("status") != "ready":
            raise ValueError("evidence_refs are not current and exact-scope ready")
        projected_by_id = {
            str(item.get("evidence_id")): item
            for item in projected.get("records", [])
            if str(item.get("evidence_id")) in evidence_ids
        }
        if set(projected_by_id) != set(evidence_ids):
            raise ValueError("evidence_refs target projection is incomplete")
        grades = [str(projected_by_id[item].get("grade", "UNKNOWN")) for item in evidence_ids]
        if any(grade not in GRADE_ORDER for grade in grades):
            raise ValueError("evidence grade is invalid")
        source_grade = min(grades, key=lambda grade: GRADE_ORDER[grade])
        confidence_bps = self._integer(
            raw["confidence_bps"], "confidence_bps", minimum=0, maximum=10000
        )
        sample_size = self._integer(
            raw["sample_size"], "sample_size", minimum=1, maximum=2_147_483_647
        )
        freshness_due_at = observed_at + timedelta(days=spec.freshness_days)
        if dimensions["source_kind"] in INELIGIBLE_SOURCE_KINDS:
            eligibility = "invalidated_source"
        elif freshness_due_at < as_of:
            eligibility = "stale"
        elif GRADE_ORDER[source_grade] < GRADE_ORDER[spec.minimum_source_grade]:
            eligibility = "ineligible_grade"
        elif confidence_bps < spec.minimum_confidence_bps:
            eligibility = "ineligible_confidence"
        elif sample_size < spec.minimum_sample_size:
            eligibility = "ineligible_sample"
        else:
            eligibility = "eligible"
        subject_ref = self._token(raw["subject_ref"], "subject_ref")
        subject_binding = self._canonical(
            {
                "contract_id": CONTRACT_ID,
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "scope_authority_sha256": scope["scope_authority_sha256"],
                "subject_ref": subject_ref,
            }
        )
        evidence_records = self._exact_evidence_records(
            evidence_ids=evidence_ids,
            projected_by_id=projected_by_id,
        )
        normalized = {
            "subject_token_sha256": hmac.new(
                self._subject_token_key, subject_binding, hashlib.sha256
            ).hexdigest(),
            "subject_class": self._choice(
                raw["subject_class"], "subject_class", SUBJECT_CLASSES
            ),
            "value": value,
            "uncertainty_lower": lower,
            "uncertainty_upper": upper,
            "confidence_bps": confidence_bps,
            "sample_size": sample_size,
            "observed_at": observed_at,
            "freshness_due_at": freshness_due_at,
            "source_grade": source_grade,
            "evidence_refs": sorted(evidence_ids),
            "evidence_records": evidence_records,
            "evidence_snapshot_sha256": self._hash(
                [
                    {
                        "evidence_id": evidence_id,
                        "sha256": projected_by_id[evidence_id]["sha256"],
                        "grade": projected_by_id[evidence_id]["grade"],
                    }
                    for evidence_id in sorted(evidence_ids)
                ]
            ),
            "eligibility_state": eligibility,
        }
        normalized["observation_sha256"] = self._hash(normalized)
        return normalized

    def _exact_evidence_records(
        self,
        *,
        evidence_ids: list[str],
        projected_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for evidence_id in sorted(evidence_ids):
            record = self.evidence.get_metadata(evidence_id)
            verification = self.evidence.verify(evidence_id)
            if not verification.valid:
                raise ValueError("benchmark evidence integrity verification failed")
            grade = getattr(record.grade, "value", str(record.grade))
            projected = projected_by_id[evidence_id]
            if projected.get("sha256") != record.sha256 or str(
                projected.get("grade", "UNKNOWN")
            ) != grade:
                raise ValueError("benchmark evidence projection binding drift")
            records.append(
                {
                    "id": evidence_id,
                    "sha256": record.sha256,
                    "source": record.source,
                    "source_ref": record.source_ref,
                    "grade": grade,
                    "effective_at": self._persisted_timestamp(
                        record.effective_at,
                        "evidence.effective_at",
                    ),
                }
            )
        return records

    def _leader_result(
        self,
        observations: list[dict[str, Any]],
        *,
        spec: MetricSpec,
        source_kind: str,
    ) -> dict[str, Any]:
        eligible = [
            observation
            for observation in observations
            if observation["eligibility_state"] == "eligible"
        ]
        if source_kind in INELIGIBLE_SOURCE_KINDS:
            state, label, refs, reason = "invalidated", None, [], "source_kind_invalidated"
        elif not eligible:
            states = {item["eligibility_state"] for item in observations}
            state = "stale" if states == {"stale"} else "no_data"
            label, refs = None, []
            reason = "all_observations_stale" if state == "stale" else "no_eligible_observations"
        elif len(eligible) == 1:
            state, label, refs = "partial", None, []
            reason = "insufficient_comparable_cohort"
        else:
            state = (
                "comparable"
                if len(eligible) == len(observations)
                else "partial"
            )
            winner = (
                self._separated_winner(eligible, spec.direction)
                if state == "comparable"
                else None
            )
            if state != "comparable":
                label, refs = None, []
                reason = "incomplete_eligible_cohort"
            elif winner is not None:
                label = "metric_leader"
                refs = [winner["observation_sha256"]]
                reason = "conservative_interval_separation"
            else:
                label = "frontier_candidate"
                refs = [
                    item["observation_sha256"]
                    for item in self._frontier(eligible, spec.direction)
                ]
                reason = "uncertainty_intervals_overlap"
        result = {
            "comparison_state": state,
            "leader_label": label,
            "leader_observation_hashes": refs,
            "reason_code": reason,
            "observation_count": len(observations),
            "comparable_count": len(eligible),
            "ineligible_count": len(observations) - len(eligible),
        }
        result["result_sha256"] = self._hash(result)
        return result

    @staticmethod
    def _separated_winner(
        observations: list[dict[str, Any]], direction: str
    ) -> dict[str, Any] | None:
        winners = []
        for candidate in observations:
            others = [item for item in observations if item is not candidate]
            if direction == "higher_is_better":
                separated = candidate["uncertainty_lower"] > max(
                    item["uncertainty_upper"] for item in others
                )
            else:
                separated = candidate["uncertainty_upper"] < min(
                    item["uncertainty_lower"] for item in others
                )
            if separated:
                winners.append(candidate)
        return winners[0] if len(winners) == 1 else None

    @staticmethod
    def _frontier(
        observations: list[dict[str, Any]], direction: str
    ) -> list[dict[str, Any]]:
        if direction == "higher_is_better":
            best_floor = max(item["uncertainty_lower"] for item in observations)
            return [
                item for item in observations if item["uncertainty_upper"] >= best_floor
            ]
        best_ceiling = min(item["uncertainty_upper"] for item in observations)
        return [
            item for item in observations if item["uncertainty_lower"] <= best_ceiling
        ]

    def _persist_groups(
        self,
        session: Session,
        *,
        snapshot: StrategicBenchmarkSnapshotRow,
        scope: dict[str, str],
        groups: list[dict[str, Any]],
        created_at: datetime,
    ) -> None:
        for group_ordinal, group in enumerate(groups, start=1):
            group_ref = new_id("sbg")
            hash_to_ref: dict[str, str] = {}
            observations: list[StrategicBenchmarkObservationRow] = []
            evidence_links: list[StrategicBenchmarkEvidenceLinkRow] = []
            for observation_ordinal, observation in enumerate(
                group["observations"], start=1
            ):
                observation_ref = new_id("sbo")
                hash_to_ref[observation["observation_sha256"]] = observation_ref
                citation_hashes: list[str] = []
                for evidence_ordinal, record in enumerate(
                    observation["evidence_records"], start=1
                ):
                    citation_token = self._citation_token(
                        snapshot_ref=snapshot.snapshot_ref,
                        scope=scope,
                        observation_ref=observation_ref,
                        evidence_id=record["id"],
                        evidence_sha256=record["sha256"],
                    )
                    citation_hash = self._text_hash(citation_token)
                    citation_hashes.append(citation_hash)
                    evidence_links.append(
                        StrategicBenchmarkEvidenceLinkRow(
                            link_ref=new_id("sbel"),
                            observation_ref=observation_ref,
                            group_ref=group_ref,
                            snapshot_ref=snapshot.snapshot_ref,
                            tenant_ref=scope["tenant_ref"],
                            entity_ref=scope["entity_ref"],
                            store_ref=scope["store_ref"],
                            scope_authority_sha256=scope[
                                "scope_authority_sha256"
                            ],
                            ordinal=evidence_ordinal,
                            evidence_id=record["id"],
                            evidence_sha256=record["sha256"],
                            evidence_source=record["source"],
                            evidence_source_ref=record["source_ref"],
                            evidence_grade=record["grade"],
                            evidence_effective_at=record["effective_at"],
                            citation_token_sha256=citation_hash,
                            created_at=created_at,
                        )
                    )
                observations.append(
                    StrategicBenchmarkObservationRow(
                        observation_ref=observation_ref,
                        group_ref=group_ref,
                        snapshot_ref=snapshot.snapshot_ref,
                        tenant_ref=scope["tenant_ref"],
                        entity_ref=scope["entity_ref"],
                        store_ref=scope["store_ref"],
                        scope_authority_sha256=scope["scope_authority_sha256"],
                        ordinal=observation_ordinal,
                        subject_token_sha256=observation["subject_token_sha256"],
                        subject_class=observation["subject_class"],
                        value=observation["value"],
                        uncertainty_lower=observation["uncertainty_lower"],
                        uncertainty_upper=observation["uncertainty_upper"],
                        confidence_bps=observation["confidence_bps"],
                        sample_size=observation["sample_size"],
                        source_grade=observation["source_grade"],
                        citation_token_hashes_json=citation_hashes,
                        evidence_snapshot_sha256=observation[
                            "evidence_snapshot_sha256"
                        ],
                        observed_at=observation["observed_at"],
                        window_start=group["window_start"],
                        window_end=group["window_end"],
                        freshness_due_at=observation["freshness_due_at"],
                        eligibility_state=observation["eligibility_state"],
                        evidence_link_count=len(observation["evidence_records"]),
                        observation_sha256=observation["observation_sha256"],
                        created_at=created_at,
                    )
                )
            leader_refs = [
                hash_to_ref[item]
                for item in group["leader_observation_hashes"]
                if item in hash_to_ref
            ]
            session.add(
                StrategicBenchmarkGroupRow(
                    group_ref=group_ref,
                    snapshot_ref=snapshot.snapshot_ref,
                    tenant_ref=scope["tenant_ref"],
                    entity_ref=scope["entity_ref"],
                    store_ref=scope["store_ref"],
                    scope_authority_sha256=scope["scope_authority_sha256"],
                    registry_sha256=BENCHMARK_REGISTRY_SHA256,
                    ordinal=group_ordinal,
                    domain=group["domain"],
                    metric_id=group["metric_id"],
                    direction=group["direction"],
                    unit=group["unit"],
                    minimum_source_grade=group["minimum_source_grade"],
                    freshness_days=group["freshness_days"],
                    cohort_ref=group["cohort_ref"],
                    market=group["market"],
                    window_start=group["window_start"],
                    window_end=group["window_end"],
                    as_of=group["as_of"],
                    methodology_id=group["methodology_id"],
                    methodology_version=group["methodology_version"],
                    methodology_sha256=group["methodology_sha256"],
                    sample_definition_sha256=group[
                        "sample_definition_sha256"
                    ],
                    source_contract_id=group["source_contract_id"],
                    source_contract_version=group["source_contract_version"],
                    source_contract_sha256=group["source_contract_sha256"],
                    source_kind=group["source_kind"],
                    comparison_state=group["comparison_state"],
                    leader_label=group["leader_label"],
                    leader_observation_refs_json=leader_refs,
                    reason_code=group["reason_code"],
                    observation_count=group["observation_count"],
                    comparable_count=group["comparable_count"],
                    ineligible_count=group["ineligible_count"],
                    leader_count=len(leader_refs),
                    group_sha256=group["group_sha256"],
                    result_sha256=group["result_sha256"],
                    created_at=created_at,
                )
            )
            session.add_all(observations)
            session.add_all(evidence_links)
            session.add_all(
                StrategicBenchmarkLeaderRow(
                    leader_ref=new_id("sbl"),
                    observation_ref=observation_ref,
                    group_ref=group_ref,
                    snapshot_ref=snapshot.snapshot_ref,
                    tenant_ref=scope["tenant_ref"],
                    entity_ref=scope["entity_ref"],
                    store_ref=scope["store_ref"],
                    scope_authority_sha256=scope["scope_authority_sha256"],
                    ordinal=ordinal,
                    created_at=created_at,
                )
                for ordinal, observation_ref in enumerate(leader_refs, start=1)
            )
    def _project(
        self,
        session: Session,
        row: StrategicBenchmarkSnapshotRow,
        *,
        as_of: datetime,
        include_groups: bool,
        replay: bool,
    ) -> dict[str, Any]:
        scope = {
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_authority_sha256": row.scope_authority_sha256,
        }
        snapshot_citation = self._citation_token(
            snapshot_ref=row.snapshot_ref,
            scope=scope,
            observation_ref=row.snapshot_ref,
            evidence_id=row.evidence_id,
            evidence_sha256=row.evidence_sha256,
        )
        snapshot = {
            "snapshot_ref": row.snapshot_ref,
            "store_ref": row.store_ref,
            "registry_schema": row.registry_schema,
            "registry_sha256": row.registry_sha256,
            "as_of": self._database_time(row.as_of).isoformat(),
            "group_count": row.group_count,
            "observation_count": row.observation_count,
            "snapshot_citation": {
                "token": snapshot_citation,
                "sha256": row.evidence_sha256,
                "grade": row.evidence_grade,
            },
            "request_sha256": row.request_sha256,
            "idempotent_replay": replay,
            "global_top1_claim": False,
            "formal_fact_created": False,
            "finance_entry_created": False,
            "approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
            "created_at": self._database_time(row.created_at).isoformat(),
        }
        return {
            "contract_id": CONTRACT_ID,
            "snapshot": snapshot,
            "groups": (
                [
                    self._project_group(session, group, as_of=as_of)
                    for group in self._groups(
                        session,
                        row.snapshot_ref,
                        authority_sha256=row.scope_authority_sha256,
                    )
                ]
                if include_groups
                else []
            ),
        }

    def _project_group(
        self,
        session: Session,
        row: StrategicBenchmarkGroupRow,
        *,
        as_of: datetime,
    ) -> dict[str, Any]:
        observations = self._observations(session, row.group_ref)
        stale = any(
            observation.eligibility_state == "eligible"
            and self._database_time(observation.freshness_due_at) < as_of
            for observation in observations
        )
        state = "stale" if stale else row.comparison_state
        label = None if stale else row.leader_label
        leader_rows = list(
            session.scalars(
                select(StrategicBenchmarkLeaderRow)
                .where(StrategicBenchmarkLeaderRow.group_ref == row.group_ref)
                .order_by(StrategicBenchmarkLeaderRow.ordinal)
            )
        )
        persisted_leaders = [item.observation_ref for item in leader_rows]
        if persisted_leaders != list(row.leader_observation_refs_json):
            raise RuntimeError("benchmark leader relation projection drift")
        leaders = [] if stale else persisted_leaders
        return {
            "group_ref": row.group_ref,
            "ordinal": row.ordinal,
            "domain": row.domain,
            "metric_id": row.metric_id,
            "direction": row.direction,
            "unit": row.unit,
            "minimum_source_grade": row.minimum_source_grade,
            "freshness_days": row.freshness_days,
            "minimum_confidence_bps": METRIC_SPECS[
                (row.domain, row.metric_id)
            ].minimum_confidence_bps,
            "minimum_sample_size": METRIC_SPECS[
                (row.domain, row.metric_id)
            ].minimum_sample_size,
            "cohort_ref": row.cohort_ref,
            "market": row.market,
            "window": {
                "start": self._database_time(row.window_start).isoformat(),
                "end": self._database_time(row.window_end).isoformat(),
            },
            "methodology": {
                "id": row.methodology_id,
                "version": row.methodology_version,
                "sha256": row.methodology_sha256,
                "sample_definition_sha256": row.sample_definition_sha256,
            },
            "source_contract": {
                "id": row.source_contract_id,
                "version": row.source_contract_version,
                "sha256": row.source_contract_sha256,
                "kind": row.source_kind,
            },
            "comparison_state": state,
            "leader_label": label,
            "leader_observation_refs": leaders,
            "reason_code": "freshness_expired" if stale else row.reason_code,
            "counts": {
                "observations": row.observation_count,
                "comparable": 0 if stale else row.comparable_count,
                "ineligible": row.observation_count if stale else row.ineligible_count,
                "leaders": 0 if stale else row.leader_count,
            },
            "group_sha256": row.group_sha256,
            "result_sha256": row.result_sha256,
            "observations": [
                self._project_observation(
                    session,
                    item,
                    as_of=as_of,
                    domain=row.domain,
                    unit=row.unit,
                    source_kind=row.source_kind,
                    source_contract_id=row.source_contract_id,
                    source_contract_version=row.source_contract_version,
                )
                for item in observations
            ],
            "global_top1_claim": False,
        }

    def _project_observation(
        self,
        session: Session,
        row: StrategicBenchmarkObservationRow,
        *,
        as_of: datetime,
        domain: str,
        unit: str,
        source_kind: str,
        source_contract_id: str,
        source_contract_version: str,
    ) -> dict[str, Any]:
        state = row.eligibility_state
        if (
            state == "eligible"
            and StrategicBenchmarkKernel._database_time(row.freshness_due_at)
            < as_of
        ):
            state = "stale"
        if domain == "finance_and_capital" or unit == "accounts":
            value_projection: dict[str, Any] = {"mode": "withheld"}
        else:
            contract = SOURCE_CONTRACTS.get(
                (source_contract_id, source_contract_version), {}
            )
        if (
            domain != "finance_and_capital"
            and unit != "accounts"
            and contract.get("public_exact_allowed") is True
            and source_kind == contract.get("source_kind")
            and row.subject_class in contract.get("subject_classes", [])
        ):
            value_projection = {
                "mode": "public_exact",
                "value": StrategicBenchmarkKernel._decimal_text(row.value),
                "lower": StrategicBenchmarkKernel._decimal_text(
                    row.uncertainty_lower
                ),
                "upper": StrategicBenchmarkKernel._decimal_text(
                    row.uncertainty_upper
                ),
            }
        elif domain != "finance_and_capital" and unit != "accounts":
            value_projection = {
                "mode": "internal_band",
                "lower": StrategicBenchmarkKernel._decimal_text(
                    row.uncertainty_lower
                ),
                "upper": StrategicBenchmarkKernel._decimal_text(
                    row.uncertainty_upper
                ),
            }
        links = list(
            session.scalars(
                select(StrategicBenchmarkEvidenceLinkRow)
                .where(
                    StrategicBenchmarkEvidenceLinkRow.observation_ref
                    == row.observation_ref
                )
                .order_by(StrategicBenchmarkEvidenceLinkRow.ordinal)
            )
        )
        scope = {
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_authority_sha256": row.scope_authority_sha256,
        }
        citations = [
            {
                "token": self._citation_token(
                    snapshot_ref=row.snapshot_ref,
                    scope=scope,
                    observation_ref=row.observation_ref,
                    evidence_id=link.evidence_id,
                    evidence_sha256=link.evidence_sha256,
                ),
                "sha256": link.evidence_sha256,
                "grade": link.evidence_grade,
            }
            for link in links
        ]
        return {
            "observation_ref": row.observation_ref,
            "ordinal": row.ordinal,
            "subject_token": row.subject_token_sha256,
            "subject_class": row.subject_class,
            "value_projection": value_projection,
            "confidence_bps": row.confidence_bps,
            "sample_size": row.sample_size,
            "source_grade": row.source_grade,
            "citations": citations,
            "evidence_snapshot_sha256": row.evidence_snapshot_sha256,
            "observed_at": StrategicBenchmarkKernel._database_time(
                row.observed_at
            ).isoformat(),
            "freshness_due_at": StrategicBenchmarkKernel._database_time(
                row.freshness_due_at
            ).isoformat(),
            "eligibility_state": state,
            "observation_sha256": row.observation_sha256,
        }

    def _compare_group(
        self,
        session: Session,
        *,
        current: StrategicBenchmarkGroupRow,
        baseline: StrategicBenchmarkGroupRow | None,
        as_of: datetime,
    ) -> dict[str, Any]:
        base = {
            "domain": current.domain,
            "metric_id": current.metric_id,
            "cohort_ref": current.cohort_ref,
            "market": current.market,
            "direction": current.direction,
            "unit": current.unit,
            "current_group_ref": current.group_ref,
            "baseline_group_ref": baseline.group_ref if baseline else None,
        }
        if baseline is None:
            return {**base, "state": "not_comparable", "reason_code": "baseline_group_missing"}
        if self._comparison_key(current) != self._comparison_key(baseline):
            return {**base, "state": "invalidated", "reason_code": "source_or_method_drift"}
        current_projection = self._project_group(session, current, as_of=as_of)
        baseline_projection = self._project_group(session, baseline, as_of=as_of)
        if "stale" in {
            current_projection["comparison_state"],
            baseline_projection["comparison_state"],
        }:
            return {**base, "state": "stale", "reason_code": "comparison_source_stale"}
        if {
            current_projection["comparison_state"],
            baseline_projection["comparison_state"],
        } != {"comparable"}:
            return {
                **base,
                "state": "not_comparable",
                "reason_code": "comparison_group_not_fully_eligible",
            }
        current_leaders = self._leader_subject_hashes(current_projection)
        baseline_leaders = self._leader_subject_hashes(baseline_projection)
        return {
            **base,
            "state": "comparable",
            "reason_code": "exact_dimension_contract_match",
            "current_label": current_projection["leader_label"],
            "baseline_label": baseline_projection["leader_label"],
            "current_leader_observation_refs": current_projection[
                "leader_observation_refs"
            ],
            "baseline_leader_observation_refs": baseline_projection[
                "leader_observation_refs"
            ],
            "current_leader_subject_tokens": current_leaders,
            "baseline_leader_subject_tokens": baseline_leaders,
            "leader_changed": current_leaders != baseline_leaders,
        }

    @staticmethod
    def _leader_subject_hashes(projection: dict[str, Any]) -> list[str]:
        leader_refs = set(projection["leader_observation_refs"])
        return sorted(
            item["subject_token"]
            for item in projection["observations"]
            if item["observation_ref"] in leader_refs
        )

    @staticmethod
    def _comparison_key(row: StrategicBenchmarkGroupRow) -> tuple[Any, ...]:
        return (
            row.tenant_ref,
            row.entity_ref,
            row.store_ref,
            row.scope_authority_sha256,
            row.domain,
            row.metric_id,
            row.cohort_ref,
            row.market,
            StrategicBenchmarkKernel._database_time(row.window_start),
            StrategicBenchmarkKernel._database_time(row.window_end),
            row.methodology_id,
            row.methodology_version,
            row.methodology_sha256,
            row.source_contract_id,
            row.source_contract_version,
            row.source_contract_sha256,
            row.source_kind,
            row.unit,
            row.direction,
        )

    @classmethod
    def _group_index(
        cls, groups: list[StrategicBenchmarkGroupRow]
    ) -> dict[tuple[Any, ...], StrategicBenchmarkGroupRow]:
        result: dict[tuple[Any, ...], StrategicBenchmarkGroupRow] = {}
        for group in groups:
            key = cls._comparison_key(group)
            if key in result:
                raise StrategicBenchmarkConflictError(
                    "duplicate strategic benchmark comparison key"
                )
            result[key] = group
        return result

    @staticmethod
    def _comparison_identity(row: StrategicBenchmarkGroupRow) -> tuple[str, ...]:
        return (
            row.tenant_ref,
            row.entity_ref,
            row.store_ref,
            row.scope_authority_sha256,
            row.domain,
            row.metric_id,
            row.cohort_ref,
            row.market,
        )

    @classmethod
    def _group_identity_index(
        cls, groups: list[StrategicBenchmarkGroupRow]
    ) -> dict[tuple[str, ...], StrategicBenchmarkGroupRow]:
        result: dict[tuple[str, ...], StrategicBenchmarkGroupRow] = {}
        for group in groups:
            key = cls._comparison_identity(group)
            if key in result:
                raise StrategicBenchmarkConflictError(
                    "duplicate strategic benchmark comparison identity"
                )
            result[key] = group
        return result

    @staticmethod
    def _groups(
        session: Session,
        snapshot_ref: str,
        *,
        authority_sha256: str,
    ) -> list[StrategicBenchmarkGroupRow]:
        return list(
            session.scalars(
                select(StrategicBenchmarkGroupRow)
                .where(
                    StrategicBenchmarkGroupRow.snapshot_ref == snapshot_ref,
                    StrategicBenchmarkGroupRow.scope_authority_sha256
                    == authority_sha256,
                )
                .order_by(StrategicBenchmarkGroupRow.ordinal)
            )
        )

    @staticmethod
    def _observations(
        session: Session, group_ref: str
    ) -> list[StrategicBenchmarkObservationRow]:
        return list(
            session.scalars(
                select(StrategicBenchmarkObservationRow)
                .where(StrategicBenchmarkObservationRow.group_ref == group_ref)
                .order_by(StrategicBenchmarkObservationRow.ordinal)
            )
        )

    @staticmethod
    def _find_by_idempotency(
        session: Session,
        *,
        scope: dict[str, str],
        idempotency_sha256: str,
    ) -> StrategicBenchmarkSnapshotRow | None:
        return session.scalar(
            select(StrategicBenchmarkSnapshotRow).where(
                StrategicBenchmarkSnapshotRow.tenant_ref == scope["tenant_ref"],
                StrategicBenchmarkSnapshotRow.entity_ref == scope["entity_ref"],
                StrategicBenchmarkSnapshotRow.store_ref == scope["store_ref"],
                StrategicBenchmarkSnapshotRow.scope_authority_sha256
                == scope["scope_authority_sha256"],
                StrategicBenchmarkSnapshotRow.idempotency_sha256
                == idempotency_sha256,
            )
        )

    def _find(
        self,
        session: Session,
        *,
        scope: dict[str, str],
        snapshot_ref: str,
        as_of: datetime,
    ) -> StrategicBenchmarkSnapshotRow:
        row = session.scalar(
            select(StrategicBenchmarkSnapshotRow).where(
                StrategicBenchmarkSnapshotRow.snapshot_ref == snapshot_ref,
                StrategicBenchmarkSnapshotRow.tenant_ref == scope["tenant_ref"],
                StrategicBenchmarkSnapshotRow.entity_ref == scope["entity_ref"],
                StrategicBenchmarkSnapshotRow.store_ref == scope["store_ref"],
                StrategicBenchmarkSnapshotRow.scope_authority_sha256
                == scope["scope_authority_sha256"],
                StrategicBenchmarkSnapshotRow.as_of <= as_of,
            )
        )
        if row is None:
            raise KeyError("Strategic benchmark snapshot not found in authorized scope")
        return row

    def _scope(
        self, principal: Principal, store_ref: str, as_of: datetime
    ) -> dict[str, str]:
        store = self._token(store_ref, "store_ref")
        authority = self.scope_grants.current(
            principal=principal,
            store_ref=store,
            as_of=as_of,
        )
        if authority.get("status") != "ready":
            raise PermissionError(
                str(authority.get("reason") or "exact-scope authority is not ready")
            )
        tenant = self._token(authority.get("tenant_ref"), "tenant_ref")
        entity = self._token(authority.get("entity_ref"), "entity_ref")
        authority_store = self._token(
            authority.get("store_ref"), "authority_store_ref"
        )
        digest = self._sha256(
            authority.get("authority_sha256"), "scope_authority_sha256"
        )
        if tenant != principal.tenant_ref or authority_store != store:
            raise PermissionError("scope authority binding mismatch")
        return {
            "tenant_ref": tenant,
            "entity_ref": entity,
            "store_ref": store,
            "scope_authority_sha256": digest,
        }

    @staticmethod
    def _manifest(
        *,
        snapshot_ref: str,
        scope: dict[str, str],
        as_of: datetime,
        groups: list[dict[str, Any]],
        request_sha256: str,
    ) -> dict[str, Any]:
        return {
            "contract_id": CONTRACT_ID,
            "registry_schema": REGISTRY_SCHEMA,
            "registry_sha256": BENCHMARK_REGISTRY_SHA256,
            "snapshot_ref": snapshot_ref,
            "scope": scope,
            "as_of": as_of.isoformat(),
            "groups": [
                {
                    "group_sha256": group["group_sha256"],
                    "result_sha256": group["result_sha256"],
                    "domain": group["domain"],
                    "metric_id": group["metric_id"],
                    "cohort_ref": group["cohort_ref"],
                    "market": group["market"],
                    "comparison_state": group["comparison_state"],
                    "leader_label": group["leader_label"],
                    "observation_hashes": [
                        observation["observation_sha256"]
                        for observation in group["observations"]
                    ],
                }
                for group in groups
            ],
            "request_sha256": request_sha256,
            "global_top1_claim": False,
            "formal_fact_created": False,
            "finance_entry_created": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _require_same_request(
        row: StrategicBenchmarkSnapshotRow, request_sha256: str
    ) -> None:
        if not hmac.compare_digest(row.request_sha256, request_sha256):
            raise StrategicBenchmarkConflictError(
                "Idempotency key is already bound to a different benchmark request"
            )

    @staticmethod
    def _require_role(principal: Principal, *roles: str) -> None:
        if not principal.has_any_role(*roles):
            raise PermissionError("Authenticated actor lacks required benchmark role")

    @staticmethod
    def _exact_keys(raw: Any, expected: set[str], field: str) -> None:
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ValueError(f"{field} must contain exactly {sorted(expected)}")

    @staticmethod
    def _token(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not _TOKEN.fullmatch(text):
            raise ValueError(f"{field} must be a bounded identifier")
        return text

    @classmethod
    def _safe_text(cls, value: Any, field: str, maximum: int) -> str:
        text = str(value or "").strip()
        if not text or len(text) > maximum:
            raise ValueError(f"{field} must contain 1 to {maximum} characters")
        if _EMAIL.search(text) or _SECRET.search(text):
            raise ValueError(f"{field} cannot contain raw contact or secret material")
        return text

    @staticmethod
    def _choice(value: Any, field: str, allowed: frozenset[str]) -> str:
        text = str(value or "").strip()
        if text not in allowed:
            raise ValueError(f"{field} must be one of {sorted(allowed)}")
        return text

    @staticmethod
    def _integer(
        value: Any, field: str, *, minimum: int, maximum: int
    ) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} must be an integer")
        try:
            numeric = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be an integer") from exc
        if not numeric.is_finite() or numeric != numeric.to_integral_value():
            raise ValueError(f"{field} must be an integer")
        result = int(numeric)
        if result < minimum or result > maximum:
            raise ValueError(f"{field} is outside the allowed range")
        return result

    @staticmethod
    def _decimal(value: Any, field: str) -> Decimal:
        if isinstance(value, bool):
            raise ValueError(f"{field} must be a finite non-negative decimal")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a finite non-negative decimal") from exc
        if not result.is_finite() or result < 0 or result > MAX_VALUE:
            raise ValueError(f"{field} must be a finite non-negative decimal")
        with localcontext() as context:
            context.prec = 50
            return result.quantize(DECIMAL_SCALE)

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        text = format(Decimal(value), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    @staticmethod
    def _evidence_refs(value: Any) -> list[str]:
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_EVIDENCE_PER_OBSERVATION:
            raise ValueError(
                f"evidence_refs must contain 1 to {MAX_EVIDENCE_PER_OBSERVATION} items"
            )
        refs = [str(item or "").strip() for item in value]
        if any(not _TOKEN.fullmatch(item) for item in refs):
            raise ValueError("evidence_refs must contain bounded identifiers")
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate evidence_refs are not allowed")
        return refs

    @staticmethod
    def _snapshot_evidence_refs(value: Any) -> list[str]:
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_SNAPSHOT_EVIDENCE:
            raise ValueError(
                f"evidence_refs must contain 1 to {MAX_SNAPSHOT_EVIDENCE} items"
            )
        refs = [str(item or "").strip() for item in value]
        if any(not _TOKEN.fullmatch(item) for item in refs):
            raise ValueError("evidence_refs must contain bounded identifiers")
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate evidence_refs are not allowed")
        return sorted(refs)

    @staticmethod
    def _aware(value: Any, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        return value.astimezone(UTC)

    @classmethod
    def _timestamp(cls, value: Any, field: str) -> datetime:
        if isinstance(value, datetime):
            return cls._aware(value, field)
        if not isinstance(value, str):
            raise ValueError(f"{field} must be an ISO-8601 timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
        return cls._aware(parsed, field)

    @staticmethod
    def _database_time(value: datetime) -> datetime:
        """Normalize dialect-specific timestamp round-trips to UTC.

        PostgreSQL preserves timezone-aware values, while SQLite returns a
        naive wall-clock value for ``DateTime(timezone=True)``. Persisted BAS-199
        timestamps are UTC by contract, so a missing tzinfo is interpreted as
        UTC rather than compared against an aware cutoff.
        """
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def _persisted_timestamp(cls, value: Any, field: str) -> datetime:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
        if not isinstance(value, datetime):
            raise ValueError(f"{field} must be a timestamp")
        return cls._database_time(value)

    @staticmethod
    def _snapshot_ref(value: Any) -> str:
        text = str(value or "").strip()
        if not re.fullmatch(r"sbs_[0-9a-f]{32}", text):
            raise ValueError("snapshot_ref is invalid")
        return text

    def _citation_token(
        self,
        *,
        snapshot_ref: str,
        scope: dict[str, str],
        observation_ref: str,
        evidence_id: str,
        evidence_sha256: str,
    ) -> str:
        payload = self._canonical(
            {
                "snapshot_ref": snapshot_ref,
                "scope_authority_sha256": scope["scope_authority_sha256"],
                "observation_ref": observation_ref,
                "evidence_id": evidence_id,
                "evidence_sha256": evidence_sha256,
            }
        )
        digest = hmac.new(self._citation_token_key, payload, hashlib.sha256).digest()
        return "sbc_" + base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def _encode_cursor(
        self,
        *,
        scope: dict[str, str],
        as_of: datetime,
        filters: dict[str, Any],
        last_created: datetime,
        last_ref: str,
    ) -> str:
        payload = self._canonical(
            {
                "v": 1,
                "scope": scope,
                "as_of": as_of,
                "filters": filters,
                "last_created": last_created,
                "last_ref": last_ref,
            }
        )
        nonce = os.urandom(12)
        sealed = nonce + self._cursor_aead.encrypt(
            nonce,
            payload,
            b"kjds-strategic-benchmark-cursor-v2",
        )
        body = base64.urlsafe_b64encode(sealed).decode().rstrip("=")
        return f"sbcursor_v2.{body}"

    def _decode_cursor(
        self,
        cursor: str,
        *,
        scope: dict[str, str],
        as_of: datetime,
        filters: dict[str, Any],
    ) -> tuple[datetime, str]:
        try:
            prefix, body = cursor.split(".", 1)
            if prefix != "sbcursor_v2" or not re.fullmatch(r"[A-Za-z0-9_-]+", body):
                raise ValueError
            padding = "=" * (-len(body) % 4)
            sealed = base64.b64decode(
                (body + padding).encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
            canonical_body = base64.urlsafe_b64encode(sealed).decode().rstrip("=")
            if not hmac.compare_digest(canonical_body, body):
                raise ValueError
            if len(sealed) <= 28:
                raise ValueError
            nonce, ciphertext = sealed[:12], sealed[12:]
            plaintext = self._cursor_aead.decrypt(
                nonce,
                ciphertext,
                b"kjds-strategic-benchmark-cursor-v2",
            )
            payload = json.loads(plaintext)
        except (
            InvalidTag,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
            raise KeyError("Strategic benchmark cursor not found") from exc
        expected_binding = {
            "v": 1,
            "scope": scope,
            "as_of": as_of.isoformat(),
            "filters": filters,
        }
        actual_binding = {
            "v": payload.get("v"),
            "scope": payload.get("scope"),
            "as_of": payload.get("as_of"),
            "filters": payload.get("filters"),
        }
        if not hmac.compare_digest(
            self._hash(actual_binding), self._hash(expected_binding)
        ):
            raise KeyError("Strategic benchmark cursor not found")
        try:
            return (
                self._timestamp(payload.get("last_created"), "cursor.last_created"),
                self._snapshot_ref(payload.get("last_ref")),
            )
        except ValueError as exc:
            raise KeyError("Strategic benchmark cursor not found") from exc

    @staticmethod
    def _sha256(value: Any, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _HEX64.fullmatch(text):
            raise ValueError(f"{field} must be a lowercase SHA-256")
        return text

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()

    @staticmethod
    def _text_hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @classmethod
    def _canonical(cls, value: Any) -> bytes:
        return json.dumps(
            cls._json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        if isinstance(value, Decimal):
            return cls._decimal_text(value)
        if isinstance(value, dict):
            return {str(key): cls._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite numeric values are not allowed")
        return value
