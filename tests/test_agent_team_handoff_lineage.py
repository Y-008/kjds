"""Acceptance contracts for the full TeamAgent handoff lineage.

These tests intentionally exercise only the public coordinator API.  A handoff
is a capability-bearing lineage link, so merely referring to an existing
``handoff_ref`` is insufficient: every child-task field must agree with the
completed source, the target thread, and the handoff contract.
"""

import hashlib
import json
from datetime import UTC, datetime

import pytest

from apps.control_plane.agent_team_orchestration import (
    OrchestrationError,
    TaskState,
    TeamAgentCoordinator,
)
from apps.control_plane.enterprise_control import ExactScope

SESSION_REF = "session-lineage"
SOURCE_THREAD_REF = "thread-source"
TARGET_THREAD_REF = "thread-target"
SOURCE_TASK_REF = "task-source"
CHILD_TASK_REF = "task-child"
TARGET_ROLE = "independent-reviewer"
TRACE_ID = "trace-handoff-lineage-001"
SOURCE_EVIDENCE = ("evidence-source-a", "evidence-source-b")
HANDOFF_EVIDENCE = ("evidence-source-a",)
ACCEPTANCE_CONTRACT = {
    "checks": ["cite-input-evidence", "return-observation-only"],
    "deliverable": "reviewed-summary",
}
SCOPE = ExactScope("tenant-lineage", "entity-lineage", "store-lineage")
AS_OF = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)


def _coordinator_with_source(*, completed: bool = True) -> TeamAgentCoordinator:
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref=SESSION_REF,
        scope=SCOPE,
        objective="exercise a bounded source-to-reviewer handoff",
        owner_id="portfolio-controller",
        max_parallel=2,
        created_at=AS_OF,
    )
    coordinator.fork_thread(
        session_ref=SESSION_REF,
        thread_ref=SOURCE_THREAD_REF,
        title="source work",
        created_at=AS_OF,
    )
    coordinator.submit_task(
        session_ref=SESSION_REF,
        task_ref=SOURCE_TASK_REF,
        thread_ref=SOURCE_THREAD_REF,
        agent_id="source-agent",
        role="source-author",
        objective="produce an evidence-backed observation",
        idempotency_key="source-task-v1",
        evidence_required=True,
        evidence_refs=SOURCE_EVIDENCE,
        trace_id=TRACE_ID,
        created_at=AS_OF,
    )
    if completed:
        coordinator.claim_task(
            task_ref=SOURCE_TASK_REF,
            worker_id="source-worker",
            as_of=AS_OF,
        )
        coordinator.complete_task(
            task_ref=SOURCE_TASK_REF,
            worker_id="source-worker",
            result={"status": "observed", "summary": "source work completed"},
            evidence_refs=SOURCE_EVIDENCE,
            trace_id=TRACE_ID,
            as_of=AS_OF,
        )
    coordinator.fork_thread(
        session_ref=SESSION_REF,
        thread_ref=TARGET_THREAD_REF,
        title="independent review",
        parent_thread_ref=SOURCE_THREAD_REF,
        parent_task_ref=SOURCE_TASK_REF,
        created_at=AS_OF,
    )
    return coordinator


def _create_handoff(coordinator: TeamAgentCoordinator):
    return coordinator.handoff_task(
        session_ref=SESSION_REF,
        source_task_ref=SOURCE_TASK_REF,
        source_thread_ref=SOURCE_THREAD_REF,
        target_thread_ref=TARGET_THREAD_REF,
        target_role=TARGET_ROLE,
        input_evidence_refs=HANDOFF_EVIDENCE,
        acceptance_contract=ACCEPTANCE_CONTRACT,
        trace_id=TRACE_ID,
        scope=SCOPE,
        created_at=AS_OF,
    )


def _submit_exact_child(
    coordinator: TeamAgentCoordinator,
    *,
    task_ref: str = CHILD_TASK_REF,
):
    handoff = coordinator.handoffs(session_ref=SESSION_REF)[0]
    return coordinator.submit_task(
        session_ref=SESSION_REF,
        task_ref=task_ref,
        thread_ref=TARGET_THREAD_REF,
        agent_id="review-agent",
        role=TARGET_ROLE,
        objective="review the source observation against its contract",
        idempotency_key=f"{task_ref}-v1",
        evidence_required=True,
        evidence_refs=HANDOFF_EVIDENCE,
        acceptance_contract=ACCEPTANCE_CONTRACT,
        trace_id=TRACE_ID,
        parent_task_ref=SOURCE_TASK_REF,
        handoff_ref=handoff.handoff_ref,
        created_at=AS_OF,
    )


def _assert_complete_lineage(coordinator: TeamAgentCoordinator) -> None:
    handoff = coordinator.handoffs(session_ref=SESSION_REF)[0]
    source = coordinator.task(SOURCE_TASK_REF)
    child = coordinator.task(CHILD_TASK_REF)
    snapshot = coordinator.snapshot(session_ref=SESSION_REF)
    threads = {item["thread_ref"]: item for item in snapshot["threads"]}

    assert source.state is TaskState.COMPLETED
    assert source.handoff_ref == handoff.handoff_ref
    assert handoff.input_evidence_refs == HANDOFF_EVIDENCE
    assert handoff.trace_id == source.trace_id == child.trace_id == TRACE_ID
    target_thread = threads[TARGET_THREAD_REF]
    assert target_thread["parent_thread_ref"] == SOURCE_THREAD_REF
    assert target_thread["parent_task_ref"] == SOURCE_TASK_REF
    assert target_thread["handoff_ref"] == handoff.handoff_ref
    assert target_thread["target_role"] == TARGET_ROLE
    assert child.thread_ref == handoff.target_thread_ref
    assert child.role == handoff.target_role
    assert child.parent_task_ref == handoff.source_task_ref
    assert child.handoff_ref == handoff.handoff_ref
    assert child.acceptance_contract == handoff.acceptance_contract
    assert child.evidence_refs == handoff.input_evidence_refs


def _rehash_checkpoint(checkpoint: dict) -> None:
    checkpoint.pop("checkpoint_sha256", None)
    checkpoint["checkpoint_sha256"] = hashlib.sha256(
        json.dumps(
            checkpoint,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def test_handoff_requires_completed_source_task() -> None:
    coordinator = _coordinator_with_source(completed=False)

    with pytest.raises(OrchestrationError, match="(?i)source.*completed"):
        _create_handoff(coordinator)


def test_handoff_evidence_must_be_owned_by_completed_source() -> None:
    coordinator = _coordinator_with_source()

    with pytest.raises(OrchestrationError, match="(?i)(source.*evidence|evidence.*source)"):
        coordinator.handoff_task(
            session_ref=SESSION_REF,
            source_task_ref=SOURCE_TASK_REF,
            source_thread_ref=SOURCE_THREAD_REF,
            target_thread_ref=TARGET_THREAD_REF,
            target_role=TARGET_ROLE,
            input_evidence_refs=("evidence-not-on-source",),
            acceptance_contract=ACCEPTANCE_CONTRACT,
            trace_id=TRACE_ID,
            scope=SCOPE,
            created_at=AS_OF,
        )


def test_handoff_trace_must_equal_completed_source_trace() -> None:
    coordinator = _coordinator_with_source()

    with pytest.raises(OrchestrationError, match="(?i)(source.*trace|trace.*source)"):
        coordinator.handoff_task(
            session_ref=SESSION_REF,
            source_task_ref=SOURCE_TASK_REF,
            source_thread_ref=SOURCE_THREAD_REF,
            target_thread_ref=TARGET_THREAD_REF,
            target_role=TARGET_ROLE,
            input_evidence_refs=HANDOFF_EVIDENCE,
            acceptance_contract=ACCEPTANCE_CONTRACT,
            trace_id="trace-divergent",
            scope=SCOPE,
            created_at=AS_OF,
        )


def test_handoff_binds_target_thread_to_reference_and_role() -> None:
    coordinator = _coordinator_with_source()
    handoff = _create_handoff(coordinator)
    target = next(
        item
        for item in coordinator.snapshot(session_ref=SESSION_REF)["threads"]
        if item["thread_ref"] == TARGET_THREAD_REF
    )

    assert target["handoff_ref"] == handoff.handoff_ref
    assert target["target_role"] == TARGET_ROLE


@pytest.mark.parametrize(
    ("override", "case_id"),
    [
        ({"thread_ref": SOURCE_THREAD_REF}, "target-thread"),
        ({"role": "different-role"}, "target-role"),
        ({"parent_task_ref": None}, "parent-task"),
        ({"acceptance_contract": {"deliverable": "different"}}, "acceptance-contract"),
        ({"evidence_refs": ("evidence-source-b",)}, "handoff-evidence"),
        ({"trace_id": "trace-divergent"}, "trace"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_child_task_must_match_every_handoff_lineage_field(
    override: dict,
    case_id: str,
) -> None:
    coordinator = _coordinator_with_source()
    handoff = _create_handoff(coordinator)
    request = {
        "session_ref": SESSION_REF,
        "task_ref": f"child-invalid-{case_id}",
        "thread_ref": TARGET_THREAD_REF,
        "agent_id": "review-agent",
        "role": TARGET_ROLE,
        "objective": "attempt a mismatched handoff child",
        "idempotency_key": f"child-invalid-{case_id}-v1",
        "evidence_required": True,
        "evidence_refs": HANDOFF_EVIDENCE,
        "acceptance_contract": ACCEPTANCE_CONTRACT,
        "trace_id": TRACE_ID,
        "parent_task_ref": SOURCE_TASK_REF,
        "handoff_ref": handoff.handoff_ref,
        "created_at": AS_OF,
    }
    request.update(override)

    with pytest.raises(OrchestrationError, match="(?i)(handoff|lineage)"):
        coordinator.submit_task(**request)


def test_exact_handoff_child_is_accepted() -> None:
    coordinator = _coordinator_with_source()
    handoff = _create_handoff(coordinator)

    child = _submit_exact_child(coordinator)

    assert child.thread_ref == handoff.target_thread_ref
    assert child.role == handoff.target_role
    assert child.parent_task_ref == handoff.source_task_ref
    assert child.acceptance_contract == handoff.acceptance_contract
    assert child.evidence_refs == handoff.input_evidence_refs
    assert child.trace_id == handoff.trace_id


def test_checkpoint_restore_preserves_complete_handoff_lineage() -> None:
    coordinator = _coordinator_with_source()
    _create_handoff(coordinator)
    _submit_exact_child(coordinator)

    restored = TeamAgentCoordinator.restore(
        coordinator.checkpoint(session_ref=SESSION_REF),
        scope=SCOPE,
    )

    _assert_complete_lineage(restored)


def test_checkpoint_rejects_rehashed_handoff_lineage_tampering() -> None:
    coordinator = _coordinator_with_source()
    _create_handoff(coordinator)
    _submit_exact_child(coordinator)
    checkpoint = coordinator.checkpoint(session_ref=SESSION_REF)
    checkpoint["handoffs"][0]["trace_id"] = "trace-tampered"
    _rehash_checkpoint(checkpoint)

    with pytest.raises(
        OrchestrationError,
        match="(?i)(handoff|lineage|trace|projection)",
    ):
        TeamAgentCoordinator.restore(checkpoint, scope=SCOPE)


def test_event_merge_reconstructs_complete_handoff_lineage() -> None:
    producer = _coordinator_with_source()
    _create_handoff(producer)
    _submit_exact_child(producer)

    receiver = TeamAgentCoordinator()
    merged = receiver.merge_events(
        producer.events(session_ref=SESSION_REF),
        expected_scope=SCOPE,
    )

    assert merged.status == "merged", merged.conflicts
    _assert_complete_lineage(receiver)
