"""COM-002 C0 commercial pilot gate contract kernel tests (capstone slice)."""

from __future__ import annotations

import hashlib

import pytest

from apps.control_plane.commercial_gate import (
    C0_DIMENSION_MODULE_REFS,
    C0_GATE_DIMENSIONS,
    ZERO_AUTHORITY_KEYS,
    CommercialGateError,
    GovernedCommercialGate,
)


def _gate() -> GovernedCommercialGate:
    return GovernedCommercialGate()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _evidence_for_all() -> list[dict]:
    return [
        {"dimension": dim, "evidence_id": f"evd-{i}", "content_sha256": _sha(dim)}
        for i, dim in enumerate(C0_GATE_DIMENSIONS)
    ]


def test_assess_all_implemented_pass_but_not_for_sale():
    result = _gate().assess_gate(evidence=_evidence_for_all())
    assert result.status == "PASS"
    assert result.gate_pass is True
    assert result.not_for_sale is True
    assert result.ready_to_sell is False
    assert result.external_write_allowed is False
    assert result.unknowns == ()
    assert all(row["status"] == "IMPLEMENTED" for row in result.dimensions)


def test_assess_nothing_declared_blocked():
    result = _gate().assess_gate()
    assert result.status == "BLOCKED"
    assert result.gate_pass is False
    assert result.not_for_sale is True
    assert result.ready_to_sell is False
    assert result.unknowns == C0_GATE_DIMENSIONS
    assert all(row["status"] == "UNKNOWN" for row in result.dimensions)


def test_assess_declared_only_contract_only_blocked():
    result = _gate().assess_gate(declared=list(C0_GATE_DIMENSIONS))
    assert result.status == "BLOCKED"
    assert all(row["status"] == "CONTRACT_ONLY" for row in result.dimensions)


def test_assess_partial_mixed():
    result = _gate().assess_gate(
        declared=["contract_dpa_privacy"],
        evidence=[
            {"dimension": "stable_release", "evidence_id": "evd-1", "content_sha256": _sha("rel")},
        ],
    )
    statuses = {row["dimension"]: row["status"] for row in result.dimensions}
    assert statuses["stable_release"] == "IMPLEMENTED"
    assert statuses["contract_dpa_privacy"] == "CONTRACT_ONLY"
    assert statuses["unit_economics"] == "UNKNOWN"
    assert result.status == "BLOCKED"


def test_dimensions_map_to_authoritative_modules():
    result = _gate().assess_gate()
    by_dim = {row["dimension"]: row["module_ref"] for row in result.dimensions}
    assert by_dim["isolated_production_deployment"] == "commercial_pilot_deployment"
    assert by_dim["exit_export_deletion"] == "customer_exit_export"
    assert by_dim["contract_dpa_privacy"] == "commercial_discovery"
    assert by_dim["minimal_billing_usage_entitlement"] == "commercial_lifecycle"
    assert by_dim["unit_economics"] == "capability_economics"
    assert by_dim["stable_release"] == "release_provenance"


def test_assess_unrecognized_dimension_fail_closed():
    with pytest.raises(CommercialGateError):
        _gate().assess_gate(declared=["not_a_real_dimension"])


def test_assess_duplicate_evidence_fail_closed():
    with pytest.raises(CommercialGateError):
        _gate().assess_gate(
            evidence=[
                {"dimension": "stable_release", "evidence_id": "evd-1", "content_sha256": _sha("a")},
                {"dimension": "stable_release", "evidence_id": "evd-2", "content_sha256": _sha("b")},
            ]
        )


def test_assess_bad_hash_fail_closed():
    with pytest.raises(CommercialGateError):
        _gate().assess_gate(
            evidence=[{"dimension": "stable_release", "evidence_id": "evd-1", "content_sha256": "bad"}]
        )


def test_readback_pending_verified_invalidated():
    gate = _gate()
    assessment = gate.assess_gate(evidence=_evidence_for_all())
    assert gate.readback(assessment)["readback_state"] == "PENDING"
    assert gate.readback(assessment, observed=assessment.assessment_sha256)["readback_state"] == "VERIFIED"
    assert gate.readback(assessment, observed="0" * 64)["readback_state"] == "INVALIDATED"


def test_zero_authority_all_false():
    authority = _gate().zero_authority()
    assert set(authority) == set(ZERO_AUTHORITY_KEYS)
    assert all(value is False for value in authority.values())
    assert "sales_authority" in authority


def test_gate_dimensions_frozen():
    assert C0_GATE_DIMENSIONS == (
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
    assert len(C0_DIMENSION_MODULE_REFS) == len(C0_GATE_DIMENSIONS)
