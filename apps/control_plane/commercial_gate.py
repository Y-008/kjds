"""Governed C0 commercial pilot gate contract kernel (COM-002 capstone slice).

Freezes the single software-line release gate (``C0 Commercial Pilot Gate``) as
a deterministic nine-dimension aggregation over the already-built commercial
sub-contracts: release provenance, isolated deployment, minimal
billing/usage/entitlement, invoice/refund lifecycle, unit economics,
contract/DPA/privacy, SLA/incident, backup/restore drill and exit/export/
deletion. It references those sub-modules by name and never re-implements them.
This kernel only ever reports ``not_for_sale=True`` and ``ready_to_sell=False``;
it certifies no sales authority and admits no Fact, FinanceEntry, Approval,
Permit, Pilot, Invoice, Payment, Receivable, Outbox or external write.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

C0_GATE_CONTRACT = "kjds-c0-commercial-pilot-gate-v1"
C0_GATE_VERSION = "1.0.0"

C0_GATE_DIMENSIONS = (
    "stable_release",
    "isolated_production_deployment",
    "minimal_billing_usage_entitlement",
    "invoice_refund_lifecycle",
    "unit_economics",
    "contract_dpa_privacy",
    "sla_and_incident",
    "backup_restore_drill",
    "exit_export_deletion",
)

DIMENSION_STATUSES = ("IMPLEMENTED", "CONTRACT_ONLY", "UNKNOWN")

# Each gate dimension maps to the single authoritative sub-module that already
# freezes that contract; the gate only references them and never duplicates.
C0_DIMENSION_MODULE_REFS = {
    "stable_release": "release_provenance",
    "isolated_production_deployment": "commercial_pilot_deployment",
    "minimal_billing_usage_entitlement": "commercial_lifecycle",
    "invoice_refund_lifecycle": "commercial_lifecycle",
    "unit_economics": "capability_economics",
    "contract_dpa_privacy": "commercial_discovery",
    "sla_and_incident": "commercial_discovery",
    "backup_restore_drill": "commercial_pilot_deployment",
    "exit_export_deletion": "customer_exit_export",
}

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
        "sales_authority",
    }
)


class CommercialGateError(ValueError):
    """Stable, non-sensitive contract failure for the C0 commercial pilot gate."""


@dataclass(frozen=True)
class GateAssessment:
    status: str
    contract_id: str
    dimensions: tuple[dict[str, Any], ...]
    gate_pass: bool
    not_for_sale: bool
    ready_to_sell: bool
    external_write_allowed: bool
    unknowns: tuple[str, ...]
    assessment_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise CommercialGateError(f"{name}_invalid")
    if len(value) > maximum:
        raise CommercialGateError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise CommercialGateError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise CommercialGateError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise CommercialGateError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise CommercialGateError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CommercialGateError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise CommercialGateError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GovernedCommercialGate:
    """Deterministic C0 commercial pilot gate contract kernel (capstone)."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def assess_gate(
        self,
        *,
        declared: list[str] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> GateAssessment:
        declared_set: set[str] = set()
        if declared is not None:
            if not isinstance(declared, list):
                raise CommercialGateError("declared_invalid")
            for dimension in declared:
                name = _text(dimension, "declared_dimension", maximum=120)
                if name not in C0_GATE_DIMENSIONS:
                    raise CommercialGateError("dimension_not_recognized")
                declared_set.add(name)

        evidence_map: dict[str, dict[str, str]] = {}
        if evidence is not None:
            if not isinstance(evidence, list):
                raise CommercialGateError("evidence_invalid")
            _safe_tree(evidence)
            for entry in evidence:
                if not isinstance(entry, Mapping):
                    raise CommercialGateError("evidence_entry_invalid")
                name = _text(entry.get("dimension"), "evidence_dimension", maximum=120)
                if name not in C0_GATE_DIMENSIONS:
                    raise CommercialGateError("dimension_not_recognized")
                if name in evidence_map:
                    raise CommercialGateError("dimension_duplicate")
                evidence_id = _token(entry.get("evidence_id"), "evidence_id")
                content_sha = _hex64(entry.get("content_sha256"), "content_sha256")
                evidence_map[name] = {"evidence_id": evidence_id, "content_sha256": content_sha}

        rows: list[dict[str, Any]] = []
        unknowns: list[str] = []
        for dimension in C0_GATE_DIMENSIONS:
            module_ref = C0_DIMENSION_MODULE_REFS[dimension]
            if dimension in evidence_map:
                rows.append(
                    {
                        "dimension": dimension,
                        "module_ref": module_ref,
                        "status": "IMPLEMENTED",
                        "evidence_id": evidence_map[dimension]["evidence_id"],
                        "content_sha256": evidence_map[dimension]["content_sha256"],
                    }
                )
            elif dimension in declared_set:
                rows.append({"dimension": dimension, "module_ref": module_ref, "status": "CONTRACT_ONLY", "evidence_id": None, "content_sha256": None})
            else:
                rows.append({"dimension": dimension, "module_ref": module_ref, "status": "UNKNOWN", "evidence_id": None, "content_sha256": None})
                unknowns.append(dimension)

        gate_pass = all(row["status"] == "IMPLEMENTED" for row in rows)
        document = {
            "contract_id": C0_GATE_CONTRACT,
            "dimensions": rows,
            "gate_pass": gate_pass,
            "not_for_sale": True,
            "ready_to_sell": False,
            "external_write_allowed": False,
        }
        return GateAssessment(
            status="PASS" if gate_pass else "BLOCKED",
            contract_id=C0_GATE_CONTRACT,
            dimensions=tuple(rows),
            gate_pass=gate_pass,
            not_for_sale=True,
            ready_to_sell=False,
            external_write_allowed=False,
            unknowns=tuple(unknowns),
            assessment_sha256=_hash(document),
        )

    def readback(self, obj: Any, *, observed: str | None = None) -> dict[str, Any]:
        if not isinstance(obj, GateAssessment):
            raise CommercialGateError("readback_target_invalid")
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == obj.assessment_sha256
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "GateAssessment",
    "GovernedCommercialGate",
    "CommercialGateError",
    "C0_DIMENSION_MODULE_REFS",
    "C0_GATE_CONTRACT",
    "C0_GATE_DIMENSIONS",
    "C0_GATE_VERSION",
    "DIMENSION_STATUSES",
    "ZERO_AUTHORITY_KEYS",
]
