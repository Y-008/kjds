from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base


class CapabilityEconomicAssessmentRow(Base):
    __tablename__ = "capability_economic_assessments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    window_id: Mapped[str] = mapped_column(
        ForeignKey("execution_observation_windows.id"), unique=True, nullable=False
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("governed_execution_plans.id"), nullable=False
    )
    policy_id: Mapped[str] = mapped_column(ForeignKey("causal_policies.id"), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String, nullable=False)
    outcome_status: Mapped[str] = mapped_column(String, nullable=False)
    realized_incremental_value: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    avoided_loss: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    model_compute_cost: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    human_review_cost: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    incident_loss: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    maintenance_cost: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    net_value: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    assessed_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapabilityEconomicsService:
    def __init__(self, *, engine, post_execution, execution_plans, evidence) -> None:
        self.engine = engine
        self.post_execution = post_execution
        self.execution_plans = execution_plans
        self.evidence = evidence

    def assess(
        self,
        window_id: str,
        *,
        realized_incremental_value: Any,
        avoided_loss: Any,
        model_compute_cost: Any,
        human_review_cost: Any,
        incident_loss: Any,
        maintenance_cost: Any,
        currency: str,
        evidence_ids: list[str],
        assessed_by: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        window = self.post_execution.get_window(window_id)
        evaluation = self.post_execution.evaluate(window_id, as_of=as_of)
        if evaluation["status"] not in {"passed", "guardrail_breached"}:
            raise ValueError("Capability economics requires a concluded observation window")
        plan = self.execution_plans.get(window["plan_id"])
        realized = self._decimal(realized_incremental_value, "Realized incremental value")
        avoided = self._nonnegative(avoided_loss, "Avoided loss")
        model_cost = self._nonnegative(model_compute_cost, "Model and compute cost")
        review_cost = self._nonnegative(human_review_cost, "Human review cost")
        incident = self._nonnegative(incident_loss, "Incident loss")
        maintenance = self._nonnegative(maintenance_cost, "Maintenance cost")
        net_value = realized + avoided - model_cost - review_cost - incident - maintenance
        currency = currency.strip().upper()
        if len(currency) != 3 or any(character < "A" or character > "Z" for character in currency):
            raise ValueError("Currency must be a three-letter ASCII code")
        evidence_ids = sorted({item.strip() for item in evidence_ids if item.strip()})
        if not evidence_ids:
            raise ValueError("Capability economics evidence is required")
        self.evidence.require_valid(evidence_ids)
        assessed_by = assessed_by.strip()
        if not assessed_by:
            raise ValueError("Capability economics assessor is required")
        canonical = {
            "window_id": window_id,
            "plan_id": plan["id"],
            "policy_id": window["policy_id"],
            "adapter_id": plan["adapter_id"],
            "outcome_status": evaluation["status"],
            "realized_incremental_value": str(realized),
            "avoided_loss": str(avoided),
            "model_compute_cost": str(model_cost),
            "human_review_cost": str(review_cost),
            "incident_loss": str(incident),
            "maintenance_cost": str(maintenance),
            "net_value": str(net_value),
            "currency": currency,
            "evidence_ids": evidence_ids,
            "assessed_by": assessed_by,
        }
        request_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(CapabilityEconomicAssessmentRow).where(
                    CapabilityEconomicAssessmentRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._serialize(exact)
            previous = session.scalar(
                select(CapabilityEconomicAssessmentRow).where(
                    CapabilityEconomicAssessmentRow.window_id == window_id
                )
            )
            if previous is not None:
                raise ValueError("Observation window already has an immutable economic assessment")
            row = CapabilityEconomicAssessmentRow(
                id=new_id("cea"),
                request_hash=request_hash,
                window_id=window_id,
                plan_id=plan["id"],
                policy_id=window["policy_id"],
                adapter_id=plan["adapter_id"],
                outcome_status=evaluation["status"],
                realized_incremental_value=realized,
                avoided_loss=avoided,
                model_compute_cost=model_cost,
                human_review_cost=review_cost,
                incident_loss=incident,
                maintenance_cost=maintenance,
                net_value=net_value,
                currency=currency,
                evidence_json=evidence_ids,
                assessed_by=assessed_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            assessment_id = row.id
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type="capability_economic_assessment",
                target_id=assessment_id,
                relationship="supports",
                created_by=assessed_by,
            )
        return self.get(assessment_id)

    def get(self, assessment_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(CapabilityEconomicAssessmentRow, assessment_id)
            if row is None:
                raise KeyError(f"Capability economic assessment not found: {assessment_id}")
            return self._serialize(row)

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(CapabilityEconomicAssessmentRow).order_by(
                        CapabilityEconomicAssessmentRow.created_at
                    )
                )
            )
            return [self._serialize(row) for row in rows]

    def summaries(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in self.list():
            grouped.setdefault((item["adapter_id"], item["currency"]), []).append(item)
        result = []
        for (adapter_id, currency), rows in sorted(grouped.items()):
            net_value = sum(Decimal(row["net_value"]) for row in rows)
            breaches = sum(row["outcome_status"] == "guardrail_breached" for row in rows)
            result.append(
                {
                    "adapter_id": adapter_id,
                    "currency": currency,
                    "assessment_count": len(rows),
                    "profitable_count": sum(Decimal(row["net_value"]) > 0 for row in rows),
                    "guardrail_breach_count": breaches,
                    "total_net_value": str(net_value),
                    "governance_recommendation": (
                        "restrict_and_review"
                        if breaches
                        else "retain_with_observation"
                        if net_value > 0
                        else "review_or_retire"
                    ),
                    "automatic_authority_change": False,
                }
            )
        return result

    @classmethod
    def _nonnegative(cls, value: Any, name: str) -> Decimal:
        parsed = cls._decimal(value, name)
        if parsed < 0:
            raise ValueError(f"{name} cannot be negative")
        return parsed

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
    def _iso(value: datetime) -> str:
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()

    @classmethod
    def _serialize(cls, row: CapabilityEconomicAssessmentRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "window_id": row.window_id,
            "plan_id": row.plan_id,
            "policy_id": row.policy_id,
            "adapter_id": row.adapter_id,
            "outcome_status": row.outcome_status,
            "realized_incremental_value": str(Decimal(row.realized_incremental_value)),
            "avoided_loss": str(Decimal(row.avoided_loss)),
            "model_compute_cost": str(Decimal(row.model_compute_cost)),
            "human_review_cost": str(Decimal(row.human_review_cost)),
            "incident_loss": str(Decimal(row.incident_loss)),
            "maintenance_cost": str(Decimal(row.maintenance_cost)),
            "net_value": str(Decimal(row.net_value)),
            "currency": row.currency,
            "evidence_ids": row.evidence_json,
            "assessed_by": row.assessed_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
            "automatic_authority_change": False,
        }
