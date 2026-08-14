"""COM-002 commercial pilot deployment contract kernel tests (prep-only slice)."""

from __future__ import annotations

import hashlib

import pytest

from apps.control_plane.commercial_pilot_deployment import (
    DEPLOYMENT_CONTROLS,
    ISOLATION_CONTRACT,
    REAL_DEPLOYMENT_ADMITTED,
    ZERO_AUTHORITY_KEYS,
    CommercialDeploymentError,
    GovernedCommercialDeployment,
)


def _deploy() -> GovernedCommercialDeployment:
    return GovernedCommercialDeployment()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _evidence_for_all() -> list[dict]:
    return [
        {"control": control, "evidence_id": f"evd-{i}", "content_sha256": _sha(control)}
        for i, control in enumerate(DEPLOYMENT_CONTROLS)
    ]


def _tenant(customer_id: str, *, suffix: str = "") -> dict:
    return {
        "customer_id": customer_id,
        "database_name": f"db-{customer_id}{suffix}",
        "key_domain": f"key-{customer_id}{suffix}",
        "storage_namespace": f"ns-{customer_id}{suffix}",
    }


def test_assess_all_implemented_admits():
    result = _deploy().assess_deployment(
        customer_id="cust-1",
        scope="single_customer_isolated_single_store",
        evidence=_evidence_for_all(),
    )
    assert result.status == "ADMITTED"
    assert result.ready is True
    assert result.unknowns == ()
    assert result.external_write_allowed is False
    assert all(row["status"] == "IMPLEMENTED" for row in result.controls)


def test_assess_declared_only_is_not_ready():
    result = _deploy().assess_deployment(
        customer_id="cust-1",
        scope="single_customer_isolated_single_store",
        declared=list(DEPLOYMENT_CONTROLS),
    )
    assert result.status == "NOT_ADMITTED"
    assert result.ready is False
    assert all(row["status"] == "CONTRACT_ONLY" for row in result.controls)


def test_assess_nothing_declared_all_unknown():
    result = _deploy().assess_deployment(
        customer_id="cust-1",
        scope="single_customer_isolated_single_store",
    )
    assert result.status == "NOT_ADMITTED"
    assert result.ready is False
    assert all(row["status"] == "UNKNOWN" for row in result.controls)
    assert result.unknowns == DEPLOYMENT_CONTROLS


def test_assess_partial_mixed_statuses():
    result = _deploy().assess_deployment(
        customer_id="cust-1",
        scope="single_customer_isolated_single_store",
        declared=["tls_termination"],
        evidence=[
            {"control": "single_customer_database", "evidence_id": "evd-1", "content_sha256": _sha("db")}
        ],
    )
    statuses = {row["control"]: row["status"] for row in result.controls}
    assert statuses["single_customer_database"] == "IMPLEMENTED"
    assert statuses["tls_termination"] == "CONTRACT_ONLY"
    assert statuses["secrets_management"] == "UNKNOWN"
    assert result.ready is False


def test_assess_unrecognized_control_fail_closed():
    with pytest.raises(CommercialDeploymentError):
        _deploy().assess_deployment(
            customer_id="cust-1",
            scope="scope",
            declared=["not_a_real_control"],
        )


def test_assess_duplicate_evidence_fail_closed():
    with pytest.raises(CommercialDeploymentError):
        _deploy().assess_deployment(
            customer_id="cust-1",
            scope="scope",
            evidence=[
                {"control": "tls_termination", "evidence_id": "evd-1", "content_sha256": _sha("a")},
                {"control": "tls_termination", "evidence_id": "evd-2", "content_sha256": _sha("b")},
            ],
        )


def test_assess_bad_evidence_hash_fail_closed():
    with pytest.raises(CommercialDeploymentError):
        _deploy().assess_deployment(
            customer_id="cust-1",
            scope="scope",
            evidence=[
                {"control": "tls_termination", "evidence_id": "evd-1", "content_sha256": "not-a-hash"},
            ],
        )


def test_assess_sensitive_scope_fail_closed():
    with pytest.raises(CommercialDeploymentError):
        _deploy().assess_deployment(customer_id="cust-1", scope="scope with password=secret")


def test_check_isolation_disjoint_tenants_ok():
    result = _deploy().check_isolation(
        tenant_a=_tenant("cust-a"),
        tenant_b=_tenant("cust-b"),
    )
    assert result.isolation_ok is True
    assert result.violations == ()
    assert result.contract_id == ISOLATION_CONTRACT
    assert result.external_write_allowed is False


def test_check_isolation_database_collision():
    result = _deploy().check_isolation(
        tenant_a=_tenant("cust-a"),
        tenant_b={"customer_id": "cust-b", "database_name": "db-cust-a", "key_domain": "key-cust-b", "storage_namespace": "ns-cust-b"},
    )
    assert result.isolation_ok is False
    assert "database_name_collision" in result.violations


def test_check_isolation_key_domain_collision():
    result = _deploy().check_isolation(
        tenant_a=_tenant("cust-a"),
        tenant_b={"customer_id": "cust-b", "database_name": "db-cust-b", "key_domain": "key-cust-a", "storage_namespace": "ns-cust-b"},
    )
    assert result.isolation_ok is False
    assert "key_domain_collision" in result.violations


def test_check_isolation_storage_collision():
    result = _deploy().check_isolation(
        tenant_a=_tenant("cust-a"),
        tenant_b={"customer_id": "cust-b", "database_name": "db-cust-b", "key_domain": "key-cust-b", "storage_namespace": "ns-cust-a"},
    )
    assert result.isolation_ok is False
    assert "storage_namespace_collision" in result.violations


def test_check_isolation_customer_id_collision():
    result = _deploy().check_isolation(
        tenant_a=_tenant("cust-a"),
        tenant_b=_tenant("cust-a"),
    )
    assert result.isolation_ok is False
    assert "customer_id_collision" in result.violations


def test_check_isolation_invalid_tenant_fail_closed():
    with pytest.raises(CommercialDeploymentError):
        _deploy().check_isolation(
            tenant_a=_tenant("cust-a"),
            tenant_b={"customer_id": "cust-b"},  # missing resource fields
        )


def test_readback_pending_verified_invalidated():
    deploy = _deploy()
    assessment = deploy.assess_deployment(customer_id="cust-1", scope="scope", evidence=_evidence_for_all())
    assert deploy.readback(assessment)["readback_state"] == "PENDING"
    assert deploy.readback(assessment, observed=assessment.assessment_sha256)["readback_state"] == "VERIFIED"
    assert deploy.readback(assessment, observed="0" * 64)["readback_state"] == "INVALIDATED"


def test_zero_authority_all_false():
    authority = _deploy().zero_authority()
    assert set(authority) == set(ZERO_AUTHORITY_KEYS)
    assert all(value is False for value in authority.values())
    assert "external_deployment_execution" in authority


def test_real_deployment_not_admitted():
    assert REAL_DEPLOYMENT_ADMITTED is False


def test_deployment_controls_frozen():
    assert DEPLOYMENT_CONTROLS == (
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
