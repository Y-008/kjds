from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

RISK_TIERS = ("L0", "L1", "L2", "L3", "L4")
DECISION_SCOPES = {"research", "real_execution"}
AUTHORIZATION_PHASES = {"request", "permit", "execute"}
AuthorizationPhase = Literal["request", "permit", "execute"]


class ActionPolicyError(ValueError):
    """Raised when the action policy registry is missing or unsafe."""


class ActionPolicyRegistry:
    """Machine contract for action risk; it does not grant runtime authority."""

    def __init__(self, registry_path: str | Path | None = None) -> None:
        configured = registry_path or os.getenv("KJDS_ACTION_POLICY_REGISTRY_PATH")
        self.registry_path = Path(configured) if configured else self._default_path()
        self.registry = self._load()
        self._actions = self._validate(self.registry)

    @staticmethod
    def _default_path() -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "project"
            / "registries"
            / "action_policy_registry.json"
        )

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ActionPolicyError(
                f"Unable to load action policy registry: {self.registry_path}"
            ) from exc
        if not isinstance(value, dict) or value.get("status") != "active":
            raise ActionPolicyError("Action policy registry must be an active object")
        return value

    @staticmethod
    def _validate(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
        tiers = registry.get("risk_tiers")
        if tuple(item.get("id") for item in tiers or []) != RISK_TIERS:
            raise ActionPolicyError("Risk tiers must be L0-L4 in canonical order")
        tier_controls = {item["id"]: item for item in tiers}
        actions: dict[str, dict[str, Any]] = {}
        for action in registry.get("actions", []):
            action_id = str(action.get("id", "")).strip()
            if not action_id or action_id in actions:
                raise ActionPolicyError("Action ids must be present and unique")
            tier = action.get("risk_tier")
            if tier not in tier_controls:
                raise ActionPolicyError(f"Unknown risk tier for action: {action_id}")
            if action.get("decision_scope") not in DECISION_SCOPES:
                raise ActionPolicyError(f"Unknown decision scope for action: {action_id}")
            if action.get("fail_closed") is not True:
                raise ActionPolicyError(f"Action must fail closed: {action_id}")
            if action["decision_scope"] == "research" and action.get(
                "external_business_side_effect"
            ):
                raise ActionPolicyError(
                    f"Research action cannot have an external business side effect: {action_id}"
                )
            if tier in {"L3", "L4"}:
                required_true = (
                    "execution_permit_required",
                    "request_revalidation",
                    "execution_revalidation",
                    "idempotency_required",
                    "readback_required",
                )
                if any(action.get(name) is not True for name in required_true):
                    raise ActionPolicyError(
                        f"High-risk action lacks execution controls: {action_id}"
                    )
                if action.get("permit_ttl_policy") != "subject_policy_required":
                    raise ActionPolicyError(
                        f"High-risk action requires an explicit permit expiry policy: {action_id}"
                    )
                if not action.get("limit_keys"):
                    raise ActionPolicyError(
                        f"High-risk action requires blast-radius limits: {action_id}"
                    )
                if "max_daily_runs" not in action["limit_keys"]:
                    raise ActionPolicyError(
                        f"High-risk action requires a daily execution limit: {action_id}"
                    )
                if tier_controls[tier].get("minimum_distinct_identities", 0) < 2:
                    raise ActionPolicyError(
                        f"High-risk tier requires two distinct identities: {tier}"
                    )
                if tier_controls[tier].get("minimum_approval_decisions", 0) < 1:
                    raise ActionPolicyError(
                        f"High-risk tier requires an independent approval: {tier}"
                    )
                ttl = tier_controls[tier].get("permit_ttl_seconds")
                if not isinstance(ttl, int) or not 30 <= ttl <= 900:
                    raise ActionPolicyError(
                        f"High-risk tier requires a bounded permit TTL: {tier}"
                    )
                value_keys = action.get("required_value_keys")
                if not isinstance(value_keys, list) or not value_keys:
                    raise ActionPolicyError(
                        f"High-risk action requires bounded risk values: {action_id}"
                    )
                readiness_keys = action.get("required_readiness_keys")
                if (
                    not isinstance(readiness_keys, list)
                    or not readiness_keys
                    or len(set(readiness_keys)) != len(readiness_keys)
                    or any(not isinstance(key, str) or not key.strip() for key in readiness_keys)
                ):
                    raise ActionPolicyError(
                        f"High-risk action requires explicit readiness keys: {action_id}"
                    )
                if tier == "L4" and tier_controls[tier].get("mfa_required") is not True:
                    raise ActionPolicyError("L4 actions require MFA")
            actions[action_id] = action
        if not actions:
            raise ActionPolicyError("Action policy registry must define actions")
        return actions

    def get(self, action_id: str) -> dict[str, Any]:
        try:
            action = self._actions[action_id]
        except KeyError as exc:
            raise ActionPolicyError(f"Unknown governed action: {action_id}") from exc
        return json.loads(json.dumps(action))

    def get_tier(self, tier_id: str) -> dict[str, Any]:
        for tier in self.registry["risk_tiers"]:
            if tier["id"] == tier_id:
                return json.loads(json.dumps(tier))
        raise ActionPolicyError(f"Unknown action risk tier: {tier_id}")

    @property
    def policy_version(self) -> str:
        return str(self.registry["policy_version"])

    def bind_risk_context(
        self,
        action_id: str,
        *,
        limits: dict[str, Any] | None,
        values: dict[str, Any] | None,
        currency: str | None,
    ) -> dict[str, Any]:
        policy = self.get(action_id)
        if not policy["execution_permit_required"]:
            return {
                "limits": {},
                "values": {},
                "currency": None,
                "permit_ttl_seconds": None,
            }

        limits = limits or {}
        values = values or {}
        expected_limits = set(policy["limit_keys"])
        expected_values = set(policy["required_value_keys"])
        if set(limits) != expected_limits:
            raise ActionPolicyError(
                f"Risk limits must exactly match the action policy: {action_id}"
            )
        if set(values) != expected_values:
            raise ActionPolicyError(
                f"Risk values must exactly match the action policy: {action_id}"
            )

        normalized_limits = {
            key: self._bounded_number(value, key, positive=True)
            for key, value in sorted(limits.items())
        }
        normalized_values = {
            key: self._bounded_number(value, key, positive=False)
            for key, value in sorted(values.items())
        }
        for key, value in normalized_values.items():
            maximum_key = f"max_{key}"
            if maximum_key not in normalized_limits:
                raise ActionPolicyError(
                    f"Risk value has no matching maximum: {action_id}.{key}"
                )
            if Decimal(value) > Decimal(normalized_limits[maximum_key]):
                raise ActionPolicyError(
                    f"Risk value exceeds its action limit: {action_id}.{key}"
                )

        integer_keys = {"quantity", "max_quantity", "max_daily_runs", "max_concurrent_runs"}
        for key in integer_keys.intersection(normalized_limits | normalized_values):
            source = normalized_limits if key in normalized_limits else normalized_values
            if Decimal(source[key]) != Decimal(source[key]).to_integral_value():
                raise ActionPolicyError(f"Risk count must be an integer: {action_id}.{key}")

        financial_keys = {
            "amount",
            "ad_budget",
            "expected_loss",
            "inventory_exposure",
        }
        needs_currency = bool(financial_keys.intersection(normalized_values))
        normalized_currency = (currency or "").strip().upper() or None
        if needs_currency and (
            normalized_currency is None
            or len(normalized_currency) != 3
            or not normalized_currency.isascii()
            or not normalized_currency.isalpha()
        ):
            raise ActionPolicyError(
                f"Financial risk values require a three-letter ASCII currency: {action_id}"
            )

        tier = next(
            item for item in self.registry["risk_tiers"] if item["id"] == policy["risk_tier"]
        )
        return {
            "limits": normalized_limits,
            "values": normalized_values,
            "currency": normalized_currency,
            "permit_ttl_seconds": tier["permit_ttl_seconds"],
        }

    @staticmethod
    def _bounded_number(value: Any, name: str, *, positive: bool) -> str:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ActionPolicyError(f"Risk value must be numeric: {name}") from exc
        if not number.is_finite() or (number <= 0 if positive else number < 0):
            comparator = "positive" if positive else "non-negative"
            raise ActionPolicyError(f"Risk value must be {comparator}: {name}")
        return format(number.normalize(), "f")

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.registry))


class ActionAuthorizationService:
    """The single deterministic policy decision point for governed actions."""

    def __init__(self, registry: ActionPolicyRegistry | None = None) -> None:
        self.registry = registry or ActionPolicyRegistry()

    def authorize_action(
        self,
        *,
        action: str,
        subject_id: str,
        actor_id: str,
        occurred_at: datetime | str,
        phase: AuthorizationPhase,
        limits: dict[str, Any] | None = None,
        values: dict[str, Any] | None = None,
        currency: str | None = None,
        policy_version: str | None = None,
        readiness: dict[str, bool] | None = None,
        approval_actor_ids: list[str] | None = None,
        executor_id: str | None = None,
        mfa_verified: bool = False,
    ) -> dict[str, Any]:
        action = self._required(action, "Action")
        subject_id = self._required(subject_id, "Action subject")
        actor_id = self._required(actor_id, "Action actor")
        if phase not in AUTHORIZATION_PHASES:
            raise ActionPolicyError(f"Unknown authorization phase: {phase}")
        occurred = self._occurred_at(occurred_at)
        blockers: list[str] = []
        policy: dict[str, Any] | None = None
        tier: dict[str, Any] | None = None
        risk: dict[str, Any] | None = None

        try:
            policy = self.registry.get(action)
            tier = self.registry.get_tier(policy["risk_tier"])
            risk = self.registry.bind_risk_context(
                action,
                limits=limits,
                values=values,
                currency=currency,
            )
        except ActionPolicyError:
            blockers.append("ACTION_POLICY_INVALID")

        if policy_version and policy_version != self.registry.policy_version:
            blockers.append("ACTION_POLICY_VERSION_CHANGED")

        normalized_readiness = {
            str(key).strip(): value is True for key, value in (readiness or {}).items()
        }
        if policy:
            for key in policy.get("required_readiness_keys", []):
                if normalized_readiness.get(key) is not True:
                    blockers.append(f"READINESS_REQUIRED:{key}")

        approvals = sorted(
            {
                identity.strip()
                for identity in (approval_actor_ids or [])
                if identity and identity.strip()
            }
        )
        if tier and phase in {"permit", "execute"}:
            if len(approvals) < int(tier["minimum_approval_decisions"]):
                blockers.append("APPROVAL_DECISION_REQUIRED")
            distinct_identities = {actor_id, *approvals}
            if len(distinct_identities) < int(tier["minimum_distinct_identities"]):
                blockers.append("INDEPENDENT_APPROVAL_REQUIRED")
            if tier.get("mfa_required") and not mfa_verified:
                blockers.append("MFA_REQUIRED")

        normalized_executor = executor_id.strip() if executor_id else None
        if phase == "execute":
            if not normalized_executor:
                blockers.append("EXECUTOR_IDENTITY_REQUIRED")
            elif normalized_executor in {actor_id, *approvals}:
                blockers.append("EXECUTOR_INDEPENDENCE_REQUIRED")

        blockers = list(dict.fromkeys(blockers))
        return {
            "allowed": not blockers,
            "action_id": action,
            "subject_id": subject_id,
            "actor_id": actor_id,
            "executor_id": normalized_executor,
            "occurred_at": occurred.isoformat(),
            "phase": phase,
            "policy_version": self.registry.policy_version,
            "decision_scope": policy["decision_scope"] if policy else None,
            "risk_tier": policy["risk_tier"] if policy else None,
            "action_policy": policy,
            "risk": risk,
            "readiness": normalized_readiness,
            "approval_actor_ids": approvals,
            "mfa_verified": bool(mfa_verified),
            "blocking_reasons": blockers,
        }

    @staticmethod
    def require_allowed(decision: dict[str, Any]) -> dict[str, Any]:
        if decision.get("allowed") is not True:
            blockers = decision.get("blocking_reasons") or ["UNKNOWN"]
            messages = {
                "INDEPENDENT_APPROVAL_REQUIRED": (
                    "Action requester must be independent from the approver"
                ),
                "EXECUTOR_INDEPENDENCE_REQUIRED": (
                    "Executor identity must be independent from request and approval"
                ),
            }
            summary = messages.get(blockers[0], "Action authorization denied")
            raise ActionPolicyError(f"{summary}: {', '.join(blockers)}")
        return decision

    @staticmethod
    def _required(value: str, name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ActionPolicyError(f"{name} is required")
        return normalized

    @staticmethod
    def _occurred_at(value: datetime | str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        except ValueError as exc:
            raise ActionPolicyError("Action occurrence time must be ISO 8601") from exc
        if not isinstance(parsed, datetime):
            raise ActionPolicyError("Action occurrence time must be a datetime")
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def require_action_authorization(
    service: ActionAuthorizationService,
    repository: Any,
    **context: Any,
) -> dict[str, Any]:
    """Evaluate and immutably audit a governed action before continuing."""
    decision = service.authorize_action(**context)
    blocking_codes = list(decision["blocking_reasons"])
    repository.append_event(
        "governance.action_authorization_evaluated",
        decision["subject_id"],
        {
            "action_id": decision["action_id"],
            "phase": decision["phase"],
            "allowed": decision["allowed"],
            "audit_code": "ACTION_AUTHORIZED" if decision["allowed"] else blocking_codes[0],
            "blocking_codes": blocking_codes,
            "policy_version": decision["policy_version"],
            "risk_tier": decision["risk_tier"],
        },
        actor_id=decision["actor_id"],
    )
    return service.require_allowed(decision)
