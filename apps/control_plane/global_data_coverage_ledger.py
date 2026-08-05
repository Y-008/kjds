from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .evidence import EvidenceGrade, EvidenceService
from .evidence_scope import BINDING_CONTRACT, DIRECT_CONTRACT, ScopedEvidenceAuthority
from .global_data_coverage import (
    CoverageObservation,
    GlobalDataCoverageWorkspace,
    canonical_json,
)
from .security import Principal
from .sql_repository import Base

LEDGER_CONTRACT_ID = "kjds-global-data-coverage-ledger-v1"
LEDGER_EVIDENCE_CONTRACT_ID = "kjds-global-data-coverage-ledger-evidence-v1"
LEDGER_EVIDENCE_SOURCE = "global-data-coverage-ledger"
MANIFEST_EVIDENCE_SOURCE = "global-data-coverage-manifest"
MANIFEST_EVIDENCE_CONTRACT_ID = "kjds-global-data-coverage-manifest-evidence-v1"
NATIVE_CAPS_EVIDENCE_SOURCE = "global-data-coverage-native-caps"
NATIVE_CAPS_EVIDENCE_CONTRACT_ID = "kjds-global-data-coverage-native-caps-evidence-v1"
DENOMINATOR_EVIDENCE_SOURCE = "global-data-coverage-denominator"
DENOMINATOR_EVIDENCE_CONTRACT_ID = "kjds-global-data-coverage-denominator-evidence-v1"
DENOMINATOR_SCHEMA_VERSION = "kjds-global-data-coverage-denominator-v1"
ZERO_SHA256 = "0" * 64
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_EVENTS = frozenset({"snapshot_committed", "unknown_outcome", "invalidated"})
EVENT_TYPES = frozenset({"snapshot_started", *TERMINAL_EVENTS})


class CoverageLedgerConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CoverageLedgerScopeContext:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    scope_grant_authority_sha256: str
    actor_id: str
    data_as_of: datetime
    authority_checked_at: datetime


@dataclass(frozen=True, slots=True)
class CoverageLedgerReceipt:
    contract_id: str
    snapshot_id: str
    status: str
    source_id: str
    source_family: str
    manifest_ref: str
    manifest_sha256: str
    native_caps_sha256: str
    registry_sha256: str
    observation_sha256: str
    request_sha256: str
    event_chain_sha256: str
    event_count: int
    idempotent: bool
    currentness: str
    full_coverage_claim: bool
    formal_fact: bool = False
    decision: bool = False
    approval: bool = False
    permit: bool = False
    pilot: bool = False
    outbox: bool = False
    external_write: bool = False
    receipt_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GlobalDataCoverageSnapshotRow(Base):
    __tablename__ = "global_data_coverage_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_gdc_snapshot_exact_scope",
        ),
        UniqueConstraint(
            "snapshot_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "transaction_stamp",
            name="uq_gdc_snapshot_exact_scope_tx",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "idempotency_sha256",
            name="uq_gdc_scope_idempotency",
        ),
        CheckConstraint(
            "scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND "
            "manifest_sha256 ~ '^[0-9a-f]{64}$' AND "
            "manifest_evidence_sha256 ~ '^[0-9a-f]{64}$' AND "
            "native_caps_sha256 ~ '^[0-9a-f]{64}$' AND "
            "native_caps_evidence_sha256 ~ '^[0-9a-f]{64}$' AND "
            "registry_sha256 ~ '^[0-9a-f]{64}$' AND "
            "observation_sha256 ~ '^[0-9a-f]{64}$' AND "
            "idempotency_sha256 ~ '^[0-9a-f]{64}$' AND "
            "request_sha256 ~ '^[0-9a-f]{64}$' AND "
            "checkpoint_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_snapshot_hashes",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(scope_grant_authority_sha256)=64 AND "
            "scope_grant_authority_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(manifest_sha256)=64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(manifest_evidence_sha256)=64 AND "
            "manifest_evidence_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(native_caps_sha256)=64 AND "
            "native_caps_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(native_caps_evidence_sha256)=64 AND "
            "native_caps_evidence_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(registry_sha256)=64 AND registry_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(observation_sha256)=64 AND "
            "observation_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(idempotency_sha256)=64 AND "
            "idempotency_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(request_sha256)=64 AND request_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(checkpoint_sha256)=64 AND "
            "checkpoint_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_gdc_snapshot_hashes_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "transaction_stamp > 0",
            name="ck_gdc_snapshot_transaction_stamp",
        ),
        CheckConstraint(
            "ledger_contract_id='kjds-global-data-coverage-ledger-v1' AND "
            "length(source_contract_id)>0 AND length(source_contract_version)>0 AND "
            "manifest_schema_version='kjds-source-coverage-manifest-v1' AND "
            "manifest_evidence_contract_id="
            "'kjds-global-data-coverage-manifest-evidence-v1' AND "
            "native_caps_schema='kjds-source-native-caps-v1' AND "
            "native_caps_evidence_contract_id="
            "'kjds-global-data-coverage-native-caps-evidence-v1'",
            name="ck_gdc_snapshot_contracts",
        ),
        CheckConstraint(
            "expected_count IS NULL OR expected_count >= 0",
            name="ck_gdc_expected_count",
        ),
        CheckConstraint(
            "observed_count >= 0 AND accepted_count >= 0 AND quarantined_count >= 0 "
            "AND failed_count >= 0 AND duplicate_count >= 0 AND suppressed_count >= 0 "
            "AND source_total >= 0 AND page_expected_count >= 0 "
            "AND page_received_count >= 0 AND page_failed_count >= 0 "
            "AND page_duplicate_count >= 0 AND checkpoint_sequence >= 0 "
            "AND required_field_count >= 0 AND window_gap_count >= 0 "
            "AND window_overlap_count >= 0 AND window_late_arrival_count >= 0 "
            "AND conflict_count >= 0 AND evidence_count > 0",
            name="ck_gdc_snapshot_nonnegative",
        ),
        CheckConstraint(
            "accepted_count + quarantined_count + failed_count + duplicate_count + "
            "suppressed_count = source_total AND observed_count = source_total",
            name="ck_gdc_snapshot_conservation",
        ),
        CheckConstraint(
            "page_received_count + page_failed_count = page_expected_count",
            name="ck_gdc_page_conservation",
        ),
        CheckConstraint(
            "page_duplicate_count <= page_received_count",
            name="ck_gdc_page_duplicate_conservation",
        ),
        CheckConstraint(
            "(denominator_known AND expected_count IS NOT NULL "
            "AND denominator_evidence_ref IS NOT NULL "
            "AND denominator_evidence_sha256 ~ '^[0-9a-f]{64}$') OR "
            "(NOT denominator_known AND expected_count IS NULL "
            "AND denominator_evidence_ref IS NULL "
            "AND denominator_evidence_sha256 IS NULL)",
            name="ck_gdc_denominator_matrix",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "((denominator_known = 1 AND expected_count IS NOT NULL "
            "AND denominator_evidence_ref IS NOT NULL "
            "AND length(denominator_evidence_sha256)=64 "
            "AND denominator_evidence_sha256 NOT GLOB '*[^0-9a-f]*') OR "
            "(denominator_known = 0 AND expected_count IS NULL "
            "AND denominator_evidence_ref IS NULL "
            "AND denominator_evidence_sha256 IS NULL))",
            name="ck_gdc_denominator_matrix_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "captured_at <= recorded_at AND recorded_at <= data_as_of "
            "AND data_as_of <= authority_checked_at AND authority_checked_at <= created_at "
            "AND fresh_until > recorded_at AND review_due >= recorded_at",
            name="ck_gdc_snapshot_chronology",
        ),
        CheckConstraint(
            "NOT formal_fact AND NOT decision AND NOT approval AND NOT permit "
            "AND NOT pilot AND NOT outbox AND NOT external_write",
            name="ck_gdc_no_promotion_or_write",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "formal_fact = 0 AND decision = 0 AND approval = 0 AND permit = 0 "
            "AND pilot = 0 AND outbox = 0 AND external_write = 0",
            name="ck_gdc_no_promotion_or_write_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "source_status IN ('implemented','contract_only','blocked','unsupported') AND "
            "observation_status IN ('complete','partial','unknown','missing','blocked',"
            "'unsupported','not_applicable') AND "
            "completeness IN ('complete','partial','unknown','missing','blocked',"
            "'unsupported','not_applicable') AND observation_status = completeness AND "
            "freshness_status IN ('fresh','stale','unknown','blocked') AND window_timezone='UTC'",
            name="ck_gdc_snapshot_status_vocabulary",
        ),
        Index(
            "ix_gdc_snapshot_scope_source_asof",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "source_id",
            "data_as_of",
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_stamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authority_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(240), nullable=False)
    source_family: Mapped[str] = mapped_column(String(80), nullable=False)
    source_status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_contract_id: Mapped[str] = mapped_column(String(240), nullable=False)
    source_contract_version: Mapped[str] = mapped_column(String(120), nullable=False)
    ledger_contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    manifest_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    manifest_version: Mapped[str] = mapped_column(String(120), nullable=False)
    manifest_schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    manifest_evidence_contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_evidence_id: Mapped[str] = mapped_column(String(160), nullable=False)
    manifest_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    native_caps_schema: Mapped[str] = mapped_column(String(120), nullable=False)
    native_caps_evidence_contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    native_caps_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    native_caps_evidence_id: Mapped[str] = mapped_column(String(160), nullable=False)
    native_caps_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registry_contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    registry_schema_version: Mapped[str] = mapped_column(String(160), nullable=False)
    registry_as_of: Mapped[str] = mapped_column(String(32), nullable=False)
    registry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    completeness: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    denominator_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    denominator_evidence_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    denominator_evidence_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    suppressed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_total: Mapped[int] = mapped_column(Integer, nullable=False)
    page_expected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_received_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_field_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_gap_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_overlap_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    window_late_arrival_count: Mapped[int] = mapped_column(Integer, nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(40), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fresh_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_due: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    full_coverage_claim: Mapped[bool] = mapped_column(Boolean, nullable=False)
    formal_fact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pilot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _child_scope_constraints(name: str) -> tuple[Any, ...]:
    return (
        ForeignKeyConstraint(
            [
                "snapshot_id",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
                "transaction_stamp",
            ],
            [
                "global_data_coverage_snapshots.snapshot_id",
                "global_data_coverage_snapshots.tenant_ref",
                "global_data_coverage_snapshots.entity_ref",
                "global_data_coverage_snapshots.store_ref",
                "global_data_coverage_snapshots.scope_grant_authority_sha256",
                "global_data_coverage_snapshots.transaction_stamp",
            ],
            name=f"fk_gdc_{name}_exact_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


class GlobalDataCoverageNativeCapsRow(Base):
    __tablename__ = "global_data_coverage_native_caps"
    __table_args__ = (
        *_child_scope_constraints("caps"),
        UniqueConstraint("snapshot_id", name="uq_gdc_caps_snapshot"),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_gdc_caps_hash"
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(content_sha256)=64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_gdc_caps_hash_sqlite",
        ).ddl_if(dialect="sqlite"),
    )

    caps_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_stamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    source_id: Mapped[str] = mapped_column(String(240), nullable=False)
    source_family: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(240), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(120), nullable=False)
    capability_version: Mapped[str] = mapped_column(String(120), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    pagination_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    page_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    historical_depth_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    authentication_mode: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalDataCoverageFieldRow(Base):
    __tablename__ = "global_data_coverage_fields"
    __table_args__ = (
        *_child_scope_constraints("field"),
        UniqueConstraint("snapshot_id", "ordinal", name="uq_gdc_field_ordinal"),
        UniqueConstraint("snapshot_id", "field_name", name="uq_gdc_field_name"),
        CheckConstraint(
            "ordinal>0 AND field_name_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_field_ordinal_hash",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "ordinal>0 AND length(field_name_sha256)=64 AND "
            "field_name_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_gdc_field_ordinal_hash_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "field_status IN ('present','missing','unparseable','conflicting')",
            name="ck_gdc_field_status",
        ),
    )

    field_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_stamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    field_name: Mapped[str] = mapped_column(String(240), nullable=False)
    field_name_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    field_status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalDataCoverageFailedPageRow(Base):
    __tablename__ = "global_data_coverage_failed_pages"
    __table_args__ = (
        *_child_scope_constraints("page"),
        UniqueConstraint("snapshot_id", "ordinal", name="uq_gdc_page_ordinal"),
        UniqueConstraint("snapshot_id", "failed_ref_sha256", name="uq_gdc_page_ref"),
        CheckConstraint(
            "ordinal>0 AND failed_ref_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_page_ordinal_hash",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "ordinal>0 AND length(failed_ref_sha256)=64 AND "
            "failed_ref_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_gdc_page_ordinal_hash_sqlite",
        ).ddl_if(dialect="sqlite"),
    )

    failed_page_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_stamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_ref_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalDataCoverageWindowRow(Base):
    __tablename__ = "global_data_coverage_windows"
    __table_args__ = (
        *_child_scope_constraints("window"),
        UniqueConstraint("snapshot_id", "segment_kind", "ordinal", name="uq_gdc_window_segment"),
        CheckConstraint(
            "ordinal>0 AND start_at<end_at", name="ck_gdc_window_interval"
        ),
        CheckConstraint(
            "segment_kind IN ('requested','effective','gap','overlap')",
            name="ck_gdc_window_kind",
        ),
        CheckConstraint(
            "(segment_kind IN ('requested','effective') AND reason_code IS NULL) OR "
            "(segment_kind IN ('gap','overlap') AND reason_code IS NOT NULL)",
            name="ck_gdc_window_reason",
        ),
    )

    window_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_stamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    segment_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalDataCoverageConflictRow(Base):
    __tablename__ = "global_data_coverage_conflicts"
    __table_args__ = (
        *_child_scope_constraints("conflict"),
        UniqueConstraint("snapshot_id", "ordinal", name="uq_gdc_conflict_ordinal"),
        UniqueConstraint("snapshot_id", "conflict_ref_sha256", name="uq_gdc_conflict_ref"),
        CheckConstraint(
            "ordinal>0 AND conflict_ref_sha256 ~ '^[0-9a-f]{64}$' AND "
            "subject_ref_sha256 ~ '^[0-9a-f]{64}$' AND "
            "field_name_sha256 ~ '^[0-9a-f]{64}$' AND "
            "valid_interval_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_conflict_hashes",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "ordinal>0 AND length(conflict_ref_sha256)=64 AND "
            "conflict_ref_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(subject_ref_sha256)=64 AND "
            "subject_ref_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(field_name_sha256)=64 AND "
            "field_name_sha256 NOT GLOB '*[^0-9a-f]*' AND "
            "length(valid_interval_sha256)=64 AND "
            "valid_interval_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_gdc_conflict_hashes_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "value_hash_count >= 2 AND value_hash_count <= 20 AND "
            "value_hashes_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_conflict_values",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "value_hash_count >= 2 AND value_hash_count <= 20 AND "
            "length(value_hashes_sha256)=64 "
            "AND value_hashes_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_gdc_conflict_values_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "resolution_status IN ('unresolved','independently_resolved')",
            name="ck_gdc_conflict_resolution",
        ),
    )

    conflict_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_stamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    conflict_ref_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_ref_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    field_name_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_interval_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    value_hash_count: Mapped[int] = mapped_column(Integer, nullable=False)
    value_hashes_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalDataCoverageEvidenceLinkRow(Base):
    __tablename__ = "global_data_coverage_evidence_links"
    __table_args__ = (
        *_child_scope_constraints("evidence"),
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
            name="fk_gdc_evidence_exact_binding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scope_binding_evidence_id"],
            ["evidence_records.id"],
            name="fk_gdc_scope_binding_evidence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "evidence_id",
                "intake_issuance_sha256",
                "intake_issuance_signature_sha256",
            ],
            [
                "global_data_coverage_evidence_issuances.evidence_id",
                "global_data_coverage_evidence_issuances.issuance_sha256",
                "global_data_coverage_evidence_issuances.issuance_signature_sha256",
            ],
            name="fk_gdc_intake_issuance",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("snapshot_id", "ordinal", name="uq_gdc_evidence_ordinal"),
        UniqueConstraint("snapshot_id", "evidence_id", name="uq_gdc_evidence_id"),
        CheckConstraint(
            "ordinal > 0 AND evidence_role IN "
            "('manifest','native_caps','denominator','supporting')",
            name="ck_gdc_evidence_role",
        ),
        CheckConstraint(
            "(evidence_role='manifest' AND evidence_source='global-data-coverage-manifest' "
            "AND evidence_grade='A') OR "
            "(evidence_role='native_caps' AND evidence_source='global-data-coverage-native-caps' "
            "AND evidence_grade='A') OR "
            "(evidence_role='denominator' AND evidence_source='global-data-coverage-denominator' "
            "AND evidence_grade='A') OR evidence_role='supporting'",
            name="ck_gdc_evidence_role_binding",
        ),
        CheckConstraint(
            "(evidence_role IN ('manifest','native_caps','denominator') "
            "AND intake_issuance_sha256 ~ '^[0-9a-f]{64}$' "
            "AND intake_issuance_signature_sha256 ~ '^[0-9a-f]{64}$' "
            "AND scope_authority_contract_id IS NULL "
            "AND scope_binding_evidence_id IS NULL AND scope_binding_evidence_sha256 IS NULL) OR "
            "(evidence_role='supporting' AND scope_authority_contract_id='kjds-evidence-scope-v1' "
            "AND intake_issuance_sha256 IS NULL AND intake_issuance_signature_sha256 IS NULL "
            "AND scope_binding_evidence_id IS NULL AND scope_binding_evidence_sha256 IS NULL) OR "
            "(evidence_role='supporting' AND scope_authority_contract_id='kjds-evidence-scope-binding-v1' "
            "AND intake_issuance_sha256 IS NULL AND intake_issuance_signature_sha256 IS NULL "
            "AND scope_binding_evidence_id IS NOT NULL "
            "AND scope_binding_evidence_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_gdc_evidence_scope_authority",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(evidence_role IN ('manifest','native_caps','denominator') "
            "AND length(intake_issuance_sha256)=64 "
            "AND intake_issuance_sha256 NOT GLOB '*[^0-9a-f]*' "
            "AND length(intake_issuance_signature_sha256)=64 "
            "AND intake_issuance_signature_sha256 NOT GLOB '*[^0-9a-f]*' "
            "AND scope_authority_contract_id IS NULL "
            "AND scope_binding_evidence_id IS NULL AND scope_binding_evidence_sha256 IS NULL) OR "
            "(evidence_role='supporting' AND scope_authority_contract_id='kjds-evidence-scope-v1' "
            "AND intake_issuance_sha256 IS NULL AND intake_issuance_signature_sha256 IS NULL "
            "AND scope_binding_evidence_id IS NULL AND scope_binding_evidence_sha256 IS NULL) OR "
            "(evidence_role='supporting' AND "
            "scope_authority_contract_id='kjds-evidence-scope-binding-v1' "
            "AND intake_issuance_sha256 IS NULL AND intake_issuance_signature_sha256 IS NULL "
            "AND scope_binding_evidence_id IS NOT NULL "
            "AND length(scope_binding_evidence_sha256)=64 "
            "AND scope_binding_evidence_sha256 NOT GLOB '*[^0-9a-f]*')",
            name="ck_gdc_evidence_scope_authority_sqlite",
        ).ddl_if(dialect="sqlite"),
        Index("ix_gdc_evidence_reverse", "evidence_id"),
    )

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_stamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_role: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(4), nullable=False)
    evidence_effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evidence_declared_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    intake_issuance_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intake_issuance_signature_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    scope_authority_contract_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    scope_binding_evidence_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    scope_binding_evidence_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalDataCoverageEventRow(Base):
    __tablename__ = "global_data_coverage_events"
    __table_args__ = (
        *_child_scope_constraints("event"),
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
            name="fk_gdc_event_evidence_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("snapshot_id", "event_index", name="uq_gdc_event_ordinal"),
        UniqueConstraint("snapshot_id", "event_sha256", name="uq_gdc_event_hash"),
        UniqueConstraint("evidence_id", name="uq_gdc_event_evidence"),
        CheckConstraint("event_index > 0", name="ck_gdc_event_ordinal"),
        CheckConstraint(
            "event_type IN ('snapshot_started','snapshot_committed','unknown_outcome','invalidated')",
            name="ck_gdc_event_type",
        ),
        CheckConstraint(
            "occurred_at<=recorded_at AND evidence_effective_at=occurred_at AND "
            "evidence_source='global-data-coverage-ledger' AND evidence_grade='D' AND "
            "evidence_source_ref=('coverage-ledger://' || snapshot_id || '/' || event_id) AND "
            "previous_event_sha256 ~ '^[0-9a-f]{64}$' AND "
            "event_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_event_binding",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "occurred_at<=recorded_at AND evidence_effective_at=occurred_at AND "
            "evidence_source='global-data-coverage-ledger' AND evidence_grade='D' AND "
            "evidence_source_ref=('coverage-ledger://' || snapshot_id || '/' || event_id) AND "
            "length(previous_event_sha256)=64 AND "
            "previous_event_sha256 NOT GLOB '*[^0-9a-f]*' AND length(event_sha256)=64 AND "
            "event_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_gdc_event_binding_sqlite",
        ).ddl_if(dialect="sqlite"),
        Index("ix_gdc_event_snapshot", "snapshot_id", "event_index"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_stamp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    previous_event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(4), nullable=False)
    evidence_effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalDataCoverageLedger:
    """Persist immutable coverage Observations under current exact-scope authority."""

    def __init__(
        self,
        *,
        engine,
        evidence: EvidenceService,
        scope_grants,
        workspace: GlobalDataCoverageWorkspace | None = None,
        trusted_registry: dict[str, Any] | None = None,
        scoped_evidence_authority: ScopedEvidenceAuthority | None = None,
        clock=None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scope_grants = scope_grants
        self.scoped_evidence_authority = scoped_evidence_authority or ScopedEvidenceAuthority(
            evidence=evidence
        )
        repository_root = Path(__file__).resolve().parents[2]
        registry = trusted_registry
        if registry is None:
            registry = json.loads(
                (
                    repository_root
                    / "docs"
                    / "project"
                    / "registries"
                    / "global_source_domain_registry.json"
                ).read_text("utf-8")
            )
        self.registry_snapshot = json.loads(canonical_json(registry))
        self.workspace = workspace or GlobalDataCoverageWorkspace(
            trusted_registry=self.registry_snapshot
        )
        self.clock = clock or (lambda: datetime.now(UTC))

    def record(
        self,
        *,
        principal: Principal,
        store_ref: str,
        data_as_of: datetime,
        idempotency_key: str,
        manifest_evidence_id: str,
        native_caps_evidence_id: str,
    ) -> CoverageLedgerReceipt:
        context = self._context(
            principal=principal,
            store_ref=store_ref,
            data_as_of=data_as_of,
        )
        try:
            registry_as_of = datetime.fromisoformat(self.registry_snapshot["as_of"]).date()
        except (KeyError, TypeError, ValueError) as exc:
            raise CoverageLedgerConflictError("trusted registry as_of is invalid") from exc
        if registry_as_of > context.data_as_of.date():
            raise CoverageLedgerConflictError("trusted registry is newer than data_as_of")
        idempotency_sha256 = _sha256_text(_required(idempotency_key, "idempotency_key"))
        manifest, manifest_evidence = self._contract_evidence(
            evidence_id=manifest_evidence_id,
            source=MANIFEST_EVIDENCE_SOURCE,
            contract_id=MANIFEST_EVIDENCE_CONTRACT_ID,
            schema_version="kjds-source-coverage-manifest-v1",
            context=context,
        )
        native_caps, native_caps_evidence = self._contract_evidence(
            evidence_id=native_caps_evidence_id,
            source=NATIVE_CAPS_EVIDENCE_SOURCE,
            contract_id=NATIVE_CAPS_EVIDENCE_CONTRACT_ID,
            schema_version="kjds-source-native-caps-v1",
            context=context,
        )
        source_contract_id = manifest["source"]["source_contract_id"]
        source_contract_version = manifest["source"]["source_contract_version"]
        if (
            manifest_evidence.metadata.get("coverage_intake_source_contract_id")
            != source_contract_id
            or native_caps_evidence.metadata.get("coverage_intake_source_contract_id")
            != source_contract_id
            or manifest_evidence.metadata.get("coverage_intake_source_contract_version")
            != source_contract_version
            or native_caps_evidence.metadata.get("coverage_intake_source_contract_version")
            != source_contract_version
        ):
            raise CoverageLedgerConflictError("coverage intake source contract drifted")
        observation = self.workspace.validate(
            manifest,
            native_caps,
            self.registry_snapshot,
            context.data_as_of,
        )
        if observation.full_coverage_claim and not _ledger_full_claim_eligible(
            manifest, observation, context.authority_checked_at
        ):
            observation = replace(
                observation,
                full_coverage_claim=False,
                full_coverage_claim_scope="not_proven",
                observation_sha256="",
            )
            observation = replace(
                observation,
                observation_sha256=_sha256(observation.to_dict()),
            )
        request_sha256 = _sha256(
            {
                "contract_id": LEDGER_CONTRACT_ID,
                "scope": _scope_dict(context),
                "manifest_ref": manifest["manifest_ref"],
                "source_contract_id": source_contract_id,
                "source_contract_version": source_contract_version,
                "manifest_version": manifest["manifest_version"],
                "manifest_schema_version": manifest["schema_version"],
                "manifest_evidence_contract_id": MANIFEST_EVIDENCE_CONTRACT_ID,
                "manifest_sha256": manifest["content_sha256"],
                "manifest_evidence_id": manifest_evidence.id,
                "manifest_evidence_sha256": manifest_evidence.sha256,
                "native_caps_schema": native_caps["schema_version"],
                "native_caps_evidence_contract_id": NATIVE_CAPS_EVIDENCE_CONTRACT_ID,
                "native_caps_sha256": native_caps["content_sha256"],
                "native_caps_evidence_id": native_caps_evidence.id,
                "native_caps_evidence_sha256": native_caps_evidence.sha256,
                "registry_contract_id": self.registry_snapshot["contract_id"],
                "registry_schema_version": self.registry_snapshot["schema_version"],
                "registry_as_of": self.registry_snapshot["as_of"],
                "registry_sha256": self.registry_snapshot["content_sha256"],
                "observation_contract_id": observation.contract_id,
                "observation_sha256": observation.observation_sha256,
                "input_evidence": [
                    {"id": item["id"], "sha256": item["sha256"]}
                    for item in manifest["evidence_refs"]
                ],
            }
        )
        existing = self._winner(context, idempotency_sha256)
        if existing is not None:
            return self._replay_winner(existing, context, request_sha256)
        evidence_records = [
            ("manifest", manifest_evidence),
            ("native_caps", native_caps_evidence),
            *self._input_evidence(manifest, context, principal),
        ]
        try:
            return self._insert(
                context=context,
                idempotency_sha256=idempotency_sha256,
                request_sha256=request_sha256,
                manifest=manifest,
                native_caps=native_caps,
                observation=observation,
                evidence_records=evidence_records,
            )
        except IntegrityError as exc:
            if not _is_idempotency_conflict(exc):
                raise
            winner = self._winner(context, idempotency_sha256)
            if winner is None:
                raise
            return self._replay_winner(winner, context, request_sha256)

    def get(
        self,
        *,
        principal: Principal,
        store_ref: str,
        snapshot_id: str,
    ) -> CoverageLedgerReceipt:
        context = self._context(principal=principal, store_ref=store_ref)
        with Session(self.engine) as session:
            row = session.scalar(
                self._scope_query(context).where(
                    GlobalDataCoverageSnapshotRow.snapshot_id == snapshot_id
                )
            )
            if row is None:
                raise KeyError("Coverage snapshot not found")
            return self._receipt(session, row, context=context, idempotent=True)

    def list(
        self,
        *,
        principal: Principal,
        store_ref: str,
        limit: int = 100,
    ) -> list[CoverageLedgerReceipt]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        context = self._context(principal=principal, store_ref=store_ref)
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    self._scope_query(context)
                    .order_by(
                        GlobalDataCoverageSnapshotRow.data_as_of.desc(),
                        GlobalDataCoverageSnapshotRow.snapshot_id.desc(),
                    )
                    .limit(limit)
                )
            )
            return [
                self._receipt(session, row, context=context, idempotent=True)
                for row in rows
            ]

    def _insert(
        self,
        *,
        context: CoverageLedgerScopeContext,
        idempotency_sha256: str,
        request_sha256: str,
        manifest: dict[str, Any],
        native_caps: dict[str, Any],
        observation: CoverageObservation,
        evidence_records: list[tuple[str, Any]],
    ) -> CoverageLedgerReceipt:
        # A random row identity ensures concurrent retries contend only on the named
        # exact-scope idempotency constraint, never on the primary key.
        snapshot_id = f"gdcs_{uuid4().hex}"
        now = _utc(self.clock(), "clock")
        conservation = manifest["conservation"]
        pages = manifest["coverage"]["pages"]
        fields = manifest["coverage"]["fields"]
        universe = manifest["universe"]
        claim = manifest["coverage_claim"]
        evidence_by_role = {role: evidence for role, evidence in evidence_records}
        row = GlobalDataCoverageSnapshotRow(
            snapshot_id=snapshot_id,
            **_scope_row(context),
            actor_id=context.actor_id,
            data_as_of=context.data_as_of,
            authority_checked_at=context.authority_checked_at,
            source_id=manifest["source"]["source_id"],
            source_family=manifest["source"]["source_family"],
            source_status=manifest["source"]["source_status"],
            source_contract_id=manifest["source"]["source_contract_id"],
            source_contract_version=manifest["source"]["source_contract_version"],
            ledger_contract_id=LEDGER_CONTRACT_ID,
            manifest_ref=manifest["manifest_ref"],
            manifest_version=manifest["manifest_version"],
            manifest_schema_version=manifest["schema_version"],
            manifest_evidence_contract_id=MANIFEST_EVIDENCE_CONTRACT_ID,
            manifest_sha256=manifest["content_sha256"],
            manifest_evidence_id=evidence_by_role["manifest"].id,
            manifest_evidence_sha256=evidence_by_role["manifest"].sha256,
            native_caps_schema=native_caps["schema_version"],
            native_caps_evidence_contract_id=NATIVE_CAPS_EVIDENCE_CONTRACT_ID,
            native_caps_sha256=native_caps["content_sha256"],
            native_caps_evidence_id=evidence_by_role["native_caps"].id,
            native_caps_evidence_sha256=evidence_by_role["native_caps"].sha256,
            registry_contract_id=self.registry_snapshot["contract_id"],
            registry_schema_version=self.registry_snapshot["schema_version"],
            registry_as_of=self.registry_snapshot["as_of"],
            registry_sha256=self.registry_snapshot["content_sha256"],
            observation_contract_id=observation.contract_id,
            observation_sha256=observation.observation_sha256,
            observation_status=observation.status,
            completeness=observation.completeness,
            idempotency_sha256=idempotency_sha256,
            request_sha256=request_sha256,
            denominator_known=universe["denominator_known"],
            expected_count=universe["expected_count"],
            denominator_evidence_ref=claim["denominator_evidence_ref"],
            denominator_evidence_sha256=claim["denominator_evidence_sha256"],
            observed_count=conservation["observed_count"],
            accepted_count=conservation["accepted_count"],
            quarantined_count=conservation["quarantined_count"],
            failed_count=conservation["failed_count"],
            duplicate_count=conservation["duplicate_count"],
            suppressed_count=conservation["suppressed_count"],
            source_total=conservation["source_total"],
            page_expected_count=pages["expected_count"],
            page_received_count=pages["received_count"],
            page_failed_count=pages["failed_count"],
            page_duplicate_count=pages["duplicate_count"],
            page_closed=pages["closed"],
            required_field_count=fields["required_count"],
            window_gap_count=len(manifest["coverage"]["window"]["gaps"]),
            window_overlap_count=len(manifest["coverage"]["window"]["overlaps"]),
            window_timezone=manifest["coverage"]["window"]["timezone"],
            window_late_arrival_count=manifest["coverage"]["window"][
                "late_arrival_count"
            ],
            conflict_count=len(manifest["conflicts"]),
            evidence_count=len(evidence_records),
            checkpoint_sha256=manifest["checkpoint"]["sha256"],
            checkpoint_sequence=manifest["checkpoint"]["sequence"],
            checkpoint_closed=manifest["checkpoint"]["closed"],
            freshness_status=manifest["freshness"]["status"],
            captured_at=_timestamp(manifest["captured_at"], "captured_at"),
            recorded_at=_timestamp(manifest["recorded_at"], "recorded_at"),
            fresh_until=_timestamp(manifest["freshness"]["fresh_until"], "fresh_until"),
            review_due=_timestamp(manifest["freshness"]["review_due"], "review_due"),
            full_coverage_claim=observation.full_coverage_claim,
            formal_fact=False,
            decision=False,
            approval=False,
            permit=False,
            pilot=False,
            outbox=False,
            external_write=False,
            created_at=now,
        )
        if self.engine.dialect.name == "sqlite":
            # SQLite is a deterministic unit-test adapter; production PostgreSQL
            # obtains the real transaction lineage from txid_current().
            row.transaction_stamp = 1
        with self.evidence.transaction() as session:
            session.add(row)
            session.flush()
            self._insert_caps(session, row, native_caps, now)
            self._insert_fields(session, row, fields, now)
            self._insert_failed_pages(session, row, pages, now)
            self._insert_windows(session, row, manifest["coverage"]["window"], now)
            self._insert_conflicts(session, row, manifest["conflicts"], now)
            self._insert_evidence_links(session, row, evidence_records, manifest, now)
            self._append_event(session, row, "snapshot_started", "coverage_validation_passed")
            self._append_event(session, row, "snapshot_committed", "coverage_snapshot_committed")
            session.flush()
            return self._receipt(session, row, context=context, idempotent=False)

    def _insert_caps(self, session, row, native_caps, now) -> None:
        capabilities = native_caps["capabilities"]
        session.add(
            GlobalDataCoverageNativeCapsRow(
                caps_id=_stable_id("gdcc", {"snapshot_id": row.snapshot_id}),
                snapshot_id=row.snapshot_id,
                **_scope_from_snapshot(row),
                schema_version=native_caps["schema_version"],
                source_id=native_caps["source_id"],
                source_family=native_caps["source_family"],
                adapter_id=native_caps["adapter_id"],
                adapter_version=native_caps["adapter_version"],
                capability_version=native_caps["capability_version"],
                content_sha256=native_caps["content_sha256"],
                universe_kind=native_caps["universe_kind"],
                pagination_mode=capabilities["pagination"]["mode"],
                page_limit=capabilities["pagination"]["page_limit"],
                historical_depth_days=capabilities["window"]["historical_depth_days"],
                rate_limit_known=capabilities["rate_limit"]["known"],
                authentication_mode=capabilities["authentication_mode"],
                created_at=now,
            )
        )

    def _insert_fields(self, session, row, fields, now) -> None:
        ordinal = 0
        for status in ("present", "missing", "unparseable", "conflicting"):
            for field_name in fields[status]:
                ordinal += 1
                session.add(
                    GlobalDataCoverageFieldRow(
                        field_id=_stable_id(
                            "gdcf", {"snapshot_id": row.snapshot_id, "field": field_name}
                        ),
                        snapshot_id=row.snapshot_id,
                        **_scope_from_snapshot(row),
                        ordinal=ordinal,
                        field_name=field_name,
                        field_name_sha256=_sha256_text(field_name),
                        field_status=status,
                        created_at=now,
                    )
                )

    def _insert_failed_pages(self, session, row, pages, now) -> None:
        for ordinal, failed_ref in enumerate(pages["failed_refs"], start=1):
            digest = _sha256_text(failed_ref)
            session.add(
                GlobalDataCoverageFailedPageRow(
                    failed_page_id=_stable_id(
                        "gdcp", {"snapshot_id": row.snapshot_id, "failed_ref": digest}
                    ),
                    snapshot_id=row.snapshot_id,
                    **_scope_from_snapshot(row),
                    ordinal=ordinal,
                    failed_ref_sha256=digest,
                    reason_code="source_page_failed",
                    created_at=now,
                )
            )

    def _insert_windows(self, session, row, window, now) -> None:
        segments = [
            ("requested", 1, window["requested_start"], window["requested_end"], None),
            ("effective", 1, window["effective_start"], window["effective_end"], None),
        ]
        for kind in ("gaps", "overlaps"):
            segment_kind = "gap" if kind == "gaps" else "overlap"
            for ordinal, item in enumerate(window[kind], start=1):
                segments.append(
                    (segment_kind, ordinal, item["start"], item["end"], item["reason_code"])
                )
        for segment_kind, ordinal, start, end, reason in segments:
            session.add(
                GlobalDataCoverageWindowRow(
                    window_id=_stable_id(
                        "gdcw",
                        {
                            "snapshot_id": row.snapshot_id,
                            "kind": segment_kind,
                            "ordinal": ordinal,
                        },
                    ),
                    snapshot_id=row.snapshot_id,
                    **_scope_from_snapshot(row),
                    segment_kind=segment_kind,
                    ordinal=ordinal,
                    start_at=_timestamp(start, "window.start"),
                    end_at=_timestamp(end, "window.end"),
                    reason_code=reason,
                    created_at=now,
                )
            )

    def _insert_conflicts(self, session, row, conflicts, now) -> None:
        for ordinal, item in enumerate(conflicts, start=1):
            ref_sha256 = _sha256_text(item["conflict_ref"])
            session.add(
                GlobalDataCoverageConflictRow(
                    conflict_id=_stable_id(
                        "gdcx", {"snapshot_id": row.snapshot_id, "ref": ref_sha256}
                    ),
                    snapshot_id=row.snapshot_id,
                    **_scope_from_snapshot(row),
                    ordinal=ordinal,
                    conflict_ref_sha256=ref_sha256,
                    subject_ref_sha256=item["subject_ref_sha256"],
                    field_name_sha256=_sha256_text(item["field"]),
                    valid_interval_sha256=item["valid_interval_sha256"],
                    value_hash_count=len(item["value_hashes"]),
                    value_hashes_sha256=_sha256(item["value_hashes"]),
                    resolution_status=item["resolution_status"],
                    created_at=now,
                )
            )

    def _insert_evidence_links(self, session, row, records, manifest, now) -> None:
        denominator_ref = manifest["coverage_claim"]["denominator_evidence_ref"]
        declarations = {item["id"]: item for item in manifest["evidence_refs"]}
        for ordinal, (declared_role, evidence) in enumerate(records, start=1):
            evidence_role = declared_role
            if evidence.id == denominator_ref:
                evidence_role = "denominator"
            session.add(
                GlobalDataCoverageEvidenceLinkRow(
                    link_id=_stable_id(
                        "gdcl", {"snapshot_id": row.snapshot_id, "evidence_id": evidence.id}
                    ),
                    snapshot_id=row.snapshot_id,
                    **_scope_from_snapshot(row),
                    ordinal=ordinal,
                    evidence_role=evidence_role,
                    evidence_id=evidence.id,
                    evidence_sha256=evidence.sha256,
                    evidence_source=evidence.source,
                    evidence_source_ref=evidence.source_ref,
                    evidence_grade=evidence.grade.value,
                    evidence_effective_at=_stored_timestamp(evidence.effective_at, "evidence.effective_at"),
                    evidence_effective_until=_optional_stored_timestamp(
                        evidence.effective_until, "evidence.effective_until"
                    ),
                    evidence_declared_recorded_at=(
                        _timestamp(
                            declarations[evidence.id]["recorded_at"],
                            "evidence.declared_recorded_at",
                        )
                        if evidence.id in declarations
                        else None
                    ),
                    intake_issuance_sha256=evidence.metadata.get(
                        "coverage_intake_issuance_sha256"
                    ),
                    intake_issuance_signature_sha256=evidence.metadata.get(
                        "coverage_intake_issuance_signature_sha256"
                    ),
                    scope_authority_contract_id=evidence.metadata.get(
                        "_coverage_scope_authority_contract_id"
                    ),
                    scope_binding_evidence_id=evidence.metadata.get(
                        "_coverage_scope_binding_evidence_id"
                    ),
                    scope_binding_evidence_sha256=evidence.metadata.get(
                        "_coverage_scope_binding_evidence_sha256"
                    ),
                    created_at=now,
                )
            )

    def _append_event(self, session, row, event_type: str, reason_code: str) -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError("coverage ledger event type is invalid")
        existing = list(
            session.scalars(
                select(GlobalDataCoverageEventRow)
                .where(GlobalDataCoverageEventRow.snapshot_id == row.snapshot_id)
                .order_by(GlobalDataCoverageEventRow.event_index)
                .with_for_update()
            )
        )
        if existing and existing[-1].event_type in TERMINAL_EVENTS:
            raise CoverageLedgerConflictError("coverage snapshot is already terminal")
        if not existing and event_type != "snapshot_started":
            raise CoverageLedgerConflictError("coverage snapshot must start first")
        if existing and event_type == "snapshot_started":
            raise CoverageLedgerConflictError("coverage snapshot already started")
        event_index = len(existing) + 1
        previous = existing[-1].event_sha256 if existing else ZERO_SHA256
        occurred_at = _utc(self.clock(), "event clock")
        occurred_at_text = occurred_at.isoformat(timespec="microseconds")
        event_payload = {
            "contract_id": LEDGER_EVIDENCE_CONTRACT_ID,
            "snapshot_id": row.snapshot_id,
            "event_index": event_index,
            "event_type": event_type,
            "reason_code": reason_code,
            "previous_event_sha256": previous,
            "request_sha256": row.request_sha256,
            "observation_sha256": row.observation_sha256,
            "occurred_at": occurred_at_text,
        }
        event_sha256 = _coverage_event_sha256(
            snapshot_id=row.snapshot_id,
            event_index=event_index,
            event_type=event_type,
            reason_code=reason_code,
            previous_event_sha256=previous,
            request_sha256=row.request_sha256,
            observation_sha256=row.observation_sha256,
            occurred_at=occurred_at,
        )
        event_id = _stable_id(
            "gdce", {"snapshot_id": row.snapshot_id, "event_sha256": event_sha256}
        )
        source_ref = f"coverage-ledger://{row.snapshot_id}/{event_id}"
        evidence = self.evidence.capture_global_data_coverage_ledger_event(
            content=canonical_json(
                {
                    **event_payload,
                    "event_sha256": event_sha256,
                    "payload_status": "hash_and_code_only",
                    "formal_fact": False,
                    "external_write": False,
                }
            ),
            source_ref=source_ref,
            effective_at=_iso(occurred_at),
            metadata={
                "contract_id": LEDGER_EVIDENCE_CONTRACT_ID,
                **_scope_from_snapshot(row),
                "snapshot_id": row.snapshot_id,
                "event_id": event_id,
                "event_type": event_type,
                "event_sha256": event_sha256,
                "request_sha256": row.request_sha256,
                "observation_sha256": row.observation_sha256,
                "occurred_at": occurred_at_text,
                "retention_class": "compliance",
                "legal_hold": False,
            },
            session=session,
        )
        session.add(
            GlobalDataCoverageEventRow(
                event_id=event_id,
                snapshot_id=row.snapshot_id,
                **_scope_from_snapshot(row),
                event_index=event_index,
                event_type=event_type,
                reason_code=reason_code,
                previous_event_sha256=previous,
                event_sha256=event_sha256,
                evidence_id=evidence.id,
                evidence_sha256=evidence.sha256,
                evidence_source=evidence.source,
                evidence_source_ref=evidence.source_ref,
                evidence_grade=evidence.grade.value,
                evidence_effective_at=_stored_timestamp(evidence.effective_at, "event.effective_at"),
                occurred_at=occurred_at,
                recorded_at=_stored_timestamp(evidence.recorded_at, "event.recorded_at"),
            )
        )
        session.flush()

    def _input_evidence(
        self,
        manifest: dict[str, Any],
        context: CoverageLedgerScopeContext,
        principal: Principal,
    ) -> list[tuple[str, Any]]:
        declared = manifest["evidence_refs"]
        ids = [item["id"] for item in declared]
        self.evidence.require_current(ids, as_of=context.authority_checked_at)
        records = [self.evidence.get_metadata(item) for item in ids]
        denominator_ref = manifest["coverage_claim"]["denominator_evidence_ref"]
        supporting_ids = [item for item in ids if item != denominator_ref]
        scoped_records: dict[str, dict[str, Any]] = {}
        if supporting_ids:
            projection = self.scoped_evidence_authority.project_targets(
                evidence_ids=supporting_ids,
                principal=principal,
                entity_scope={"status": "ready", "entity_ref": context.entity_ref},
                store_ref=context.store_ref,
                as_of=context.authority_checked_at,
            )
            scoped_records = {
                item["evidence_id"]: item
                for item in projection.get("records", [])
                if item.get("evidence_id") in supporting_ids
            }
            if projection.get("status") != "ready" or set(scoped_records) != set(
                supporting_ids
            ):
                raise CoverageLedgerConflictError(
                    "supporting Evidence scope authority is incomplete"
                )
        denominator_count = 0
        projected: list[tuple[str, Any]] = []
        for declaration, record in zip(declared, records, strict=True):
            is_reserved_denominator = record.source == DENOMINATOR_EVIDENCE_SOURCE
            declared_effective_at = _timestamp(
                declaration["effective_at"], "evidence.effective_at"
            )
            declared_recorded_at = _timestamp(
                declaration["recorded_at"], "evidence.recorded_at"
            )
            declared_until = _optional_timestamp(
                declaration.get("effective_until"), "evidence.effective_until"
            )
            expected_declared_effective_at = _stored_timestamp(
                record.effective_at, "stored.effective_at"
            )
            expected_declared_recorded_at = _stored_timestamp(
                record.recorded_at, "stored.recorded_at"
            )
            expected_declared_until = _optional_stored_timestamp(
                record.effective_until, "stored.effective_until"
            )
            if is_reserved_denominator:
                expected_declared_effective_at = _timestamp(
                    record.metadata.get("coverage_intake_upstream_effective_at"),
                    "coverage_intake_upstream_effective_at",
                )
                expected_declared_recorded_at = _timestamp(
                    record.metadata.get("coverage_intake_upstream_recorded_at"),
                    "coverage_intake_upstream_recorded_at",
                )
                expected_declared_until = _optional_timestamp(
                    record.metadata.get("coverage_intake_upstream_effective_until"),
                    "coverage_intake_upstream_effective_until",
                )
            if (
                not hmac.compare_digest(declaration["sha256"], record.sha256)
                or declaration["grade"] != record.grade.value
                or declared_effective_at != expected_declared_effective_at
                or declared_recorded_at != expected_declared_recorded_at
                or declared_until != expected_declared_until
            ):
                raise CoverageLedgerConflictError("manifest Evidence binding drift")
            expected_scope = {
                "tenant_ref": context.tenant_ref,
                "entity_ref": context.entity_ref,
                "store_ref": context.store_ref,
                "scope_grant_authority_sha256": context.scope_grant_authority_sha256,
            }
            effective_at = _stored_timestamp(record.effective_at, "stored.effective_at")
            recorded_at = _stored_timestamp(record.recorded_at, "stored.recorded_at")
            if effective_at > recorded_at or recorded_at > context.authority_checked_at:
                raise CoverageLedgerConflictError("manifest Evidence chronology is invalid")
            role = "supporting"
            if record.id == denominator_ref:
                denominator_count += 1
                role = "denominator"
                if any(
                    record.metadata.get(key) != value
                    for key, value in expected_scope.items()
                ):
                    raise CoverageLedgerConflictError(
                        "denominator Evidence exact scope mismatch"
                    )
                self._verify_denominator_evidence(manifest, record, context)
            else:
                if recorded_at > context.data_as_of:
                    raise CoverageLedgerConflictError("supporting Evidence is hindsight data")
                scoped = scoped_records[record.id]
                binding = scoped.get("scope_binding") or {}
                authority = binding.get("authority")
                if (
                    scoped.get("sha256") != record.sha256
                    or binding.get("status") != "ready"
                    or authority not in {DIRECT_CONTRACT, BINDING_CONTRACT}
                ):
                    raise CoverageLedgerConflictError(
                        "supporting Evidence scope authority drifted"
                    )
                binding_id = binding.get("binding_evidence_id")
                binding_record = (
                    self.evidence.get_metadata(binding_id) if binding_id else None
                )
                authority_metadata = (
                    binding_record.metadata if binding_record is not None else record.metadata
                )
                if any(
                    authority_metadata.get(key) != value
                    for key, value in expected_scope.items()
                ):
                    raise CoverageLedgerConflictError(
                        "supporting Evidence current authority mismatch"
                    )
                record = replace(
                    record,
                    metadata={
                        **record.metadata,
                        "_coverage_scope_authority_contract_id": authority,
                        "_coverage_scope_binding_evidence_id": binding_id,
                        "_coverage_scope_binding_evidence_sha256": (
                            binding_record.sha256 if binding_record is not None else None
                        ),
                    },
                )
            projected.append((role, record))
        expected_denominator_count = 1 if manifest["universe"]["denominator_known"] else 0
        if denominator_count != expected_denominator_count:
            raise CoverageLedgerConflictError("denominator Evidence binding is incomplete")
        return projected

    def _contract_evidence(
        self,
        *,
        evidence_id: str,
        source: str,
        contract_id: str,
        schema_version: str,
        context: CoverageLedgerScopeContext,
    ) -> tuple[dict[str, Any], Any]:
        identifier = _required(evidence_id, "evidence_id")
        self.evidence.require_current([identifier], as_of=context.authority_checked_at)
        content, record = self.evidence.content(identifier)
        if not self.evidence.verify(identifier).valid:
            raise CoverageLedgerConflictError("coverage contract Evidence integrity failed")
        expected_scope = {
            "tenant_ref": context.tenant_ref,
            "entity_ref": context.entity_ref,
            "store_ref": context.store_ref,
            "scope_grant_authority_sha256": context.scope_grant_authority_sha256,
        }
        purpose = {
            MANIFEST_EVIDENCE_SOURCE: "manifest",
            NATIVE_CAPS_EVIDENCE_SOURCE: "native_caps",
        }.get(source)
        expected_issuance = _coverage_intake_issuance_sha256(
            purpose=purpose or "",
            source=source,
            contract_id=contract_id,
            schema_version=schema_version,
            content_sha256=record.sha256,
            context=context,
            source_contract_id=record.metadata.get("coverage_intake_source_contract_id"),
            source_contract_version=record.metadata.get(
                "coverage_intake_source_contract_version"
            ),
            attestation_contract_id=record.metadata.get(
                "coverage_intake_attestation_contract_id"
            ),
            attestation_contract_version=record.metadata.get(
                "coverage_intake_attestation_contract_version"
            ),
            attestation_sha256=record.metadata.get("coverage_intake_attestation_sha256"),
            issuer_ref_sha256=record.metadata.get("coverage_intake_issuer_ref_sha256"),
            upstream_effective_at=record.metadata.get(
                "coverage_intake_upstream_effective_at"
            ),
            upstream_recorded_at=record.metadata.get(
                "coverage_intake_upstream_recorded_at"
            ),
            upstream_effective_until=record.metadata.get(
                "coverage_intake_upstream_effective_until"
            ),
        )
        if (
            record.source != source
            or record.source_ref
            != (
                f"{source}://{context.scope_grant_authority_sha256}/{record.sha256}/"
                f"{record.metadata.get('coverage_intake_issuance_sha256')}"
            )
            or record.grade not in {EvidenceGrade.A, EvidenceGrade.B}
            or record.content_type != "application/json"
            or record.metadata.get("contract_id") != contract_id
            or record.metadata.get("schema_version") != schema_version
            or record.metadata.get("coverage_intake_purpose") != purpose
            or record.metadata.get("coverage_intake_issuance_sha256")
            != expected_issuance
            or not _is_hex64(
                record.metadata.get("coverage_intake_issuance_signature_sha256")
            )
            or not _is_hex64(record.metadata.get("coverage_intake_attestation_sha256"))
            or not _is_hex64(record.metadata.get("coverage_intake_issuer_ref_sha256"))
            or any(record.metadata.get(key) != value for key, value in expected_scope.items())
        ):
            raise CoverageLedgerConflictError("coverage contract Evidence authority mismatch")
        effective_at = _stored_timestamp(record.effective_at, "contract.effective_at")
        recorded_at = _stored_timestamp(record.recorded_at, "contract.recorded_at")
        upstream_effective_at = _timestamp(
            record.metadata.get("coverage_intake_upstream_effective_at"),
            "coverage_intake_upstream_effective_at",
        )
        upstream_recorded_at = _timestamp(
            record.metadata.get("coverage_intake_upstream_recorded_at"),
            "coverage_intake_upstream_recorded_at",
        )
        upstream_until_raw = record.metadata.get(
            "coverage_intake_upstream_effective_until"
        )
        upstream_effective_until = (
            _timestamp(upstream_until_raw, "coverage_intake_upstream_effective_until")
            if upstream_until_raw
            else None
        )
        if (
            effective_at > recorded_at
            or recorded_at > context.authority_checked_at
            or upstream_effective_at > upstream_recorded_at
            or upstream_recorded_at > context.data_as_of
            or _optional_stored_timestamp(
                record.effective_until, "contract.effective_until"
            )
            != upstream_effective_until
            or (
                upstream_effective_until is not None
                and context.authority_checked_at >= upstream_effective_until
            )
        ):
            raise CoverageLedgerConflictError("coverage contract Evidence chronology is invalid")
        payload = _strict_json_object(content, "coverage contract Evidence")
        if canonical_json(payload) != content:
            raise CoverageLedgerConflictError("coverage contract Evidence is not canonical JSON")
        if payload.get("schema_version") != schema_version:
            raise CoverageLedgerConflictError("coverage contract schema version mismatch")
        payload_sha256 = _sha256(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
        if (
            payload.get("content_sha256") != payload_sha256
            or record.metadata.get("payload_content_sha256") != payload_sha256
        ):
            raise CoverageLedgerConflictError("coverage contract content hash mismatch")
        return payload, record

    def _verify_denominator_evidence(
        self,
        manifest: dict[str, Any],
        record: Any,
        context: CoverageLedgerScopeContext,
    ) -> None:
        if (
            record.source != DENOMINATOR_EVIDENCE_SOURCE
            or record.source_ref
            != (
                f"{DENOMINATOR_EVIDENCE_SOURCE}://"
                f"{context.scope_grant_authority_sha256}/{record.sha256}/"
                f"{record.metadata.get('coverage_intake_issuance_sha256')}"
            )
            or record.grade not in {EvidenceGrade.A, EvidenceGrade.B}
            or record.content_type != "application/json"
            or record.metadata.get("contract_id") != DENOMINATOR_EVIDENCE_CONTRACT_ID
            or record.metadata.get("schema_version") != DENOMINATOR_SCHEMA_VERSION
            or record.metadata.get("coverage_intake_purpose") != "denominator"
            or record.metadata.get("coverage_intake_issuance_sha256")
            != _coverage_intake_issuance_sha256(
                purpose="denominator",
                source=DENOMINATOR_EVIDENCE_SOURCE,
                contract_id=DENOMINATOR_EVIDENCE_CONTRACT_ID,
                schema_version=DENOMINATOR_SCHEMA_VERSION,
                content_sha256=record.sha256,
                context=context,
                source_contract_id=record.metadata.get(
                    "coverage_intake_source_contract_id"
                ),
                source_contract_version=record.metadata.get(
                    "coverage_intake_source_contract_version"
                ),
                attestation_contract_id=record.metadata.get(
                    "coverage_intake_attestation_contract_id"
                ),
                attestation_contract_version=record.metadata.get(
                    "coverage_intake_attestation_contract_version"
                ),
                attestation_sha256=record.metadata.get(
                    "coverage_intake_attestation_sha256"
                ),
                issuer_ref_sha256=record.metadata.get(
                    "coverage_intake_issuer_ref_sha256"
                ),
                upstream_effective_at=record.metadata.get(
                    "coverage_intake_upstream_effective_at"
                ),
                upstream_recorded_at=record.metadata.get(
                    "coverage_intake_upstream_recorded_at"
                ),
                upstream_effective_until=record.metadata.get(
                    "coverage_intake_upstream_effective_until"
                ),
            )
            or not _is_hex64(
                record.metadata.get("coverage_intake_issuance_signature_sha256")
            )
            or record.metadata.get("coverage_intake_source_contract_id")
            != manifest["source"]["source_contract_id"]
            or record.metadata.get("coverage_intake_source_contract_version")
            != manifest["source"]["source_contract_version"]
        ):
            raise CoverageLedgerConflictError("denominator Evidence authority mismatch")
        upstream_effective_at = _timestamp(
            record.metadata.get("coverage_intake_upstream_effective_at"),
            "denominator.upstream_effective_at",
        )
        upstream_recorded_at = _timestamp(
            record.metadata.get("coverage_intake_upstream_recorded_at"),
            "denominator.upstream_recorded_at",
        )
        upstream_until_raw = record.metadata.get(
            "coverage_intake_upstream_effective_until"
        )
        upstream_effective_until = (
            _timestamp(upstream_until_raw, "denominator.upstream_effective_until")
            if upstream_until_raw
            else None
        )
        if (
            upstream_effective_at > upstream_recorded_at
            or upstream_recorded_at > context.data_as_of
            or upstream_effective_at > context.data_as_of
            or _optional_stored_timestamp(
                record.effective_until, "denominator.effective_until"
            )
            != upstream_effective_until
            or (
                upstream_effective_until is not None
                and context.data_as_of >= upstream_effective_until
            )
        ):
            raise CoverageLedgerConflictError("denominator Evidence chronology is invalid")
        content, _ = self.evidence.content(record.id)
        payload = _strict_json_object(content, "denominator Evidence")
        if canonical_json(payload) != content:
            raise CoverageLedgerConflictError("denominator Evidence is not canonical JSON")
        expected = {
            "contract_id": DENOMINATOR_EVIDENCE_CONTRACT_ID,
            "schema_version": DENOMINATOR_SCHEMA_VERSION,
            "source_id": manifest["source"]["source_id"],
            "source_family": manifest["source"]["source_family"],
            "universe_kind": manifest["universe"]["kind"],
            "expected_count": manifest["universe"]["expected_count"],
            "manifest_ref": manifest["manifest_ref"],
            "manifest_version": manifest["manifest_version"],
            "data_as_of": _iso(context.data_as_of),
            "window_start": manifest["coverage"]["window"]["requested_start"],
            "window_end": manifest["coverage"]["window"]["requested_end"],
            "partition_sha256": _sha256(
                {
                    "scope": manifest["scope"],
                    "query_bounds": manifest["universe"]["query_bounds"],
                    "source_id": manifest["source"]["source_id"],
                }
            ),
        }
        if payload != expected:
            raise CoverageLedgerConflictError("denominator Evidence claim mismatch")

    def _context(
        self,
        *,
        principal: Principal,
        store_ref: str,
        data_as_of: datetime | None = None,
    ) -> CoverageLedgerScopeContext:
        checked_at = _utc(self.clock(), "clock")
        cutoff = checked_at if data_as_of is None else _utc(data_as_of, "data_as_of")
        if cutoff > checked_at:
            raise ValueError("data_as_of cannot be later than the authority check")
        store = _required(store_ref, "store_ref")
        authority = self.scope_grants.current(
            principal=principal,
            store_ref=store,
            as_of=checked_at,
        )
        if authority.get("status") != "ready":
            raise PermissionError("exact scope authority is not ready")
        tenant_ref = _required(principal.tenant_ref, "principal.tenant_ref")
        entity_ref = _required(authority.get("entity_ref"), "authority.entity_ref")
        authority_store = _required(authority.get("store_ref"), "authority.store_ref")
        authority_tenant = _required(authority.get("tenant_ref"), "authority.tenant_ref")
        authority_sha256 = _required(
            authority.get("authority_sha256"), "authority.authority_sha256"
        )
        if (
            authority_tenant != tenant_ref
            or authority_store != store
            or not principal.can_access_store(store)
            or HEX64.fullmatch(authority_sha256) is None
        ):
            raise PermissionError("exact scope authority binding is invalid")
        return CoverageLedgerScopeContext(
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store,
            scope_grant_authority_sha256=authority_sha256,
            actor_id=_required(principal.actor_id, "principal.actor_id"),
            data_as_of=cutoff,
            authority_checked_at=checked_at,
        )

    def _winner(
        self, context: CoverageLedgerScopeContext, idempotency_sha256: str
    ) -> GlobalDataCoverageSnapshotRow | None:
        with Session(self.engine) as session:
            return session.scalar(
                select(GlobalDataCoverageSnapshotRow).where(
                    GlobalDataCoverageSnapshotRow.tenant_ref == context.tenant_ref,
                    GlobalDataCoverageSnapshotRow.entity_ref == context.entity_ref,
                    GlobalDataCoverageSnapshotRow.store_ref == context.store_ref,
                    GlobalDataCoverageSnapshotRow.scope_grant_authority_sha256
                    == context.scope_grant_authority_sha256,
                    GlobalDataCoverageSnapshotRow.idempotency_sha256
                    == idempotency_sha256,
                )
            )

    def _replay_winner(
        self,
        row: GlobalDataCoverageSnapshotRow,
        context: CoverageLedgerScopeContext,
        request_sha256: str,
    ) -> CoverageLedgerReceipt:
        if (
            row.scope_grant_authority_sha256 != context.scope_grant_authority_sha256
            or not hmac.compare_digest(row.request_sha256, request_sha256)
        ):
            raise CoverageLedgerConflictError(
                "idempotency key authority, payload, hash, or version drift"
            )
        with Session(self.engine) as session:
            attached = session.get(GlobalDataCoverageSnapshotRow, row.snapshot_id)
            if attached is None:
                raise CoverageLedgerConflictError("idempotency winner is unavailable")
            return self._receipt(session, attached, context=context, idempotent=True)

    def _receipt(
        self,
        session: Session,
        row: GlobalDataCoverageSnapshotRow,
        *,
        context: CoverageLedgerScopeContext,
        idempotent: bool,
    ) -> CoverageLedgerReceipt:
        events = list(
            session.scalars(
                select(GlobalDataCoverageEventRow)
                .where(GlobalDataCoverageEventRow.snapshot_id == row.snapshot_id)
                .order_by(GlobalDataCoverageEventRow.event_index)
            )
        )
        self._verify_events(events, row, session=session)
        links = list(
            session.scalars(
                select(GlobalDataCoverageEvidenceLinkRow)
                .where(GlobalDataCoverageEvidenceLinkRow.snapshot_id == row.snapshot_id)
                .order_by(GlobalDataCoverageEvidenceLinkRow.ordinal)
            )
        )
        if len(links) != row.evidence_count:
            raise CoverageLedgerConflictError("coverage Evidence conservation failed")
        self.evidence.require_current_in_session(
            [item.evidence_id for item in links],
            as_of=context.authority_checked_at,
            session=session,
        )
        for link in links:
            record = self.evidence.get_metadata_in_session(
                link.evidence_id, session=session
            )
            if (
                record.sha256 != link.evidence_sha256
                or record.source != link.evidence_source
                or record.source_ref != link.evidence_source_ref
                or record.grade.value != link.evidence_grade
            ):
                raise CoverageLedgerConflictError("coverage Evidence link integrity failed")
        last_event = events[-1]
        status = {
            "snapshot_committed": row.observation_status,
            "unknown_outcome": "unknown_outcome",
            "invalidated": "invalidated",
        }.get(last_event.event_type, "in_progress")
        freshness_deadline = min(
            _stored_timestamp(row.fresh_until, "fresh_until"),
            _stored_timestamp(row.review_due, "review_due"),
        )
        currentness = (
            "current"
            if row.freshness_status == "fresh"
            and context.authority_checked_at < freshness_deadline
            else "stale"
        )
        receipt = CoverageLedgerReceipt(
            contract_id=LEDGER_CONTRACT_ID,
            snapshot_id=row.snapshot_id,
            status=status,
            source_id=row.source_id,
            source_family=row.source_family,
            manifest_ref=row.manifest_ref,
            manifest_sha256=row.manifest_sha256,
            native_caps_sha256=row.native_caps_sha256,
            registry_sha256=row.registry_sha256,
            observation_sha256=row.observation_sha256,
            request_sha256=row.request_sha256,
            event_chain_sha256=last_event.event_sha256,
            event_count=len(events),
            idempotent=idempotent,
            currentness=currentness,
            full_coverage_claim=(
                row.full_coverage_claim
                and currentness == "current"
                and last_event.event_type == "snapshot_committed"
            ),
        )
        return replace(receipt, receipt_sha256=_sha256(receipt.to_dict()))

    def _verify_events(
        self,
        events: list[GlobalDataCoverageEventRow],
        snapshot: GlobalDataCoverageSnapshotRow,
        *,
        session: Session,
    ) -> None:
        if not events:
            raise CoverageLedgerConflictError("coverage event chain is missing")
        previous = ZERO_SHA256
        terminal_seen = False
        for expected_index, event in enumerate(events, start=1):
            if terminal_seen or event.event_index != expected_index:
                raise CoverageLedgerConflictError("coverage event ordinal is invalid")
            if event.event_type not in EVENT_TYPES or event.previous_event_sha256 != previous:
                raise CoverageLedgerConflictError("coverage event transition is invalid")
            expected_sha256 = _coverage_event_sha256(
                snapshot_id=event.snapshot_id,
                event_index=event.event_index,
                event_type=event.event_type,
                reason_code=event.reason_code,
                previous_event_sha256=event.previous_event_sha256,
                request_sha256=snapshot.request_sha256,
                observation_sha256=snapshot.observation_sha256,
                occurred_at=_stored_timestamp(event.occurred_at, "event.occurred_at"),
            )
            if not hmac.compare_digest(expected_sha256, event.event_sha256):
                raise CoverageLedgerConflictError("coverage event hash chain is invalid")
            self.evidence.require_current_in_session(
                [event.evidence_id],
                as_of=_stored_timestamp(event.recorded_at, "event.recorded_at"),
                session=session,
            )
            evidence = self.evidence.get_metadata_in_session(
                event.evidence_id, session=session
            )
            expected_metadata = {
                "snapshot_id": event.snapshot_id,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "event_sha256": event.event_sha256,
                "request_sha256": snapshot.request_sha256,
                "observation_sha256": snapshot.observation_sha256,
                "occurred_at": _stored_timestamp(
                    event.occurred_at, "event.occurred_at"
                ).isoformat(timespec="microseconds"),
                **_scope_from_event(event),
            }
            if (
                evidence.sha256 != event.evidence_sha256
                or evidence.source != LEDGER_EVIDENCE_SOURCE
                or evidence.source_ref != event.evidence_source_ref
                or evidence.grade.value != event.evidence_grade
                or any(evidence.metadata.get(key) != value for key, value in expected_metadata.items())
            ):
                raise CoverageLedgerConflictError("coverage event Evidence integrity failed")
            previous = event.event_sha256
            terminal_seen = event.event_type in TERMINAL_EVENTS
        if events[0].event_type != "snapshot_started":
            raise CoverageLedgerConflictError("coverage event chain must start explicitly")

    @staticmethod
    def _scope_query(context: CoverageLedgerScopeContext):
        return select(GlobalDataCoverageSnapshotRow).where(
            GlobalDataCoverageSnapshotRow.tenant_ref == context.tenant_ref,
            GlobalDataCoverageSnapshotRow.entity_ref == context.entity_ref,
            GlobalDataCoverageSnapshotRow.store_ref == context.store_ref,
            GlobalDataCoverageSnapshotRow.scope_grant_authority_sha256
            == context.scope_grant_authority_sha256,
        )


def _scope_dict(context: CoverageLedgerScopeContext) -> dict[str, Any]:
    return {
        "tenant_ref": context.tenant_ref,
        "entity_ref": context.entity_ref,
        "store_ref": context.store_ref,
        "scope_grant_authority_sha256": context.scope_grant_authority_sha256,
        "actor_id": context.actor_id,
        "data_as_of": _iso(context.data_as_of),
    }


def _scope_row(context: CoverageLedgerScopeContext) -> dict[str, str]:
    return {
        "tenant_ref": context.tenant_ref,
        "entity_ref": context.entity_ref,
        "store_ref": context.store_ref,
        "scope_grant_authority_sha256": context.scope_grant_authority_sha256,
    }


def _scope_from_snapshot(row: GlobalDataCoverageSnapshotRow) -> dict[str, str]:
    return {
        "tenant_ref": row.tenant_ref,
        "entity_ref": row.entity_ref,
        "store_ref": row.store_ref,
        "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
        "transaction_stamp": row.transaction_stamp,
    }


def _scope_from_event(row: GlobalDataCoverageEventRow) -> dict[str, str]:
    return {
        "tenant_ref": row.tenant_ref,
        "entity_ref": row.entity_ref,
        "store_ref": row.store_ref,
        "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
        "transaction_stamp": row.transaction_stamp,
    }


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{_sha256(value)[:32]}"


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _strict_json_object(content: bytes, field: str) -> dict[str, Any]:
    def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise CoverageLedgerConflictError(f"{field} contains duplicate keys")
            result[key] = value
        return result

    try:
        parsed = json.loads(content.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageLedgerConflictError(f"{field} must be canonical JSON") from exc
    if not isinstance(parsed, dict):
        raise CoverageLedgerConflictError(f"{field} must contain a JSON object")
    return parsed


def _coverage_intake_issuance_sha256(
    *,
    purpose: str,
    source: str,
    contract_id: str,
    schema_version: str,
    content_sha256: str,
    context: CoverageLedgerScopeContext,
    source_contract_id: Any,
    source_contract_version: Any,
    attestation_contract_id: Any,
    attestation_contract_version: Any,
    attestation_sha256: Any,
    issuer_ref_sha256: Any,
    upstream_effective_at: Any,
    upstream_recorded_at: Any,
    upstream_effective_until: Any,
) -> str:
    return _sha256(
        {
            "purpose": purpose,
            "source": source,
            "contract_id": contract_id,
            "schema_version": schema_version,
            "content_sha256": content_sha256,
            "source_contract_id": source_contract_id,
            "source_contract_version": source_contract_version,
            "attestation_contract_id": attestation_contract_id,
            "attestation_contract_version": attestation_contract_version,
            "attestation_sha256": attestation_sha256,
            "issuer_ref_sha256": issuer_ref_sha256,
            "upstream_effective_at": upstream_effective_at,
            "upstream_recorded_at": upstream_recorded_at,
            "upstream_effective_until": upstream_effective_until,
            "scope": {
                "tenant_ref": context.tenant_ref,
                "entity_ref": context.entity_ref,
                "store_ref": context.store_ref,
                "scope_grant_authority_sha256": context.scope_grant_authority_sha256,
            },
        }
    )


def _coverage_event_sha256(
    *,
    snapshot_id: str,
    event_index: int,
    event_type: str,
    reason_code: str,
    previous_event_sha256: str,
    request_sha256: str,
    observation_sha256: str,
    occurred_at: datetime,
) -> str:
    timestamp = _stored_timestamp(occurred_at, "event.occurred_at").isoformat(
        timespec="microseconds"
    )
    canonical = "\x1f".join(
        (
            LEDGER_EVIDENCE_CONTRACT_ID,
            snapshot_id,
            str(event_index),
            event_type,
            reason_code,
            previous_event_sha256,
            request_sha256,
            observation_sha256,
            timestamp,
        )
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _is_idempotency_conflict(exc: IntegrityError) -> bool:
    original = getattr(exc, "orig", None)
    constraint = getattr(getattr(original, "diag", None), "constraint_name", None)
    if constraint == "uq_gdc_scope_idempotency":
        return True
    message = str(original)
    sqlite_columns = (
        "UNIQUE constraint failed: global_data_coverage_snapshots.tenant_ref, "
        "global_data_coverage_snapshots.entity_ref, "
        "global_data_coverage_snapshots.store_ref, "
        "global_data_coverage_snapshots.scope_grant_authority_sha256, "
        "global_data_coverage_snapshots.idempotency_sha256"
    )
    return sqlite_columns in message


def _required(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 240:
        raise ValueError(f"{field} is required and must be at most 240 characters")
    return normalized


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return _utc(value, field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")), field)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc


def _optional_timestamp(value: Any, field: str) -> datetime | None:
    return None if value in (None, "") else _timestamp(value, field)


def _stored_timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    else:
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_stored_timestamp(value: Any, field: str) -> datetime | None:
    return None if value in (None, "") else _stored_timestamp(value, field)


def _ledger_full_claim_eligible(
    manifest: dict[str, Any], observation: CoverageObservation, checked_at: datetime
) -> bool:
    conservation = manifest["conservation"]
    pages = manifest["coverage"]["pages"]
    fields = manifest["coverage"]["fields"]
    window = manifest["coverage"]["window"]
    universe = manifest["universe"]
    freshness = manifest["freshness"]
    return bool(
        observation.status == "complete"
        and observation.completeness == "complete"
        and manifest["source"]["source_status"] == "implemented"
        and universe["denominator_known"]
        and universe["expected_count"] == conservation["observed_count"]
        and all(
            conservation[name] == 0
            for name in (
                "quarantined_count",
                "failed_count",
                "duplicate_count",
                "suppressed_count",
            )
        )
        and pages["failed_count"] == 0
        and pages["duplicate_count"] == 0
        and pages["closed"]
        and manifest["checkpoint"]["closed"]
        and not window["gaps"]
        and not window["overlaps"]
        and window["late_arrival_count"] == 0
        and not manifest["conflicts"]
        and freshness["status"] == "fresh"
        and _timestamp(freshness["fresh_until"], "fresh_until") > checked_at
        and _timestamp(freshness["review_due"], "review_due") > checked_at
        and len(fields["present"]) == fields["required_count"]
        and all(not fields[name] for name in ("missing", "unparseable", "conflicting"))
        and window["requested_start"] == window["effective_start"]
        and window["requested_end"] == window["effective_end"]
    )


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat()
