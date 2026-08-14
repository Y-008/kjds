from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .security import Principal


class GovernanceScopeAuthority:
    """Project governance facts through Evidence scope and exact parent links."""

    CONTRACT_ID = "kjds-governance-scope-authority-v1"

    def __init__(
        self,
        *,
        governance,
        execution_plans,
        limited_executor,
        post_execution,
        scoped_evidence,
    ) -> None:
        self.governance = governance
        self.execution_plans = execution_plans
        self.limited_executor = limited_executor
        self.post_execution = post_execution
        self.scoped_evidence = scoped_evidence

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        if (
            entity_scope.get("status") != "ready"
            or not entity_scope.get("entity_ref")
        ):
            reason = entity_scope.get(
                "reason",
                "entity_scope_authority_missing",
            )
            return self._result(
                status="no_data",
                as_of=as_of,
                reviews=[],
                plans=[],
                commands=[],
                windows=[],
                excluded={},
                source_gaps=[f"governance_{reason}"],
                blockers=[],
            )

        authorities, unavailable = self._load()
        scope = {
            "principal": principal,
            "entity_scope": entity_scope,
            "store_ref": store_ref,
            "as_of": as_of.astimezone(UTC),
        }
        excluded: dict[str, list[str]] = {}
        reviews = self._scope_evidence_records(
            authorities["reviews"],
            kind="gate_review",
            scope=scope,
            excluded=excluded,
        )
        plans = self._scope_evidence_records(
            authorities["plans"],
            kind="execution_plan",
            scope=scope,
            excluded=excluded,
        )
        plan_by_id = {item["id"]: item for item in plans}
        commands = self._scope_commands(
            authorities["commands"],
            plans=plan_by_id,
            scope=scope,
            excluded=excluded,
        )
        command_by_id = {item["id"]: item for item in commands}
        windows = self._scope_windows(
            authorities["windows"],
            plans=plan_by_id,
            commands=command_by_id,
            scope=scope,
            excluded=excluded,
        )

        source_gaps = sorted(
            {
                *unavailable,
                *(
                    f"{kind}:{reason}"
                    for kind, reasons in excluded.items()
                    for reason in reasons
                ),
            }
        )
        blockers = self._blockers(
            unavailable=unavailable,
            excluded=excluded,
        )
        ready_count = sum(
            len(items) for items in (reviews, plans, commands, windows)
        )
        hard_failure = bool(unavailable) or any(
            self._hard_reason(reason)
            for reasons in excluded.values()
            for reason in reasons
        )
        status = (
            "ready"
            if not source_gaps
            else "partial"
            if ready_count
            else "blocked"
            if hard_failure
            else "no_data"
        )
        return self._result(
            status=status,
            as_of=as_of,
            reviews=reviews,
            plans=plans,
            commands=commands,
            windows=windows,
            excluded=excluded,
            source_gaps=source_gaps,
            blockers=blockers,
        )

    def _load(self) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        result: dict[str, list[dict[str, Any]]] = {
            "reviews": [],
            "plans": [],
            "commands": [],
            "windows": [],
        }
        unavailable: list[str] = []
        loaders = {
            "reviews": self.governance.list,
            "plans": self.execution_plans.list,
            "commands": self.limited_executor.list,
            "windows": self.post_execution.list_windows,
        }
        for kind, loader in loaders.items():
            try:
                values = loader()
                if not isinstance(values, list):
                    raise ValueError("Authority list must be a list")
                result[kind] = [
                    item for item in values if isinstance(item, dict)
                ]
                if len(result[kind]) != len(values):
                    raise ValueError("Authority records must be objects")
            except (KeyError, RuntimeError, TypeError, ValueError):
                unavailable.append(f"{kind}_authority_unavailable")
        return result, sorted(unavailable)

    def _scope_evidence_records(
        self,
        values: list[dict[str, Any]],
        *,
        kind: str,
        scope: dict[str, Any],
        excluded: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        ready: list[dict[str, Any]] = []
        for value in sorted(values, key=self._id):
            reasons = self._direct_scope_reasons(
                value,
                store_ref=scope["store_ref"],
            )
            if not self._id(value):
                reasons.append("record_id_missing")
            evidence_ids = self._evidence_ids(value.get("evidence_ids"))
            if not evidence_ids:
                reasons.append("evidence_scope_binding_missing")
            elif not reasons:
                projection = self.scoped_evidence.project(
                    evidence_ids=evidence_ids,
                    principal=scope["principal"],
                    entity_scope=scope["entity_scope"],
                    store_ref=scope["store_ref"],
                    as_of=scope["as_of"],
                )
                if projection["status"] != "ready":
                    reasons.extend(
                        projection["source_gaps"]
                        or [f"evidence_scope_{projection['status']}"]
                    )
            if reasons:
                self._exclude(excluded, kind, reasons)
            else:
                ready.append(self._normalize(kind, value))
        return ready

    def _scope_commands(
        self,
        values: list[dict[str, Any]],
        *,
        plans: dict[str, dict[str, Any]],
        scope: dict[str, Any],
        excluded: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        ready: list[dict[str, Any]] = []
        for value in sorted(values, key=self._id):
            reasons = self._direct_scope_reasons(
                value,
                store_ref=scope["store_ref"],
            )
            if not self._id(value):
                reasons.append("record_id_missing")
            plan_id = self._text(value.get("plan_id"))
            if not plan_id or plan_id not in plans:
                reasons.append("parent_plan_not_scoped")
            receipt = value.get("receipt")
            if receipt is not None:
                if not isinstance(receipt, dict):
                    reasons.append("receipt_contract_invalid")
                else:
                    receipt_evidence = self._evidence_ids(
                        receipt.get("evidence_ids")
                    )
                    if not receipt_evidence:
                        reasons.append("receipt_evidence_scope_missing")
                    elif not reasons:
                        projection = self.scoped_evidence.project(
                            evidence_ids=receipt_evidence,
                            principal=scope["principal"],
                            entity_scope=scope["entity_scope"],
                            store_ref=scope["store_ref"],
                            as_of=scope["as_of"],
                        )
                        if projection["status"] != "ready":
                            reasons.extend(
                                projection["source_gaps"]
                                or [
                                    "receipt_evidence_scope_"
                                    f"{projection['status']}"
                                ]
                            )
            if reasons:
                self._exclude(excluded, "command", reasons)
            else:
                ready.append(self._normalize("command", value))
        return ready

    def _scope_windows(
        self,
        values: list[dict[str, Any]],
        *,
        plans: dict[str, dict[str, Any]],
        commands: dict[str, dict[str, Any]],
        scope: dict[str, Any],
        excluded: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        ready: list[dict[str, Any]] = []
        for value in sorted(values, key=self._id):
            reasons = self._direct_scope_reasons(
                value,
                store_ref=scope["store_ref"],
            )
            if not self._id(value):
                reasons.append("record_id_missing")
            plan_id = self._text(value.get("plan_id"))
            command_id = self._text(value.get("command_id"))
            command = commands.get(command_id)
            if not plan_id or plan_id not in plans:
                reasons.append("parent_plan_not_scoped")
            if command is None:
                reasons.append("parent_command_not_scoped")
            elif command.get("plan_id") != plan_id:
                reasons.append("parent_chain_mismatch")
            evidence_ids = self._evidence_ids(value.get("evidence_ids"))
            if evidence_ids and not reasons:
                projection = self.scoped_evidence.project(
                    evidence_ids=evidence_ids,
                    principal=scope["principal"],
                    entity_scope=scope["entity_scope"],
                    store_ref=scope["store_ref"],
                    as_of=scope["as_of"],
                )
                if projection["status"] != "ready":
                    reasons.extend(
                        projection["source_gaps"]
                        or [f"window_evidence_scope_{projection['status']}"]
                    )
            if reasons:
                self._exclude(excluded, "window", reasons)
            else:
                ready.append(self._normalize("window", value))
        return ready

    @classmethod
    def _result(
        cls,
        *,
        status: str,
        as_of: datetime,
        reviews: list[dict[str, Any]],
        plans: list[dict[str, Any]],
        commands: list[dict[str, Any]],
        windows: list[dict[str, Any]],
        excluded: dict[str, list[str]],
        source_gaps: list[str],
        blockers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        projection = {
            "reviews": reviews,
            "plans": plans,
            "commands": commands,
            "windows": windows,
        }
        counts = {kind: len(values) for kind, values in projection.items()}
        excluded_counts = {
            kind: len(reasons) for kind, reasons in sorted(excluded.items())
        }
        authority_projection = {
            "as_of": cls._iso(as_of),
            "record_sha256": {
                kind: cls._hash(values)
                for kind, values in projection.items()
            },
            "counts": counts,
            "excluded_counts": excluded_counts,
            "source_gaps": source_gaps,
        }
        return {
            "contract_id": cls.CONTRACT_ID,
            "status": status,
            "as_of": cls._iso(as_of),
            **projection,
            "counts": counts,
            "excluded_counts": excluded_counts,
            "source_gaps": source_gaps,
            "blockers": blockers,
            "authority_sha256": cls._hash(authority_projection),
        }

    @classmethod
    def _blockers(
        cls,
        *,
        unavailable: list[str],
        excluded: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        codes: set[str] = set()
        if unavailable:
            codes.add("governance_authority_unavailable")
        reasons = {
            reason for values in excluded.values() for reason in values
        }
        if any(cls._hard_reason(reason) for reason in reasons):
            codes.add("governance_scope_conflict")
        if reasons - {
            reason for reason in reasons if cls._hard_reason(reason)
        }:
            codes.add("governance_scope_binding_missing")
        return [
            {
                "code": code,
                "severity": "P0",
                "owner": "execution-governance",
                "sla": "before external approval",
                "next": (
                    "Bind the governance fact to exact scoped Evidence and "
                    "repair its immutable parent chain."
                ),
                "next_workspace": "/growth-command",
            }
            for code in sorted(codes)
        ]

    @staticmethod
    def _direct_scope_reasons(
        value: dict[str, Any],
        *,
        store_ref: str,
    ) -> list[str]:
        declared = value.get("store_ref")
        if declared is None:
            return []
        return [] if declared == store_ref else ["direct_store_scope_mismatch"]

    @staticmethod
    def _evidence_ids(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized = [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]
        if (
            len(normalized) != len(value)
            or len(set(normalized)) != len(normalized)
        ):
            return []
        return sorted(normalized)

    @staticmethod
    def _normalize(kind: str, value: dict[str, Any]) -> dict[str, Any]:
        fields = {
            "gate_review": (
                "id",
                "store_ref",
                "evidence_ids",
                "status",
                "decision",
                "decided_by",
            ),
            "execution_plan": (
                "id",
                "store_ref",
                "evidence_ids",
                "approval_status",
                "approval_decided_by",
                "source_approval_status",
                "created_by",
            ),
            "command": (
                "id",
                "store_ref",
                "plan_id",
                "command_kind",
                "operation",
                "status",
                "permit_expires_at",
                "claimed_by",
                "lease_expires_at",
                "created_at",
            ),
            "window": (
                "id",
                "store_ref",
                "plan_id",
                "command_id",
                "evidence_ids",
                "status",
                "primary_metric",
                "created_by",
                "created_at",
                "ends_at",
                "evaluation",
            ),
        }[kind]
        result = {field: value.get(field) for field in fields}
        if kind == "command":
            receipt = value.get("receipt")
            result["receipt"] = (
                {
                    "outcome": receipt.get("outcome"),
                    "resulting_state_hash": receipt.get(
                        "resulting_state_hash"
                    ),
                    "evidence_ids": receipt.get("evidence_ids", []),
                }
                if isinstance(receipt, dict)
                else None
            )
        return result

    @staticmethod
    def _exclude(
        excluded: dict[str, list[str]],
        kind: str,
        reasons: list[str],
    ) -> None:
        excluded.setdefault(kind, []).extend(sorted(set(reasons)))

    @staticmethod
    def _hard_reason(reason: str) -> bool:
        return any(
            marker in reason
            for marker in (
                "unavailable",
                "invalid",
                "conflict",
                "mismatch",
                "not_scoped",
            )
        )

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _id(value: dict[str, Any]) -> str:
        return str(value.get("id", ""))

    @staticmethod
    def _iso(value: datetime) -> str:
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        ).isoformat()

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
