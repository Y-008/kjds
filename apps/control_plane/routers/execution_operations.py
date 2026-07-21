from __future__ import annotations

import json
import os
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from ..api_contracts import (
    AgentTaskInput,
    ApprovalDecisionInput,
    ApprovalInput,
    CapabilityEconomicAssessmentInput,
    ExecutionMetricObservationInput,
    ExecutionObservationWindowInput,
    GovernedExecutionDryRunInput,
    GovernedExecutionPlanInput,
    IncidentClosureInput,
    IncidentRecoveryCheckInput,
    IncidentRecoveryReviewInput,
    LimitedExecutionClaimInput,
    LimitedExecutionReceiptInput,
    OperationalIncidentInput,
    OperationsQueueScanInput,
    PilotActivationInput,
    PilotControlAttestationInput,
    PilotReviewInput,
    PilotReviewSubmissionInput,
    PilotRunCompletionInput,
    PilotRunReapInput,
    PilotRunStartInput,
    ReadOnlyClaimInput,
    ReadOnlyClaimReviewInput,
    ReadOnlyPilotInput,
    current_principal,
    ensure_role,
    run,
)
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


@router.get("/v1/governed-execution-adapters")
def list_governed_execution_adapters():
    return runtime.execution_plans.adapters()


@router.post("/v1/causal-policy-activation-handoffs/{handoff_id}/execution-plans", status_code=201)
def create_governed_execution_plan(
    handoff_id: str, body: GovernedExecutionPlanInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.execution_plans.create(handoff_id, **body.model_dump(), created_by=principal.actor_id))


@router.get("/v1/governed-execution-plans")
def list_governed_execution_plans():
    return run(runtime.execution_plans.list)


@router.get("/v1/governed-execution-plans/{plan_id}")
def get_governed_execution_plan(plan_id: str):
    return run(lambda: runtime.execution_plans.get(plan_id))


@router.post("/v1/governed-execution-plans/{plan_id}/dry-run", status_code=201)
def dry_run_governed_execution_plan(
    plan_id: str, body: GovernedExecutionDryRunInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(lambda: runtime.execution_plans.dry_run(plan_id, **body.model_dump(), performed_by=principal.actor_id))


@router.post("/v1/governed-execution-plans/{plan_id}/commands", status_code=201)
def queue_limited_execution_command(plan_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.limited_executor.queue(plan_id, queued_by=principal.actor_id))


@router.get("/v1/limited-execution-commands")
def list_limited_execution_commands():
    return run(runtime.limited_executor.list)


@router.get("/v1/limited-execution-commands/{command_id}")
def get_limited_execution_command(command_id: str):
    return run(lambda: runtime.limited_executor.get(command_id))


@router.post("/v1/limited-execution-commands/{command_id}/claim")
def claim_limited_execution_command(
    command_id: str, body: LimitedExecutionClaimInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "executor", "admin")
    return run(lambda: runtime.limited_executor.claim(command_id, **body.model_dump(), worker_id=principal.actor_id))


@router.post("/v1/limited-execution-commands/{command_id}/receipt", status_code=201)
def record_limited_execution_receipt(
    command_id: str,
    body: LimitedExecutionReceiptInput,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "executor", "admin")
    return run(
        lambda: runtime.limited_executor.record_receipt(
            command_id,
            **body.model_dump(),
            recorded_by=principal.actor_id,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        )
    )


@router.post("/v1/limited-execution-commands/{command_id}/rollback", status_code=201)
def request_limited_execution_rollback(command_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "risk", "admin")
    return run(lambda: runtime.limited_executor.request_rollback(command_id, requested_by=principal.actor_id))


@router.post("/v1/limited-execution-commands/{command_id}/observation-window", status_code=201)
def create_execution_observation_window(
    command_id: str, body: ExecutionObservationWindowInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.post_execution.create_window(command_id, **body.model_dump(), created_by=principal.actor_id)
    )


@router.get("/v1/execution-observation-windows")
def list_execution_observation_windows():
    return run(runtime.post_execution.list_windows)


@router.get("/v1/execution-observation-windows/{window_id}")
def get_execution_observation_window(window_id: str):
    return run(lambda: runtime.post_execution.get_window(window_id))


@router.post("/v1/execution-observation-windows/{window_id}/observations", status_code=201)
def record_execution_metric_observation(
    window_id: str, body: ExecutionMetricObservationInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "monitor", "operator", "admin")

    def record_and_open_incident():
        result = runtime.post_execution.observe(window_id, **body.model_dump(), created_by=principal.actor_id)
        if not result["guardrail_breached"]:
            return result
        window = runtime.post_execution.get_window(window_id)
        incident = runtime.incident_recovery.open(
            idempotency_key=f"post-execution-guardrail:{result['id']}",
            mode="live",
            severity="critical",
            trigger_type="post_execution_guardrail_breached",
            source_type="execution_metric_observation",
            source_id=result["id"],
            summary=f"Post-execution guardrail breached: {result['metric']}",
            impact=[
                f"observation_window:{window_id}",
                f"execution_command:{window['command_id']}",
                f"execution_plan:{window['plan_id']}",
            ],
            evidence_ids=body.evidence_ids,
            opened_by="post-execution-guardrail",
        )
        return {**result, "incident_id": incident["id"]}

    return run(record_and_open_incident)


@router.get("/v1/execution-observation-windows/{window_id}/evaluation")
def evaluate_execution_observation_window(window_id: str, as_of: str | None = None):
    return run(lambda: runtime.post_execution.evaluate(window_id, as_of=as_of))


@router.post("/v1/execution-observation-windows/{window_id}/capability-economics", status_code=201)
def assess_execution_capability_economics(
    window_id: str, body: CapabilityEconomicAssessmentInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "risk", "admin")
    return run(
        lambda: runtime.capability_economics.assess(window_id, **body.model_dump(), assessed_by=principal.actor_id)
    )


@router.get("/v1/capability-economic-assessments")
def list_capability_economic_assessments():
    return run(runtime.capability_economics.list)


@router.get("/v1/capability-economic-summaries")
def list_capability_economic_summaries():
    return run(runtime.capability_economics.summaries)


@router.post("/v1/operational-incidents", status_code=201)
def open_operational_incident(
    body: OperationalIncidentInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "risk", "admin")
    return run(lambda: runtime.incident_recovery.open(**body.model_dump(), opened_by=principal.actor_id))


@router.get("/v1/operational-incidents")
def list_operational_incidents():
    return run(runtime.incident_recovery.list)


@router.get("/v1/operational-incidents/{incident_id}")
def get_operational_incident(incident_id: str):
    return run(lambda: runtime.incident_recovery.get(incident_id))


@router.post("/v1/operational-incidents/{incident_id}/claim")
def claim_operational_incident(incident_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "risk", "admin")
    return run(lambda: runtime.incident_recovery.claim(incident_id, actor_id=principal.actor_id))


@router.post("/v1/operational-incidents/{incident_id}/checks", status_code=201)
def record_operational_incident_check(
    incident_id: str, body: IncidentRecoveryCheckInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "risk", "admin")
    return run(
        lambda: runtime.incident_recovery.record_check(incident_id, **body.model_dump(), actor_id=principal.actor_id)
    )


@router.post("/v1/operational-incidents/{incident_id}/review-request")
def request_operational_incident_review(incident_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "risk", "admin")
    return run(lambda: runtime.incident_recovery.submit_review(incident_id, actor_id=principal.actor_id))


@router.post("/v1/operational-incidents/{incident_id}/review", status_code=201)
def review_operational_incident(
    incident_id: str, body: IncidentRecoveryReviewInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "risk", "admin")
    return run(lambda: runtime.incident_recovery.review(incident_id, **body.model_dump(), actor_id=principal.actor_id))


@router.post("/v1/operational-incidents/{incident_id}/close")
def close_operational_incident(
    incident_id: str, body: IncidentClosureInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "admin")
    return run(lambda: runtime.incident_recovery.close(incident_id, **body.model_dump(), actor_id=principal.actor_id))


@router.get("/v1/operations-control/queue")
def list_operations_control_queue(as_of: str | None = None):
    return run(lambda: runtime.operations_queue.queue(as_of=as_of))


@router.post("/v1/operations-control/escalation-scan")
def scan_operations_control_escalations(
    body: OperationsQueueScanInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "monitor", "risk", "admin")
    return run(lambda: runtime.operations_queue.scan(as_of=body.as_of, actor_id=principal.actor_id))


@router.get("/v1/operations-control/escalations")
def list_operations_control_escalations():
    return run(runtime.operations_queue.escalations)


@router.post("/v1/read-only-pilots", status_code=201)
def create_read_only_pilot(body: ReadOnlyPilotInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.pilot_readiness.create(**body.model_dump(), requested_by=principal.actor_id))


@router.get("/v1/read-only-pilots")
def list_read_only_pilots():
    return run(runtime.pilot_readiness.list)


@router.get("/v1/read-only-pilots/{pilot_id}")
def get_read_only_pilot(pilot_id: str):
    return run(lambda: runtime.pilot_readiness.get(pilot_id))


@router.get("/v1/read-only-pilots/{pilot_id}/evaluation")
def evaluate_read_only_pilot(pilot_id: str, as_of: str | None = None):
    return run(lambda: runtime.pilot_readiness.evaluate(pilot_id, as_of=as_of))


@router.post("/v1/read-only-pilots/{pilot_id}/attestations", status_code=201)
def attest_read_only_pilot_control(
    pilot_id: str, body: PilotControlAttestationInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "compliance", "admin")
    return run(lambda: runtime.pilot_readiness.attest(pilot_id, **body.model_dump(), attested_by=principal.actor_id))


@router.post("/v1/read-only-pilots/{pilot_id}/review-request")
def submit_read_only_pilot_review(
    pilot_id: str, body: PilotReviewSubmissionInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.pilot_readiness.submit_review(pilot_id, actor_id=principal.actor_id, as_of=body.as_of))


@router.post("/v1/read-only-pilots/{pilot_id}/review")
def review_read_only_pilot(
    pilot_id: str, body: PilotReviewInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "admin")
    return run(lambda: runtime.pilot_readiness.review(pilot_id, **body.model_dump(), actor_id=principal.actor_id))


@router.post("/v1/read-only-pilots/{pilot_id}/activate")
def activate_read_only_pilot(
    pilot_id: str, body: PilotActivationInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "admin")
    return run(lambda: runtime.pilot_readiness.activate(pilot_id, actor_id=principal.actor_id, as_of=body.as_of))


@router.post("/v1/read-only-pilots/{pilot_id}/runs", status_code=201)
def start_read_only_pilot_run(
    pilot_id: str,
    body: PilotRunStartInput,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "pilot_reader", "admin")
    return run(
        lambda: runtime.pilot_runs.start(
            pilot_id,
            **body.model_dump(),
            worker_id=principal.actor_id,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        )
    )


@router.post("/v1/read-only-pilot-runs/{run_id}/complete")
def complete_read_only_pilot_run(
    run_id: str, body: PilotRunCompletionInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "pilot_reader", "admin")
    return run(lambda: runtime.pilot_runs.complete(run_id, **body.model_dump(), worker_id=principal.actor_id))


@router.post("/v1/read-only-pilot-runs/{run_id}/response-evidence", status_code=201)
async def capture_read_only_pilot_response(
    run_id: str,
    response_sha256: Annotated[str, Form(min_length=64, max_length=64)],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "pilot_reader", "admin")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Evidence file exceeds {max_bytes} bytes")
    return run(
        lambda: runtime.pilot_runs.capture_response(
            run_id, content=content_bytes, response_sha256=response_sha256, worker_id=principal.actor_id
        )
    )


@router.post("/v1/read-only-pilot-runs/{run_id}/response-checkpoint", status_code=201)
async def checkpoint_read_only_pilot_response(
    run_id: str,
    response_sha256: Annotated[str, Form(min_length=64, max_length=64)],
    response_byte_size: Annotated[int, Form(ge=1)],
    record_count: Annotated[int, Form(ge=0)],
    summary_json: Annotated[str, Form(min_length=2, max_length=8192)],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "pilot_reader", "admin")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Evidence file exceeds {max_bytes} bytes")
    try:
        summary = json.loads(summary_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="summary_json must be valid JSON") from exc
    return run(
        lambda: runtime.pilot_runs.checkpoint_success(
            run_id,
            content=content_bytes,
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=record_count,
            summary=summary,
            worker_id=principal.actor_id,
        )
    )


@router.post("/v1/read-only-pilot-runs/{run_id}/finalize")
def finalize_read_only_pilot_response(run_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "pilot_reader", "admin")
    return run(lambda: runtime.pilot_runs.finalize_captured(run_id, worker_id=principal.actor_id))


@router.get("/v1/read-only-pilot-runs")
def list_read_only_pilot_runs(
    pilot_id: str | None = None, principal: Annotated[Principal, Depends(current_principal)] = None
):
    ensure_role(principal, "pilot_reader", "operator", "reviewer", "admin")
    return run(lambda: runtime.pilot_runs.list(pilot_id=pilot_id))


@router.get("/v1/read-only-pilot-runs/{run_id}")
def get_read_only_pilot_run(run_id: str, principal: Annotated[Principal, Depends(current_principal)] = None):
    ensure_role(principal, "pilot_reader", "operator", "reviewer", "admin")
    return run(lambda: runtime.pilot_runs.get(run_id))


@router.post("/v1/read-only-pilot-runs/{run_id}/claims", status_code=201)
def propose_read_only_claim(
    run_id: str, body: ReadOnlyClaimInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.read_only_claims.propose(run_id, **body.model_dump(), proposed_by=principal.actor_id))


@router.get("/v1/read-only-claims")
def list_read_only_claims(
    run_id: str | None = None,
    status: str | None = None,
    principal: Annotated[Principal, Depends(current_principal)] = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: runtime.read_only_claims.list(run_id=run_id, status=status))


@router.get("/v1/read-only-claims/{claim_id}")
def get_read_only_claim(claim_id: str, principal: Annotated[Principal, Depends(current_principal)] = None):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: runtime.read_only_claims.get(claim_id))


@router.post("/v1/read-only-claims/{claim_id}/review")
def review_read_only_claim(
    claim_id: str, body: ReadOnlyClaimReviewInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: runtime.read_only_claims.review(claim_id, **body.model_dump(), reviewed_by=principal.actor_id))


@router.post("/v1/read-only-pilot-runs/reap")
def reap_read_only_pilot_runs(body: PilotRunReapInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "admin")
    return run(lambda: runtime.pilot_runs.reap_expired(as_of=body.as_of, limit=body.limit, actor_id=principal.actor_id))


@router.get("/v1/read-only-pilots/{pilot_id}/usage")
def get_read_only_pilot_usage(
    pilot_id: str, as_of: str | None = None, principal: Annotated[Principal, Depends(current_principal)] = None
):
    ensure_role(principal, "pilot_reader", "operator", "reviewer", "admin")
    return run(lambda: runtime.pilot_runs.usage(pilot_id, as_of=as_of))


@router.post("/v1/approvals", status_code=201)
def request_approval(body: ApprovalInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.commerce.request_approval(**body.model_dump(), requested_by=principal.actor_id))


@router.get("/v1/approvals")
def list_approvals(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "approver", "admin")
    return run(runtime.repo.list_approvals)


@router.post("/v1/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str, body: ApprovalDecisionInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "approver", "admin")

    def decide():
        approval = runtime.repo.get_approval(approval_id)
        if body.approved and approval.action == "listing.publish":
            runtime.sourcing.verify_listing_approval(
                draft_id=approval.resource_id, approval_id=approval.id, approval_payload=approval.payload
            )
        return runtime.commerce.decide_approval(approval_id, **body.model_dump(), decided_by=principal.actor_id)

    return run(decide)


@router.post("/v1/agent-tasks", status_code=201)
def submit_agent_task(body: AgentTaskInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.commerce.submit_agent_task(**body.model_dump(), requested_by=principal.actor_id))


@router.get("/v1/events")
def events(after: int = 0):
    return runtime.repo.events_after(after)


@router.get("/v1/outbox/status")
def outbox_status(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "monitor", "reviewer", "admin")
    return runtime.outbox.status()
