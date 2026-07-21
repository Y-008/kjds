from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

ExperimentEvent = Literal["started", "paused", "resumed", "stopped", "completed"]


class ExperimentProtocolRow(Base):
    __tablename__ = "causal_experiment_protocols"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    resolution_id: Mapped[str] = mapped_column(
        ForeignKey("decision_resolutions.id"), unique=True, nullable=False
    )
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    primary_metric: Mapped[str] = mapped_column(String, nullable=False)
    randomization_unit: Mapped[str] = mapped_column(String, nullable=False)
    interference_cluster: Mapped[str | None] = mapped_column(String, nullable=True)
    variants_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    target_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_detectable_effect_decimal: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    budget_cap_amount_decimal: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    stop_loss_amount_decimal: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    guardrails_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    stratification_keys_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    effect_metrics_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    assignment_seed: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentProtocolEventRow(Base):
    __tablename__ = "causal_experiment_events"
    __table_args__ = (
        UniqueConstraint(
            "protocol_id",
            "sequence",
            name="uq_causal_experiment_event_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    protocol_id: Mapped[str] = mapped_column(
        ForeignKey("causal_experiment_protocols.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentAssignmentRow(Base):
    __tablename__ = "causal_experiment_assignments"
    __table_args__ = (
        UniqueConstraint(
            "protocol_id",
            "unit_hash",
            name="uq_causal_experiment_unit",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    protocol_id: Mapped[str] = mapped_column(
        ForeignKey("causal_experiment_protocols.id"), nullable=False
    )
    unit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    variant_id: Mapped[str] = mapped_column(String, nullable=False)
    strata_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentObservationRow(Base):
    __tablename__ = "causal_experiment_observations"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "metric",
            name="uq_causal_experiment_assignment_metric",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    protocol_id: Mapped[str] = mapped_column(
        ForeignKey("causal_experiment_protocols.id"), nullable=False
    )
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("causal_experiment_assignments.id"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value_decimal: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentSafetyCheckRow(Base):
    __tablename__ = "causal_experiment_safety_checks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    protocol_id: Mapped[str] = mapped_column(
        ForeignKey("causal_experiment_protocols.id"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value_decimal: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    threshold_decimal: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CausalExperimentService:
    def __init__(self, *, engine, decisions, evidence) -> None:
        self.engine = engine
        self.decisions = decisions
        self.evidence = evidence

    def register(
        self,
        resolution_id: str,
        *,
        hypothesis: str,
        primary_metric: str,
        randomization_unit: str,
        variants: list[dict[str, Any]],
        target_sample_size: int,
        minimum_detectable_effect: Decimal,
        budget_cap_amount: Decimal,
        stop_loss_amount: Decimal,
        currency: str,
        start_at: str,
        end_at: str,
        guardrails: list[dict[str, Any]],
        evidence_ids: list[str],
        created_by: str,
        interference_cluster: str | None = None,
        outcome_window_days: int = 30,
        stratification_keys: list[str] | None = None,
        effect_metrics: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        resolution = self.decisions.get_resolution(resolution_id)
        if resolution["disposition"] != "experiment":
            raise ValueError("Only a formal experiment resolution can register a protocol")
        hypothesis = hypothesis.strip()
        primary_metric = primary_metric.strip()
        randomization_unit = randomization_unit.strip().lower()
        created_by = created_by.strip()
        if not all((hypothesis, primary_metric, randomization_unit, created_by)):
            raise ValueError("Experiment requires hypothesis, metric, unit, and owner")
        variants = self._variants(variants)
        if target_sample_size < 20:
            raise ValueError("Target sample size must be at least 20")
        mde = self._finite_decimal(minimum_detectable_effect, "Minimum detectable effect")
        budget = self._finite_decimal(budget_cap_amount, "Budget cap")
        stop_loss = self._finite_decimal(stop_loss_amount, "Stop loss")
        if mde <= 0 or budget <= 0 or stop_loss <= 0 or stop_loss > budget:
            raise ValueError("Experiment requires positive MDE and a stop loss within budget")
        currency = currency.strip().upper()
        if len(currency) != 3 or not all("A" <= char <= "Z" for char in currency):
            raise ValueError("Currency must be a three-letter code")
        start = self._datetime(start_at, "start_at")
        end = self._datetime(end_at, "end_at")
        if end <= start:
            raise ValueError("Experiment end must be after start")
        if not 0 <= outcome_window_days <= 365:
            raise ValueError("Outcome window must be between 0 and 365 days")
        evidence_ids = self._evidence(evidence_ids)
        guardrails = self._guardrails(guardrails)
        stratification_keys = self._stratification_keys(stratification_keys or [])
        effect_metrics = self._effect_metric_contract(
            primary_metric, effect_metrics or []
        )
        interference_cluster = (
            interference_cluster.strip().lower() if interference_cluster else None
        )
        canonical = {
            "resolution_id": resolution_id,
            "hypothesis": hypothesis,
            "primary_metric": primary_metric,
            "randomization_unit": randomization_unit,
            "interference_cluster": interference_cluster,
            "variants": variants,
            "target_sample_size": target_sample_size,
            "minimum_detectable_effect": str(mde),
            "budget_cap_amount": str(budget),
            "stop_loss_amount": str(stop_loss),
            "currency": currency,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "outcome_window_days": outcome_window_days,
            "guardrails": guardrails,
            "stratification_keys": stratification_keys,
            "effect_metrics": effect_metrics,
            "evidence_ids": evidence_ids,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        existing_id: str | None = None
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(ExperimentProtocolRow).where(
                    ExperimentProtocolRow.request_hash == request_hash
                )
            )
            if exact is not None:
                existing_id = exact.id
            if existing_id is not None:
                pass
            else:
                existing = session.scalar(
                    select(ExperimentProtocolRow).where(
                        ExperimentProtocolRow.resolution_id == resolution_id
                    )
                )
                if existing is not None:
                    raise ValueError(
                        "Resolution already has an immutable experiment protocol"
                    )
                row = ExperimentProtocolRow(
                    id=new_id("xpt"),
                    request_hash=request_hash,
                    resolution_id=resolution_id,
                    hypothesis=hypothesis,
                    primary_metric=primary_metric,
                    randomization_unit=randomization_unit,
                    interference_cluster=interference_cluster,
                    variants_json=variants,
                    target_sample_size=target_sample_size,
                    minimum_detectable_effect_decimal=mde,
                    budget_cap_amount_decimal=budget,
                    stop_loss_amount_decimal=stop_loss,
                    currency=currency,
                    start_at=start,
                    end_at=end,
                    outcome_window_days=outcome_window_days,
                    guardrails_json=guardrails,
                    stratification_keys_json=stratification_keys,
                    effect_metrics_json=effect_metrics,
                    assignment_seed=secrets.token_hex(32),
                    evidence_json=evidence_ids,
                    created_by=created_by,
                    created_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                existing_id = row.id
        if existing_id is None:
            raise RuntimeError("Experiment protocol persistence failed")
        result = self.get(existing_id)
        if result["evidence_ids"] != evidence_ids:
            raise RuntimeError("Idempotent protocol payload mismatch")
        self._link_many(evidence_ids, "causal_experiment_protocol", result["id"], created_by)
        return result

    def transition(
        self,
        protocol_id: str,
        *,
        event_type: ExperimentEvent,
        effective_at: str,
        evidence_id: str,
        reason: str,
        created_by: str,
    ) -> dict[str, Any]:
        if event_type not in {"started", "paused", "resumed", "stopped", "completed"}:
            raise ValueError("Unknown experiment lifecycle event")
        effective = self._datetime(effective_at, "effective_at")
        reason = reason.strip()
        created_by = created_by.strip()
        if not reason or not created_by:
            raise ValueError("Experiment event requires reason and actor")
        self.evidence.require_valid([evidence_id])
        canonical = {
            "protocol_id": protocol_id,
            "event_type": event_type,
            "effective_at": effective.isoformat(),
            "evidence_id": evidence_id,
            "reason": reason,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session:
            exact = session.scalar(
                select(ExperimentProtocolEventRow).where(
                    ExperimentProtocolEventRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self.get(protocol_id)

        protocol = self.get(protocol_id)
        transitions = {
            "registered": {"started"},
            "running": {"paused", "stopped", "completed"},
            "paused": {"resumed", "stopped", "completed"},
            "stopped": set(),
            "completed": set(),
        }
        if event_type not in transitions[protocol["status"]]:
            raise ValueError(
                f"Cannot record {event_type} while experiment is {protocol['status']}"
            )
        if event_type == "started" and not (
            self._datetime(protocol["start_at"], "start_at")
            <= effective
            <= self._datetime(protocol["end_at"], "end_at")
        ):
            raise ValueError("Experiment must start inside its preregistered time window")
        if protocol["events"]:
            previous = self._datetime(
                protocol["events"][-1]["effective_at"], "previous effective_at"
            )
            if effective < previous:
                raise ValueError("Experiment lifecycle events must be chronological")
        with Session(self.engine) as session, session.begin():
            sequence = len(protocol["events"]) + 1
            row = ExperimentProtocolEventRow(
                id=new_id("xev"),
                request_hash=request_hash,
                protocol_id=protocol_id,
                sequence=sequence,
                event_type=event_type,
                effective_at=effective,
                evidence_id=evidence_id,
                reason=reason,
                created_by=created_by,
                recorded_at=datetime.now(UTC),
            )
            session.add(row)
        self.evidence.link(
            evidence_id=evidence_id,
            target_type="causal_experiment_event",
            target_id=protocol_id,
            relationship=event_type,
            created_by=created_by,
        )
        return self.get(protocol_id)

    def assign(
        self,
        protocol_id: str,
        *,
        unit_key: str,
        assigned_at: str,
        strata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        with Session(self.engine) as lookup_session:
            protocol_row = lookup_session.get(ExperimentProtocolRow, protocol_id)
            if protocol_row is None:
                raise KeyError(f"Unknown causal experiment protocol: {protocol_id}")
            seed = protocol_row.assignment_seed
        protocol = self.get(protocol_id)
        unit_key = unit_key.strip()
        if not unit_key:
            raise ValueError("Randomization unit key is required")
        assigned = self._datetime(assigned_at, "assigned_at")
        strata = self._strata(protocol["stratification_keys"], strata or {})
        unit_hash = hmac.new(
            seed.encode(),
            unit_key.encode(),
            hashlib.sha256,
        ).hexdigest()
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(ExperimentAssignmentRow).where(
                    ExperimentAssignmentRow.protocol_id == protocol_id,
                    ExperimentAssignmentRow.unit_hash == unit_hash,
                )
            )
            if existing is not None:
                if existing.strata_json != strata:
                    raise ValueError("Randomization unit already has immutable strata")
                return self._assignment(existing)
            if protocol["status"] != "running":
                raise ValueError("Experiment assignments require running status")
            safety_breach = session.scalar(
                select(ExperimentSafetyCheckRow.id).where(
                    ExperimentSafetyCheckRow.protocol_id == protocol_id,
                    ExperimentSafetyCheckRow.status == "breached",
                )
            )
            if safety_breach is not None:
                raise ValueError(
                    "Experiment safety gate is breached; new assignments are blocked"
                )
            if not (
                self._datetime(protocol["start_at"], "start_at")
                <= assigned
                <= self._datetime(protocol["end_at"], "end_at")
            ):
                raise ValueError("Assignment is outside the preregistered experiment window")
            bucket = int(
                hmac.new(
                    seed.encode(),
                    f"variant:{unit_key}".encode(),
                    hashlib.sha256,
                ).hexdigest(),
                16,
            ) / (2**256)
            cumulative = Decimal("0")
            chosen = protocol["variants"][-1]["id"]
            for variant in protocol["variants"]:
                cumulative += Decimal(variant["allocation"])
                if Decimal(str(bucket)) < cumulative:
                    chosen = variant["id"]
                    break
            row = ExperimentAssignmentRow(
                id=new_id("xas"),
                protocol_id=protocol_id,
                unit_hash=unit_hash,
                variant_id=chosen,
                strata_json=strata,
                assigned_at=assigned,
            )
            session.add(row)
            session.flush()
            return self._assignment(row)

    def observe(
        self,
        assignment_id: str,
        *,
        value: Decimal,
        observed_at: str,
        evidence_id: str,
        created_by: str,
        metric: str | None = None,
    ) -> dict[str, Any]:
        assignment = self.get_assignment(assignment_id)
        protocol = self.get(assignment["protocol_id"])
        observed = self._datetime(observed_at, "observed_at")
        assignment_time = self._datetime(assignment["assigned_at"], "assigned_at")
        outcome_deadline = self._datetime(protocol["end_at"], "end_at") + timedelta(
            days=protocol["outcome_window_days"]
        )
        if observed < assignment_time or observed > outcome_deadline:
            raise ValueError("Observation is outside the assignment/outcome window")
        self.evidence.require_valid([evidence_id])
        created_by = created_by.strip()
        if not created_by:
            raise ValueError("Observation recording identity is required")
        metric = (metric or protocol["primary_metric"]).strip()
        allowed_metrics = {item["metric"] for item in protocol["effect_metrics"]}
        if metric not in allowed_metrics:
            raise ValueError("Metric is not part of the preregistered effect model")
        numeric_value = self._finite_decimal(value, "Observation value")
        canonical = {
            "assignment_id": assignment_id,
            "metric": metric,
            "value": str(numeric_value),
            "observed_at": observed.isoformat(),
            "evidence_id": evidence_id,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(ExperimentObservationRow).where(
                    ExperimentObservationRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._observation(exact)
            existing = session.scalar(
                select(ExperimentObservationRow).where(
                    ExperimentObservationRow.assignment_id == assignment_id,
                    ExperimentObservationRow.metric == metric,
                )
            )
            if existing is not None:
                raise ValueError("Assignment already has an immutable primary outcome")
            row = ExperimentObservationRow(
                id=new_id("xob"),
                request_hash=request_hash,
                protocol_id=protocol["id"],
                assignment_id=assignment_id,
                metric=metric,
                value_decimal=numeric_value,
                observed_at=observed,
                evidence_id=evidence_id,
                created_by=created_by,
                recorded_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._observation(row)
        self.evidence.link(
            evidence_id=evidence_id,
            target_type="causal_experiment_observation",
            target_id=result["id"],
            relationship="observes_primary_metric",
            created_by=created_by,
        )
        return result

    def record_safety_check(
        self,
        protocol_id: str,
        *,
        metric: str,
        value: Decimal,
        observed_at: str,
        evidence_id: str,
        created_by: str,
    ) -> dict[str, Any]:
        protocol = self.get(protocol_id)
        metric = metric.strip()
        created_by = created_by.strip()
        if not metric or not created_by:
            raise ValueError("Safety check requires metric and recording identity")
        numeric_value = self._finite_decimal(value, "Safety check value")
        direction, threshold = self._safety_threshold(protocol, metric)
        if metric in {"budget_spend_amount", "cumulative_loss_amount"} and numeric_value < 0:
            raise ValueError("Budget spend and cumulative loss must be non-negative")
        observed = self._datetime(observed_at, "observed_at")
        deadline = self._datetime(protocol["end_at"], "end_at") + timedelta(
            days=protocol["outcome_window_days"]
        )
        if observed < self._datetime(protocol["start_at"], "start_at") or observed > deadline:
            raise ValueError("Safety check is outside the experiment/outcome window")
        self.evidence.require_valid([evidence_id])
        breached = (
            numeric_value > threshold if direction == "max" else numeric_value < threshold
        )
        canonical = {
            "protocol_id": protocol_id,
            "metric": metric,
            "value": str(numeric_value),
            "direction": direction,
            "threshold": str(threshold),
            "status": "breached" if breached else "within_limit",
            "observed_at": observed.isoformat(),
            "evidence_id": evidence_id,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(ExperimentSafetyCheckRow).where(
                    ExperimentSafetyCheckRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._safety_check(exact)
            row = ExperimentSafetyCheckRow(
                id=new_id("xsc"),
                request_hash=request_hash,
                protocol_id=protocol_id,
                metric=metric,
                value_decimal=numeric_value,
                direction=direction,
                threshold_decimal=threshold,
                status="breached" if breached else "within_limit",
                observed_at=observed,
                evidence_id=evidence_id,
                created_by=created_by,
                recorded_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._safety_check(row)
        self.evidence.link(
            evidence_id=evidence_id,
            target_type="causal_experiment_safety_check",
            target_id=result["id"],
            relationship="measures_guardrail",
            created_by=created_by,
        )
        return result

    def evaluate(self, protocol_id: str) -> dict[str, Any]:
        protocol = self.get(protocol_id)
        with Session(self.engine) as session:
            assignments = list(
                session.scalars(
                    select(ExperimentAssignmentRow).where(
                        ExperimentAssignmentRow.protocol_id == protocol_id
                    )
                )
            )
            observations = list(
                session.scalars(
                    select(ExperimentObservationRow).where(
                        ExperimentObservationRow.protocol_id == protocol_id
                    )
                )
            )
            safety_checks = list(
                session.scalars(
                    select(ExperimentSafetyCheckRow)
                    .where(ExperimentSafetyCheckRow.protocol_id == protocol_id)
                    .order_by(
                        ExperimentSafetyCheckRow.observed_at,
                        ExperimentSafetyCheckRow.recorded_at,
                        ExperimentSafetyCheckRow.id,
                    )
                )
            )
        variant_counts = {
            variant["id"]: sum(1 for item in assignments if item.variant_id == variant["id"])
            for variant in protocol["variants"]
        }
        total_assignments = len(assignments)
        chi_square = Decimal("0")
        if total_assignments:
            for variant in protocol["variants"]:
                expected = Decimal(total_assignments) * Decimal(variant["allocation"])
                if expected > 0:
                    chi_square += (
                        Decimal(variant_counts[variant["id"]]) - expected
                    ) ** 2 / expected
        srm_p_value = math.erfc(math.sqrt(float(chi_square) / 2)) if total_assignments else 1.0

        assignment_variants = {item.id: item.variant_id for item in assignments}
        control = next(item for item in protocol["variants"] if item["control"])
        treatment = next(item for item in protocol["variants"] if not item["control"])
        metric_results = []
        missing_required_metrics = []
        for metric_contract in protocol["effect_metrics"]:
            metric = metric_contract["metric"]
            metric_values = {
                variant["id"]: [
                    Decimal(item.value_decimal)
                    for item in observations
                    if item.metric == metric
                    and assignment_variants.get(item.assignment_id) == variant["id"]
                ]
                for variant in protocol["variants"]
            }
            metric_summaries = {
                variant["id"]: self._summary(metric_values[variant["id"]])
                for variant in protocol["variants"]
            }
            metric_effect = self._effect(
                metric_values[control["id"]], metric_values[treatment["id"]]
            )
            metric_observed = sum(len(items) for items in metric_values.values())
            if metric_contract["required"] and (
                metric_observed < protocol["target_sample_size"]
                or metric_effect is None
            ):
                missing_required_metrics.append(metric)
            metric_results.append(
                {
                    **metric_contract,
                    "observed_count": metric_observed,
                    "variant_summaries": metric_summaries,
                    "effect": metric_effect,
                }
            )
        primary_result = next(
            item for item in metric_results if item["role"] == "primary"
        )
        effect = primary_result["effect"]
        observed_count = primary_result["observed_count"]
        incremental_value = None
        if not missing_required_metrics:
            incremental_value = sum(
                (
                    Decimal(item["effect"]["absolute_effect"])
                    * Decimal(item["multiplier"])
                )
                for item in metric_results
                if item["required"] and item["effect"] is not None
            )
        heterogeneous_effects = self._heterogeneous_effects(
            assignments=assignments,
            observations=observations,
            metric=protocol["primary_metric"],
            stratification_keys=protocol["stratification_keys"],
            control_id=control["id"],
            treatment_id=treatment["id"],
        )
        safety_breaches = [item for item in safety_checks if item.status == "breached"]
        if safety_breaches:
            status = "safety_breach"
        elif total_assignments >= 20 and srm_p_value < 0.01:
            status = "invalid_sample_ratio"
        elif observed_count < protocol["target_sample_size"]:
            status = "insufficient_samples"
        elif effect is None:
            status = "insufficient_variance"
        elif missing_required_metrics:
            status = "incomplete_value_model"
        else:
            status = "ready_for_independent_review"
        return {
            "protocol_id": protocol_id,
            "status": status,
            "review_eligible": status == "ready_for_independent_review",
            "decision_eligible": False,
            "automatic_rollout": False,
            "assignment_count": total_assignments,
            "observed_count": observed_count,
            "target_sample_size": protocol["target_sample_size"],
            "variant_assignment_counts": variant_counts,
            "sample_ratio_chi_square": str(chi_square),
            "sample_ratio_p_value": str(srm_p_value),
            "sample_ratio_mismatch": total_assignments >= 20 and srm_p_value < 0.01,
            "safety_gate_breached": bool(safety_breaches),
            "safety_checks": [self._safety_check(item) for item in safety_checks],
            "variant_summaries": primary_result["variant_summaries"],
            "treatment_effect": effect,
            "effect_metric_results": metric_results,
            "missing_required_metrics": missing_required_metrics,
            "incremental_value_per_unit": (
                str(incremental_value) if incremental_value is not None else None
            ),
            "heterogeneous_effects": heterogeneous_effects,
            "minimum_detectable_effect": protocol["minimum_detectable_effect"],
            "guardrails": protocol["guardrails"],
            "interpretation": (
                "SAFETY_BREACH_FREEZES_ASSIGNMENT"
                if status == "safety_breach"
                else "SRM_BLOCKS_DECISION"
                if status == "invalid_sample_ratio"
                else "RESULT_REQUIRES_INDEPENDENT_REVIEW"
                if status == "ready_for_independent_review"
                else "KEEP_COLLECTING_PREREGISTERED_SAMPLE"
            ),
        }

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ExperimentProtocolRow).order_by(
                        ExperimentProtocolRow.created_at.desc(),
                        ExperimentProtocolRow.id,
                    )
                )
            )
            events = list(
                session.scalars(
                    select(ExperimentProtocolEventRow).order_by(
                        ExperimentProtocolEventRow.protocol_id,
                        ExperimentProtocolEventRow.sequence,
                    )
                )
            )
        grouped: dict[str, list[ExperimentProtocolEventRow]] = {}
        for event in events:
            grouped.setdefault(event.protocol_id, []).append(event)
        return [
            self._protocol(row, self._status(grouped.get(row.id, [])), grouped.get(row.id, []))
            for row in rows
        ]

    def get(self, protocol_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(ExperimentProtocolRow, protocol_id)
            if row is None:
                raise KeyError(f"Unknown causal experiment protocol: {protocol_id}")
            events = list(
                session.scalars(
                    select(ExperimentProtocolEventRow)
                    .where(ExperimentProtocolEventRow.protocol_id == protocol_id)
                    .order_by(ExperimentProtocolEventRow.sequence)
                )
            )
            return self._protocol(row, self._status(events), events)

    def get_assignment(self, assignment_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(ExperimentAssignmentRow, assignment_id)
            if row is None:
                raise KeyError(f"Unknown experiment assignment: {assignment_id}")
            return self._assignment(row)

    @staticmethod
    def _safety_threshold(
        protocol: dict[str, Any], metric: str
    ) -> tuple[str, Decimal]:
        if metric == "budget_spend_amount":
            return "max", Decimal(protocol["budget_cap_amount"])
        if metric == "cumulative_loss_amount":
            return "max", Decimal(protocol["stop_loss_amount"])
        guardrail = next(
            (item for item in protocol["guardrails"] if item["metric"] == metric),
            None,
        )
        if guardrail is None:
            raise ValueError("Metric is not a preregistered safety guardrail")
        return guardrail["direction"], Decimal(guardrail["threshold"])

    @staticmethod
    def _variants(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(values) != 2:
            raise ValueError("MVP causal experiments require exactly two variants")
        result = []
        ids = set()
        for item in values:
            variant_id = str(item.get("id", "")).strip()
            label = str(item.get("label", "")).strip()
            allocation = CausalExperimentService._finite_decimal(
                item.get("allocation", "0"), "Variant allocation"
            )
            control_value = item.get("control", False)
            if not isinstance(control_value, bool):
                raise ValueError("Variant control flag must be boolean")
            control = control_value
            if not variant_id or not label or allocation <= 0:
                raise ValueError("Variant requires id, label, and positive allocation")
            if variant_id in ids:
                raise ValueError("Variant ids must be unique")
            ids.add(variant_id)
            result.append(
                {
                    "id": variant_id,
                    "label": label,
                    "allocation": str(allocation),
                    "control": control,
                }
            )
        if sum((Decimal(item["allocation"]) for item in result), Decimal("0")) != Decimal("1"):
            raise ValueError("Variant allocations must sum to exactly 1")
        if sum(1 for item in result if item["control"]) != 1:
            raise ValueError("Exactly one variant must be the control")
        return result

    @staticmethod
    def _stratification_keys(values: list[str]) -> list[str]:
        result = []
        for value in values:
            key = value.strip().lower()
            if not key:
                continue
            if key in result:
                raise ValueError("Stratification keys must be unique")
            result.append(key)
        if len(result) > 3:
            raise ValueError("At most three preregistered stratification keys are allowed")
        return result

    @staticmethod
    def _effect_metric_contract(
        primary_metric: str, values: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result = [
            {
                "metric": primary_metric,
                "role": "primary",
                "multiplier": "1",
                "required": True,
            }
        ]
        allowed_roles = {
            "cannibalization",
            "long_term_cost",
            "long_term_value",
            "secondary",
        }
        for item in values:
            metric = str(item.get("metric", "")).strip()
            role = str(item.get("role", "")).strip().lower()
            multiplier = CausalExperimentService._finite_decimal(
                item.get("multiplier", "0"), "Effect metric multiplier"
            )
            required_value = item.get("required", True)
            if not metric or role not in allowed_roles or multiplier == 0:
                raise ValueError(
                    "Effect metric requires metric, supported role, and non-zero multiplier"
                )
            if not isinstance(required_value, bool):
                raise ValueError("Effect metric required flag must be boolean")
            if metric in {row["metric"] for row in result}:
                raise ValueError("Effect metrics must be unique")
            if role in {"cannibalization", "long_term_cost"} and multiplier >= 0:
                raise ValueError("Cost and cannibalization multipliers must be negative")
            if role == "long_term_value" and multiplier <= 0:
                raise ValueError("Long-term value multiplier must be positive")
            result.append(
                {
                    "metric": metric,
                    "role": role,
                    "multiplier": str(multiplier),
                    "required": required_value,
                }
            )
        return result

    @staticmethod
    def _strata(keys: list[str], values: dict[str, str]) -> dict[str, str]:
        normalized = {
            str(key).strip().lower(): str(value).strip()
            for key, value in values.items()
        }
        if set(normalized) != set(keys) or any(not value for value in normalized.values()):
            raise ValueError("Assignment strata must exactly match preregistered keys")
        return {key: normalized[key] for key in keys}

    @staticmethod
    def _guardrails(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for item in values:
            metric = str(item.get("metric", "")).strip()
            direction = str(item.get("direction", "")).strip().lower()
            threshold = item.get("threshold")
            if not metric or direction not in {"max", "min"} or threshold is None:
                raise ValueError("Guardrail requires metric, min/max direction, and threshold")
            numeric_threshold = CausalExperimentService._finite_decimal(
                threshold, "Guardrail threshold"
            )
            result.append(
                {
                    "metric": metric,
                    "direction": direction,
                    "threshold": str(numeric_threshold),
                }
            )
        if not result:
            raise ValueError("Experiment requires at least one preregistered guardrail")
        return result

    @staticmethod
    def _finite_decimal(value: object, name: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a finite number") from exc
        if not parsed.is_finite():
            raise ValueError(f"{name} must be a finite number")
        return parsed

    def _evidence(self, values: list[str]) -> list[str]:
        result = sorted({item.strip() for item in values if item.strip()})
        self.evidence.require_valid(result)
        return result

    @staticmethod
    def _datetime(value: str, name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 datetime") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()

    @staticmethod
    def _status(events: list[ExperimentProtocolEventRow]) -> str:
        if not events:
            return "registered"
        return {
            "started": "running",
            "paused": "paused",
            "resumed": "running",
            "stopped": "stopped",
            "completed": "completed",
        }[events[-1].event_type]

    @staticmethod
    def _summary(values: list[Decimal]) -> dict[str, Any]:
        if not values:
            return {"count": 0, "mean": None, "variance": None}
        mean = sum(values, Decimal("0")) / len(values)
        variance = None
        if len(values) > 1:
            variance = sum(((item - mean) ** 2 for item in values), Decimal("0")) / (
                len(values) - 1
            )
        return {
            "count": len(values),
            "mean": str(mean),
            "variance": str(variance) if variance is not None else None,
        }

    @staticmethod
    def _effect(control: list[Decimal], treatment: list[Decimal]) -> dict[str, Any] | None:
        if len(control) < 2 or len(treatment) < 2:
            return None
        control_mean = sum(control, Decimal("0")) / len(control)
        treatment_mean = sum(treatment, Decimal("0")) / len(treatment)
        control_var = sum(((item - control_mean) ** 2 for item in control), Decimal("0")) / (
            len(control) - 1
        )
        treatment_var = sum(
            ((item - treatment_mean) ** 2 for item in treatment), Decimal("0")
        ) / (len(treatment) - 1)
        standard_error = Decimal(
            str(
                math.sqrt(
                    float(control_var / len(control) + treatment_var / len(treatment))
                )
            )
        )
        difference = treatment_mean - control_mean
        if standard_error == 0:
            p_value = Decimal("0") if difference != 0 else Decimal("1")
        else:
            z_score = abs(float(difference / standard_error))
            p_value = Decimal(str(math.erfc(z_score / math.sqrt(2))))
        margin = Decimal("1.96") * standard_error
        return {
            "control_mean": str(control_mean),
            "treatment_mean": str(treatment_mean),
            "absolute_effect": str(difference),
            "relative_effect": (
                str(difference / abs(control_mean)) if control_mean != 0 else None
            ),
            "standard_error": str(standard_error),
            "confidence_interval_95": [str(difference - margin), str(difference + margin)],
            "normal_approximation_p_value": str(p_value),
            "method": "two_arm_welch_normal_approximation",
        }

    @classmethod
    def _heterogeneous_effects(
        cls,
        *,
        assignments: list[ExperimentAssignmentRow],
        observations: list[ExperimentObservationRow],
        metric: str,
        stratification_keys: list[str],
        control_id: str,
        treatment_id: str,
    ) -> list[dict[str, Any]]:
        observed = {
            item.assignment_id: Decimal(item.value_decimal)
            for item in observations
            if item.metric == metric
        }
        result = []
        for key in stratification_keys:
            values = sorted(
                {
                    item.strata_json[key]
                    for item in assignments
                    if key in item.strata_json
                }
            )
            segments = []
            for value in values:
                control_values = [
                    observed[item.id]
                    for item in assignments
                    if item.variant_id == control_id
                    and item.strata_json.get(key) == value
                    and item.id in observed
                ]
                treatment_values = [
                    observed[item.id]
                    for item in assignments
                    if item.variant_id == treatment_id
                    and item.strata_json.get(key) == value
                    and item.id in observed
                ]
                effect = cls._effect(control_values, treatment_values)
                segments.append(
                    {
                        "value": value,
                        "control_count": len(control_values),
                        "treatment_count": len(treatment_values),
                        "effect": effect,
                        "estimable": effect is not None,
                    }
                )
            result.append({"key": key, "segments": segments})
        return result

    def _link_many(self, evidence_ids: list[str], target_type: str, target_id: str, actor: str) -> None:
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type=target_type,
                target_id=target_id,
                relationship="supports_preregistration",
                created_by=actor,
            )

    @classmethod
    def _protocol(
        cls,
        row: ExperimentProtocolRow,
        status: str,
        events: list[ExperimentProtocolEventRow] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "resolution_id": row.resolution_id,
            "hypothesis": row.hypothesis,
            "primary_metric": row.primary_metric,
            "randomization_unit": row.randomization_unit,
            "interference_cluster": row.interference_cluster,
            "variants": row.variants_json,
            "target_sample_size": row.target_sample_size,
            "minimum_detectable_effect": str(row.minimum_detectable_effect_decimal),
            "budget_cap_amount": str(row.budget_cap_amount_decimal),
            "stop_loss_amount": str(row.stop_loss_amount_decimal),
            "currency": row.currency,
            "start_at": cls._iso(row.start_at),
            "end_at": cls._iso(row.end_at),
            "outcome_window_days": row.outcome_window_days,
            "guardrails": row.guardrails_json,
            "stratification_keys": row.stratification_keys_json,
            "effect_metrics": row.effect_metrics_json
            or [
                {
                    "metric": row.primary_metric,
                    "role": "primary",
                    "multiplier": "1",
                    "required": True,
                }
            ],
            "evidence_ids": row.evidence_json,
            "status": status,
            "events": [cls._event(item) for item in events or []],
            "created_by": row.created_by,
            "created_at": cls._iso(row.created_at),
        }

    @classmethod
    def _event(cls, row: ExperimentProtocolEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "sequence": row.sequence,
            "event_type": row.event_type,
            "effective_at": cls._iso(row.effective_at),
            "evidence_id": row.evidence_id,
            "reason": row.reason,
            "created_by": row.created_by,
            "recorded_at": cls._iso(row.recorded_at),
        }

    @classmethod
    def _assignment(cls, row: ExperimentAssignmentRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "protocol_id": row.protocol_id,
            "unit_hash": row.unit_hash,
            "variant_id": row.variant_id,
            "strata": row.strata_json,
            "assigned_at": cls._iso(row.assigned_at),
        }

    @classmethod
    def _observation(cls, row: ExperimentObservationRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "protocol_id": row.protocol_id,
            "assignment_id": row.assignment_id,
            "metric": row.metric,
            "value": str(row.value_decimal),
            "observed_at": cls._iso(row.observed_at),
            "evidence_id": row.evidence_id,
            "created_by": row.created_by,
            "recorded_at": cls._iso(row.recorded_at),
        }

    @classmethod
    def _safety_check(cls, row: ExperimentSafetyCheckRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "protocol_id": row.protocol_id,
            "metric": row.metric,
            "value": str(row.value_decimal),
            "direction": row.direction,
            "threshold": str(row.threshold_decimal),
            "status": row.status,
            "observed_at": cls._iso(row.observed_at),
            "evidence_id": row.evidence_id,
            "created_by": row.created_by,
            "recorded_at": cls._iso(row.recorded_at),
        }

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
