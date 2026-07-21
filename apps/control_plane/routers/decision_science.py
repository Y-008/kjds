from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..api_contracts import (
    CausalExperimentProtocolInput,
    CausalExperimentReviewInput,
    CausalKnowledgeInput,
    CausalPolicyContextInput,
    CausalPolicyInput,
    CausalPolicyReleaseInput,
    CausalPolicyReviewInput,
    CausalPolicyStageOutcomeInput,
    DecisionAnalysisInput,
    DecisionAnalysisReviewInput,
    DecisionContractInput,
    DecisionOutcomeInput,
    DecisionResolutionInput,
    ExperimentAssignmentInput,
    ExperimentInput,
    ExperimentObservationInput,
    ExperimentSafetyCheckInput,
    ExperimentTransitionInput,
    PolicyActivationInput,
    PolicyEvaluationInput,
    PolicyShadowBatchInput,
    current_principal,
    ensure_role,
    run,
)
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


@router.get("/v1/interaction-profiles")
def interaction_profiles():
    return runtime.decision_contracts.profiles()


@router.post("/v1/decision-contracts", status_code=201)
def create_decision_contract(body: DecisionContractInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "admin")
    return run(lambda: runtime.decision_contracts.create(**body.model_dump(), requested_by=principal.actor_id))


@router.get("/v1/decision-contracts")
def list_decision_contracts(limit: int = 100):
    return runtime.decision_contracts.list(limit)


@router.get("/v1/decision-contracts/{contract_id}")
def get_decision_contract(contract_id: str):
    return run(lambda: runtime.decision_contracts.get(contract_id))


@router.post("/v1/decision-contracts/{contract_id}/analyses", status_code=201)
def submit_decision_analysis(
    contract_id: str, body: DecisionAnalysisInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: runtime.decision_lifecycle.submit_analysis(
            contract_id, **body.model_dump(), submitted_by=principal.actor_id
        )
    )


@router.get("/v1/decision-analyses")
def list_decision_analyses(contract_id: str | None = None):
    return runtime.decision_lifecycle.list_analyses(contract_id)


@router.get("/v1/decision-analyses/{analysis_id}")
def get_decision_analysis(analysis_id: str):
    return run(lambda: runtime.decision_lifecycle.get_analysis(analysis_id))


@router.post("/v1/decision-analyses/{analysis_id}/reviews", status_code=201)
def review_decision_analysis(
    analysis_id: str, body: DecisionAnalysisReviewInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: runtime.decision_lifecycle.review_analysis(
            analysis_id, **body.model_dump(), reviewed_by=principal.actor_id
        )
    )


@router.get("/v1/decision-analyses/{analysis_id}/reviews")
def list_decision_analysis_reviews(analysis_id: str):
    return runtime.decision_lifecycle.list_reviews(analysis_id)


@router.post("/v1/decision-contracts/{contract_id}/resolution", status_code=201)
def resolve_decision_contract(
    contract_id: str, body: DecisionResolutionInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: runtime.decision_lifecycle.resolve(contract_id, **body.model_dump(), decided_by=principal.actor_id)
    )


@router.get("/v1/decision-resolutions")
def list_decision_resolutions():
    return runtime.decision_lifecycle.list_resolutions()


@router.post("/v1/decision-resolutions/{resolution_id}/outcome", status_code=201)
def record_decision_outcome(
    resolution_id: str, body: DecisionOutcomeInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: runtime.decision_lifecycle.record_outcome(
            resolution_id, **body.model_dump(), recorded_by=principal.actor_id
        )
    )


@router.get("/v1/decision-outcomes")
def list_decision_outcomes():
    return runtime.decision_lifecycle.list_outcomes()


@router.get("/v1/decision-calibration")
def decision_calibration():
    return runtime.decision_lifecycle.calibration()


@router.post("/v1/decision-resolutions/{resolution_id}/experiment", status_code=201)
def register_causal_experiment(
    resolution_id: str, body: CausalExperimentProtocolInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: runtime.causal_experiments.register(resolution_id, **body.model_dump(), created_by=principal.actor_id)
    )


@router.get("/v1/causal-experiments")
def list_causal_experiments():
    return runtime.causal_experiments.list()


@router.get("/v1/causal-experiments/{protocol_id}")
def get_causal_experiment(protocol_id: str):
    return run(lambda: runtime.causal_experiments.get(protocol_id))


@router.get("/v1/causal-experiments/{protocol_id}/evaluation")
def evaluate_causal_experiment(protocol_id: str):
    return run(lambda: runtime.causal_experiments.evaluate(protocol_id))


@router.post("/v1/causal-experiments/{protocol_id}/events", status_code=201)
def transition_causal_experiment(
    protocol_id: str, body: ExperimentTransitionInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: runtime.causal_experiments.transition(protocol_id, **body.model_dump(), created_by=principal.actor_id)
    )


@router.post("/v1/causal-experiments/{protocol_id}/assignments", status_code=201)
def assign_causal_experiment(
    protocol_id: str, body: ExperimentAssignmentInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.causal_experiments.assign(protocol_id, **body.model_dump()))


@router.post("/v1/causal-experiment-assignments/{assignment_id}/observation", status_code=201)
def observe_causal_experiment(
    assignment_id: str, body: ExperimentObservationInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.causal_experiments.observe(assignment_id, **body.model_dump(), created_by=principal.actor_id)
    )


@router.post("/v1/causal-experiments/{protocol_id}/safety-checks", status_code=201)
def record_causal_experiment_safety(
    protocol_id: str, body: ExperimentSafetyCheckInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: runtime.causal_experiments.record_safety_check(
            protocol_id, **body.model_dump(), created_by=principal.actor_id
        )
    )


@router.post("/v1/causal-experiments/{protocol_id}/reviews", status_code=201)
def review_causal_experiment(
    protocol_id: str, body: CausalExperimentReviewInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: runtime.causal_knowledge.review_experiment(
            protocol_id, **body.model_dump(), reviewed_by=principal.actor_id
        )
    )


@router.get("/v1/causal-experiments/{protocol_id}/reviews")
def list_causal_experiment_reviews(protocol_id: str):
    return run(lambda: runtime.causal_knowledge.list_reviews(protocol_id))


@router.post("/v1/causal-experiments/{protocol_id}/knowledge", status_code=201)
def publish_causal_knowledge(
    protocol_id: str, body: CausalKnowledgeInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: runtime.causal_knowledge.publish(protocol_id, **body.model_dump(), created_by=principal.actor_id)
    )


@router.get("/v1/causal-knowledge")
def list_causal_knowledge(usable_only: bool = False):
    return runtime.causal_knowledge.list(usable_only=usable_only)


@router.get("/v1/causal-knowledge/{knowledge_id}")
def get_causal_knowledge(knowledge_id: str):
    return run(lambda: runtime.causal_knowledge.get(knowledge_id))


@router.post("/v1/causal-policies", status_code=201)
def propose_causal_policy(body: CausalPolicyInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.causal_policies.propose(**body.model_dump(), proposed_by=principal.actor_id))


@router.get("/v1/causal-policies")
def list_causal_policies():
    return runtime.causal_policies.list()


@router.get("/v1/causal-policies/{policy_id}")
def get_causal_policy(policy_id: str):
    return run(lambda: runtime.causal_policies.get(policy_id))


@router.post("/v1/causal-policies/{policy_id}/reviews", status_code=201)
def review_causal_policy(
    policy_id: str, body: CausalPolicyReviewInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: runtime.causal_policies.review(policy_id, **body.model_dump(), reviewed_by=principal.actor_id))


@router.post("/v1/causal-policies/{policy_id}/releases", status_code=201)
def release_causal_policy_stage(
    policy_id: str, body: CausalPolicyReleaseInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: runtime.causal_policies.release_stage(policy_id, **body.model_dump(), approved_by=principal.actor_id)
    )


@router.post("/v1/causal-policy-releases/{release_id}/outcome", status_code=201)
def record_causal_policy_stage_outcome(
    release_id: str, body: CausalPolicyStageOutcomeInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: runtime.policy_shadow.record_stage_outcome(
            release_id, **body.model_dump(), recorded_by=principal.actor_id
        )
    )


@router.post("/v1/causal-policies/{policy_id}/evaluation")
def evaluate_causal_policy_context(
    policy_id: str, body: CausalPolicyContextInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "approver", "admin")
    return run(lambda: runtime.causal_policies.evaluate_context(policy_id, body.context))


@router.post("/v1/causal-policy-releases/{release_id}/evaluations", status_code=201)
def record_causal_policy_evaluation(
    release_id: str, body: PolicyEvaluationInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.policy_shadow.record_evaluation(
            release_id, **body.model_dump(), evaluated_by=principal.actor_id
        )
    )


@router.post("/v1/causal-policy-releases/{release_id}/shadow-batches", status_code=201)
def run_causal_policy_shadow_batch(
    release_id: str, body: PolicyShadowBatchInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.policy_shadow.run_shadow_batch(release_id, **body.model_dump(), created_by=principal.actor_id)
    )


@router.get("/v1/causal-policy-evaluations")
def list_causal_policy_evaluations(policy_id: str | None = None):
    return run(lambda: runtime.policy_shadow.list_evaluations(policy_id))


@router.get("/v1/causal-policy-shadow-batches")
def list_causal_policy_shadow_batches(policy_id: str | None = None):
    return run(lambda: runtime.policy_shadow.list_batches(policy_id))


@router.post("/v1/causal-policy-releases/{release_id}/activation-handoff", status_code=201)
def request_causal_policy_activation(
    release_id: str, body: PolicyActivationInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.policy_shadow.request_activation(
            release_id, **body.model_dump(), requested_by=principal.actor_id
        )
    )


@router.get("/v1/causal-policy-activation-handoffs")
def list_causal_policy_activation_handoffs():
    return run(runtime.policy_shadow.list_handoffs)


@router.get("/v1/causal-policy-activation-handoffs/{handoff_id}")
def get_causal_policy_activation_handoff(handoff_id: str):
    return run(lambda: runtime.policy_shadow.get_handoff(handoff_id))


@router.post("/v1/experiments", status_code=201)
def create_experiment(body: ExperimentInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.content.create_experiment(**body.model_dump()))


@router.post("/v1/experiments/{experiment_id}/start")
def start_experiment(experiment_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.content.start_experiment(experiment_id))
