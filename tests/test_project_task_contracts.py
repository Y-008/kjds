from decimal import Decimal

import pytest

from apps.control_plane.project_task_contracts import (
    ClaimLevel,
    HierarchyError,
    ProjectTaskContractError,
    TaskBrief,
    TaskResult,
    TaskStatus,
    WIPLimitError,
    WorkItem,
    build_project_snapshot,
    build_release_packet,
    canonical_hash,
    critical_path,
    invalidate_downstream,
    minimum_blocker_set,
    ready_frontier,
    validate_task_brief,
    validate_task_result,
    validate_wip,
    validate_work_breakdown,
)


def _wbs() -> tuple[WorkItem, ...]:
    return (
        WorkItem("i-1", "initiative", "AI control plane", owner="product", reviewer="risk"),
        WorkItem("p-1", "program", "trusted runtime", "i-1", owner="platform", reviewer="risk"),
        WorkItem("e-1", "epic", "task contracts", "p-1", owner="platform", reviewer="qa"),
        WorkItem(
            "s-1", "slice", "snapshot contract", "e-1", owner="platform", reviewer="qa",
            exact_write_set=("shared_contract:task",), acceptance_tests=("contract",),
        ),
        WorkItem(
            "t-1", "task", "define hash", "s-1", owner="backend", reviewer="qa",
            exact_write_set=("apps/control_plane/project_task_contracts.py",),
            acceptance_tests=("hash",), rollback_ref="git:previous",
        ),
    )


def test_five_level_breakdown_and_frontier_are_deterministic():
    items = _wbs()
    report = validate_work_breakdown(items)
    assert report.valid is True
    assert ready_frontier(items) == ("t-1",)
    promoted = tuple(
        WorkItem(**{**item.to_dict(), "status": TaskStatus.RELEASED.value})
        if item.node_id == "i-1" else item for item in items
    )
    assert ready_frontier(promoted) == ("t-1",)
    assert report.snapshot_sha256 == validate_work_breakdown(items).snapshot_sha256


def test_invalid_parent_and_cycle_fail_closed():
    items = list(_wbs())
    items[1] = WorkItem("p-1", "epic", "wrong", "i-1", owner="a", reviewer="b")
    report = validate_work_breakdown(items)
    assert report.valid is False
    assert any("parent must be program" in error for error in report.errors)
    with pytest.raises(HierarchyError):
        validate_work_breakdown(items, raise_on_error=True)


def test_task_brief_and_result_use_fixed_envelopes_and_stable_hashes():
    brief = TaskBrief(
        task_id="t-1", objective="define schema", allowed_scope=("contract",),
        prohibited_scope=("external write",), exact_files_or_domain=("shared_contract:task",),
        acceptance_tests=("schema",), input_snapshot={"snapshot_id": "snap-1"},
        scope={"tenant": "t1"},
        owner="backend", reviewer="qa",
    )
    same = TaskBrief.from_mapping(brief.to_dict())
    assert brief.brief_sha256 == same.brief_sha256
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})

    result = TaskResult(
        task_id="t-1", status=TaskStatus.CONTRACT_VERIFIED,
        changed_files=("apps/control_plane/project_task_contracts.py",),
        test_receipts=("test:1",), proof_refs=("proof:1",), evidence_refs=("evidence:1",),
        rollback_ref="git:previous", claim_level=ClaimLevel.ENGINEERING,
    )
    assert result.result_sha256 == TaskResult.from_mapping(result.to_dict()).result_sha256
    assert result.to_dict()["external_write_allowed"] is False
    assert validate_task_brief(brief).valid
    assert validate_task_result(result).valid


def test_result_rejects_authority_and_secret_fields():
    with pytest.raises(ProjectTaskContractError, match="authority"):
        TaskResult.from_mapping({"task_id": "t", "status": "BLOCKED", "permit": "p"})
    with pytest.raises(ProjectTaskContractError, match="sensitive"):
        TaskResult.from_mapping({"task_id": "t", "status": "BLOCKED", "blockers": [{"api_key": "x"}]})
    with pytest.raises(ProjectTaskContractError, match="external writes"):
        TaskResult.from_mapping({"task_id": "t", "status": "BLOCKED", "external_write_allowed": True})


def test_wip_policy_blocks_same_domain_and_reports_counts():
    first = TaskBrief("a", "one", exact_files_or_domain=("migration",))
    second = TaskBrief("b", "two", exact_files_or_domain=("migration",))
    report = validate_wip((first, second))
    assert report.valid is False
    assert report.counts["migration"] == 2
    assert any("WIP limit" in violation for violation in report.violations)
    with pytest.raises(WIPLimitError):
        validate_wip((first, second), raise_on_error=True)


def test_wip_counts_one_task_once_even_when_it_owns_multiple_files():
    task = TaskBrief("a", "one", exact_files_or_domain=("core_api:orders/a.py", "core_api:orders/b.py"))
    report = validate_wip((task,))
    assert report.valid is True
    assert report.counts["core_api:orders"] == 1


def test_critical_path_invalidation_and_blocker_projection():
    items = list(_wbs())
    items[-1] = WorkItem(**{**items[-1].to_dict(), "status": "IN_PROGRESS", "business_value": Decimal("3")})
    assert critical_path(items) == ("t-1",)
    invalidated = invalidate_downstream(items, ("s-1",))
    assert {item.node_id for item in invalidated if item.status == "INVALIDATED"} == {"s-1", "t-1"}
    blockers = minimum_blocker_set(invalidated)
    assert {item["node_id"] for item in blockers} == {"s-1", "t-1"}


def test_release_packet_is_immutable_evidence_and_never_authorizes_writes():
    kwargs = {
        "wave_id": "wave-1", "goal": "task contract wave", "included_tasks": ("t-1",),
        "exact_head": "a" * 40, "changed_paths": ("apps/control_plane/project_task_contracts.py",),
        "test_receipts": ("test:task-contracts",), "rollback_ref": "git:previous",
    }
    packet = build_release_packet(**kwargs)
    again = build_release_packet(**kwargs)
    assert packet.packet_sha256 == again.packet_sha256
    assert packet.to_dict()["external_write_allowed"] is False
    with pytest.raises(ProjectTaskContractError, match="external writes"):
        type(packet)(wave_id=packet.wave_id, goal=packet.goal, included_tasks=packet.included_tasks,
                      exact_head=packet.exact_head, external_write_allowed=True)
    with pytest.raises(ProjectTaskContractError, match="full 40 or 64"):
        build_release_packet(**{**kwargs, "exact_head": "short"})


def test_project_snapshot_is_read_only_and_content_bound():
    first = build_project_snapshot(_wbs())
    second = build_project_snapshot(_wbs())
    assert first == second
    supplied = first.pop("snapshot_sha256")
    assert supplied == canonical_hash(first)
    first["nodes"][0]["title"] = "mutated"
    assert build_project_snapshot(_wbs())["nodes"][0]["title"] != "mutated"
