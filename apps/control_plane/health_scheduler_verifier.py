from __future__ import annotations
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class HealthSchedulerDeploymentVerifier:
    """Verify the real external health scheduler without installing or owning it."""

    CONTRACT_ID = "kjds-health-scheduler-deployment-verifier-v1"
    AUDIT_CONTRACT_ID = "kjds-evidence-health-task-v1"
    TASK_NAME = "KJDS-Evidence-Integrity-Health"
    TASK_PATH = "\\"
    INTERVAL_MINUTES = 15
    EXECUTION_LIMIT_MINUTES = 5
    REQUIRED_CONSECUTIVE_SUCCESSES = 3
    MAX_SOURCE_AGE = timedelta(minutes=20)
    MAX_FUTURE_SKEW = timedelta(minutes=2)

    _AUDIT_FLAGS = (
        "enabled",
        "action_valid",
        "arguments_secret_free",
        "working_directory_valid",
        "trigger_valid",
        "execution_limit_valid",
        "overlap_policy_valid",
    )
    _HEALTH_SECTIONS = (
        "snapshot",
        "control_plane",
        "operations_readiness",
        "evidence_integrity",
        "agent_gate_observation",
    )

    def evaluate(
        self,
        *,
        task_audit: dict[str, Any],
        health_preflight: dict[str, Any],
        observed_at: datetime,
    ) -> dict[str, Any]:
        cutoff = self._timestamp(observed_at, "observed_at")
        errors = self._contract_errors(
            task_audit=task_audit,
            health_preflight=health_preflight,
            observed_at=cutoff,
        )
        semantic_input = {
            "audit": task_audit,
            "health": health_preflight,
            "observed_at": cutoff.isoformat(),
        }
        input_sha256 = _sha(semantic_input)
        if errors:
            return self._result(
                state="failed",
                summary=(
                    "health scheduler external observation contract failed: "
                    + ", ".join(errors)
                ),
                blockers=[f"contract:{error}" for error in errors],
                next_action=(
                    "repair the external audit contract and rerun the bounded "
                    "read-only verifier"
                ),
                input_sha256=input_sha256,
                observed_at=cutoff,
            )

        audit = task_audit["audit"]
        history = audit["history"]
        blockers: list[str] = []
        if not audit["task_found"]:
            blockers.append("scheduled_task_missing")
        else:
            blockers.extend(
                f"scheduled_task_{name}_invalid"
                for name in self._AUDIT_FLAGS
                if not audit[name]
            )
            if audit["last_result"] != 0:
                blockers.append("scheduled_task_last_result_nonzero")
            if not history["available"]:
                blockers.append("scheduled_task_history_unavailable")
            if (
                int(history["consecutive_successes"])
                < self.REQUIRED_CONSECUTIVE_SUCCESSES
            ):
                blockers.append("scheduled_task_success_history_incomplete")

        for section in self._HEALTH_SECTIONS:
            if not health_preflight[section]["ok"]:
                blockers.append(f"health_{section}_not_ready")

        audit_age = cutoff - self._timestamp(
            task_audit["generated_at"], "task_audit.generated_at"
        )
        health_age = cutoff - self._timestamp(
            health_preflight["generated_at"],
            "health_preflight.generated_at",
        )
        if audit_age > self.MAX_SOURCE_AGE:
            blockers.append("scheduled_task_audit_stale")
        if health_age > self.MAX_SOURCE_AGE:
            blockers.append("health_preflight_stale")

        state = "passed" if not blockers else "blocked"
        if state == "passed":
            summary = (
                "external Windows Task definition is exact, the current health "
                "preflight is green, and three consecutive completions returned 0"
            )
            next_action = (
                "continue the 15-minute external observation cadence and retain "
                "immutable completion history"
            )
        else:
            summary = (
                "external health scheduler deployment remains blocked: "
                + ", ".join(blockers)
            )
            if "scheduled_task_missing" in blockers:
                next_action = (
                    "provide scheduler-visible project configuration, run the "
                    "explicit Install mode, then observe three consecutive "
                    "successful completions"
                )
            elif any(
                blocker.startswith("health_") and blocker.endswith("_not_ready")
                for blocker in blockers
            ):
                next_action = (
                    "configure dedicated scheduler-visible operator and monitor "
                    "credentials without borrowing another runtime identity, then "
                    "rerun the health preflight"
                )
            elif "scheduled_task_success_history_incomplete" in blockers:
                next_action = (
                    "allow the exact installed task to complete successfully three "
                    "consecutive times, then rerun Audit"
                )
            else:
                next_action = (
                    "repair the exact secret-free Task definition through the "
                    "explicit installer and rerun the read-only audit"
                )
        return self._result(
            state=state,
            summary=summary,
            blockers=blockers,
            next_action=next_action,
            input_sha256=input_sha256,
            observed_at=cutoff,
        )

    def _contract_errors(
        self,
        *,
        task_audit: dict[str, Any],
        health_preflight: dict[str, Any],
        observed_at: datetime,
    ) -> list[str]:
        errors: list[str] = []
        if not isinstance(task_audit, dict):
            return ["task_audit_not_object"]
        if not isinstance(health_preflight, dict):
            return ["health_preflight_not_object"]
        expected_audit = {
            "schema_version": self.AUDIT_CONTRACT_ID,
            "mode": "audit",
            "task_name": self.TASK_NAME,
            "task_path": self.TASK_PATH,
            "interval_minutes": self.INTERVAL_MINUTES,
            "execution_limit_minutes": self.EXECUTION_LIMIT_MINUTES,
            "configuration_source": "project_env_file",
            "control_plane_only": True,
            "command_contains_secrets": False,
            "required_consecutive_successes": (
                self.REQUIRED_CONSECUTIVE_SUCCESSES
            ),
            "mutation_performed": False,
        }
        for key, expected in expected_audit.items():
            if task_audit.get(key) != expected:
                errors.append(f"task_audit_{key}_drift")
        audit = task_audit.get("audit")
        if not isinstance(audit, dict):
            errors.append("task_audit_result_missing")
        else:
            required_audit = {
                "task_found",
                *self._AUDIT_FLAGS,
                "last_result",
                "history",
                "definition_valid",
                "accepted",
            }
            missing = sorted(required_audit - set(audit))
            errors.extend(f"task_audit_{key}_missing" for key in missing)
            history = audit.get("history")
            if not isinstance(history, dict):
                errors.append("task_audit_history_missing")
            elif not {
                "available",
                "consecutive_successes",
                "latest_results",
            } <= set(history):
                errors.append("task_audit_history_contract_drift")
            if not missing and isinstance(history, dict):
                definition_valid = bool(audit["task_found"]) and all(
                    audit[name] is True for name in self._AUDIT_FLAGS
                )
                accepted = (
                    definition_valid
                    and audit["last_result"] == 0
                    and history.get("available") is True
                    and self._nonnegative_integer(
                        history.get("consecutive_successes")
                    )
                    >= self.REQUIRED_CONSECUTIVE_SUCCESSES
                )
                if audit["definition_valid"] is not definition_valid:
                    errors.append("task_audit_definition_claim_drift")
                if audit["accepted"] is not accepted:
                    errors.append("task_audit_acceptance_claim_drift")
                expected_status = "accepted" if accepted else "not_accepted"
                if task_audit.get("status") != expected_status:
                    errors.append("task_audit_status_claim_drift")

        for section in self._HEALTH_SECTIONS:
            payload = health_preflight.get(section)
            if not isinstance(payload, dict) or not isinstance(
                payload.get("ok"), bool
            ):
                errors.append(f"health_{section}_contract_drift")
        for source, field in (
            (task_audit, "task_audit.generated_at"),
            (health_preflight, "health_preflight.generated_at"),
        ):
            key = "generated_at"
            try:
                timestamp = self._timestamp(source.get(key), field)
            except (TypeError, ValueError):
                errors.append(f"{field}_invalid")
                continue
            if timestamp - observed_at > self.MAX_FUTURE_SKEW:
                errors.append(f"{field}_future")
        return errors

    @staticmethod
    def _nonnegative_integer(value: Any) -> int:
        if isinstance(value, bool):
            return -1
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return -1
        return parsed if parsed >= 0 else -1

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise TypeError(f"{field} must be an ISO-8601 timestamp")
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include timezone")
        return parsed.astimezone(UTC)

    def _result(
        self,
        *,
        state: str,
        summary: str,
        blockers: list[str],
        next_action: str,
        input_sha256: str,
        observed_at: datetime,
    ) -> dict[str, Any]:
        result = {
            "contract_id": self.CONTRACT_ID,
            "state": state,
            "summary": summary,
            "blockers": blockers,
            "owner": "engineering+operations",
            "sla_seconds": 86400,
            "next_action": next_action,
            "input_sha256": input_sha256,
            "observed_at": observed_at.isoformat(),
            "external_write_allowed": False,
            "model_self_certification_allowed": False,
        }
        result["result_sha256"] = _sha(result)
        return result
