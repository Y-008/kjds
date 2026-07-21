from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceService
from .pilot_readiness import OZON_PRODUCT_READ_CONTRACT_VERSION
from .pilot_runs import ReadOnlyPilotRunRow
from .sql_repository import Base

CLAIM_TYPES = {
    "product_identity",
    "product_attribute",
    "inventory_observation",
    "price_observation",
}
SENSITIVE_TOKENS = {
    "address",
    "api_key",
    "authorization",
    "credential",
    "customer",
    "email",
    "name",
    "password",
    "phone",
    "secret",
    "token",
}
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
MAX_PAYLOAD_BYTES = 8192


class ReadOnlyClaimRow(Base):
    __tablename__ = "read_only_claims"
    __table_args__ = (
        UniqueConstraint("run_id", "payload_hash", name="uq_read_only_claim_run_payload"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("read_only_pilot_runs.id"), nullable=False)
    claim_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    proposed_by: Mapped[str] = mapped_column(String, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    rationale: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReadOnlyClaimService:
    def __init__(self, *, engine, evidence: EvidenceService) -> None:
        self.engine = engine
        self.evidence = evidence

    def propose(
        self,
        run_id: str,
        *,
        idempotency_key: str,
        claim_type: str,
        payload: dict[str, Any],
        source_state_sha256: str,
        effective_at: str,
        proposed_by: str,
    ) -> dict[str, Any]:
        key = self._text(idempotency_key, "Claim idempotency key", 300)
        normalized_type = claim_type.strip().lower()
        if normalized_type not in CLAIM_TYPES:
            raise ValueError("Unsupported read-only claim type")
        normalized_payload = self._payload(payload)
        state_hash = self._digest(source_state_sha256, "Source state SHA-256")
        effective = self._datetime(effective_at, "effective_at")
        proposer = self._text(proposed_by, "Claim proposer", 120)
        payload_hash = self._hash(normalized_payload)
        request_hash = self._hash(
            {
                "run_id": run_id,
                "claim_type": normalized_type,
                "payload_hash": payload_hash,
                "source_state_sha256": state_hash,
                "effective_at": effective.isoformat(),
                "proposed_by": proposer,
            }
        )
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(ReadOnlyClaimRow).where(ReadOnlyClaimRow.idempotency_key == key)
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ValueError("Claim idempotency key already has different content")
                return self._serialize(existing)
            run = session.get(ReadOnlyPilotRunRow, run_id)
            if run is None:
                raise KeyError(f"Read-only pilot run not found: {run_id}")
            if run.status != "completed" or run.outcome != "succeeded":
                raise ValueError("Claims require a completed successful read-only run")
            if (
                run.operation == "ozon.product.read"
                and (run.summary_json or {}).get("contract_version")
                != OZON_PRODUCT_READ_CONTRACT_VERSION
            ):
                raise ValueError("Claims require a supported Ozon product read contract")
            expected_hash = (run.summary_json or {}).get("state_sha256")
            if expected_hash != state_hash:
                raise ValueError("Claim source state hash does not match the read-only run")
            if not run.evidence_id:
                raise ValueError("Read-only run has no evidence to support a claim")
            row = ReadOnlyClaimRow(
                id=new_id("claim"),
                idempotency_key=key,
                request_hash=request_hash,
                run_id=run_id,
                claim_type=normalized_type,
                payload_json=normalized_payload,
                payload_hash=payload_hash,
                source_state_sha256=state_hash,
                effective_at=effective,
                evidence_id=run.evidence_id,
                status="pending_review",
                proposed_by=proposer,
                reviewed_by=None,
                decision=None,
                rationale=None,
                created_at=now,
                reviewed_at=None,
            )
            session.add(row)
            session.flush()
            claim_id = row.id
            evidence_id = run.evidence_id
        self.evidence.link(
            evidence_id=evidence_id,
            target_type="read_only_claim",
            target_id=claim_id,
            relationship="supports",
            created_by=proposer,
        )
        return self.get(claim_id)

    def review(
        self,
        claim_id: str,
        *,
        decision: str,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"accepted", "rejected"}:
            raise ValueError("Claim decision must be accepted or rejected")
        reviewer = self._text(reviewed_by, "Claim reviewer", 120)
        reason = self._text(rationale, "Claim rationale", 5000)
        with Session(self.engine) as session, session.begin():
            row = self._row(session, claim_id, lock=True)
            if row.status != "pending_review":
                raise ValueError("Only pending claims can be reviewed")
            if reviewer == row.proposed_by:
                raise ValueError("Claim review must be independent from its proposer")
            row.status = normalized_decision
            row.decision = normalized_decision
            row.rationale = reason
            row.reviewed_by = reviewer
            row.reviewed_at = datetime.now(UTC)
        return self.get(claim_id)

    def get(self, claim_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._serialize(self._row(session, claim_id))

    def list(self, *, run_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        query = select(ReadOnlyClaimRow).order_by(ReadOnlyClaimRow.created_at.desc(), ReadOnlyClaimRow.id)
        if run_id:
            query = query.where(ReadOnlyClaimRow.run_id == run_id)
        if status:
            query = query.where(ReadOnlyClaimRow.status == status.strip().lower())
        with Session(self.engine) as session:
            return [self._serialize(row) for row in session.scalars(query)]

    @staticmethod
    def _row(session: Session, claim_id: str, *, lock: bool = False) -> ReadOnlyClaimRow:
        row = session.get(ReadOnlyClaimRow, claim_id, with_for_update=lock)
        if row is None:
            raise KeyError(f"Read-only claim not found: {claim_id}")
        return row

    @classmethod
    def _payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("Claim payload must be a non-empty object")

        def clean(item: Any, depth: int = 0) -> Any:
            if depth > 4:
                raise ValueError("Claim payload is too deeply nested")
            if isinstance(item, dict):
                result: dict[str, Any] = {}
                for raw_key, nested in item.items():
                    key = str(raw_key).strip().lower()
                    if not KEY_PATTERN.fullmatch(key) or any(token in key for token in SENSITIVE_TOKENS):
                        raise ValueError(f"Claim payload contains prohibited field: {raw_key}")
                    result[key] = clean(nested, depth + 1)
                return result
            if isinstance(item, list):
                if len(item) > 100:
                    raise ValueError("Claim payload list is too large")
                return [clean(nested, depth + 1) for nested in item]
            if item is None or isinstance(item, (bool, int, float)):
                return item
            if isinstance(item, str) and len(item) <= 500:
                return item
            raise ValueError("Claim payload contains an unsupported value")

        cleaned = clean(value)
        encoded = json.dumps(cleaned, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise ValueError("Claim payload is too large")
        return cleaned

    @staticmethod
    def _text(value: str, name: str, max_length: int) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        if len(cleaned) > max_length:
            raise ValueError(f"{name} is too long")
        return cleaned

    @classmethod
    def _digest(cls, value: str, name: str) -> str:
        cleaned = cls._text(value, name, 64).lower()
        if len(cleaned) != 64 or any(char not in "0123456789abcdef" for char in cleaned):
            raise ValueError(f"{name} must be a lowercase hexadecimal SHA-256 digest")
        return cleaned

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

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
    def _serialize(row: ReadOnlyClaimRow) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            if value is None:
                return None
            normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            return normalized.isoformat()

        return {
            "id": row.id,
            "run_id": row.run_id,
            "claim_type": row.claim_type,
            "payload": row.payload_json,
            "payload_hash": row.payload_hash,
            "source_state_sha256": row.source_state_sha256,
            "effective_at": iso(row.effective_at),
            "evidence_id": row.evidence_id,
            "status": row.status,
            "proposed_by": row.proposed_by,
            "reviewed_by": row.reviewed_by,
            "decision": row.decision,
            "rationale": row.rationale,
            "created_at": iso(row.created_at),
            "reviewed_at": iso(row.reviewed_at),
            "formal_fact_promoted": False,
        }
