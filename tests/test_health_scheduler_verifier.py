from copy import deepcopy
from datetime import UTC, datetime, timedelta

from apps.control_plane.health_scheduler_verifier import HealthSchedulerDeploymentVerifier

NOW = datetime(2026, 7, 28, 15, 15, tzinfo=UTC)


def _task_audit() -> dict:
    return {
        "schema_version": "kjds-evidence-health-task-v1",
        "generated_at": (NOW - timedelta(minutes=1)).isoformat(),
        "mode": "audit",
        "task_name": "KJDS-Evidence-Integrity-Health",
        "task_path": "\\",
        "interval_minutes": 15,
        "execution_limit_minutes": 5,
        "configuration_source": "project_env_file",
        "control_plane_only": True,
        "command_contains_secrets": False,
        "required_consecutive_successes": 3,
        "mutation_performed": False,
        "status": "accepted",
        "audit": {
            "task_found": True,
            "enabled": True,
            "action_valid": True,
            "arguments_secret_free": True,
            "working_directory_valid": True,
            "trigger_valid": True,
            "execution_limit_valid": True,
            "overlap_policy_valid": True,
            "last_result": 0,
            "last_run_time": (NOW - timedelta(minutes=2)).isoformat(),
            "history": {
                "available": True,
                "matching_events": 3,
                "consecutive_successes": 3,
                "latest_results": [
                    {"completed_at": NOW.isoformat(), "result_code": 0}
                ],
                "error": None,
            },
            "definition_valid": True,
            "accepted": True,
            "error": None,
        },
    }


def _health() -> dict:
    return {
        "generated_at": (NOW - timedelta(seconds=30)).isoformat(),
        "snapshot": {"ok": True},
        "control_plane": {"ok": True, "status": 200},
        "operations_readiness": {"ok": True, "status": 200},
        "evidence_integrity": {"ok": True, "completed": True, "invalid": 0},
        "agent_gate_observation": {
            "ok": True,
            "database_revision": "20260728_0070",
            "operating_subject_actor_id": "r0-requester",
        },
    }


def test_exact_external_scheduler_and_health_pass() -> None:
    result = HealthSchedulerDeploymentVerifier().evaluate(
        task_audit=_task_audit(),
        health_preflight=_health(),
        observed_at=NOW,
    )
    assert result["state"] == "passed"
    assert result["blockers"] == []
    assert result["external_write_allowed"] is False
    assert result["model_self_certification_allowed"] is False


def test_missing_real_task_and_credentials_remain_blocked() -> None:
    audit = _task_audit()
    audit["status"] = "not_accepted"
    audit["audit"].update(
        {
            "task_found": False,
            "enabled": False,
            "action_valid": False,
            "arguments_secret_free": False,
            "working_directory_valid": False,
            "trigger_valid": False,
            "execution_limit_valid": False,
            "overlap_policy_valid": False,
            "last_result": None,
            "definition_valid": False,
            "accepted": False,
        }
    )
    audit["audit"]["history"].update(
        {
            "available": False,
            "matching_events": 0,
            "consecutive_successes": 0,
            "latest_results": [],
        }
    )
    health = _health()
    health["operations_readiness"] = {"ok": False, "error": "missing"}
    health["evidence_integrity"] = {"ok": False, "error": "missing"}
    health["agent_gate_observation"] = {"ok": False, "error": "missing"}

    result = HealthSchedulerDeploymentVerifier().evaluate(
        task_audit=audit,
        health_preflight=health,
        observed_at=NOW,
    )
    assert result["state"] == "blocked"
    assert result["blockers"] == [
        "scheduled_task_missing",
        "health_operations_readiness_not_ready",
        "health_evidence_integrity_not_ready",
        "health_agent_gate_observation_not_ready",
    ]
    assert "explicit Install mode" in result["next_action"]


def test_acceptance_claim_cannot_override_invalid_definition() -> None:
    audit = _task_audit()
    audit["audit"]["arguments_secret_free"] = False
    result = HealthSchedulerDeploymentVerifier().evaluate(
        task_audit=audit,
        health_preflight=_health(),
        observed_at=NOW,
    )
    assert result["state"] == "failed"
    assert "contract:task_audit_definition_claim_drift" in result["blockers"]
    assert "contract:task_audit_acceptance_claim_drift" in result["blockers"]


def test_insufficient_completion_history_is_blocked() -> None:
    audit = _task_audit()
    audit["status"] = "not_accepted"
    audit["audit"]["accepted"] = False
    audit["audit"]["history"]["consecutive_successes"] = 2
    result = HealthSchedulerDeploymentVerifier().evaluate(
        task_audit=audit,
        health_preflight=_health(),
        observed_at=NOW,
    )
    assert result["state"] == "blocked"
    assert result["blockers"] == [
        "scheduled_task_success_history_incomplete"
    ]


def test_stale_external_results_are_blocked_and_hashes_are_deterministic() -> None:
    audit = _task_audit()
    health = _health()
    first = HealthSchedulerDeploymentVerifier().evaluate(
        task_audit=audit,
        health_preflight=health,
        observed_at=NOW,
    )
    replay = HealthSchedulerDeploymentVerifier().evaluate(
        task_audit=deepcopy(audit),
        health_preflight=deepcopy(health),
        observed_at=NOW,
    )
    assert first == replay

    stale_at = NOW + timedelta(minutes=30)
    stale = HealthSchedulerDeploymentVerifier().evaluate(
        task_audit=audit,
        health_preflight=health,
        observed_at=stale_at,
    )
    assert stale["state"] == "blocked"
    assert "scheduled_task_audit_stale" in stale["blockers"]
    assert "health_preflight_stale" in stale["blockers"]
    assert stale["input_sha256"] != first["input_sha256"]
