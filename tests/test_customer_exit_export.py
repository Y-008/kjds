"""COM-002 customer exit / data return / deletion contract kernel tests (prep-only slice)."""

from __future__ import annotations

import hashlib

import pytest

from apps.control_plane.customer_exit_export import (
    DEFAULT_RETENTION_POLICY,
    EXIT_STATES,
    EXPORT_DATA_CLASSES,
    REAL_EXECUTOR_ADMITTED,
    RETENTION_DATA_CLASSES,
    ZERO_AUTHORITY_KEYS,
    CustomerExitError,
    GovernedCustomerExit,
)


def _exit() -> GovernedCustomerExit:
    return GovernedCustomerExit()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _request(**overrides) -> dict:
    req = {
        "customer_id": "cust-123",
        "scope": "single_customer_isolated_single_store",
        "authority": "customer_data_owner",
        "requested_at": "2026-08-14T00:00:00+00:00",
    }
    req.update(overrides)
    return req


def _full_data_classes() -> list[dict]:
    return [
        {"class": "operating_products", "record_count": 12, "content_sha256": _sha("products")},
        {"class": "finance_orders", "record_count": 34, "content_sha256": _sha("finance")},
        {"class": "profit_projections", "record_count": 7, "content_sha256": _sha("profit")},
        {"class": "evidence_objects", "record_count": 19, "content_sha256": _sha("evidence")},
        {"class": "customer_pii", "record_count": 1, "content_sha256": _sha("pii")},
    ]


def test_open_exit_request():
    result = _exit().open_exit_request(**_request())
    assert result.status == "requested"
    assert result.customer_id == "cust-123"
    assert result.external_write_allowed is False
    assert result.retention_policy == DEFAULT_RETENTION_POLICY
    assert "retention_policy" in result.unknowns


def test_open_exit_request_explicit_retention_policy():
    result = _exit().open_exit_request(
        **_request(retention_policy=["deidentified_governance_audit_trail"])
    )
    assert result.retention_policy == ("deidentified_governance_audit_trail",)
    assert result.unknowns == ()


def test_open_exit_request_invalid_customer_id_fail_closed():
    with pytest.raises(CustomerExitError):
        _exit().open_exit_request(**_request(customer_id="bad id!"))


def test_open_exit_request_invalid_time_fail_closed():
    with pytest.raises(CustomerExitError):
        _exit().open_exit_request(**_request(requested_at="not-a-time"))


def test_open_exit_request_unrecognized_retention_fail_closed():
    with pytest.raises(CustomerExitError):
        _exit().open_exit_request(
            **_request(retention_policy=["customer_pii"])
        )


def test_open_exit_request_sensitive_value_fail_closed():
    with pytest.raises(CustomerExitError):
        _exit().open_exit_request(
            **_request(scope="scope with password=hunter2")
        )


def test_prepare_export_full_manifest():
    req = _exit().open_exit_request(**_request())
    manifest = _exit().prepare_export(request=req, data_classes=_full_data_classes())
    assert manifest.status == "export_prepared"
    assert manifest.customer_id == "cust-123"
    assert manifest.external_write_allowed is False
    assert all(row["status"] == "EXPORTED" for row in manifest.data_classes)
    assert manifest.unknowns == ()
    assert {row["data_class"] for row in manifest.data_classes} == set(EXPORT_DATA_CLASSES)


def test_prepare_export_missing_class_is_unknown():
    req = _exit().open_exit_request(**_request())
    manifest = _exit().prepare_export(request=req, data_classes=[{"class": "customer_pii", "content_sha256": _sha("pii")}])
    statuses = {row["data_class"]: row["status"] for row in manifest.data_classes}
    assert statuses["customer_pii"] == "EXPORTED"
    assert statuses["operating_products"] == "UNKNOWN"
    assert "operating_products" in manifest.unknowns


def test_prepare_export_unknown_content_hash():
    req = _exit().open_exit_request(**_request())
    manifest = _exit().prepare_export(request=req, data_classes=[{"class": "customer_pii", "record_count": 1}])
    row = [r for r in manifest.data_classes if r["data_class"] == "customer_pii"][0]
    assert row["status"] == "UNKNOWN"
    assert "customer_pii_content_hash" in manifest.unknowns


def test_prepare_export_unrecognized_class_fail_closed():
    req = _exit().open_exit_request(**_request())
    with pytest.raises(CustomerExitError):
        _exit().prepare_export(request=req, data_classes=[{"class": "raw_passwords"}])
        pass


def test_prepare_export_duplicate_class_fail_closed():
    req = _exit().open_exit_request(**_request())
    with pytest.raises(CustomerExitError):
        _exit().prepare_export(
            request=req,
            data_classes=[
                {"class": "customer_pii", "content_sha256": _sha("a")},
                {"class": "customer_pii", "content_sha256": _sha("b")},
            ],
        )


def test_prepare_export_bad_record_count_fail_closed():
    req = _exit().open_exit_request(**_request())
    with pytest.raises(CustomerExitError):
        _exit().prepare_export(
            request=req,
            data_classes=[{"class": "customer_pii", "record_count": -1, "content_sha256": _sha("pii")}],
        )


def test_plan_deletion_targets_all_exported_classes():
    req = _exit().open_exit_request(**_request())
    manifest = _exit().prepare_export(request=req, data_classes=_full_data_classes())
    plan = _exit().plan_deletion(manifest=manifest)
    assert plan.status == "deletion_planned"
    assert plan.customer_id == "cust-123"
    assert plan.targets == EXPORT_DATA_CLASSES
    assert plan.retained == DEFAULT_RETENTION_POLICY
    assert plan.external_write_allowed is False
    assert set(plan.retained) <= set(RETENTION_DATA_CLASSES)


def test_plan_deletion_custom_retention_policy():
    req = _exit().open_exit_request(**_request())
    manifest = _exit().prepare_export(request=req, data_classes=_full_data_classes())
    plan = _exit().plan_deletion(
        manifest=manifest, retention_policy=["deidentified_governance_audit_trail"]
    )
    assert plan.retained == ("deidentified_governance_audit_trail",)


def test_close_exit_receipt():
    req = _exit().open_exit_request(**_request())
    manifest = _exit().prepare_export(request=req, data_classes=_full_data_classes())
    plan = _exit().plan_deletion(manifest=manifest)
    receipt = _exit().close_exit(
        manifest=manifest,
        plan=plan,
        closed_at="2026-08-14T12:00:00+00:00",
    )
    assert receipt.status == "closed"
    assert receipt.export_sha256 == manifest.manifest_sha256
    assert receipt.deletion_sha256 == plan.plan_sha256
    assert receipt.external_write_allowed is False


def test_close_exit_customer_mismatch_fail_closed():
    req1 = _exit().open_exit_request(**_request(customer_id="cust-1"))
    req2 = _exit().open_exit_request(**_request(customer_id="cust-2"))
    manifest = _exit().prepare_export(request=req1, data_classes=_full_data_classes())
    plan = _exit().plan_deletion(
        manifest=_exit().prepare_export(request=req2, data_classes=_full_data_classes())
    )
    with pytest.raises(CustomerExitError):
        _exit().close_exit(manifest=manifest, plan=plan)


def test_readback_pending_verified_invalidated():
    exit_svc = _exit()
    req = exit_svc.open_exit_request(**_request())
    manifest = exit_svc.prepare_export(request=req, data_classes=_full_data_classes())
    assert exit_svc.readback(manifest)["readback_state"] == "PENDING"
    assert exit_svc.readback(manifest, observed=manifest.manifest_sha256)["readback_state"] == "VERIFIED"
    assert exit_svc.readback(manifest, observed="0" * 64)["readback_state"] == "INVALIDATED"


def test_zero_authority_all_false():
    authority = _exit().zero_authority()
    assert set(authority) == set(ZERO_AUTHORITY_KEYS)
    assert all(value is False for value in authority.values())
    assert {"external_data_export", "external_data_deletion", "invoice", "payment", "receivable"} <= set(authority)


def test_real_executor_not_admitted():
    assert REAL_EXECUTOR_ADMITTED is False


def test_exit_states_frozen():
    assert EXIT_STATES == (
        "requested",
        "export_prepared",
        "export_verified",
        "deletion_planned",
        "deletion_verified",
        "closed",
    )
