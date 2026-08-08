from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base


class EvidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


class RetentionClass(StrEnum):
    OPERATIONAL = "operational"
    FINANCIAL = "financial"
    COMPLIANCE = "compliance"
    EXPERIMENT = "experiment"
    SECURITY = "security"


UNIQUE_SOURCE_REF_SOURCES = {
    "browser-capture-inbox",
    "channel_account_authorization_consent",
    "channel_account_authorization_lifecycle",
    "channel_account_compensation_plan",
    "channel_account_governance_review",
    "channel_account_governance_submission",
    "channel_account_kill_switch_release",
    "channel_account_official_readback",
    "channel_account_one_time_permit",
    "governed-agent-run-evidence",
    "global-data-coverage-denominator",
    "global-data-coverage-ledger",
    "global-data-coverage-manifest",
    "global-data-coverage-native-caps",
    "governed-team-agent-evolution",
    "team-agent-baseline-authority",
    "team-agent-deidentification-authority",
    "team-agent-eval-set-authority",
    "team-agent-license-authority",
    "team-agent-retirement-authority",
    "team-agent-review-authority",
    "team-agent-revocation-authority",
    "team-agent-risk-authority",
    "team-agent-rollback-authority",
    "team-agent-shadow-authority",
    "marketplace-observation",
    "ozon-isolated-execution-worker",
    "primary-source-intake",
    "strategic-benchmark-snapshot",
    "strategic-benchmark-observation",
    "scope_authority_review",
    "scope_authority_source",
    "seller_erp_bridge_binding",
    "seller_erp_bridge_review",
    "seller_erp_bridge_revocation",
    "seller_erp_bridge_source",
    "supplier_rfq_dispatch",
    "supplier_rfq_package",
    "governed-media-job-request",
    "governed-media-job-transition",
    "governed-media-job-usage",
}

CHANNEL_ACCOUNT_RESERVED_SOURCES = frozenset(
    {
        "channel_account_authorization_consent",
        "channel_account_authorization_lifecycle",
        "channel_account_compensation_plan",
        "channel_account_governance_review",
        "channel_account_governance_submission",
        "channel_account_kill_switch_release",
        "channel_account_official_readback",
        "channel_account_one_time_permit",
    }
)
CHANNEL_ACCOUNT_RESERVED_CONTRACTS = frozenset(
    {
        "kjds-channel-account-consent-evidence-v1",
        "kjds-channel-account-governance-submission-v1",
        "kjds-channel-account-kill-switch-evidence-v1",
        "kjds-channel-account-lifecycle-evidence-v1",
        "kjds-channel-account-one-time-permit-v1",
        "kjds-channel-account-readback-v1",
        "kjds-channel-account-compensation-evidence-v1",
        "kjds-channel-account-sod-review-v1",
    }
)
TEAM_AGENT_RESERVED_SOURCES = frozenset(
    {
        "governed-team-agent-evolution",
        "team-agent-baseline-authority",
        "team-agent-deidentification-authority",
        "team-agent-eval-set-authority",
        "team-agent-license-authority",
        "team-agent-retirement-authority",
        "team-agent-review-authority",
        "team-agent-revocation-authority",
        "team-agent-risk-authority",
        "team-agent-rollback-authority",
        "team-agent-shadow-authority",
    }
)
TEAM_AGENT_RESERVED_CONTRACTS = frozenset(
    {
        "kjds-governed-team-agent-evolution-evidence-v1",
        "kjds-team-agent-baseline-authority-v1",
        "kjds-team-agent-deidentification-authority-v1",
        "kjds-team-agent-eval-set-authority-v1",
        "kjds-team-agent-license-authority-v1",
        "kjds-team-agent-retirement-authority-v1",
        "kjds-team-agent-review-authority-v1",
        "kjds-team-agent-revocation-authority-v1",
        "kjds-team-agent-risk-authority-v1",
        "kjds-team-agent-rollback-authority-v1",
        "kjds-team-agent-shadow-authority-v1",
    }
)
COVERAGE_RESERVED_SOURCES = frozenset(
    {
        "global-data-coverage-manifest",
        "global-data-coverage-native-caps",
        "global-data-coverage-denominator",
        "global-data-coverage-ledger",
    }
)
COVERAGE_RESERVED_CONTRACTS = frozenset(
    {
        "kjds-global-data-coverage-manifest-evidence-v1",
        "kjds-global-data-coverage-native-caps-evidence-v1",
        "kjds-global-data-coverage-denominator-evidence-v1",
        "kjds-global-data-coverage-ledger-evidence-v1",
    }
)
CLOSED_LOOP_RESERVED_SOURCES = frozenset(
    {
        "closed-loop-experiment-receipt",
        "closed-loop-cost-receipt",
        "closed-loop-business-outcome-receipt",
        "closed-loop-review-authority-receipt",
        "governed-closed-loop-evolution",
    }
)
CLOSED_LOOP_RESERVED_CONTRACTS = frozenset(
    {
        "kjds-closed-loop-experiment-receipt-v1",
        "kjds-closed-loop-cost-receipt-v1",
        "kjds-closed-loop-business-outcome-receipt-v1",
        "kjds-closed-loop-review-authority-receipt-v1",
        "kjds-governed-closed-loop-evolution-event-v1",
    }
)
MEDIA_JOB_RESERVED_SOURCES = frozenset(
    {
        "governed-media-job-request",
        "governed-media-job-transition",
        "governed-media-job-usage",
    }
)
MEDIA_JOB_RESERVED_CONTRACTS = frozenset(
    {
        "kjds-governed-media-job-request-v1",
        "kjds-governed-media-job-transition-v1",
        "kjds-governed-media-job-usage-v1",
    }
)
CLOSED_LOOP_AUTHORITY_SCHEMA_MANIFESTS: dict[str, dict[str, Any]] = {
    "experiment": {
        "schema_id": "kjds-closed-loop-experiment-claims-v1",
        "additional_properties": False,
        "required_fields": [
            "agent_run_ref",
            "experiment_ref",
            "method",
            "treatment_ref",
            "control_ref",
            "sample_size",
            "minimum_sample_size",
            "metric_id",
            "metric_unit",
            "metric_currency",
            "window_start",
            "window_end",
            "confidence_level_decimal",
            "independent_review_passed",
            "causal_claim_allowed",
        ],
        "field_types": {
            "agent_run_ref": "token",
            "experiment_ref": "token",
            "method": "token",
            "treatment_ref": "token",
            "control_ref": "nullable_token",
            "sample_size": "positive_integer",
            "minimum_sample_size": "positive_integer",
            "metric_id": "token",
            "metric_unit": "token",
            "metric_currency": "currency_or_null_by_metric_unit",
            "window_start": "aware_utc_datetime",
            "window_end": "aware_utc_datetime",
            "confidence_level_decimal": "numeric_8_6_exact_gt_0_lte_1",
            "independent_review_passed": "strict_boolean",
            "causal_claim_allowed": "literal_false",
        },
        "cross_field_rules": [
            "window_start_lt_window_end",
            "treatment_ref_ne_control_ref",
            "monetary_metric_requires_currency",
            "decimal_storage_exact_without_rounding",
            "causal_claim_forbidden",
        ],
    },
    "cost": {
        "schema_id": "kjds-closed-loop-cost-claims-v1",
        "additional_properties": False,
        "required_fields": [
            "agent_run_ref",
            "experiment_ref",
            "outcome_ref",
            "cost_ref",
            "amount_minor_units",
            "currency",
            "period_start",
            "period_end",
            "allocation_method",
        ],
        "field_types": {
            "agent_run_ref": "token",
            "experiment_ref": "token",
            "outcome_ref": "token",
            "cost_ref": "token",
            "amount_minor_units": "nonnegative_integer",
            "currency": "iso_4217_uppercase",
            "period_start": "aware_utc_datetime",
            "period_end": "aware_utc_datetime",
            "allocation_method": "token",
        },
        "cross_field_rules": ["period_start_lt_period_end"],
    },
    "business_outcome": {
        "schema_id": "kjds-closed-loop-business-outcome-claims-v1",
        "additional_properties": False,
        "required_fields": [
            "agent_run_ref",
            "outcome_ref",
            "experiment_ref",
            "metric_id",
            "metric_unit",
            "metric_currency",
            "method",
            "sample_size",
            "interval_start",
            "interval_end",
            "value_decimal",
            "confidence_level_decimal",
            "independent_review_passed",
            "causal_claim_allowed",
        ],
        "field_types": {
            "agent_run_ref": "token",
            "outcome_ref": "token",
            "experiment_ref": "token",
            "metric_id": "token",
            "metric_unit": "token",
            "metric_currency": "currency_or_null_by_metric_unit",
            "method": "token",
            "sample_size": "positive_integer",
            "interval_start": "aware_utc_datetime",
            "interval_end": "aware_utc_datetime",
            "value_decimal": "numeric_30_12_exact_abs_lt_1e18",
            "confidence_level_decimal": "numeric_8_6_exact_gt_0_lte_1",
            "independent_review_passed": "strict_boolean",
            "causal_claim_allowed": "literal_false",
        },
        "cross_field_rules": [
            "interval_start_lt_interval_end",
            "monetary_metric_requires_currency",
            "decimal_storage_exact_without_rounding",
            "causal_claim_forbidden",
        ],
    },
    "review_event": {
        "schema_id": "kjds-closed-loop-review-event-claims-v1",
        "additional_properties": False,
        "required_fields": [
            "bundle_id",
            "event_type",
            "reason_code",
            "replacement_bundle_id",
            "requested_by_actor_id",
        ],
        "field_types": {
            "bundle_id": "token",
            "event_type": "review_event_enum",
            "reason_code": "token",
            "replacement_bundle_id": "nullable_token",
            "requested_by_actor_id": "token",
        },
        "cross_field_rules": [
            "superseded_iff_replacement_bundle_id_present"
        ],
    },
}


def _closed_loop_schema_sha256(purpose: str) -> str:
    return hashlib.sha256(
        json.dumps(
            CLOSED_LOOP_AUTHORITY_SCHEMA_MANIFESTS[purpose],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


CLOSED_LOOP_AUTHORITY_CONTRACTS: dict[str, dict[str, Any]] = {
    "experiment": {
        "source": "closed-loop-experiment-receipt",
        "contract_id": "kjds-closed-loop-experiment-receipt-v1",
        "issuer_id": "kjds-closed-loop-experiment-authority",
        "issuer_contract_id": "kjds-closed-loop-experiment-authority-v1",
        "issuer_contract_version": "1.0.0",
        "issuer_contract_sha256": (
            "f97fe473225e7ffc13f42e94f164f3cfc3fba028179e1b04864c09203a7576ea"
        ),
        "schema_sha256": _closed_loop_schema_sha256("experiment"),
        "fields": frozenset(
            {
                "agent_run_ref",
                "experiment_ref",
                "method",
                "treatment_ref",
                "control_ref",
                "sample_size",
                "minimum_sample_size",
                "metric_id",
                "metric_unit",
                "metric_currency",
                "window_start",
                "window_end",
                "confidence_level_decimal",
                "independent_review_passed",
                "causal_claim_allowed",
            }
        ),
    },
    "cost": {
        "source": "closed-loop-cost-receipt",
        "contract_id": "kjds-closed-loop-cost-receipt-v1",
        "issuer_id": "kjds-closed-loop-cost-authority",
        "issuer_contract_id": "kjds-closed-loop-cost-authority-v1",
        "issuer_contract_version": "1.0.0",
        "issuer_contract_sha256": (
            "26d5067a2eb437e757258fa60d072074771161025d3354e87d4710a26bb4602f"
        ),
        "schema_sha256": _closed_loop_schema_sha256("cost"),
        "fields": frozenset(
            {
                "agent_run_ref",
                "experiment_ref",
                "outcome_ref",
                "cost_ref",
                "amount_minor_units",
                "currency",
                "period_start",
                "period_end",
                "allocation_method",
            }
        ),
    },
    "business_outcome": {
        "source": "closed-loop-business-outcome-receipt",
        "contract_id": "kjds-closed-loop-business-outcome-receipt-v1",
        "issuer_id": "kjds-closed-loop-business_outcome-authority",
        "issuer_contract_id": "kjds-closed-loop-business_outcome-authority-v1",
        "issuer_contract_version": "1.0.0",
        "issuer_contract_sha256": (
            "707982da198bd289c13fbc7151ded979e0125672b7b341e5728079467147db6c"
        ),
        "schema_sha256": _closed_loop_schema_sha256("business_outcome"),
        "fields": frozenset(
            {
                "agent_run_ref",
                "outcome_ref",
                "experiment_ref",
                "metric_id",
                "metric_unit",
                "metric_currency",
                "method",
                "sample_size",
                "interval_start",
                "interval_end",
                "value_decimal",
                "confidence_level_decimal",
                "independent_review_passed",
                "causal_claim_allowed",
            }
        ),
    },
    "review_event": {
        "source": "closed-loop-review-authority-receipt",
        "contract_id": "kjds-closed-loop-review-authority-receipt-v1",
        "issuer_id": "kjds-closed-loop-review-authority",
        "issuer_contract_id": "kjds-closed-loop-review-authority-v1",
        "issuer_contract_version": "1.0.0",
        "issuer_contract_sha256": (
            "d85428cb588631ff0afd0592b08d5c4bd372aed4abbd543c0fbb07f4c5a773e7"
        ),
        "schema_sha256": _closed_loop_schema_sha256("review_event"),
        "fields": frozenset(
            {
                "bundle_id",
                "event_type",
                "reason_code",
                "replacement_bundle_id",
                "requested_by_actor_id",
            }
        ),
    },
}
COVERAGE_INTAKE_CONTRACTS: dict[str, dict[str, str]] = {
    "manifest": {
        "source": "global-data-coverage-manifest",
        "contract_id": "kjds-global-data-coverage-manifest-evidence-v1",
        "schema_version": "kjds-source-coverage-manifest-v1",
    },
    "native_caps": {
        "source": "global-data-coverage-native-caps",
        "contract_id": "kjds-global-data-coverage-native-caps-evidence-v1",
        "schema_version": "kjds-source-native-caps-v1",
    },
    "denominator": {
        "source": "global-data-coverage-denominator",
        "contract_id": "kjds-global-data-coverage-denominator-evidence-v1",
        "schema_version": "kjds-global-data-coverage-denominator-v1",
    },
}
_RESERVED_CAPTURE_AUTHORITY = object()
_RESEARCH_CAPTURE_AUTHORITY = object()
_MEDIA_JOB_CAPTURE_AUTHORITY = object()
RESEARCH_SIGNAL_EVIDENCE_ROLE = "research_signal"
RESEARCH_CAPTURE_CONTRACT_ID = "kjds-research-capture-request-v1"
MEDIA_JOB_EVIDENCE_CONTRACT_ID = "kjds-governed-media-job-request-v1"

TEAM_AGENT_AUTHORITY_CONTRACTS: dict[str, dict[str, Any]] = {
    "eval_set": {
        "source": "team-agent-eval-set-authority",
        "contract_id": "kjds-team-agent-eval-set-authority-v1",
        "grade": EvidenceGrade.A,
        "payload_field": "eval_set_sha256",
        "roles": frozenset({"compliance", "admin"}),
        "fields": frozenset({"eval_set_sha256", "snapshot_sha256"}),
    },
    "baseline": {
        "source": "team-agent-baseline-authority",
        "contract_id": "kjds-team-agent-baseline-authority-v1",
        "grade": EvidenceGrade.B,
        "payload_field": "baseline_snapshot_sha256",
        "roles": frozenset({"reviewer", "monitor", "compliance", "admin"}),
        "fields": frozenset(
            {
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
            }
        ),
    },
    "shadow": {
        "source": "team-agent-shadow-authority",
        "contract_id": "kjds-team-agent-shadow-authority-v1",
        "grade": EvidenceGrade.B,
        "payload_field": "snapshot_sha256",
        "roles": frozenset({"reviewer", "monitor", "compliance", "admin"}),
        "fields": frozenset(
            {
                "agent_run_ref",
                "runtime_sha256",
                "snapshot_sha256",
                "shadow_passed",
                "zero_external_writes",
                "cost_usd",
                "latency_ms",
                "token_count",
            }
        ),
    },
    "review": {
        "source": "team-agent-review-authority",
        "contract_id": "kjds-team-agent-review-authority-v1",
        "grade": EvidenceGrade.A,
        "payload_field": "snapshot_sha256",
        "roles": frozenset({"reviewer", "compliance", "admin"}),
        "fields": frozenset({"review_verdict", "snapshot_sha256"}),
    },
    "risk_authority": {
        "source": "team-agent-risk-authority",
        "contract_id": "kjds-team-agent-risk-authority-v1",
        "grade": EvidenceGrade.A,
        "payload_field": "snapshot_sha256",
        "roles": frozenset({"risk", "compliance", "admin"}),
        "fields": frozenset(
            {"risk_authority_sha256", "current", "snapshot_sha256"}
        ),
    },
    "rollback": {
        "source": "team-agent-rollback-authority",
        "contract_id": "kjds-team-agent-rollback-authority-v1",
        "grade": EvidenceGrade.A,
        "payload_field": "rollback_artifact_sha256",
        "roles": frozenset({"risk", "compliance", "admin"}),
        "fields": frozenset(
            {
                "rollback_target_ref",
                "rollback_version",
                "rollback_target_content_sha256",
                "rollback_target_runtime_sha256",
                "rollback_artifact_sha256",
                "snapshot_sha256",
            }
        ),
    },
    "license": {
        "source": "team-agent-license-authority",
        "contract_id": "kjds-team-agent-license-authority-v1",
        "grade": EvidenceGrade.A,
        "payload_field": "license_sha256",
        "roles": frozenset({"compliance", "admin"}),
        "fields": frozenset(
            {
                "license_sha256",
                "authority_subject_sha256",
                "authority_epoch",
                "current",
                "snapshot_sha256",
            }
        ),
    },
    "deidentification": {
        "source": "team-agent-deidentification-authority",
        "contract_id": "kjds-team-agent-deidentification-authority-v1",
        "grade": EvidenceGrade.A,
        "payload_field": "deidentification_sha256",
        "roles": frozenset({"compliance", "admin"}),
        "fields": frozenset(
            {
                "deidentification_sha256",
                "authority_subject_sha256",
                "authority_epoch",
                "current",
                "nonreversible",
                "snapshot_sha256",
            }
        ),
    },
    "revocation": {
        "source": "team-agent-revocation-authority",
        "contract_id": "kjds-team-agent-revocation-authority-v1",
        "grade": EvidenceGrade.A,
        "payload_field": "revocation_contract_sha256",
        "roles": frozenset({"compliance", "admin"}),
        "fields": frozenset(
            {
                "revocation_contract_sha256",
                "authority_subject_sha256",
                "authority_epoch",
                "current",
                "revoked",
                "snapshot_sha256",
            }
        ),
    },
    "retirement": {
        "source": "team-agent-retirement-authority",
        "contract_id": "kjds-team-agent-retirement-authority-v1",
        "grade": EvidenceGrade.A,
        "payload_field": "retirement_sha256",
        "roles": frozenset({"risk", "compliance", "admin"}),
        "fields": frozenset({"retirement_sha256", "snapshot_sha256"}),
    },
}

RETENTION_REVIEW_DAYS = {
    RetentionClass.OPERATIONAL: 365,
    RetentionClass.FINANCIAL: 3650,
    RetentionClass.COMPLIANCE: 3650,
    RetentionClass.EXPERIMENT: 1095,
    RetentionClass.SECURITY: 2555,
}


class EvidenceBlobRow(Base):
    __tablename__ = "evidence_blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRecordRow(Base):
    __tablename__ = "evidence_records"
    __table_args__ = (
        UniqueConstraint("blob_sha256", "source", "source_ref", "effective_at", name="uq_evidence_capture"),
        UniqueConstraint(
            "id",
            "blob_sha256",
            "source",
            "source_ref",
            "grade",
            "effective_at",
            name="uq_evidence_record_strategic_binding",
        ),
        Index(
            "uq_execution_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'ozon-isolated-execution-worker'"),
            sqlite_where=text("source = 'ozon-isolated-execution-worker'"),
        ),
        Index(
            "uq_governed_agent_run_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'governed-agent-run-evidence'"),
            sqlite_where=text("source = 'governed-agent-run-evidence'"),
        ),
        Index(
            "uq_team_agent_evolution_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'governed-team-agent-evolution'"),
            sqlite_where=text("source = 'governed-team-agent-evolution'"),
        ),
        Index(
            "uq_team_agent_authority_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text(
                "source IN ('team-agent-baseline-authority',"
                "'team-agent-deidentification-authority',"
                "'team-agent-eval-set-authority',"
                "'team-agent-license-authority',"
                "'team-agent-retirement-authority',"
                "'team-agent-review-authority',"
                "'team-agent-revocation-authority',"
                "'team-agent-risk-authority',"
                "'team-agent-rollback-authority',"
                "'team-agent-shadow-authority')"
            ),
            sqlite_where=text(
                "source IN ('team-agent-baseline-authority',"
                "'team-agent-deidentification-authority',"
                "'team-agent-eval-set-authority',"
                "'team-agent-license-authority',"
                "'team-agent-retirement-authority',"
                "'team-agent-review-authority',"
                "'team-agent-revocation-authority',"
                "'team-agent-risk-authority',"
                "'team-agent-rollback-authority',"
                "'team-agent-shadow-authority')"
            ),
        ),
        Index(
            "uq_closed_loop_authority_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text(
                "source IN ('closed-loop-experiment-receipt',"
                "'closed-loop-cost-receipt',"
                "'closed-loop-business-outcome-receipt',"
                "'closed-loop-review-authority-receipt',"
                "'governed-closed-loop-evolution')"
            ),
            sqlite_where=text(
                "source IN ('closed-loop-experiment-receipt',"
                "'closed-loop-cost-receipt',"
                "'closed-loop-business-outcome-receipt',"
                "'closed-loop-review-authority-receipt',"
                "'governed-closed-loop-evolution')"
            ),
        ),
        Index(
            "uq_media_job_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text(
                "source IN ('governed-media-job-request',"
                "'governed-media-job-transition','governed-media-job-usage')"
            ),
            sqlite_where=text(
                "source IN ('governed-media-job-request',"
                "'governed-media-job-transition','governed-media-job-usage')"
            ),
        ),
        Index(
            "uq_primary_source_intake_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'primary-source-intake'"),
            sqlite_where=text("source = 'primary-source-intake'"),
        ),
        Index(
            "uq_strategic_benchmark_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'strategic-benchmark-snapshot'"),
            sqlite_where=text("source = 'strategic-benchmark-snapshot'"),
        ),
        Index(
            "uq_strategic_benchmark_observation_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'strategic-benchmark-observation'"),
            sqlite_where=text("source = 'strategic-benchmark-observation'"),
        ),
        Index(
            "uq_scope_authority_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'scope_authority_source'"),
            sqlite_where=text("source = 'scope_authority_source'"),
        ),
        Index(
            "uq_scope_authority_review_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'scope_authority_review'"),
            sqlite_where=text("source = 'scope_authority_review'"),
        ),
        Index(
            "uq_seller_erp_bridge_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'seller_erp_bridge_source'"),
            sqlite_where=text("source = 'seller_erp_bridge_source'"),
        ),
        Index(
            "uq_seller_erp_bridge_review_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'seller_erp_bridge_review'"),
            sqlite_where=text("source = 'seller_erp_bridge_review'"),
        ),
        Index(
            "uq_seller_erp_bridge_binding_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'seller_erp_bridge_binding'"),
            sqlite_where=text("source = 'seller_erp_bridge_binding'"),
        ),
        Index(
            "uq_seller_erp_bridge_revocation_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'seller_erp_bridge_revocation'"),
            sqlite_where=text("source = 'seller_erp_bridge_revocation'"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    blob_sha256: Mapped[str] = mapped_column(ForeignKey("evidence_blobs.sha256"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class GlobalDataCoverageIssuanceAuthorityRow(Base):
    __tablename__ = "global_data_coverage_issuance_authorities"

    authority_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    signing_key_secret: Mapped[str] = mapped_column(Text, nullable=False)
    signing_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalDataCoverageEvidenceIssuanceRow(Base):
    __tablename__ = "global_data_coverage_evidence_issuances"
    __table_args__ = (
        UniqueConstraint(
            "evidence_id",
            "issuance_sha256",
            "issuance_signature_sha256",
            name="uq_gdc_issuance_exact_binding",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id", ondelete="RESTRICT"), primary_key=True
    )
    authority_id: Mapped[str] = mapped_column(
        ForeignKey(
            "global_data_coverage_issuance_authorities.authority_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    issuance_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    issuance_signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LineageEdgeRow(Base):
    __tablename__ = "lineage_edges"
    __table_args__ = (
        UniqueConstraint(
            "from_type",
            "from_id",
            "to_type",
            "to_id",
            "relationship",
            name="uq_lineage_edge",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    from_type: Mapped[str] = mapped_column(String, nullable=False)
    from_id: Mapped[str] = mapped_column(String, nullable=False)
    to_type: Mapped[str] = mapped_column(String, nullable=False)
    to_id: Mapped[str] = mapped_column(String, nullable=False)
    relationship: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: str
    sha256: str
    byte_size: int
    filename: str
    content_type: str
    source: str
    source_ref: str
    grade: EvidenceGrade
    effective_at: str
    effective_until: str | None
    recorded_at: str
    created_by: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LineageEdge:
    id: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    relationship: str
    created_by: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class EvidenceVerification:
    evidence_id: str
    expected_sha256: str
    actual_sha256: str
    byte_size: int
    valid: bool


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityFinding:
    evidence_id: str
    declared_sha256: str
    actual_sha256: str | None
    declared_byte_size: int | None
    actual_byte_size: int | None
    codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityScan:
    total: int
    offset: int
    scanned: int
    valid: int
    invalid: int
    next_offset: int | None
    findings: tuple[EvidenceIntegrityFinding, ...]


@dataclass(frozen=True, slots=True)
class RetentionAssessment:
    evidence_id: str
    retention_class: str | None
    legal_hold: bool
    review_due_at: str | None
    status: str
    archive_eligible: bool
    automatic_delete_allowed: bool = False


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


class EvidenceService:
    def __init__(self, engine) -> None:
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Open one governed transaction for Evidence and its owning ledger."""
        with Session(self.engine) as session, session.begin():
            yield session

    @staticmethod
    def lock_scope_authority_in_session(
        *,
        tenant_ref: str,
        store_ref: str,
        subject_actor_id: str,
        session: Session,
    ) -> None:
        """Serialize capture with the matching append-only scope authority."""

        tenant_ref = tenant_ref.strip()
        store_ref = store_ref.strip()
        subject_actor_id = subject_actor_id.strip()
        if not tenant_ref or not store_ref or not subject_actor_id:
            raise ValueError("Scope authority lock requires tenant, store, and subject")
        if session.get_bind().dialect.name != "postgresql":
            return
        session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended("
                "concat_ws(chr(31), CAST(:tenant_ref AS text), "
                "CAST(:store_ref AS text), CAST(:subject_actor_id AS text)), 0"
                ")"
                ")"
            ),
            {
                "tenant_ref": tenant_ref,
                "store_ref": store_ref,
                "subject_actor_id": subject_actor_id,
            },
        )

    def capture_team_agent_evolution_event(
        self,
        *,
        content: bytes,
        source_ref: str,
        effective_at: str,
        metadata: dict[str, Any],
        session: Session,
    ) -> EvidenceRecord:
        """Persist the module-owned Grade-D event receipt.

        Supporting review, risk, license, and evaluation Evidence remains
        reserved to its independent authority adapter.  This narrow method
        only admits the hash-and-code-only audit receipt emitted by the
        governed evolution ledger itself.
        """

        candidate_ref = str(metadata.get("candidate_ref") or "").strip()
        event_ref = str(metadata.get("event_ref") or "").strip()
        expected_ref = f"team-agent-evolution://{candidate_ref}/{event_ref}"
        if (
            metadata.get("contract_id")
            != "kjds-governed-team-agent-evolution-evidence-v1"
            or metadata.get("evolution_purpose") != "event_audit"
            or source_ref != expected_ref
            or not candidate_ref
            or not event_ref
        ):
            raise ValueError("Invalid governed team-agent event Evidence contract")
        return self.capture(
            content=content,
            filename=f"{event_ref}.json",
            content_type="application/json",
            source="governed-team-agent-evolution",
            source_ref=source_ref,
            grade=EvidenceGrade.D,
            effective_at=effective_at,
            effective_until=None,
            created_by="kjds-team-agent-evolution",
            metadata=metadata,
            _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
            _session=session,
        )

    def capture_global_data_coverage_ledger_event(
        self,
        *,
        content: bytes,
        source_ref: str,
        effective_at: str,
        metadata: dict[str, Any],
        session: Session,
    ) -> EvidenceRecord:
        """Persist one module-owned hash-and-code-only coverage ledger event."""

        snapshot_id = str(metadata.get("snapshot_id") or "").strip()
        event_id = str(metadata.get("event_id") or "").strip()
        expected_ref = f"coverage-ledger://{snapshot_id}/{event_id}"
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Coverage ledger event must be canonical JSON") from exc
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        if (
            not isinstance(payload, dict)
            or canonical != content
            or metadata.get("contract_id")
            != "kjds-global-data-coverage-ledger-evidence-v1"
            or payload.get("contract_id")
            != "kjds-global-data-coverage-ledger-evidence-v1"
            or payload.get("snapshot_id") != snapshot_id
            or payload.get("event_sha256") != metadata.get("event_sha256")
            or source_ref != expected_ref
            or not snapshot_id
            or not event_id
        ):
            raise ValueError("Invalid global data coverage ledger event contract")
        return self.capture(
            content=content,
            filename=f"{event_id}.json",
            content_type="application/json",
            source="global-data-coverage-ledger",
            source_ref=source_ref,
            grade=EvidenceGrade.D,
            effective_at=effective_at,
            effective_until=None,
            created_by="kjds-global-data-coverage-ledger",
            metadata=metadata,
            _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
            _session=session,
        )

    def capture_closed_loop_evolution_event(
        self,
        *,
        content: bytes,
        source_ref: str,
        effective_at: str,
        recorded_at: str,
        metadata: dict[str, Any],
        session: Session,
    ) -> EvidenceRecord:
        """Persist one module-owned, canonical closed-loop event receipt."""

        bundle_id = str(metadata.get("bundle_id") or "").strip()
        event_id = str(metadata.get("event_id") or "").strip()
        expected_ref = f"closed-loop-evolution://{bundle_id}/{event_id}"
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Closed-loop event must be canonical JSON") from None
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        if not isinstance(payload, dict):
            raise ValueError("Invalid governed closed-loop event Evidence contract")
        expected_keys = {
            "contract_id",
            "bundle_id",
            "event_index",
            "event_type",
            "reason_code",
            "actor_id",
            "request_sha256",
            "previous_event_sha256",
            "occurred_at",
            "event_sha256",
            "review_evidence_ref",
            "replacement_bundle_id",
            "payload_status",
            "candidate_created",
            "transition_allowed",
            "promotion_allowed",
            "external_write_allowed",
        }
        expected_metadata_keys = {
            "contract_id",
            "bundle_id",
            "event_id",
            "event_type",
            "event_sha256",
            "review_evidence_ref",
            "replacement_bundle_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "retention_class",
            "legal_hold",
        }
        event_core = {
            key: payload.get(key)
            for key in (
                "bundle_id",
                "event_index",
                "event_type",
                "reason_code",
                "actor_id",
                "request_sha256",
                "previous_event_sha256",
                "occurred_at",
            )
        }
        recomputed_event_sha256 = hashlib.sha256(
            "\x1f".join(
                str(event_core[field])
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
            ).encode()
        ).hexdigest()
        if (
            canonical != content
            or set(payload) != expected_keys
            or set(metadata) != expected_metadata_keys
            or metadata.get("contract_id")
            != "kjds-governed-closed-loop-evolution-event-v1"
            or payload.get("contract_id")
            != "kjds-governed-closed-loop-evolution-event-v1"
            or payload.get("bundle_id") != bundle_id
            or payload.get("event_sha256") != metadata.get("event_sha256")
            or payload.get("event_sha256") != recomputed_event_sha256
            or payload.get("event_type") != metadata.get("event_type")
            or payload.get("review_evidence_ref")
            != metadata.get("review_evidence_ref")
            or payload.get("replacement_bundle_id")
            != metadata.get("replacement_bundle_id")
            or metadata.get("retention_class") != "compliance"
            or metadata.get("legal_hold") is not False
            or not isinstance(payload.get("event_index"), int)
            or isinstance(payload.get("event_index"), bool)
            or payload.get("event_index", 0) < 1
            or payload.get("payload_status") != "hash_and_code_only"
            or any(
                payload.get(field) is not False
                for field in (
                    "candidate_created",
                    "transition_allowed",
                    "promotion_allowed",
                    "external_write_allowed",
                )
            )
            or source_ref != expected_ref
            or not bundle_id
            or not event_id
        ):
            raise ValueError("Invalid governed closed-loop event Evidence contract")
        return self.capture(
            content=content,
            filename=f"{event_id}.json",
            content_type="application/json",
            source="governed-closed-loop-evolution",
            source_ref=source_ref,
            grade=EvidenceGrade.D,
            effective_at=effective_at,
            effective_until=None,
            created_by="kjds-closed-loop-evolution",
            metadata=metadata,
            _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
            _session=session,
            _recorded_at=recorded_at,
        )

    def capture(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        source: str,
        source_ref: str,
        grade: EvidenceGrade,
        effective_at: str,
        effective_until: str | None,
        created_by: str,
        metadata: dict[str, Any] | None = None,
        _reserved_authority: object | None = None,
        _session: Session | None = None,
        _recorded_at: str | None = None,
    ) -> EvidenceRecord:
        if not content:
            raise ValueError("Evidence content cannot be empty")
        filename = filename.strip()
        content_type = content_type.strip() or "application/octet-stream"
        source = source.strip()
        source_ref = source_ref.strip()
        if not filename or not source or not source_ref:
            raise ValueError("Evidence requires filename, source, and source_ref")
        effective = parse_timestamp(effective_at, "effective_at")
        effective_end = parse_timestamp(effective_until, "effective_until") if effective_until else None
        if effective_end is not None and effective_end <= effective:
            raise ValueError("effective_until must be later than effective_at")

        metadata = metadata or {}
        if (
            source.strip().lower() in CHANNEL_ACCOUNT_RESERVED_SOURCES
            or str(metadata.get("contract_id") or "").strip() in CHANNEL_ACCOUNT_RESERVED_CONTRACTS
            or str(metadata.get("channel_account_review_contract_id") or "").strip()
            == "kjds-channel-account-sod-review-v1"
        ) and _reserved_authority is not _RESERVED_CAPTURE_AUTHORITY:
            raise ValueError("Reserved channel account Evidence requires the dedicated separation-of-duties workflow")
        if (
            source.strip().lower() in TEAM_AGENT_RESERVED_SOURCES
            or str(metadata.get("source_contract_id") or "").strip()
            in TEAM_AGENT_RESERVED_CONTRACTS
            or (
                source.strip().lower() == "governed-team-agent-evolution"
                and str(metadata.get("contract_id") or "").strip()
                == "kjds-governed-team-agent-evolution-evidence-v1"
            )
        ) and _reserved_authority is not _RESERVED_CAPTURE_AUTHORITY:
            raise ValueError(
                "Reserved team-agent Evidence requires its dedicated authority adapter"
            )
        if (
            source.strip().lower() in COVERAGE_RESERVED_SOURCES
            or str(metadata.get("contract_id") or "").strip()
            in COVERAGE_RESERVED_CONTRACTS
        ) and _reserved_authority is not _RESERVED_CAPTURE_AUTHORITY:
            raise ValueError(
                "Reserved coverage Evidence requires its dedicated authority adapter"
            )
        if (
            source.strip().lower() in CLOSED_LOOP_RESERVED_SOURCES
            or str(metadata.get("contract_id") or "").strip()
            in CLOSED_LOOP_RESERVED_CONTRACTS
        ) and _reserved_authority is not _RESERVED_CAPTURE_AUTHORITY:
            raise ValueError(
                "Reserved closed-loop Evidence requires its dedicated authority adapter"
            )
        if (
            source.strip().lower() in MEDIA_JOB_RESERVED_SOURCES
            or str(metadata.get("contract_id") or "").strip()
            in MEDIA_JOB_RESERVED_CONTRACTS
        ) and _reserved_authority is not _MEDIA_JOB_CAPTURE_AUTHORITY:
            raise ValueError(
                "Reserved media-job Evidence requires its dedicated authority adapter"
            )
        if (
            str(metadata.get("evidence_role") or "").strip()
            == RESEARCH_SIGNAL_EVIDENCE_ROLE
            or str(metadata.get("research_capture_contract_id") or "").strip()
            == RESEARCH_CAPTURE_CONTRACT_ID
        ) and _reserved_authority is not _RESEARCH_CAPTURE_AUTHORITY:
            raise ValueError(
                "Reserved research Evidence requires its dedicated intake workflow"
            )
        retention_class = metadata.get("retention_class")
        if retention_class is not None:
            try:
                RetentionClass(retention_class)
            except ValueError as exc:
                raise ValueError(f"Unsupported retention_class: {retention_class}") from exc
        if "legal_hold" in metadata and not isinstance(metadata["legal_hold"], bool):
            raise ValueError("legal_hold must be true or false")

        digest = hashlib.sha256(content).hexdigest()
        if _recorded_at is not None:
            if _reserved_authority not in {
                _RESERVED_CAPTURE_AUTHORITY,
                _MEDIA_JOB_CAPTURE_AUTHORITY,
            }:
                raise ValueError("Explicit Evidence recorded_at is reserved")
            now = parse_timestamp(_recorded_at, "recorded_at")
        else:
            now = datetime.now(UTC)
        if _session is not None:
            blob = _session.get(EvidenceBlobRow, digest)
            if blob is None:
                _session.add(
                    EvidenceBlobRow(
                        sha256=digest,
                        byte_size=len(content),
                        content_bytes=content,
                        created_at=now,
                    )
                )
            existing = self._captured_row(
                _session,
                digest=digest,
                source=source,
                source_ref=source_ref,
                effective_at=effective,
            )
            if existing is not None:
                return self._record(existing, len(content))
            if source in UNIQUE_SOURCE_REF_SOURCES:
                source_ref_winner = self._source_ref_row(
                    _session,
                    source=source,
                    source_ref=source_ref,
                )
                if source_ref_winner is not None:
                    if not hmac.compare_digest(
                        source_ref_winner.blob_sha256,
                        digest,
                    ):
                        raise ValueError(
                            "Evidence source reference already has different immutable content"
                        )
                    return self._record(source_ref_winner, len(content))
            row = EvidenceRecordRow(
                id=new_id("evd"),
                blob_sha256=digest,
                filename=filename,
                content_type=content_type,
                source=source,
                source_ref=source_ref,
                grade=grade.value,
                effective_at=effective,
                effective_until=effective_end,
                recorded_at=now,
                created_by=created_by,
                metadata_json=metadata,
            )
            _session.add(row)
            _session.flush()
            return self._record(row, len(content))
        try:
            with Session(self.engine) as session, session.begin():
                blob = session.get(EvidenceBlobRow, digest)
                if blob is None:
                    session.add(
                        EvidenceBlobRow(sha256=digest, byte_size=len(content), content_bytes=content, created_at=now)
                    )
                existing = self._captured_row(
                    session,
                    digest=digest,
                    source=source,
                    source_ref=source_ref,
                    effective_at=effective,
                )
                if existing is not None:
                    return self._record(existing, len(content))
                if source in UNIQUE_SOURCE_REF_SOURCES:
                    source_ref_winner = self._source_ref_row(
                        session,
                        source=source,
                        source_ref=source_ref,
                    )
                    if source_ref_winner is not None:
                        if not hmac.compare_digest(source_ref_winner.blob_sha256, digest):
                            raise ValueError("Evidence source reference already has different immutable content")
                        return self._record(source_ref_winner, len(content))
                row = EvidenceRecordRow(
                    id=new_id("evd"),
                    blob_sha256=digest,
                    filename=filename,
                    content_type=content_type,
                    source=source,
                    source_ref=source_ref,
                    grade=grade.value,
                    effective_at=effective,
                    effective_until=effective_end,
                    recorded_at=now,
                    created_by=created_by,
                    metadata_json=metadata,
                )
                session.add(row)
                session.flush()
                return self._record(row, len(content))
        except IntegrityError:
            with Session(self.engine) as session:
                winner = self._captured_row(
                    session,
                    digest=digest,
                    source=source,
                    source_ref=source_ref,
                    effective_at=effective,
                )
                if winner is None and source in UNIQUE_SOURCE_REF_SOURCES:
                    winner = self._source_ref_row(
                        session,
                        source=source,
                        source_ref=source_ref,
                    )
                if winner is None:
                    raise
                if not hmac.compare_digest(winner.blob_sha256, digest):
                    raise ValueError(
                        "Evidence source reference already has different immutable content"
                    ) from None
                return self._record(winner, len(content))

    def capture_research_signal_evidence(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        source: str,
        source_ref: str,
        grade: EvidenceGrade,
        effective_at: str,
        recorded_at: str,
        created_by: str,
        metadata: dict[str, Any],
        session: Session,
    ) -> EvidenceRecord:
        """Persist one Research Inbox record through its dedicated adapter."""

        if (
            metadata.get("evidence_role") != RESEARCH_SIGNAL_EVIDENCE_ROLE
            or metadata.get("research_capture_contract_id")
            != RESEARCH_CAPTURE_CONTRACT_ID
        ):
            raise ValueError("Invalid reserved research Evidence contract")
        return self.capture(
            content=content,
            filename=filename,
            content_type=content_type,
            source=source,
            source_ref=source_ref,
            grade=grade,
            effective_at=effective_at,
            effective_until=None,
            created_by=created_by,
            metadata=metadata,
            _reserved_authority=_RESEARCH_CAPTURE_AUTHORITY,
            _session=session,
        )

    def capture_media_job_evidence(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        source: str,
        source_ref: str,
        grade: EvidenceGrade,
        effective_at: str,
        recorded_at: str,
        created_by: str,
        metadata: dict[str, Any],
        session: Session,
    ) -> EvidenceRecord:
        """Capture a job-owned Evidence record without opening generic capture."""

        if source not in MEDIA_JOB_RESERVED_SOURCES:
            raise ValueError("Invalid media-job Evidence source")
        contracts = {
            "governed-media-job-request": (
                "kjds-governed-media-job-request-v1",
                "media_job_request_fingerprint_sha256",
            ),
            "governed-media-job-transition": (
                "kjds-governed-media-job-transition-v1",
                "event_sha256",
            ),
            "governed-media-job-usage": (
                "kjds-governed-media-job-usage-v1",
                "usage_receipt_sha256",
            ),
        }
        expected_contract, binding_field = contracts[source]
        expected_keys = {
            "contract_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "subject_actor_id",
            binding_field,
        }
        if set(metadata) != expected_keys or any(
            not isinstance(metadata[key], str) or not metadata[key].strip()
            for key in expected_keys
        ):
            raise ValueError("Invalid media-job Evidence metadata")
        if metadata["contract_id"] != expected_contract:
            raise ValueError("Invalid media-job Evidence contract")
        for hash_field in ("scope_grant_authority_sha256", binding_field):
            value = metadata[hash_field].lower()
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("Invalid media-job Evidence metadata hash")
        if not source_ref.startswith("media-job://"):
            raise ValueError("Invalid media-job Evidence source reference")
        return self.capture(
            content=content,
            filename=filename,
            content_type=content_type,
            source=source,
            source_ref=source_ref,
            grade=grade,
            effective_at=effective_at,
            effective_until=None,
            created_by=created_by,
            metadata=metadata,
            _reserved_authority=_MEDIA_JOB_CAPTURE_AUTHORITY,
            _session=session,
            _recorded_at=recorded_at,
        )
    def get(self, evidence_id: str) -> EvidenceRecord:
        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            if blob is None:
                raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
            return self._record(row, blob.byte_size)

    def get_metadata(self, evidence_id: str) -> EvidenceRecord:
        """Load record metadata and blob size without selecting blob content."""

        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            return self._record(row, 0)

    def get_metadata_in_session(
        self, evidence_id: str, *, session: Session
    ) -> EvidenceRecord:
        """Load Evidence metadata through the caller's governed transaction."""

        row = session.get(EvidenceRecordRow, evidence_id)
        if row is None:
            raise KeyError(f"Unknown evidence: {evidence_id}")
        blob = session.get(EvidenceBlobRow, row.blob_sha256)
        if blob is None:
            raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
        return self._record(row, blob.byte_size)

    def list(self, limit: int = 100) -> list[EvidenceRecord]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
                .join(EvidenceBlobRow, EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256)
                .order_by(EvidenceRecordRow.recorded_at.desc(), EvidenceRecordRow.id)
                .limit(limit)
            ).all()
            return [self._record(row, byte_size) for row, byte_size in rows]

    def list_for_governance(
        self,
        *,
        closed_loop_scopes: Sequence[Mapping[str, str]],
        limit: int,
        cursor_recorded_at: datetime | None = None,
        cursor_id: str | None = None,
        evidence_role: str | None = None,
        evidence_ids: Sequence[str] | None = None,
        exact_scope: Mapping[str, str] | None = None,
        lineage_target: Mapping[str, str] | None = None,
        metadata_equals: Mapping[str, str] | None = None,
    ) -> list[EvidenceRecord]:
        """Page records while applying governance visibility in SQL.

        Ordinary Evidence keeps the historical governance visibility contract.
        Closed-loop authority and event Evidence is admitted to the query only
        when every current scope component matches, so another scope cannot
        consume the bounded page or disclose its record count/order. Optional
        Role, identifier, exact-scope, lineage, and metadata filters are applied
        before the bounded page. A supplied cursor must itself remain visible
        under the same complete predicate before it can advance the page.
        """

        bounded_limit = min(max(limit, 1), 501)
        if (cursor_recorded_at is None) != (cursor_id is None):
            raise ValueError("Evidence cursor components must be supplied together")
        if cursor_recorded_at is not None and cursor_recorded_at.tzinfo is None:
            raise ValueError("Evidence cursor timestamp must include a timezone")
        normalized_role = evidence_role.strip() if evidence_role is not None else None
        if evidence_role is not None and not normalized_role:
            raise ValueError("Evidence role filter cannot be empty")
        normalized_ids = (
            tuple(sorted({item.strip() for item in evidence_ids if item.strip()}))
            if evidence_ids is not None
            else None
        )
        if normalized_ids == ():
            return []
        scope_keys = {
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
        }
        normalized_scope: dict[str, str] | None = None
        if exact_scope is not None:
            if set(exact_scope) != scope_keys:
                raise ValueError("Evidence exact scope must contain exactly four fields")
            normalized_scope = {
                key: str(exact_scope[key]).strip() for key in sorted(scope_keys)
            }
            if any(not value for value in normalized_scope.values()) or not re.fullmatch(
                r"[0-9a-f]{64}",
                normalized_scope["scope_grant_authority_sha256"],
            ):
                raise ValueError("Evidence exact scope is invalid")
        lineage_keys = {"target_type", "target_id", "relationship"}
        normalized_lineage: dict[str, str] | None = None
        if lineage_target is not None:
            if set(lineage_target) != lineage_keys:
                raise ValueError("Evidence lineage filter must contain exactly three fields")
            normalized_lineage = {
                "target_type": str(lineage_target["target_type"]).strip().lower(),
                "target_id": str(lineage_target["target_id"]).strip(),
                "relationship": str(lineage_target["relationship"]).strip(),
            }
            if any(not value for value in normalized_lineage.values()):
                raise ValueError("Evidence lineage filter is invalid")
        normalized_metadata: dict[str, str] | None = None
        if metadata_equals is not None:
            if any(
                not isinstance(key, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,119}", key)
                or not isinstance(value, str)
                or not value
                for key, value in metadata_equals.items()
            ):
                raise ValueError("Evidence metadata filter is invalid")
            normalized_metadata = dict(sorted(metadata_equals.items()))

        def scope_clause(scope: Mapping[str, str]):
            return and_(
                EvidenceRecordRow.metadata_json["tenant_ref"].as_string()
                == scope["tenant_ref"],
                EvidenceRecordRow.metadata_json["entity_ref"].as_string()
                == scope["entity_ref"],
                EvidenceRecordRow.metadata_json["store_ref"].as_string()
                == scope["store_ref"],
                EvidenceRecordRow.metadata_json[
                    "scope_grant_authority_sha256"
                ].as_string()
                == scope["scope_grant_authority_sha256"],
            )

        scope_clauses = [
            scope_clause(scope)
            for scope in closed_loop_scopes
        ]
        closed_loop_visibility = and_(
            EvidenceRecordRow.source.in_(tuple(CLOSED_LOOP_RESERVED_SOURCES)),
            or_(*scope_clauses) if scope_clauses else text("false"),
        )
        ordinary_visibility = EvidenceRecordRow.source.not_in(
            tuple(CLOSED_LOOP_RESERVED_SOURCES)
        )
        if normalized_scope is not None:
            ordinary_visibility = and_(
                ordinary_visibility,
                scope_clause(normalized_scope),
            )
        visibility = or_(
            ordinary_visibility,
            closed_loop_visibility,
        )
        filters = [visibility]
        if normalized_role is not None:
            filters.append(
                EvidenceRecordRow.metadata_json["evidence_role"].as_string()
                == normalized_role
            )
        if normalized_ids is not None:
            filters.append(EvidenceRecordRow.id.in_(normalized_ids))
        if normalized_lineage is not None:
            filters.append(
                EvidenceRecordRow.id.in_(
                    select(LineageEdgeRow.from_id).where(
                        LineageEdgeRow.from_type == "evidence",
                        LineageEdgeRow.to_type
                        == normalized_lineage["target_type"],
                        LineageEdgeRow.to_id == normalized_lineage["target_id"],
                        LineageEdgeRow.relationship
                        == normalized_lineage["relationship"],
                    )
                )
            )
        if normalized_metadata is not None:
            filters.extend(
                EvidenceRecordRow.metadata_json[key].as_string() == value
                for key, value in normalized_metadata.items()
            )
        with Session(self.engine) as session:
            if cursor_recorded_at is not None and cursor_id is not None:
                normalized_cursor = cursor_recorded_at.astimezone(UTC)
                cursor_row = session.scalar(
                    select(EvidenceRecordRow).where(
                        *filters,
                        EvidenceRecordRow.id == cursor_id,
                    )
                )
                if cursor_row is None:
                    raise ValueError(
                        "Evidence cursor is not visible in the current query scope"
                    )
                stored_cursor = cursor_row.recorded_at
                if stored_cursor.tzinfo is None:
                    stored_cursor = stored_cursor.replace(tzinfo=UTC)
                if stored_cursor.astimezone(UTC) != normalized_cursor:
                    raise ValueError("Evidence cursor timestamp does not match its record")
                filters.append(
                    or_(
                        EvidenceRecordRow.recorded_at < normalized_cursor,
                        and_(
                            EvidenceRecordRow.recorded_at == normalized_cursor,
                            EvidenceRecordRow.id > cursor_id,
                        ),
                    )
                )
            query = (
                select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
                .join(
                    EvidenceBlobRow,
                    EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256,
                )
                .where(*filters)
                .order_by(EvidenceRecordRow.recorded_at.desc(), EvidenceRecordRow.id)
                .limit(bounded_limit)
            )
            rows = session.execute(query).all()
            return [self._record(row, byte_size) for row, byte_size in rows]

    def governance_cursor_candidates(
        self,
        *,
        closed_loop_scopes: Sequence[Mapping[str, str]],
        recorded_at: datetime,
    ) -> tuple[str, ...]:
        """Return only current-scope identifiers at one cursor timestamp."""

        scope_clauses = [
            and_(
                EvidenceRecordRow.metadata_json["tenant_ref"].as_string()
                == scope["tenant_ref"],
                EvidenceRecordRow.metadata_json["entity_ref"].as_string()
                == scope["entity_ref"],
                EvidenceRecordRow.metadata_json["store_ref"].as_string()
                == scope["store_ref"],
                EvidenceRecordRow.metadata_json[
                    "scope_grant_authority_sha256"
                ].as_string()
                == scope["scope_grant_authority_sha256"],
            )
            for scope in closed_loop_scopes
        ]
        visibility = or_(
            EvidenceRecordRow.source.not_in(tuple(CLOSED_LOOP_RESERVED_SOURCES)),
            and_(
                EvidenceRecordRow.source.in_(tuple(CLOSED_LOOP_RESERVED_SOURCES)),
                or_(*scope_clauses) if scope_clauses else text("false"),
            ),
        )
        with Session(self.engine) as session:
            return tuple(
                session.scalars(
                    select(EvidenceRecordRow.id)
                    .where(
                        visibility,
                        EvidenceRecordRow.recorded_at == recorded_at,
                    )
                    .order_by(EvidenceRecordRow.id)
                )
            )

    def list_by_source(self, source: str, limit: int = 100) -> list[EvidenceRecord]:
        source = source.strip()
        if not source:
            raise ValueError("Evidence source is required")
        with Session(self.engine) as session:
            rows = session.execute(
                select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
                .join(
                    EvidenceBlobRow,
                    EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256,
                )
                .where(EvidenceRecordRow.source == source)
                .order_by(EvidenceRecordRow.recorded_at.desc(), EvidenceRecordRow.id)
                .limit(min(max(limit, 1), 2000))
            ).all()
            return [self._record(row, byte_size) for row, byte_size in rows]

    def find_by_source_ref(self, *, source: str, source_ref: str) -> EvidenceRecord | None:
        source = source.strip()
        source_ref = source_ref.strip()
        if not source or not source_ref:
            raise ValueError("Evidence source and source_ref are required")
        with Session(self.engine) as session:
            result = session.execute(
                select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
                .join(EvidenceBlobRow, EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256)
                .where(
                    EvidenceRecordRow.source == source,
                    EvidenceRecordRow.source_ref == source_ref,
                )
                .order_by(EvidenceRecordRow.recorded_at, EvidenceRecordRow.id)
                .limit(1)
            ).first()
            if result is None:
                return None
            row, byte_size = result
            return self._record(row, byte_size)

    def find_by_source_ref_in_session(
        self,
        *,
        source: str,
        source_ref: str,
        session: Session,
    ) -> EvidenceRecord | None:
        """Resolve one source identity in the caller's transaction."""

        source = source.strip()
        source_ref = source_ref.strip()
        if not source or not source_ref:
            raise ValueError("Evidence source and source_ref are required")
        result = session.execute(
            select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
            .join(
                EvidenceBlobRow,
                EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256,
            )
            .where(
                EvidenceRecordRow.source == source,
                EvidenceRecordRow.source_ref == source_ref,
            )
            .order_by(EvidenceRecordRow.recorded_at, EvidenceRecordRow.id)
            .limit(1)
        ).first()
        if result is None:
            return None
        row, byte_size = result
        return self._record(row, byte_size)

    def find_binding_ids(
        self,
        *,
        target_evidence_ids: list[str],
        binding_contract_id: str,
        as_of: datetime,
    ) -> list[str]:
        """Find current immutable bindings without scanning the global ledger."""
        targets = sorted({item.strip() for item in target_evidence_ids if item.strip()})
        contract = binding_contract_id.strip()
        if not targets:
            return []
        if not contract:
            raise ValueError("binding_contract_id is required")
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        cutoff = as_of.astimezone(UTC)
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(EvidenceRecordRow.id)
                    .where(
                        EvidenceRecordRow.metadata_json["evidence_scope_contract_id"].as_string() == contract,
                        EvidenceRecordRow.metadata_json["target_evidence_id"].as_string().in_(targets),
                        EvidenceRecordRow.effective_at <= cutoff,
                        (EvidenceRecordRow.effective_until.is_(None) | (EvidenceRecordRow.effective_until > cutoff)),
                    )
                    .order_by(EvidenceRecordRow.id)
                )
            )

    def content(self, evidence_id: str) -> tuple[bytes, EvidenceRecord]:
        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            if blob is None:
                raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
            return blob.content_bytes, self._record(row, blob.byte_size)

    def verify(self, evidence_id: str) -> EvidenceVerification:
        _, verification = self.inspect_integrity(evidence_id)
        return verification

    def scan_integrity(
        self,
        *,
        limit: int = 500,
        offset: int = 0,
        excluded_sources: tuple[str, ...] = (),
    ) -> EvidenceIntegrityScan:
        """Verify a bounded record/blob snapshot, including records whose blob is missing."""
        if not 1 <= limit <= 1000:
            raise ValueError("Evidence integrity scan limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("Evidence integrity scan offset cannot be negative")
        excluded_sources = tuple(sorted({item.strip() for item in excluded_sources if item.strip()}))
        with Session(self.engine) as session:
            count_query = select(func.count()).select_from(EvidenceRecordRow)
            rows_query = (
                select(EvidenceRecordRow, EvidenceBlobRow)
                .outerjoin(EvidenceBlobRow, EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256)
                .order_by(EvidenceRecordRow.recorded_at, EvidenceRecordRow.id)
                .offset(offset)
                .limit(limit)
            )
            if excluded_sources:
                source_filter = EvidenceRecordRow.source.not_in(excluded_sources)
                count_query = count_query.where(source_filter)
                rows_query = rows_query.where(source_filter)
            total = int(session.scalar(count_query) or 0)
            rows = list(session.execute(rows_query).all())
            snapshots = [
                (
                    row.id,
                    row.blob_sha256,
                    blob.byte_size if blob is not None else None,
                    bytes(blob.content_bytes) if blob is not None else None,
                )
                for row, blob in rows
            ]

        findings: list[EvidenceIntegrityFinding] = []
        for evidence_id, declared_sha256, declared_byte_size, content in snapshots:
            if content is None:
                findings.append(
                    EvidenceIntegrityFinding(
                        evidence_id,
                        declared_sha256,
                        None,
                        None,
                        None,
                        ("EVIDENCE_BLOB_MISSING",),
                    )
                )
                continue
            actual_sha256 = hashlib.sha256(content).hexdigest()
            actual_byte_size = len(content)
            codes = []
            if not hmac_compare(declared_sha256, actual_sha256):
                codes.append("EVIDENCE_HASH_MISMATCH")
            if declared_byte_size != actual_byte_size:
                codes.append("EVIDENCE_SIZE_MISMATCH")
            if codes:
                findings.append(
                    EvidenceIntegrityFinding(
                        evidence_id,
                        declared_sha256,
                        actual_sha256,
                        declared_byte_size,
                        actual_byte_size,
                        tuple(codes),
                    )
                )

        scanned = len(snapshots)
        next_offset = offset + scanned if offset + scanned < total else None
        return EvidenceIntegrityScan(
            total=total,
            offset=offset,
            scanned=scanned,
            valid=scanned - len(findings),
            invalid=len(findings),
            next_offset=next_offset,
            findings=tuple(findings),
        )

    def inspect_integrity(self, evidence_id: str) -> tuple[EvidenceRecord, EvidenceVerification]:
        """Read record and blob in one snapshot and recompute the blob digest."""
        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            if blob is None:
                raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
            content = bytes(blob.content_bytes)
            record = self._record(row, blob.byte_size)
        actual = hashlib.sha256(content).hexdigest()
        verification = EvidenceVerification(
            record.id,
            record.sha256,
            actual,
            len(content),
            hmac_compare(record.sha256, actual),
        )
        return record, verification

    def inspect_integrity_in_session(
        self, evidence_id: str, *, session: Session
    ) -> tuple[EvidenceRecord, EvidenceVerification]:
        """Verify Evidence through the same transaction as its owning ledger."""

        row = session.get(EvidenceRecordRow, evidence_id)
        if row is None:
            raise KeyError(f"Unknown evidence: {evidence_id}")
        blob = session.get(EvidenceBlobRow, row.blob_sha256)
        if blob is None:
            raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
        content = bytes(blob.content_bytes)
        record = self._record(row, blob.byte_size)
        actual = hashlib.sha256(content).hexdigest()
        return record, EvidenceVerification(
            record.id,
            record.sha256,
            actual,
            len(content),
            hmac_compare(record.sha256, actual),
        )

    def require_current_in_session(
        self,
        evidence_ids: list[str],
        *,
        as_of: datetime,
        session: Session,
    ) -> None:
        """Apply currentness and integrity gates inside the owning transaction."""

        normalized = self._normalized_evidence_ids(evidence_ids)
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        current = as_of.astimezone(UTC)
        for evidence_id in normalized:
            record, verification = self.inspect_integrity_in_session(
                evidence_id, session=session
            )
            if not verification.valid:
                raise ValueError(f"Evidence failed hash verification: {evidence_id}")
            effective_at = self._stored_timestamp(record.effective_at)
            effective_until = (
                self._stored_timestamp(record.effective_until)
                if record.effective_until
                else None
            )
            if effective_at > current:
                raise ValueError(f"Evidence is not yet effective: {evidence_id}")
            if effective_until is not None and current >= effective_until:
                raise ValueError(f"Evidence is no longer effective: {evidence_id}")

    def retention(self, evidence_id: str, *, as_of: datetime | None = None) -> RetentionAssessment:
        record = self.get(evidence_id)
        class_value = record.metadata.get("retention_class")
        legal_hold = record.metadata.get("legal_hold", False)
        if class_value is None:
            return RetentionAssessment(record.id, None, legal_hold, None, "classification_required", False)

        retention_class = RetentionClass(class_value)
        recorded_at = datetime.fromisoformat(record.recorded_at.replace("Z", "+00:00"))
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        review_due = recorded_at.astimezone(UTC) + timedelta(days=RETENTION_REVIEW_DAYS[retention_class])
        now = (as_of or datetime.now(UTC)).astimezone(UTC)
        status = "legal_hold" if legal_hold else "review_due" if now >= review_due else "active"
        return RetentionAssessment(
            record.id,
            retention_class.value,
            legal_hold,
            review_due.isoformat(),
            status,
            status == "review_due",
        )

    def require_valid(self, evidence_ids: list[str]) -> None:
        normalized = self._normalized_evidence_ids(evidence_ids)
        for evidence_id in normalized:
            verification = self.verify(evidence_id)
            if not verification.valid:
                raise ValueError(f"Evidence failed hash verification: {evidence_id}")

    def require_current(
        self,
        evidence_ids: list[str],
        *,
        as_of: datetime | None = None,
    ) -> None:
        """Require immutable evidence that is effective at the execution decision time."""
        normalized = self._normalized_evidence_ids(evidence_ids)
        current = as_of or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        current = current.astimezone(UTC)
        for evidence_id in normalized:
            record, verification = self.inspect_integrity(evidence_id)
            if not verification.valid:
                raise ValueError(f"Evidence failed hash verification: {evidence_id}")
            effective_at = self._stored_timestamp(record.effective_at)
            effective_until = self._stored_timestamp(record.effective_until) if record.effective_until else None
            if effective_at > current:
                raise ValueError(f"Evidence is not yet effective: {evidence_id}")
            if effective_until is not None and current >= effective_until:
                raise ValueError(f"Evidence is no longer effective: {evidence_id}")

    @staticmethod
    def _normalized_evidence_ids(evidence_ids: list[str]) -> list[str]:
        normalized = [item.strip() for item in evidence_ids if item.strip()]
        if not normalized:
            raise ValueError("At least one immutable evidence record is required")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Duplicate evidence references are not allowed")
        return normalized

    @staticmethod
    def _stored_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def link(
        self,
        *,
        evidence_id: str,
        target_type: str,
        target_id: str,
        relationship: str,
        created_by: str,
    ) -> LineageEdge:
        source_record = self.get(evidence_id)
        if source_record.source in CLOSED_LOOP_RESERVED_SOURCES:
            raise ValueError(
                "Reserved closed-loop lineage requires its dedicated ledger"
            )
        target_type = target_type.strip().lower()
        target_id = target_id.strip()
        relationship = relationship.strip()
        if not target_type or not target_id or not relationship:
            raise ValueError("Lineage requires target_type, target_id, and relationship")
        if target_type == "evidence":
            target_record = self.get(target_id)
            if target_record.source in CLOSED_LOOP_RESERVED_SOURCES:
                raise ValueError(
                    "Reserved closed-loop lineage requires its dedicated ledger"
                )
            if target_id == evidence_id:
                raise ValueError("Evidence cannot derive from itself")
        try:
            with Session(self.engine) as session, session.begin():
                existing = self._lineage_row(
                    session,
                    evidence_id=evidence_id,
                    target_type=target_type,
                    target_id=target_id,
                    relationship=relationship,
                )
                if existing is not None:
                    return self._edge(existing)
                row = LineageEdgeRow(
                    id=new_id("lin"),
                    from_type="evidence",
                    from_id=evidence_id,
                    to_type=target_type,
                    to_id=target_id,
                    relationship=relationship,
                    created_by=created_by,
                    recorded_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                return self._edge(row)
        except IntegrityError:
            with Session(self.engine) as session:
                winner = self._lineage_row(
                    session,
                    evidence_id=evidence_id,
                    target_type=target_type,
                    target_id=target_id,
                    relationship=relationship,
                )
                if winner is None:
                    raise
                return self._edge(winner)

    def link_in_session(
        self,
        *,
        evidence_id: str,
        target_type: str,
        target_id: str,
        relationship: str,
        created_by: str,
        session: Session,
    ) -> LineageEdge:
        """Append lineage inside the caller's Evidence transaction."""

        source_row = session.get(EvidenceRecordRow, evidence_id)
        if source_row is None:
            raise KeyError(f"Unknown evidence: {evidence_id}")
        if source_row.source in CLOSED_LOOP_RESERVED_SOURCES:
            raise ValueError(
                "Reserved closed-loop lineage requires its dedicated ledger"
            )
        target_type = target_type.strip().lower()
        target_id = target_id.strip()
        relationship = relationship.strip()
        if not target_type or not target_id or not relationship:
            raise ValueError(
                "Lineage requires target_type, target_id, and relationship"
            )
        if target_type == "evidence":
            target_row = session.get(EvidenceRecordRow, target_id)
            if target_row is None:
                raise KeyError(f"Unknown evidence: {target_id}")
            if target_row.source in CLOSED_LOOP_RESERVED_SOURCES:
                raise ValueError(
                    "Reserved closed-loop lineage requires its dedicated ledger"
                )
            if target_id == evidence_id:
                raise ValueError("Evidence cannot derive from itself")
        existing = self._lineage_row(
            session,
            evidence_id=evidence_id,
            target_type=target_type,
            target_id=target_id,
            relationship=relationship,
        )
        if existing is not None:
            return self._edge(existing)
        row = LineageEdgeRow(
            id=new_id("lin"),
            from_type="evidence",
            from_id=evidence_id,
            to_type=target_type,
            to_id=target_id,
            relationship=relationship,
            created_by=created_by,
            recorded_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        return self._edge(row)

    @staticmethod
    def linked_target_ids_in_session(
        *,
        evidence_id: str,
        target_type: str,
        relationship: str,
        session: Session,
    ) -> list[str]:
        """Read one Evidence record's governed target IDs in its transaction."""

        return list(
            session.scalars(
                select(LineageEdgeRow.to_id)
                .where(
                    LineageEdgeRow.from_type == "evidence",
                    LineageEdgeRow.from_id == evidence_id,
                    LineageEdgeRow.to_type == target_type,
                    LineageEdgeRow.relationship == relationship,
                )
                .order_by(LineageEdgeRow.to_id)
            )
        )

    def lineage(self, evidence_id: str) -> list[LineageEdge]:
        self.get(evidence_id)
        with Session(self.engine) as session:
            rows = session.scalars(
                select(LineageEdgeRow)
                .where(
                    (LineageEdgeRow.from_type == "evidence") & (LineageEdgeRow.from_id == evidence_id)
                    | (LineageEdgeRow.to_type == "evidence") & (LineageEdgeRow.to_id == evidence_id)
                )
                .order_by(LineageEdgeRow.recorded_at, LineageEdgeRow.id)
            ).all()
        return [self._edge(row) for row in rows]

    def target_evidence_ids(
        self,
        *,
        target_type: str,
        target_id: str,
        relationship: str | None = None,
    ) -> list[str]:
        target_type = target_type.strip().lower()
        target_id = target_id.strip()
        if not target_type or not target_id:
            raise ValueError("Target evidence lookup requires target_type and target_id")
        relationship = relationship.strip() if relationship else None
        with Session(self.engine) as session:
            query = select(LineageEdgeRow.from_id).where(
                LineageEdgeRow.from_type == "evidence",
                LineageEdgeRow.to_type == target_type,
                LineageEdgeRow.to_id == target_id,
            )
            if relationship:
                query = query.where(LineageEdgeRow.relationship == relationship)
            return list(session.scalars(query.distinct().order_by(LineageEdgeRow.from_id)).all())

    @staticmethod
    def _record(row: EvidenceRecordRow, byte_size: int) -> EvidenceRecord:
        effective_at = row.effective_at
        recorded_at = row.recorded_at
        if effective_at.tzinfo is None:
            effective_at = effective_at.replace(tzinfo=UTC)
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        effective_until = row.effective_until
        if effective_until is not None and effective_until.tzinfo is None:
            effective_until = effective_until.replace(tzinfo=UTC)
        return EvidenceRecord(
            row.id,
            row.blob_sha256,
            byte_size,
            row.filename,
            row.content_type,
            row.source,
            row.source_ref,
            EvidenceGrade(row.grade),
            effective_at.astimezone(UTC).isoformat(),
            effective_until.astimezone(UTC).isoformat()
            if effective_until
            else None,
            recorded_at.astimezone(UTC).isoformat(),
            row.created_by,
            row.metadata_json,
        )

    @staticmethod
    def _captured_row(
        session: Session,
        *,
        digest: str,
        source: str,
        source_ref: str,
        effective_at: datetime,
    ) -> EvidenceRecordRow | None:
        return session.scalar(
            select(EvidenceRecordRow).where(
                EvidenceRecordRow.blob_sha256 == digest,
                EvidenceRecordRow.source == source,
                EvidenceRecordRow.source_ref == source_ref,
                EvidenceRecordRow.effective_at == effective_at,
            )
        )

    @staticmethod
    def _source_ref_row(
        session: Session,
        *,
        source: str,
        source_ref: str,
    ) -> EvidenceRecordRow | None:
        return session.scalar(
            select(EvidenceRecordRow).where(
                EvidenceRecordRow.source == source,
                EvidenceRecordRow.source_ref == source_ref,
            )
        )

    @staticmethod
    def _lineage_row(
        session: Session,
        *,
        evidence_id: str,
        target_type: str,
        target_id: str,
        relationship: str,
    ) -> LineageEdgeRow | None:
        return session.scalar(
            select(LineageEdgeRow).where(
                LineageEdgeRow.from_type == "evidence",
                LineageEdgeRow.from_id == evidence_id,
                LineageEdgeRow.to_type == target_type,
                LineageEdgeRow.to_id == target_id,
                LineageEdgeRow.relationship == relationship,
            )
        )

    @staticmethod
    def _edge(row: LineageEdgeRow) -> LineageEdge:
        return LineageEdge(
            row.id,
            row.from_type,
            row.from_id,
            row.to_type,
            row.to_id,
            row.relationship,
            row.created_by,
            row.recorded_at.isoformat(),
        )


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


_CLOSED_LOOP_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_CLOSED_LOOP_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLOSED_LOOP_CURRENCY = re.compile(r"^[A-Z]{3}$")


def _closed_loop_token(
    value: object, field: str, *, optional: bool = False
) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise PermissionError(f"Closed-loop {field} is invalid")
    normalized = value.strip()
    if optional and not normalized:
        return None
    if not _CLOSED_LOOP_TOKEN.fullmatch(normalized):
        raise PermissionError(f"Closed-loop {field} is invalid")
    return normalized


def _closed_loop_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _CLOSED_LOOP_SHA256.fullmatch(value):
        raise PermissionError(f"Closed-loop {field} is invalid")
    return value


def _closed_loop_int(
    value: object, field: str, *, positive: bool, maximum: int
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < (1 if positive else 0)
        or value > maximum
    ):
        raise PermissionError(f"Closed-loop {field} is invalid")
    return value


def _closed_loop_time(value: object, field: str) -> tuple[datetime, str]:
    if not isinstance(value, str):
        raise PermissionError(f"Closed-loop {field} is invalid")
    parsed = parse_timestamp(value, field)
    return parsed, parsed.isoformat()


def _closed_loop_decimal(
    value: object,
    field: str,
    *,
    maximum_scale: int,
    maximum_integer_digits: int | None = None,
) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise PermissionError(f"Closed-loop {field} is invalid")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise PermissionError(f"Closed-loop {field} is invalid") from None
    if not parsed.is_finite():
        raise PermissionError(f"Closed-loop {field} is invalid")
    _, digits, exponent = parsed.as_tuple()
    if exponent < -maximum_scale:
        excess_digits = -maximum_scale - exponent
        if any(digit != 0 for digit in digits[-excess_digits:]):
            raise PermissionError(f"Closed-loop {field} is not exactly storable")
    if (
        maximum_integer_digits is not None
        and parsed.copy_abs() >= Decimal(10) ** maximum_integer_digits
    ):
        raise PermissionError(f"Closed-loop {field} is not exactly storable")
    return parsed


def _closed_loop_metric_currency(*, metric_unit: str, value: object) -> str | None:
    if metric_unit == "minor_currency_units":
        if not isinstance(value, str) or not _CLOSED_LOOP_CURRENCY.fullmatch(value):
            raise PermissionError("Closed-loop monetary metric currency is invalid")
        return value
    if value is not None:
        raise PermissionError("Closed-loop non-monetary metric currency must be null")
    return None


def _closed_loop_require_association_only(
    purpose: str, claims: Mapping[str, Any]
) -> None:
    if purpose in {"experiment", "business_outcome"}:
        if claims.get("causal_claim_allowed") is not False:
            raise PermissionError("Closed-loop causal claims are not admitted")
    elif purpose == "cost" and "causal_claim_allowed" in claims:
        raise PermissionError("Closed-loop cost claims cannot declare causality")


def _closed_loop_claims(purpose: str, claims: dict[str, Any]) -> dict[str, Any]:
    _closed_loop_require_association_only(purpose, claims)
    if purpose == "review_event":
        event_type = _closed_loop_token(
            claims["event_type"], "review_event.event_type"
        )
        replacement = _closed_loop_token(
            claims["replacement_bundle_id"],
            "review_event.replacement_bundle_id",
            optional=True,
        )
        if event_type not in {
            "review_requested",
            "invalidated",
            "revoked",
            "superseded",
        } or (event_type == "superseded") != (replacement is not None):
            raise PermissionError("Closed-loop review claims are invalid")
        return {
            "bundle_id": _closed_loop_token(
                claims["bundle_id"], "review_event.bundle_id"
            ),
            "event_type": event_type,
            "reason_code": _closed_loop_token(
                claims["reason_code"], "review_event.reason_code"
            ),
            "replacement_bundle_id": replacement,
            "requested_by_actor_id": _closed_loop_token(
                claims["requested_by_actor_id"],
                "review_event.requested_by_actor_id",
            ),
        }
    if purpose == "experiment":
        window_start, window_start_text = _closed_loop_time(
            claims["window_start"], "experiment.window_start"
        )
        window_end, window_end_text = _closed_loop_time(
            claims["window_end"], "experiment.window_end"
        )
        treatment = _closed_loop_token(
            claims["treatment_ref"], "experiment.treatment_ref"
        )
        control = _closed_loop_token(
            claims["control_ref"], "experiment.control_ref", optional=True
        )
        sample = _closed_loop_int(
            claims["sample_size"],
            "experiment.sample_size",
            positive=True,
            maximum=1_000_000_000,
        )
        minimum = _closed_loop_int(
            claims["minimum_sample_size"],
            "experiment.minimum_sample_size",
            positive=True,
            maximum=1_000_000_000,
        )
        causal = False
        independent_review = claims["independent_review_passed"]
        confidence = _closed_loop_decimal(
            claims["confidence_level_decimal"],
            "experiment.confidence_level_decimal",
            maximum_scale=6,
        )
        if (
            not isinstance(causal, bool)
            or not isinstance(independent_review, bool)
            or confidence <= 0
            or confidence > 1
            or window_start >= window_end
            or treatment == control
        ):
            raise PermissionError("Closed-loop experiment claims are invalid")
        metric_unit = _closed_loop_token(
            claims["metric_unit"], "experiment.metric_unit"
        )
        return {
            "agent_run_ref": _closed_loop_token(
                claims["agent_run_ref"], "experiment.agent_run_ref"
            ),
            "experiment_ref": _closed_loop_token(
                claims["experiment_ref"], "experiment.experiment_ref"
            ),
            "method": _closed_loop_token(
                claims["method"], "experiment.method"
            ),
            "treatment_ref": treatment,
            "control_ref": control,
            "sample_size": sample,
            "minimum_sample_size": minimum,
            "metric_id": _closed_loop_token(
                claims["metric_id"], "experiment.metric_id"
            ),
            "metric_unit": metric_unit,
            "metric_currency": _closed_loop_metric_currency(
                metric_unit=metric_unit, value=claims["metric_currency"]
            ),
            "window_start": window_start_text,
            "window_end": window_end_text,
            "confidence_level_decimal": format(confidence, "f"),
            "independent_review_passed": independent_review,
            "causal_claim_allowed": causal,
        }
    if purpose == "cost":
        period_start, period_start_text = _closed_loop_time(
            claims["period_start"], "cost.period_start"
        )
        period_end, period_end_text = _closed_loop_time(
            claims["period_end"], "cost.period_end"
        )
        currency = claims["currency"]
        if (
            not isinstance(currency, str)
            or not _CLOSED_LOOP_CURRENCY.fullmatch(currency)
            or period_start >= period_end
        ):
            raise PermissionError("Closed-loop cost claims are invalid")
        return {
            "agent_run_ref": _closed_loop_token(
                claims["agent_run_ref"], "cost.agent_run_ref"
            ),
            "experiment_ref": _closed_loop_token(
                claims["experiment_ref"], "cost.experiment_ref"
            ),
            "outcome_ref": _closed_loop_token(
                claims["outcome_ref"], "cost.outcome_ref"
            ),
            "cost_ref": _closed_loop_token(claims["cost_ref"], "cost.cost_ref"),
            "amount_minor_units": _closed_loop_int(
                claims["amount_minor_units"],
                "cost.amount_minor_units",
                positive=False,
                maximum=10**18,
            ),
            "currency": currency,
            "period_start": period_start_text,
            "period_end": period_end_text,
            "allocation_method": _closed_loop_token(
                claims["allocation_method"], "cost.allocation_method"
            ),
        }
    interval_start, interval_start_text = _closed_loop_time(
        claims["interval_start"], "outcome.interval_start"
    )
    interval_end, interval_end_text = _closed_loop_time(
        claims["interval_end"], "outcome.interval_end"
    )
    decimal_value = _closed_loop_decimal(
        claims["value_decimal"],
        "outcome.value_decimal",
        maximum_scale=12,
        maximum_integer_digits=18,
    )
    confidence = _closed_loop_decimal(
        claims["confidence_level_decimal"],
        "outcome.confidence_level_decimal",
        maximum_scale=6,
    )
    causal = False
    independent_review = claims["independent_review_passed"]
    if (
        not isinstance(causal, bool)
        or not isinstance(independent_review, bool)
        or confidence <= 0
        or confidence > 1
        or interval_start >= interval_end
    ):
        raise PermissionError("Closed-loop outcome claims are invalid")
    metric_unit = _closed_loop_token(claims["metric_unit"], "outcome.metric_unit")
    return {
        "agent_run_ref": _closed_loop_token(
            claims["agent_run_ref"], "outcome.agent_run_ref"
        ),
        "outcome_ref": _closed_loop_token(
            claims["outcome_ref"], "outcome.outcome_ref"
        ),
        "experiment_ref": _closed_loop_token(
            claims["experiment_ref"], "outcome.experiment_ref"
        ),
        "metric_id": _closed_loop_token(
            claims["metric_id"], "outcome.metric_id"
        ),
        "metric_unit": metric_unit,
        "metric_currency": _closed_loop_metric_currency(
            metric_unit=metric_unit, value=claims["metric_currency"]
        ),
        "method": _closed_loop_token(claims["method"], "outcome.method"),
        "sample_size": _closed_loop_int(
            claims["sample_size"],
            "outcome.sample_size",
            positive=True,
            maximum=1_000_000_000,
        ),
        "interval_start": interval_start_text,
        "interval_end": interval_end_text,
        "value_decimal": format(decimal_value, "f"),
        "confidence_level_decimal": format(confidence, "f"),
        "independent_review_passed": independent_review,
        "causal_claim_allowed": causal,
    }


def _closed_loop_postgres_jsonb_text(value: Any) -> str:
    """Serialize the bounded closed-loop projections like PostgreSQL jsonb::text."""

    if isinstance(value, Mapping):
        keys = list(value)
        if any(not isinstance(key, str) for key in keys):
            raise TypeError("Closed-loop JSON object keys must be strings")
        keys.sort(key=lambda key: (len(key.encode("utf-8")), key.encode("utf-8")))
        return "{" + ", ".join(
            f"{json.dumps(key, ensure_ascii=False)}: "
            f"{_closed_loop_postgres_jsonb_text(value[key])}"
            for key in keys
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(
            _closed_loop_postgres_jsonb_text(item) for item in value
        ) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _closed_loop_postgres_jsonb_sha256(value: Any) -> str:
    return hashlib.sha256(
        _closed_loop_postgres_jsonb_text(value).encode("utf-8")
    ).hexdigest()


def _closed_loop_claims_sha256(claims: Mapping[str, Any]) -> str:
    """Match PostgreSQL jsonb::text for the frozen scalar-only claims schemas."""

    return _closed_loop_postgres_jsonb_sha256(claims)


class TeamAgentEvidenceAuthorityAdapter:
    """Purpose-specific signer for reserved TeamAgent governance Evidence."""

    def __init__(self, evidence: EvidenceService) -> None:
        self.evidence = evidence

    def capture(
        self,
        *,
        principal: Any,
        purpose: str,
        claims: dict[str, Any],
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_authority_sha256: str,
        candidate_author_actor_id: str,
        human_owner_actor_id: str,
        effective_at: str,
        effective_until: str | None,
        session: Session | None = None,
    ) -> EvidenceRecord:
        contract = TEAM_AGENT_AUTHORITY_CONTRACTS.get(purpose)
        if contract is None or set(claims) != contract["fields"]:
            raise ValueError("Team-agent authority claims contract drifted")
        actor_id = str(getattr(principal, "actor_id", "") or "").strip()
        roles = frozenset(getattr(principal, "roles", ()))
        if not actor_id or not roles.intersection(contract["roles"]):
            raise PermissionError("Team-agent authority signer role is not admitted")
        if actor_id in {candidate_author_actor_id, human_owner_actor_id}:
            raise PermissionError(
                "Team-agent authority signer must differ from author and owner"
            )
        if getattr(principal, "tenant_ref", None) != tenant_ref:
            raise PermissionError("Team-agent authority signer tenant differs")
        can_access = getattr(principal, "can_access_store", None)
        if not callable(can_access) or not can_access(store_ref):
            raise PermissionError("Team-agent authority signer cannot access store")
        payload_sha256 = str(claims[contract["payload_field"]]).strip().lower()
        if (
            len(payload_sha256) != 64
            or any(character not in "0123456789abcdef" for character in payload_sha256)
            or payload_sha256 == "0" * 64
        ):
            raise ValueError("Team-agent authority payload hash is invalid")
        scope = {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_authority_sha256": scope_authority_sha256,
        }
        binding = {
            "purpose": purpose,
            "actor_id": actor_id,
            "scope": scope,
            "payload_sha256": payload_sha256,
            "claims": claims,
        }
        binding_sha256 = hashlib.sha256(
            json.dumps(
                binding,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        source = str(contract["source"])
        source_ref = f"{source}://{binding_sha256}"
        grade = contract["grade"]
        payload = {
            "contract_id": "kjds-governed-team-agent-evolution-evidence-v1",
            "source_contract_id": contract["contract_id"],
            "scope": scope,
            "purpose": purpose,
            "claims": claims,
            "payload_sha256": payload_sha256,
            "source": source,
            "source_ref": source_ref,
            "grade": grade.value,
            "payload_status": "hash_and_code_only",
            "contains_customer_data": False,
            "external_write_allowed": False,
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self.evidence.capture(
            content=content,
            filename=f"{binding_sha256}.json",
            content_type="application/json",
            source=source,
            source_ref=source_ref,
            grade=grade,
            effective_at=effective_at,
            effective_until=effective_until,
            created_by=actor_id,
            metadata={
                "contract_id": "kjds-governed-team-agent-evolution-evidence-v1",
                "source_contract_id": contract["contract_id"],
                **scope,
                "evolution_purpose": purpose,
                "payload_sha256": payload_sha256,
                "claims_sha256": hashlib.sha256(
                    json.dumps(
                        claims,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                **claims,
                "retention_class": "security",
                "legal_hold": False,
            },
            _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
            _session=session,
        )


class ClosedLoopEvidenceAuthorityAdapter:
    """Server-only intake for independent experiment, cost, and Outcome receipts."""

    def __init__(
        self,
        evidence: EvidenceService,
        *,
        scope_grants: Any,
        attestation_authorities: Mapping[str, Any],
        issuer_port: Any | None = None,
        receipt_registrars: Mapping[str, Any] | None = None,
        clock: Any | None = None,
    ) -> None:
        self.evidence = evidence
        self.scope_grants = scope_grants
        if set(attestation_authorities) != set(CLOSED_LOOP_AUTHORITY_CONTRACTS):
            raise ValueError("Three registered closed-loop authorities are required")
        self.attestation_authorities = dict(attestation_authorities)
        authority_ids = []
        for purpose, authority in self.attestation_authorities.items():
            expected = CLOSED_LOOP_AUTHORITY_CONTRACTS[purpose]["issuer_id"]
            if (
                getattr(authority, "authority_id", None) != expected
                or not callable(getattr(authority, "project", None))
                or not callable(getattr(authority, "verify_receipt", None))
            ):
                raise ValueError("Closed-loop authority registration drifted")
            authority_ids.append(expected)
        if len(set(authority_ids)) != len(authority_ids):
            raise ValueError("Closed-loop authorities must be independent")
        self.issuer_port = issuer_port
        self.receipt_registrars = dict(receipt_registrars or {})
        if (
            evidence.engine.dialect.name == "postgresql"
            and not callable(getattr(issuer_port, "issue_evidence", None))
        ):
            raise RuntimeError("Dedicated PostgreSQL closed-loop issuer is required")
        if evidence.engine.dialect.name == "postgresql" and (
            set(self.receipt_registrars) != set(CLOSED_LOOP_AUTHORITY_CONTRACTS)
            or any(
                not callable(getattr(registrar, "register_authority_receipt", None))
                for registrar in self.receipt_registrars.values()
            )
        ):
            raise RuntimeError(
                "Independent PostgreSQL closed-loop registrars are required"
            )
        self.clock = clock or (lambda: datetime.now(UTC))

    def capture_experiment(self, **kwargs: Any) -> EvidenceRecord:
        return self._capture(purpose="experiment", **kwargs)

    def capture_cost(self, **kwargs: Any) -> EvidenceRecord:
        return self._capture(purpose="cost", **kwargs)

    def capture_business_outcome(self, **kwargs: Any) -> EvidenceRecord:
        return self._capture(purpose="business_outcome", **kwargs)

    def capture_review_event(self, **kwargs: Any) -> EvidenceRecord:
        return self._capture(purpose="review_event", **kwargs)

    def dispose(self) -> None:
        for registrar in self.receipt_registrars.values():
            dispose = getattr(registrar, "dispose", None)
            if callable(dispose):
                dispose()
        dispose_issuer = getattr(self.issuer_port, "dispose", None)
        if callable(dispose_issuer):
            dispose_issuer()

    def _capture(
        self,
        *,
        purpose: str,
        principal: Any,
        store_ref: str,
        data_as_of: datetime,
        attestation_ref: str,
        session: Session | None = None,
    ) -> EvidenceRecord:
        contract = CLOSED_LOOP_AUTHORITY_CONTRACTS[purpose]
        actor_id = str(getattr(principal, "actor_id", "") or "").strip()
        roles = frozenset(getattr(principal, "roles", ()))
        store = str(store_ref or "").strip()
        reference = str(attestation_ref or "").strip()
        if not actor_id or not roles.intersection({"operator", "compliance", "admin"}):
            raise PermissionError("Closed-loop intake signer role is not admitted")
        can_access = getattr(principal, "can_access_store", None)
        if not callable(can_access) or not can_access(store):
            raise PermissionError("Closed-loop intake signer cannot access store")
        checked_at = self.clock()
        if not isinstance(checked_at, datetime) or checked_at.tzinfo is None:
            raise ValueError("Closed-loop authority clock must include a timezone")
        checked_at = checked_at.astimezone(UTC)
        if not isinstance(data_as_of, datetime) or data_as_of.tzinfo is None:
            raise ValueError("Closed-loop data_as_of must include a timezone")
        cutoff = data_as_of.astimezone(UTC)
        if cutoff > checked_at or not reference:
            raise ValueError("Closed-loop cutoff or attestation reference is invalid")
        authority = self.scope_grants.current(
            principal=principal,
            store_ref=store,
            as_of=checked_at,
        )
        tenant_ref = getattr(principal, "tenant_ref", None)
        raw_scope = {
            "tenant_ref": authority.get("tenant_ref"),
            "entity_ref": authority.get("entity_ref"),
            "store_ref": authority.get("store_ref"),
            "scope_grant_authority_sha256": authority.get("authority_sha256"),
        }
        if (
            authority.get("status") != "ready"
            or not isinstance(tenant_ref, str)
            or any(not isinstance(value, str) for value in raw_scope.values())
        ):
            raise PermissionError("Closed-loop exact scope authority is invalid")
        exact_scope = {
            "tenant_ref": _closed_loop_token(
                raw_scope["tenant_ref"], "tenant_ref"
            ),
            "entity_ref": _closed_loop_token(
                raw_scope["entity_ref"], "entity_ref"
            ),
            "store_ref": _closed_loop_token(raw_scope["store_ref"], "store_ref"),
            "scope_grant_authority_sha256": _closed_loop_sha256(
                raw_scope["scope_grant_authority_sha256"],
                "scope_grant_authority_sha256",
            ),
        }
        if exact_scope["tenant_ref"] != tenant_ref or exact_scope["store_ref"] != store:
            raise PermissionError("Closed-loop exact scope authority is invalid")
        attestation_authority = self.attestation_authorities[purpose]
        projection = attestation_authority.project(
            purpose=purpose,
            attestation_ref=reference,
            exact_scope=exact_scope,
            data_as_of=cutoff,
            checked_at=checked_at,
        )
        claims = projection.get("claims")
        issuer_actor_id = projection.get("issuer_actor_id")
        authority_receipt_id = projection.get("authority_receipt_id")
        if (
            projection.get("status") != "ready"
            or projection.get("purpose") != purpose
            or projection.get("attestation_ref") != reference
            or projection.get("contract_id") != contract["contract_id"]
            or projection.get("issuer_id") != contract["issuer_id"]
            or projection.get("issuer_contract_id")
            != contract["issuer_contract_id"]
            or projection.get("issuer_contract_version")
            != contract["issuer_contract_version"]
            or projection.get("issuer_contract_sha256")
            != contract["issuer_contract_sha256"]
            or projection.get("schema_sha256") != contract["schema_sha256"]
            or projection.get("exact_scope") != exact_scope
            or not isinstance(claims, dict)
            or set(claims) != contract["fields"]
            or not isinstance(issuer_actor_id, str)
            or not isinstance(authority_receipt_id, str)
        ):
            raise PermissionError("Closed-loop upstream attestation is invalid")
        issuer_actor_id = _closed_loop_token(issuer_actor_id, "issuer_actor_id")
        authority_receipt_id = _closed_loop_token(
            authority_receipt_id, "authority_receipt_id"
        )
        if issuer_actor_id == actor_id:
            raise PermissionError("Closed-loop authority must be independent")
        claims = _closed_loop_claims(purpose, claims)
        if (
            purpose == "review_event"
            and claims["requested_by_actor_id"] == issuer_actor_id
        ):
            raise PermissionError(
                "Closed-loop review requester and issuer must be independent"
            )
        effective_at = parse_timestamp(
            str(projection.get("effective_at") or ""), "effective_at"
        )
        recorded_at = parse_timestamp(
            str(projection.get("recorded_at") or ""), "recorded_at"
        )
        effective_until = parse_timestamp(
            str(projection.get("effective_until") or ""), "effective_until"
        )
        review_due_at = parse_timestamp(
            str(projection.get("review_due_at") or ""), "review_due_at"
        )
        if not (
            effective_at <= recorded_at <= cutoff
            and cutoff <= checked_at
            and effective_at <= cutoff
            and checked_at < review_due_at <= effective_until
        ):
            raise PermissionError("Closed-loop attestation chronology is invalid")
        claims_sha256 = _closed_loop_claims_sha256(claims)
        attestation_envelope = {
            "contract_id": contract["contract_id"],
            "purpose": purpose,
            "attestation_ref": reference,
            "authority_receipt_id": authority_receipt_id,
            "issuer_id": contract["issuer_id"],
            "issuer_contract_id": contract["issuer_contract_id"],
            "issuer_contract_version": contract["issuer_contract_version"],
            "issuer_contract_sha256": contract["issuer_contract_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "issuer_actor_id": issuer_actor_id,
            "exact_scope": exact_scope,
            "data_as_of": cutoff.isoformat(),
            "effective_at": effective_at.isoformat(),
            "effective_until": effective_until.isoformat(),
            "recorded_at": recorded_at.isoformat(),
            "review_due_at": review_due_at.isoformat(),
            "claims": claims,
            "claims_sha256": claims_sha256,
        }
        attestation_sha256 = hashlib.sha256(
            json.dumps(
                attestation_envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        if projection.get("attestation_sha256") != attestation_sha256:
            raise PermissionError("Closed-loop attestation hash drifted")
        signature_sha256 = _closed_loop_sha256(
            projection.get("attestation_signature_sha256"),
            "attestation_signature_sha256",
        )
        verified = attestation_authority.verify_receipt(
            attestation_sha256=attestation_sha256,
            attestation_signature_sha256=signature_sha256,
            expected_envelope=attestation_envelope,
        )
        if (
            not isinstance(verified, Mapping)
            or verified.get("status") != "verified"
            or verified.get("authority_id") != contract["issuer_id"]
            or verified.get("attestation_sha256") != attestation_sha256
        ):
            raise PermissionError("Closed-loop authority receipt is invalid")
        payload = {
            **attestation_envelope,
            "attestation_sha256": attestation_sha256,
            "attestation_signature_sha256": signature_sha256,
            "payload_status": "authority_projection_only",
            "contains_customer_data": False,
            "external_write_allowed": False,
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        content_sha256 = hashlib.sha256(content).hexdigest()
        source = str(contract["source"])
        scope_binding_sha256 = hashlib.sha256(
            json.dumps(
                exact_scope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        source_ref = (
            f"{source}://{scope_binding_sha256}/"
            f"{claims_sha256}/{content_sha256}"
        )
        metadata = {
            "contract_id": contract["contract_id"],
            "closed_loop_purpose": purpose,
            "closed_loop_claims_sha256": claims_sha256,
            "closed_loop_attestation_sha256": attestation_sha256,
            "closed_loop_attestation_signature_sha256": signature_sha256,
            "closed_loop_attestation_ref": reference,
            "closed_loop_authority_receipt_id": authority_receipt_id,
            "closed_loop_issuer_id": contract["issuer_id"],
            "closed_loop_issuer_contract_id": contract["issuer_contract_id"],
            "closed_loop_issuer_contract_version": (
                contract["issuer_contract_version"]
            ),
            "closed_loop_issuer_contract_sha256": (
                contract["issuer_contract_sha256"]
            ),
            "closed_loop_schema_sha256": contract["schema_sha256"],
            "closed_loop_issuer_actor_id": issuer_actor_id,
            "closed_loop_data_as_of": cutoff.isoformat(),
            "closed_loop_recorded_at": recorded_at.isoformat(),
            "closed_loop_review_due_at": review_due_at.isoformat(),
            "closed_loop_claims": claims,
            "closed_loop_scope_binding_sha256": scope_binding_sha256,
            **exact_scope,
            "retention_class": "compliance",
            "legal_hold": False,
        }

        def persist(target_session: Session) -> EvidenceRecord:
            return self.evidence.capture(
                content=content,
                filename=f"{purpose}-{content_sha256}.json",
                content_type="application/json",
                source=source,
                source_ref=source_ref,
                grade=EvidenceGrade.A,
                effective_at=effective_at.isoformat(),
                effective_until=effective_until.isoformat(),
                created_by=issuer_actor_id,
                metadata=metadata,
                _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
                _session=target_session,
                _recorded_at=recorded_at.isoformat(),
            )

        if self.evidence.engine.dialect.name == "postgresql":
            if session is not None:
                raise RuntimeError(
                    "PostgreSQL closed-loop issuance uses an isolated transaction"
                )
            metadata_sha256 = _closed_loop_postgres_jsonb_sha256(metadata)
            # The registrar and issuer use separate least-privilege database
            # identities.  Deriving the Evidence identifier from their shared,
            # immutable receipt tuple makes a crash between those transactions
            # replayable instead of stranding the authority receipt behind a
            # newly generated identifier.
            evidence_id = "evd_" + hashlib.sha256(
                json.dumps(
                    {
                        "authority_receipt_id": authority_receipt_id,
                        "content_sha256": content_sha256,
                        "metadata_sha256": metadata_sha256,
                        "purpose": purpose,
                        "source": source,
                        "source_ref": source_ref,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()[:40]
            authority_receipt = {
                "authority_receipt_id": authority_receipt_id,
                "purpose": purpose,
                "evidence_id": evidence_id,
                "content_sha256": content_sha256,
                "metadata_sha256": metadata_sha256,
                "source": source,
                "source_ref": source_ref,
                "attestation_sha256": attestation_sha256,
                "attestation_signature_sha256": signature_sha256,
                "issuer_id": contract["issuer_id"],
                "issuer_contract_id": contract["issuer_contract_id"],
                "issuer_contract_version": contract["issuer_contract_version"],
                "issuer_contract_sha256": contract["issuer_contract_sha256"],
                "schema_sha256": contract["schema_sha256"],
                "issuer_actor_id": issuer_actor_id,
                **exact_scope,
                "data_as_of": cutoff.isoformat(),
                "effective_at": effective_at.isoformat(),
                "effective_until": effective_until.isoformat(),
                "recorded_at": recorded_at.isoformat(),
                "review_due_at": review_due_at.isoformat(),
            }
            registered_id = self.receipt_registrars[
                purpose
            ].register_authority_receipt(receipt=authority_receipt)
            if registered_id != authority_receipt_id:
                raise PermissionError(
                    "Closed-loop authority registration binding drifted"
                )
            returned_id = self.issuer_port.issue_evidence(
                authority_receipt_id=authority_receipt_id,
                evidence_id=evidence_id,
                content=content,
                filename=f"{purpose}-{content_sha256}.json",
                source=source,
                source_ref=source_ref,
                effective_at=effective_at,
                effective_until=effective_until,
                metadata=metadata,
                attestation_sha256=attestation_sha256,
                attestation_signature_sha256=signature_sha256,
            )
            record = self.evidence.get(returned_id)
            if (
                record.id != evidence_id
                or record.sha256 != content_sha256
                or record.source != source
                or record.source_ref != source_ref
                or record.metadata.get("closed_loop_authority_receipt_id")
                != authority_receipt_id
            ):
                raise PermissionError("Closed-loop issuer receipt binding drifted")
            return record
        if session is not None:
            return persist(session)
        with self.evidence.transaction() as target_session:
            return persist(target_session)


class GlobalDataCoverageEvidenceAuthorityAdapter:
    """Server-only projector for independently attested coverage intake Evidence."""

    def __init__(
        self,
        evidence: EvidenceService,
        *,
        scope_grants: Any,
        intake_authority: Any,
        issuance_signing_key: bytes | str | None = None,
        issuer_port: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.evidence = evidence
        self.scope_grants = scope_grants
        self.intake_authority = intake_authority
        self._issuer_port = issuer_port
        is_postgres = evidence.engine.dialect.name == "postgresql"
        if is_postgres:
            if issuance_signing_key is not None:
                raise ValueError("PostgreSQL coverage issuer must not hold an application signing key")
            if self._issuer_port is None or not callable(
                getattr(self._issuer_port, "issue_evidence", None)
            ):
                raise RuntimeError("Dedicated PostgreSQL coverage issuer port is required")
            self.issuance_signing_key = None
            self.issuance_signing_key_sha256 = None
        else:
            key = (
                issuance_signing_key.encode()
                if isinstance(issuance_signing_key, str)
                else issuance_signing_key
            )
            if not isinstance(key, bytes) or len(key) < 32:
                raise ValueError(
                    "SQLite coverage intake signing key must be at least 32 bytes"
                )
            self.issuance_signing_key = key.hex()
            self.issuance_signing_key_sha256 = hashlib.sha256(
                self.issuance_signing_key.encode()
            ).hexdigest()
        self.clock = clock or (lambda: datetime.now(UTC))

    def capture_manifest(
        self,
        *,
        principal: Any,
        store_ref: str,
        data_as_of: datetime,
        attestation_ref: str,
        session: Session | None = None,
    ) -> EvidenceRecord:
        return self._capture(
            purpose="manifest",
            principal=principal,
            store_ref=store_ref,
            data_as_of=data_as_of,
            attestation_ref=attestation_ref,
            session=session,
        )

    def capture_native_caps(
        self,
        *,
        principal: Any,
        store_ref: str,
        data_as_of: datetime,
        attestation_ref: str,
        session: Session | None = None,
    ) -> EvidenceRecord:
        return self._capture(
            purpose="native_caps",
            principal=principal,
            store_ref=store_ref,
            data_as_of=data_as_of,
            attestation_ref=attestation_ref,
            session=session,
        )

    def capture_denominator(
        self,
        *,
        principal: Any,
        store_ref: str,
        data_as_of: datetime,
        attestation_ref: str,
        session: Session | None = None,
    ) -> EvidenceRecord:
        return self._capture(
            purpose="denominator",
            principal=principal,
            store_ref=store_ref,
            data_as_of=data_as_of,
            attestation_ref=attestation_ref,
            session=session,
        )

    def _capture(
        self,
        *,
        purpose: str,
        principal: Any,
        store_ref: str,
        data_as_of: datetime,
        attestation_ref: str,
        session: Session | None,
    ) -> EvidenceRecord:
        contract = COVERAGE_INTAKE_CONTRACTS[purpose]
        actor_id = str(getattr(principal, "actor_id", "") or "").strip()
        roles = frozenset(getattr(principal, "roles", ()))
        store = str(store_ref or "").strip()
        reference = str(attestation_ref or "").strip()
        if not actor_id or not roles.intersection({"operator", "compliance", "admin"}):
            raise PermissionError("Coverage intake issuer role is not admitted")
        can_access = getattr(principal, "can_access_store", None)
        if not callable(can_access) or not can_access(store):
            raise PermissionError("Coverage intake issuer cannot access store")
        checked_at = self.clock()
        if not isinstance(checked_at, datetime) or checked_at.tzinfo is None:
            raise ValueError("Coverage intake authority clock must include a timezone")
        checked_at = checked_at.astimezone(UTC)
        if not isinstance(data_as_of, datetime) or data_as_of.tzinfo is None:
            raise ValueError("Coverage intake data_as_of must include a timezone")
        cutoff = data_as_of.astimezone(UTC)
        if cutoff > checked_at or not reference:
            raise ValueError("Coverage intake cutoff or attestation reference is invalid")
        authority = self.scope_grants.current(
            principal=principal,
            store_ref=store,
            as_of=checked_at,
        )
        if authority.get("status") != "ready":
            raise PermissionError("Coverage intake exact scope authority is not ready")
        tenant_ref = str(getattr(principal, "tenant_ref", "") or "").strip()
        entity_ref = str(authority.get("entity_ref") or "").strip()
        authority_store = str(authority.get("store_ref") or "").strip()
        authority_tenant = str(authority.get("tenant_ref") or "").strip()
        authority_sha256 = str(authority.get("authority_sha256") or "").strip().lower()
        if (
            not tenant_ref
            or not entity_ref
            or authority_store != store
            or authority_tenant != tenant_ref
            or len(authority_sha256) != 64
            or any(character not in "0123456789abcdef" for character in authority_sha256)
        ):
            raise PermissionError("Coverage intake exact scope authority binding is invalid")
        scope = {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store,
            "scope_grant_authority_sha256": authority_sha256,
        }
        projection = self.intake_authority.project(
            purpose=purpose,
            attestation_ref=reference,
            exact_scope=scope,
            data_as_of=cutoff,
            checked_at=checked_at,
        )
        payload = projection.get("payload")
        source_contract_id = str(projection.get("source_contract_id") or "").strip()
        source_contract_version = str(
            projection.get("source_contract_version") or ""
        ).strip()
        attestation_contract_id = str(
            projection.get("attestation_contract_id") or ""
        ).strip()
        attestation_contract_version = str(
            projection.get("attestation_contract_version") or ""
        ).strip()
        attestation_sha256 = str(projection.get("attestation_sha256") or "").strip().lower()
        issuer_ref_sha256 = str(projection.get("issuer_ref_sha256") or "").strip().lower()
        if (
            projection.get("status") != "ready"
            or projection.get("purpose") != purpose
            or projection.get("attestation_ref") != reference
            or not isinstance(payload, dict)
            or payload.get("schema_version") != contract["schema_version"]
            or not source_contract_id
            or not source_contract_version
            or not attestation_contract_id
            or not attestation_contract_version
            or len(attestation_sha256) != 64
            or len(issuer_ref_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for value in (attestation_sha256, issuer_ref_sha256)
                for character in value
            )
        ):
            raise PermissionError("Coverage intake upstream attestation is invalid")
        effective_at = parse_timestamp(str(projection.get("effective_at") or ""), "effective_at")
        recorded_at = parse_timestamp(str(projection.get("recorded_at") or ""), "recorded_at")
        effective_until_raw = projection.get("effective_until")
        effective_until = (
            parse_timestamp(str(effective_until_raw), "effective_until")
            if effective_until_raw
            else None
        )
        if (
            effective_at > recorded_at
            or recorded_at > cutoff
            or effective_at > cutoff
            or (effective_until is not None and cutoff >= effective_until)
            or (effective_until is not None and checked_at >= effective_until)
        ):
            raise PermissionError("Coverage intake attestation chronology is invalid")
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        content_sha256 = hashlib.sha256(content).hexdigest()
        if projection.get("payload_sha256") != content_sha256:
            raise PermissionError("Coverage intake attested payload hash drifted")
        if purpose != "denominator":
            unsigned = {key: value for key, value in payload.items() if key != "content_sha256"}
            payload_sha256 = hashlib.sha256(
                json.dumps(
                    unsigned,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            if payload.get("content_sha256") != payload_sha256:
                raise ValueError("Coverage intake payload content hash drifted")
        issuance = {
            "purpose": purpose,
            "source": contract["source"],
            "contract_id": contract["contract_id"],
            "schema_version": contract["schema_version"],
            "content_sha256": content_sha256,
            "source_contract_id": source_contract_id,
            "source_contract_version": source_contract_version,
            "attestation_contract_id": attestation_contract_id,
            "attestation_contract_version": attestation_contract_version,
            "attestation_sha256": attestation_sha256,
            "issuer_ref_sha256": issuer_ref_sha256,
            "upstream_effective_at": effective_at.isoformat(),
            "upstream_recorded_at": recorded_at.isoformat(),
            "upstream_effective_until": (
                effective_until.isoformat() if effective_until else None
            ),
            "scope": scope,
        }
        issuance_sha256 = hashlib.sha256(
            json.dumps(
                issuance,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        issuance_signature_sha256 = (
            hashlib.sha256(
                f"{self.issuance_signing_key}:{issuance_sha256}".encode()
            ).hexdigest()
            if self.issuance_signing_key is not None
            else None
        )
        source = str(contract["source"])
        source_ref = (
            f"{source}://{authority_sha256}/{content_sha256}/{issuance_sha256}"
        )
        metadata = {
                "contract_id": contract["contract_id"],
                "schema_version": contract["schema_version"],
                "coverage_intake_purpose": purpose,
                "coverage_intake_issuance_sha256": issuance_sha256,
                "coverage_intake_source_contract_id": source_contract_id,
                "coverage_intake_source_contract_version": source_contract_version,
                "coverage_intake_attestation_contract_id": attestation_contract_id,
                "coverage_intake_attestation_contract_version": attestation_contract_version,
                "coverage_intake_attestation_sha256": attestation_sha256,
                "coverage_intake_issuer_ref_sha256": issuer_ref_sha256,
                "coverage_intake_authority_checked_at": checked_at.isoformat(),
                "coverage_intake_data_as_of": cutoff.isoformat(),
                "coverage_intake_upstream_recorded_at": recorded_at.isoformat(),
                "coverage_intake_upstream_effective_at": effective_at.isoformat(),
                "coverage_intake_upstream_effective_until": (
                    effective_until.isoformat() if effective_until else None
                ),
                "payload_content_sha256": payload.get("content_sha256"),
                **scope,
                "retention_class": "compliance",
                "legal_hold": False,
            }
        if issuance_signature_sha256 is not None:
            metadata["coverage_intake_issuance_signature_sha256"] = (
                issuance_signature_sha256
            )

        def persist_local(target_session: Session) -> EvidenceRecord:
            authority_row = target_session.get(
                GlobalDataCoverageIssuanceAuthorityRow,
                "coverage-intake-v1",
            )
            if authority_row is None:
                target_session.add(
                    GlobalDataCoverageIssuanceAuthorityRow(
                        authority_id="coverage-intake-v1",
                        signing_key_secret=self.issuance_signing_key,
                        signing_key_sha256=self.issuance_signing_key_sha256,
                        created_at=checked_at,
                    )
                )
                target_session.flush()
            elif (
                authority_row.signing_key_secret != self.issuance_signing_key
                or authority_row.signing_key_sha256
                != self.issuance_signing_key_sha256
            ):
                raise PermissionError("Coverage issuance authority key drifted")
            record = self.evidence.capture(
                content=content,
                filename=f"{purpose}-{content_sha256}.json",
                content_type="application/json",
                source=source,
                source_ref=source_ref,
                grade=EvidenceGrade.A,
                effective_at=effective_at.isoformat(),
                effective_until=(
                    effective_until.isoformat() if effective_until else None
                ),
                created_by="kjds-global-data-coverage-intake-authority",
                metadata=metadata,
                _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
                _session=target_session,
            )
            existing = target_session.get(
                GlobalDataCoverageEvidenceIssuanceRow, record.id
            )
            if existing is None:
                target_session.add(
                    GlobalDataCoverageEvidenceIssuanceRow(
                        evidence_id=record.id,
                        authority_id="coverage-intake-v1",
                        evidence_sha256=record.sha256,
                        source=record.source,
                        source_ref=record.source_ref,
                        issuance_sha256=issuance_sha256,
                        issuance_signature_sha256=issuance_signature_sha256,
                        authority_checked_at=checked_at,
                        created_at=checked_at,
                    )
                )
                target_session.flush()
            elif existing is None or (
                existing.evidence_sha256 != record.sha256
                or existing.source != record.source
                or existing.source_ref != record.source_ref
                or existing.issuance_sha256 != issuance_sha256
                or existing.issuance_signature_sha256
                != issuance_signature_sha256
            ):
                raise ValueError("Coverage intake issuance replay drifted")
            return record

        if self.evidence.engine.dialect.name != "postgresql":
            if session is not None:
                return persist_local(session)
            with self.evidence.transaction() as target_session:
                return persist_local(target_session)

        if session is not None:
            raise RuntimeError(
                "PostgreSQL coverage issuance uses its isolated issuer transaction"
            )
        evidence_id = new_id("evd")
        assert self._issuer_port is not None
        returned_evidence_id = self._issuer_port.issue_evidence(
            evidence_id=evidence_id,
            content=content,
            source=source,
            source_ref=source_ref,
            effective_at=effective_at,
            effective_until=effective_until,
            metadata=metadata,
            issuance_sha256=issuance_sha256,
            authority_checked_at=checked_at,
        )
        record = self.evidence.get(returned_evidence_id)
        if (
            record.sha256 != content_sha256
            or record.source != source
            or record.source_ref != source_ref
            or record.metadata.get("coverage_intake_issuance_sha256")
            != issuance_sha256
            or not record.metadata.get("coverage_intake_issuance_signature_sha256")
        ):
            raise PermissionError("Coverage issuer receipt binding drifted")
        self.evidence.require_current([record.id], as_of=checked_at)
        return record
