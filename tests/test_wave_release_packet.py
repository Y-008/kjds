from datetime import UTC, datetime

from apps.control_plane.wave_release_packet import (
    build_release_packet,
    derive_claim_level,
    is_definition_of_done,
    is_definition_of_ready,
    summarize_delivery_lanes,
    validate_definition_of_ready,
    validate_release_packet,
)


def brief():
    return {
        "task_id": "WP-001",
        "parent_id": "P0",
        "scope": {"tenant": "t1", "entity": "e1", "store": "s1"},
        "owner": "agent-a",
        "reviewer": "reviewer",
        "objective": "build contract",
        "business_context": "control plane",
        "allowed_scope": ["apps/control_plane"],
        "prohibited_scope": ["Ozon external write"],
        "dependencies": [],
        "exact_write_set": ["apps/control_plane/project_task_contracts.py"],
        "input_snapshot": "snapshot-1",
        "exact_files_or_domain": ["apps/control_plane/project_task_contracts.py"],
        "expected_outputs": ["code", "tests"],
        "acceptance_tests": ["pytest"],
        "budget": {"limit": "1"},
        "lease": "lease-1",
        "deadline": datetime(2030, 1, 1, tzinfo=UTC).isoformat(),
        "risk_tier": "R1",
        "rollback_ref": "git:HEAD",
        "reporting_format": "TaskResult",
    }


def packet(level="engineering"):
    return {
        "wave_id": "W-001",
        "goal": "contract",
        "included_tasks": ["WP-001"],
        "excluded_tasks": [],
        "dependency_frontier": [],
        "claim_level": level,
        "exact_head": "a" * 40,
        "migration_head": "migration-1",
        "changed_paths": ["apps/control_plane/project_task_contracts.py"],
        "api_schema_diff": [],
        "test_receipts": ["test-1"],
        "runtime_receipt": None,
        "business_evidence": None,
        "economic_impact": None,
        "open_blockers": [],
        "invalidated_nodes": [],
        "rollback_ref": "git:HEAD",
        "next_wave": [],
    }


def test_definition_of_ready_rejects_broad_write_and_accepts_valid_brief():
    assert is_definition_of_ready(brief())
    invalid = {**brief(), "exact_write_set": ["*"]}
    report = validate_definition_of_ready(invalid)
    assert report.valid is False
    assert any(issue.code == "broad_write_set" for issue in report.errors)


def test_release_packet_hash_and_claim_projection_are_deterministic():
    packet_value = build_release_packet(packet())
    assert validate_release_packet(packet_value).valid
    assert packet_value.packet_sha256
    assert derive_claim_level(packet_value) == "engineering"
    assert summarize_delivery_lanes((packet_value,))["engineering"]["ready"]
    assert summarize_delivery_lanes((packet_value,))["runtime"]["ready"] is False


def test_definition_of_done_requires_current_receipts_and_rejects_unknown_result():
    done = {
        "task_id": "WP-001",
        "status": "RUNTIME_PROVEN",
        "changed_files": ["apps/control_plane/project_task_contracts.py"],
        "test_receipts": ["test-1"],
        "evidence_refs": ["evidence-1"],
        "rollback_ref": "git:HEAD",
        "exact_head": "a" * 40,
        "migration_head": "migration-1",
    }
    assert is_definition_of_done(done)
    assert is_definition_of_done({**done, "status": "DONE"}) is False
