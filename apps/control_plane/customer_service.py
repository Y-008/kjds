from __future__ import annotations

import hashlib
import json
import re
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
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import parse_timestamp
from .security import Principal
from .sql_repository import Base, ProductRow

SCOPE_REQUIRED_SQL = (
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
)
EXECUTION_BINDING_SQL = (
    "("
    "approval_id IS NULL AND command_id IS NULL AND receipt_id IS NULL"
    ") OR ("
    "event_type = 'message_sent_readback' "
    "AND approval_id IS NOT NULL AND length(approval_id) > 0 "
    "AND command_id IS NOT NULL AND length(command_id) > 0 "
    "AND receipt_id IS NOT NULL AND length(receipt_id) > 0"
    ")"
)


class CustomerServiceCaseRow(Base):
    """Immutable non-sensitive identity for one exact-scope service case."""

    __tablename__ = "customer_service_cases"
    __table_args__ = (
        CheckConstraint(
            SCOPE_REQUIRED_SQL,
            name="ck_customer_service_cases_scope_required",
        ),
        CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_customer_service_cases_payload_sha256",
        ),
        Index(
            "uq_customer_service_case_scope_source",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "channel",
            "external_case_ref",
            unique=True,
        ),
        Index(
            "ix_customer_service_case_scope_opened",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "opened_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_case_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    channel: Mapped[str] = mapped_column(String(80), nullable=False)
    order_external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(240), nullable=False)
    locale: Mapped[str] = mapped_column(String(40), nullable=False)
    classification: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=False,
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_evidence_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    scope_as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class CustomerServiceEventRow(Base):
    """Immutable non-sensitive event; message bodies remain in Evidence Blob."""

    __tablename__ = "customer_service_events"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "sequence",
            name="uq_customer_service_event_sequence",
        ),
        UniqueConstraint(
            "case_id",
            "source_event_ref",
            name="uq_customer_service_event_source",
        ),
        CheckConstraint(
            SCOPE_REQUIRED_SQL,
            name="ck_customer_service_events_scope_required",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_customer_service_events_sequence",
        ),
        CheckConstraint(
            "body_sha256 IS NULL OR length(body_sha256) = 64",
            name="ck_customer_service_events_body_sha256",
        ),
        CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_customer_service_events_payload_sha256",
        ),
        CheckConstraint(
            EXECUTION_BINDING_SQL,
            name="ck_customer_service_events_execution_binding",
        ),
        Index(
            "ix_customer_service_event_scope_case",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "case_id",
            "sequence",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("customer_service_cases.id"),
        nullable=False,
    )
    source_event_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(String(40), nullable=False)
    locale: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=False,
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approvals.id"),
        nullable=True,
    )
    # PostgreSQL migration 0079 owns these foreign keys. Keeping the ORM
    # columns shallow avoids forcing unrelated execution tables into narrow
    # metadata-only authority tests.
    command_id: Mapped[str | None] = mapped_column(String, nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_evidence_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    scope_as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class CustomerServiceAuthorityService:
    """Capture exact-scope case/event authority without copying customer PII."""

    CASE_CONTRACT_ID = "kjds-customer-service-case-authority-v1"
    EVENT_CONTRACT_ID = "kjds-customer-service-event-authority-v1"
    SOURCE_CONTRACT_ID = "kjds-customer-service-read-source-v1"
    CHANNELS = frozenset({"ozon", "email", "chat", "phone", "other_authorized"})
    CLASSIFICATIONS = frozenset(
        {
            "product_question",
            "delivery",
            "damage",
            "return",
            "refund",
            "dispute",
            "rma",
            "other",
        }
    )
    PRIORITIES = frozenset({"low", "normal", "high", "urgent"})
    DIRECTIONS = frozenset({"inbound", "outbound", "system"})
    EVENT_TYPES = frozenset(
        {
            "case_opened",
            "triaged",
            "reply_drafted",
            "reply_approval_pending",
            "reply_permit_pending",
            "reply_readback_pending",
            "message_received",
            "message_sent_readback",
            "return_opened",
            "dispute_opened",
            "dispute_resolved",
            "rma_opened",
            "rma_resolved",
            "resolved",
            "closed",
        }
    )
    BODY_REQUIRED_EVENTS = frozenset(
        {
            "reply_drafted",
            "reply_approval_pending",
            "reply_permit_pending",
            "reply_readback_pending",
            "message_received",
            "message_sent_readback",
        }
    )
    _EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    _PHONE_LABEL = re.compile(
        r"\b(?:phone|tel|telephone|mobile|whatsapp|微信|电话|手机)\s*[:：]?\s*"
        r"\+?[\d()\-\s]{7,}",
        re.I,
    )
    _ADDRESS_LABEL = re.compile(
        r"\b(?:address|recipient|customer name|full name)\s*[:：]",
        re.I,
    )

    def __init__(self, *, engine, evidence, scoped_evidence) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence

    def capture_case(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        external_case_ref: str,
        channel: str,
        order_external_id: str,
        product_id: str,
        sku: str,
        locale: str,
        classification: str,
        priority: str,
        evidence_id: str,
        opened_at: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        external_case_ref = self._required(
            external_case_ref, "external_case_ref", 240
        )
        channel = self._choice(channel, "channel", self.CHANNELS)
        order_external_id = self._required(
            order_external_id, "order_external_id", 240
        )
        product_id = self._required(product_id, "product_id", 240)
        sku = self._required(sku, "sku", 240)
        locale = self._required(locale, "locale", 40).lower()
        classification = self._choice(
            classification,
            "classification",
            self.CLASSIFICATIONS,
        )
        priority = self._choice(priority, "priority", self.PRIORITIES)
        opened = parse_timestamp(opened_at, "opened_at")
        if opened > context["cutoff"]:
            raise ValueError("opened_at cannot be later than as_of")
        original = self._require_evidence(
            evidence_id=evidence_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        self._require_product(
            product_id=product_id,
            sku=sku,
            context=context,
        )
        payload = {
            "contract_id": self.CASE_CONTRACT_ID,
            "external_case_ref": external_case_ref,
            "channel": channel,
            "order_external_id": order_external_id,
            "product_id": product_id,
            "sku": sku,
            "locale": locale,
            "classification": classification,
            "priority": priority,
            "evidence_id": evidence_id,
            "evidence_sha256": original.sha256,
            "opened_at": opened.isoformat(),
            "scope": context["scope"],
        }
        payload_sha256 = self._hash(payload)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(
                select(CustomerServiceCaseRow).where(
                    CustomerServiceCaseRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    CustomerServiceCaseRow.entity_ref
                    == context["scope"]["entity_ref"],
                    CustomerServiceCaseRow.store_ref
                    == context["scope"]["store_ref"],
                    CustomerServiceCaseRow.channel == channel,
                    CustomerServiceCaseRow.external_case_ref
                    == external_case_ref,
                )
            )
            if existing is not None:
                if existing.payload_sha256 != payload_sha256:
                    raise ValueError(
                        "Customer-service case identity conflicts with immutable values"
                    )
                return self._case(existing, idempotent=True)
            row = CustomerServiceCaseRow(
                id=new_id("csc"),
                external_case_ref=external_case_ref,
                channel=channel,
                order_external_id=order_external_id,
                product_id=product_id,
                sku=sku,
                locale=locale,
                classification=classification,
                priority=priority,
                evidence_id=evidence_id,
                payload_sha256=payload_sha256,
                opened_at=opened,
                recorded_at=datetime.now(UTC),
                created_by=principal.actor_id,
                source_evidence_sha256=original.sha256,
                scope_as_of=context["cutoff"],
                **context["scope"],
            )
            session.add(row)
            session.flush()
            return self._case(row, idempotent=False)

    def append_event(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        case_id: str,
        source_event_ref: str,
        sequence: int,
        event_type: str,
        direction: str,
        locale: str,
        summary: str,
        body_sha256: str | None,
        evidence_id: str,
        effective_at: str,
        approval_id: str | None = None,
        command_id: str | None = None,
        receipt_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        case_id = self._required(case_id, "case_id", 240)
        source_event_ref = self._required(
            source_event_ref, "source_event_ref", 240
        )
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("sequence must be a positive integer")
        event_type = self._choice(event_type, "event_type", self.EVENT_TYPES)
        direction = self._choice(direction, "direction", self.DIRECTIONS)
        locale = self._required(locale, "locale", 40).lower()
        summary = self._safe_summary(summary)
        normalized_body = self._optional_sha256(body_sha256, "body_sha256")
        if event_type in self.BODY_REQUIRED_EVENTS and normalized_body is None:
            raise ValueError(f"{event_type} requires body_sha256")
        execution = tuple(
            self._optional(value, field, 240)
            for value, field in (
                (approval_id, "approval_id"),
                (command_id, "command_id"),
                (receipt_id, "receipt_id"),
            )
        )
        if event_type == "message_sent_readback":
            if any(value is None for value in execution):
                raise ValueError(
                    "message_sent_readback requires approval, command and receipt"
                )
            if direction != "outbound":
                raise ValueError("message_sent_readback must be outbound")
        elif any(value is not None for value in execution):
            raise ValueError(
                "Execution authority is allowed only on message_sent_readback"
            )
        effective = parse_timestamp(effective_at, "effective_at")
        if effective > context["cutoff"]:
            raise ValueError("effective_at cannot be later than as_of")
        original = self._require_evidence(
            evidence_id=evidence_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            case = session.get(CustomerServiceCaseRow, case_id)
            if case is None or not self._row_matches(case, context):
                raise KeyError(f"Unknown exact-scope customer-service case: {case_id}")
            if effective < self._aware(case.opened_at):
                raise ValueError("Customer-service event predates its case")
            payload = {
                "contract_id": self.EVENT_CONTRACT_ID,
                "case_id": case_id,
                "source_event_ref": source_event_ref,
                "sequence": sequence,
                "event_type": event_type,
                "direction": direction,
                "locale": locale,
                "summary": summary,
                "body_sha256": normalized_body,
                "evidence_id": evidence_id,
                "evidence_sha256": original.sha256,
                "effective_at": effective.isoformat(),
                "approval_id": execution[0],
                "command_id": execution[1],
                "receipt_id": execution[2],
                "scope": context["scope"],
            }
            payload_sha256 = self._hash(payload)
            by_source = session.scalar(
                select(CustomerServiceEventRow).where(
                    CustomerServiceEventRow.case_id == case_id,
                    CustomerServiceEventRow.source_event_ref == source_event_ref,
                )
            )
            if by_source is not None:
                if by_source.payload_sha256 != payload_sha256:
                    raise ValueError(
                        "Customer-service source event conflicts with immutable values"
                    )
                return self._event(by_source, idempotent=True)
            by_sequence = session.scalar(
                select(CustomerServiceEventRow).where(
                    CustomerServiceEventRow.case_id == case_id,
                    CustomerServiceEventRow.sequence == sequence,
                )
            )
            if by_sequence is not None:
                raise ValueError("Customer-service event sequence already exists")
            latest = session.scalar(
                select(CustomerServiceEventRow)
                .where(CustomerServiceEventRow.case_id == case_id)
                .order_by(
                    CustomerServiceEventRow.sequence.desc(),
                    CustomerServiceEventRow.id.desc(),
                )
                .limit(1)
            )
            expected = 1 if latest is None else latest.sequence + 1
            if sequence != expected:
                raise ValueError(
                    f"Customer-service event sequence must be {expected}"
                )
            if latest is None and event_type != "case_opened":
                raise ValueError("First customer-service event must be case_opened")
            if latest is not None and effective < self._aware(latest.effective_at):
                raise ValueError("Customer-service event time moved backwards")
            row = CustomerServiceEventRow(
                id=new_id("csev"),
                case_id=case_id,
                source_event_ref=source_event_ref,
                sequence=sequence,
                event_type=event_type,
                direction=direction,
                locale=locale,
                summary=summary,
                body_sha256=normalized_body,
                evidence_id=evidence_id,
                payload_sha256=payload_sha256,
                effective_at=effective,
                recorded_at=datetime.now(UTC),
                created_by=principal.actor_id,
                approval_id=execution[0],
                command_id=execution[1],
                receipt_id=execution[2],
                source_evidence_sha256=original.sha256,
                scope_as_of=context["cutoff"],
                **context["scope"],
            )
            session.add(row)
            session.flush()
            return self._event(row, idempotent=False)

    def read_scoped_sources(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
        max_cases: int = 5000,
        max_events: int = 20_000,
    ) -> dict[str, Any]:
        context = self._read_context(
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            scope_grant_authority_sha256=scope_grant_authority_sha256,
            as_of=as_of,
        )
        if not 1 <= max_cases <= 50_000:
            raise ValueError("max_cases must be between 1 and 50000")
        if not 1 <= max_events <= 100_000:
            raise ValueError("max_events must be between 1 and 100000")
        cutoff = context["cutoff"]
        with Session(self.engine) as session:
            cases = list(
                session.scalars(
                    select(CustomerServiceCaseRow)
                    .where(
                        CustomerServiceCaseRow.tenant_ref
                        == context["scope"]["tenant_ref"],
                        CustomerServiceCaseRow.entity_ref
                        == context["scope"]["entity_ref"],
                        CustomerServiceCaseRow.store_ref
                        == context["scope"]["store_ref"],
                        CustomerServiceCaseRow.scope_grant_authority_sha256
                        == context["scope"]["scope_grant_authority_sha256"],
                        CustomerServiceCaseRow.opened_at <= cutoff,
                        CustomerServiceCaseRow.recorded_at <= cutoff,
                        CustomerServiceCaseRow.scope_as_of <= cutoff,
                    )
                    .order_by(
                        CustomerServiceCaseRow.opened_at,
                        CustomerServiceCaseRow.recorded_at,
                        CustomerServiceCaseRow.id,
                    )
                    .limit(max_cases + 1)
                ).all()
            )
            case_ids = [row.id for row in cases[:max_cases]]
            events = (
                list(
                    session.scalars(
                        select(CustomerServiceEventRow)
                        .where(
                            CustomerServiceEventRow.case_id.in_(case_ids),
                            CustomerServiceEventRow.tenant_ref
                            == context["scope"]["tenant_ref"],
                            CustomerServiceEventRow.entity_ref
                            == context["scope"]["entity_ref"],
                            CustomerServiceEventRow.store_ref
                            == context["scope"]["store_ref"],
                            CustomerServiceEventRow.scope_grant_authority_sha256
                            == context["scope"][
                                "scope_grant_authority_sha256"
                            ],
                            CustomerServiceEventRow.effective_at <= cutoff,
                            CustomerServiceEventRow.recorded_at <= cutoff,
                            CustomerServiceEventRow.scope_as_of <= cutoff,
                        )
                        .order_by(
                            CustomerServiceEventRow.case_id,
                            CustomerServiceEventRow.sequence,
                            CustomerServiceEventRow.id,
                        )
                        .limit(max_events + 1)
                    ).all()
                )
                if case_ids
                else []
            )
        payload = {
            "contract_id": self.SOURCE_CONTRACT_ID,
            "as_of": cutoff.isoformat(),
            "scope": context["scope"],
            "cases": [self._case_source(row) for row in cases[:max_cases]],
            "events": [self._event_source(row) for row in events[:max_events]],
            "truncated": {
                "cases": len(cases) > max_cases,
                "events": len(events) > max_events,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _require_evidence(
        self,
        *,
        evidence_id: str,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
    ):
        evidence_id = self._required(evidence_id, "evidence_id", 240)
        self.evidence.require_current([evidence_id], as_of=context["cutoff"])
        original = self.evidence.get(evidence_id)
        projection = self.scoped_evidence.project_targets(
            evidence_ids=[evidence_id],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
        )
        target = next(
            (
                item
                for item in projection.get("records", [])
                if item.get("evidence_id", item.get("id")) == evidence_id
            ),
            None,
        )
        if (
            projection.get("status") != "ready"
            or target is None
            or (
                target.get("status")
                or (target.get("scope_binding") or {}).get("status")
            )
            != "ready"
        ):
            raise ValueError(
                "Customer-service Evidence is not exact-scope ready"
            )
        return original

    def _require_product(
        self,
        *,
        product_id: str,
        sku: str,
        context: dict[str, Any],
    ) -> None:
        cutoff = context["cutoff"]
        scope = context["scope"]
        with Session(self.engine) as session:
            product = session.get(ProductRow, product_id)
            if (
                product is None
                or product.sku != sku
                or product.tenant_ref != scope["tenant_ref"]
                or product.entity_ref != scope["entity_ref"]
                or product.store_ref != scope["store_ref"]
                or product.scope_grant_authority_sha256
                != scope["scope_grant_authority_sha256"]
                or product.scope_as_of is None
                or self._aware(product.scope_as_of) > cutoff
                or self._aware(product.created_at) > cutoff
            ):
                raise ValueError(
                    "Customer-service case Product/SKU authority is invalid"
                )

    @classmethod
    def _context(
        cls,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: str | None,
    ) -> dict[str, Any]:
        store = cls._required(store_ref, "store_ref", 160)
        if not principal.can_access_store(store):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = str(entity_scope.get("authority_sha256") or "").strip().lower()
        if (
            entity_scope.get("status") != "ready"
            or not entity_ref
            or not cls._sha256(authority)
        ):
            raise ValueError("Exact entity scope authority is required")
        cutoff = parse_timestamp(
            as_of or datetime.now(UTC).isoformat(),
            "as_of",
        )
        return {
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_ref,
                "store_ref": store,
                "scope_grant_authority_sha256": authority,
            },
        }

    @classmethod
    def _read_context(
        cls,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
    ) -> dict[str, Any]:
        authority = str(scope_grant_authority_sha256 or "").strip().lower()
        if not cls._sha256(authority):
            raise ValueError("scope_grant_authority_sha256 must be SHA-256")
        return {
            "cutoff": parse_timestamp(as_of, "as_of"),
            "scope": {
                "tenant_ref": cls._required(tenant_ref, "tenant_ref", 160),
                "entity_ref": cls._required(entity_ref, "entity_ref", 160),
                "store_ref": cls._required(store_ref, "store_ref", 160),
                "scope_grant_authority_sha256": authority,
            },
        }

    @classmethod
    def _safe_summary(cls, value: str) -> str:
        summary = cls._required(value, "summary", 500)
        if (
            cls._EMAIL.search(summary)
            or cls._PHONE_LABEL.search(summary)
            or cls._ADDRESS_LABEL.search(summary)
        ):
            raise ValueError("summary must not contain customer PII")
        return summary

    @classmethod
    def _row_matches(cls, row, context: dict[str, Any]) -> bool:
        scope = context["scope"]
        return bool(
            row.tenant_ref == scope["tenant_ref"]
            and row.entity_ref == scope["entity_ref"]
            and row.store_ref == scope["store_ref"]
            and row.scope_grant_authority_sha256
            == scope["scope_grant_authority_sha256"]
            and cls._aware(row.scope_as_of) <= context["cutoff"]
            and cls._aware(row.recorded_at) <= context["cutoff"]
        )

    @classmethod
    def _case(cls, row: CustomerServiceCaseRow, *, idempotent: bool) -> dict[str, Any]:
        return {**cls._case_source(row), "idempotent": idempotent}

    @classmethod
    def _case_source(cls, row: CustomerServiceCaseRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "external_case_ref": row.external_case_ref,
            "channel": row.channel,
            "order_external_id": row.order_external_id,
            "product_id": row.product_id,
            "sku": row.sku,
            "locale": row.locale,
            "classification": row.classification,
            "priority": row.priority,
            "evidence_id": row.evidence_id,
            "payload_sha256": row.payload_sha256,
            "opened_at": cls._aware(row.opened_at).isoformat(),
            "recorded_at": cls._aware(row.recorded_at).isoformat(),
            "created_by": row.created_by,
            "source_evidence_sha256": row.source_evidence_sha256,
            "scope_as_of": cls._aware(row.scope_as_of).isoformat(),
        }

    @classmethod
    def _event(cls, row: CustomerServiceEventRow, *, idempotent: bool) -> dict[str, Any]:
        return {**cls._event_source(row), "idempotent": idempotent}

    @classmethod
    def _event_source(cls, row: CustomerServiceEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "case_id": row.case_id,
            "source_event_ref": row.source_event_ref,
            "sequence": row.sequence,
            "event_type": row.event_type,
            "direction": row.direction,
            "locale": row.locale,
            "summary": row.summary,
            "body_sha256": row.body_sha256,
            "evidence_id": row.evidence_id,
            "payload_sha256": row.payload_sha256,
            "effective_at": cls._aware(row.effective_at).isoformat(),
            "recorded_at": cls._aware(row.recorded_at).isoformat(),
            "created_by": row.created_by,
            "approval_id": row.approval_id,
            "command_id": row.command_id,
            "receipt_id": row.receipt_id,
            "source_evidence_sha256": row.source_evidence_sha256,
            "scope_as_of": cls._aware(row.scope_as_of).isoformat(),
        }

    @staticmethod
    def _required(value: Any, field: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > limit:
            raise ValueError(f"{field} must be 1 to {limit} characters")
        return normalized

    @classmethod
    def _choice(cls, value: str, field: str, allowed: frozenset[str]) -> str:
        normalized = cls._required(value, field, 80).lower()
        if normalized not in allowed:
            raise ValueError(f"{field} is unsupported")
        return normalized

    @classmethod
    def _optional(cls, value: str | None, field: str, limit: int) -> str | None:
        if value is None or not str(value).strip():
            return None
        return cls._required(value, field, limit)

    @classmethod
    def _optional_sha256(cls, value: str | None, field: str) -> str | None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        if not cls._sha256(normalized):
            raise ValueError(f"{field} must be SHA-256")
        return normalized

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value.lower()
        )

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
