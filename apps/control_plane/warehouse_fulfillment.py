from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import parse_timestamp
from .security import Principal
from .sql_repository import ApprovalRow, Base, ProductRow

SCOPE_REQUIRED_SQL = (
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND warehouse_ref IS NOT NULL AND length(warehouse_ref) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND source_payload_sha256 IS NOT NULL "
    "AND length(source_payload_sha256) = 64 "
    "AND payload_sha256 IS NOT NULL AND length(payload_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
)
EXECUTION_BINDING_SQL = (
    "("
    "event_type NOT IN ("
    "'inventory_adjustment_readback',"
    "'outbound_confirmed_readback',"
    "'label_purchased_readback',"
    "'carrier_handoff_readback'"
    ") "
    "AND approval_id IS NULL AND command_id IS NULL AND receipt_id IS NULL "
    "AND kill_switch_evidence_id IS NULL "
    "AND compensation_evidence_id IS NULL"
    ") OR ("
    "event_type IN ("
    "'inventory_adjustment_readback',"
    "'outbound_confirmed_readback',"
    "'label_purchased_readback',"
    "'carrier_handoff_readback'"
    ") "
    "AND approval_id IS NOT NULL AND length(approval_id) > 0 "
    "AND command_id IS NOT NULL AND length(command_id) > 0 "
    "AND receipt_id IS NOT NULL AND length(receipt_id) > 0 "
    "AND kill_switch_evidence_id IS NOT NULL "
    "AND compensation_evidence_id IS NOT NULL"
    ")"
)


class WarehouseExecutionEventRow(Base):
    """Immutable warehouse execution event; upstream truths remain references."""

    __tablename__ = "warehouse_execution_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
            "source_event_ref",
            name="uq_warehouse_execution_source_event",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
            "aggregate_ref",
            "sequence",
            name="uq_warehouse_execution_aggregate_sequence",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
            "command_id",
            name="uq_warehouse_execution_command",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
            "receipt_id",
            name="uq_warehouse_execution_receipt",
        ),
        CheckConstraint(
            SCOPE_REQUIRED_SQL,
            name="ck_warehouse_execution_scope_required",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_warehouse_execution_sequence",
        ),
        CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ck_warehouse_execution_quantity",
        ),
        CheckConstraint(
            "weight_kg IS NULL OR length(weight_kg) > 0",
            name="ck_warehouse_execution_weight",
        ),
        CheckConstraint(
            EXECUTION_BINDING_SQL,
            name="ck_warehouse_execution_governance_binding",
        ),
        Index(
            "ix_warehouse_execution_scope_order",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "warehouse_ref",
            "order_external_id",
            "effective_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_event_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    aggregate_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    order_external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(240), nullable=False)
    location_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    bin_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    lot_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    wave_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    parcel_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    label_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[str | None] = mapped_column(String(48), nullable=True)
    weight_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    carrier_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    service_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=False,
    )
    source_payload_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approvals.id"),
        nullable=True,
    )
    command_id: Mapped[str | None] = mapped_column(String, nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kill_switch_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=True,
    )
    compensation_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=True,
    )
    effective_at: Mapped[datetime] = mapped_column(
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
    warehouse_ref: Mapped[str] = mapped_column(String(160), nullable=False)
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


class WarehouseExecutionAuthorityService:
    """Append-only exact-scope authority for warehouse execution observations."""

    EVENT_CONTRACT_ID = "kjds-warehouse-execution-event-authority-v1"
    SOURCE_CONTRACT_ID = "kjds-warehouse-execution-read-source-v1"
    SOURCE_EVIDENCE_CONTRACT_ID = (
        "kjds-formal-warehouse-event-evidence-v1"
    )
    AUTHORIZATION_CONTRACT_ID = (
        "kjds-authorized-warehouse-adapter-v1"
    )
    PERMIT_CONTRACT_ID = "kjds-warehouse-one-time-permit-v1"
    READBACK_CONTRACT_ID = "kjds-warehouse-execution-readback-v1"
    SOURCE_KINDS = frozenset(
        {
            "official_public_api",
            "authorized_formal_export",
            "authorized_warehouse_system",
        }
    )
    EVENT_TYPES = frozenset(
        {
            "location_registered",
            "bin_registered",
            "lot_received",
            "reservation_created",
            "reservation_released",
            "wave_created",
            "wave_order_added",
            "pick_scanned",
            "pack_scanned",
            "parcel_created",
            "label_bound",
            "weight_scanned",
            "inventory_adjustment_readback",
            "outbound_confirmed_readback",
            "label_purchased_readback",
            "carrier_handoff_readback",
            "exception_recorded",
        }
    )
    GOVERNED_EVENTS = frozenset(
        {
            "inventory_adjustment_readback",
            "outbound_confirmed_readback",
            "label_purchased_readback",
            "carrier_handoff_readback",
        }
    )
    GOVERNED_ACTION_IDS = {
        "inventory_adjustment_readback": "warehouse_inventory_adjustment",
        "outbound_confirmed_readback": "warehouse_outbound_confirm",
        "label_purchased_readback": "warehouse_label_purchase",
        "carrier_handoff_readback": "warehouse_carrier_handoff",
    }
    WEIGHT_SOURCES = frozenset(
        {
            "authorized_scale_readback",
            "official_carrier_readback",
            "authorized_formal_export",
        }
    )

    def __init__(self, *, engine, evidence, scoped_evidence) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence

    def append_event(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        warehouse_ref: str,
        source_event_ref: str,
        aggregate_ref: str,
        sequence: int,
        event_type: str,
        order_external_id: str,
        product_id: str,
        sku: str,
        evidence_id: str,
        effective_at: str,
        location_ref: str | None = None,
        bin_ref: str | None = None,
        lot_ref: str | None = None,
        wave_ref: str | None = None,
        parcel_ref: str | None = None,
        label_ref: str | None = None,
        quantity: int | None = None,
        weight_kg: str | None = None,
        weight_source: str | None = None,
        carrier_ref: str | None = None,
        service_ref: str | None = None,
        approval_id: str | None = None,
        command_id: str | None = None,
        receipt_id: str | None = None,
        kill_switch_evidence_id: str | None = None,
        compensation_evidence_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            warehouse_ref=warehouse_ref,
            as_of=as_of,
        )
        source_event_ref = self._required(
            source_event_ref,
            "source_event_ref",
            240,
        )
        aggregate_ref = self._required(
            aggregate_ref,
            "aggregate_ref",
            240,
        )
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise ValueError("sequence must be a positive integer")
        if sequence < 1:
            raise ValueError("sequence must be a positive integer")
        event_type = self._choice(
            event_type,
            "event_type",
            self.EVENT_TYPES,
        )
        order_external_id = self._required(
            order_external_id,
            "order_external_id",
            240,
        )
        product_id = self._required(product_id, "product_id", 240)
        sku = self._required(sku, "sku", 240)
        effective = parse_timestamp(effective_at, "effective_at")
        if effective > context["cutoff"]:
            raise ValueError("effective_at cannot be later than as_of")
        normalized = {
            "location_ref": self._optional(location_ref, "location_ref"),
            "bin_ref": self._optional(bin_ref, "bin_ref"),
            "lot_ref": self._optional(lot_ref, "lot_ref"),
            "wave_ref": self._optional(wave_ref, "wave_ref"),
            "parcel_ref": self._optional(parcel_ref, "parcel_ref"),
            "label_ref": self._optional(label_ref, "label_ref"),
            "carrier_ref": self._optional(carrier_ref, "carrier_ref"),
            "service_ref": self._optional(service_ref, "service_ref"),
        }
        if quantity is not None and (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 1
        ):
            raise ValueError("quantity must be a positive integer")
        normalized_weight = self._weight(weight_kg)
        normalized_weight_source = self._optional(
            weight_source,
            "weight_source",
            80,
        )
        if (normalized_weight is None) != (normalized_weight_source is None):
            raise ValueError("weight and weight_source must be bound together")
        if (
            normalized_weight_source is not None
            and normalized_weight_source not in self.WEIGHT_SOURCES
        ):
            raise ValueError("weight_source is not formally authorized")
        governance = {
            "approval_id": self._optional(approval_id, "approval_id"),
            "command_id": self._optional(command_id, "command_id"),
            "receipt_id": self._optional(receipt_id, "receipt_id"),
            "kill_switch_evidence_id": self._optional(
                kill_switch_evidence_id,
                "kill_switch_evidence_id",
            ),
            "compensation_evidence_id": self._optional(
                compensation_evidence_id,
                "compensation_evidence_id",
            ),
        }
        if event_type in self.GOVERNED_EVENTS:
            if any(value is None for value in governance.values()):
                raise ValueError(
                    f"{event_type} requires Approval, one-time Permit, "
                    "Readback, Kill Switch and Compensation Evidence"
                )
        elif any(value is not None for value in governance.values()):
            raise ValueError(
                "Execution bindings are allowed only on governed Readback events"
            )
        evidence = self._require_source_evidence(
            evidence_id=evidence_id,
            event_type=event_type,
            source_event_ref=source_event_ref,
            aggregate_ref=aggregate_ref,
            order_external_id=order_external_id,
            product_id=product_id,
            sku=sku,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        if event_type in self.GOVERNED_EVENTS:
            self._require_governance_evidence(
                governance=governance,
                event_type=event_type,
                source_event_ref=source_event_ref,
                order_external_id=order_external_id,
                effective_at=effective,
                source_evidence=evidence,
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
            "contract_id": self.EVENT_CONTRACT_ID,
            "source_event_ref": source_event_ref,
            "aggregate_ref": aggregate_ref,
            "sequence": sequence,
            "event_type": event_type,
            "order_external_id": order_external_id,
            "product_id": product_id,
            "sku": sku,
            **normalized,
            "quantity": quantity,
            "weight_kg": normalized_weight,
            "weight_source": normalized_weight_source,
            "evidence_id": evidence.id,
            "evidence_sha256": evidence.sha256,
            **governance,
            "effective_at": effective.isoformat(),
            "scope": context["scope"],
        }
        payload_sha256 = self._hash(payload)
        source_payload_sha256 = str(
            evidence.metadata.get("event_payload_sha256") or ""
        ).lower()
        with Session(
            self.engine,
            expire_on_commit=False,
        ) as session, session.begin():
            existing = session.scalar(
                select(WarehouseExecutionEventRow).where(
                    WarehouseExecutionEventRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    WarehouseExecutionEventRow.entity_ref
                    == context["scope"]["entity_ref"],
                    WarehouseExecutionEventRow.store_ref
                    == context["scope"]["store_ref"],
                    WarehouseExecutionEventRow.warehouse_ref
                    == context["scope"]["warehouse_ref"],
                    WarehouseExecutionEventRow.source_event_ref
                    == source_event_ref,
                )
            )
            if existing is not None:
                if existing.payload_sha256 != payload_sha256:
                    raise ValueError(
                        "Warehouse source event conflicts with immutable values"
                    )
                return self._event(existing, idempotent=True)
            latest = session.scalar(
                select(WarehouseExecutionEventRow)
                .where(
                    WarehouseExecutionEventRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    WarehouseExecutionEventRow.entity_ref
                    == context["scope"]["entity_ref"],
                    WarehouseExecutionEventRow.store_ref
                    == context["scope"]["store_ref"],
                    WarehouseExecutionEventRow.warehouse_ref
                    == context["scope"]["warehouse_ref"],
                    WarehouseExecutionEventRow.aggregate_ref
                    == aggregate_ref,
                )
                .order_by(
                    WarehouseExecutionEventRow.sequence.desc(),
                    WarehouseExecutionEventRow.id.desc(),
                )
                .limit(1)
            )
            expected = 1 if latest is None else latest.sequence + 1
            if sequence != expected:
                raise ValueError(
                    f"Warehouse aggregate sequence must be {expected}"
                )
            if latest is not None and effective < self._aware(
                latest.effective_at
            ):
                raise ValueError("Warehouse event time moved backwards")
            row = WarehouseExecutionEventRow(
                id=new_id("whev"),
                source_event_ref=source_event_ref,
                aggregate_ref=aggregate_ref,
                sequence=sequence,
                event_type=event_type,
                order_external_id=order_external_id,
                product_id=product_id,
                sku=sku,
                quantity=quantity,
                weight_kg=normalized_weight,
                weight_source=normalized_weight_source,
                evidence_id=evidence.id,
                source_payload_sha256=source_payload_sha256,
                payload_sha256=payload_sha256,
                effective_at=effective,
                recorded_at=datetime.now(UTC),
                created_by=principal.actor_id,
                source_evidence_sha256=evidence.sha256,
                scope_as_of=context["cutoff"],
                **normalized,
                **governance,
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
        warehouse_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
        order_external_id: str | None = None,
        max_events: int = 50_000,
    ) -> dict[str, Any]:
        context = self._read_context(
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            warehouse_ref=warehouse_ref,
            scope_grant_authority_sha256=scope_grant_authority_sha256,
            as_of=as_of,
        )
        if not 1 <= max_events <= 100_000:
            raise ValueError("max_events must be between 1 and 100000")
        query = select(WarehouseExecutionEventRow).where(
            WarehouseExecutionEventRow.tenant_ref
            == context["scope"]["tenant_ref"],
            WarehouseExecutionEventRow.entity_ref
            == context["scope"]["entity_ref"],
            WarehouseExecutionEventRow.store_ref
            == context["scope"]["store_ref"],
            WarehouseExecutionEventRow.warehouse_ref
            == context["scope"]["warehouse_ref"],
            WarehouseExecutionEventRow.scope_grant_authority_sha256
            == context["scope"]["scope_grant_authority_sha256"],
            WarehouseExecutionEventRow.effective_at <= context["cutoff"],
            WarehouseExecutionEventRow.recorded_at <= context["cutoff"],
            WarehouseExecutionEventRow.scope_as_of <= context["cutoff"],
        )
        normalized_order = str(order_external_id or "").strip()
        if normalized_order:
            query = query.where(
                WarehouseExecutionEventRow.order_external_id
                == normalized_order
            )
        query = query.order_by(
            WarehouseExecutionEventRow.effective_at,
            WarehouseExecutionEventRow.recorded_at,
            WarehouseExecutionEventRow.id,
        ).limit(max_events + 1)
        with Session(self.engine) as session:
            rows = list(session.scalars(query).all())
        payload = {
            "contract_id": self.SOURCE_CONTRACT_ID,
            "status": "ready" if rows else "no_data",
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "events": [
                self._event_source(row) for row in rows[:max_events]
            ],
            "truncated": len(rows) > max_events,
            "source_gaps": (
                []
                if rows
                else ["warehouse_execution_event_missing"]
            ),
            "control_envelope": {
                "append_only_authority": True,
                "legacy_warehouse_rows_read": 0,
                "private_erp_interface_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def validate_event(
        self,
        *,
        event: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, Any],
        as_of: datetime,
    ) -> list[str]:
        """Revalidate current Evidence and immutable normalized payload."""

        context = {
            "cutoff": as_of,
            "scope": {
                key: scope[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                    "warehouse_ref",
                    "scope_grant_authority_sha256",
                )
            },
        }
        evidence = self._require_source_evidence(
            evidence_id=str(event.get("evidence_id") or ""),
            event_type=str(event.get("event_type") or ""),
            source_event_ref=str(event.get("source_event_ref") or ""),
            aggregate_ref=str(event.get("aggregate_ref") or ""),
            order_external_id=str(
                event.get("order_external_id") or ""
            ),
            product_id=str(event.get("product_id") or ""),
            sku=str(event.get("sku") or ""),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        governance = {
            field: event.get(field)
            for field in (
                "approval_id",
                "command_id",
                "receipt_id",
                "kill_switch_evidence_id",
                "compensation_evidence_id",
            )
        }
        if event.get("event_type") in self.GOVERNED_EVENTS:
            self._require_governance_evidence(
                governance=governance,
                event_type=str(event["event_type"]),
                source_event_ref=str(event.get("source_event_ref") or ""),
                order_external_id=str(
                    event.get("order_external_id") or ""
                ),
                effective_at=parse_timestamp(
                    str(event.get("effective_at") or ""),
                    "effective_at",
                ),
                source_evidence=evidence,
                context=context,
                principal=principal,
                entity_scope=entity_scope,
            )
        payload = {
            "contract_id": self.EVENT_CONTRACT_ID,
            "source_event_ref": event.get("source_event_ref"),
            "aggregate_ref": event.get("aggregate_ref"),
            "sequence": event.get("sequence"),
            "event_type": event.get("event_type"),
            "order_external_id": event.get("order_external_id"),
            "product_id": event.get("product_id"),
            "sku": event.get("sku"),
            **{
                field: event.get(field)
                for field in (
                    "location_ref",
                    "bin_ref",
                    "lot_ref",
                    "wave_ref",
                    "parcel_ref",
                    "label_ref",
                    "carrier_ref",
                    "service_ref",
                )
            },
            "quantity": event.get("quantity"),
            "weight_kg": event.get("weight_kg"),
            "weight_source": event.get("weight_source"),
            "evidence_id": evidence.id,
            "evidence_sha256": evidence.sha256,
            **governance,
            "effective_at": event.get("effective_at"),
            "scope": context["scope"],
        }
        issues = []
        if self._hash(payload) != event.get("payload_sha256"):
            issues.append("warehouse_event_payload_hash_drift")
        if evidence.sha256 != event.get("source_evidence_sha256"):
            issues.append("warehouse_event_evidence_hash_drift")
        if (
            evidence.metadata.get("event_payload_sha256")
            != event.get("source_payload_sha256")
        ):
            issues.append("warehouse_source_payload_hash_drift")
        return issues

    def _require_source_evidence(
        self,
        *,
        evidence_id: str,
        event_type: str,
        source_event_ref: str,
        aggregate_ref: str,
        order_external_id: str,
        product_id: str,
        sku: str,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
    ):
        record = self._require_exact_evidence(
            evidence_id=evidence_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        metadata = record.metadata
        source_kind = str(metadata.get("source_kind") or "")
        authorization_id = str(
            metadata.get("authorization_evidence_id") or ""
        )
        if (
            metadata.get("contract_id")
            != self.SOURCE_EVIDENCE_CONTRACT_ID
            or source_kind not in self.SOURCE_KINDS
            or not str(metadata.get("adapter_id") or "").strip()
            or not str(metadata.get("adapter_version") or "").strip()
            or not authorization_id
            or metadata.get("immutable") is not True
            or metadata.get("revoked") is not False
            or metadata.get("tenant_ref")
            != context["scope"]["tenant_ref"]
            or metadata.get("entity_ref")
            != context["scope"]["entity_ref"]
            or metadata.get("store_ref")
            != context["scope"]["store_ref"]
            or metadata.get("warehouse_ref")
            != context["scope"]["warehouse_ref"]
            or metadata.get("source_event_ref") != source_event_ref
            or metadata.get("aggregate_ref") != aggregate_ref
            or metadata.get("event_type") != event_type
            or metadata.get("order_external_id") != order_external_id
            or metadata.get("product_id") != product_id
            or metadata.get("sku") != sku
            or not self._sha256(
                str(metadata.get("event_payload_sha256") or "")
            )
        ):
            raise ValueError(
                "Warehouse event Evidence authority binding is invalid"
            )
        authorization = self._require_exact_evidence(
            evidence_id=authorization_id,
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        auth = authorization.metadata
        if (
            auth.get("contract_id") != self.AUTHORIZATION_CONTRACT_ID
            or auth.get("status") != "authorized"
            or auth.get("revoked") is not False
            or auth.get("source_kind") != source_kind
            or auth.get("adapter_id") != metadata.get("adapter_id")
            or auth.get("adapter_version")
            != metadata.get("adapter_version")
            or auth.get("tenant_ref") != context["scope"]["tenant_ref"]
            or auth.get("entity_ref") != context["scope"]["entity_ref"]
            or auth.get("store_ref") != context["scope"]["store_ref"]
            or auth.get("warehouse_ref")
            != context["scope"]["warehouse_ref"]
        ):
            raise ValueError(
                "Warehouse adapter authorization Evidence is invalid"
            )
        return record

    def _require_governance_evidence(
        self,
        *,
        governance: dict[str, str | None],
        event_type: str,
        source_event_ref: str,
        order_external_id: str,
        effective_at: datetime,
        source_evidence,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
    ) -> None:
        action_id = self.GOVERNED_ACTION_IDS[event_type]
        metadata = source_evidence.metadata
        if (
            metadata.get("governed_action_id") != action_id
            or metadata.get("approval_id") != governance["approval_id"]
            or metadata.get("permit_evidence_id")
            != governance["command_id"]
            or metadata.get("readback_evidence_id")
            != governance["receipt_id"]
            or metadata.get("kill_switch_evidence_id")
            != governance["kill_switch_evidence_id"]
            or metadata.get("compensation_evidence_id")
            != governance["compensation_evidence_id"]
        ):
            raise ValueError(
                "Warehouse governed Readback source binding is invalid"
            )
        self._require_independent_approval(
            approval_id=str(governance["approval_id"]),
            action_id=action_id,
            event_type=event_type,
            source_event_ref=source_event_ref,
            order_external_id=order_external_id,
            context=context,
        )
        permit = self._require_exact_evidence(
            evidence_id=str(governance["command_id"]),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        permit_metadata = permit.metadata
        issued_at = parse_timestamp(
            str(permit_metadata.get("issued_at") or ""),
            "permit issued_at",
        )
        expires_at = parse_timestamp(
            str(permit_metadata.get("expires_at") or ""),
            "permit expires_at",
        )
        if (
            permit_metadata.get("contract_id")
            != self.PERMIT_CONTRACT_ID
            or permit_metadata.get("status") != "issued"
            or permit_metadata.get("revoked") is not False
            or permit_metadata.get("single_use") is not True
            or permit_metadata.get("approval_id")
            != governance["approval_id"]
            or permit_metadata.get("action_id") != action_id
            or permit_metadata.get("event_type") != event_type
            or permit_metadata.get("source_event_ref")
            != source_event_ref
            or permit_metadata.get("order_external_id")
            != order_external_id
            or issued_at > effective_at
            or expires_at < effective_at
        ):
            raise ValueError(
                "Warehouse one-time Permit Evidence is invalid"
            )
        readback = self._require_exact_evidence(
            evidence_id=str(governance["receipt_id"]),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
        )
        readback_metadata = readback.metadata
        readback_at = parse_timestamp(
            str(readback_metadata.get("readback_at") or ""),
            "readback_at",
        )
        if (
            readback_metadata.get("contract_id")
            != self.READBACK_CONTRACT_ID
            or readback_metadata.get("outcome") != "succeeded"
            or readback_metadata.get("mutation_applied") is not True
            or readback_metadata.get("approval_id")
            != governance["approval_id"]
            or readback_metadata.get("permit_evidence_id")
            != governance["command_id"]
            or readback_metadata.get("action_id") != action_id
            or readback_metadata.get("event_type") != event_type
            or readback_metadata.get("source_event_ref")
            != source_event_ref
            or readback_metadata.get("order_external_id")
            != order_external_id
            or readback_metadata.get("adapter_id")
            != metadata.get("adapter_id")
            or readback_metadata.get("adapter_version")
            != metadata.get("adapter_version")
            or not str(
                readback_metadata.get("remote_operation_id") or ""
            ).strip()
            or not self._sha256(
                str(
                    readback_metadata.get(
                        "resulting_state_sha256"
                    )
                    or ""
                )
            )
            or readback_at != effective_at
        ):
            raise ValueError(
                "Warehouse successful Readback Evidence is invalid"
            )
        expected = {
            "kill_switch_evidence_id": "kill_switch_release",
            "compensation_evidence_id": "warehouse_compensation_plan",
        }
        for field, purpose in expected.items():
            record = self._require_exact_evidence(
                evidence_id=str(governance[field]),
                context=context,
                principal=principal,
                entity_scope=entity_scope,
            )
            metadata = record.metadata
            if (
                metadata.get("purpose") != purpose
                or metadata.get("status") not in {"released", "ready"}
                or metadata.get("event_type") != event_type
                or metadata.get("action_id") != action_id
                or metadata.get("approval_id")
                != governance["approval_id"]
                or metadata.get("permit_evidence_id")
                != governance["command_id"]
                or metadata.get("readback_evidence_id")
                != governance["receipt_id"]
                or metadata.get("source_event_ref")
                != source_event_ref
                or metadata.get("order_external_id")
                != order_external_id
                or not str(metadata.get("owner") or "").strip()
            ):
                raise ValueError(
                    f"{field} is not bound to this warehouse Readback"
                )
        with Session(self.engine) as session:
            reused = session.scalar(
                select(WarehouseExecutionEventRow.id).where(
                    WarehouseExecutionEventRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    WarehouseExecutionEventRow.entity_ref
                    == context["scope"]["entity_ref"],
                    WarehouseExecutionEventRow.store_ref
                    == context["scope"]["store_ref"],
                    WarehouseExecutionEventRow.warehouse_ref
                    == context["scope"]["warehouse_ref"],
                    WarehouseExecutionEventRow.source_event_ref
                    != source_event_ref,
                    (
                        WarehouseExecutionEventRow.command_id
                        == governance["command_id"]
                    )
                    | (
                        WarehouseExecutionEventRow.receipt_id
                        == governance["receipt_id"]
                    ),
                )
            )
        if reused is not None:
            raise ValueError(
                "Warehouse Permit or Readback Evidence was already consumed"
            )

    def _require_independent_approval(
        self,
        *,
        approval_id: str,
        action_id: str,
        event_type: str,
        source_event_ref: str,
        order_external_id: str,
        context: dict[str, Any],
    ) -> None:
        with Session(self.engine) as session:
            approval = session.get(ApprovalRow, approval_id)
        scope = context["scope"]
        payload = approval.payload_json if approval is not None else {}
        if (
            approval is None
            or approval.status != "approved"
            or not approval.decided_by
            or approval.requested_by == approval.decided_by
            or approval.action != action_id
            or approval.resource_type != "warehouse_order"
            or approval.resource_id != order_external_id
            or payload.get("tenant_ref") != scope["tenant_ref"]
            or payload.get("entity_ref") != scope["entity_ref"]
            or payload.get("store_ref") != scope["store_ref"]
            or payload.get("warehouse_ref") != scope["warehouse_ref"]
            or payload.get("order_external_id") != order_external_id
            or payload.get("event_type") != event_type
            or payload.get("source_event_ref") != source_event_ref
            or payload.get("scope_grant_authority_sha256")
            != scope["scope_grant_authority_sha256"]
        ):
            raise ValueError(
                "Warehouse independent Approval authority is invalid"
            )

    def _require_exact_evidence(
        self,
        *,
        evidence_id: str,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
    ):
        evidence_id = self._required(evidence_id, "evidence_id", 240)
        self.evidence.require_current(
            [evidence_id],
            as_of=context["cutoff"],
        )
        record = self.evidence.get(evidence_id)
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
            raise ValueError("Warehouse Evidence is not exact-scope ready")
        return record

    def _require_product(
        self,
        *,
        product_id: str,
        sku: str,
        context: dict[str, Any],
    ) -> None:
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
                or self._aware(product.scope_as_of) > context["cutoff"]
                or self._aware(product.created_at) > context["cutoff"]
            ):
                raise ValueError(
                    "Warehouse Product/SKU authority is invalid"
                )

    @classmethod
    def _context(
        cls,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        warehouse_ref: str,
        as_of: str | None,
    ) -> dict[str, Any]:
        store = cls._required(store_ref, "store_ref", 160)
        warehouse = cls._required(
            warehouse_ref,
            "warehouse_ref",
            160,
        )
        if not principal.can_access_store(store):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = str(
            entity_scope.get("authority_sha256") or ""
        ).strip().lower()
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
                "warehouse_ref": warehouse,
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
        warehouse_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
    ) -> dict[str, Any]:
        authority = str(scope_grant_authority_sha256 or "").lower()
        if not cls._sha256(authority):
            raise ValueError(
                "scope_grant_authority_sha256 must be SHA-256"
            )
        return {
            "cutoff": parse_timestamp(as_of, "as_of"),
            "scope": {
                "tenant_ref": cls._required(
                    tenant_ref,
                    "tenant_ref",
                    160,
                ),
                "entity_ref": cls._required(
                    entity_ref,
                    "entity_ref",
                    160,
                ),
                "store_ref": cls._required(
                    store_ref,
                    "store_ref",
                    160,
                ),
                "warehouse_ref": cls._required(
                    warehouse_ref,
                    "warehouse_ref",
                    160,
                ),
                "scope_grant_authority_sha256": authority,
            },
        }

    @classmethod
    def _event(
        cls,
        row: WarehouseExecutionEventRow,
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {**cls._event_source(row), "idempotent": idempotent}

    @classmethod
    def _event_source(
        cls,
        row: WarehouseExecutionEventRow,
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_event_ref": row.source_event_ref,
            "aggregate_ref": row.aggregate_ref,
            "sequence": row.sequence,
            "event_type": row.event_type,
            "order_external_id": row.order_external_id,
            "product_id": row.product_id,
            "sku": row.sku,
            "location_ref": row.location_ref,
            "bin_ref": row.bin_ref,
            "lot_ref": row.lot_ref,
            "wave_ref": row.wave_ref,
            "parcel_ref": row.parcel_ref,
            "label_ref": row.label_ref,
            "quantity": row.quantity,
            "weight_kg": row.weight_kg,
            "weight_source": row.weight_source,
            "carrier_ref": row.carrier_ref,
            "service_ref": row.service_ref,
            "evidence_id": row.evidence_id,
            "source_evidence_sha256": row.source_evidence_sha256,
            "source_payload_sha256": row.source_payload_sha256,
            "payload_sha256": row.payload_sha256,
            "approval_id": row.approval_id,
            "command_id": row.command_id,
            "receipt_id": row.receipt_id,
            "kill_switch_evidence_id": row.kill_switch_evidence_id,
            "compensation_evidence_id": row.compensation_evidence_id,
            "effective_at": cls._aware(row.effective_at).isoformat(),
            "recorded_at": cls._aware(row.recorded_at).isoformat(),
            "created_by": row.created_by,
            "scope_as_of": cls._aware(row.scope_as_of).isoformat(),
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "warehouse_ref": row.warehouse_ref,
                "scope_grant_authority_sha256": (
                    row.scope_grant_authority_sha256
                ),
            },
        }

    @staticmethod
    def _required(value: Any, field: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > limit:
            raise ValueError(f"{field} must be 1 to {limit} characters")
        return normalized

    @classmethod
    def _optional(
        cls,
        value: str | None,
        field: str,
        limit: int = 240,
    ) -> str | None:
        if value is None or not str(value).strip():
            return None
        return cls._required(value, field, limit)

    @classmethod
    def _choice(
        cls,
        value: str,
        field: str,
        allowed: frozenset[str],
    ) -> str:
        normalized = cls._required(value, field, 80).lower()
        if normalized not in allowed:
            raise ValueError(f"{field} is unsupported")
        return normalized

    @staticmethod
    def _weight(value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        try:
            decimal = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("weight_kg must be a positive decimal") from exc
        if not decimal.is_finite() or decimal <= 0:
            raise ValueError("weight_kg must be a positive decimal")
        return format(decimal.normalize(), "f")

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _sha256(value: str) -> bool:
        value = str(value or "").strip().lower()
        return len(value) == 64 and all(
            char in "0123456789abcdef" for char in value
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
            ).encode()
        ).hexdigest()
