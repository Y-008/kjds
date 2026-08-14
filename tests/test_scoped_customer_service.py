from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane import causal_policies as _causal_policies  # noqa: F401
from apps.control_plane import policy_shadow as _policy_shadow  # noqa: F401
from apps.control_plane.customer_service import (
    CustomerServiceAuthorityService,
)
from apps.control_plane.domain import ApprovalStatus
from apps.control_plane.execution_plans import ExecutionPlanRow
from apps.control_plane.limited_executor import (
    LimitedExecutionCommandRow,
    LimitedExecutionReceiptRow,
)
from apps.control_plane.scoped_customer_service import (
    ScopedCustomerServiceWorkspace,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base, ProductRow

AS_OF = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
AUTHORITY = "a" * 64
BODY_SHA = "b" * 64
EVIDENCE_SHA = "e" * 64
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": AUTHORITY,
}
ENTITY_SCOPE = {
    "status": "ready",
    "entity_ref": "entity-a",
    "authority_sha256": AUTHORITY,
}


def principal(*, stores=frozenset({"ozon-primary"})) -> Principal:
    return Principal(
        actor_id="service-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=stores,
    )


def engine():
    value = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(value)
    with Session(value) as session, session.begin():
        session.add(
            ProductRow(
                id="product-a",
                sku="SKU-A",
                name="Product A",
                market="RU",
                channel="ozon",
                status="active",
                created_at=datetime(2026, 7, 20, tzinfo=UTC),
                tenant_ref="tenant-a",
                entity_ref="entity-a",
                store_ref="ozon-primary",
                scope_grant_authority_sha256=AUTHORITY,
                scope_as_of=datetime(2026, 7, 20, tzinfo=UTC),
                created_by="product-owner",
            )
        )
    return value


def case() -> dict:
    value = {
        "id": "case-a",
        "external_case_ref": "OZON-CASE-1",
        "channel": "ozon",
        "order_external_id": "order-a",
        "product_id": "product-a",
        "sku": "SKU-A",
        "locale": "ru-ru",
        "classification": "product_question",
        "priority": "normal",
        "evidence_id": "evidence-case",
        "opened_at": "2026-07-29T10:00:00+00:00",
        "recorded_at": "2026-07-29T10:01:00+00:00",
        "created_by": "service-operator",
        "source_evidence_sha256": EVIDENCE_SHA,
        "scope_as_of": "2026-07-29T10:00:00+00:00",
    }
    value["payload_sha256"] = ScopedCustomerServiceWorkspace._hash(
        {
            "contract_id": CustomerServiceAuthorityService.CASE_CONTRACT_ID,
            "external_case_ref": value["external_case_ref"],
            "channel": value["channel"],
            "order_external_id": value["order_external_id"],
            "product_id": value["product_id"],
            "sku": value["sku"],
            "locale": value["locale"],
            "classification": value["classification"],
            "priority": value["priority"],
            "evidence_id": value["evidence_id"],
            "evidence_sha256": value["source_evidence_sha256"],
            "opened_at": value["opened_at"],
            "scope": SCOPE,
        }
    )
    return value


def event(
    sequence: int,
    event_type: str,
    *,
    direction: str = "system",
    body_sha256: str | None = None,
    summary: str | None = None,
    approval_id: str | None = None,
    command_id: str | None = None,
    receipt_id: str | None = None,
) -> dict:
    effective_at = f"2026-07-29T{10 + sequence:02d}:00:00+00:00"
    value = {
        "id": f"event-{sequence}",
        "case_id": "case-a",
        "source_event_ref": f"OZON-EVENT-{sequence}",
        "sequence": sequence,
        "event_type": event_type,
        "direction": direction,
        "locale": "ru-ru",
        "summary": summary or event_type.replace("_", " "),
        "body_sha256": body_sha256,
        "evidence_id": f"evidence-event-{sequence}",
        "effective_at": effective_at,
        "recorded_at": effective_at,
        "created_by": "service-operator",
        "approval_id": approval_id,
        "command_id": command_id,
        "receipt_id": receipt_id,
        "source_evidence_sha256": EVIDENCE_SHA,
        "scope_as_of": "2026-07-29T10:00:00+00:00",
    }
    value["payload_sha256"] = ScopedCustomerServiceWorkspace._hash(
        {
            "contract_id": CustomerServiceAuthorityService.EVENT_CONTRACT_ID,
            "case_id": value["case_id"],
            "source_event_ref": value["source_event_ref"],
            "sequence": sequence,
            "event_type": event_type,
            "direction": direction,
            "locale": value["locale"],
            "summary": value["summary"],
            "body_sha256": body_sha256,
            "evidence_id": value["evidence_id"],
            "evidence_sha256": value["source_evidence_sha256"],
            "effective_at": effective_at,
            "approval_id": approval_id,
            "command_id": command_id,
            "receipt_id": receipt_id,
            "scope": SCOPE,
        }
    )
    return value


def source(cases: list[dict], events: list[dict]) -> dict:
    value = {
        "contract_id": CustomerServiceAuthorityService.SOURCE_CONTRACT_ID,
        "as_of": AS_OF,
        "scope": SCOPE,
        "cases": copy.deepcopy(cases),
        "events": copy.deepcopy(events),
        "truncated": {"cases": False, "events": False},
    }
    value["snapshot_sha256"] = ScopedCustomerServiceWorkspace._hash(value)
    return value


def returns_projection() -> dict:
    value = {
        "contract_id": "kjds-native-exact-scope-returns-aftersales-v1",
        "status": "no_data",
        "as_of": AS_OF,
        "scope": SCOPE,
        "filters": {},
        "counts": {},
        "pagination": {"page_size": 100, "next_cursor": None},
        "returns": [],
        "source_gaps": ["return_fact_missing"],
    }
    value["snapshot_sha256"] = ScopedCustomerServiceWorkspace._hash(value)
    return value


class FakeSource:
    def __init__(self, value: dict) -> None:
        self.value = value
        self.calls = 0

    def read_scoped_sources(self, **_kwargs):
        self.calls += 1
        return copy.deepcopy(self.value)


class MustNotRead:
    def __init__(self) -> None:
        self.calls = 0

    def read_scoped_sources(self, **_kwargs):
        self.calls += 1
        raise AssertionError("customer-service source must not be read")

    def project(self, **_kwargs):
        self.calls += 1
        raise AssertionError("returns must not be read")


class FakeReturns:
    def __init__(self, value: dict | None = None) -> None:
        self.value = value or returns_projection()
        self.calls = 0

    def project(self, **_kwargs):
        self.calls += 1
        return copy.deepcopy(self.value)


class FakeEvidence:
    def __init__(
        self,
        invalid: set[str] | None = None,
        records: dict[str, SimpleNamespace] | None = None,
    ) -> None:
        self.invalid = invalid or set()
        self.records = records or {}

    def require_current(self, evidence_ids, **_kwargs):
        if any(item in self.invalid for item in evidence_ids):
            raise ValueError("bad evidence")

    def get(self, evidence_id):
        if evidence_id in self.invalid:
            raise ValueError("bad evidence")
        return self.records.get(
            evidence_id,
            SimpleNamespace(
                sha256=EVIDENCE_SHA,
                record_sha256="f" * 64,
                source="generic",
                metadata={},
            ),
        )


class FakeScopedEvidence:
    def project_targets(self, *, evidence_ids, **_kwargs):
        return {
            "status": "ready",
            "records": [
                {"evidence_id": item, "status": "ready"}
                for item in evidence_ids
            ],
        }


class FakeRepository:
    def __init__(self, approval=None) -> None:
        self.approval = approval

    def get_approval_at(self, approval_id, **_kwargs):
        if self.approval is None or approval_id != "approval-a":
            raise KeyError(approval_id)
        return self.approval


class FakeActionPolicies:
    def get(self, action_id):
        assert action_id == "customer_service_reply_send"
        return {
            "risk_tier": "L3",
            "external_business_side_effect": True,
            "execution_permit_required": True,
            "idempotency_required": True,
            "readback_required": True,
            "allowed_executor": "limited_executor",
            "fail_closed": True,
        }

    def snapshot(self):
        return {"policy_version": "test-v1"}


class FakeMessageReadbackAuthority:
    def __init__(self, *, overrides=None) -> None:
        self.overrides = overrides or {}

    def attest(self, **kwargs):
        as_of = kwargs["as_of"].isoformat()
        value = {
            "contract_id": (
                ScopedCustomerServiceWorkspace
                .MESSAGE_READBACK_AUTHORITY_CONTRACT_ID
            ),
            "status": "verified",
            "as_of": as_of,
            "authority": {
                "source_kind": "written_authorized_adapter",
                "adapter_id": "official-customer-message-adapter",
                "adapter_version": "1.0.0",
                "authorization_evidence_id": "evidence-adapter-auth",
                "authorization_evidence_sha256": EVIDENCE_SHA,
                "immutable": True,
                "revoked": False,
            },
            "binding": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "ozon-primary",
                "case_id": "case-a",
                "event_id": "event-7",
                "body_sha256": BODY_SHA,
                "action_id": "customer_service_reply_send",
                "operation": "customer_service.send_reply",
                "command_id": "command-a",
                "receipt_id": "receipt-a",
                "remote_operation_id": "remote-message-a",
                "worker_id": "message-worker",
            },
            "success": {
                "outcome": "succeeded",
                "mutation_applied": True,
                "platform_acknowledged": True,
                "resulting_state_hash": "8" * 64,
                "remote_operation_id": "remote-message-a",
                "observed_at": "2026-07-29T16:10:00+00:00",
                "readback_evidence_id": "evidence-readback",
                "readback_evidence_sha256": EVIDENCE_SHA,
            },
            "kill_switch": {
                "status": "released",
                "observed_at": "2026-07-29T15:29:00+00:00",
                "evidence_id": "evidence-kill",
                "evidence_sha256": EVIDENCE_SHA,
            },
            "compensation": {
                "strategy": "manual_case_follow_up",
                "status": "ready",
                "owner": "customer-operations",
                "evidence_id": "evidence-compensation",
                "evidence_sha256": EVIDENCE_SHA,
            },
        }
        for key, item in self.overrides.items():
            if isinstance(item, dict) and isinstance(value.get(key), dict):
                value[key] = {**value[key], **item}
            else:
                value[key] = item
        value["snapshot_sha256"] = ScopedCustomerServiceWorkspace._hash(
            value
        )
        return value


def message_authority_evidence() -> dict[str, SimpleNamespace]:
    binding = {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "ozon-primary",
        "case_id": "case-a",
        "event_id": "event-7",
        "body_sha256": BODY_SHA,
        "action_id": "customer_service_reply_send",
        "operation": "customer_service.send_reply",
        "command_id": "command-a",
        "receipt_id": "receipt-a",
        "remote_operation_id": "remote-message-a",
        "worker_id": "message-worker",
    }
    return {
        "evidence-adapter-auth": SimpleNamespace(
            sha256=EVIDENCE_SHA,
            record_sha256="f" * 64,
            source="customer_message_adapter_authorization",
            metadata={
                "adapter_id": "official-customer-message-adapter",
                "adapter_version": "1.0.0",
                "action_id": "customer_service_reply_send",
                "authorization_status": "active",
                "revoked": False,
            },
        ),
        "evidence-readback": SimpleNamespace(
            sha256=EVIDENCE_SHA,
            record_sha256="f" * 64,
            source="customer_message_adapter_readback",
            metadata={
                **binding,
                "evidence_contract_id": (
                    ScopedCustomerServiceWorkspace
                    .MESSAGE_READBACK_EVIDENCE_CONTRACT_ID
                ),
                "outcome": "succeeded",
                "mutation_applied": True,
                "platform_acknowledged": True,
            },
        ),
        "evidence-kill": SimpleNamespace(
            sha256=EVIDENCE_SHA,
            record_sha256="f" * 64,
            source="kill_switch_release",
            metadata={
                "adapter_id": "official-customer-message-adapter",
                "action_id": "customer_service_reply_send",
                "status": "released",
            },
        ),
        "evidence-compensation": SimpleNamespace(
            sha256=EVIDENCE_SHA,
            record_sha256="f" * 64,
            source="customer_message_compensation_plan",
            metadata={
                "case_id": "case-a",
                "strategy": "manual_case_follow_up",
                "status": "ready",
            },
        ),
    }


def approval():
    return SimpleNamespace(
        status=ApprovalStatus.APPROVED,
        action="customer_service.send_reply",
        resource_type="customer_service_case",
        resource_id="case-a",
        requested_by="service-operator",
        decided_by="independent-approver",
        payload={
            "case_id": "case-a",
            "body_sha256": BODY_SHA,
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "ozon-primary",
        },
    )


def workspace(
    source_value: dict,
    *,
    repository=None,
    returns=None,
    evidence=None,
    message_readback_authority=None,
):
    return ScopedCustomerServiceWorkspace(
        engine=engine(),
        source=FakeSource(source_value),
        evidence=evidence or FakeEvidence(),
        scoped_evidence=FakeScopedEvidence(),
        returns=returns or FakeReturns(),
        repository=repository or FakeRepository(),
        action_policies=FakeActionPolicies(),
        message_readback_authority=message_readback_authority,
    )


def project(service, **kwargs):
    return service.project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        as_of=AS_OF,
        **kwargs,
    )


def basic_events():
    return [
        event(1, "case_opened"),
        event(2, "triaged"),
    ]


def send_events():
    return [
        event(1, "case_opened"),
        event(2, "triaged"),
        event(3, "reply_drafted", direction="outbound", body_sha256=BODY_SHA),
        event(
            4,
            "reply_approval_pending",
            direction="outbound",
            body_sha256=BODY_SHA,
        ),
        event(
            5,
            "reply_permit_pending",
            direction="outbound",
            body_sha256=BODY_SHA,
        ),
        event(
            6,
            "reply_readback_pending",
            direction="outbound",
            body_sha256=BODY_SHA,
        ),
        event(
            7,
            "message_sent_readback",
            direction="outbound",
            body_sha256=BODY_SHA,
            approval_id="approval-a",
            command_id="command-a",
            receipt_id="receipt-a",
        ),
    ]


def test_missing_entity_reads_no_source_or_returns():
    source_value = MustNotRead()
    returns_value = MustNotRead()
    result = ScopedCustomerServiceWorkspace(
        engine=engine(),
        source=source_value,
        evidence=FakeEvidence(),
        scoped_evidence=FakeScopedEvidence(),
        returns=returns_value,
        repository=FakeRepository(),
        action_policies=FakeActionPolicies(),
    ).project(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["cases"] == []
    assert result["control_envelope"]["scoped_input_read"] is False
    assert source_value.calls == 0
    assert returns_value.calls == 0


def test_no_cases_short_circuits_returns():
    source_value = FakeSource(source([], []))
    returns_value = MustNotRead()
    result = ScopedCustomerServiceWorkspace(
        engine=engine(),
        source=source_value,
        evidence=FakeEvidence(),
        scoped_evidence=FakeScopedEvidence(),
        returns=returns_value,
        repository=FakeRepository(),
        action_policies=FakeActionPolicies(),
    ).project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["source_gaps"] == ["customer_service_case_missing"]
    assert source_value.calls == 1
    assert returns_value.calls == 0


def test_ready_case_is_stable_redacted_and_server_owned():
    service = workspace(source([case()], basic_events()))
    first = project(service, query="sku-a", stage="triaged")
    second = project(service, query="sku-a", stage="triaged")

    assert first["status"] == "ready"
    assert first["counts"]["total_cases"] == 1
    assert first["counts"]["total_events"] == 2
    assert first["counts"]["triaged"] == 1
    assert first["cases"][0]["stage"] == "triaged"
    assert "summary" in first["cases"][0]["timeline"][0]
    assert all(
        "raw_message_body" not in item and "body" not in item
        for item in first["cases"][0]["timeline"]
    )
    assert first["privacy_envelope"]["raw_message_body_exposed"] is False
    assert first["agent_artifact"]["raw_pii_read_allowed"] is False
    assert first["agent_artifact"]["self_approval_allowed"] is False
    assert first["agent_artifact"]["permit_issue_allowed"] is False
    assert first["control_envelope"]["message_adapter_enabled"] is False
    assert first["control_envelope"]["private_erp_interface_allowed"] is False
    assert first["snapshot_sha256"] == second["snapshot_sha256"]


def test_bad_latest_event_hash_blocks_without_fallback():
    events = basic_events()
    events[-1]["summary"] = "tampered after immutable hash"
    result = project(workspace(source([case()], events)))

    assert result["status"] == "blocked"
    assert result["cases"] == []
    assert result["excluded"]["business_values_exposed"] is False
    assert result["excluded"]["reason_counts"] == {
        "customer_service_event_payload_hash_drift": 1
    }


def test_illegal_transition_fails_closed():
    events = [
        event(1, "case_opened"),
        event(
            2,
            "reply_permit_pending",
            direction="outbound",
            body_sha256=BODY_SHA,
        ),
    ]
    result = project(workspace(source([case()], events)))

    assert result["status"] == "blocked"
    assert result["cases"] == []
    assert "customer_service_transition_invalid" in result[
        "excluded"
    ]["reason_counts"]


def test_pii_in_summary_fails_closed_even_with_valid_snapshot():
    events = [
        event(1, "case_opened"),
        event(
            2,
            "triaged",
            summary="Customer email buyer@example.com",
        ),
    ]
    result = project(workspace(source([case()], events)))

    assert result["status"] == "blocked"
    assert result["cases"] == []
    assert result["excluded"]["reason_counts"] == {
        "customer_service_event_pii_leak": 1
    }


def test_sent_event_without_permit_and_readback_fails_closed():
    result = project(
        workspace(
            source([case()], send_events()),
            repository=FakeRepository(approval()),
        )
    )

    assert result["status"] == "blocked"
    assert result["cases"] == []
    assert result["excluded"]["reason_counts"] == {
        "customer_service_reply_permit_missing": 1
    }


@pytest.mark.parametrize(
    "authority_mode",
    ["unbound", "trusted", "intake_only"],
)
def test_send_receipt_requires_independent_message_readback_authority(
    authority_mode,
):
    database = engine()
    with Session(database) as session, session.begin():
        session.add(
            ExecutionPlanRow(
                id="plan-a",
                request_hash="1" * 64,
                source_kind="approved_customer_service_reply",
                source_id="case-a",
                source_approval_id="approval-a",
                source_snapshot_hash=BODY_SHA,
                handoff_id=None,
                policy_id=None,
                release_id=None,
                idempotency_key="reply-a",
                adapter_id="official-customer-message-adapter",
                action_id="customer_service_reply_send",
                action_policy_version="test-v1",
                target_json={
                    "case_id": "case-a",
                    "body_sha256": BODY_SHA,
                },
                precondition_state_hash="2" * 64,
                intended_patch_json={},
                rollback_patch_json={},
                risk_limits_json={},
                risk_values_json={},
                risk_currency=None,
                permit_ttl_seconds=300,
                evidence_json=[
                    "evidence-event-7",
                    "evidence-adapter-auth",
                ],
                approval_id="approval-a",
                created_by="service-operator",
                created_at=datetime(2026, 7, 29, 15, 0, tzinfo=UTC),
            )
        )
        session.add(
            LimitedExecutionCommandRow(
                id="command-a",
                plan_id="plan-a",
                parent_command_id=None,
                command_kind="execute",
                idempotency_token="3" * 64,
                adapter_id="official-customer-message-adapter",
                action_id="customer_service_reply_send",
                action_policy_version="test-v1",
                decision_hash="4" * 64,
                authorization_hash="5" * 64,
                permit_expires_at=datetime(
                    2026, 7, 29, 17, 0, tzinfo=UTC
                ),
                operation="customer_service.send_reply",
                target_json={
                    "case_id": "case-a",
                    "body_sha256": BODY_SHA,
                    "tenant_ref": "tenant-a",
                    "entity_ref": "entity-a",
                    "store_ref": "ozon-primary",
                },
                patch_json={},
                risk_limits_json={},
                risk_values_json={},
                risk_currency=None,
                portfolio_risk_json={},
                expected_state_hash="6" * 64,
                status="succeeded",
                queued_by="service-operator",
                claimed_by="message-worker",
                claimed_at=datetime(2026, 7, 29, 16, 0, tzinfo=UTC),
                lease_expires_at=datetime(
                    2026, 7, 29, 16, 5, tzinfo=UTC
                ),
                created_at=datetime(2026, 7, 29, 15, 30, tzinfo=UTC),
            )
        )
        session.add(
            LimitedExecutionReceiptRow(
                id="receipt-a",
                request_hash="7" * 64,
                command_id="command-a",
                request_id="request-a",
                trace_id="trace-a",
                outcome="succeeded",
                remote_operation_id="remote-message-a",
                resulting_state_hash="8" * 64,
                mutation_applied=True,
                error_code=None,
                error_detail=None,
                evidence_json=[
                    (
                        "evidence-event-7"
                        if authority_mode == "intake_only"
                        else "evidence-readback"
                    )
                ],
                recorded_by="message-worker",
                recorded_at=datetime(2026, 7, 29, 16, 10, tzinfo=UTC),
            )
        )
    service = ScopedCustomerServiceWorkspace(
        engine=database,
        source=FakeSource(source([case()], send_events())),
        evidence=(
            FakeEvidence(records=message_authority_evidence())
            if authority_mode != "unbound"
            else FakeEvidence()
        ),
        scoped_evidence=FakeScopedEvidence(),
        returns=FakeReturns(),
        repository=FakeRepository(approval()),
        action_policies=FakeActionPolicies(),
        message_readback_authority=(
            FakeMessageReadbackAuthority(
                overrides=(
                    {
                        "success": {
                            "readback_evidence_id": "evidence-event-7",
                            "readback_evidence_sha256": EVIDENCE_SHA,
                        }
                    }
                    if authority_mode == "intake_only"
                    else None
                )
            )
            if authority_mode != "unbound"
            else None
        ),
    )

    result = project(service)

    if authority_mode != "trusted":
        assert result["status"] == "blocked"
        assert result["cases"] == []
        expected = (
            "customer_service_message_readback_authority_unbound"
            if authority_mode == "unbound"
            else (
                "customer_service_message_readback_evidence_"
                "not_independent"
            )
        )
        assert expected in result["excluded"]["reason_counts"]
        return
    assert result["status"] == "ready"
    assert result["counts"]["verified_sends"] == 1
    item = result["cases"][0]
    assert item["stage"] == "awaiting_customer"
    assert item["execution_authority"]["status"] == "verified"
    assert item["execution_authority"]["receipt_id"] == "receipt-a"
    assert result["control_envelope"]["message_marked_sent"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_capture_authority_rejects_pii_and_replays_exact_source_event():
    database = engine()
    service = CustomerServiceAuthorityService(
        engine=database,
        evidence=FakeEvidence(),
        scoped_evidence=FakeScopedEvidence(),
    )
    captured = service.capture_case(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        external_case_ref="OZON-CASE-1",
        channel="ozon",
        order_external_id="order-a",
        product_id="product-a",
        sku="SKU-A",
        locale="ru-RU",
        classification="product_question",
        priority="normal",
        evidence_id="evidence-case",
        opened_at="2026-07-29T10:00:00+00:00",
        as_of=AS_OF,
    )
    first = service.append_event(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        case_id=captured["id"],
        source_event_ref="OZON-EVENT-1",
        sequence=1,
        event_type="case_opened",
        direction="system",
        locale="ru-RU",
        summary="case opened",
        body_sha256=None,
        evidence_id="evidence-event-1",
        effective_at="2026-07-29T11:00:00+00:00",
        as_of=AS_OF,
    )
    replay = service.append_event(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        case_id=captured["id"],
        source_event_ref="OZON-EVENT-1",
        sequence=1,
        event_type="case_opened",
        direction="system",
        locale="ru-RU",
        summary="case opened",
        body_sha256=None,
        evidence_id="evidence-event-1",
        effective_at="2026-07-29T11:00:00+00:00",
        as_of=AS_OF,
    )

    assert first["idempotent"] is False
    assert replay["idempotent"] is True
    with pytest.raises(ValueError, match="must not contain customer PII"):
        service.append_event(
            principal=principal(),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            case_id=captured["id"],
            source_event_ref="OZON-EVENT-2",
            sequence=2,
            event_type="triaged",
            direction="system",
            locale="ru-RU",
            summary="Customer email buyer@example.com",
            body_sha256=None,
            evidence_id="evidence-event-2",
            effective_at="2026-07-29T12:00:00+00:00",
            as_of=AS_OF,
        )


def test_cross_store_is_forbidden_before_reads():
    service = workspace(source([case()], basic_events()))

    with pytest.raises(PermissionError):
        service.project(
            principal=principal(),
            entity_scope=ENTITY_SCOPE,
            store_ref="other-store",
            as_of=AS_OF,
        )
