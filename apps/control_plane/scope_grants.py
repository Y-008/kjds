from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade, parse_timestamp
from .security import Principal
from .sql_repository import Base


class ScopeGrantEventRow(Base):
    """Append-only tenant/entity/store authority event."""

    __tablename__ = "scope_grant_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('grant','revoke')",
            name="ck_scope_grant_event_type",
        ),
        UniqueConstraint(
            "tenant_ref",
            "idempotency_key",
            name="uq_scope_grant_event_idempotency",
        ),
        Index(
            "ix_scope_grant_current",
            "tenant_ref",
            "subject_actor_id",
            "store_ref",
            "effective_at",
            "sequence",
        ),
    )

    sequence: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    tenant_ref: Mapped[str] = mapped_column(String, nullable=False)
    entity_ref: Mapped[str] = mapped_column(String, nullable=False)
    store_ref: Mapped[str] = mapped_column(String, nullable=False)
    subject_actor_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"), nullable=False
    )
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ScopeGrantAuthority:
    """Resolve formal entity authority without extending Principal by inference."""

    CONTRACT_ID = "kjds-scope-grant-events-v1"
    ADMISSION_CONTRACT_ID = "kjds-scope-grant-admission-v1"
    ADMISSION_VERIFIER_ID = "scope-grant-admission"
    ADMISSION_VERIFIER_VERSION = "1"
    SOURCE_CONTRACT_ID = "kjds-scope-authority-source-v1"
    REVIEW_CONTRACT_ID = "kjds-scope-authority-review-v1"
    SOURCE_NAME = "scope_authority_source"
    REVIEW_SOURCE_NAME = "scope_authority_review"
    REVIEW_RELATIONSHIP = "scope_authority_review"
    INTAKE_CONTRACT_ID = "kjds-scope-authority-intake-v1"
    INTAKE_VERIFIER_ID = "scope-authority-intake"
    INTAKE_VERIFIER_VERSION = "1"

    def __init__(self, *, engine, evidence) -> None:
        self.engine = engine
        self.evidence = evidence

    def submit_source(
        self,
        *,
        principal: Principal,
        entity_ref: str,
        store_ref: str,
        subject_actor_id: str,
        event_type: str,
        effective_at: str,
        effective_until: str | None,
        idempotency_key: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, Any]:
        values = self._authority_scope_values(
            principal=principal,
            entity_ref=entity_ref,
            store_ref=store_ref,
            subject_actor_id=subject_actor_id,
            event_type=event_type,
            effective_at=effective_at,
        )
        if principal.actor_id == values["subject_actor_id"]:
            raise PermissionError(
                "Scope authority owner source requires an independent subject"
            )
        idempotency_key = self._required(
            idempotency_key,
            "idempotency_key",
            300,
        )
        metadata = {
            "scope_authority_source_contract_id": self.SOURCE_CONTRACT_ID,
            "tenant_ref": values["tenant_ref"],
            "entity_ref": values["entity_ref"],
            "store_ref": values["store_ref"],
            "subject_actor_id": values["subject_actor_id"],
            "scope_decision": values["event_type"],
            "owner_actor_id": principal.actor_id,
            "retention_class": "compliance",
            "legal_hold": False,
        }
        source_ref = (
            f"scope-authority-source://{values['tenant_ref']}/"
            f"{principal.actor_id}/{idempotency_key}"
        )
        existing = self.evidence.find_by_source_ref(
            source=self.SOURCE_NAME,
            source_ref=source_ref,
        )
        if existing is not None:
            self._require_exact_source_replay(
                existing=existing,
                content=content,
                effective_at=values["effective_at"],
                metadata=metadata,
                created_by=principal.actor_id,
            )
            return self._source_projection(existing, idempotent=True)

        source = self.evidence.capture(
            content=content,
            filename=filename,
            content_type=content_type,
            source=self.SOURCE_NAME,
            source_ref=source_ref,
            grade=EvidenceGrade.B,
            effective_at=values["effective_at"].isoformat(),
            effective_until=effective_until,
            created_by=principal.actor_id,
            metadata=metadata,
        )
        self._require_exact_source_replay(
            existing=source,
            content=content,
            effective_at=values["effective_at"],
            metadata=metadata,
            created_by=principal.actor_id,
        )
        return self._source_projection(source, idempotent=False)

    def review_source(
        self,
        *,
        principal: Principal,
        source_evidence_id: str,
        entity_ref: str,
        store_ref: str,
        subject_actor_id: str,
        event_type: str,
        effective_at: str,
        accepted: bool,
        authentic_original: bool,
        owner_authority_verified: bool,
        scope_matches: bool,
        rationale: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        values = self._authority_scope_values(
            principal=principal,
            entity_ref=entity_ref,
            store_ref=store_ref,
            subject_actor_id=subject_actor_id,
            event_type=event_type,
            effective_at=effective_at,
        )
        source_evidence_id = self._required(
            source_evidence_id,
            "source_evidence_id",
            160,
        )
        rationale = self._required(rationale, "rationale", 5000)
        idempotency_key = self._required(
            idempotency_key,
            "idempotency_key",
            300,
        )
        self.evidence.require_current(
            [source_evidence_id],
            as_of=values["effective_at"],
        )
        source = self.evidence.get(source_evidence_id)
        self._validate_source_evidence(source, values)
        if principal.actor_id in {
            source.created_by,
            values["subject_actor_id"],
        }:
            raise PermissionError(
                "Scope authority review requires an independent reviewer"
            )
        checks = {
            "authentic_original": authentic_original,
            "owner_authority_verified": owner_authority_verified,
            "scope_matches": scope_matches,
        }
        if accepted and not all(checks.values()):
            raise ValueError(
                "Accepted scope authority review requires every check to pass"
            )
        payload = {
            "scope_authority_review_contract_id": self.REVIEW_CONTRACT_ID,
            "tenant_ref": values["tenant_ref"],
            "entity_ref": values["entity_ref"],
            "store_ref": values["store_ref"],
            "subject_actor_id": values["subject_actor_id"],
            "scope_decision": values["event_type"],
            "review_decision": "accepted" if accepted else "rejected",
            "source_evidence_id": source.id,
            "source_evidence_sha256": source.sha256,
            "owner_actor_id": source.created_by,
            "reviewed_by": principal.actor_id,
            "rationale": rationale,
            "checks": checks,
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        source_ref = (
            f"scope-authority-review://{values['tenant_ref']}/"
            f"{principal.actor_id}/{idempotency_key}"
        )
        existing = self.evidence.find_by_source_ref(
            source=self.REVIEW_SOURCE_NAME,
            source_ref=source_ref,
        )
        if existing is not None:
            self._require_exact_review_replay(
                existing=existing,
                content=content,
                effective_at=values["effective_at"],
                payload=payload,
                reviewer=principal.actor_id,
            )
            return self._review_projection(
                source=source,
                review=existing,
                idempotent=True,
            )
        review = self.evidence.capture(
            content=content,
            filename=f"{source.id}-scope-authority-review.json",
            content_type="application/json",
            source=self.REVIEW_SOURCE_NAME,
            source_ref=source_ref,
            grade=EvidenceGrade.A,
            effective_at=values["effective_at"].isoformat(),
            effective_until=None,
            created_by=principal.actor_id,
            metadata={
                **payload,
                "retention_class": "compliance",
                "legal_hold": False,
            },
        )
        self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=source.id,
            relationship=self.REVIEW_RELATIONSHIP,
            created_by=principal.actor_id,
        )
        self._require_exact_review_replay(
            existing=review,
            content=content,
            effective_at=values["effective_at"],
            payload=payload,
            reviewer=principal.actor_id,
        )
        return self._review_projection(
            source=source,
            review=review,
            idempotent=False,
        )

    def record(
        self,
        *,
        principal: Principal,
        entity_ref: str,
        store_ref: str,
        subject_actor_id: str,
        event_type: str,
        effective_at: str,
        evidence_id: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        values = self._freeze_values(
            principal=principal,
            entity_ref=entity_ref,
            store_ref=store_ref,
            subject_actor_id=subject_actor_id,
            event_type=event_type,
            effective_at=effective_at,
            evidence_id=evidence_id,
            reason=reason,
            idempotency_key=idempotency_key,
        )
        evidence = self._require_admissible_evidence(values)
        request_sha256 = self._request_sha256(values)
        with Session(self.engine) as session:
            existing = session.scalar(
                select(ScopeGrantEventRow).where(
                    ScopeGrantEventRow.tenant_ref == values["tenant_ref"],
                    ScopeGrantEventRow.idempotency_key
                    == values["idempotency_key"],
                )
            )
            if existing is not None:
                return self._replay(existing, request_sha256)

        now = datetime.now(UTC)
        row = ScopeGrantEventRow(
            id=new_id("sge"),
            **values,
            evidence_sha256=evidence.sha256,
            request_sha256=request_sha256,
            recorded_at=now,
        )
        try:
            with Session(self.engine) as session, session.begin():
                session.add(row)
                session.flush()
                result = self._project(row, idempotent=False)
        except IntegrityError:
            with Session(self.engine) as session:
                existing = session.scalar(
                    select(ScopeGrantEventRow).where(
                        ScopeGrantEventRow.tenant_ref == values["tenant_ref"],
                        ScopeGrantEventRow.idempotency_key
                        == values["idempotency_key"],
                    )
                )
                if existing is None:
                    raise
                result = self._replay(existing, request_sha256)
        return result

    def preflight(
        self,
        *,
        principal: Principal,
        entity_ref: str,
        store_ref: str,
        subject_actor_id: str,
        event_type: str,
        effective_at: str,
        evidence_id: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Verify an exact grant request without recording authority."""

        values = self._freeze_values(
            principal=principal,
            entity_ref=entity_ref,
            store_ref=store_ref,
            subject_actor_id=subject_actor_id,
            event_type=event_type,
            effective_at=effective_at,
            evidence_id=evidence_id,
            reason=reason,
            idempotency_key=idempotency_key,
        )
        request_sha256 = self._request_sha256(values)
        evidence = None
        blocker_codes: list[str] = []
        why = "Exact scope authority Evidence passed admission verification."
        try:
            evidence = self._require_admissible_evidence(values)
        except (KeyError, RuntimeError, ValueError) as exc:
            blocker_codes.append(self._admission_blocker_code(exc))
            why = str(exc) or "Scope authority Evidence failed admission verification."

        existing = None
        with Session(self.engine) as session:
            existing = session.scalar(
                select(ScopeGrantEventRow).where(
                    ScopeGrantEventRow.tenant_ref == values["tenant_ref"],
                    ScopeGrantEventRow.idempotency_key
                    == values["idempotency_key"],
                )
            )
        idempotent_replay = False
        if existing is not None:
            if existing.request_sha256 != request_sha256:
                blocker_codes.append("idempotency_request_conflict")
                why = "Idempotency key conflicts with immutable scope grant event"
            else:
                idempotent_replay = True

        state = "ready" if not blocker_codes else "blocked"
        payload = {
            "contract_id": self.ADMISSION_CONTRACT_ID,
            "verifier": {
                "id": self.ADMISSION_VERIFIER_ID,
                "version": self.ADMISSION_VERIFIER_VERSION,
                "authority": "identity_governance",
            },
            "state": state,
            "freshness": "point_in_time",
            "scope": {
                "tenant_ref": values["tenant_ref"],
                "entity_ref": values["entity_ref"],
                "store_ref": values["store_ref"],
                "subject_actor_id": values["subject_actor_id"],
            },
            "decision": values["event_type"],
            "effective_at": values["effective_at"].isoformat(),
            "evidence": {
                "id": values["evidence_id"],
                "sha256": evidence.sha256 if evidence is not None else None,
                "grade": (
                    evidence.grade.value if evidence is not None else None
                ),
                "created_by": (
                    evidence.created_by if evidence is not None else None
                ),
                "reviewed_by": (
                    evidence.metadata.get("reviewed_by")
                    if evidence is not None
                    else None
                ),
            },
            "request_sha256": request_sha256,
            "blocker_codes": sorted(set(blocker_codes)),
            "why": why,
            "owner": "account_owner+independent_reviewer+compliance",
            "sla_seconds": 86400,
            "next_safe_action": (
                "Record the immutable grant event with an independent compliance "
                "identity."
                if state == "ready"
                else "Submit current exact-scope owner source Evidence, obtain an "
                "accepted independent review Evidence, then rerun this preflight."
            ),
            "existing_event_id": existing.id if existing is not None else None,
            "idempotent_replay": idempotent_replay,
            "would_record_event": state == "ready" and existing is None,
            "event_recorded": False,
            "external_write_allowed": False,
            "approval_created": False,
            "permit_created": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def intake(
        self,
        *,
        principal: Principal,
        subject: Principal,
        store_ref: str,
        entity_ref: str | None,
        event_type: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Project the exact-scope owner/reviewer/preflight handoff without writing."""

        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        cutoff = as_of.astimezone(UTC)
        store = self._required(store_ref, "store_ref", 160)
        entity = (
            self._required(entity_ref, "entity_ref", 160)
            if entity_ref is not None and entity_ref.strip()
            else None
        )
        decision = self._required(event_type, "event_type", 20)
        if decision not in {"grant", "revoke"}:
            raise ValueError("event_type must be grant or revoke")
        if not principal.can_access_store(store):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        if (
            subject.tenant_ref != principal.tenant_ref
            or not subject.can_access_store(store)
        ):
            raise PermissionError(
                "Requested subject is outside authorized tenant/store scope"
            )
        if (
            subject.actor_id != principal.actor_id
            and not principal.has_any_role(
                "reviewer",
                "compliance",
                "risk",
                "monitor",
                "admin",
            )
        ):
            raise PermissionError(
                "Only authority workflow roles may inspect another actor scope"
            )

        allowed_actions = {
            "submit_source": (
                principal.actor_id != subject.actor_id
                and principal.has_any_role("reviewer", "admin")
            ),
            "review_source": (
                principal.actor_id != subject.actor_id
                and principal.has_any_role(
                    "reviewer",
                    "compliance",
                    "risk",
                    "admin",
                )
            ),
            "run_preflight": (
                principal.actor_id != subject.actor_id
                and principal.has_any_role("compliance", "admin")
            ),
            "record_grant": False,
        }
        formal_authority = self.current(
            principal=subject,
            store_ref=store,
            as_of=cutoff,
        )
        candidates: list[dict[str, Any]] = []
        invalid_source_count = 0
        invalid_review_count = 0
        if entity is not None:
            values = {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity,
                "store_ref": store,
                "subject_actor_id": subject.actor_id,
                "event_type": decision,
                "effective_at": cutoff,
            }
            reviews = self.evidence.list_by_source(
                self.REVIEW_SOURCE_NAME,
                limit=2000,
            )
            for source in self.evidence.list_by_source(
                self.SOURCE_NAME,
                limit=2000,
            ):
                if not self._evidence_matches_scope(
                    source,
                    values=values,
                    contract_key="scope_authority_source_contract_id",
                    contract_id=self.SOURCE_CONTRACT_ID,
                ):
                    continue
                if not self._recorded_by(source, cutoff):
                    continue
                try:
                    self.evidence.require_current([source.id], as_of=cutoff)
                    self._validate_source_evidence(source, values)
                except (KeyError, RuntimeError, ValueError):
                    invalid_source_count += 1
                    continue

                lineage_ids = set(
                    self.evidence.target_evidence_ids(
                        target_type="evidence",
                        target_id=source.id,
                        relationship=self.REVIEW_RELATIONSHIP,
                    )
                )
                source_reviews: list[dict[str, Any]] = []
                for review in reviews:
                    if (
                        review.id not in lineage_ids
                        or review.metadata.get("source_evidence_id") != source.id
                        or review.metadata.get("source_evidence_sha256")
                        != source.sha256
                        or not self._evidence_matches_scope(
                            review,
                            values=values,
                            contract_key=(
                                "scope_authority_review_contract_id"
                            ),
                            contract_id=self.REVIEW_CONTRACT_ID,
                        )
                        or not self._recorded_by(review, cutoff)
                    ):
                        continue
                    try:
                        self.evidence.require_current(
                            [review.id],
                            as_of=cutoff,
                        )
                    except (KeyError, RuntimeError, ValueError):
                        invalid_review_count += 1
                        continue
                    review_decision = review.metadata.get("review_decision")
                    checks = review.metadata.get("checks")
                    valid_review = (
                        review.grade == EvidenceGrade.A
                        and review.created_by
                        == review.metadata.get("reviewed_by")
                        and review.created_by
                        not in {source.created_by, subject.actor_id}
                        and review_decision in {"accepted", "rejected"}
                        and isinstance(checks, dict)
                        and set(checks)
                        == {
                            "authentic_original",
                            "owner_authority_verified",
                            "scope_matches",
                        }
                        and bool(
                            str(review.metadata.get("rationale", "")).strip()
                        )
                        and (
                            review_decision == "rejected"
                            or all(value is True for value in checks.values())
                        )
                    )
                    if not valid_review:
                        invalid_review_count += 1
                        continue
                    source_reviews.append(
                        {
                            "id": review.id,
                            "sha256": review.sha256,
                            "decision": review_decision,
                            "reviewed_by": review.created_by,
                            "effective_at": review.effective_at,
                            "recorded_at": review.recorded_at,
                            "lineage_verified": True,
                        }
                    )
                source_reviews.sort(
                    key=lambda item: (
                        item["recorded_at"],
                        item["id"],
                    ),
                    reverse=True,
                )
                has_rejection = any(
                    item["decision"] == "rejected"
                    for item in source_reviews
                )
                accepted = next(
                    (
                        item
                        for item in source_reviews
                        if item["decision"] == "accepted"
                    ),
                    None,
                )
                review_state = (
                    "rejected"
                    if has_rejection
                    else "accepted"
                    if accepted is not None
                    else "pending_independent_review"
                )
                recorder_is_independent = (
                    accepted is not None
                    and principal.actor_id
                    not in {
                        source.created_by,
                        accepted["reviewed_by"],
                        subject.actor_id,
                    }
                )
                candidates.append(
                    {
                        "source_evidence_id": source.id,
                        "source_evidence_sha256": source.sha256,
                        "owner_actor_id": source.created_by,
                        "effective_at": source.effective_at,
                        "recorded_at": source.recorded_at,
                        "review_state": review_state,
                        "reviews": source_reviews,
                        "accepted_review_evidence_id": (
                            accepted["id"]
                            if accepted is not None and not has_rejection
                            else None
                        ),
                        "can_current_actor_review": (
                            allowed_actions["review_source"]
                            and principal.actor_id != source.created_by
                        ),
                        "can_current_actor_preflight": (
                            allowed_actions["run_preflight"]
                            and not has_rejection
                            and recorder_is_independent
                        ),
                    }
                )
            candidates.sort(
                key=lambda item: (
                    item["recorded_at"],
                    item["source_evidence_id"],
                ),
                reverse=True,
            )

        ready_candidates = [
            item
            for item in candidates
            if item["accepted_review_evidence_id"] is not None
        ]
        if entity is None:
            state = "input_required"
            blocker_codes = ["entity_ref_required"]
            why = "An exact legal entity reference is required before Evidence lookup."
            next_safe_action = (
                "Enter the exact legal entity reference for this tenant, subject, and store."
            )
            owner = "account_owner"
        elif invalid_source_count or invalid_review_count:
            state = "blocked"
            blocker_codes = ["scope_authority_evidence_invalid"]
            why = "Exact-scope Evidence exists but failed hash, freshness, or lineage verification."
            next_safe_action = (
                "Repair the immutable Evidence chain; do not record a scope grant."
            )
            owner = "identity_governance"
        elif ready_candidates:
            state = "ready_for_preflight"
            blocker_codes = []
            why = "An accepted independent review is current and lineage-verified."
            next_safe_action = (
                "Use an independent compliance identity to run the zero-write preflight."
            )
            owner = "compliance"
        elif candidates:
            state = "blocked"
            blocker_codes = (
                ["scope_authority_independent_review_rejected"]
                if all(item["review_state"] == "rejected" for item in candidates)
                else ["scope_authority_independent_review_missing"]
            )
            why = "Current exact-scope owner Evidence has no admissible accepted review."
            next_safe_action = (
                "Obtain an independent review from an identity distinct from owner and subject."
            )
            owner = "independent_reviewer"
        else:
            state = "no_data"
            blocker_codes = ["scope_authority_source_missing"]
            why = "No current owner-authored Evidence exists for the exact scope."
            next_safe_action = (
                "Have the authenticated account owner submit immutable source Evidence."
            )
            owner = "account_owner"

        payload = {
            "contract_id": self.INTAKE_CONTRACT_ID,
            "verifier": {
                "id": self.INTAKE_VERIFIER_ID,
                "version": self.INTAKE_VERIFIER_VERSION,
                "authority": "identity_governance",
            },
            "state": state,
            "freshness": "point_in_time",
            "as_of": cutoff.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity,
                "store_ref": store,
                "subject_actor_id": subject.actor_id,
                "event_type": decision,
            },
            "requester": {
                "actor_id": principal.actor_id,
                "roles": sorted(principal.roles),
            },
            "allowed_actions": allowed_actions,
            "formal_authority": formal_authority,
            "candidates": candidates,
            "counts": {
                "sources": len(candidates),
                "reviews": sum(
                    len(item["reviews"])
                    for item in candidates
                ),
                "ready_for_preflight": len(ready_candidates),
                "invalid_sources": invalid_source_count,
                "invalid_reviews": invalid_review_count,
            },
            "blocker_codes": blocker_codes,
            "why": why,
            "owner": owner,
            "sla_seconds": 86400,
            "next_safe_action": next_safe_action,
            "grant_endpoint_exposed": False,
            "grant_created": False,
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def current(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        cutoff = as_of.astimezone(UTC)
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ScopeGrantEventRow)
                    .where(
                        ScopeGrantEventRow.tenant_ref == principal.tenant_ref,
                        ScopeGrantEventRow.store_ref == store_ref,
                        ScopeGrantEventRow.subject_actor_id == principal.actor_id,
                        ScopeGrantEventRow.effective_at <= cutoff,
                    )
                    .order_by(
                        ScopeGrantEventRow.effective_at.desc(),
                        ScopeGrantEventRow.sequence.desc(),
                    )
                )
            )

        latest_by_entity: dict[str, ScopeGrantEventRow] = {}
        for row in rows:
            latest_by_entity.setdefault(row.entity_ref, row)
        active = sorted(
            (row for row in latest_by_entity.values() if row.event_type == "grant"),
            key=lambda row: row.entity_ref,
        )
        authority_sha256 = self._hash(
            [self._event_hash_input(row) for row in sorted(rows, key=lambda r: r.sequence)]
        ) if rows else None
        if not active:
            return {
                "status": "no_data",
                "tenant_ref": principal.tenant_ref,
                "store_ref": store_ref,
                "entity_ref": None,
                "authority": None,
                "authority_sha256": authority_sha256,
                "reason": "entity_scope_authority_missing",
                "active_grant_count": 0,
            }
        if len(active) > 1:
            return {
                "status": "blocked",
                "tenant_ref": principal.tenant_ref,
                "store_ref": store_ref,
                "entity_ref": None,
                "authority": self.CONTRACT_ID,
                "authority_sha256": authority_sha256,
                "reason": "entity_scope_authority_ambiguous",
                "active_grant_count": len(active),
            }
        row = active[0]
        try:
            self.evidence.require_current([row.evidence_id], as_of=cutoff)
            evidence = self.evidence.get(row.evidence_id)
        except (KeyError, RuntimeError, ValueError):
            return {
                "status": "blocked",
                "tenant_ref": principal.tenant_ref,
                "store_ref": store_ref,
                "entity_ref": None,
                "authority": self.CONTRACT_ID,
                "authority_sha256": authority_sha256,
                "reason": "entity_scope_evidence_invalid",
                "active_grant_count": 1,
            }
        try:
            self._validate_evidence_binding(
                evidence,
                {
                    "tenant_ref": row.tenant_ref,
                    "entity_ref": row.entity_ref,
                    "store_ref": row.store_ref,
                    "subject_actor_id": row.subject_actor_id,
                    "event_type": row.event_type,
                    "created_by": row.created_by,
                    "effective_at": cutoff,
                },
            )
        except ValueError:
            return {
                "status": "blocked",
                "tenant_ref": principal.tenant_ref,
                "store_ref": store_ref,
                "entity_ref": None,
                "authority": self.CONTRACT_ID,
                "authority_sha256": authority_sha256,
                "reason": "entity_scope_evidence_invalid",
                "active_grant_count": 1,
            }
        if evidence.sha256 != row.evidence_sha256 or evidence.grade != EvidenceGrade.A:
            return {
                "status": "blocked",
                "tenant_ref": principal.tenant_ref,
                "store_ref": store_ref,
                "entity_ref": None,
                "authority": self.CONTRACT_ID,
                "authority_sha256": authority_sha256,
                "reason": "entity_scope_evidence_invalid",
                "active_grant_count": 1,
            }
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "store_ref": store_ref,
            "entity_ref": row.entity_ref,
            "authority": self.CONTRACT_ID,
            "authority_sha256": authority_sha256,
            "grant_event_id": row.id,
            "grant_effective_at": row.effective_at.isoformat(),
            "evidence_id": row.evidence_id,
            "evidence_sha256": row.evidence_sha256,
            "active_grant_count": 1,
        }

    def events(
        self,
        *,
        principal: Principal,
        store_ref: str,
        subject_actor_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        subject = subject_actor_id or principal.actor_id
        if subject != principal.actor_id and not principal.has_any_role("admin"):
            raise PermissionError("Only admin may inspect another actor scope")
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ScopeGrantEventRow)
                    .where(
                        ScopeGrantEventRow.tenant_ref == principal.tenant_ref,
                        ScopeGrantEventRow.store_ref == store_ref,
                        ScopeGrantEventRow.subject_actor_id == subject,
                    )
                    .order_by(ScopeGrantEventRow.sequence)
                )
            )
        return [self._project(row, idempotent=False) for row in rows]

    def _authority_scope_values(
        self,
        *,
        principal: Principal,
        entity_ref: str,
        store_ref: str,
        subject_actor_id: str,
        event_type: str,
        effective_at: str,
    ) -> dict[str, Any]:
        values = {
            "tenant_ref": self._required(
                principal.tenant_ref,
                "tenant_ref",
                160,
            ),
            "entity_ref": self._required(entity_ref, "entity_ref", 160),
            "store_ref": self._required(store_ref, "store_ref", 160),
            "subject_actor_id": self._required(
                subject_actor_id,
                "subject_actor_id",
                160,
            ),
            "event_type": self._required(event_type, "event_type", 20),
            "effective_at": parse_timestamp(effective_at, "effective_at"),
        }
        if values["event_type"] not in {"grant", "revoke"}:
            raise ValueError("event_type must be grant or revoke")
        if not principal.can_access_store(values["store_ref"]):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        return values

    def _freeze_values(
        self,
        *,
        principal: Principal,
        entity_ref: str,
        store_ref: str,
        subject_actor_id: str,
        event_type: str,
        effective_at: str,
        evidence_id: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope = self._authority_scope_values(
            principal=principal,
            entity_ref=entity_ref,
            store_ref=store_ref,
            subject_actor_id=subject_actor_id,
            event_type=event_type,
            effective_at=effective_at,
        )
        values = {
            **scope,
            "evidence_id": self._required(evidence_id, "evidence_id", 160),
            "reason": self._required(reason, "reason", 2000),
            "idempotency_key": self._required(
                idempotency_key, "idempotency_key", 300
            ),
            "created_by": principal.actor_id,
        }
        if principal.actor_id == values["subject_actor_id"]:
            raise PermissionError(
                "Scope authority changes require an independent actor"
            )
        return values

    def _require_admissible_evidence(self, values: dict[str, Any]):
        self.evidence.require_current(
            [values["evidence_id"]], as_of=values["effective_at"]
        )
        evidence = self.evidence.get(values["evidence_id"])
        if evidence.grade != EvidenceGrade.A:
            raise ValueError("Scope authority requires grade A Evidence")
        self._validate_evidence_binding(evidence, values)
        return evidence

    def _validate_evidence_binding(
        self,
        evidence,
        values: dict[str, Any],
    ) -> None:
        metadata = evidence.metadata
        expected = {
            "scope_authority_review_contract_id": self.REVIEW_CONTRACT_ID,
            "tenant_ref": values["tenant_ref"],
            "entity_ref": values["entity_ref"],
            "store_ref": values["store_ref"],
            "subject_actor_id": values["subject_actor_id"],
            "scope_decision": values["event_type"],
            "review_decision": "accepted",
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError(
                "Accepted scope authority review does not match the frozen grant scope"
            )
        if (
            evidence.source != self.REVIEW_SOURCE_NAME
            or evidence.grade != EvidenceGrade.A
        ):
            raise ValueError(
                "Scope authority requires accepted grade A review Evidence"
            )
        reviewed_by = str(metadata.get("reviewed_by", "")).strip()
        owner_actor_id = str(metadata.get("owner_actor_id", "")).strip()
        source_id = str(metadata.get("source_evidence_id", "")).strip()
        source_sha256 = str(
            metadata.get("source_evidence_sha256", "")
        ).strip()
        recorder = str(values.get("created_by", "")).strip()
        identities = {
            reviewed_by,
            owner_actor_id,
            recorder,
            values["subject_actor_id"],
        }
        if (
            not reviewed_by
            or reviewed_by != evidence.created_by
            or not owner_actor_id
            or not recorder
            or len(identities) != 4
        ):
            raise ValueError(
                "Scope authority requires distinct owner, reviewer, recorder, "
                "and subject identities"
            )
        checks = metadata.get("checks")
        if (
            not isinstance(checks, dict)
            or set(checks)
            != {
                "authentic_original",
                "owner_authority_verified",
                "scope_matches",
            }
            or not all(value is True for value in checks.values())
            or not str(metadata.get("rationale", "")).strip()
        ):
            raise ValueError(
                "Accepted scope authority review checks are incomplete"
            )
        self.evidence.require_current(
            [source_id],
            as_of=values["effective_at"],
        )
        source = self.evidence.get(source_id)
        if source.sha256 != source_sha256:
            raise ValueError("Scope authority source Evidence hash changed")
        self._validate_source_evidence(source, values)
        if source.created_by != owner_actor_id:
            raise ValueError("Scope authority owner identity does not match source")
        review_ids = self.evidence.target_evidence_ids(
            target_type="evidence",
            target_id=source.id,
            relationship=self.REVIEW_RELATIONSHIP,
        )
        if evidence.id not in review_ids:
            raise ValueError(
                "Scope authority review lacks immutable source lineage"
            )
        for review_id in review_ids:
            try:
                self.evidence.require_current(
                    [review_id],
                    as_of=values["effective_at"],
                )
                review = self.evidence.get(review_id)
            except (KeyError, RuntimeError, ValueError):
                continue
            review_metadata = review.metadata
            same_source = (
                review.source == self.REVIEW_SOURCE_NAME
                and review_metadata.get(
                    "scope_authority_review_contract_id"
                )
                == self.REVIEW_CONTRACT_ID
                and review_metadata.get("source_evidence_id") == source.id
                and review_metadata.get("source_evidence_sha256")
                == source.sha256
                and all(
                    review_metadata.get(key) == value
                    for key, value in expected.items()
                    if key != "review_decision"
                )
            )
            if (
                same_source
                and review_metadata.get("review_decision") == "rejected"
            ):
                raise ValueError(
                    "Scope authority source has an independent rejection"
                )

    def _validate_source_evidence(
        self,
        source,
        values: dict[str, Any],
    ) -> None:
        metadata = source.metadata
        expected = {
            "scope_authority_source_contract_id": self.SOURCE_CONTRACT_ID,
            "tenant_ref": values["tenant_ref"],
            "entity_ref": values["entity_ref"],
            "store_ref": values["store_ref"],
            "subject_actor_id": values["subject_actor_id"],
            "scope_decision": values["event_type"],
            "owner_actor_id": source.created_by,
        }
        if (
            source.source != self.SOURCE_NAME
            or source.grade != EvidenceGrade.B
            or any(
                metadata.get(key) != value
                for key, value in expected.items()
            )
            or source.created_by == values["subject_actor_id"]
        ):
            raise ValueError(
                "Scope authority source Evidence does not match the exact owner scope"
            )

    @classmethod
    def _evidence_matches_scope(
        cls,
        evidence,
        *,
        values: dict[str, Any],
        contract_key: str,
        contract_id: str,
    ) -> bool:
        metadata = evidence.metadata
        return (
            metadata.get(contract_key) == contract_id
            and metadata.get("tenant_ref") == values["tenant_ref"]
            and metadata.get("entity_ref") == values["entity_ref"]
            and metadata.get("store_ref") == values["store_ref"]
            and metadata.get("subject_actor_id")
            == values["subject_actor_id"]
            and metadata.get("scope_decision") == values["event_type"]
        )

    @staticmethod
    def _recorded_by(evidence, cutoff: datetime) -> bool:
        recorded_at = datetime.fromisoformat(
            evidence.recorded_at.replace("Z", "+00:00")
        )
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        return recorded_at.astimezone(UTC) <= cutoff

    @classmethod
    def _require_exact_source_replay(
        cls,
        *,
        existing,
        content: bytes,
        effective_at: datetime,
        metadata: dict[str, Any],
        created_by: str,
    ) -> None:
        if (
            existing.sha256 != hashlib.sha256(content).hexdigest()
            or not cls._same_timestamp(
                existing.effective_at,
                effective_at,
            )
            or existing.metadata != metadata
            or existing.created_by != created_by
            or existing.source != cls.SOURCE_NAME
            or existing.grade != EvidenceGrade.B
        ):
            raise ValueError(
                "Scope authority source idempotency key conflicts with "
                "immutable content or scope"
            )

    @classmethod
    def _require_exact_review_replay(
        cls,
        *,
        existing,
        content: bytes,
        effective_at: datetime,
        payload: dict[str, Any],
        reviewer: str,
    ) -> None:
        if (
            existing.sha256 != hashlib.sha256(content).hexdigest()
            or not cls._same_timestamp(
                existing.effective_at,
                effective_at,
            )
            or any(
                existing.metadata.get(key) != value
                for key, value in payload.items()
            )
            or existing.created_by != reviewer
            or existing.source != cls.REVIEW_SOURCE_NAME
            or existing.grade != EvidenceGrade.A
        ):
            raise ValueError(
                "Scope authority review idempotency key conflicts with "
                "immutable decision or scope"
            )

    @classmethod
    def _source_projection(
        cls,
        source,
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        payload = {
            "contract_id": cls.SOURCE_CONTRACT_ID,
            "state": "pending_independent_review",
            "source_evidence_id": source.id,
            "source_evidence_sha256": source.sha256,
            "grade": source.grade.value,
            "created_by": source.created_by,
            "effective_at": source.effective_at,
            "scope": {
                key: source.metadata[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                    "subject_actor_id",
                )
            },
            "scope_decision": source.metadata["scope_decision"],
            "idempotent": idempotent,
            "grant_created": False,
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = cls._hash(payload)
        return payload

    @classmethod
    def _review_projection(
        cls,
        *,
        source,
        review,
        idempotent: bool,
    ) -> dict[str, Any]:
        payload = {
            "contract_id": cls.REVIEW_CONTRACT_ID,
            "state": (
                "accepted"
                if review.metadata["review_decision"] == "accepted"
                else "rejected"
            ),
            "source_evidence_id": source.id,
            "source_evidence_sha256": source.sha256,
            "review_evidence_id": review.id,
            "review_evidence_sha256": review.sha256,
            "reviewed_by": review.created_by,
            "effective_at": review.effective_at,
            "scope": {
                key: review.metadata[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                    "subject_actor_id",
                )
            },
            "scope_decision": review.metadata["scope_decision"],
            "idempotent": idempotent,
            "grant_created": False,
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = cls._hash(payload)
        return payload

    @classmethod
    def _request_sha256(cls, values: dict[str, Any]) -> str:
        request_payload = {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in values.items()
            if key != "idempotency_key"
        }
        return cls._hash(request_payload)

    @staticmethod
    def _admission_blocker_code(exc: Exception) -> str:
        message = str(exc).lower()
        if isinstance(exc, KeyError) or "not found" in message:
            return "scope_authority_evidence_missing"
        if "current" in message or "expired" in message:
            return "scope_authority_evidence_not_current"
        if "grade a" in message:
            return "scope_authority_evidence_not_grade_a"
        if (
            "independent review" in message
            or "accepted grade a review" in message
            or "distinct owner" in message
        ):
            return "scope_authority_independent_review_missing"
        if "does not match" in message:
            return "scope_authority_scope_mismatch"
        return "scope_authority_evidence_invalid"

    @staticmethod
    def _required(value: str, field: str, limit: int) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > limit:
            raise ValueError(f"{field} must be 1 to {limit} characters")
        return normalized

    @staticmethod
    def _same_timestamp(value: str, expected: datetime) -> bool:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if expected.tzinfo is None:
            expected = expected.replace(tzinfo=UTC)
        return parsed.astimezone(UTC) == expected.astimezone(UTC)

    @classmethod
    def _replay(cls, row: ScopeGrantEventRow, request_sha256: str) -> dict[str, Any]:
        if row.request_sha256 != request_sha256:
            raise ValueError("Idempotency key conflicts with immutable scope grant event")
        return cls._project(row, idempotent=True)

    @classmethod
    def _project(cls, row: ScopeGrantEventRow, *, idempotent: bool) -> dict[str, Any]:
        return {
            **cls._event_hash_input(row),
            "sequence": row.sequence,
            "recorded_at": row.recorded_at.isoformat(),
            "request_sha256": row.request_sha256,
            "idempotent": idempotent,
            "immutable": True,
        }

    @staticmethod
    def _event_hash_input(row: ScopeGrantEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "subject_actor_id": row.subject_actor_id,
            "event_type": row.event_type,
            "effective_at": row.effective_at.isoformat(),
            "evidence_id": row.evidence_id,
            "evidence_sha256": row.evidence_sha256,
            "reason": row.reason,
            "idempotency_key": row.idempotency_key,
            "created_by": row.created_by,
        }

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
