"""Governed commercial pilot deployment contract kernel (COM-002 prep-only slice).

Freezes the C0 single-customer isolated delivery base as a deterministic
readiness checklist: one app instance, one database, one key domain and one
storage namespace per customer, TLS termination, managed secrets, verified
backup/restore, verified upgrade/rollback, verified full data export, health
monitoring and declared RPO/RTO. It also freezes the two-customer negative
isolation invariant. This kernel is a contract and classifier only — it admits
no real deployment, secret write, Fact, FinanceEntry, Approval, Permit, Pilot,
Invoice, Payment, Receivable or Outbox authority; unevidenced controls are
reported UNKNOWN, never fabricated as ready.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEPLOYMENT_CONTRACT = "kjds-commercial-pilot-deployment-v1"
ISOLATION_CONTRACT = "kjds-commercial-isolation-v1"
DEPLOYMENT_VERSION = "1.0.0"

DEPLOYMENT_CONTROLS = (
    "single_customer_app_instance",
    "single_customer_database",
    "single_customer_key_domain",
    "single_customer_storage_namespace",
    "tls_termination",
    "secrets_management",
    "backup_configured",
    "restore_verified",
    "upgrade_rollback_verified",
    "full_data_export_verified",
    "health_monitoring",
    "rpo_rto_declared",
)

CONTROL_STATUSES = ("IMPLEMENTED", "CONTRACT_ONLY", "UNKNOWN")

TENANT_RESOURCE_FIELDS = ("database_name", "key_domain", "storage_namespace")

REAL_DEPLOYMENT_ADMITTED = False

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

SENSITIVE_MARKERS = (
    "authorization:",
    "bearer ",
    "cookie=",
    "api_key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "password=",
    "private_key=",
    "sk-",
)

ZERO_AUTHORITY_KEYS = frozenset(
    {
        "formal_fact",
        "finance_entry",
        "approval",
        "permit",
        "pilot",
        "outbox",
        "canonical_graph_write",
        "dependency_install",
        "network",
        "external_write",
        "invoice",
        "payment",
        "receivable",
        "external_deployment_execution",
    }
)


class CommercialDeploymentError(ValueError):
    """Stable, non-sensitive contract failure for commercial pilot deployment."""


@dataclass(frozen=True)
class DeploymentAssessment:
    status: str
    contract_id: str
    customer_id: str
    scope: str
    controls: tuple[dict[str, Any], ...]
    ready: bool
    external_write_allowed: bool
    unknowns: tuple[str, ...]
    assessment_sha256: str


@dataclass(frozen=True)
class IsolationCheck:
    contract_id: str
    isolation_ok: bool
    violations: tuple[str, ...]
    external_write_allowed: bool
    isolation_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise CommercialDeploymentError(f"{name}_invalid")
    if len(value) > maximum:
        raise CommercialDeploymentError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise CommercialDeploymentError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise CommercialDeploymentError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise CommercialDeploymentError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise CommercialDeploymentError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CommercialDeploymentError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise CommercialDeploymentError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GovernedCommercialDeployment:
    """Deterministic commercial pilot deployment contract kernel (COM-002 prep-only)."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def assess_deployment(
        self,
        *,
        customer_id: str,
        scope: str,
        declared: list[str] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> DeploymentAssessment:
        customer_id = _token(customer_id, "customer_id")
        scope = _text(scope, "scope", maximum=200)
        _safe_tree(scope)

        declared_set: set[str] = set()
        if declared is not None:
            if not isinstance(declared, list):
                raise CommercialDeploymentError("declared_invalid")
            for control in declared:
                name = _text(control, "declared_control", maximum=120)
                if name not in DEPLOYMENT_CONTROLS:
                    raise CommercialDeploymentError("control_not_recognized")
                declared_set.add(name)

        evidence_map: dict[str, dict[str, str]] = {}
        if evidence is not None:
            if not isinstance(evidence, list):
                raise CommercialDeploymentError("evidence_invalid")
            _safe_tree(evidence)
            for entry in evidence:
                if not isinstance(entry, Mapping):
                    raise CommercialDeploymentError("evidence_entry_invalid")
                name = _text(entry.get("control"), "evidence_control", maximum=120)
                if name not in DEPLOYMENT_CONTROLS:
                    raise CommercialDeploymentError("control_not_recognized")
                if name in evidence_map:
                    raise CommercialDeploymentError("control_duplicate")
                evidence_id = _token(entry.get("evidence_id"), "evidence_id")
                content_sha = _hex64(entry.get("content_sha256"), "content_sha256")
                evidence_map[name] = {"evidence_id": evidence_id, "content_sha256": content_sha}

        rows: list[dict[str, Any]] = []
        unknowns: list[str] = []
        for control in DEPLOYMENT_CONTROLS:
            if control in evidence_map:
                rows.append(
                    {
                        "control": control,
                        "status": "IMPLEMENTED",
                        "evidence_id": evidence_map[control]["evidence_id"],
                        "content_sha256": evidence_map[control]["content_sha256"],
                    }
                )
            elif control in declared_set:
                rows.append({"control": control, "status": "CONTRACT_ONLY", "evidence_id": None, "content_sha256": None})
            else:
                rows.append({"control": control, "status": "UNKNOWN", "evidence_id": None, "content_sha256": None})
                unknowns.append(control)

        ready = all(row["status"] == "IMPLEMENTED" for row in rows)
        document = {
            "contract_id": DEPLOYMENT_CONTRACT,
            "customer_id": customer_id,
            "scope": scope,
            "controls": rows,
            "external_write_allowed": False,
        }
        return DeploymentAssessment(
            status="ADMITTED" if ready else "NOT_ADMITTED",
            contract_id=DEPLOYMENT_CONTRACT,
            customer_id=customer_id,
            scope=scope,
            controls=tuple(rows),
            ready=ready,
            external_write_allowed=False,
            unknowns=tuple(unknowns),
            assessment_sha256=_hash(document),
        )

    def _validate_tenant(self, value: Any, name: str) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise CommercialDeploymentError(f"{name}_invalid")
        _safe_tree(dict(value))
        customer_id = _token(value.get("customer_id"), f"{name}_customer_id")
        database_name = _text(value.get("database_name"), f"{name}_database_name", maximum=120)
        key_domain = _text(value.get("key_domain"), f"{name}_key_domain", maximum=120)
        storage_namespace = _text(value.get("storage_namespace"), f"{name}_storage_namespace", maximum=120)
        return {
            "customer_id": customer_id,
            "database_name": database_name,
            "key_domain": key_domain,
            "storage_namespace": storage_namespace,
        }

    def check_isolation(self, *, tenant_a: dict[str, str], tenant_b: dict[str, str]) -> IsolationCheck:
        a = self._validate_tenant(tenant_a, "tenant_a")
        b = self._validate_tenant(tenant_b, "tenant_b")

        violations: list[str] = []
        if a["customer_id"] == b["customer_id"]:
            violations.append("customer_id_collision")
        for field in TENANT_RESOURCE_FIELDS:
            if a[field] == b[field]:
                violations.append(f"{field}_collision")

        document = {
            "contract_id": ISOLATION_CONTRACT,
            "tenant_a": a,
            "tenant_b": b,
            "violations": violations,
            "external_write_allowed": False,
        }
        return IsolationCheck(
            contract_id=ISOLATION_CONTRACT,
            isolation_ok=not violations,
            violations=tuple(violations),
            external_write_allowed=False,
            isolation_sha256=_hash(document),
        )

    def readback(self, obj: Any, *, observed: str | None = None) -> dict[str, Any]:
        if isinstance(obj, DeploymentAssessment):
            digest = obj.assessment_sha256
        elif isinstance(obj, IsolationCheck):
            digest = obj.isolation_sha256
        else:
            raise CommercialDeploymentError("readback_target_invalid")
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == digest
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "DeploymentAssessment",
    "IsolationCheck",
    "GovernedCommercialDeployment",
    "CommercialDeploymentError",
    "CONTROL_STATUSES",
    "DEPLOYMENT_CONTRACT",
    "DEPLOYMENT_CONTROLS",
    "ISOLATION_CONTRACT",
    "REAL_DEPLOYMENT_ADMITTED",
    "TENANT_RESOURCE_FIELDS",
    "ZERO_AUTHORITY_KEYS",
]
