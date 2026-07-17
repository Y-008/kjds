from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base


class ExecutionObservationWindowRow(Base):
    __tablename__ = "execution_observation_windows"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    command_id: Mapped[str] = mapped_column(
        ForeignKey("limited_execution_commands.id"), unique=True, nullable=False
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("governed_execution_plans.id"), nullable=False
    )
    policy_id: Mapped[str] = mapped_column(ForeignKey("causal_policies.id"), nullable=False)
    primary_metric: Mapped[str] = mapped_column(String, nullable=False)
    baseline_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    guardrails_json: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    required_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionMetricObservationRow(Base):
    __tablename__ = "execution_metric_observations"
    __table_args__ = (
        UniqueConstraint(
            "window_id",
            "metric",
            "observed_at",
            name="uq_execution_metric_observation",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    window_id: Mapped[str] = mapped_column(
        ForeignKey("execution_observation_windows.id"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PostExecutionService:
    def __init__(
        self,
        *,
        engine,
        limited_executor,
        execution_plans,
        policies,
        evidence,
        kill_switch,
    ) -> None:
        self.engine = engine
        self.limited_executor = limited_executor
        self.execution_plans = execution_plans
        self.policies = policies
        self.evidence = evidence
        self.kill_switch = kill_switch

    def create_window(
        self,
        command_id: str,
        *,
        primary_metric: str,
        baseline: dict[str, Any],
        required_observations: int,
        starts_at: str,
        ends_at: str,
        evidence_ids: list[str],
        created_by: str,
    ) -> dict[str, Any]:
        command = self.limited_executor.get(command_id)
        if command["command_kind"] != "execute" or command["status"] != "succeeded":
            raise ValueError("Observation window requires a confirmed successful execution")
        if command["receipt"] is None or not command["receipt"]["mutation_applied"]:
            raise ValueError("Observation window requires a confirmed platform mutation")
        if self._rollback_for(command["plan_id"]):
            raise ValueError("Observation window cannot start after rollback has been queued")
        plan = self.execution_plans.get(command["plan_id"])
        policy = self.policies.get(plan["policy_id"])
        if not policy["usable"]:
            raise ValueError("Observation window requires a currently usable policy")
        primary_metric = self._required(primary_metric, "Primary observation metric")
        created_by = self._required(created_by, "Observation owner")
        baseline = self._baseline(baseline)
        guardrail_metrics = {item["metric"] for item in policy["guardrails"]}
        required_metrics = guardrail_metrics | {primary_metric}
        if missing := required_metrics - set(baseline):
            raise ValueError(f"Observation baseline is missing: {', '.join(sorted(missing))}")
        if not 1 <= required_observations <= 10000:
            raise ValueError("Required observations must be between 1 and 10000")
        starts_at_dt = self._datetime(starts_at, "starts_at")
        ends_at_dt = self._datetime(ends_at, "ends_at")
        if ends_at_dt <= starts_at_dt:
            raise ValueError("Observation window end must be after its start")
        evidence_ids = self._evidence(evidence_ids)
        canonical = {
            "command_id": command_id,
            "plan_id": plan["id"],
            "policy_id": policy["id"],
            "primary_metric": primary_metric,
            "baseline": baseline,
            "guardrails": policy["guardrails"],
            "required_observations": required_observations,
            "starts_at": starts_at_dt.isoformat(),
            "ends_at": ends_at_dt.isoformat(),
            "evidence_ids": evidence_ids,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(ExecutionObservationWindowRow).where(
                    ExecutionObservationWindowRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self.get_window(exact.id)
            previous = session.scalar(
                select(ExecutionObservationWindowRow).where(
                    ExecutionObservationWindowRow.command_id == command_id
                )
            )
            if previous is not None:
                raise ValueError("Execution already has an immutable observation window")
            row = ExecutionObservationWindowRow(
                id=new_id("eow"),
                request_hash=request_hash,
                command_id=command_id,
                plan_id=plan["id"],
                policy_id=policy["id"],
                primary_metric=primary_metric,
                baseline_json=baseline,
                guardrails_json=policy["guardrails"],
                required_observations=required_observations,
                starts_at=starts_at_dt,
                ends_at=ends_at_dt,
                evidence_json=evidence_ids,
                status="monitoring",
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            window_id = row.id
        self._link(evidence_ids, "execution_observation_window", window_id, created_by)
        return self.get_window(window_id)

    def observe(
        self,
        window_id: str,
        *,
        metric: str,
        value: Any,
        observed_at: str,
        evidence_ids: list[str],
        created_by: str,
    ) -> dict[str, Any]:
        window = self.get_window(window_id)
        metric = self._required(metric, "Metric")
        allowed_metrics = {window["primary_metric"]} | {
            item["metric"] for item in window["guardrails"]
        }
        if metric not in allowed_metrics:
            raise ValueError("Metric is outside the preregistered observation contract")
        decimal_value = self._decimal(value, "Metric value")
        observed_at_dt = self._datetime(observed_at, "observed_at")
        if not self._datetime(window["starts_at"], "starts_at") <= observed_at_dt <= self._datetime(
            window["ends_at"], "ends_at"
        ):
            raise ValueError("Metric observation is outside the preregistered window")
        evidence_ids = self._evidence(evidence_ids)
        created_by = self._required(created_by, "Metric observer")
        canonical = {
            "window_id": window_id,
            "metric": metric,
            "value": str(decimal_value),
            "observed_at": observed_at_dt.isoformat(),
            "evidence_ids": evidence_ids,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        exact_result = None
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(ExecutionMetricObservationRow).where(
                    ExecutionMetricObservationRow.request_hash == request_hash
                )
            )
            if exact is not None:
                exact_result = self._observation(exact, False, None)
            if exact_result is not None:
                observation_id = exact.id
            else:
                if window["status"] != "monitoring":
                    raise ValueError("Observation window is no longer accepting metrics")
                previous = session.scalar(
                    select(ExecutionMetricObservationRow).where(
                        ExecutionMetricObservationRow.window_id == window_id,
                        ExecutionMetricObservationRow.metric == metric,
                        ExecutionMetricObservationRow.observed_at == observed_at_dt,
                    )
                )
                if previous is not None:
                    raise ValueError("Metric timestamp already has immutable content")
                row = ExecutionMetricObservationRow(
                    id=new_id("emo"),
                    request_hash=request_hash,
                    window_id=window_id,
                    metric=metric,
                    value=str(decimal_value),
                    observed_at=observed_at_dt,
                    evidence_json=evidence_ids,
                    created_by=created_by,
                    created_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                observation_id = row.id
        if exact_result is not None:
            breached = self._breached(window["guardrails"], metric, decimal_value)
            rollback_id = self._rollback_for(window["plan_id"]) if breached else None
            return {
                **exact_result,
                "guardrail_breached": breached,
                "rollback_command_id": rollback_id,
            }
        self._link(evidence_ids, "execution_metric_observation", observation_id, created_by)
        breached = self._breached(window["guardrails"], metric, decimal_value)
        rollback_id = None
        if breached:
            rollback = self.limited_executor.request_rollback(
                window["command_id"], requested_by="post-execution-guardrail"
            )
            rollback_id = rollback["id"]
            with Session(self.engine) as session, session.begin():
                row = session.get(ExecutionObservationWindowRow, window_id, with_for_update=True)
                if row is not None:
                    row.status = "guardrail_breached"
            self.kill_switch.set_state(
                engaged=True,
                reason=f"Post-execution guardrail breached: {window_id}:{metric}",
                actor_id="post-execution-guardrail",
            )
        with Session(self.engine) as session:
            row = session.get(ExecutionMetricObservationRow, observation_id)
            if row is None:
                raise RuntimeError("Metric observation disappeared after commit")
            return self._observation(row, breached, rollback_id)

    def evaluate(self, window_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        window = self.get_window(window_id)
        as_of_dt = self._datetime(as_of, "as_of") if as_of else datetime.now(UTC)
        observations = window["observations"]
        primary = [
            Decimal(item["value"])
            for item in observations
            if item["metric"] == window["primary_metric"]
        ]
        baseline = Decimal(window["baseline"][window["primary_metric"]])
        latest = primary[-1] if primary else None
        if window["status"] == "guardrail_breached":
            status = "guardrail_breached"
        elif as_of_dt <= self._datetime(window["ends_at"], "ends_at"):
            status = "monitoring"
        elif len(observations) < window["required_observations"]:
            status = "insufficient_observations"
        else:
            status = "passed"
        return {
            "window_id": window_id,
            "status": status,
            "observation_count": len(observations),
            "required_observations": window["required_observations"],
            "primary_metric": window["primary_metric"],
            "baseline_value": str(baseline),
            "latest_value": str(latest) if latest is not None else None,
            "absolute_change": str(latest - baseline) if latest is not None else None,
            "rollback_queued": bool(self._rollback_for(window["plan_id"])),
            "kill_switch_engaged": self.kill_switch.current().engaged,
            "automatic_policy_promotion": False,
        }

    def list_windows(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    select(ExecutionObservationWindowRow.id).order_by(
                        ExecutionObservationWindowRow.created_at
                    )
                )
            )
        return [self.get_window(item_id) for item_id in ids]

    def get_window(self, window_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(ExecutionObservationWindowRow, window_id)
            if row is None:
                raise KeyError(f"Execution observation window not found: {window_id}")
            observations = list(
                session.scalars(
                    select(ExecutionMetricObservationRow)
                    .where(ExecutionMetricObservationRow.window_id == window_id)
                    .order_by(
                        ExecutionMetricObservationRow.observed_at,
                        ExecutionMetricObservationRow.created_at,
                    )
                )
            )
            return self._window(row, observations)

    def _rollback_for(self, plan_id: str) -> str | None:
        return next(
            (
                item["id"]
                for item in self.limited_executor.list()
                if item["plan_id"] == plan_id and item["command_kind"] == "rollback"
            ),
            None,
        )

    @staticmethod
    def _breached(guardrails: list[dict[str, str]], metric: str, value: Decimal) -> bool:
        for guardrail in guardrails:
            if guardrail["metric"] != metric:
                continue
            threshold = Decimal(guardrail["threshold"])
            return value > threshold if guardrail["direction"] == "max" else value < threshold
        return False

    @classmethod
    def _baseline(cls, value: dict[str, Any]) -> dict[str, str]:
        if not isinstance(value, dict) or not value:
            raise ValueError("Observation baseline must be structured")
        return {
            cls._required(str(metric), "Baseline metric"): str(
                cls._decimal(metric_value, "Baseline value")
            )
            for metric, metric_value in value.items()
        }

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
    def _decimal(value: Any, name: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be decimal") from exc
        if not parsed.is_finite():
            raise ValueError(f"{name} must be finite")
        return parsed

    @staticmethod
    def _datetime(value: str, name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
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
    def _window(
        cls,
        row: ExecutionObservationWindowRow,
        observations: list[ExecutionMetricObservationRow],
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "command_id": row.command_id,
            "plan_id": row.plan_id,
            "policy_id": row.policy_id,
            "primary_metric": row.primary_metric,
            "baseline": row.baseline_json,
            "guardrails": row.guardrails_json,
            "required_observations": row.required_observations,
            "starts_at": cls._iso(row.starts_at),
            "ends_at": cls._iso(row.ends_at),
            "evidence_ids": row.evidence_json,
            "status": row.status,
            "created_by": row.created_by,
            "created_at": cls._iso(row.created_at),
            "observations": [cls._observation(item, False, None) for item in observations],
            "immutable_contract": True,
            "automatic_policy_promotion": False,
        }

    @classmethod
    def _observation(
        cls,
        row: ExecutionMetricObservationRow,
        breached: bool,
        rollback_command_id: str | None,
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "window_id": row.window_id,
            "metric": row.metric,
            "value": row.value,
            "observed_at": cls._iso(row.observed_at),
            "evidence_ids": row.evidence_json,
            "created_by": row.created_by,
            "created_at": cls._iso(row.created_at),
            "guardrail_breached": breached,
            "rollback_command_id": rollback_command_id,
            "immutable": True,
        }
