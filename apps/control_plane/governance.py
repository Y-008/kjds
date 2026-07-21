from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base, add_outbox_event

GATE_IDS = {"G0", "G1", "G4"}
DECISIONS = {"PASS", "CONDITIONAL", "FAIL", "STOP"}


class GateReviewRow(Base):
    __tablename__ = "gate_reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[str] = mapped_column(String, nullable=False)
    approver_id: Mapped[str] = mapped_column(String, nullable=False)
    participants_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    objective: Mapped[str] = mapped_column(String, nullable=False)
    exit_criteria: Mapped[str] = mapped_column(String, nullable=False)
    deliverables_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    blockers_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risk_budget_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    max_loss_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    rollback_plan: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    rationale: Mapped[str | None] = mapped_column(String, nullable=True)
    conditions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GovernanceService:
    def __init__(self, *, engine, evidence) -> None:
        self.engine = engine
        self.evidence = evidence

    def create(
        self,
        *,
        idempotency_key: str,
        gate_id: str,
        owner_id: str,
        approver_id: str,
        participants: list[str],
        objective: str,
        exit_criteria: str,
        deliverables: list[str],
        evidence_ids: list[str],
        unknowns: list[str],
        blockers: list[str],
        risk_budget: dict[str, Any],
        max_loss: dict[str, Any],
        rollback_plan: str,
        actor_id: str,
    ) -> dict[str, Any]:
        key = self._text(idempotency_key, "Idempotency key", 300)
        gate = gate_id.strip().upper()
        if gate not in GATE_IDS:
            raise ValueError("Gate must be one of G0, G1, G4")
        owner = self._text(owner_id, "Owner", 120)
        approver = self._text(approver_id, "Approver", 120)
        if owner == approver:
            raise ValueError("Owner and approver must be different identities")
        actor = self._text(actor_id, "Actor", 120)
        if actor != owner:
            raise ValueError("Only the gate owner can create the review")
        participant_list = self._list(participants, "Participants", required=True)
        if approver not in participant_list:
            participant_list.append(approver)
        deliverable_list = self._list(deliverables, "Deliverables", required=True)
        unknown_list = self._list(unknowns, "Unknowns")
        blocker_list = self._list(blockers, "Blockers")
        evidence_list = self._evidence_ids(evidence_ids, required=False)
        budget = self._money(risk_budget, "Risk budget")
        loss = self._money(max_loss, "Maximum loss")
        if Decimal(loss["amount"]) > Decimal(budget["amount"]):
            raise ValueError("Maximum loss cannot exceed risk budget")
        payload = {
            "gate_id": gate,
            "owner_id": owner,
            "approver_id": approver,
            "participants": participant_list,
            "objective": self._text(objective, "Objective", 5000),
            "exit_criteria": self._text(exit_criteria, "Exit criteria", 5000),
            "deliverables": deliverable_list,
            "evidence_ids": evidence_list,
            "unknowns": unknown_list,
            "blockers": blocker_list,
            "risk_budget": budget,
            "max_loss": loss,
            "rollback_plan": self._text(rollback_plan, "Rollback plan", 5000),
        }
        request_hash = self._hash(payload)
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(GateReviewRow).where(GateReviewRow.idempotency_key == key)
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ValueError("Gate review idempotency key already has different content")
                return self._serialize(existing)
            row = GateReviewRow(
                id=new_id("gate"),
                idempotency_key=key,
                request_hash=request_hash,
                gate_id=gate,
                owner_id=owner,
                approver_id=approver,
                participants_json=participant_list,
                objective=payload["objective"],
                exit_criteria=payload["exit_criteria"],
                deliverables_json=deliverable_list,
                evidence_ids_json=evidence_list,
                unknowns_json=unknown_list,
                blockers_json=blocker_list,
                risk_budget_json=budget,
                max_loss_json=loss,
                rollback_plan=payload["rollback_plan"],
                status="draft",
                decision=None,
                rationale=None,
                conditions_json=[],
                decided_by=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            add_outbox_event(
                session,
                "gate_review.created",
                row.id,
                {"gate_id": gate, "status": "draft"},
                actor_id=actor,
            )
            session.flush()
            review_id = row.id
        return self.get(review_id)

    def submit(self, review_id: str, *, evidence_ids: list[str], actor_id: str) -> dict[str, Any]:
        evidence_list = self._evidence_ids(evidence_ids, required=True)
        self.evidence.require_valid(evidence_list)
        actor = self._text(actor_id, "Actor", 120)
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            row = self._row(session, review_id, lock=True)
            if row.status != "draft":
                raise ValueError("Only draft gate reviews can be submitted")
            if row.owner_id != actor:
                raise ValueError("Only the gate owner can submit the review")
            row.evidence_ids_json = evidence_list
            row.status = "submitted"
            row.updated_at = now
            add_outbox_event(
                session,
                "gate_review.submitted",
                row.id,
                {
                    "gate_id": row.gate_id,
                    "status": "submitted",
                    "evidence_count": len(evidence_list),
                },
                actor_id=actor,
                source_evidence_id=evidence_list[0],
            )
        return self.get(review_id)

    def decide(
        self,
        review_id: str,
        *,
        decision: str,
        rationale: str,
        conditions: list[str],
        actor_id: str,
    ) -> dict[str, Any]:
        normalized = decision.strip().upper()
        if normalized not in DECISIONS:
            raise ValueError("Gate decision must be PASS, CONDITIONAL, FAIL, or STOP")
        actor = self._text(actor_id, "Actor", 120)
        reason = self._text(rationale, "Rationale", 5000)
        condition_list = self._list(conditions, "Conditions")
        with Session(self.engine) as session, session.begin():
            row = self._row(session, review_id, lock=True)
            if row.status != "submitted":
                raise ValueError("Only submitted gate reviews can be decided")
            if row.approver_id != actor:
                raise ValueError("Only the named approver can decide the review")
            self.evidence.require_valid(row.evidence_ids_json)
            row.status = "decided"
            row.decision = normalized
            row.rationale = reason
            row.conditions_json = condition_list
            row.decided_by = actor
            row.updated_at = datetime.now(UTC)
            add_outbox_event(
                session,
                "gate_review.decided",
                row.id,
                {
                    "gate_id": row.gate_id,
                    "status": "decided",
                    "decision": normalized,
                    "condition_count": len(condition_list),
                },
                actor_id=actor,
                source_evidence_id=row.evidence_ids_json[0],
            )
        return self.get(review_id)

    def get(self, review_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._serialize(self._row(session, review_id))

    def list(self, *, gate_id: str | None = None) -> list[dict[str, Any]]:
        query = select(GateReviewRow).order_by(GateReviewRow.updated_at.desc(), GateReviewRow.id)
        if gate_id:
            query = query.where(GateReviewRow.gate_id == gate_id.strip().upper())
        with Session(self.engine) as session:
            return [self._serialize(row) for row in session.scalars(query)]

    @staticmethod
    def _row(session: Session, review_id: str, *, lock: bool = False) -> GateReviewRow:
        row = session.get(GateReviewRow, review_id, with_for_update=lock)
        if row is None:
            raise KeyError(f"Gate review not found: {review_id}")
        return row

    @staticmethod
    def _text(value: str, name: str, max_length: int) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        if len(cleaned) > max_length:
            raise ValueError(f"{name} is too long")
        return cleaned

    @classmethod
    def _list(cls, values: list[str], name: str, *, required: bool = False) -> list[str]:
        if not isinstance(values, list):
            raise ValueError(f"{name} must be a list")
        normalized = [cls._text(value, name, 500) for value in values]
        if required and not normalized:
            raise ValueError(f"At least one {name.lower()} is required")
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"{name} must not contain duplicates")
        return normalized

    @classmethod
    def _evidence_ids(cls, values: list[str], *, required: bool) -> list[str]:
        normalized = cls._list(values, "Evidence IDs", required=required)
        if any(len(value) > 200 for value in normalized):
            raise ValueError("Evidence ID is too long")
        return normalized

    @classmethod
    def _money(cls, value: dict[str, Any], name: str) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")
        amount = value.get("amount")
        currency = str(value.get("currency", "")).strip().upper()
        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} amount must be numeric") from exc
        if decimal_amount < 0 or not decimal_amount.is_finite():
            raise ValueError(f"{name} amount must be finite and non-negative")
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(f"{name} currency must be a 3-letter code")
        return {"amount": format(decimal_amount, "f"), "currency": currency}

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _serialize(row: GateReviewRow) -> dict[str, Any]:
        created_at = row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at.astimezone(UTC)
        updated_at = row.updated_at.replace(tzinfo=UTC) if row.updated_at.tzinfo is None else row.updated_at.astimezone(UTC)
        return {
            "id": row.id,
            "gate_id": row.gate_id,
            "owner_id": row.owner_id,
            "approver_id": row.approver_id,
            "participants": row.participants_json,
            "objective": row.objective,
            "exit_criteria": row.exit_criteria,
            "deliverables": row.deliverables_json,
            "evidence_ids": row.evidence_ids_json,
            "unknowns": row.unknowns_json,
            "blockers": row.blockers_json,
            "risk_budget": row.risk_budget_json,
            "max_loss": row.max_loss_json,
            "rollback_plan": row.rollback_plan,
            "status": row.status,
            "decision": row.decision,
            "rationale": row.rationale,
            "conditions": row.conditions_json,
            "decided_by": row.decided_by,
            "created_at": created_at.isoformat(),
            "updated_at": updated_at.isoformat(),
        }
