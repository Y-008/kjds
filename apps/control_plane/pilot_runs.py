from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .correlation import correlation_id
from .domain import new_id
from .evidence import EvidenceGrade
from .pilot_readiness import (
    IMPLEMENTED_READ_ONLY_OPERATIONS,
    OZON_FINANCE_READ_CONTRACT_VERSION,
    OZON_PRODUCT_READ_CONTRACT_VERSION,
    ReadOnlyPilotRow,
)
from .sql_repository import Base

SENSITIVE_KEY_TOKENS = (
    "address",
    "api_key",
    "authorization",
    "client_id",
    "credential",
    "customer",
    "email",
    "name",
    "password",
    "phone",
    "secret",
    "token",
)
MAX_SUMMARY_BYTES = 8192
ALLOWED_SUMMARY_KEYS = {
    "attribute_item_count",
    "circuit_state",
    "contract_version",
    "connector_error_code",
    "info_item_count",
    "operation_count",
    "page",
    "page_count",
    "page_size",
    "query_window_sha256",
    "retryable",
    "state_sha256",
}


class ResponseEvidenceIntegrityError(ValueError):
    """A non-sensitive, machine-readable raw-response integrity failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Ozon raw response evidence failed integrity verification: {code}")


class ReadOnlyPilotRunRow(Base):
    __tablename__ = "read_only_pilot_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pilot_id: Mapped[str] = mapped_column(ForeignKey("read_only_pilots.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_id: Mapped[str] = mapped_column(String, nullable=False)
    request_id: Mapped[str] = mapped_column(
        String(128), default=lambda: correlation_id(None, "req"), nullable=False
    )
    trace_id: Mapped[str] = mapped_column(
        String(128), default=lambda: correlation_id(None, "trace"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PilotRunService:
    def __init__(self, *, engine, pilots, evidence, lease_seconds: int = 900) -> None:
        if lease_seconds < 30 or lease_seconds > 86_400:
            raise ValueError("Read-only pilot lease must be between 30 and 86400 seconds")
        self.engine = engine
        self.pilots = pilots
        self.evidence = evidence
        self.lease_seconds = lease_seconds

    def capture_response(
        self,
        run_id: str,
        *,
        content: bytes,
        response_sha256: str,
        worker_id: str,
    ):
        if not content:
            raise ValueError("Ozon response evidence cannot be empty")
        worker_id = self._required(worker_id, "Read worker identity")
        response_sha256 = self._sha256(response_sha256)
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != response_sha256:
            raise ValueError("Ozon response evidence SHA-256 does not match content")
        with Session(self.engine) as session:
            row = self._row(session, run_id)
            if row.status not in {"started", "response_captured", "completed"}:
                raise ValueError("Ozon response evidence requires an active or captured read run")
            if row.worker_id != worker_id:
                raise ValueError("Only the worker that started the run can capture its response")
            started_at = self._iso(row.started_at)
        existing_ids = self._raw_response_evidence_ids(run_id)
        if existing_ids:
            return self._verified_raw_response(
                run_id,
                expected_sha256=response_sha256,
                expected_byte_size=len(content),
            )
        captured = self.evidence.capture(
            content=content,
            filename=f"{run_id}-ozon-response.json",
            content_type="application/json",
            source="ozon-isolated-read-worker",
            source_ref=run_id,
            grade=EvidenceGrade.A,
            effective_at=started_at,
            effective_until=None,
            created_by=worker_id,
            metadata={
                "retention_class": "operational",
                "raw_response_stored": True,
                "response_sha256": response_sha256,
            },
        )
        self.evidence.link(
            evidence_id=captured.id,
            target_type="read_only_pilot_run",
            target_id=run_id,
            relationship="raw_response",
            created_by=worker_id,
        )
        return captured

    def checkpoint_success(
        self,
        run_id: str,
        *,
        content: bytes,
        response_sha256: str,
        response_byte_size: int,
        record_count: int,
        summary: dict[str, Any],
        worker_id: str,
    ) -> dict[str, Any]:
        """Persist a successful platform response before any completion acknowledgement."""
        (
            outcome,
            response_sha256,
            response_byte_size,
            record_count,
            safe_summary,
            safe_error,
            worker_id,
        ) = self._completion_values(
            outcome="succeeded",
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=record_count,
            summary=summary,
            error_code=None,
            worker_id=worker_id,
        )
        if len(content) != response_byte_size:
            raise ValueError("Ozon response checkpoint byte size does not match content")
        with Session(self.engine) as session:
            operation = self._row(session, run_id).operation
        self._validate_success_summary(operation, safe_summary, record_count)
        raw_record = self.capture_response(
            run_id,
            content=content,
            response_sha256=response_sha256,
            worker_id=worker_id,
        )
        payload = {
            "outcome": outcome,
            "response_sha256": response_sha256,
            "response_byte_size": response_byte_size,
            "record_count": record_count,
            "summary": safe_summary,
            "error_code": safe_error,
        }
        with Session(self.engine) as session, session.begin():
            row = self._row(session, run_id, lock=True)
            if row.worker_id != worker_id:
                raise ValueError("Only the worker that started the run can checkpoint its response")
            if row.status == "completed":
                if self._completion_payload(row) != payload:
                    raise ValueError("Completed read run is immutable")
                return self._serialize(row)
            if row.status == "expired":
                raise ValueError("Read-only pilot run lease has expired")
            if row.status == "response_captured" and self._completion_payload(row) != payload:
                raise ValueError("Captured read response is immutable")
            if row.status not in {"started", "response_captured"}:
                raise ValueError("Read response checkpoint requires an active run")
            row.status = "response_captured"
            row.outcome = outcome
            row.response_sha256 = response_sha256
            row.response_byte_size = response_byte_size
            row.record_count = record_count
            row.summary_json = safe_summary
            row.error_code = safe_error
        result = self.get(run_id)
        result["checkpoint_evidence_id"] = raw_record.id
        result["recovery_pending"] = True
        return result

    def finalize_captured(
        self,
        run_id: str,
        *,
        worker_id: str,
        completion_actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Complete only from a durable response checkpoint; never contact the platform."""
        worker_id = self._required(worker_id, "Read worker identity")
        with Session(self.engine) as session:
            row = self._row(session, run_id)
            if row.worker_id != worker_id:
                raise ValueError("Only the worker that started the run can finalize its response")
            if row.status == "completed":
                return self._serialize(row)
            if row.status != "response_captured":
                raise ValueError("Read run has no durable response checkpoint")
            payload = self._completion_payload(row)
        return self.complete(
            run_id,
            **payload,
            worker_id=worker_id,
            completion_actor_id=completion_actor_id,
        )

    def start(
        self,
        pilot_id: str,
        *,
        idempotency_key: str,
        operation: str,
        target_ref: str,
        worker_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        idempotency_key = self._required(idempotency_key, "Run idempotency key")
        operation = self._required(operation, "Read operation")
        target_ref = self._required(target_ref, "Read target")
        worker_id = self._required(worker_id, "Read worker identity")
        request_id = correlation_id(request_id, "req")
        trace_id = correlation_id(trace_id, "trace")
        if operation not in IMPLEMENTED_READ_ONLY_OPERATIONS:
            raise ValueError("Read operation has no production-safe worker adapter")
        now = self._datetime(as_of, "as_of") if as_of else datetime.now(UTC)
        target_hash = self._digest(target_ref)
        request_hash = self._hash(
            {
                "pilot_id": pilot_id,
                "operation": operation,
                "target_hash": target_hash,
                "worker_id": worker_id,
            }
        )
        execution_granted = False
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(ReadOnlyPilotRunRow).where(
                    ReadOnlyPilotRunRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ValueError("Run idempotency key already has different content")
                run_id = existing.id
            else:
                pilot_row = session.get(ReadOnlyPilotRow, pilot_id, with_for_update=True)
                if pilot_row is None:
                    raise KeyError(f"Read-only pilot not found: {pilot_id}")
                evaluation = self.pilots.evaluate(pilot_id, as_of=now.isoformat())
                if not evaluation["runtime_allowed"]:
                    raise ValueError(
                        f"Read-only pilot runtime is blocked: {', '.join(evaluation['blockers'])}"
                    )
                if operation not in pilot_row.allowed_operations_json:
                    raise ValueError("Read operation is outside the active pilot contract")
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)
                daily_runs = list(
                    session.scalars(
                        select(ReadOnlyPilotRunRow).where(
                            ReadOnlyPilotRunRow.pilot_id == pilot_id,
                            ReadOnlyPilotRunRow.started_at >= day_start,
                            ReadOnlyPilotRunRow.started_at < day_end,
                        )
                    )
                )
                if len(daily_runs) >= pilot_row.max_daily_requests:
                    raise ValueError("Read-only pilot daily request limit is exhausted")
                target_hashes = {
                    value
                    for value in session.scalars(
                        select(ReadOnlyPilotRunRow.target_hash).where(
                            ReadOnlyPilotRunRow.pilot_id == pilot_id
                        )
                    )
                }
                if target_hash not in target_hashes and len(target_hashes) >= pilot_row.max_targets:
                    raise ValueError("Read-only pilot target limit is exhausted")
                row = ReadOnlyPilotRunRow(
                    id=new_id("ror"),
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    pilot_id=pilot_id,
                    operation=operation,
                    target_hash=target_hash,
                    worker_id=worker_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    status="started",
                    outcome=None,
                    response_sha256=None,
                    response_byte_size=None,
                    record_count=None,
                    summary_json=None,
                    error_code=None,
                    evidence_id=None,
                    started_at=now,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    completed_at=None,
                )
                session.add(row)
                session.flush()
                run_id = row.id
                execution_granted = True
        result = self.get(run_id)
        result["execution_granted"] = execution_granted
        result["idempotency_replay"] = not execution_granted
        return result

    def complete(
        self,
        run_id: str,
        *,
        outcome: str,
        response_sha256: str | None,
        response_byte_size: int,
        record_count: int,
        summary: dict[str, Any],
        error_code: str | None,
        worker_id: str,
        completion_actor_id: str | None = None,
    ) -> dict[str, Any]:
        (
            outcome,
            response_sha256,
            response_byte_size,
            record_count,
            safe_summary,
            safe_error,
            worker_id,
        ) = self._completion_values(
            outcome=outcome,
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=record_count,
            summary=summary,
            error_code=error_code,
            worker_id=worker_id,
        )
        completion_actor_id = self._required(
            completion_actor_id or worker_id, "Completion actor identity"
        )
        payload = {
            "outcome": outcome,
            "response_sha256": response_sha256,
            "response_byte_size": response_byte_size,
            "record_count": record_count,
            "summary": safe_summary,
            "error_code": safe_error,
        }
        with Session(self.engine) as session:
            row = self._row(session, run_id)
            if row.status == "completed":
                if self._completion_payload(row) != payload:
                    raise ValueError("Completed read run is immutable")
                return self._serialize(row)
            if row.status == "expired":
                raise ValueError("Read-only pilot run lease has expired")
            if row.worker_id != worker_id:
                raise ValueError("Only the worker that started the run can complete it")
            if row.status == "response_captured" and self._completion_payload(row) != payload:
                raise ValueError("Captured read response is immutable")
            started_at = self._iso(row.started_at)
            pilot_id = row.pilot_id
            operation = row.operation
        raw_evidence_ids = self._raw_response_evidence_ids(run_id)
        raw_evidence_id = raw_evidence_ids[0] if len(raw_evidence_ids) == 1 else None
        if outcome == "succeeded":
            raw_record = self._verified_raw_response(
                run_id,
                expected_sha256=response_sha256,
                expected_byte_size=response_byte_size,
            )
            raw_evidence_id = raw_record.id
            self._validate_success_summary(operation, safe_summary, record_count)
        envelope = {
            "run_id": run_id,
            "request_id": row.request_id,
            "trace_id": row.trace_id,
            "pilot_id": pilot_id,
            "operation": operation,
            "outcome": outcome,
            "response_sha256": response_sha256,
            "response_byte_size": response_byte_size,
            "record_count": record_count,
            "summary": safe_summary,
            "error_code": safe_error,
            "raw_response_stored": raw_evidence_id is not None,
            "raw_response_evidence_id": raw_evidence_id,
        }
        content = json.dumps(
            envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
        captured = self.evidence.capture(
            content=content,
            filename=f"{run_id}-sanitized-summary.json",
            content_type="application/json",
            source="ozon-isolated-read-worker",
            source_ref=run_id,
            grade=EvidenceGrade.B,
            effective_at=started_at,
            effective_until=None,
            created_by=completion_actor_id,
            metadata={
                "raw_response_stored": raw_evidence_id is not None,
                "raw_response_evidence_id": raw_evidence_id,
                "response_sha256": response_sha256,
            },
        )
        with Session(self.engine) as session, session.begin():
            row = self._row(session, run_id, lock=True)
            if row.status == "completed":
                if self._completion_payload(row) != payload:
                    raise ValueError("Completed read run is immutable")
                return self._serialize(row)
            row.status = "completed"
            row.outcome = outcome
            row.response_sha256 = response_sha256
            row.response_byte_size = response_byte_size
            row.record_count = record_count
            row.summary_json = safe_summary
            row.error_code = safe_error
            row.evidence_id = captured.id
            row.completed_at = datetime.now(UTC)
        self.evidence.link(
            evidence_id=captured.id,
            target_type="read_only_pilot_run",
            target_id=run_id,
            relationship="summarizes",
            created_by=completion_actor_id,
        )
        return self.get(run_id)

    def reap_expired(
        self,
        *,
        as_of: str | None = None,
        limit: int = 100,
        actor_id: str = "pilot-run-reaper",
    ) -> dict[str, Any]:
        """Recover captured responses, then close only truly abandoned started runs."""
        if limit < 1 or limit > 1000:
            raise ValueError("Reaper limit must be between 1 and 1000")
        actor_id = self._required(actor_id, "Reaper identity")
        now = self._datetime(as_of, "as_of") if as_of else datetime.now(UTC)
        with Session(self.engine) as session:
            captured = list(
                session.execute(
                    select(ReadOnlyPilotRunRow.id, ReadOnlyPilotRunRow.worker_id)
                    .where(
                        ReadOnlyPilotRunRow.status == "response_captured",
                        ReadOnlyPilotRunRow.lease_expires_at <= now,
                    )
                    .order_by(ReadOnlyPilotRunRow.lease_expires_at, ReadOnlyPilotRunRow.id)
                    .limit(limit)
                ).all()
            )
        recovered_ids = []
        recovery_blocked_ids: list[str] = []
        recovery_blockers: dict[str, str] = {}
        for run_id, worker_id in captured:
            try:
                self.finalize_captured(
                    run_id,
                    worker_id=worker_id,
                    completion_actor_id=actor_id,
                )
            except ResponseEvidenceIntegrityError as exc:
                recovery_blocked_ids.append(run_id)
                recovery_blockers[run_id] = exc.code
            except ValueError:
                recovery_blocked_ids.append(run_id)
                recovery_blockers[run_id] = "CAPTURED_RESPONSE_INVALID"
            else:
                recovered_ids.append(run_id)
        remaining_limit = max(limit - len(captured), 0)
        with Session(self.engine) as session, session.begin():
            rows = list(
                session.scalars(
                    select(ReadOnlyPilotRunRow)
                    .where(
                        ReadOnlyPilotRunRow.status == "started",
                        ReadOnlyPilotRunRow.lease_expires_at <= now,
                    )
                    .order_by(ReadOnlyPilotRunRow.lease_expires_at, ReadOnlyPilotRunRow.id)
                    .limit(remaining_limit)
                    .with_for_update()
                )
            ) if remaining_limit else []
            run_ids = [row.id for row in rows]
            for row in rows:
                row.status = "expired"
                row.outcome = "failed"
                row.response_sha256 = None
                row.response_byte_size = 0
                row.record_count = 0
                row.summary_json = {"retryable": True}
                row.error_code = "RUN_LEASE_EXPIRED"
                row.completed_at = now
        evidence_ids: dict[str, str] = {}
        for run_id in run_ids:
            content = json.dumps(
                {
                    "run_id": run_id,
                    "outcome": "failed",
                    "error_code": "RUN_LEASE_EXPIRED",
                    "summary": {"retryable": True},
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            captured = self.evidence.capture(
                content=content,
                filename=f"{run_id}-lease-expired.json",
                content_type="application/json",
                source="pilot-run-reaper",
                source_ref=f"{run_id}:lease-expired",
                grade=EvidenceGrade.B,
                effective_at=now.isoformat(),
                effective_until=None,
                created_by=actor_id,
                metadata={"run_lease_expired": True},
            )
            self.evidence.link(
                evidence_id=captured.id,
                target_type="read_only_pilot_run",
                target_id=run_id,
                relationship="lease_expired",
                created_by=actor_id,
            )
            evidence_ids[run_id] = captured.id
        if evidence_ids:
            with Session(self.engine) as session, session.begin():
                for run_id, evidence_id in evidence_ids.items():
                    row = self._row(session, run_id, lock=True)
                    if row.status == "expired" and row.evidence_id is None:
                        row.evidence_id = evidence_id
        return {
            "reaped": len(run_ids),
            "run_ids": run_ids,
            "evidence_ids": evidence_ids,
            "recovered": len(recovered_ids),
            "recovered_run_ids": recovered_ids,
            "recovery_blocked": len(recovery_blocked_ids),
            "recovery_blocked_run_ids": recovery_blocked_ids,
            "recovery_blockers": recovery_blockers,
            "as_of": now.isoformat(),
        }

    def get(self, run_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._serialize(self._row(session, run_id))

    def list(self, *, pilot_id: str | None = None) -> list[dict[str, Any]]:
        query = select(ReadOnlyPilotRunRow).order_by(
            ReadOnlyPilotRunRow.started_at.desc(), ReadOnlyPilotRunRow.id
        )
        if pilot_id:
            query = query.where(ReadOnlyPilotRunRow.pilot_id == pilot_id)
        with Session(self.engine) as session:
            return [self._serialize(row) for row in session.scalars(query)]

    def usage(self, pilot_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        pilot = self.pilots.get(pilot_id)
        now = self._datetime(as_of, "as_of") if as_of else datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ReadOnlyPilotRunRow).where(ReadOnlyPilotRunRow.pilot_id == pilot_id)
                )
            )
        daily = [row for row in rows if day_start <= self._utc(row.started_at) < day_end]
        targets = {row.target_hash for row in rows}
        return {
            "pilot_id": pilot_id,
            "daily_requests_used": len(daily),
            "daily_requests_limit": pilot["max_daily_requests"],
            "targets_used": len(targets),
            "targets_limit": pilot["max_targets"],
            "completed_runs": sum(row.status == "completed" for row in rows),
            "raw_responses_stored": sum(bool(self._raw_response_evidence_ids(row.id)) for row in rows),
        }

    @classmethod
    def _safe_summary(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Read result summary must be an object")

        def clean(item: Any, depth: int = 0) -> Any:
            if depth > 4:
                raise ValueError("Read result summary is too deeply nested")
            if isinstance(item, dict):
                result = {}
                for key, nested in item.items():
                    normalized = str(key).strip().lower()
                    if (
                        not normalized
                        or normalized not in ALLOWED_SUMMARY_KEYS
                        or any(token in normalized for token in SENSITIVE_KEY_TOKENS)
                    ):
                        raise ValueError(f"Read result summary contains prohibited field: {key}")
                    result[normalized] = clean(nested, depth + 1)
                return result
            if isinstance(item, list):
                if len(item) > 100:
                    raise ValueError("Read result summary list is too large")
                return [clean(nested, depth + 1) for nested in item]
            if item is None or isinstance(item, (bool, int, float)):
                return item
            if isinstance(item, str) and len(item) <= 500:
                return item
            raise ValueError("Read result summary contains an unsupported value")

        cleaned = clean(value)
        encoded = json.dumps(cleaned, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_SUMMARY_BYTES:
            raise ValueError("Read result summary is too large")
        return cleaned

    @staticmethod
    def _validate_success_summary(
        operation: str,
        summary: dict[str, Any],
        record_count: int,
    ) -> None:
        if operation == "ozon.finance.read":
            if summary.get("contract_version") != OZON_FINANCE_READ_CONTRACT_VERSION:
                raise ValueError("Ozon finance read summary has an unsupported contract version")
            operation_count = summary.get("operation_count")
            if (
                isinstance(operation_count, bool)
                or not isinstance(operation_count, int)
                or operation_count < 0
                or operation_count != record_count
            ):
                raise ValueError("Ozon finance read record count must match operation_count")
            page = summary.get("page")
            page_size = summary.get("page_size")
            page_count = summary.get("page_count")
            if isinstance(page, bool) or not isinstance(page, int) or page < 1:
                raise ValueError("Ozon finance read summary has an invalid page")
            if (
                isinstance(page_size, bool)
                or not isinstance(page_size, int)
                or not 1 <= page_size <= 1000
            ):
                raise ValueError("Ozon finance read summary has an invalid page_size")
            if page_count is not None and (
                isinstance(page_count, bool)
                or not isinstance(page_count, int)
                or page_count < 0
            ):
                raise ValueError("Ozon finance read summary has an invalid page_count")
            query_hash = summary.get("query_window_sha256")
            if (
                not isinstance(query_hash, str)
                or len(query_hash) != 64
                or any(character not in "0123456789abcdef" for character in query_hash)
            ):
                raise ValueError("Ozon finance read summary requires a query SHA-256")
            return
        if operation != "ozon.product.read":
            return
        if summary.get("contract_version") != OZON_PRODUCT_READ_CONTRACT_VERSION:
            raise ValueError("Ozon product read summary has an unsupported contract version")
        if summary.get("info_item_count") != 1 or summary.get("attribute_item_count") != 1:
            raise ValueError("Ozon product read summary must prove one bound info and attribute item")
        if record_count != 2:
            raise ValueError("Ozon product read record count must match its bound response contract")
        state_hash = summary.get("state_sha256")
        if (
            not isinstance(state_hash, str)
            or len(state_hash) != 64
            or any(character not in "0123456789abcdef" for character in state_hash)
        ):
            raise ValueError("Ozon product read summary requires a state SHA-256")

    @staticmethod
    def _row(session: Session, run_id: str, *, lock: bool = False) -> ReadOnlyPilotRunRow:
        row = session.get(ReadOnlyPilotRunRow, run_id, with_for_update=lock)
        if row is None:
            raise KeyError(f"Read-only pilot run not found: {run_id}")
        return row

    def _serialize(self, row: ReadOnlyPilotRunRow) -> dict[str, Any]:
        raw_evidence_ids = self._raw_response_evidence_ids(row.id)
        raw_response_verified = False
        raw_response_integrity_code = None
        if row.response_sha256 is not None and row.response_byte_size is not None:
            try:
                self._verified_raw_response(
                    row.id,
                    expected_sha256=row.response_sha256,
                    expected_byte_size=row.response_byte_size,
                )
            except ResponseEvidenceIntegrityError as exc:
                raw_response_integrity_code = exc.code
            else:
                raw_response_verified = True
        return {
            "id": row.id,
            "pilot_id": row.pilot_id,
            "operation": row.operation,
            "target_hash": row.target_hash,
            "worker_id": row.worker_id,
            "request_id": row.request_id,
            "trace_id": row.trace_id,
            "status": row.status,
            "outcome": row.outcome,
            "response_sha256": row.response_sha256,
            "response_byte_size": row.response_byte_size,
            "record_count": row.record_count,
            "summary": row.summary_json,
            "error_code": row.error_code,
            "evidence_id": row.evidence_id,
            "started_at": self._iso(row.started_at),
            "lease_expires_at": self._iso(row.lease_expires_at),
            "completed_at": self._iso(row.completed_at) if row.completed_at else None,
            "raw_response_stored": len(raw_evidence_ids) == 1,
            "raw_response_evidence_id": raw_evidence_ids[0] if len(raw_evidence_ids) == 1 else None,
            "raw_response_verified": raw_response_verified,
            "raw_response_integrity_code": raw_response_integrity_code,
            "target_material_stored": False,
            "immutable_after_completion": row.status in {"completed", "expired"},
        }

    @staticmethod
    def _completion_payload(row: ReadOnlyPilotRunRow) -> dict[str, Any]:
        return {
            "outcome": row.outcome,
            "response_sha256": row.response_sha256,
            "response_byte_size": row.response_byte_size,
            "record_count": row.record_count,
            "summary": row.summary_json,
            "error_code": row.error_code,
        }

    def _raw_response_evidence_ids(self, run_id: str) -> list[str]:
        return self.evidence.target_evidence_ids(
            target_type="read_only_pilot_run",
            target_id=run_id,
            relationship="raw_response",
        )

    def _verified_raw_response(
        self,
        run_id: str,
        *,
        expected_sha256: str,
        expected_byte_size: int,
    ):
        evidence_ids = self._raw_response_evidence_ids(run_id)
        if len(evidence_ids) != 1:
            raise ResponseEvidenceIntegrityError("RAW_RESPONSE_LINEAGE_INVALID")
        try:
            record, verification = self.evidence.inspect_integrity(evidence_ids[0])
        except (KeyError, RuntimeError) as exc:
            raise ResponseEvidenceIntegrityError("RAW_RESPONSE_EVIDENCE_MISSING") from exc
        if (
            record.source != "ozon-isolated-read-worker"
            or record.source_ref != run_id
            or record.content_type != "application/json"
            or record.grade != EvidenceGrade.A
            or record.metadata.get("raw_response_stored") is not True
            or record.metadata.get("response_sha256") != expected_sha256
        ):
            raise ResponseEvidenceIntegrityError("RAW_RESPONSE_EVIDENCE_CONTRACT_INVALID")
        if not verification.valid or verification.actual_sha256 != expected_sha256:
            raise ResponseEvidenceIntegrityError("RAW_RESPONSE_EVIDENCE_HASH_MISMATCH")
        if verification.byte_size != expected_byte_size or record.byte_size != expected_byte_size:
            raise ResponseEvidenceIntegrityError("RAW_RESPONSE_EVIDENCE_SIZE_MISMATCH")
        return record

    @classmethod
    def _completion_values(
        cls,
        *,
        outcome: str,
        response_sha256: str | None,
        response_byte_size: int,
        record_count: int,
        summary: dict[str, Any],
        error_code: str | None,
        worker_id: str,
    ) -> tuple[str, str | None, int, int, dict[str, Any], str | None, str]:
        outcome = cls._required(outcome, "Read outcome")
        if outcome not in {"succeeded", "failed"}:
            raise ValueError("Read outcome must be succeeded or failed")
        worker_id = cls._required(worker_id, "Read worker identity")
        if response_byte_size < 0 or record_count < 0:
            raise ValueError("Read byte size and record count cannot be negative")
        if response_sha256 is not None:
            response_sha256 = cls._sha256(response_sha256)
        if outcome == "succeeded" and response_sha256 is None:
            raise ValueError("Successful reads require a response SHA-256")
        safe_summary = cls._safe_summary(summary)
        safe_error = error_code.strip() if error_code else None
        if safe_error and (len(safe_error) > 120 or not safe_error.replace("_", "").isalnum()):
            raise ValueError("Read error code must be a short machine-safe value")
        return (
            outcome,
            response_sha256,
            response_byte_size,
            record_count,
            safe_summary,
            safe_error,
            worker_id,
        )

    @staticmethod
    def _sha256(value: str) -> str:
        digest = str(value).strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("Response SHA-256 must be a lowercase hexadecimal digest")
        return digest

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
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @classmethod
    def _iso(cls, value: datetime) -> str:
        return cls._utc(value).isoformat()

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
