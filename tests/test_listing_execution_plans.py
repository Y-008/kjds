import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane import ai_listing as _ai_listing  # noqa: F401
from apps.control_plane import browser_capture_inbox as _browser_capture_inbox  # noqa: F401
from apps.control_plane.action_policies import ActionPolicyError
from apps.control_plane.causal_policies import CausalPolicyRow
from apps.control_plane.domain import Product
from apps.control_plane.evidence import EvidenceGrade, EvidenceRecordRow, EvidenceService
from apps.control_plane.execution_plans import ExecutionPlanRow, ExecutionPlanService
from apps.control_plane.limited_executor import (
    LimitedExecutionCommandRow,
    LimitedExecutionReceiptRow,
    LimitedExecutorService,
)
from apps.control_plane.pilot_readiness import ReadOnlyPilotRow
from apps.control_plane.pilot_runs import ReadOnlyPilotRunRow
from apps.control_plane.policy_shadow import PolicyActivationHandoffRow
from apps.control_plane.read_only_claims import ReadOnlyClaimRow
from apps.control_plane.readiness import LISTING_EXECUTION_READINESS_KEYS
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.security import KillSwitchService, WritesDisabled
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import ListingDraft, listing_approval_payload
from apps.control_plane.sql_repository import ApprovalRow, Base


class ListingStore:
    def __init__(self, draft):
        self.draft = draft

    def get_listing_draft(self, draft_id):
        if draft_id != self.draft.id:
            raise KeyError(draft_id)
        return self.draft


class ListingSourcing:
    def __init__(self, draft):
        self.store = ListingStore(draft)

    def verify_listing_approval(self, *, draft_id, approval_id, approval_payload):
        draft = self.store.get_listing_draft(draft_id)
        if draft.approval_id != approval_id or approval_payload["draft_id"] != draft.id:
            raise ValueError("Listing approval does not match the stored draft")
        return draft


class NoCausalSource:
    def get_handoff(self, _handoff_id):
        raise AssertionError("Listing execution must not resolve a causal handoff")


def execution_bundle(path, body, *, status_code=200, request_context=None):
    encoded = json.dumps(body, separators=(",", ":")).encode()
    bundle_value = {
        "schema_version": "ozon-response-bundle-v2",
        "contract_version": "ozon-execution-v1",
        "responses": [
            {
                "path": path,
                "status_code": status_code,
                "headers": {},
                "body_sha256": hashlib.sha256(encoded).hexdigest(),
                "body_base64": base64.b64encode(encoded).decode(),
            }
        ],
    }
    if request_context is not None:
        bundle_value["request_context"] = request_context
    return json.dumps(bundle_value, sort_keys=True, separators=(",", ":")).encode()


def bundle(info, attributes):
    responses = []
    for path, body in (
        ("/v3/product/info/list", info),
        ("/v4/product/info/attributes", attributes),
    ):
        encoded = json.dumps(body, separators=(",", ":")).encode()
        responses.append(
            {
                "path": path,
                "status_code": 200,
                "headers": {},
                "body_sha256": hashlib.sha256(encoded).hexdigest(),
                "body_base64": base64.b64encode(encoded).decode(),
            }
        )
    return json.dumps(
        {
            "schema_version": "ozon-response-bundle-v2",
            "contract_version": "ozon-product-read-v1",
            "responses": responses,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


@pytest.mark.parametrize("mutation", ["body_hash", "duplicate_path"])
def test_ozon_before_state_bundle_rejects_ambiguous_or_tampered_responses(mutation):
    info = {"items": [{"offer_id": "offer-1"}]}
    attributes = {"result": [{"offer_id": "offer-1"}]}
    payload = json.loads(bundle(info, attributes))
    if mutation == "body_hash":
        payload["responses"][0]["body_sha256"] = "0" * 64
    else:
        payload["responses"].append(dict(payload["responses"][0]))

    with pytest.raises(ValueError, match="unsupported contract"):
        ExecutionPlanService._ozon_state_from_bundle(
            json.dumps(payload).encode(),
            offer_id="offer-1",
        )


def test_approved_listing_plan_derives_ozon_target_and_items_server_side():
    assert CausalPolicyRow.__tablename__ == "causal_policies"
    assert PolicyActivationHandoffRow.__tablename__ == "causal_policy_activation_handoffs"
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    repo = InMemoryRepository()
    product = Product(sku="ozon-offer-001", name="Storage box")
    repo.add_product(product)
    commerce = CommerceService(repo, evidence_validator=evidence.require_valid)
    draft = ListingDraft(
        product_id=product.id,
        offer_id="off_internal_supplier_key",
        scenario_id="scenario-1",
        target_platform="OZON",
        listing_data={
            "title": "Контейнер для хранения",
            "description": "Verified facts only",
            "category_id": "123",
            "attributes": [{"complex_id": 0, "id": 1, "values": [{"value": "white"}]}],
            "images": ["https://cdn.example.test/approved.jpg"],
            "content_asset_ids": ["asset-1"],
        },
        requested_by="listing-requester",
    )
    scenario = type(
        "Scenario",
        (),
        {
            "cm3_cny": Decimal("10"),
            "cm3_rate": Decimal("0.1"),
            "cost_complete": True,
            "cost_breakdown": lambda self: {},
            "cost_evidence": {},
            "cost_states": {},
            "template_id": "profit-v1",
            "missing_cost_evidence": [],
            "unknown_costs": [],
            "evidence": [],
        },
    )()
    source_approval = commerce.request_approval(
        action="listing.publish",
        resource_type="listing_draft",
        resource_id=draft.id,
        requested_by=draft.requested_by,
        payload=listing_approval_payload(draft, scenario),
    )
    commerce.decide_approval(
        source_approval.id,
        approved=True,
        decided_by="independent-listing-reviewer",
        reason="Snapshot independently reviewed",
    )
    draft.approval_id = source_approval.id

    before_info = {"items": [{"offer_id": product.sku, "version": 1}]}
    rollback_item = {
        "offer_id": product.sku,
        "name": "Prior title",
        "description": "Prior description",
        "description_category_id": 123,
        "attributes": [{"complex_id": 0, "id": 1, "values": [{"value": "prior"}]}],
        "images": ["https://cdn.example.test/prior.jpg"],
    }
    before_attributes = {"result": [rollback_item]}
    before_state = {
        "contract_version": "ozon-product-read-v1",
        "offer_id": product.sku,
        "info": before_info,
        "attributes": before_attributes,
    }
    state_hash = ExecutionPlanService._hash(before_state)
    raw = bundle(before_info, before_attributes)
    raw_record = evidence.capture(
        content=raw,
        filename="before.json",
        content_type="application/json",
        source="ozon-isolated-read-worker",
        source_ref="run-1",
        grade=EvidenceGrade.A,
        effective_at="2026-07-24T00:00:00+00:00",
        effective_until=None,
        created_by="ozon-read-worker",
        metadata={
            "raw_response_stored": True,
            "response_sha256": hashlib.sha256(raw).hexdigest(),
        },
    )
    summary_record = evidence.capture(
        content=b'{"outcome":"succeeded","raw_response_stored":true}',
        filename="summary.json",
        content_type="application/json",
        source="ozon-isolated-read-worker",
        source_ref="run-1",
        grade=EvidenceGrade.B,
        effective_at="2026-07-24T00:00:00+00:00",
        effective_until=None,
        created_by="ozon-read-worker",
        metadata={"raw_response_evidence_id": raw_record.id},
    )
    evidence.link(
        evidence_id=raw_record.id,
        target_type="read_only_pilot_run",
        target_id="run-1",
        relationship="raw_response",
        created_by="ozon-read-worker",
    )
    now = datetime(2026, 7, 24, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            ApprovalRow(
                id=source_approval.id,
                action=source_approval.action,
                resource_type=source_approval.resource_type,
                resource_id=source_approval.resource_id,
                requested_by=source_approval.requested_by,
                payload_json=source_approval.payload,
                status=source_approval.status.value,
                decided_by=source_approval.decided_by,
                decision_reason=source_approval.decision_reason,
                created_at=now,
            )
        )
        session.add(
            ReadOnlyPilotRow(
                id="pilot-1",
                idempotency_key="pilot-1",
                platform="ozon",
                account_alias="ozon-main",
                allowed_operations_json=["ozon.product.read"],
                max_daily_requests=1,
                max_targets=1,
                starts_at=now,
                ends_at=now,
                evidence_json=[raw_record.id],
                status="active",
                requested_by="owner",
                reviewed_by="reviewer",
                review_rationale="approved",
                activated_by="admin",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ReadOnlyPilotRunRow(
                id="run-1",
                idempotency_key="run-1",
                request_hash="a" * 64,
                pilot_id="pilot-1",
                operation="ozon.product.read",
                target_hash=hashlib.sha256(product.sku.encode()).hexdigest(),
                worker_id="ozon-read-worker",
                request_id="req-1",
                trace_id="trace-1",
                status="completed",
                outcome="succeeded",
                response_sha256=raw_record.sha256,
                response_byte_size=len(raw),
                record_count=2,
                summary_json={
                    "contract_version": "ozon-product-read-v1",
                    "state_sha256": state_hash,
                    "info_item_count": 1,
                    "attribute_item_count": 1,
                },
                error_code=None,
                evidence_id=summary_record.id,
                started_at=now,
                lease_expires_at=now,
                completed_at=now,
            )
        )
        session.add(
            ReadOnlyClaimRow(
                id="claim-1",
                idempotency_key="claim-1",
                request_hash="b" * 64,
                run_id="run-1",
                claim_type="product_attribute",
                payload_json={"target_verified": True},
                payload_hash="c" * 64,
                source_state_sha256=state_hash,
                effective_at=now,
                evidence_id=summary_record.id,
                status="accepted",
                proposed_by="reader",
                reviewed_by="claim-reviewer",
                decision="accepted",
                rationale="Target and state accepted",
                created_at=now,
                reviewed_at=now,
            )
        )
    def listing_readiness(context):
        identity_matches = context.executor_identity_ref in {None, "ozon-worker"}
        return {
            key: {
                "ready": identity_matches if key == "ozon.execution_identity" else True,
                "evidence_ids": [raw_record.id],
                "blocking_reasons": (
                    []
                    if key != "ozon.execution_identity" or identity_matches
                    else ["OZON_EXECUTION_IDENTITY_MISMATCH"]
                ),
            }
            for key in LISTING_EXECUTION_READINESS_KEYS
        }

    service = ExecutionPlanService(
        engine=engine,
        policy_shadow=NoCausalSource(),
        policies=None,
        evidence=evidence,
        commerce=commerce,
        sourcing=ListingSourcing(draft),
        repository=repo,
        readiness_provider=listing_readiness,
    )

    plan = service.create_from_approved_listing(
        draft.id,
        idempotency_key="listing-plan-1",
        precondition_state_hash=state_hash,
        evidence_ids=[summary_record.id],
        created_by="execution-planner",
        risk_limits={
            "max_quantity": "1",
            "max_daily_runs": "1",
            "max_expected_loss": "500",
        },
        risk_values={"quantity": "1", "expected_loss": "100"},
        risk_currency="CNY",
    )

    assert plan["source_kind"] == "approved_listing_draft"
    assert plan["source_id"] == draft.id
    assert plan["source_approval_id"] == source_approval.id
    assert plan["target"] == {"offer_id": product.sku}
    assert draft.offer_id not in json.dumps(plan, ensure_ascii=False)
    assert plan["intended_patch"]["item"]["offer_id"] == product.sku
    assert plan["intended_patch"]["item"]["name"] == draft.listing_data["title"]
    assert plan["rollback_patch"]["item"] == rollback_item
    assert plan["source_validity_status"] == "active"
    assert commerce.repo.get_approval(plan["approval_id"]).payload[
        "live_execution_supported"
    ] is True
    retry = service.create_from_approved_listing(
        draft.id,
        idempotency_key="listing-plan-1",
        precondition_state_hash=state_hash,
        evidence_ids=[summary_record.id],
        created_by="execution-planner",
        risk_limits={
            "max_quantity": "1",
            "max_daily_runs": "1",
            "max_expected_loss": "500",
        },
        risk_values={"quantity": "1", "expected_loss": "100"},
        risk_currency="CNY",
    )
    assert retry["id"] == plan["id"]
    with Session(engine) as session:
        assert session.query(ExecutionPlanRow).count() == 1

    with pytest.raises(ValueError, match="immutable content"):
        service.create_from_approved_listing(
            draft.id,
            idempotency_key="listing-plan-1",
            precondition_state_hash=state_hash,
            evidence_ids=[summary_record.id],
            created_by="execution-planner",
            risk_limits={
                "max_quantity": "1",
                "max_daily_runs": "1",
                "max_expected_loss": "500",
            },
            risk_values={"quantity": "1", "expected_loss": "101"},
            risk_currency="CNY",
        )

    dry_run = service.dry_run(
        plan["id"],
        current_state_hash=state_hash,
        evidence_ids=[summary_record.id],
        performed_by="dry-run-operator",
    )
    assert dry_run["passed"] is True
    commerce.decide_approval(
        plan["approval_id"],
        approved=True,
        decided_by="execution-approver",
        reason="Execution snapshot independently approved",
    )
    assert service.get(plan["id"])["ready_for_executor"] is True

    executor = LimitedExecutorService(
        engine=engine,
        execution_plans=service,
        evidence=evidence,
        kill_switch=KillSwitchService(engine),
        enabled=True,
    )
    with pytest.raises(ValueError, match="not ready"):
        with Session(engine) as session, session.begin():
            session.execute(
                update(EvidenceRecordRow)
                .where(EvidenceRecordRow.id == raw_record.id)
                .values(effective_until=datetime.now(UTC) - timedelta(microseconds=1))
            )
        executor.queue(plan["id"], queued_by="execution-operator")

    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceRecordRow)
            .where(EvidenceRecordRow.id == raw_record.id)
            .values(effective_until=None)
        )
    command = executor.queue(plan["id"], queued_by="execution-operator")
    assert command["status"] == "queued"
    with pytest.raises(
        ActionPolicyError,
        match="READINESS_REQUIRED:ozon.execution_identity",
    ):
        executor.claim(
            command["id"],
            current_state_hash=state_hash,
            worker_id="other-worker",
        )

    executor.kill_switch.set_state(
        engaged=True,
        reason="Readiness revoked before claim",
        actor_id="risk-owner",
    )
    with pytest.raises(WritesDisabled, match="Readiness revoked before claim"):
        executor.claim(
            command["id"],
            current_state_hash=state_hash,
            worker_id="ozon-worker",
        )
    executor.kill_switch.set_state(
        engaged=False,
        reason="Continue claim revocation test",
        actor_id="risk-owner",
    )
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceRecordRow)
            .where(EvidenceRecordRow.id == raw_record.id)
            .values(effective_until=datetime.now(UTC) - timedelta(microseconds=1))
        )
    with pytest.raises(ValueError, match="became invalid before claim"):
        executor.claim(
            command["id"],
            current_state_hash=state_hash,
            worker_id="ozon-worker",
        )

    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceRecordRow)
            .where(EvidenceRecordRow.id == raw_record.id)
            .values(effective_until=None)
        )
    claimed = executor.claim(
        command["id"],
        current_state_hash=state_hash,
        worker_id="ozon-worker",
    )
    assert claimed["status"] == "claimed"
    before_artifact = executor.capture_execution_artifact(
        command["id"],
        artifact_kind="before_read",
        content=raw,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        sequence_number=None,
        worker_id="ozon-worker",
    )
    assert before_artifact["state_hash"] == state_hash
    assert executor.capture_execution_artifact(
        command["id"],
        artifact_kind="before_read",
        content=raw,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        sequence_number=None,
        worker_id="ozon-worker",
    )["evidence_id"] == before_artifact["evidence_id"]
    with pytest.raises(ValueError, match="immutable content"):
        conflicting_before = raw + b" "
        executor.capture_execution_artifact(
            command["id"],
            artifact_kind="before_read",
            content=conflicting_before,
            response_sha256=hashlib.sha256(conflicting_before).hexdigest(),
            sequence_number=None,
            worker_id="ozon-worker",
        )

    executor.kill_switch.set_state(
        engaged=True,
        reason="Execution revoked after claim",
        actor_id="risk-owner",
    )
    with pytest.raises(WritesDisabled, match="Execution revoked after claim"):
        executor.begin_write_attempt(
            command["id"],
            worker_id="ozon-worker",
        )
    executor.kill_switch.set_state(
        engaged=False,
        reason="Continue write-attempt revocation test",
        actor_id="risk-owner",
    )
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceRecordRow)
            .where(EvidenceRecordRow.id == raw_record.id)
            .values(effective_until=datetime.now(UTC) - timedelta(microseconds=1))
        )
    with pytest.raises(ValueError, match="became invalid before the write attempt"):
        executor.begin_write_attempt(
            command["id"],
            worker_id="ozon-worker",
        )

    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceRecordRow)
            .where(EvidenceRecordRow.id == raw_record.id)
            .values(effective_until=None)
        )
    started = executor.begin_write_attempt(
        command["id"],
        worker_id="ozon-worker",
    )
    assert started["status"] == "write_started"
    assert started["write_attempt_consumed"] is True
    with pytest.raises(ValueError, match="not available"):
        executor.begin_write_attempt(
            command["id"],
            worker_id="ozon-worker",
        )

    import_raw = execution_bundle(
        "/v3/product/import",
        {"result": {"task_id": 42}},
    )
    import_artifact = executor.capture_execution_artifact(
        command["id"],
        artifact_kind="product_import_response",
        content=import_raw,
        response_sha256=hashlib.sha256(import_raw).hexdigest(),
        sequence_number=None,
        worker_id="ozon-worker",
    )
    assert import_artifact["remote_operation_id"] == "42"
    status_raw = execution_bundle(
        "/v1/product/import/info",
        {
            "result": {
                "items": [
                    {
                        "offer_id": product.sku,
                        "status": "imported",
                        "errors": [],
                    }
                ]
            }
        },
        request_context={"task_id": "42"},
    )
    status_artifact = executor.capture_execution_artifact(
        command["id"],
        artifact_kind="import_status_response",
        content=status_raw,
        response_sha256=hashlib.sha256(status_raw).hexdigest(),
        sequence_number=0,
        worker_id="ozon-worker",
    )
    assert status_artifact["import_outcome"] == "succeeded"
    status_body = json.loads(
        base64.b64decode(json.loads(status_raw)["responses"][0]["body_base64"])
    )
    assert "task_id" not in status_body["result"]

    after_info = {"items": [{"offer_id": product.sku, "version": 2}]}
    after_attributes = {"result": [plan["intended_patch"]["item"]]}
    after_raw = bundle(after_info, after_attributes)
    after_state_hash = ExecutionPlanService._hash(
        {
            "contract_version": "ozon-product-read-v1",
            "offer_id": product.sku,
            "info": after_info,
            "attributes": after_attributes,
        }
    )
    after_artifact = executor.capture_execution_artifact(
        command["id"],
        artifact_kind="after_read",
        content=after_raw,
        response_sha256=hashlib.sha256(after_raw).hexdigest(),
        sequence_number=None,
        worker_id="ozon-worker",
    )
    assert after_artifact["state_hash"] == after_state_hash
    receipt = executor.record_receipt(
        command["id"],
        outcome="succeeded",
        remote_operation_id="42",
        resulting_state_hash=after_state_hash,
        mutation_applied=True,
        error_code=None,
        error_detail=None,
        evidence_ids=[
            summary_record.id,
            before_artifact["evidence_id"],
            import_artifact["evidence_id"],
            status_artifact["evidence_id"],
            after_artifact["evidence_id"],
        ],
        recorded_by="ozon-worker",
    )
    assert receipt["outcome"] == "succeeded"
    assert receipt["remote_operation_id"] == "42"


def test_late_execution_receipt_is_persisted_as_uncertain() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    source = evidence.capture(
        content=b"late execution evidence",
        filename="late.txt",
        content_type="text/plain",
        source="test",
        source_ref="late-execution",
        grade=EvidenceGrade.A,
        effective_at="2026-07-24T00:00:00+00:00",
        effective_until=None,
        created_by="ozon-worker",
    )
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(
            LimitedExecutionCommandRow(
                id="lxc-late",
                plan_id="gxp-late",
                parent_command_id=None,
                command_kind="execute",
                idempotency_token="a" * 64,
                adapter_id="mock.adapter",
                action_id="listing_publish",
                action_policy_version="2026-07-24.1",
                decision_hash="b" * 64,
                authorization_hash="c" * 64,
                permit_expires_at=now + timedelta(minutes=5),
                operation="mock.execute",
                target_json={"offer_id": "offer-1"},
                patch_json={"item": {"offer_id": "offer-1"}},
                risk_limits_json={},
                risk_values_json={},
                risk_currency=None,
                portfolio_risk_json={},
                expected_state_hash="d" * 64,
                status="write_started",
                queued_by="operator",
                claimed_by="ozon-worker",
                claimed_at=now - timedelta(minutes=2),
                lease_expires_at=now - timedelta(minutes=1),
                created_at=now - timedelta(minutes=3),
            )
        )
    executor = LimitedExecutorService(
        engine=engine,
        execution_plans=SimpleNamespace(
            action_policies=SimpleNamespace(),
            action_authorization=SimpleNamespace(),
        ),
        evidence=evidence,
        kill_switch=KillSwitchService(engine),
        enabled=True,
    )

    receipt = executor.record_receipt(
        "lxc-late",
        outcome="failed",
        remote_operation_id="42",
        resulting_state_hash=None,
        mutation_applied=False,
        error_code="OZON_IMPORT_FAILED",
        error_detail="Ozon rejected the task",
        evidence_ids=[source.id],
        recorded_by="ozon-worker",
        request_id="req-late",
        trace_id="trace-late",
    )

    assert receipt["outcome"] == "uncertain"
    assert receipt["error_code"] == "EXECUTION_LEASE_EXPIRED"
    assert receipt["remote_operation_id"] == "42"
    assert executor.get("lxc-late")["status"] == "uncertain"
    retry = executor.record_receipt(
        "lxc-late",
        outcome="failed",
        remote_operation_id="42",
        resulting_state_hash=None,
        mutation_applied=False,
        error_code="OZON_IMPORT_FAILED",
        error_detail="Ozon rejected the task",
        evidence_ids=[source.id],
        recorded_by="ozon-worker",
        request_id="req-retry",
        trace_id="trace-retry",
    )
    assert retry["id"] == receipt["id"]
    with Session(engine) as session:
        assert session.query(LimitedExecutionReceiptRow).count() == 1
