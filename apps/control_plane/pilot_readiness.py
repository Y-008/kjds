from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

READ_ONLY_OPERATIONS = {
    "ozon.product.read",
    "ozon.inventory.read",
    "ozon.orders.read",
    "ozon.analytics.read",
    "ozon.finance.read",
}
IMPLEMENTED_READ_ONLY_OPERATIONS = {"ozon.product.read", "ozon.finance.read"}
OZON_PRODUCT_READ_CONTRACT_VERSION = "ozon-product-read-v1"
OZON_FINANCE_READ_CONTRACT_VERSION = "ozon-finance-transactions-v1"
PILOT_CONTROLS = (
    "credentials_isolated",
    "least_privilege_scope",
    "monitoring_configured",
    "data_export_backup_verified",
)


class ReadOnlyPilotRow(Base):
    __tablename__ = "read_only_pilots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    account_alias: Mapped[str] = mapped_column(String, nullable=False)
    allowed_operations_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    max_daily_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    max_targets: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    review_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PilotControlAttestationRow(Base):
    __tablename__ = "pilot_control_attestations"
    __table_args__ = (
        UniqueConstraint(
            "pilot_id", "control", "request_hash", name="uq_pilot_control_attestation"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    pilot_id: Mapped[str] = mapped_column(ForeignKey("read_only_pilots.id"), nullable=False)
    control: Mapped[str] = mapped_column(String, nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    attested_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PilotReadinessService:
    def __init__(self, *, engine, evidence, incidents, kill_switch) -> None:
        self.engine = engine
        self.evidence = evidence
        self.incidents = incidents
        self.kill_switch = kill_switch

    def create(
        self,
        *,
        idempotency_key: str,
        platform: str,
        account_alias: str,
        allowed_operations: list[str],
        max_daily_requests: int,
        max_targets: int,
        starts_at: str,
        ends_at: str,
        evidence_ids: list[str],
        requested_by: str,
    ) -> dict[str, Any]:
        idempotency_key = self._required(idempotency_key, "Pilot idempotency key")
        platform = self._required(platform, "Pilot platform").lower()
        if platform != "ozon":
            raise ValueError("Current read-only pilot supports Ozon only")
        account_alias = self._required(account_alias, "Non-secret account alias")
        if any(token in account_alias.lower() for token in ("key", "secret", "token", "password")):
            raise ValueError("Pilot account alias must not contain credential material")
        operations = sorted({self._required(item, "Allowed operation") for item in allowed_operations})
        if not operations or not set(operations) <= READ_ONLY_OPERATIONS:
            raise ValueError("Pilot operations must remain inside the read-only Ozon allowlist")
        if not 1 <= max_daily_requests <= 10000:
            raise ValueError("Pilot daily request limit must be between 1 and 10000")
        if not 1 <= max_targets <= 1000:
            raise ValueError("Pilot target limit must be between 1 and 1000")
        starts = self._datetime(starts_at, "starts_at")
        ends = self._datetime(ends_at, "ends_at")
        if ends <= starts or ends - starts > timedelta(days=14):
            raise ValueError("Read-only pilot duration must be positive and no longer than 14 days")
        evidence_ids = self._evidence(evidence_ids)
        requested_by = self._required(requested_by, "Pilot requester")
        canonical = {
            "platform": platform,
            "account_alias": account_alias,
            "allowed_operations": operations,
            "max_daily_requests": max_daily_requests,
            "max_targets": max_targets,
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "evidence_ids": evidence_ids,
            "requested_by": requested_by,
        }
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(ReadOnlyPilotRow).where(ReadOnlyPilotRow.idempotency_key == idempotency_key)
            )
            if existing is not None:
                if self._pilot_payload(existing) != canonical:
                    raise ValueError("Pilot idempotency key already has different content")
                pilot_id = existing.id
            else:
                row = ReadOnlyPilotRow(
                    id=new_id("rop"),
                    idempotency_key=idempotency_key,
                    platform=platform,
                    account_alias=account_alias,
                    allowed_operations_json=operations,
                    max_daily_requests=max_daily_requests,
                    max_targets=max_targets,
                    starts_at=starts,
                    ends_at=ends,
                    evidence_json=evidence_ids,
                    status="draft",
                    requested_by=requested_by,
                    reviewed_by=None,
                    review_rationale=None,
                    activated_by=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
                pilot_id = row.id
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type="read_only_pilot",
                target_id=pilot_id,
                relationship="supports",
                created_by=requested_by,
            )
        return self.get(pilot_id)

    def attest(
        self,
        pilot_id: str,
        *,
        control: str,
        passed: bool,
        notes: str,
        evidence_ids: list[str],
        attested_by: str,
    ) -> dict[str, Any]:
        if control not in PILOT_CONTROLS:
            raise ValueError("Unknown pilot readiness control")
        notes = self._required(notes, "Pilot control notes")
        evidence_ids = self._evidence(evidence_ids)
        attested_by = self._required(attested_by, "Pilot control attestor")
        pilot = self.get(pilot_id)
        if pilot["status"] not in {"draft", "changes_requested"}:
            raise ValueError("Pilot controls cannot change after review submission")
        canonical = {
            "pilot_id": pilot_id,
            "control": control,
            "passed": passed,
            "notes": notes,
            "evidence_ids": evidence_ids,
            "attested_by": attested_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(PilotControlAttestationRow).where(
                    PilotControlAttestationRow.request_hash == request_hash
                )
            )
            if existing is None:
                row = PilotControlAttestationRow(
                    id=new_id("pca"),
                    request_hash=request_hash,
                    pilot_id=pilot_id,
                    control=control,
                    passed=passed,
                    notes=notes,
                    evidence_json=evidence_ids,
                    attested_by=attested_by,
                    created_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                attestation_id = row.id
            else:
                attestation_id = existing.id
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type="pilot_control_attestation",
                target_id=attestation_id,
                relationship="supports",
                created_by=attested_by,
            )
        return self.get(pilot_id)

    def evaluate(self, pilot_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        pilot = self.get(pilot_id)
        now = self._datetime(as_of, "as_of") if as_of else datetime.now(UTC)
        latest = pilot["controls"]
        open_live = [
            item
            for item in self.incidents.list()
            if item["mode"] == "live" and item["status"] != "closed"
        ]
        recent_drills = [
            item
            for item in self.incidents.list()
            if item["mode"] == "drill"
            and item["status"] == "closed"
            and self._datetime(item["updated_at"], "drill.updated_at") >= now - timedelta(days=90)
        ]
        requirements = {
            control: bool(latest.get(control, {}).get("passed")) for control in PILOT_CONTROLS
        }
        requirements.update(
            {
                "no_open_live_incident": not open_live,
                "kill_switch_released": not self.kill_switch.current().engaged,
                "recent_recovery_drill": bool(recent_drills),
                "window_active": self._datetime(pilot["starts_at"], "starts_at")
                <= now
                <= self._datetime(pilot["ends_at"], "ends_at"),
                "read_only_allowlist": set(pilot["allowed_operations"]) <= READ_ONLY_OPERATIONS,
                "worker_implemented_scope": set(pilot["allowed_operations"])
                <= IMPLEMENTED_READ_ONLY_OPERATIONS,
            }
        )
        blockers = [name for name, passed in requirements.items() if not passed]
        return {
            "pilot_id": pilot_id,
            "ready_for_review": not blockers,
            "ready_for_activation": not blockers and pilot["status"] == "approved",
            "runtime_allowed": not blockers and pilot["status"] == "active",
            "requirements": requirements,
            "blockers": blockers,
            "open_live_incident_ids": [item["id"] for item in open_live],
            "recent_drill_ids": [item["id"] for item in recent_drills],
            "platform_write_allowed": False,
            "automatic_activation": False,
        }

    def submit_review(self, pilot_id: str, *, actor_id: str, as_of: str | None = None) -> dict[str, Any]:
        actor_id = self._required(actor_id, "Pilot requester")
        pilot = self.get(pilot_id)
        if pilot["requested_by"] != actor_id:
            raise ValueError("Only the pilot requester can submit readiness for review")
        evaluation = self.evaluate(pilot_id, as_of=as_of)
        if not evaluation["ready_for_review"]:
            raise ValueError(f"Pilot readiness is blocked: {', '.join(evaluation['blockers'])}")
        with Session(self.engine) as session, session.begin():
            row = self._row(session, pilot_id, lock=True)
            row.status = "pending_review"
            row.updated_at = datetime.now(UTC)
        return self.get(pilot_id)

    def review(
        self,
        pilot_id: str,
        *,
        accepted: bool,
        rationale: str,
        actor_id: str,
    ) -> dict[str, Any]:
        rationale = self._required(rationale, "Pilot review rationale")
        actor_id = self._required(actor_id, "Pilot reviewer")
        pilot = self.get(pilot_id)
        if pilot["status"] != "pending_review":
            raise ValueError("Pilot is not pending review")
        if pilot["requested_by"] == actor_id:
            raise ValueError("Pilot reviewer must be independent from requester")
        with Session(self.engine) as session, session.begin():
            row = self._row(session, pilot_id, lock=True)
            row.status = "approved" if accepted else "changes_requested"
            row.reviewed_by = actor_id
            row.review_rationale = rationale
            row.updated_at = datetime.now(UTC)
        return self.get(pilot_id)

    def activate(self, pilot_id: str, *, actor_id: str, as_of: str | None = None) -> dict[str, Any]:
        actor_id = self._required(actor_id, "Pilot activator")
        evaluation = self.evaluate(pilot_id, as_of=as_of)
        if not evaluation["ready_for_activation"]:
            raise ValueError(f"Pilot activation is blocked: {', '.join(evaluation['blockers'])}")
        with Session(self.engine) as session, session.begin():
            row = self._row(session, pilot_id, lock=True)
            row.status = "active"
            row.activated_by = actor_id
            row.updated_at = datetime.now(UTC)
        return self.get(pilot_id)

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(session.scalars(select(ReadOnlyPilotRow.id).order_by(ReadOnlyPilotRow.created_at)))
        return [self.get(pilot_id) for pilot_id in ids]

    def get(self, pilot_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = self._row(session, pilot_id)
            attestations = list(
                session.scalars(
                    select(PilotControlAttestationRow)
                    .where(PilotControlAttestationRow.pilot_id == pilot_id)
                    .order_by(PilotControlAttestationRow.created_at, PilotControlAttestationRow.id)
                )
            )
            controls: dict[str, dict[str, Any]] = {}
            for item in attestations:
                controls[item.control] = {
                    "id": item.id,
                    "passed": item.passed,
                    "notes": item.notes,
                    "evidence_ids": item.evidence_json,
                    "attested_by": item.attested_by,
                    "created_at": self._iso(item.created_at),
                    "immutable": True,
                }
            return {
                "id": row.id,
                "idempotency_key": row.idempotency_key,
                "platform": row.platform,
                "account_alias": row.account_alias,
                "allowed_operations": row.allowed_operations_json,
                "max_daily_requests": row.max_daily_requests,
                "max_targets": row.max_targets,
                "starts_at": self._iso(row.starts_at),
                "ends_at": self._iso(row.ends_at),
                "evidence_ids": row.evidence_json,
                "status": row.status,
                "requested_by": row.requested_by,
                "reviewed_by": row.reviewed_by,
                "review_rationale": row.review_rationale,
                "activated_by": row.activated_by,
                "created_at": self._iso(row.created_at),
                "updated_at": self._iso(row.updated_at),
                "controls": controls,
                "required_controls": list(PILOT_CONTROLS),
                "platform_write_allowed": False,
                "execution_eligible": False,
                "credential_material_stored": False,
            }

    @staticmethod
    def _row(session: Session, pilot_id: str, *, lock: bool = False) -> ReadOnlyPilotRow:
        row = session.get(ReadOnlyPilotRow, pilot_id, with_for_update=lock)
        if row is None:
            raise KeyError(f"Read-only pilot not found: {pilot_id}")
        return row

    def _evidence(self, values: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in values if item.strip()})
        if not normalized:
            raise ValueError("Pilot evidence is required")
        self.evidence.require_valid(normalized)
        return normalized

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
        except (AttributeError, ValueError) as exc:
            raise ValueError(f"{name} must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} must include timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _iso(value: datetime) -> str:
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @classmethod
    def _pilot_payload(cls, row: ReadOnlyPilotRow) -> dict[str, Any]:
        return {
            "platform": row.platform,
            "account_alias": row.account_alias,
            "allowed_operations": row.allowed_operations_json,
            "max_daily_requests": row.max_daily_requests,
            "max_targets": row.max_targets,
            "starts_at": cls._iso(row.starts_at),
            "ends_at": cls._iso(row.ends_at),
            "evidence_ids": row.evidence_json,
            "requested_by": row.requested_by,
        }
