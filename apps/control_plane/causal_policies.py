from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

PolicyReviewVerdict = Literal["accepted", "needs_revision", "rejected"]
StageOutcomeVerdict = Literal["passed", "failed", "inconclusive"]


class CausalPolicyRow(Base):
    __tablename__ = "causal_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    applicability_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    conditions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    action_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    guardrails_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    fallback_action_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rollout_stages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    proposed_by: Mapped[str] = mapped_column(String, nullable=False)
    execution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CausalPolicyReviewRow(Base):
    __tablename__ = "causal_policy_reviews"
    __table_args__ = (
        UniqueConstraint("policy_id", "reviewed_by", name="uq_causal_policy_reviewer"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    policy_id: Mapped[str] = mapped_column(ForeignKey("causal_policies.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    counterarguments_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CausalPolicyReleaseRow(Base):
    __tablename__ = "causal_policy_releases"
    __table_args__ = (
        UniqueConstraint("policy_id", "stage_index", name="uq_causal_policy_release_stage"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    policy_id: Mapped[str] = mapped_column(ForeignKey("causal_policies.id"), nullable=False)
    review_id: Mapped[str] = mapped_column(ForeignKey("causal_policy_reviews.id"), nullable=False)
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    approved_by: Mapped[str] = mapped_column(String, nullable=False)
    execution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CausalPolicyStageOutcomeRow(Base):
    __tablename__ = "causal_policy_stage_outcomes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("causal_policy_releases.id"), unique=True, nullable=False
    )
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    incremental_value_decimal: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    guardrail_breached: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CausalPolicyService:
    OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in"}

    def __init__(self, *, engine, knowledge, evidence) -> None:
        self.engine = engine
        self.knowledge = knowledge
        self.evidence = evidence

    def propose(
        self,
        *,
        title: str,
        objective: str,
        knowledge_ids: list[str],
        applicability: dict[str, Any],
        conditions: list[dict[str, Any]],
        action: dict[str, Any],
        guardrails: list[dict[str, Any]],
        fallback_action: dict[str, Any],
        rollout_stages: list[dict[str, Any]],
        evidence_ids: list[str],
        proposed_by: str,
    ) -> dict[str, Any]:
        title = self._required(title, "Policy title")
        objective = self._required(objective, "Policy objective")
        proposed_by = self._required(proposed_by, "Policy proposer")
        knowledge_ids = sorted({item.strip() for item in knowledge_ids if item.strip()})
        if not knowledge_ids:
            raise ValueError("Policy requires at least one causal knowledge entry")
        source_entries = [self.knowledge.get(item_id) for item_id in knowledge_ids]
        if any(not item["usable"] for item in source_entries):
            raise ValueError("Policy can only use currently usable causal knowledge")
        applicability = self._applicability(applicability)
        for source in source_entries:
            if source["applicability"] != applicability:
                raise ValueError("Policy applicability must exactly match its causal knowledge boundary")
        conditions = self._conditions(conditions)
        action = self._action(action, "Policy action")
        fallback_action = self._action(fallback_action, "Fallback action")
        guardrails = self._guardrails(guardrails)
        rollout_stages = self._stages(rollout_stages)
        evidence_ids = self._evidence(evidence_ids)
        canonical = {
            "title": title,
            "objective": objective,
            "knowledge_ids": knowledge_ids,
            "applicability": applicability,
            "conditions": conditions,
            "action": action,
            "guardrails": guardrails,
            "fallback_action": fallback_action,
            "rollout_stages": rollout_stages,
            "evidence_ids": evidence_ids,
            "proposed_by": proposed_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(CausalPolicyRow).where(CausalPolicyRow.request_hash == request_hash)
            )
            if exact is not None:
                return self.get(exact.id)
            row = CausalPolicyRow(
                id=new_id("cpo"),
                request_hash=request_hash,
                title=title,
                objective=objective,
                knowledge_ids_json=knowledge_ids,
                applicability_json=applicability,
                conditions_json=conditions,
                action_json=action,
                guardrails_json=guardrails,
                fallback_action_json=fallback_action,
                rollout_stages_json=rollout_stages,
                evidence_json=evidence_ids,
                proposed_by=proposed_by,
                execution_eligible=False,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._policy(row)
        self._link(evidence_ids, "causal_policy", result["id"], proposed_by)
        return self.get(result["id"])

    def review(
        self,
        policy_id: str,
        *,
        verdict: PolicyReviewVerdict,
        rationale: str,
        counterarguments: list[str],
        evidence_ids: list[str],
        reviewed_by: str,
    ) -> dict[str, Any]:
        policy = self.get(policy_id)
        reviewed_by = self._required(reviewed_by, "Policy reviewer")
        if reviewed_by == policy["proposed_by"]:
            raise ValueError("Policy proposer cannot independently review their own policy")
        if verdict not in {"accepted", "needs_revision", "rejected"}:
            raise ValueError("Invalid policy review verdict")
        rationale = self._required(rationale, "Policy review rationale")
        counterarguments = self._strings(counterarguments)
        if not counterarguments:
            raise ValueError("Policy review requires at least one counterargument")
        evidence_ids = self._evidence(evidence_ids)
        canonical = {
            "policy_id": policy_id,
            "verdict": verdict,
            "rationale": rationale,
            "counterarguments": counterarguments,
            "evidence_ids": evidence_ids,
            "reviewed_by": reviewed_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(CausalPolicyReviewRow).where(
                    CausalPolicyReviewRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._review(exact)
            previous = session.scalar(
                select(CausalPolicyReviewRow).where(
                    CausalPolicyReviewRow.policy_id == policy_id,
                    CausalPolicyReviewRow.reviewed_by == reviewed_by,
                )
            )
            if previous is not None:
                raise ValueError("Reviewer has already submitted an immutable policy review")
            row = CausalPolicyReviewRow(
                id=new_id("cpr"),
                request_hash=request_hash,
                policy_id=policy_id,
                verdict=verdict,
                rationale=rationale,
                counterarguments_json=counterarguments,
                evidence_json=evidence_ids,
                reviewed_by=reviewed_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._review(row)
        self._link(evidence_ids, "causal_policy_review", result["id"], reviewed_by)
        return result

    def release_stage(
        self,
        policy_id: str,
        *,
        review_id: str,
        stage_index: int,
        rationale: str,
        evidence_ids: list[str],
        approved_by: str,
    ) -> dict[str, Any]:
        policy = self.get(policy_id)
        if not policy["usable"]:
            raise ValueError("Policy source knowledge is no longer usable")
        review = self.get_review(review_id)
        if review["policy_id"] != policy_id or review["verdict"] != "accepted":
            raise ValueError("Stage release requires an accepted review for this policy")
        approved_by = self._required(approved_by, "Stage approver")
        if approved_by in {policy["proposed_by"], review["reviewed_by"]}:
            raise ValueError("Stage approver must be independent from proposer and reviewer")
        if stage_index < 0 or stage_index >= len(policy["rollout_stages"]):
            raise ValueError("Invalid rollout stage index")
        rationale = self._required(rationale, "Stage release rationale")
        evidence_ids = self._evidence(evidence_ids)
        with Session(self.engine) as session:
            previous_releases = list(
                session.scalars(
                    select(CausalPolicyReleaseRow)
                    .where(CausalPolicyReleaseRow.policy_id == policy_id)
                    .order_by(CausalPolicyReleaseRow.stage_index)
                )
            )
            previous_indexes = {item.stage_index for item in previous_releases}
            if stage_index in previous_indexes:
                existing = next(item for item in previous_releases if item.stage_index == stage_index)
                candidate_hash = self._hash(
                    {
                        "policy_id": policy_id,
                        "review_id": review_id,
                        "stage_index": stage_index,
                        "rationale": rationale,
                        "evidence_ids": evidence_ids,
                        "approved_by": approved_by,
                    }
                )
                if existing.request_hash == candidate_hash:
                    return self._release(existing, policy["rollout_stages"])
                raise ValueError("Rollout stage already has an immutable release decision")
            if previous_indexes != set(range(stage_index)):
                raise ValueError("Rollout stages cannot be skipped")
            if stage_index > 0:
                previous_release = previous_releases[-1]
                outcome = session.scalar(
                    select(CausalPolicyStageOutcomeRow).where(
                        CausalPolicyStageOutcomeRow.release_id == previous_release.id
                    )
                )
                if outcome is None:
                    raise ValueError("Previous rollout stage needs a recorded outcome")
                previous_stage = policy["rollout_stages"][stage_index - 1]
                if (
                    outcome.verdict != "passed"
                    or outcome.guardrail_breached
                    or outcome.observation_count < previous_stage["minimum_observation_count"]
                    or Decimal(outcome.incremental_value_decimal)
                    < Decimal(previous_stage["minimum_incremental_value"])
                ):
                    raise ValueError("Previous rollout stage did not satisfy promotion gates")
        canonical = {
            "policy_id": policy_id,
            "review_id": review_id,
            "stage_index": stage_index,
            "rationale": rationale,
            "evidence_ids": evidence_ids,
            "approved_by": approved_by,
        }
        with Session(self.engine) as session, session.begin():
            row = CausalPolicyReleaseRow(
                id=new_id("csr"),
                request_hash=self._hash(canonical),
                policy_id=policy_id,
                review_id=review_id,
                stage_index=stage_index,
                rationale=rationale,
                evidence_json=evidence_ids,
                approved_by=approved_by,
                execution_eligible=False,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._release(row, policy["rollout_stages"])
        self._link(evidence_ids, "causal_policy_release", result["id"], approved_by)
        return result

    def _record_stage_outcome(
        self,
        release_id: str,
        *,
        verdict: StageOutcomeVerdict,
        observation_count: int,
        incremental_value: Decimal,
        guardrail_breached: bool,
        notes: str,
        evidence_ids: list[str],
        recorded_by: str,
    ) -> dict[str, Any]:
        self.get_release(release_id)
        if verdict not in {"passed", "failed", "inconclusive"}:
            raise ValueError("Invalid rollout stage outcome verdict")
        if observation_count < 0:
            raise ValueError("Observation count cannot be negative")
        incremental_value = self._finite_decimal(incremental_value, "Incremental value")
        notes = self._required(notes, "Stage outcome notes")
        recorded_by = self._required(recorded_by, "Stage outcome recorder")
        evidence_ids = self._evidence(evidence_ids)
        if guardrail_breached and verdict == "passed":
            raise ValueError("A stage with a breached guardrail cannot pass")
        canonical = {
            "release_id": release_id,
            "verdict": verdict,
            "observation_count": observation_count,
            "incremental_value": str(incremental_value),
            "guardrail_breached": guardrail_breached,
            "notes": notes,
            "evidence_ids": evidence_ids,
            "recorded_by": recorded_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(CausalPolicyStageOutcomeRow).where(
                    CausalPolicyStageOutcomeRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._outcome(exact)
            previous = session.scalar(
                select(CausalPolicyStageOutcomeRow).where(
                    CausalPolicyStageOutcomeRow.release_id == release_id
                )
            )
            if previous is not None:
                raise ValueError("Rollout stage already has an immutable outcome")
            row = CausalPolicyStageOutcomeRow(
                id=new_id("cso"),
                request_hash=request_hash,
                release_id=release_id,
                verdict=verdict,
                observation_count=observation_count,
                incremental_value_decimal=incremental_value,
                guardrail_breached=guardrail_breached,
                notes=notes,
                evidence_json=evidence_ids,
                recorded_by=recorded_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._outcome(row)
        self._link(evidence_ids, "causal_policy_stage_outcome", result["id"], recorded_by)
        return result

    def evaluate_context(self, policy_id: str, context: dict[str, Any]) -> dict[str, Any]:
        policy = self.get(policy_id)
        missing = []
        failed = []
        for key, expected in policy["applicability"].items():
            if key not in context:
                missing.append(key)
            elif context[key] != expected:
                failed.append({"field": key, "reason": "outside_applicability"})
        for condition in policy["conditions"]:
            field = condition["field"]
            if field not in context:
                missing.append(field)
            elif not self._matches(context[field], condition["operator"], condition["value"]):
                failed.append({"field": field, "reason": "condition_not_met"})
        matched = policy["usable"] and not missing and not failed
        return {
            "policy_id": policy_id,
            "matched": matched,
            "missing_fields": sorted(set(missing)),
            "failed_conditions": failed,
            "recommendation": policy["action"] if matched else policy["fallback_action"],
            "execution_eligible": False,
            "automatic_execution": False,
            "reason": "CONDITIONS_MATCH_ADVISORY_ONLY" if matched else "POLICY_NOT_APPLICABLE",
        }

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(session.scalars(select(CausalPolicyRow.id).order_by(CausalPolicyRow.created_at)))
        return [self.get(item_id) for item_id in ids]

    def get(self, policy_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(CausalPolicyRow, policy_id)
            if row is None:
                raise KeyError(f"Causal policy not found: {policy_id}")
            reviews = list(
                session.scalars(
                    select(CausalPolicyReviewRow)
                    .where(CausalPolicyReviewRow.policy_id == policy_id)
                    .order_by(CausalPolicyReviewRow.created_at)
                )
            )
            releases = list(
                session.scalars(
                    select(CausalPolicyReleaseRow)
                    .where(CausalPolicyReleaseRow.policy_id == policy_id)
                    .order_by(CausalPolicyReleaseRow.stage_index)
                )
            )
            release_ids = [item.id for item in releases]
            outcomes = (
                list(
                    session.scalars(
                        select(CausalPolicyStageOutcomeRow).where(
                            CausalPolicyStageOutcomeRow.release_id.in_(release_ids)
                        )
                    )
                )
                if release_ids
                else []
            )
            result = self._policy(row)
        outcome_by_release = {item.release_id: item for item in outcomes}
        knowledge = [self.knowledge.get(item_id) for item_id in result["knowledge_ids"]]
        usable = all(item["usable"] for item in knowledge)
        return {
            **result,
            "usable": usable,
            "validity_status": "active" if usable else "source_knowledge_invalidated",
            "reviews": [self._review(item) for item in reviews],
            "releases": [
                {
                    **self._release(item, result["rollout_stages"]),
                    "outcome": (
                        self._outcome(outcome_by_release[item.id])
                        if item.id in outcome_by_release
                        else None
                    ),
                }
                for item in releases
            ],
            "execution_eligible": False,
            "automatic_execution": False,
        }

    def get_review(self, review_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(CausalPolicyReviewRow, review_id)
            if row is None:
                raise KeyError(f"Causal policy review not found: {review_id}")
            return self._review(row)

    def get_release(self, release_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(CausalPolicyReleaseRow, release_id)
            if row is None:
                raise KeyError(f"Causal policy release not found: {release_id}")
            policy = session.get(CausalPolicyRow, row.policy_id)
            if policy is None:
                raise KeyError(f"Causal policy not found: {row.policy_id}")
            outcome = session.scalar(
                select(CausalPolicyStageOutcomeRow).where(
                    CausalPolicyStageOutcomeRow.release_id == release_id
                )
            )
            result = self._release(row, policy.rollout_stages_json)
            return {**result, "outcome": self._outcome(outcome) if outcome else None}

    @classmethod
    def _conditions(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not values:
            raise ValueError("Policy requires at least one explicit condition")
        result = []
        for item in values:
            field = str(item.get("field", "")).strip()
            operator = str(item.get("operator", "")).strip()
            if not field or operator not in cls.OPERATORS or "value" not in item:
                raise ValueError("Each policy condition requires field, supported operator, and value")
            result.append({"field": field, "operator": operator, "value": item["value"]})
        return result

    @staticmethod
    def _action(value: dict[str, Any], name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be structured")
        action_type = str(value.get("type", "")).strip()
        parameters = value.get("parameters", {})
        if not action_type.startswith("recommend_") or not isinstance(parameters, dict):
            raise ValueError(f"{name} must use a recommend_* type and structured parameters")
        return {"type": action_type, "parameters": parameters}

    @classmethod
    def _guardrails(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not values:
            raise ValueError("Policy requires at least one guardrail")
        result = []
        for item in values:
            metric = str(item.get("metric", "")).strip()
            direction = str(item.get("direction", "")).strip()
            if not metric or direction not in {"min", "max"} or "threshold" not in item:
                raise ValueError("Each guardrail requires metric, min/max direction, and threshold")
            threshold = cls._finite_decimal(item["threshold"], "Guardrail threshold")
            result.append({"metric": metric, "direction": direction, "threshold": str(threshold)})
        return result

    @classmethod
    def _stages(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(values) < 2:
            raise ValueError("Controlled rollout requires at least shadow and limited stages")
        result = []
        previous_fraction = Decimal("-1")
        for index, item in enumerate(values):
            name = str(item.get("name", "")).strip()
            fraction = cls._finite_decimal(
                item.get("max_exposure_fraction", "-1"), "Rollout exposure fraction"
            )
            observation_count = int(item.get("minimum_observation_count", -1))
            minimum_value = cls._finite_decimal(
                item.get("minimum_incremental_value", "0"),
                "Minimum incremental value",
            )
            if not name or fraction < 0 or fraction > 1 or observation_count < 0:
                raise ValueError("Invalid rollout stage")
            if fraction <= previous_fraction:
                raise ValueError("Rollout exposure fractions must strictly increase")
            if index == 0 and fraction != 0:
                raise ValueError("First rollout stage must be shadow with zero exposure")
            previous_fraction = fraction
            result.append(
                {
                    "name": name,
                    "max_exposure_fraction": str(fraction),
                    "minimum_observation_count": observation_count,
                    "minimum_incremental_value": str(minimum_value),
                }
            )
        return result

    @staticmethod
    def _applicability(value: dict[str, Any]) -> dict[str, Any]:
        required = {"platform", "country", "category", "population"}
        if not isinstance(value, dict) or required - set(value):
            raise ValueError("Policy applicability requires platform, country, category, and population")
        return {str(key).strip(): item.strip() if isinstance(item, str) else item for key, item in value.items()}

    @staticmethod
    def _matches(actual: Any, operator: str, expected: Any) -> bool:
        if operator == "eq":
            return actual == expected
        if operator == "neq":
            return actual != expected
        if operator in {"in", "not_in"}:
            if not isinstance(expected, list):
                return False
            present = actual in expected
            return present if operator == "in" else not present
        try:
            left = Decimal(str(actual))
            right = Decimal(str(expected))
        except (InvalidOperation, TypeError, ValueError):
            return False
        if not left.is_finite() or not right.is_finite():
            return False
        return {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[operator]

    @staticmethod
    def _finite_decimal(value: Any, name: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be decimal") from exc
        if not parsed.is_finite():
            raise ValueError(f"{name} must be finite")
        return parsed

    def _evidence(self, values: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in values if item.strip()})
        if not normalized:
            raise ValueError("Evidence is required")
        self.evidence.require_valid(normalized)
        return normalized

    def _link(self, evidence_ids: list[str], target_type: str, target_id: str, actor: str) -> None:
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type=target_type,
                target_id=target_id,
                relationship="supports",
                created_by=actor,
            )

    @staticmethod
    def _required(value: str, name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        return cleaned

    @staticmethod
    def _strings(values: list[str]) -> list[str]:
        return [item.strip() for item in values if item.strip()]

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()

    @staticmethod
    def _iso(value: datetime) -> str:
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()

    @classmethod
    def _policy(cls, row: CausalPolicyRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "title": row.title,
            "objective": row.objective,
            "knowledge_ids": row.knowledge_ids_json,
            "applicability": row.applicability_json,
            "conditions": row.conditions_json,
            "action": row.action_json,
            "guardrails": row.guardrails_json,
            "fallback_action": row.fallback_action_json,
            "rollout_stages": row.rollout_stages_json,
            "evidence_ids": row.evidence_json,
            "proposed_by": row.proposed_by,
            "execution_eligible": False,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }

    @classmethod
    def _review(cls, row: CausalPolicyReviewRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "policy_id": row.policy_id,
            "verdict": row.verdict,
            "rationale": row.rationale,
            "counterarguments": row.counterarguments_json,
            "evidence_ids": row.evidence_json,
            "reviewed_by": row.reviewed_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }

    @classmethod
    def _release(cls, row: CausalPolicyReleaseRow, stages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": row.id,
            "policy_id": row.policy_id,
            "review_id": row.review_id,
            "stage_index": row.stage_index,
            "stage": stages[row.stage_index],
            "rationale": row.rationale,
            "evidence_ids": row.evidence_json,
            "approved_by": row.approved_by,
            "execution_eligible": False,
            "automatic_promotion": False,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }

    @classmethod
    def _outcome(cls, row: CausalPolicyStageOutcomeRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "release_id": row.release_id,
            "verdict": row.verdict,
            "observation_count": row.observation_count,
            "incremental_value": str(Decimal(row.incremental_value_decimal)),
            "guardrail_breached": row.guardrail_breached,
            "notes": row.notes,
            "evidence_ids": row.evidence_json,
            "recorded_by": row.recorded_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }
