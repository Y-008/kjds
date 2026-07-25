from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

IncidentMode = Literal["live", "drill"]
IncidentSeverity = Literal["critical", "high", "medium", "low"]

RECOVERY_CHECKS = (
    "remote_state_reconciled",
    "rollback_confirmed_or_not_required",
    "data_reconciled",
    "credentials_rotated_or_not_required",
    "monitoring_restored",
)


class OperationalIncidentRow(Base):
    __tablename__ = "operational_incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    impact_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    review_status: Mapped[str | None] = mapped_column(String, nullable=True)
    opened_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IncidentRecoveryEventRow(Base):
    __tablename__ = "incident_recovery_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("operational_incidents.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IncidentRecoveryService:
    def __init__(self, *, engine, evidence, kill_switch) -> None:
        self.engine = engine
        self.evidence = evidence
        self.kill_switch = kill_switch

    def open(
        self,
        *,
        idempotency_key: str,
        mode: IncidentMode,
        severity: IncidentSeverity,
        trigger_type: str,
        source_type: str | None,
        source_id: str | None,
        summary: str,
        impact: list[str],
        evidence_ids: list[str],
        opened_by: str,
    ) -> dict[str, Any]:
        idempotency_key = self._required(idempotency_key, "Incident idempotency key")
        trigger_type = self._required(trigger_type, "Incident trigger type")
        summary = self._required(summary, "Incident summary")
        opened_by = self._required(opened_by, "Incident opener")
        impact = self._strings(impact, "Incident impact")
        evidence_ids = self._evidence(evidence_ids)
        source_type = source_type.strip() if source_type else None
        source_id = source_id.strip() if source_id else None
        if bool(source_type) != bool(source_id):
            raise ValueError("Incident source type and source id must be supplied together")
        requested = self._opening_payload(
            mode,
            severity,
            trigger_type,
            source_type,
            source_id,
            summary,
            impact,
            evidence_ids,
            opened_by,
        )
        with Session(self.engine) as session:
            existing = session.scalar(
                select(OperationalIncidentRow).where(
                    OperationalIncidentRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                candidate = self._opening_payload(
                    existing.mode,
                    existing.severity,
                    existing.trigger_type,
                    existing.source_type,
                    existing.source_id,
                    existing.summary,
                    existing.impact_json,
                    evidence_ids,
                    existing.opened_by,
                )
                if candidate != requested:
                    raise ValueError("Incident idempotency key already has different content")
                existing_id = existing.id
            else:
                existing_id = None
        if existing_id is not None:
            return self.get(existing_id)
        if mode == "live" and severity in {"critical", "high"}:
            state = self.kill_switch.current()
            if not state.engaged:
                self.kill_switch.set_state(
                    engaged=True,
                    reason=f"Operational incident opened: {summary}",
                    actor_id=opened_by,
                )
        now = datetime.now(UTC)
        try:
            with Session(self.engine) as session, session.begin():
                row = OperationalIncidentRow(
                    id=new_id("inc"),
                    idempotency_key=idempotency_key,
                    mode=mode,
                    severity=severity,
                    trigger_type=trigger_type,
                    source_type=source_type,
                    source_id=source_id,
                    summary=summary,
                    impact_json=impact,
                    status="contained" if mode == "live" and self.kill_switch.current().engaged else "open",
                    owner_id=None,
                    review_status=None,
                    opened_by=opened_by,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
                incident_id = row.id
        except IntegrityError:
            with Session(self.engine) as session:
                winner = session.scalar(
                    select(OperationalIncidentRow).where(
                        OperationalIncidentRow.idempotency_key == idempotency_key
                    )
                )
            if winner is None:
                raise
            winner_payload = self._opening_payload(
                winner.mode,
                winner.severity,
                winner.trigger_type,
                winner.source_type,
                winner.source_id,
                winner.summary,
                winner.impact_json,
                evidence_ids,
                winner.opened_by,
            )
            if winner_payload != requested:
                raise ValueError("Incident idempotency key already has different content") from None
            return self.get(winner.id)
        self._append_event(
            incident_id,
            "opened",
            {
                "mode": mode,
                "severity": severity,
                "trigger_type": trigger_type,
                "source_type": source_type,
                "source_id": source_id,
                "summary": summary,
                "impact": impact,
            },
            evidence_ids,
            opened_by,
        )
        return self.get(incident_id)

    def claim(self, incident_id: str, *, actor_id: str) -> dict[str, Any]:
        actor_id = self._required(actor_id, "Recovery owner")
        with Session(self.engine) as session, session.begin():
            row = self._row(session, incident_id, lock=True)
            if row.status == "closed":
                raise ValueError("Closed incident cannot be claimed")
            if row.owner_id and row.owner_id != actor_id:
                raise ValueError("Incident already has a different recovery owner")
            if row.owner_id is None:
                row.owner_id = actor_id
                row.status = "recovering"
                row.updated_at = datetime.now(UTC)
                should_append = True
            else:
                should_append = False
        if should_append:
            self._append_event(incident_id, "owner_claimed", {}, [], actor_id)
        return self.get(incident_id)

    def record_check(
        self,
        incident_id: str,
        *,
        check: str,
        passed: bool,
        notes: str,
        evidence_ids: list[str],
        actor_id: str,
    ) -> dict[str, Any]:
        if check not in RECOVERY_CHECKS:
            raise ValueError("Unknown recovery check")
        notes = self._required(notes, "Recovery check notes")
        evidence_ids = self._evidence(evidence_ids)
        actor_id = self._required(actor_id, "Recovery check actor")
        incident = self.get(incident_id)
        if incident["owner_id"] != actor_id:
            raise ValueError("Only the recovery owner can record recovery checks")
        if incident["status"] not in {"recovering", "pending_review"}:
            raise ValueError("Incident is not accepting recovery checks")
        self._append_event(
            incident_id,
            "recovery_check",
            {"check": check, "passed": passed, "notes": notes},
            evidence_ids,
            actor_id,
        )
        with Session(self.engine) as session, session.begin():
            row = self._row(session, incident_id, lock=True)
            row.status = "recovering"
            row.review_status = None
            row.updated_at = datetime.now(UTC)
        return self.get(incident_id)

    def submit_review(self, incident_id: str, *, actor_id: str) -> dict[str, Any]:
        actor_id = self._required(actor_id, "Recovery owner")
        incident = self.get(incident_id)
        if incident["owner_id"] != actor_id:
            raise ValueError("Only the recovery owner can submit recovery for review")
        missing = [check for check in RECOVERY_CHECKS if not incident["checks"].get(check, {}).get("passed")]
        if missing:
            raise ValueError(f"Recovery checklist is incomplete: {', '.join(missing)}")
        if (
            incident["mode"] == "live"
            and incident["severity"] in {"critical", "high"}
            and not self.kill_switch.current().engaged
        ):
            raise ValueError("Live recovery must be independently reviewed before kill switch release")
        with Session(self.engine) as session, session.begin():
            row = self._row(session, incident_id, lock=True)
            row.status = "pending_review"
            row.review_status = "pending"
            row.updated_at = datetime.now(UTC)
        self._append_event(incident_id, "review_requested", {}, [], actor_id)
        return self.get(incident_id)

    def review(
        self,
        incident_id: str,
        *,
        accepted: bool,
        rationale: str,
        evidence_ids: list[str],
        actor_id: str,
    ) -> dict[str, Any]:
        rationale = self._required(rationale, "Recovery review rationale")
        evidence_ids = self._evidence(evidence_ids)
        actor_id = self._required(actor_id, "Recovery reviewer")
        incident = self.get(incident_id)
        if incident["status"] != "pending_review":
            raise ValueError("Incident is not pending recovery review")
        if actor_id in {incident["owner_id"], incident["opened_by"]}:
            raise ValueError("Recovery reviewer must be independent from opener and owner")
        with Session(self.engine) as session, session.begin():
            row = self._row(session, incident_id, lock=True)
            row.review_status = "accepted" if accepted else "rejected"
            row.status = "ready_for_release" if accepted else "recovering"
            row.updated_at = datetime.now(UTC)
        self._append_event(
            incident_id,
            "reviewed",
            {"accepted": accepted, "rationale": rationale},
            evidence_ids,
            actor_id,
        )
        return self.get(incident_id)

    def close(
        self,
        incident_id: str,
        *,
        notes: str,
        evidence_ids: list[str],
        actor_id: str,
    ) -> dict[str, Any]:
        notes = self._required(notes, "Incident closure notes")
        evidence_ids = self._evidence(evidence_ids)
        actor_id = self._required(actor_id, "Incident closer")
        incident = self.get(incident_id)
        if incident["status"] != "ready_for_release" or incident["review_status"] != "accepted":
            raise ValueError("Incident requires accepted independent recovery review")
        if incident["mode"] == "live" and self.kill_switch.current().engaged:
            raise ValueError("Administrator must explicitly release the kill switch before closure")
        with Session(self.engine) as session, session.begin():
            row = self._row(session, incident_id, lock=True)
            row.status = "closed"
            row.updated_at = datetime.now(UTC)
        self._append_event(
            incident_id,
            "closed",
            {"notes": notes},
            evidence_ids,
            actor_id,
        )
        return self.get(incident_id)

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    select(OperationalIncidentRow.id).order_by(
                        OperationalIncidentRow.created_at.desc()
                    )
                )
            )
        return [self.get(incident_id) for incident_id in ids]

    def get(self, incident_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = self._row(session, incident_id)
            events = list(
                session.scalars(
                    select(IncidentRecoveryEventRow)
                    .where(IncidentRecoveryEventRow.incident_id == incident_id)
                    .order_by(IncidentRecoveryEventRow.created_at, IncidentRecoveryEventRow.id)
                )
            )
            checks: dict[str, dict[str, Any]] = {}
            for event in events:
                if event.event_type == "recovery_check":
                    checks[event.payload_json["check"]] = {
                        **event.payload_json,
                        "evidence_ids": event.evidence_json,
                        "actor_id": event.actor_id,
                        "created_at": self._iso(event.created_at),
                    }
            return {
                "id": row.id,
                "idempotency_key": row.idempotency_key,
                "mode": row.mode,
                "severity": row.severity,
                "trigger_type": row.trigger_type,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "summary": row.summary,
                "impact": row.impact_json,
                "status": row.status,
                "owner_id": row.owner_id,
                "review_status": row.review_status,
                "opened_by": row.opened_by,
                "created_at": self._iso(row.created_at),
                "updated_at": self._iso(row.updated_at),
                "checks": checks,
                "required_checks": list(RECOVERY_CHECKS),
                "events": [self._event(event) for event in events],
                "kill_switch_engaged": self.kill_switch.current().engaged,
                "automatic_release": False,
                "immutable_event_history": True,
            }

    def _append_event(
        self,
        incident_id: str,
        event_type: str,
        payload: dict[str, Any],
        evidence_ids: list[str],
        actor_id: str,
    ) -> None:
        canonical = {
            "incident_id": incident_id,
            "event_type": event_type,
            "payload": payload,
            "evidence_ids": evidence_ids,
            "actor_id": actor_id,
        }
        request_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(IncidentRecoveryEventRow).where(
                    IncidentRecoveryEventRow.request_hash == request_hash
                )
            )
            if existing is not None:
                return
            row = IncidentRecoveryEventRow(
                id=new_id("ire"),
                request_hash=request_hash,
                incident_id=incident_id,
                event_type=event_type,
                payload_json=payload,
                evidence_json=evidence_ids,
                actor_id=actor_id,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            event_id = row.id
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type="incident_recovery_event",
                target_id=event_id,
                relationship="supports",
                created_by=actor_id,
            )

    def _evidence(self, values: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in values if item.strip()})
        if not normalized:
            raise ValueError("Incident action evidence is required")
        self.evidence.require_valid(normalized)
        return normalized

    @staticmethod
    def _row(session: Session, incident_id: str, *, lock: bool = False) -> OperationalIncidentRow:
        row = session.get(OperationalIncidentRow, incident_id, with_for_update=lock)
        if row is None:
            raise KeyError(f"Operational incident not found: {incident_id}")
        return row

    @staticmethod
    def _required(value: str, name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        return cleaned

    @classmethod
    def _strings(cls, values: list[str], name: str) -> list[str]:
        normalized = sorted({cls._required(item, name) for item in values})
        if not normalized:
            raise ValueError(f"{name} is required")
        return normalized

    @staticmethod
    def _opening_payload(
        mode: str,
        severity: str,
        trigger_type: str,
        source_type: str | None,
        source_id: str | None,
        summary: str,
        impact: list[str],
        evidence_ids: list[str],
        opened_by: str,
    ) -> dict[str, Any]:
        return {
            "mode": mode,
            "severity": severity,
            "trigger_type": trigger_type,
            "source_type": source_type,
            "source_id": source_id,
            "summary": summary,
            "impact": impact,
            "evidence_ids": evidence_ids,
            "opened_by": opened_by,
        }

    @staticmethod
    def _iso(value: datetime) -> str:
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()

    @classmethod
    def _event(cls, row: IncidentRecoveryEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "event_type": row.event_type,
            "payload": row.payload_json,
            "evidence_ids": row.evidence_json,
            "actor_id": row.actor_id,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }
