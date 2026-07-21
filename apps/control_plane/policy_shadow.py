from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base


class PolicyEvaluationRow(Base):
    __tablename__ = "causal_policy_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "idempotency_key",
            name="uq_causal_policy_evaluation_key",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    policy_id: Mapped[str] = mapped_column(ForeignKey("causal_policies.id"), nullable=False)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("causal_policy_releases.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    policy_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evaluated_by: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyShadowBatchRow(Base):
    __tablename__ = "causal_policy_shadow_batches"
    __table_args__ = (
        UniqueConstraint("release_id", "batch_key", name="uq_causal_policy_shadow_batch"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    policy_id: Mapped[str] = mapped_column(ForeignKey("causal_policies.id"), nullable=False)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("causal_policy_releases.id"), nullable=False
    )
    batch_key: Mapped[str] = mapped_column(String, nullable=False)
    evaluation_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    context_count: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fallback_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyActivationHandoffRow(Base):
    __tablename__ = "causal_policy_activation_handoffs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    policy_id: Mapped[str] = mapped_column(ForeignKey("causal_policies.id"), nullable=False)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("causal_policy_releases.id"), unique=True, nullable=False
    )
    approval_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    evaluation_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    policy_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyShadowService:
    FORBIDDEN_KEY_TOKENS = {
        "address",
        "customer",
        "email",
        "password",
        "phone",
        "secret",
        "token",
    }
    FORBIDDEN_EXACT_KEYS = {"api_key", "name", "full_name", "customer_name"}

    def __init__(self, *, engine, policies, evidence, commerce) -> None:
        self.engine = engine
        self.policies = policies
        self.evidence = evidence
        self.commerce = commerce

    def record_evaluation(
        self,
        release_id: str,
        *,
        idempotency_key: str,
        context: dict[str, Any],
        baseline: dict[str, Any] | None = None,
        observed_at: str,
        evidence_ids: list[str],
        evaluated_by: str,
    ) -> dict[str, Any]:
        release, policy = self._release_policy(release_id)
        idempotency_key = self._required(idempotency_key, "Evaluation idempotency key")
        evaluated_by = self._required(evaluated_by, "Evaluator identity")
        context = self._context(context)
        observed_at_dt = self._datetime(observed_at, "observed_at")
        evidence_ids = self._evidence(evidence_ids)
        challenger_result = self.policies.evaluate_context(policy["id"], context)
        comparison, baseline_evidence_ids = self._comparison(
            baseline,
            challenger_result=challenger_result,
            evaluated_by=evaluated_by,
        )
        evidence_ids = sorted(set(evidence_ids) | set(baseline_evidence_ids))
        result = (
            {**challenger_result, "shadow_comparison": comparison}
            if comparison is not None
            else challenger_result
        )
        snapshot_hash = self._policy_snapshot_hash(policy, release)
        canonical = {
            "release_id": release_id,
            "idempotency_key": idempotency_key,
            "policy_snapshot_hash": snapshot_hash,
            "context": context,
            "result": result,
            "observed_at": observed_at_dt.isoformat(),
            "evidence_ids": evidence_ids,
            "evaluated_by": evaluated_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(PolicyEvaluationRow).where(
                    PolicyEvaluationRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._evaluation(exact)
            previous = session.scalar(
                select(PolicyEvaluationRow).where(
                    PolicyEvaluationRow.release_id == release_id,
                    PolicyEvaluationRow.idempotency_key == idempotency_key,
                )
            )
            if previous is not None:
                raise ValueError("Evaluation idempotency key already has immutable content")
            row = PolicyEvaluationRow(
                id=new_id("cpe"),
                request_hash=request_hash,
                policy_id=policy["id"],
                release_id=release_id,
                idempotency_key=idempotency_key,
                policy_snapshot_hash=snapshot_hash,
                context_hash=self._hash(context),
                context_json=context,
                result_json=result,
                evidence_json=evidence_ids,
                evaluated_by=evaluated_by,
                observed_at=observed_at_dt,
                recorded_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            saved = self._evaluation(row)
        self._link(evidence_ids, "causal_policy_evaluation", saved["id"], evaluated_by)
        return saved

    def run_shadow_batch(
        self,
        release_id: str,
        *,
        batch_key: str,
        contexts: list[dict[str, Any]],
        baselines: list[dict[str, Any]] | None = None,
        observed_at: str,
        evidence_ids: list[str],
        created_by: str,
    ) -> dict[str, Any]:
        release, policy = self._release_policy(release_id)
        if release["stage"]["max_exposure_fraction"] != "0":
            raise ValueError("Shadow batches require a zero-exposure release stage")
        batch_key = self._required(batch_key, "Shadow batch key")
        created_by = self._required(created_by, "Shadow batch creator")
        if not 1 <= len(contexts) <= 100:
            raise ValueError("Shadow batch requires between 1 and 100 contexts")
        observed_at_dt = self._datetime(observed_at, "observed_at")
        evidence_ids = self._evidence(evidence_ids)
        normalized_contexts = [self._context(item) for item in contexts]
        if baselines is not None and len(baselines) != len(normalized_contexts):
            raise ValueError("Shadow batch baselines must match the context count")
        normalized_baselines = baselines or [None] * len(normalized_contexts)
        canonical = {
            "release_id": release_id,
            "batch_key": batch_key,
            "contexts": normalized_contexts,
            "baselines": normalized_baselines,
            "observed_at": observed_at_dt.isoformat(),
            "evidence_ids": evidence_ids,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session:
            exact = session.scalar(
                select(PolicyShadowBatchRow).where(
                    PolicyShadowBatchRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._batch(exact)
            previous = session.scalar(
                select(PolicyShadowBatchRow).where(
                    PolicyShadowBatchRow.release_id == release_id,
                    PolicyShadowBatchRow.batch_key == batch_key,
                )
            )
            if previous is not None:
                raise ValueError("Shadow batch key already has immutable content")
        evaluations = [
            self.record_evaluation(
                release_id,
                idempotency_key=f"{batch_key}:{index}",
                context=context,
                baseline=normalized_baselines[index],
                observed_at=observed_at_dt.isoformat(),
                evidence_ids=evidence_ids,
                evaluated_by=created_by,
            )
            for index, context in enumerate(normalized_contexts)
        ]
        matched_count = sum(1 for item in evaluations if item["result"]["matched"])
        with Session(self.engine) as session, session.begin():
            row = PolicyShadowBatchRow(
                id=new_id("cpb"),
                request_hash=request_hash,
                policy_id=policy["id"],
                release_id=release_id,
                batch_key=batch_key,
                evaluation_ids_json=[item["id"] for item in evaluations],
                context_count=len(evaluations),
                matched_count=matched_count,
                fallback_count=len(evaluations) - matched_count,
                evidence_json=evidence_ids,
                created_by=created_by,
                observed_at=observed_at_dt,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._batch(row)
        self._link(evidence_ids, "causal_policy_shadow_batch", result["id"], created_by)
        return result

    def request_activation(
        self,
        release_id: str,
        *,
        evaluation_ids: list[str],
        evidence_ids: list[str],
        requested_by: str,
    ) -> dict[str, Any]:
        release, policy = self._release_policy(release_id)
        requested_by = self._required(requested_by, "Activation requester")
        if release["stage"]["max_exposure_fraction"] == "0":
            raise ValueError("A zero-exposure shadow stage cannot be activated")
        previous_release = next(
            (
                item
                for item in policy["releases"]
                if item["stage_index"] == release["stage_index"] - 1
            ),
            None,
        )
        if previous_release is None or previous_release["outcome"] is None:
            raise ValueError("Activation requires the previous stage outcome")
        if (
            previous_release["outcome"]["verdict"] != "passed"
            or previous_release["outcome"]["guardrail_breached"]
        ):
            raise ValueError("Previous stage outcome blocks activation")
        evaluation_ids = sorted({item.strip() for item in evaluation_ids if item.strip()})
        if not evaluation_ids:
            raise ValueError("Activation requires immutable policy evaluations")
        evaluations = [self.get_evaluation(item_id) for item_id in evaluation_ids]
        if any(
            item["policy_id"] != policy["id"]
            or item["release_id"] != previous_release["id"]
            for item in evaluations
        ):
            raise ValueError("Activation evaluations must belong to the previous policy stage")
        self._require_comparisons(evaluations, purpose="Activation")
        for item in evaluations:
            self.evidence.require_valid(item["evidence_ids"])
        previous_stage = policy["rollout_stages"][release["stage_index"] - 1]
        if len(evaluations) < previous_stage["minimum_observation_count"]:
            raise ValueError("Activation has insufficient immutable shadow evaluations")
        evidence_ids = self._evidence(evidence_ids)
        snapshot_hash = self._policy_snapshot_hash(policy, release)
        canonical = {
            "release_id": release_id,
            "evaluation_ids": evaluation_ids,
            "evidence_ids": evidence_ids,
            "policy_snapshot_hash": snapshot_hash,
            "requested_by": requested_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session:
            exact = session.scalar(
                select(PolicyActivationHandoffRow).where(
                    PolicyActivationHandoffRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self.get_handoff(exact.id)
            previous = session.scalar(
                select(PolicyActivationHandoffRow).where(
                    PolicyActivationHandoffRow.release_id == release_id
                )
            )
            if previous is not None:
                raise ValueError("Policy release already has an immutable activation handoff")
        matched_count = sum(1 for item in evaluations if item["result"]["matched"])
        approval = self.commerce.request_approval(
            action="causal_policy.activate_stage",
            resource_type="causal_policy_release",
            resource_id=release_id,
            requested_by=requested_by,
            payload={
                "policy_id": policy["id"],
                "release_id": release_id,
                "stage": release["stage"],
                "action": policy["action"],
                "fallback_action": policy["fallback_action"],
                "guardrails": policy["guardrails"],
                "knowledge_ids": policy["knowledge_ids"],
                "policy_snapshot_hash": snapshot_hash,
                "evaluation_count": len(evaluations),
                "matched_count": matched_count,
                "automatic_execution": False,
            },
        )
        with Session(self.engine) as session, session.begin():
            row = PolicyActivationHandoffRow(
                id=new_id("cph"),
                request_hash=request_hash,
                policy_id=policy["id"],
                release_id=release_id,
                approval_id=approval.id,
                evaluation_ids_json=evaluation_ids,
                evidence_json=evidence_ids,
                policy_snapshot_hash=snapshot_hash,
                requested_by=requested_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            handoff_id = row.id
        self._link(evidence_ids, "causal_policy_activation_handoff", handoff_id, requested_by)
        return self.get_handoff(handoff_id)

    def list_evaluations(self, policy_id: str | None = None) -> list[dict[str, Any]]:
        query = select(PolicyEvaluationRow).order_by(
            PolicyEvaluationRow.observed_at,
            PolicyEvaluationRow.recorded_at,
            PolicyEvaluationRow.id,
        )
        if policy_id:
            self.policies.get(policy_id)
            query = query.where(PolicyEvaluationRow.policy_id == policy_id)
        with Session(self.engine) as session:
            rows = list(session.scalars(query))
        return [self._evaluation(row) for row in rows]

    def validate_stage_outcome(self, release_id: str, observation_count: int) -> None:
        release, policy = self._release_policy(release_id)
        if release["stage"]["max_exposure_fraction"] != "0":
            return
        evaluations = self.list_evaluations(policy["id"])
        evaluations = [item for item in evaluations if item["release_id"] == release_id]
        evaluation_ids = [item["id"] for item in evaluations]
        minimum_count = policy["rollout_stages"][release["stage_index"]][
            "minimum_observation_count"
        ]
        if len(evaluation_ids) < minimum_count:
            raise ValueError(
                "Shadow outcome requires the preregistered number of immutable evaluations"
            )
        if observation_count != len(evaluation_ids):
            raise ValueError(
                "Shadow outcome observation count must equal the immutable evaluation ledger"
            )
        self._require_comparisons(evaluations, purpose="Shadow outcome")
        for item in evaluations:
            self.evidence.require_valid(item["evidence_ids"])

    def record_stage_outcome(
        self,
        release_id: str,
        *,
        verdict: str,
        observation_count: int,
        incremental_value: Any,
        guardrail_breached: bool,
        notes: str,
        evidence_ids: list[str],
        recorded_by: str,
    ) -> dict[str, Any]:
        self.validate_stage_outcome(release_id, observation_count)
        return self.policies._record_stage_outcome(
            release_id,
            verdict=verdict,
            observation_count=observation_count,
            incremental_value=incremental_value,
            guardrail_breached=guardrail_breached,
            notes=notes,
            evidence_ids=evidence_ids,
            recorded_by=recorded_by,
        )

    def list_batches(self, policy_id: str | None = None) -> list[dict[str, Any]]:
        query = select(PolicyShadowBatchRow).order_by(PolicyShadowBatchRow.created_at)
        if policy_id:
            self.policies.get(policy_id)
            query = query.where(PolicyShadowBatchRow.policy_id == policy_id)
        with Session(self.engine) as session:
            rows = list(session.scalars(query))
        return [self._batch(row) for row in rows]

    def list_handoffs(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    select(PolicyActivationHandoffRow.id).order_by(
                        PolicyActivationHandoffRow.created_at
                    )
                )
            )
        return [self.get_handoff(item_id) for item_id in ids]

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(PolicyEvaluationRow, evaluation_id)
            if row is None:
                raise KeyError(f"Policy evaluation not found: {evaluation_id}")
            return self._evaluation(row)

    def get_handoff(self, handoff_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(PolicyActivationHandoffRow, handoff_id)
            if row is None:
                raise KeyError(f"Policy activation handoff not found: {handoff_id}")
            result = self._handoff(row)
        policy = self.policies.get(result["policy_id"])
        release = self.policies.get_release(result["release_id"])
        current_hash = self._policy_snapshot_hash(policy, release)
        approval = self.commerce.repo.get_approval(result["approval_id"])
        if not policy["usable"]:
            validity_status = "source_policy_invalidated"
        elif current_hash != result["policy_snapshot_hash"]:
            validity_status = "policy_snapshot_changed"
        else:
            validity_status = "active"
        return {
            **result,
            "approval_status": approval.status.value,
            "approval_decided_by": approval.decided_by,
            "validity_status": validity_status,
            "activation_eligible": validity_status == "active"
            and approval.status.value == "approved",
            "execution_eligible": False,
            "automatic_execution": False,
        }

    def _release_policy(self, release_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        release = self.policies.get_release(release_id)
        policy = self.policies.get(release["policy_id"])
        if not policy["usable"]:
            raise ValueError("Policy source knowledge is no longer usable")
        if not any(item["id"] == release_id for item in policy["releases"]):
            raise ValueError("Policy release is not active in the policy ledger")
        return release, policy

    @classmethod
    def _context(cls, value: dict[str, Any]) -> dict[str, Any]:
        return cls._structured(value, name="Policy evaluation context", path="context")

    @classmethod
    def _structured(cls, value: dict[str, Any], *, name: str, path: str) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError(f"{name} must be a non-empty object")
        if len(value) > 100:
            raise ValueError(f"{name} exceeds the 100-field limit")
        cls._reject_sensitive(value, path)
        try:
            encoded = json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be JSON serializable") from exc
        if len(encoded.encode()) > 65536:
            raise ValueError(f"{name} exceeds the 64 KiB limit")
        return json.loads(encoded)

    def _comparison(
        self,
        baseline: dict[str, Any] | None,
        *,
        challenger_result: dict[str, Any],
        evaluated_by: str,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if baseline is None:
            return None, []
        if not isinstance(baseline, dict):
            raise ValueError("Shadow baseline must be an object")
        kind = self._required(str(baseline.get("kind", "")), "Shadow baseline kind")
        if kind not in {"champion", "human"}:
            raise ValueError("Shadow baseline kind must be champion or human")
        actor_id = self._required(
            str(baseline.get("actor_id", "")),
            "Shadow baseline actor",
        )
        if actor_id == evaluated_by:
            raise ValueError("Shadow baseline actor must be independent from evaluator")
        baseline_result = self._structured(
            baseline.get("result"),
            name="Shadow baseline result",
            path="baseline.result",
        )
        baseline_evidence_ids = self._evidence(baseline.get("evidence_ids") or [])
        changed_path_count, changed_paths = self._changed_paths(
            baseline_result,
            challenger_result,
        )
        return (
            {
                "baseline_kind": kind,
                "baseline_actor_id": actor_id,
                "baseline_result": baseline_result,
                "baseline_result_hash": self._hash(baseline_result),
                "challenger_result_hash": self._hash(challenger_result),
                "baseline_evidence_ids": baseline_evidence_ids,
                "exact_match": changed_path_count == 0,
                "changed_path_count": changed_path_count,
                "changed_paths": changed_paths,
                "changed_paths_truncated": changed_path_count > len(changed_paths),
            },
            baseline_evidence_ids,
        )

    @staticmethod
    def _require_comparisons(evaluations: list[dict[str, Any]], *, purpose: str) -> None:
        if any("shadow_comparison" not in item["result"] for item in evaluations):
            raise ValueError(f"{purpose} requires champion or human baseline comparisons")

    @classmethod
    def _changed_paths(cls, baseline: Any, challenger: Any) -> tuple[int, list[str]]:
        paths: list[str] = []
        count = 0

        def record(path: str) -> None:
            nonlocal count
            count += 1
            if len(paths) < 100:
                paths.append(path)

        def walk(left: Any, right: Any, path: str) -> None:
            if isinstance(left, dict) and isinstance(right, dict):
                for key in sorted(set(left) | set(right)):
                    child = f"{path}/{cls._pointer_token(key)}"
                    if key not in left or key not in right:
                        record(child)
                    else:
                        walk(left[key], right[key], child)
                return
            if isinstance(left, list) and isinstance(right, list):
                for index in range(max(len(left), len(right))):
                    child = f"{path}/{index}"
                    if index >= len(left) or index >= len(right):
                        record(child)
                    else:
                        walk(left[index], right[index], child)
                return
            if left != right:
                record(path)

        walk(baseline, challenger, "")
        return count, paths

    @staticmethod
    def _pointer_token(value: Any) -> str:
        return str(value).replace("~", "~0").replace("/", "~1")

    @classmethod
    def _reject_sensitive(cls, value: Any, path: str = "context") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).strip().casefold()
                tokenized = normalized.replace("-", "_").replace(".", "_").split("_")
                if (
                    normalized in cls.FORBIDDEN_EXACT_KEYS
                    or cls.FORBIDDEN_KEY_TOKENS.intersection(tokenized)
                ):
                    raise ValueError(f"Sensitive field is forbidden in policy context: {path}.{key}")
                cls._reject_sensitive(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._reject_sensitive(item, f"{path}[{index}]")

    @classmethod
    def _policy_snapshot_hash(cls, policy: dict[str, Any], release: dict[str, Any]) -> str:
        return cls._hash(
            {
                "policy_id": policy["id"],
                "knowledge_ids": policy["knowledge_ids"],
                "validity_status": policy["validity_status"],
                "conditions": policy["conditions"],
                "action": policy["action"],
                "fallback_action": policy["fallback_action"],
                "guardrails": policy["guardrails"],
                "release_id": release["id"],
                "stage": release["stage"],
            }
        )

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
    def _datetime(value: str, name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} must include timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _iso(value: datetime) -> str:
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()

    @classmethod
    def _evaluation(cls, row: PolicyEvaluationRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "policy_id": row.policy_id,
            "release_id": row.release_id,
            "idempotency_key": row.idempotency_key,
            "policy_snapshot_hash": row.policy_snapshot_hash,
            "context_hash": row.context_hash,
            "context": row.context_json,
            "result": row.result_json,
            "evidence_ids": row.evidence_json,
            "evaluated_by": row.evaluated_by,
            "observed_at": cls._iso(row.observed_at),
            "recorded_at": cls._iso(row.recorded_at),
            "immutable": True,
            "execution_eligible": False,
        }

    @classmethod
    def _batch(cls, row: PolicyShadowBatchRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "policy_id": row.policy_id,
            "release_id": row.release_id,
            "batch_key": row.batch_key,
            "evaluation_ids": row.evaluation_ids_json,
            "context_count": row.context_count,
            "matched_count": row.matched_count,
            "fallback_count": row.fallback_count,
            "evidence_ids": row.evidence_json,
            "created_by": row.created_by,
            "observed_at": cls._iso(row.observed_at),
            "created_at": cls._iso(row.created_at),
            "zero_exposure": True,
            "execution_eligible": False,
        }

    @classmethod
    def _handoff(cls, row: PolicyActivationHandoffRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "policy_id": row.policy_id,
            "release_id": row.release_id,
            "approval_id": row.approval_id,
            "evaluation_ids": row.evaluation_ids_json,
            "evidence_ids": row.evidence_json,
            "policy_snapshot_hash": row.policy_snapshot_hash,
            "requested_by": row.requested_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }
